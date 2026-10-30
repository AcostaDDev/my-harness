"""Explicit local supervisor H2.2/H2.3, without managed HTTP/CLI entry points.

Each run_once claims at most one job. Several calls may work on
different checkouts; the database decides idempotency and exclusion. Only the heartbeat
uses a thread and it never holds an SQL session during engine calls.
"""

from dataclasses import asdict, replace
import json
from threading import Event, Thread
from uuid import uuid4

from my_harness.core.engine.commit import MechanicalUpdate, commit_accepted
from my_harness.core.engine.contracts import stop_history
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.serialization import restore_context
from my_harness.core.engine.workflow import OfflineEngine
from my_harness.i18n import emission, tr
from my_harness.storage.managed import OwnershipLost


class _Journal:
    def __init__(self, repository, claim, heartbeat_failed, renewal=None):
        self.repository = repository
        self.claim = claim
        self.heartbeat_failed = heartbeat_failed
        self.renewal = renewal if renewal is not None else {'failures': 0, 'last_error': None, 'lost': False}

    def cancel_requested(self):
        # Read persisted revocation/expiry; the adapter owns live handles, signalling and reconciliation.
        from sqlalchemy.orm import Session
        lifecycle = getattr(self.repository, 'permission_lifecycle', None)
        if lifecycle is None:
            return False
        with Session(self.repository.engine) as session:
            return lifecycle.cancelled(session, self.claim.run_id)

    def command_cancel_requested(self, command_id):
        from sqlalchemy.orm import Session
        lifecycle = getattr(self.repository, 'permission_lifecycle', None)
        if lifecycle is None:
            return False
        with Session(self.repository.engine) as session:
            return lifecycle.cancelled(session, self.claim.run_id, command_id=command_id, job_id=self.claim.id)

    def _renewal_error(self):
        return tr('supervisor.heartbeat_failed_stop_before', failures=self.renewal['failures'],
                  error=self.renewal['last_error'] or 'OwnershipLost')

    def _call(self, operation, *args):
        if self.heartbeat_failed.is_set():
            raise JournalError(self._renewal_error())
        try:
            return operation(self.claim, *args)
        except Exception as exc:
            if isinstance(exc, OwnershipLost) and (self.renewal['failures'] or self.renewal['lost']):
                self.renewal['lost'] = True
                raise JournalError(self._renewal_error()) from exc
            raise JournalError(tr('supervisor.managed_persistence_failed', exc=exc)) from exc

    def checkpoint(self, history, stage):
        self._call(self.repository.checkpoint, history, stage)

    def agent_started(self, history, request):
        return self._call(self.repository.agent_started, history, request)

    def process_intent(self, attempt_id, spec):
        self._call(self.repository.process_intent, attempt_id, spec)

    def compatibility_refused(self, reports):
        self._call(self.repository.effect, 'cli_preflight_refused', reports)

    def process_update(self, attempt_id, kind, payload):
        self._call(self.repository.process_update, attempt_id, kind, payload)

    def process_updates(self, attempt_id, items):
        self._call(self.repository.process_updates, attempt_id, items)

    def command_process_event(self, command_id, kind, payload):
        self._call(self.repository.command_process_event, command_id, kind, payload)

    def pending_commit(self):
        return self._call(self.repository.pending_commit)

    def commit_intent(self, intent):
        self._call(self.repository.commit_intent, intent)

    def commit_result(self, outcome):
        self._call(self.repository.commit_result, outcome)

    def commit_invalidated(self, outcome):
        self._call(self.repository.commit_invalidated, outcome)

    def tag_intent(self, intent):
        self._call(self.repository.tag_intent, intent)

    def export_intent(self, intent):
        self._call(self.repository.export_intent, intent)

    def document_intent(self, intent):
        self._call(self.repository.document_intent, intent)

    def command_started(self, command):
        identity = str(uuid4())
        self._call(self.repository.effect, "command_started", {"command_id": identity, "command": asdict(command)})
        return identity

    def command_finished(self, identity, result):
        from my_harness.core.engine.validation import command_result_payload
        self._call(self.repository.effect, "command_finished", {"command_id": identity, "result": command_result_payload(result)})


class _DocumentsJournal:
    """D072: adopts the managed block hashes in the same transaction that records the commit.

    The intent (new or pending reconciliation) fixes which blocks the harness wrote; their previous
    hashes are read from the base revision, so resuming adopts the same thing."""

    def __init__(self, journal, writer, context):
        self.journal, self.writer, self.context = journal, writer, context
        self.intent = None

    def __getattr__(self, name):
        return getattr(self.journal, name)

    def pending_commit(self):
        self.intent = self.journal.pending_commit()
        return self.intent

    def commit_intent(self, intent):
        self.journal.commit_intent(intent)
        self.intent = intent

    def commit_result(self, outcome):
        adopt = None
        if outcome.status != "invalidated" and self.intent is not None:
            from my_harness.storage.documents import block_adoption
            adopt = block_adoption(self.context, self.intent, self.writer)
        self.journal._call(self.journal.repository.commit_result, outcome, adopt)


def _bind_commands(commands, journal, versions):
    """A run frozen for native validators never executes through another runner."""
    if hasattr(commands, "bind_process_journal"):
        commands.bind_process_journal(journal)
    elif "command_config_sha256" in versions:
        raise JournalError("Run has a frozen native command configuration; its managed runner is required")


def guarded_writer(factory, guard):
    """Bind Git evidence to the installation's mode authority, including D099's local marker."""
    if factory is None:
        return None
    def create(context, versions):
        from my_harness.storage.managed_mode import bind_git_mode
        return bind_git_mode(factory(context, versions), guard)
    return create


class LocalSupervisor:
    def __init__(self, repository, ports_factory, *, lease_seconds=30, commit_factory=None, lane=None):
        """factory(context, frozen_versions) returns agents, commands and evidence.

        The H2.3 CLI ports are connected only by explicit injection. The selection/versions are explicit;
        the factory must reject them if it lacks the frozen implementation.
        It is not a self-starting service. `commit_factory(context, frozen_versions)` provides the
        Git writer (capture + idempotent commit) only for jobs with the `commit` action.
        """
        self.lane = lane
        self.repository = repository
        def ports(context, versions):
            from my_harness.storage.managed_mode import bind_git_mode
            agents, commands, evidence = ports_factory(context, versions)
            return agents, commands, bind_git_mode(evidence, repository.guard)
        self.ports_factory = ports
        self.commit_factory = guarded_writer(commit_factory, repository.guard)
        self.lease_seconds = lease_seconds

    def run_once(self):
        self.repository.recover_expired()
        # H3.4: the unattended batch queues its next step before claiming; it never checks or closes.
        from my_harness.storage.phases import advance_batches
        if self.lane != "chat":
            advance_batches(self.repository)
        claim = self.repository.claim(lease_seconds=self.lease_seconds, lane=self.lane)
        if claim is None:
            return None
        # P011-T021: own texts of this job use the visual language frozen at its admission (D166).
        with emission(lambda: self.repository.job_visual(claim)):
            return self._run_claimed(claim)

    def _run_claimed(self, claim):
        retired = self.repository.retired_reason(claim.run_id, claim.request_json)
        if retired is not None:
            self.repository.quarantine(claim, retired)
            return replace(claim, status="RECOVERY_REQUIRED")
        # H2.5: before any effect. Legacy writer, marker or changed mode → REFUSED.
        refusal = self.repository.mode_refusal(claim)
        if refusal is not None:
            self.repository.refuse(claim, refusal)
            return replace(claim, status="REFUSED")
        stopped, heartbeat_failed = Event(), Event()
        renewal = {'failures': 0, 'last_error': None, 'lost': False}

        def heartbeat():
            interval = self.lease_seconds / 3
            wait = interval
            while not stopped.wait(wait):
                try:
                    self.repository.heartbeat(claim, lease_seconds=self.lease_seconds)
                    wait = interval
                except OwnershipLost:
                    renewal['lost'] = True
                    heartbeat_failed.set()
                    return
                except Exception as exc:
                    # D252: retry renewal within the existing lease; every effect still checks ownership.
                    renewal['failures'] += 1
                    renewal['last_error'] = type(exc).__name__
                    wait = min(interval, 1.0)

        thread = Thread(target=heartbeat, name=f"managed-heartbeat-{claim.id}", daemon=True)
        thread.start()
        agents = None
        owner_closed = False
        try:
            from my_harness.adapters.processes import identity
            self.repository.register_owner(claim, identity())
            record = self.repository.get_run(claim.run_id)
            context = restore_context(record.history.context_json)
            journal = _Journal(self.repository, claim, heartbeat_failed, renewal)
            request = json.loads(claim.request_json)
            versions = json.loads(record.versions_json)
            language = self.repository.job_language(claim)  # D169: only the pair sealed at admission
            outcome = None
            if request["action"] == "bootstrap_discovery":
                from my_harness.core.engine.bootstrap_discovery import execute
                from my_harness.storage.bootstrap_discovery import DiscoveryRepository
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.bootstrap_discovery_requires_configured'))
                writer = self.commit_factory(context, versions)
                agents, _, _ = self.ports_factory(context, versions)
                if hasattr(agents, 'bind_process_journal'):
                    agents.bind_process_journal(journal)
                history, outcome = execute(context, record.history,
                    DiscoveryRepository(self.repository).request(claim.run_id), agents, writer, journal)
            elif request["action"] == "import_commit":
                from my_harness.core.engine.import_commit import execute
                from my_harness.storage.project_import import ImportRepository, check_git
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.import_requires_configured_git'))
                writer = self.commit_factory(context, versions)
                saved = ImportRepository(self.repository).request(claim.run_id)
                check_git(context, writer, saved['preview'], json.loads(saved['intent'])['expected_tree'])
                history, outcome = execute(context, record.history, saved, writer, journal)
            elif request["action"] == "bootstrap":
                from my_harness.core.engine.bootstrap import execute
                from my_harness.storage.bootstrap import BootstrapRepository
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.bootstrap_requires_configured_git'))
                writer = self.commit_factory(context, versions)
                self.repository._require_mode(claim)
                history, outcome = execute(context, record.history,
                    BootstrapRepository(self.repository).request(claim.run_id), writer, journal)
            elif request["action"] == "document_export":
                from my_harness.core.engine.document_export import execute
                from my_harness.storage.document_export import DocumentExportRepository
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.document_export_requires_configured'))
                writer = self.commit_factory(context, versions)
                frozen = DocumentExportRepository(self.repository).request(claim.run_id)
                # On resume the intent already exists; the guard is checked again before the effect.
                self.repository._require_mode(claim)
                history, outcome = execute(context, record.history, frozen, writer, journal, self.repository.clock)
            elif request["action"] in ("document_edit", "phase_transition"):
                # D072: confirmed edit or phase transition; no agents, intent before writing.
                from my_harness.core.engine.document_ops import execute
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.document_operations_require_configured'))
                if request["action"] == "document_edit":
                    writer = self.commit_factory(context, versions)
                    from my_harness.storage.documents import DocumentsRepository
                    frozen = DocumentsRepository(self.repository).request(claim.run_id)
                    label = "confirm document edit"
                else:
                    from my_harness.storage.transition import TransitionRepository
                    from my_harness.core.engine.documents import DOCUMENT_LAYOUT
                    frozen = TransitionRepository(self.repository).request(claim.run_id)
                    writer_versions = versions
                    if (frozen.get('commit_intent')
                            and versions.get('document_layout') in ('d088-1', 'd088-2', 'd088-3')):
                        writer_versions = {**versions, 'document_layout': DOCUMENT_LAYOUT}
                    writer = self.commit_factory(context, writer_versions)
                    shown = frozen["preview"]
                    label = f"archive {shown['closed']}" + (f" and open {shown['next']['code']}" if shown["next"] else "")
                self.repository._require_mode(claim)
                history, outcome = execute(context, record.history, frozen, writer, journal, self.repository.clock,
                                           label=label)
            elif request["action"] == "chat_command":
                from my_harness.storage.chat import ChatRepository
                frozen = ChatRepository(self.repository).snapshot(claim.run_id)
                from my_harness.core.engine.chat import digest, validate_chat_result
                if digest(frozen['context']) != frozen['context_sha256']:
                    raise ValueError('Frozen deterministic command context changed')
                result = validate_chat_result(frozen['context']['command_result'])
                history = replace(record.history, status="completed", stop=None)
                outcome = {"status": "ANSWERED", "reasons": [], "result": result,
                           "checkout": None}
            elif request["action"] in ("chat_turn", "chat_snapshot"):
                # E5 exports HEAD for new turns; H4.1 jobs retain their original checkout semantics.
                from my_harness.core.engine.chat import chat_turn
                from my_harness.storage.chat import ChatRepository
                from my_harness.storage.prompts import PromptRepository
                agents, _, evidence = self.ports_factory(context, versions)
                if hasattr(agents, "bind_process_journal"):
                    agents.bind_process_journal(journal)
                frozen = ChatRepository(self.repository).snapshot(claim.run_id)
                catalog = PromptRepository(self.repository.engine).catalog(context)
                if request['action'] == 'chat_snapshot':
                    from my_harness.adapters.chat_snapshot import HeadSnapshot, snapshot_path
                    destination = snapshot_path(self.repository, claim)
                    journal._call(self.repository.effect, 'chat_snapshot_intent', {
                        'head': frozen['context']['head'], 'format': 'head-export-1', 'path': str(destination)})
                    reader = HeadSnapshot(context.root, executable=getattr(evidence, 'executable', 'git'))
                    evidence = reader.export(frozen['context']['head'], destination)
                    context = replace(context, root=destination)
                history, outcome = chat_turn(context, record.history, frozen, agents, evidence, journal, catalog,
                                             language)
            elif request["action"] == "planning_turn":
                # H6.5: definition or phase planning turn, read-only and with a frozen request.
                from my_harness.core.engine.definition import planning_turn
                from my_harness.storage.planning import PlanningRepository
                from my_harness.storage.prompts import PromptRepository
                snapshot = PlanningRepository(self.repository).snapshot(claim.run_id)
                agents, _, evidence = self.ports_factory(context, versions)
                catalog = PromptRepository(self.repository.engine).catalog(context)
                if hasattr(agents, "bind_process_journal"):
                    agents.bind_process_journal(journal)
                if snapshot["kind"] == "definition":
                    if self.commit_factory is None:
                        raise RuntimeError(tr('supervisor.definition_turns_require_configured'))
                    reader = self.commit_factory(context, versions)

                    def observe():
                        return reader.inspect_definition(context)
                elif snapshot["kind"] == "onboarding":
                    from my_harness.adapters.chat_snapshot import snapshot_path
                    from my_harness.storage.onboarding import OnboardingDrafts, export_snapshot, observation
                    area = OnboardingDrafts.of(self.repository.engine, snapshot['conversation_id'])
                    destination = snapshot_path(self.repository, claim)
                    head = snapshot['context']['head']
                    journal._call(self.repository.effect, 'onboarding_snapshot_intent', {
                        'head': head, 'format': 'head-export-1', 'path': str(destination)})
                    reader = self.commit_factory(context, versions) if self.commit_factory is not None else None
                    from my_harness.core.engine.context import IntakeContext
                    if isinstance(context, IntakeContext):
                        from my_harness.storage.onboarding import read_inventory
                        if read_inventory(context, getattr(reader, 'executable', 'git')) != snapshot['context']['inventory']:
                            reason = tr('profile_proposal.stale')
                            history = stop_history(record.history, 'onboarding', reason)
                            outcome = {'status': 'FAILED', 'reasons': [reason], 'result': None, 'observed': None}
                    if outcome is None:
                        evidence = export_snapshot(context.root, head, destination, getattr(reader, 'executable', 'git'))
                        context = replace(context, root=destination)

                    def observe():
                        return {**observation(area.inspect_definition(context)),
                                'snapshot': evidence.capture(context).fingerprint}
                else:
                    def observe():
                        captured = evidence.capture(context)
                        return {"base_revision": captured.base_revision, "fingerprint": captured.fingerprint}
                if outcome is None:
                    from my_harness.services.profile_proposal import validate as validate_profile
                    history, outcome = planning_turn(context, record.history, snapshot, agents, observe, journal,
                                                     catalog, language, profile_validator=validate_profile)
            elif request["action"] in ("phase_check", "phase_close"):
                # D088: check and closure under the lock; the closure includes the documentary archive.
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.phase_operations_require_configured'))
                from my_harness.core.engine.phases import check_phase, close_phase
                from my_harness.storage.phases import PhaseRepository
                git = self.commit_factory(context, versions)
                snapshot = PhaseRepository(self.repository).snapshot(claim.run_id)
                if request["action"] == "phase_close":
                    history, outcome = close_phase(context, record.history, snapshot, git, journal,
                                                   now=self.repository.clock)
                else:
                    agents, commands, _ = self.ports_factory(context, versions)
                    _bind_commands(commands, journal, versions)
                    if hasattr(agents, "bind_process_journal"):
                        agents.bind_process_journal(journal)
                    from my_harness.storage.prompts import PromptRepository
                    history, outcome = check_phase(context, record.history, snapshot, agents, commands, git, journal,
                                                   PromptRepository(self.repository.engine).catalog(context),
                                                   language)
            elif request["action"] == "commit":
                if self.commit_factory is None:
                    raise RuntimeError(tr('supervisor.no_commit_writer_configured'))
                writer = self.commit_factory(context, versions)
                updates = tuple(MechanicalUpdate(**item) for item in request["mechanical"])
                history, blocks, committer = None, frozenset(), journal
                if context.documents is not None:
                    # D072: managed blocks regenerated over what was reviewed, in the same commit.
                    committer = _DocumentsJournal(journal, writer, context)
                    if journal.pending_commit() is None:
                        from my_harness.storage.documents import task_commit_updates
                        try:
                            extra, blocks = task_commit_updates(self.repository, context, claim.run_id, record.history)
                            updates += extra
                        except (ValueError, OSError, UnicodeError) as exc:
                            history = stop_history(record.history, "commit",
                                                   tr('supervisor.managed_documentation_blocks_could', exc=exc))
                if history is None:
                    history, _ = commit_accepted(context, record.history, writer, committer, mechanical=updates,
                                                 now=self.repository.clock, block_paths=blocks)
            else:
                agents, commands, evidence = self.ports_factory(context, versions)
                _bind_commands(commands, journal, versions)
                if hasattr(agents, "bind_process_journal"):
                    agents.bind_process_journal(journal)
                from my_harness.storage.prompts import PromptRepository
                engine = OfflineEngine(agents, commands, evidence, journal,
                                       prompts=PromptRepository(self.repository.engine).catalog, language=language)
                if request["action"] == "start":
                    history = engine.start(context, request["task_id"], request["phase_id"], request["text"],
                                           history=record.history, contract=request.get("contract_json"),
                                           notes=request.get("notes"))
                else:
                    history = engine.resume(context, record.history, retry_executor=request["action"] == "retry")
            stopped.set()
            thread.join()
            self.repository.close_owner(claim, heartbeat=renewal)
            owner_closed = True
            journal._call(self.repository.finish, history, outcome)
            return replace(claim, status="DONE")
        except Exception as exc:
            # A persistence error also leaves intent and lock for reconciliation.
            self.repository.quarantine(claim, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if agents is not None and hasattr(agents, "close"):
                agents.close()
            stopped.set()
            thread.join()
            if not owner_closed:
                self.repository.close_owner(claim, heartbeat=renewal)
