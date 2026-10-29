"""H2.2 authority. Every writing transaction ends before running ports.

FIFO among eligible jobs, one writer per root within this database. The lease
does not release the checkout: an executor with an uncertain result requires reconciliation.
"""

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text, func, or_
from sqlalchemy.orm import Session

from my_harness.core.engine.commit import (
    CommitError, CommitIntent, CommitOutcome, MechanicalUpdate, git_provenance, validate_mechanical_updates,
)
from my_harness.core.engine.context import ProjectContext
from my_harness.core.engine.contracts import (
    AgentRequest, AgentResult, Attempt, RunHistory, context_snapshot, freeze, stop_history,
)
from my_harness.core.engine.serialization import dump_history, load_history, restore_context, restore_request
from my_harness.storage.models import (
    CheckoutLockRow as Lock, ManagedAttemptRow as AttemptRow, ManagedEventRow as Event,
    ManagedJobRow as Job, ManagedRunRow as Run, ManagedProcessRow as Process,
    ManagedCommitRow as Commit,
)
from my_harness.storage.managed_mode import ModeConflict, ModeGuard
from my_harness.storage.metrics import executor_round, record as record_metrics
from my_harness.storage.accounting import intend_attempt as intend_usage, settle_attempt as settle_usage
from my_harness.storage import operation_journal
from my_harness.storage import run_projection
from my_harness.storage.schema import require_schema
from my_harness.i18n import tr


class Conflict(ValueError):
    pass


class OwnershipLost(RuntimeError):
    pass


@dataclass(frozen=True)
class JobRecord:
    id: int
    run_id: str
    status: str
    request_json: str
    owner_token: str | None


@dataclass(frozen=True)
class RunRecord:
    history: RunHistory
    versions_json: str
    status: str
    stage: str
    version: int
    revisions: int


@dataclass(frozen=True)
class CommitRecord:
    operation_id: str
    run_id: str
    status: str
    intent: CommitIntent
    outcome: CommitOutcome | None
    commit: str | None


def _commit(row: Commit) -> CommitRecord:
    return CommitRecord(row.operation_id, row.run_id, row.status, CommitIntent.from_json(row.intent_json),
                        CommitOutcome.from_json(row.result_json) if row.result_json else None, row.commit_sha)


def _job(row: Job) -> JobRecord:
    return JobRecord(row.id, row.run_id, row.status, row.request_json, row.owner_token)


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(tr('managed.explicit_required', name=name))


def existing_creation(session, row_type, key, request_sha256):
    """Registration without a job (conversations, 0018): the same key and the same request return the same id."""
    _nonempty(key, "idempotency key")
    if len(key) > 200:
        raise ValueError(tr('managed.idempotency_key_exceeds_200'))
    row = session.scalar(select(row_type).where(row_type.idempotency_key == key))
    if row is not None and row.request_sha256 != request_sha256:
        raise Conflict(tr('managed.idempotency_key_already_names'))
    return None if row is None else row.id


def independent_chat(job):
    return json.loads(job.request_json).get('action') in ('chat_snapshot', 'chat_command')


def _operation_module(run):
    """Authority of the result of a non-task run: phase (H3.3) or chat turn (H4.1)."""
    if run.purpose == "project_import":
        from my_harness.storage import retired_work
        return retired_work
    if run.purpose == "bootstrap_discovery":
        from my_harness.storage import bootstrap_discovery
        return bootstrap_discovery
    if run.purpose == "import_commit":
        from my_harness.storage import project_import
        return project_import
    if run.purpose == "bootstrap":
        from my_harness.storage import bootstrap
        return bootstrap
    if run.purpose == "chat":
        from my_harness.storage import chat
        return chat
    if run.purpose == "document_export":
        from my_harness.storage import document_export
        return document_export
    if run.purpose == "document_edit":
        from my_harness.storage import documents
        return documents
    if run.purpose == "phase_transition":
        from my_harness.storage import transition
        return transition
    if run.purpose in ("definition", "phase_planning", "project_import", "onboarding"):
        from my_harness.storage import planning
        return planning
    from my_harness.storage import phases
    return phases


def _lease(seconds: float) -> None:
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Lease must be positive and finite")


class SQLiteManagedRepository:
    def __init__(self, engine, *, clock=None, mode_probe=None):
        require_schema(engine)
        self.engine = engine
        self.write_guard = None  # Optional service admission gate, checked under the SQLite barrier.
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        # H2.5: legacy/managed exclusion. Checkouts without legacy state do not change behavior.
        self.guard = ModeGuard(engine, mode_probe)

    def _now(self) -> str:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("Clock must return an aware UTC time")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")

    @contextmanager
    def _write(self):
        with Session(self.engine) as session, session.begin():
            # First DML operation: acquires the SQLite lock before querying.
            session.execute(text("UPDATE managed_runs SET version = version WHERE 0"))
            if self.write_guard is not None:
                self.write_guard(session)
            yield session

    def _event(self, session, run, kind, payload):
        run.version += 1
        run.updated_at = self._now()
        session.add(Event(run_id=run.id, sequence=run.version, kind=kind, recorded_at=run.updated_at,
                          payload={**payload, "status": run.status, "stage": run.stage,
                                   "revisions": run.revisions}))

    @staticmethod
    def _language(session, inherit_run: str | None = None, *, root: str | None = None) -> dict | None:
        """Language pair of a new job on `root` (D167); continuing a run keeps its original value (D166)."""
        from my_harness.storage.preferences import inherited
        from my_harness.storage.work_language import capture
        if inherit_run is not None:
            return inherited(session, inherit_run)
        if root is None:
            raise ValueError("A new job needs its checkout root to freeze its languages")
        return capture(session, root)

    def job_language(self, claim: JobRecord) -> dict | None:
        """The language pair sealed when the claimed job was admitted (D167); prompts read only this (D169)."""
        with Session(self.engine) as session:
            return session.scalar(select(Job.language_context).where(Job.id == claim.id))

    def job_visual(self, claim: JobRecord) -> str:
        """Visual language of the job's own texts: the frozen one; jobs admitted without it use the stored one."""
        from my_harness.storage.preferences import language
        frozen = self.job_language(claim)
        return frozen.get("ui_language") if isinstance(frozen, dict) and frozen.get("ui_language") else language(self.engine)

    def _admit(self, session, assessment) -> str | None:
        try:
            return ModeGuard.enforce(session, assessment)
        except ModeConflict as exc:
            raise Conflict(str(exc)) from exc

    @staticmethod
    def _registry_current(session, root, versions, *, working=True):
        """Serializes admission with D078: never queue with an already replaced row."""
        if 'project_registry' not in versions:
            return
        from my_harness.storage.models import RegisteredProjectRow
        current = session.scalar(select(RegisteredProjectRow).where(
            RegisteredProjectRow.root == root, RegisteredProjectRow.status == 'ACTIVE'))
        if (current is None or str(current.version) != versions['project_registry']
                or ('project_registry_id' in versions and current.id != versions['project_registry_id'])
                or ('project_registry_sha256' in versions
                    and current.row_sha256 != versions['project_registry_sha256'])):
            raise Conflict(tr('managed.project_configuration_changed_reload'))
        from my_harness.storage.models import ConfigurationScopeRow as Scope, ConfigurationRevisionRow as Revision
        head = session.get(Scope, 'project:' + current.id)
        if head and head.active_revision:
            reference = session.get(Revision, (head.scope, head.active_revision))
            if (not reference or versions.get('project_configuration_revision') != str(reference.revision)
                    or versions.get('project_configuration_sha256') != reference.sha256):
                raise Conflict(tr('managed.project_configuration_changed_reload'))
            from my_harness.storage.configuration_files import ConfigurationFiles
            from my_harness.services.configuration import digest
            files = ConfigurationFiles(Path(head.directory))
            raw = files.read(files.immutable(head.scope, reference.revision, reference.sha256))
            if (raw is None or digest(raw) != reference.sha256
                    or working and files.hash(files.working(head.scope)) != head.working_sha256):
                raise Conflict(tr('managed.project_configuration_changed_reload'))
        elif versions.get('project_configuration'):
            raise Conflict(tr('managed.project_configuration_changed_reload'))

    def _run_root(self, run_id: str) -> str | None:
        with Session(self.engine) as session:
            return session.scalar(select(Run.root).where(Run.id == run_id))

    def retired_reason(self, run_id, request_json=None):
        from my_harness.storage.retired_work import reason
        with Session(self.engine) as session:
            run = session.get(Run, run_id)
            return reason(session, run, request_json) if run else tr('managed.unknown_persisted_run')

    def mode_refusal(self, claim: JobRecord) -> str | None:
        """Disk read outside a transaction: the checkout mode still admits this job."""
        with Session(self.engine) as session:
            job = session.get(Job, claim.id)
            if job is None:
                raise LookupError(tr('managed.unknown_managed_job'))
            root, admitted = session.get(Run, job.run_id).root, job.activation_id
        retired = self.retired_reason(claim.run_id, claim.request_json)
        if retired is not None:
            return retired
        assessment = self.guard.assess(root)
        if assessment.refusal is not None:
            return assessment.refusal
        current = assessment.activation.id if assessment.activation else None
        if current != admitted:
            return tr('mode.changed_admission')
        return None

    def _require_mode(self, claim: JobRecord) -> None:
        refusal = self.mode_refusal(claim)
        if refusal is not None:
            raise Conflict(refusal)

    def refuse(self, claim: JobRecord, diagnostic: str) -> None:
        """Claimed job that never recorded an owner or effects: it is closed and the lock released."""
        _nonempty(diagnostic, "refusal diagnostic")
        with self._write() as session:
            job, run = self._owned(session, claim)
            if job.process_owner is not None:
                raise Conflict(tr('managed.job_already_registered_process'))
            history = load_history(run.history_json)
            job.status, job.finished_at, job.diagnostic = "REFUSED", self._now(), diagnostic
            run.status = (history.status.upper()
                          if history.status in {"stopped", "blocked", "revision_limit", "acceptance_ready"}
                          else "REFUSED")
            if self._live_commit(session, run.id, ("COMMITTED",)) is not None:
                run.status = "COMMITTED"
            run.stage = "mode_guard"
            self._release(session, job, run)
            self._event(session, run, "job_refused", {"job_id": job.id, "diagnostic": diagnostic})
            if run.purpose != "task":
                _operation_module(run).abort(self, session, run, "REFUSED", diagnostic)

    def _existing(self, session, key, request):
        _nonempty(key, "idempotency key")
        if len(key) > 200:
            raise ValueError(tr('managed.idempotency_key_exceeds_200'))
        row = session.scalar(select(Job).where(Job.idempotency_key == key))
        if row and row.request_json != request:
            raise Conflict(tr('managed.idempotency_key_already_names_2'))
        return row

    def submit(self, context: ProjectContext, task_id: str, phase_id: str, text: str,
               versions: dict, *, key: str, notes: str | None = None) -> JobRecord:
        for value, name in ((task_id, "task identity"), (phase_id, "phase identity"), (text, "plan text")):
            _nonempty(value, name)
        if notes is not None:
            _nonempty(notes, "additional notes")
        if (not isinstance(versions, dict)
                or not {"engine", "agent_adapter", "commands", "evidence"} <= versions.keys()
                or not all(isinstance(k, str) and k and (v is None or isinstance(v, str) and v.strip())
                           for k, v in versions.items())):
            raise ValueError("Explicit component versions required; unknown values use null")
        if Path(self.engine.url.database).resolve().is_relative_to(context.root):
            raise ValueError(tr('managed.managed_sqlite_outside_agent'))
        request = {"action": "start", "context_json": context_snapshot(context),
                   "versions_json": freeze(versions), "task_id": task_id, "phase_id": phase_id, "text": text}
        if notes is not None:
            request["notes"] = notes  # P009-T020: in the job request; without notes, the request does not change
        request = freeze(request)
        assessment = self.guard.assess(context.root)
        with self._write() as session:
            existing = self._existing(session, key, request)
            if existing:
                return _job(existing)
            return self._queue_new_run(session, assessment, context, versions, task_id, phase_id, key, request)

    def _queue_new_run(self, session, assessment, context, versions, task_id, phase_id, key, request,
                       purpose="task"):
        """New run and its first job in the caller's transaction (tasks and H3.3 phase operations)."""
        from my_harness.core.engine.context import IntakeContext
        if isinstance(context, IntakeContext) and purpose not in ('definition', 'onboarding', 'bootstrap', 'import_commit'):
            raise Conflict(tr('profile_proposal.required'))
        if versions.get('agent_adapter') == 'cli-14':
            from my_harness.adapters.cli_compatibility import CompatibilityError, MINIMUM, eligible
            for role in ('reviewer', 'executor'):
                provider, observed = versions.get(f'{role}_provider'), versions.get(f'{role}_cli')
                if provider not in MINIMUM or observed is None or not versions.get(f'{role}_cli_launch_sha256'):
                    raise CompatibilityError('unresolved_client')
                if not eligible(provider, observed):
                    raise CompatibilityError('minimum_version', provider=provider, observed=observed,
                                             minimum=MINIMUM[provider])
        self._registry_current(session, str(context.root), versions)
        from my_harness.storage.preparation import admit
        admit(session, str(context.root), versions, purpose)
        if purpose != "import_commit":
            from my_harness.storage.project_import import unresolved as import_unresolved
            if import_unresolved(session, str(context.root)):
                raise Conflict(tr('managed.import_awaits_completion_explicit'))
        if purpose != "bootstrap":
            from my_harness.storage.bootstrap import unresolved
            if unresolved(session, str(context.root)):
                raise Conflict(tr('managed.bootstrap_awaits_completion_explicit'))
        if purpose == "task":
            self._phase_open(session, str(context.root), phase_id)
        activation_id = self._admit(session, assessment)
        snapshot = context_snapshot(context)
        history = RunHistory(str(uuid4()), snapshot)
        now = self._now()
        action = json.loads(request)["action"]
        run = Run(id=history.id, root=str(context.root), task_id=task_id, phase_id=phase_id,
                  context_json=snapshot, versions_json=freeze(versions), history_json=dump_history(history),
                  status="QUEUED", stage=action, revisions=0, purpose=purpose,
                  revision_limit=context.policy.max_revision_cycles, version=0, created_at=now, updated_at=now)
        session.add(run)
        session.flush()
        run_projection.create(session, run.id, run.history_json, history)
        job = Job(idempotency_key=key, run_id=run.id, request_json=request, status="QUEUED", created_at=now,
                  activation_id=activation_id, language_context=self._language(session, root=run.root))
        if json.loads(snapshot).get("work_language") not in (None, job.language_context["work_language"]):
            raise Conflict(tr('managed.project_context_does_not'))
        session.add(job)
        session.flush()
        self._event(session, run, "job_queued", {"job_id": job.id, "action": action})
        return _job(job)

    @staticmethod
    def _phase_open(session, root, code):
        """H3.3/H3.4: a closed, closing or abandoned phase accepts no tasks, resumptions or commits."""
        from my_harness.storage.models import PhaseRow
        from my_harness.storage.documents import unresolved
        if unresolved(session, root):
            raise Conflict(tr('managed.document_intent_awaits_reconciliation'))
        if session.scalar(select(PhaseRow.id).where(PhaseRow.root == root, PhaseRow.code == code,
                                                    PhaseRow.status.in_(("CLOSED", "CLOSING", "ABANDONED")))):
            raise Conflict(tr('managed.phase_closed_closing_abandoned'))

    def resume(self, run_id: str, *, key: str, expected_version: int, retry_executor=False) -> JobRecord:
        if type(expected_version) is not int or type(retry_executor) is not bool:
            raise ValueError(tr('managed.explicit_resource_version_boolean'))
        request = freeze({"action": "retry" if retry_executor else "revalidate", "run_id": run_id,
                          "expected_version": expected_version})
        root = self._run_root(run_id)
        assessment = self.guard.assess(root) if root is not None else None
        with self._write() as session:
            existing = self._existing(session, key, request)
            if existing:
                return _job(existing)
            run = session.get(Run, run_id)
            if run is None:
                raise LookupError(tr('managed.unknown_managed_run'))
            from my_harness.storage.retired_work import reason
            if diagnostic := reason(session, run):
                raise Conflict(diagnostic)
            history = load_history(run.history_json)
            if run.version != expected_version:
                raise Conflict(tr('managed.run_changed_reload_before'))
            if session.scalar(select(Job.id).where(Job.run_id == run_id,
                    Job.status.in_(("QUEUED", "ACTIVE", "RECOVERY_REQUIRED")))) is not None:
                raise Conflict(tr('managed.run_already_has_unfinished'))
            if session.scalar(select(Commit.operation_id).where(
                    Commit.run_id == run_id, Commit.status.in_(("INTENT", "COMMITTED")))) is not None:
                raise Conflict(tr('managed.run_has_recorded_pending'))
            if history.status not in {"stopped", "blocked", "revision_limit"} or history.task_json is None:
                raise Conflict(tr('managed.stopped_run_frozen_contract'))
            if retry_executor and not json.loads(history.task_json)["allowed_paths"]:
                raise Conflict(tr('managed.read_tasks_cannot_retry'))
            self._phase_open(session, run.root, run.phase_id)
            self._registry_current(session, run.root, json.loads(run.versions_json))
            from my_harness.storage.preparation import admit
            admit(session, run.root, json.loads(run.versions_json), run.purpose)
            activation_id = self._admit(session, assessment)
            job = Job(idempotency_key=key, run_id=run_id, request_json=request, status="QUEUED", created_at=self._now(),
                      activation_id=activation_id, language_context=self._language(session, run_id))
            session.add(job)
            session.flush()
            run.status, run.stage = "QUEUED", json.loads(request)["action"]
            self._event(session, run, "job_queued", {"job_id": job.id, "action": run.stage})
            return _job(job)

    def get_run(self, run_id: str) -> RunRecord:
        with Session(self.engine) as session:
            row = session.get(Run, run_id)
            if row is None:
                raise LookupError(tr('managed.unknown_managed_run'))
            return RunRecord(load_history(row.history_json), row.versions_json, row.status,
                             row.stage, row.version, row.revisions)

    def get_job(self, job_id: int) -> JobRecord:
        with Session(self.engine) as session:
            row = session.get(Job, job_id)
            if row is None:
                raise LookupError(tr('managed.unknown_managed_job'))
            return _job(row)

    def events(self, run_id: str, *, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError(tr('managed.invalid_managed_event_page'))
        with Session(self.engine) as session:
            rows = session.scalars(select(Event).where(Event.run_id == run_id, Event.sequence > after)
                                   .order_by(Event.sequence).limit(limit)).all()
            return [{"id": row.id, "sequence": row.sequence, "kind": row.kind,
                     "recorded_at": row.recorded_at, "payload": row.payload} for row in rows]

    def claim(self, *, lease_seconds=30, lane=None) -> JobRecord | None:
        _lease(lease_seconds)
        with self._write() as session:
            # FIFO of eligible jobs: another checkout may advance while one is blocked.
            independent = func.json_extract(Job.request_json, '$.action').in_(['chat_snapshot', 'chat_command'])
            query = select(Job).join(Run, Run.id == Job.run_id).where(
                Job.status == "QUEUED", or_(independent, ~Run.root.in_(select(Lock.root))))
            if lane is not None:
                query = query.where(independent if lane == 'chat' else ~independent)
            job = session.scalar(query.order_by(Job.id).limit(1))
            if job is None:
                return None
            run = session.get(Run, job.run_id)
            now = self._now()
            job.status, job.owner_token = "ACTIVE", str(uuid4())
            job.heartbeat_at = now
            job.lease_until = (datetime.fromisoformat(now) + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")
            if not independent_chat(job):
                session.add(Lock(root=run.root, job_id=job.id))
            run.status, run.stage = "ACTIVE", json.loads(job.request_json)["action"]
            self._event(session, run, "job_claimed", {"job_id": job.id, "owner_token": job.owner_token})
            return _job(job)

    def _owned(self, session, claim):
        job = session.get(Job, claim.id)
        if (job is None or not claim.owner_token or job.owner_token != claim.owner_token
                or job.status != "ACTIVE" or job.lease_until <= self._now()):
            raise OwnershipLost(tr('managed.job_lease_ownership_lost'))
        run = session.get(Run, job.run_id)
        versions = json.loads(run.versions_json)
        if versions.get('project_configuration'):
            # Working-copy edits block admissions; an owned job checks only its immutable authority.
            self._registry_current(session, run.root, versions, working=False)
        lock = session.get(Lock, run.root)
        if not independent_chat(job) and (lock is None or lock.job_id != job.id):
            raise OwnershipLost(tr('managed.checkout_writer_lock_lost'))
        return job, run

    def _release(self, session, job, run):
        if independent_chat(job) or run.purpose == 'onboarding':
            from my_harness.adapters.chat_snapshot import cleanup
            cleanup(self, job)
        if not independent_chat(job):
            session.delete(session.get(Lock, run.root))

    def heartbeat(self, claim: JobRecord, *, lease_seconds=30) -> None:
        _lease(lease_seconds)
        with self._write() as session:
            job, _ = self._owned(session, claim)
            job.heartbeat_at = self._now()
            job.lease_until = (datetime.fromisoformat(job.heartbeat_at) + timedelta(seconds=lease_seconds)).isoformat(timespec="microseconds")

    def _history(self, session, run, history):
        previous = load_history(run.history_json)
        if history.id != run.id or history.context_json != run.context_json:
            raise Conflict("Frozen run identity/context changed")
        if previous.task_json is not None and history.task_json != previous.task_json:
            raise Conflict("Frozen task contract changed")
        if history.task_json is not None:
            task = json.loads(history.task_json)
            if task.get("task_id") != run.task_id or task.get("phase_id") != run.phase_id:
                raise Conflict("Frozen task identity must match the managed run")
        if (history.attempts[:len(previous.attempts)] != previous.attempts
                or history.preparation_json[:len(previous.preparation_json)] != previous.preparation_json
                or history.stops[:len(previous.stops)] != previous.stops
                or len(history.cycles) < len(previous.cycles)):
            raise Conflict("Managed history cannot be discarded or replaced")
        for old, new in zip(previous.cycles, history.cycles):
            if old != new and (old.review_json is not None or replace(new, review_json=None) != old):
                raise Conflict("Recorded validation/review cannot change")
        completed = []
        roles = [attempt.request.role for attempt in history.attempts]
        for number, attempt in enumerate(history.attempts, start=1):
            row = session.get(AttemptRow, attempt.request.id)
            if (row is None or row.run_id != run.id or row.number != number
                    or restore_request(json.loads(row.request_json)) != attempt.request):
                raise Conflict("Attempt requires a previously persisted invocation intent")
            result = freeze(asdict(attempt.result))
            if row.result_json is not None and freeze(asdict(AgentResult(**json.loads(row.result_json)))) != result:
                raise Conflict("Frozen attempt result changed")
            if row.result_json is None:
                row.result_json, row.status, row.finished_at = result, (attempt.result.status or "COMPLETED").upper(), self._now()
                completed.append(row.id)
                # H6.4: metrics materialized in the same transaction as the attempt result.
                record_metrics(session, run, row, executor_round=executor_round(roles, number), recorded_at=row.finished_at)
                settle_usage(session, run, row)  # P001-T003: accounting capture in the same transaction
                # P002-T006 (D287): the invocation's operation settles with the fenced result, if a graph sealed one.
                operation_journal.settle_attempt(session, row, revision_round=executor_round(roles, number),
                                                 at=row.finished_at)
        run.history_json = dump_history(history)
        run.revisions = history.revisions
        run_projection.advance(session, run.id, previous, history, run.history_json)  # same transaction (D142)
        return completed

    def checkpoint(self, claim: JobRecord, history: RunHistory, stage: str) -> None:
        with self._write() as session:
            job, run = self._owned(session, claim)
            completed = self._history(session, run, history)
            run.stage = stage
            run.status = {"planner": "PLANNING", "executor": "EXECUTING", "preparation": "PREPARING",
                          "validation": "VALIDATING", "reviewer": "REVIEWING"}.get(stage, "ACTIVE")
            self._event(session, run, "checkpoint", {"job_id": job.id, "history_status": history.status,
                                                    "completed_attempts": completed})

    def agent_started(self, claim: JobRecord, history: RunHistory, request: AgentRequest,
                      operation: 'operation_journal.InvocationOperation | None' = None) -> AgentRequest:
        """`operation`: a graph node's invocation operation, sealed here with the attempt and the ledger intent."""
        self._require_mode(claim)
        with self._write() as session:
            job, run = self._owned(session, claim)
            self._history(session, run, history)
            if request.context_json != run.context_json or request.task_json != history.task_json or not request.fresh_session:
                raise Conflict("Attempt must use frozen context/task and a fresh session")
            attempts = session.scalars(select(AttemptRow).where(AttemptRow.run_id == run.id)
                                      .order_by(AttemptRow.number)).all()
            if any(row.result_json is None for row in attempts):
                raise Conflict(tr('managed.earlier_invocation_still_has'))
            executions = sum(json.loads(row.request_json)["role"] == "executor" for row in attempts)
            if request.role == "executor":
                run.revisions = max(0, executions)
                if run.revisions > run.revision_limit:
                    raise Conflict("Persisted correction budget exhausted")
            from my_harness.storage.permissions import authorize
            request = authorize(session, self, run, request)
            attempt = AttemptRow(id=request.id, run_id=run.id, number=len(attempts) + 1,
                                 request_json=freeze(asdict(request)), versions_json=run.versions_json,
                                 status="ACTIVE", started_at=self._now(), language_context=job.language_context)
            session.add(attempt)
            session.flush()
            invocation = intend_usage(session, run, attempt)  # P001-T003: expected invocation with its native intent
            if operation is not None:
                operation_journal.seal_invocation(session, operation, root=run.root, job=job, attempt=attempt,
                                                  invocation_id=invocation.id, at=attempt.started_at)
            run.stage = request.role
            run.status = {"planner": "PLANNING", "executor": "EXECUTING", "reviewer": "REVIEWING",
                          "phase": "CHECKING", "chat": "ANSWERING", "bootstrap": "DISCOVERING",
                          "definition": "ANSWERING", "planning": "ANSWERING"}[request.role]
            self._event(session, run, "attempt_started", {"job_id": job.id, "attempt_id": request.id,
                                                        "number": len(attempts) + 1, "role": request.role})
            return request

    def effect(self, claim: JobRecord, kind: str, payload: dict) -> None:
        with self._write() as session:
            job, run = self._owned(session, claim)
            self._event(session, run, kind, {**payload, "job_id": job.id})

    def finish(self, claim: JobRecord, history: RunHistory, outcome: dict | None = None) -> None:
        """`outcome`: result of a phase operation (H3.3) or a chat turn (H4.1), applied in
        the same transaction."""
        with self._write() as session:
            job, run = self._owned(session, claim)
            terminal = {"stopped", "completed"} if run.purpose != "task" else {
                "stopped", "blocked", "revision_limit", "acceptance_ready"}
            if history.status not in terminal or (outcome is None) != (run.purpose == "task"):
                raise Conflict("Only a terminal engine action can finish a job")
            self._history(session, run, history)
            if session.scalar(select(AttemptRow.id).where(AttemptRow.run_id == run.id,
                    AttemptRow.result_json.is_(None))) is not None:
                raise Conflict("Cannot finish with an unknown invocation outcome")
            self._processes_stopped(session, job)
            run.status = history.status.upper()
            run.stage = history.stop.stage if history.stop else "finished"
            if self._live_commit(session, run.id, ("COMMITTED",)) is not None:
                run.status, run.stage = "COMMITTED", "committed"
            if outcome is not None:
                _operation_module(run).settle(self, session, run, outcome)
            job.status, job.finished_at = "DONE", self._now()
            self._release(session, job, run)
            self._event(session, run, "job_finished", {"job_id": job.id, "history_status": history.status})

    def quarantine(self, claim: JobRecord, reason: str) -> None:
        """Without releasing the writer or inferring that a process finished."""
        _nonempty(reason, "recovery reason")
        with self._write() as session:
            job = session.get(Job, claim.id)
            if job is None or job.owner_token != claim.owner_token or job.status not in {"ACTIVE", "RECOVERY_REQUIRED"}:
                raise OwnershipLost("Cannot quarantine a different/finished owner")
            if job.status == "RECOVERY_REQUIRED":
                return
            job.status, job.diagnostic = "RECOVERY_REQUIRED", reason
            run = session.get(Run, job.run_id)
            run.status = "RECOVERY_REQUIRED"
            self._event(session, run, "recovery_required", {"job_id": job.id, "reason": reason})

    def recover_expired(self) -> list[int]:
        """Reconcile at startup/periodically. Never requeues or releases locks."""
        with self._write() as session:
            rows = session.scalars(select(Job).where(Job.status == "ACTIVE", Job.lease_until <= self._now())
                                   .order_by(Job.id)).all()
            for job in rows:
                job.status, job.diagnostic = "RECOVERY_REQUIRED", tr('managed.lease_expired')
                run = session.get(Run, job.run_id)
                run.status = "RECOVERY_REQUIRED"
                self._event(session, run, "recovery_required", {"job_id": job.id, "reason": job.diagnostic})
            return [job.id for job in rows]

    def confirm_stopped(self, job_id: int, *, owner_token: str, expected_version: int, reason: str) -> None:
        """Explicit action AFTER ruling out the previous writer; does not prove its death."""
        _nonempty(reason, "confirmation evidence")
        with self._write() as session:
            job = session.get(Job, job_id)
            if job is None or job.owner_token != owner_token or job.status != "RECOVERY_REQUIRED":
                raise Conflict(tr('managed.confirm_exact_quarantined_owner'))
            run = session.get(Run, job.run_id)
            if run.version != expected_version:
                raise Conflict(tr('managed.run_changed_reload_before_2'))
            self._processes_stopped(session, job, recovering=True)
            history = load_history(run.history_json)
            pending = session.scalars(select(AttemptRow).where(AttemptRow.run_id == run.id,
                                      AttemptRow.result_json.is_(None)).order_by(AttemptRow.number)).all()
            for row in pending:
                result = AgentResult(None, error="Interrupted invocation; outcome unknown, no automatic retry")
                row.status, row.result_json, row.finished_at = "INTERRUPTED", freeze(asdict(result)), self._now()
                history = replace(history, attempts=history.attempts + (Attempt(restore_request(json.loads(row.request_json)), result),))
                round_ = executor_round([attempt.request.role for attempt in history.attempts], row.number)
                record_metrics(session, run, row, recorded_at=row.finished_at, executor_round=round_)
                settle_usage(session, run, row)
                operation_journal.settle_attempt(session, row, revision_round=round_, at=row.finished_at)
            history = stop_history(history, run.stage, reason)
            self._history(session, run, history)
            run.status = "COMMITTED" if self._live_commit(session, run.id, ("COMMITTED",)) else "INTERRUPTED"
            job.status, job.finished_at, job.diagnostic = "INTERRUPTED", self._now(), reason
            self._release(session, job, run)
            self._event(session, run, "writer_stopped_confirmed", {"job_id": job.id, "owner_token": owner_token, "reason": reason})
            if run.purpose != "task":
                from my_harness.storage import retired_work
                module = retired_work if retired_work.reason(session, run, job.request_json) else _operation_module(run)
                module.abort(self, session, run, "INTERRUPTED", reason)


    # --- H2.4: accepted commit ----------------------------------------------------

    @staticmethod
    def _live_commit(session, run_id, statuses=("INTENT", "COMMITTED")):
        return session.scalar(select(Commit).where(Commit.run_id == run_id, Commit.status.in_(statuses)))

    def submit_commit(self, run_id: str, *, key: str, expected_version: int,
                      mechanical: tuple[MechanicalUpdate, ...] = ()) -> JobRecord:
        """Queues the commit as a writing action; a pending intent is reconciled, not repeated."""
        if type(expected_version) is not int:
            raise ValueError(tr('managed.explicit_resource_version_required'))
        updates = tuple(mechanical)
        request = freeze({"action": "commit", "run_id": run_id, "expected_version": expected_version,
                          "mechanical": [asdict(item) for item in updates]})
        root = self._run_root(run_id)
        assessment = self.guard.assess(root) if root is not None else None
        with self._write() as session:
            existing = self._existing(session, key, request)
            if existing:
                return _job(existing)
            run = session.get(Run, run_id)
            if run is None:
                raise LookupError(tr('managed.unknown_managed_run'))
            if run.version != expected_version:
                raise Conflict(tr('managed.run_changed_reload_before_3'))
            return self._queue_commit(session, run, key, request, updates, assessment)

    def _queue_commit(self, session, run, key, request, updates, assessment) -> JobRecord:
        """Checks and commit job in the caller's transaction (own action or H3.4 batch)."""
        self._registry_current(session, run.root, json.loads(run.versions_json))
        from my_harness.storage.preparation import admit
        admit(session, run.root, json.loads(run.versions_json), run.purpose)
        run_id = run.id
        if session.scalar(select(Job.id).where(Job.run_id == run_id,
                Job.status.in_(("QUEUED", "ACTIVE", "RECOVERY_REQUIRED")))) is not None:
            raise Conflict(tr('managed.run_already_has_unfinished'))
        live = self._live_commit(session, run_id)
        if live is not None and live.status == "COMMITTED":
            raise Conflict(tr('managed.run_already_has_recorded'))
        self._phase_open(session, run.root, run.phase_id)
        history = load_history(run.history_json)
        if live is not None:
            if updates and updates != CommitIntent.from_json(live.intent_json).mechanical:
                raise Conflict("A pending commit operation fixed different mechanical updates")
        else:
            if (history.status != "acceptance_ready" or history.acceptance is None
                    or not history.acceptance.eligible):
                raise Conflict(tr('managed.eligible_acceptance_ready_run'))
            try:
                git_provenance(history.acceptance.evidence)
                validate_mechanical_updates(restore_context(run.context_json),
                                            history.acceptance.evidence.changed_paths, updates)
            except (CommitError, ValueError) as exc:
                raise Conflict(str(exc)) from exc
        activation_id = self._admit(session, assessment)
        job = Job(idempotency_key=key, run_id=run_id, request_json=request, status="QUEUED",
                  created_at=self._now(), activation_id=activation_id,
                  language_context=self._language(session, root=run.root))
        session.add(job)
        session.flush()
        run.status, run.stage = "QUEUED", "commit"
        self._event(session, run, "job_queued", {"job_id": job.id, "action": "commit"})
        return _job(job)

    def commit_record(self, run_id: str) -> CommitRecord | None:
        with Session(self.engine) as session:
            row = self._live_commit(session, run_id) or session.scalar(
                select(Commit).where(Commit.run_id == run_id).order_by(Commit.created_at.desc()).limit(1))
            return _commit(row) if row else None

    def pending_commit(self, claim: JobRecord) -> CommitIntent | None:
        with Session(self.engine) as session:
            job = session.get(Job, claim.id)
            if job is None or not claim.owner_token or job.owner_token != claim.owner_token:
                raise OwnershipLost(tr('managed.job_ownership_lost_reconciliation'))
            row = self._live_commit(session, job.run_id, ("INTENT",))
            return CommitIntent.from_json(row.intent_json) if row else None

    def commit_intent(self, claim: JobRecord, intent: CommitIntent) -> None:
        """Durable intent BEFORE moving the reference; own, short transaction."""
        self._require_mode(claim)
        with self._write() as session:
            job, run = self._owned(session, claim)
            history = load_history(run.history_json)
            if (intent.run_id != run.id or history.acceptance is None
                    or history.acceptance.evidence.fingerprint != intent.reviewed_fingerprint
                    or history.acceptance.evidence.base_revision != intent.base_revision):
                raise Conflict("Commit intent must name this run's reviewed acceptance evidence")
            if self._live_commit(session, run.id) is not None:
                raise Conflict(tr('managed.run_already_has_live'))
            self._phase_open(session, run.root, run.phase_id)
            session.add(Commit(operation_id=intent.operation_id, run_id=run.id, job_id=job.id, status="INTENT",
                               base_revision=intent.base_revision, reviewed_fingerprint=intent.reviewed_fingerprint,
                               expected_tree=intent.expected_tree, expected_commit=intent.expected_commit,
                               intent_json=intent.to_json(), created_at=self._now()))
            run.stage, run.status = "commit", "COMMITTING"
            self._event(session, run, "commit_intent", {
                "job_id": job.id, "operation_id": intent.operation_id, "base_revision": intent.base_revision,
                "expected_tree": intent.expected_tree, "expected_commit": intent.expected_commit,
                "reviewed_fingerprint": intent.reviewed_fingerprint})

    def commit_result(self, claim: JobRecord, outcome: CommitOutcome, adopt: dict | None = None) -> None:
        """`adopt` (D072): hashes of managed blocks that the commit itself regenerated, adopted atomically."""
        with self._write() as session:
            job, run = self._owned(session, claim)
            row = session.get(Commit, outcome.operation_id) if outcome.operation_id else None
            if row is None or row.run_id != run.id or row.status != "INTENT":
                raise Conflict("Commit result requires its pending intent")
            row.result_json = outcome.to_json()
            row.finished_at = self._now()
            if outcome.status == "invalidated":
                row.status = "INVALIDATED"
                self._event(session, run, "commit_invalidated", {
                    "job_id": job.id, "operation_id": row.operation_id, "diagnostic": outcome.diagnostic})
                return
            if (outcome.commit != row.expected_commit or outcome.tree != row.expected_tree):
                raise Conflict("Commit result differs from the persisted intent")
            row.status, row.commit_sha = "COMMITTED", outcome.commit
            run.status, run.stage = "COMMITTED", "committed"
            if adopt:
                from my_harness.storage.documents import adopt_blocks
                adopt_blocks(self, session, run, adopt, outcome.commit)
            self._event(session, run, "commit_recorded", {
                "job_id": job.id, "operation_id": row.operation_id, "commit": outcome.commit,
                "tree": outcome.tree, "reconciled": outcome.status == "reconciled", "index": outcome.index})

    def commit_invalidated(self, claim: JobRecord, outcome: CommitOutcome) -> None:
        """Invalidation prior to any intent: evidence only, no operation row."""
        self.effect(claim, "commit_invalidated", {
            "operation_id": None, "diagnostic": outcome.diagnostic,
            "observed_fingerprint": outcome.observed_fingerprint, "head": outcome.head})

    def tag_intent(self, claim: JobRecord, intent: dict) -> None:
        """H3.3: closure tag intent BEFORE creating the reference; own, short transaction."""
        self._require_mode(claim)
        with self._write() as session:
            job, run = self._owned(session, claim)
            from my_harness.storage.phases import record_tag_intent
            record_tag_intent(self, session, run, intent)
            self._event(session, run, "phase_tag_intent", {"job_id": job.id, **intent})

    def export_intent(self, claim: JobRecord, intent: CommitIntent) -> None:
        """Confirmed export intent, persisted before writing documents or Git."""
        self._require_mode(claim)
        with self._write() as session:
            _, run = self._owned(session, claim)
            from my_harness.storage.document_export import record_intent
            record_intent(self, session, run, intent)
            self._event(session, run, 'document_export_intent', {
                'operation_id': intent.operation_id, 'expected_commit': intent.expected_commit,
                'expected_tree': intent.expected_tree})

    def document_intent(self, claim: JobRecord, intent: CommitIntent) -> None:
        """D072: transition or documentary edit intent, persisted before writing documents or Git."""
        self._require_mode(claim)
        with self._write() as session:
            _, run = self._owned(session, claim)
            if run.purpose not in ("document_edit", "phase_transition", "phase_close"):
                raise Conflict("Document intents belong to document operations")
            _operation_module(run).record_intent(self, session, run, intent)
            self._event(session, run, f"{run.purpose}_intent", {
                "operation_id": intent.operation_id, "expected_commit": intent.expected_commit,
                "expected_tree": intent.expected_tree})

    def register_owner(self, claim, identity):
        with self._write() as session:
            job, run = self._owned(session, claim)
            if job.process_owner is not None:
                raise Conflict("Process owner already registered")
            job.process_owner = identity
            self._event(session, run, "process_owner_registered", {"job_id": job.id, "identity": identity})

    def close_owner(self, claim, *, heartbeat=None):
        # Closing the scope forbids future launches; may run after lease loss.
        with self._write() as session:
            job = session.get(Job, claim.id)
            if job is None or job.owner_token != claim.owner_token:
                raise OwnershipLost("Different process owner")
            run = session.get(Run, job.run_id)
            # D252: only the closing owner may settle its unfinished attempts, even after lease loss.
            from my_harness.adapters.processes import liveness
            for row in session.scalars(select(Process).where(Process.job_id == job.id, Process.status == 'RUNNING')):
                if row.capture is not None or row.identity is None:
                    continue
                state = liveness(row.identity, group=True)
                partial = None
                artifacts = (row.spec or {}).get('artifacts')
                if isinstance(artifacts, str):
                    try:
                        partial = json.loads((Path(artifacts) / 'capture.json').read_text())
                    except (OSError, ValueError):
                        pass
                capture = partial if isinstance(partial, dict) else {'status': 'interrupted'}
                row.capture = {**capture, 'reported_group_state': capture.get('group_state'), 'group_state': state,
                               'settled_by': 'closing_owner'}
                row.status = 'STOPPED' if state == 'dead' else 'UNCERTAIN'
                self._event(session, run, 'process_interrupted', {'job_id': job.id, 'attempt_id': row.attempt_id,
                    'process_status': row.status, 'group_state': state, 'partial_capture': isinstance(partial, dict)})
            job.owner_closed = True
            self._event(session, run, "process_owner_closed", {"job_id": job.id,
                **({'heartbeat': dict(heartbeat)} if heartbeat and (heartbeat['failures'] or heartbeat['lost']) else {})})

    def process_intent(self, claim, attempt_id, spec):
        with self._write() as session:
            job, run = self._owned(session, claim)
            attempt = session.get(AttemptRow, attempt_id)
            if (not attempt or attempt.run_id != run.id or attempt.result_json is not None
                    or job.process_owner is None or job.owner_closed):
                raise Conflict("Live owner and pending invocation required")
            if session.get(Process, attempt_id):
                raise Conflict("One launch per attempt; no retry")
            session.add(Process(attempt_id=attempt_id, job_id=job.id, spec=spec, status="PENDING"))
            self._event(session, run, "process_intent", {"job_id": job.id, "attempt_id": attempt_id, "spec": spec})

    def process_update(self, claim, attempt_id, kind, payload):
        self.process_updates(claim, attempt_id, ((kind, payload),))

    def process_updates(self, claim, attempt_id, items):
        """D252: preserve each event and sequence, with one fenced transaction per read chunk."""
        with self._write() as session:
            job, run = self._owned(session, claim)
            row = session.get(Process, attempt_id)
            if row is None or row.job_id != job.id:
                raise Conflict("Unknown process intent")
            for kind, payload in items:
                if kind == "process_spawned":
                    if job.owner_closed or row.identity is not None:
                        raise Conflict("Process identity cannot change")
                    row.identity, row.status = payload, "RUNNING"
                elif kind == "process_finished":
                    row.status = "STOPPED" if payload["group_state"] == "dead" else "UNCERTAIN"
                    row.capture = payload
                self._event(session, run, kind, {"job_id": job.id, "attempt_id": attempt_id, **payload})

    def processes(self, job_id):
        with Session(self.engine) as session:
            return [{"attempt_id": row.attempt_id, "spec": row.spec, "identity": row.identity,
                     "status": row.status, "capture": row.capture}
                    for row in session.scalars(select(Process).where(Process.job_id == job_id))]

    def command_process_event(self, claim, command_id, kind, payload):
        from my_harness.storage.command_processes import PREFIX, for_job
        self._require_mode(claim)
        with self._write() as session:
            job, run = self._owned(session, claim)
            if job.process_owner is None or job.owner_closed:
                raise Conflict("Live command owner required")
            row = next((r for r in for_job(session, job) if r['command_id'] == command_id), None)
            if kind == 'intent':
                started = session.scalars(select(Event).where(Event.run_id == run.id,
                    Event.kind == 'command_started')).all()
                if row or not any(e.payload.get('command_id') == command_id
                                  and e.payload.get('job_id') == job.id for e in started):
                    raise Conflict("One process intent per started command")
            elif row is None or row['capture'] is not None:
                raise Conflict("Pending command process required")
            elif kind == 'spawned':
                if row['identity'] is not None:
                    raise Conflict("Command process identity cannot change")
            elif kind == 'bytes':
                if row['identity'] is None:
                    raise Conflict("Command has not spawned")
            elif kind != 'finished':
                raise Conflict("Unknown command process event")
            self._event(session, run, PREFIX + kind,
                        {**payload, 'job_id': job.id, 'command_id': command_id})

    def command_processes(self, job_id):
        from my_harness.storage.command_processes import for_job
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                raise Conflict("Unknown job")
            return for_job(session, job)

    def _processes_stopped(self, session, job, *, recovering=False):
        from my_harness.adapters.processes import liveness
        if recovering and job.process_owner and not job.owner_closed:
            if liveness(job.process_owner) != "dead":
                raise Conflict(tr('managed.previous_owner_may_still'))
        from my_harness.storage.command_processes import for_job
        for command in for_job(session, job):
            if command['identity'] is None:
                if command['status'] == 'STOPPED':
                    continue  # Observed failure before spawn, no target executed.
                if not recovering or (not job.owner_closed and liveness(job.process_owner) != 'dead'):
                    raise Conflict(tr('managed.pending_command_spawn_requires'))
            elif liveness(command['identity'], group=True) != 'dead':
                raise Conflict(tr('managed.previous_command_group_alive'))
        for row in session.scalars(select(Process).where(Process.job_id == job.id)):
            if row.identity is None:
                # Gate cannot execute without a durable identity. Owner must first stop.
                if not recovering or (not job.owner_closed and liveness(job.process_owner) != "dead"):
                    raise Conflict(tr('managed.pending_spawn_requires_stopped'))
            elif liveness(row.identity, group=True) != "dead":
                raise Conflict(tr('managed.previous_process_group_alive'))
