"""Engine with explicit ports and an optional journal; it does not publish real execution."""

from dataclasses import asdict, replace
import json
import shlex
from uuid import uuid4

from my_harness.core.engine.acceptance import assess_acceptance, documentation_parity
from my_harness.core.engine.context import Command, ProjectContext
from my_harness.core.engine.contracts import (
    AgentAdapter, ContractError, IncompleteContract, RunHistory,
    Selection, context_snapshot, executor_selection, freeze, invoke_agent, task_contract,
    stop_history as stopped,
)
from my_harness.core.engine.evidence import (
    ContentEvidence, EvidenceCapture, check_paths, matches, strip_empty_provenance,
)
from my_harness.core.engine.journal import EngineJournal, JournalError
from my_harness.core.engine.prompts import builtin_catalog, dump_catalog, load_catalog, render_attempt
from my_harness.core.engine.planning import SHARED_HEADING, deterministic_task, section
from my_harness.core.engine.review import ReviewCycle, decision_proposals, review_contract, stalled_review_signature
from my_harness.core.engine.validation import (
    CommandRunner, command_result_payload, run_command, run_identified_command, run_validations, validation_payload,
)
from my_harness.i18n import tr


def _executor_output(payload: dict) -> str | None:
    """Stop reason when the executor output brings denials or malformed ADR proposals."""
    if not isinstance(payload.get("permission_denials", []), list):
        return tr('workflow.malformed_denials')
    try:
        decision_proposals(payload.get("decision_proposals", []))
    except ContractError as exc:
        return tr('workflow.malformed_proposals', error=exc)
    return None


FORMATTER_TIMEOUT_SECONDS = 120
FORMATTING_NOTE = ('The harness ran the profile formatter on these executor files before validation; the evidence '
                   'and the diff already include its output.')


NOTES_PREFIX = ('\nAdditional notes from the user (they never widen the contract\'s paths, commands or '
                'permissions):\n')


def _with_notes(context: ProjectContext, task_json: str, notes: str | None) -> str:
    """P009-T020: the contract's `additional_notes` are always the user's: they are set with notes and, without
    them, the key is removed if the planner invented it (its original output stays in its attempt)."""
    task = json.loads(task_json)
    task.pop("additional_notes", None)
    if notes is not None:
        task["additional_notes"] = notes
    return task_contract(context, task, task["task_id"], task["phase_id"])


def _profile_instructions(context: ProjectContext) -> str:
    """P009-T019 (D133): an executor without a shell cannot format with the profile tool; it is told that it does
    not need to. Without a formatter, the profile text stays the same."""
    profile = context.profile
    if not profile.formatter_argv:
        return profile.executor_instructions
    return (profile.executor_instructions + '\nAfter each of your turns the harness runs `'
            + shlex.join(profile.formatter_argv) + '` on the changed files that match '
            + ', '.join(profile.formatter_paths) + '; do not reformat by hand to a different style.').lstrip('\n')


def _latest_executor_proposals(history: RunHistory) -> list:
    """Valid ADR proposals from the executor's last output (P008-T003). An output that stopped because of
    malformed proposals does not contribute them on revalidation."""
    for attempt in reversed(history.attempts):
        if attempt.request.role == "executor":
            try:
                payload = json.loads(attempt.result.payload_json or "")
                return decision_proposals(payload.get("decision_proposals", []))
            except (ValueError, AttributeError):  # ContractError is a ValueError
                return []
    return []


class OfflineEngine:
    """Injected ports; no CLI is activated from the core."""

    def __init__(self, agents: AgentAdapter, commands: CommandRunner, evidence: EvidenceCapture,
                 journal: EngineJournal | None = None, prompts=None, language: dict | None = None):
        """`language`: the pair frozen when the job was admitted (D167), rendered as the D169 directive."""
        self.agents = agents
        self.commands = commands
        self.evidence = evidence
        self.journal = journal
        self.language = language
        self.prompts = prompts or (lambda context: builtin_catalog())
        self.resuming = False

    def _checkpoint(self, history: RunHistory, stage: str) -> None:
        if self.journal:
            self.journal.checkpoint(history, stage)

    def _catalog(self, context, history):
        if self.resuming and history.prompt_catalog_json is not None:
            return load_catalog(history.prompt_catalog_json)
        return self.prompts(context)

    def _invoke(self, context, history, role, selection, name, values):
        try:
            catalog = self._catalog(context, history)
            history = replace(history, prompt_catalog_json=dump_catalog(catalog))
            prompt, snapshot = render_attempt(catalog, name, values, context, self.language)
        except (ValueError, KeyError, TypeError) as exc:
            return stopped(history, "prompts", str(exc)), None
        return invoke_agent(context, history, self.agents, role, selection, prompt, self.journal,
                            prompt_snapshot_json=snapshot)

    def _prepare(self, context: ProjectContext, history: RunHistory) -> RunHistory:
        try:
            history = replace(history, prompt_catalog_json=dump_catalog(self._catalog(context, history)))
        except (ValueError, KeyError, TypeError) as exc:
            return stopped(history, "prompts", str(exc))
        self._checkpoint(history, "preparation")
        for command in context.profile.preparation:
            result = run_command(context, self.commands, command, self.journal)
            entry = freeze({"command": asdict(command), "result": command_result_payload(result)})
            history = replace(history, preparation_json=history.preparation_json + (entry,))
            self._checkpoint(history, "preparation")
            if not result.passed:
                return stopped(history, "preparation", result.error or tr('workflow.environment_preparation_failed'))
        return history

    def start(self, context: ProjectContext, task_id: str, phase_id: str, text: str,
              *, history: RunHistory | None = None, contract: str | None = None,
              notes: str | None = None) -> RunHistory:
        """`contract`: deterministic contract already frozen by the server (H3.4); the planner is not called.
        `notes`: additional user notes (P009-T020); frozen in the contract and never widening its scope."""
        from my_harness.core.engine.context import IntakeContext
        if isinstance(context, IntakeContext):
            raise ContractError(tr('profile_proposal.required'))
        if notes is not None and (not isinstance(notes, str) or not notes.strip() or contract is not None):
            raise ContractError(tr('workflow.additional_notes_non_empty'))
        planned = contract is None  # the deterministic planner reuses `contract` further below
        self.resuming = False
        history = history or RunHistory(str(uuid4()), context_snapshot(context))
        if (history.context_json != context_snapshot(context) or history.task_json is not None
                or history.attempts or history.cycles or history.stops or history.preparation_json
                or history.status != "planned"):
            raise ContractError("Start requires a fresh history with the frozen context")
        if context.documents is not None:
            # D072: prior local changes would get mixed with the executor's diff.
            try:
                current = self.evidence.capture(context)
            except Exception as exc:
                return stopped(history, "evidence", str(exc))
            if current.changed_paths:
                return stopped(history, "start", tr('workflow.uncommitted_changes',
                                                    paths=", ".join(current.changed_paths[:20])))
        history = self._prepare(context, history)
        if history.stop:
            return history
        self._checkpoint(history, "planner")
        try:
            if contract is not None:
                if task_contract(context, json.loads(contract), task_id, phase_id) != contract:
                    raise ContractError("Server contract must be frozen canonical JSON")
                history = replace(history, task_json=contract)
            elif context.policy.planning_mode != "agent":
                try:
                    contract = deterministic_task(context, task_id, phase_id, text)
                except IncompleteContract:
                    if context.policy.planning_mode == "deterministic":
                        raise
                else:
                    history = replace(history, task_json=contract)
            if history.task_json is None:
                planner_input = {
                    "task_id": task_id, "phase_id": phase_id,
                    "task_section": section(text, rf"^##\s+{task_id}\s+[—-].*$"),
                    "shared_constraints": section(text, SHARED_HEADING),
                }
                if notes is not None:
                    planner_input["additional_notes"] = notes  # P009-T020: notes only; otherwise the same input
                prompt = freeze(planner_input)
                selection = Selection(context.policy.planner_model, context.policy.planner_effort, "Explicit planner policy")
                history, data = self._invoke(context, history, "planner", selection, "plan-task", {"INPUT_JSON": prompt})
                if data is None:
                    return history
                history = replace(history, task_json=task_contract(context, data, task_id, phase_id))
            if notes is not None or (planned and "additional_notes" in json.loads(history.task_json)):
                history = replace(history, task_json=_with_notes(context, history.task_json, notes))
        except ContractError as exc:
            return stopped(history, "planner", str(exc))
        task = json.loads(history.task_json)
        return self._execute(context, history, executor_selection(context, task["executor_selection"]),
                             task["executor_prompt"])

    def resume(self, context: ProjectContext, history: RunHistory, *, retry_executor: bool = False) -> RunHistory:
        """Revalidation keeps the work; an explicit retry consumes the previous budget."""
        self.resuming = True
        if context_snapshot(context) != history.context_json:
            raise ContractError("Resume requires the original frozen context/policy")
        if history.status not in {"stopped", "blocked", "revision_limit"} or history.task_json is None:
            raise ContractError(tr('workflow.stopped_task_contract_resumed'))
        task = json.loads(history.task_json)
        try:
            current = self.evidence.capture(context)
        except Exception as exc:
            return stopped(history, "evidence", str(exc))
        if check_paths(context, task, current).hard_failure:
            return stopped(history, "resume", tr('workflow.out_scope_changes_resolved'))
        if retry_executor and not task["allowed_paths"]:
            raise ContractError(tr('managed.read_tasks_cannot_retry'))
        has_execution = any(item.request.role == "executor" for item in history.attempts)
        if retry_executor and has_execution and history.revisions >= context.policy.max_revision_cycles:
            return replace(history, status="revision_limit", stop=None)
        history = replace(history, status="planned", stop=None, acceptance=None)
        history = self._prepare(context, history)
        if history.stop:
            return history
        if retry_executor:
            selection = executor_selection(context, task["executor_selection"])
            # Keep the last explicit correction selection, if any.
            executions = [item for item in history.attempts if item.request.role == "executor"]
            if executions:
                selection = executions[-1].request.selection
            prompt = task["executor_prompt"] + "\nExplicit retry: preserve existing implementation and resolve outstanding findings."
            latest_review = history.cycles[-1].review_json if history.cycles else None
            prompt += "\nHistorical review (does not change scope):\n" + (latest_review or "No review recorded")
            return self._execute(context, history, selection, prompt)
        return self._review_loop(context, history, None, [], allow_revision=False)

    def _format(self, context: ProjectContext, task: dict) -> tuple[str | None, str | None]:
        """P009-T019 (D133): formats the files the executor may touch under the contract, before capturing the
        evidence. Returns the frozen record (None if there is nothing to format) and the stop reason if the
        formatter did not run properly; a non-zero exit code is judged by validation and review."""
        profile = context.profile
        evidence = self.evidence.capture(context)
        excluded = set(check_paths(context, task, evidence).violations)
        paths = tuple(path for path in evidence.changed_paths if path not in excluded
                      and matches(path, profile.formatter_paths) and context.path(path).is_file())
        if not paths:
            return None, None
        command = Command(profile.formatter_argv + paths, timeout_seconds=FORMATTER_TIMEOUT_SECONDS)
        result, identity = run_identified_command(context, self.commands, command, self.journal)
        record = freeze({'command': asdict(command), 'command_id': identity, 'paths': list(paths),
                         'result': command_result_payload(result), 'note': FORMATTING_NOTE})
        if result.error or result.timed_out or result.exit_code is None:
            return record, 'Formatter failed: ' + (result.error or 'no exit code')
        return record, None

    def _execute(self, context: ProjectContext, history: RunHistory, selection: Selection, prompt: str) -> RunHistory:
        self._checkpoint(history, "executor")
        try:
            before = self.evidence.capture(context)
        except Exception as exc:
            return stopped(history, "evidence", str(exc))
        notes = json.loads(history.task_json).get("additional_notes")
        if isinstance(notes, str):
            prompt += NOTES_PREFIX + notes
        # No path/tool/network grant is inferred from prompt text.
        history, payload = self._invoke(context, history, "executor", selection, "execute-task", {
            "INSTRUCTIONS": prompt, "TASK_JSON": history.task_json,
            "PROFILE_INSTRUCTIONS": _profile_instructions(context)})
        if payload is None:
            return history
        malformed = _executor_output(payload)
        if malformed:
            return stopped(history, "executor", malformed)
        return self._review_loop(context, history, before, payload.get("permission_denials", []))

    def _review_loop(self, context: ProjectContext, history: RunHistory,
                     before: ContentEvidence | None, denials: list, *, allow_revision: bool = True) -> RunHistory:
        task = json.loads(history.task_json)
        while True:
            self._checkpoint(history, "validation")
            try:
                formatting = None
                if before is not None and context.profile.formatter_argv:
                    formatting, failure = self._format(context, task)
                    if failure:
                        return stopped(history, "formatter", failure)
                evidence = self.evidence.capture(context)
                policy = check_paths(context, task, evidence)
                source = next((a.request.id for a in reversed(history.attempts) if a.request.role == 'executor'), None)
                validation = run_validations(context, task, evidence, self.commands, self.journal,
                                             run_id=history.id, source_attempt_id=source)
                cycle = ReviewCycle(len(history.cycles), evidence, policy, validation, None, before, freeze(denials),
                                    formatting)
                history = replace(history, cycles=history.cycles + (cycle,))
                if self.evidence.capture(context) != evidence:
                    return stopped(history, "validation", tr('workflow.content_changed_during_validation'))
            except JournalError:
                raise
            except Exception as exc:
                return stopped(history, "evidence", str(exc))
            self._checkpoint(history, "reviewer")
            review_input = {
                "task": task, "evidence": strip_empty_provenance(asdict(evidence)), "policy": asdict(policy),
                "validation": strip_empty_provenance(validation_payload(validation)),
            }
            # P008-T003 and D133: keys only with layout v2, formatting or proposals, to preserve the earlier
            # input.
            if formatting is not None:
                review_input["formatting"] = json.loads(formatting)
            parity = documentation_parity(context, evidence.changed_paths)
            if parity is not None:
                review_input["documentation"] = parity
            proposals = _latest_executor_proposals(history)
            if proposals:
                review_input["executor_decision_proposals"] = proposals
            prompt = freeze(review_input)
            selection = Selection(context.policy.reviewer_model, context.policy.reviewer_effort, "Explicit independent review policy")
            history, data = self._invoke(context, history, "reviewer", selection, "review-task", {"INPUT_JSON": prompt})
            if data is None:
                return history
            # Even an invalid review is kept for diagnosis.
            cycle = replace(cycle, review_json=freeze(data))
            history = replace(history, cycles=history.cycles[:-1] + (cycle,))
            self._checkpoint(history, "reviewer")
            try:
                review_contract(context, task, data)
            except ContractError as exc:
                return stopped(history, "reviewer", str(exc))
            verdict = data["verdict"]
            if verdict == "ACCEPT":
                try:
                    decision = assess_acceptance(cycle, self.evidence.capture(context), context)
                except Exception as exc:
                    return stopped(history, "evidence", str(exc))
                history = replace(history, acceptance=decision)
                if not decision.eligible:
                    return stopped(history, "acceptance", "; ".join(decision.reasons))
                return replace(history, status="acceptance_ready", stop=None)
            if verdict == "BLOCKED":
                return replace(history, status="blocked", stop=None)
            if data.get("blocking_questions") or data.get("scope_grants"):
                return stopped(history, "permissions", tr('workflow.human_decision_required_task'))
            no_changes = before is not None and before == evidence
            previous = next((item for item in reversed(history.cycles[:-1]) if item.verdict == "REVISE"), None)
            signature = stalled_review_signature(data, validation)
            if no_changes and previous and signature == stalled_review_signature(json.loads(previous.review_json), previous.validation):
                return stopped(history, "revision", tr('workflow.revision_made_no_changes'))
            if denials and no_changes:
                return stopped(history, "permissions", tr('workflow.required_operations_denied_no'))
            if history.revisions >= context.policy.max_revision_cycles:
                return replace(history, status="revision_limit", stop=None)
            if not allow_revision:
                return stopped(history, 'revision', tr('workflow.review_requests_changes_retry'))
            selection = executor_selection(context, data["executor_selection"])
            prompt = data["next_prompt"]
            try:
                before = self.evidence.capture(context)
            except Exception as exc:
                return stopped(history, "evidence", str(exc))
            history, payload = self._invoke(context, history, "executor", selection, "revise-task", {
                "INSTRUCTIONS": prompt, "TASK_JSON": history.task_json, "REVIEW_JSON": cycle.review_json,
                "PROFILE_INSTRUCTIONS": _profile_instructions(context)})
            if payload is None:
                return history
            malformed = _executor_output(payload)
            if malformed:
                return stopped(history, "executor", malformed)
            denials = payload.get("permission_denials", [])
