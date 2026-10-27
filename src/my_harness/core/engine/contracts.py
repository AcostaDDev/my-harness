"""Frozen values and ports; no persisted operational state."""

from dataclasses import asdict, dataclass, replace
from fnmatch import fnmatchcase
from glob import has_magic
import json
import re
import shlex
from typing import Protocol, TYPE_CHECKING
from uuid import uuid4

from my_harness.core.engine.context import IntakeContext, ProjectContext, policy_payload, relative_path
from my_harness.i18n import tr

if TYPE_CHECKING:
    from my_harness.core.engine.journal import EngineJournal
    from my_harness.core.engine.acceptance import AcceptanceDecision
    from my_harness.core.engine.review import ReviewCycle


def freeze(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


MODEL_FORM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@\[\]-]{0,127}")


class ContractError(ValueError):
    pass


class IncompleteContract(ContractError):
    """The only reason that allows moving from document planning to an agent."""


@dataclass(frozen=True)
class Selection:
    model: str
    effort: str
    reason: str


def executor_selection(context: ProjectContext, data: object) -> Selection:
    if not isinstance(data, dict) or set(data) != {"model", "effort", "reason"}:
        raise ContractError(tr('contracts.executor_selection_requires_model'))
    policy = context.policy
    if policy.executor_mode == "open":
        # Open mode (D052): only the model shape and the executor provider's vocabulary.
        allowed = (isinstance(data["model"], str) and MODEL_FORM.fullmatch(data["model"]) is not None
                   and data["effort"] in policy.executor_effort_vocabulary)
    else:
        allowed = data["model"] in policy.executor_models and data["effort"] in policy.executor_efforts
    if not allowed or not isinstance(data["reason"], str) or not data["reason"].strip():
        raise ContractError(tr('contracts.executor_selection_outside_explicit'))
    return Selection(**data)


def command_text(item: object) -> object:
    """D056: an argv array becomes the equivalent shell-free string; validation splits it back unchanged."""
    if isinstance(item, list) and item and all(isinstance(arg, str) and arg for arg in item):
        return shlex.join(item)
    return item


def task_contract(context: ProjectContext, data: object, task_id: str, phase_id: str) -> str:
    if not isinstance(data, dict) or data.get("task_id") != task_id or data.get("phase_id") != phase_id:
        raise ContractError(tr('contracts.task_phase_identity_mismatch'))
    if isinstance(data.get("validation_commands"), list):
        # The frozen contract keeps strings; the agent's original output stays in its attempt.
        data = {**data, "validation_commands": [command_text(item) for item in data["validation_commands"]]}
    for field in ("title", "objective", "executor_prompt"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ContractError(tr('contracts.missing_task', field=field))
    for field in ("allowed_paths", "forbidden_paths", "acceptance_criteria", "validation_commands"):
        items = data.get(field)
        if not isinstance(items, list) or not all(isinstance(item, str) and item.strip() for item in items):
            raise ContractError(tr('contracts.invalid_task', field=field))
    if not data["acceptance_criteria"]:
        raise ContractError(tr('contracts.task_requires_acceptance_criteria'))
    data = {**data, **{field: directory_patterns(data[field]) for field in ("allowed_paths", "forbidden_paths")}}
    data = harness_owned_paths(context, data, task_id)
    for path in data["allowed_paths"] + data["forbidden_paths"]:
        try:
            relative_path(path)
        except ValueError as exc:
            raise ContractError(tr('contracts.task_file_scope_stay')) from exc
    # Denials take precedence in check_paths. Catch a contradictory concrete
    # allowlist before invoking a writer; never silently remove a prohibition.
    # Broad allow patterns may legitimately have narrower forbidden exceptions.
    for allowed in data["allowed_paths"]:
        if any(allowed == forbidden or forbidden in {"*", "**"}
               or (not has_magic(allowed) and fnmatchcase(allowed, forbidden))
               for forbidden in data["forbidden_paths"]):
            raise ContractError(tr('contracts.task_allowed_path_also', allowed=allowed))
    executor_selection(context, data.get("executor_selection"))
    return freeze(data)


def directory_patterns(paths: list[str]) -> list[str]:
    """P009-T017 (D129): `core/` names a directory, but fnmatch never matches a file against it. It is frozen as
    `core/**` so the contract, the executor and the path policy read the same scope. Idempotent; contracts frozen
    before keep their bytes and their literal reading."""
    return [path + "**" if path.endswith("/") else path for path in paths]


RECONCILE_TASK = re.compile(r".+-RECONCILE-\d+")


def harness_owned_paths(context: ProjectContext, data: dict, task_id: str) -> dict:
    """D072: with layout v2 the phase archive is never edited and the tracking documents belong to the
    harness; only phase reconciliation (`<phase>-RECONCILE-<n>`, server contract) edits their prose.
    D088: also that of DECISIONS, now a single register where reconciliation appends decisions. The root
    instruction files (AGENTS, CLAUDE, GEMINI) are written only by the harness, also against
    reconciliation (P008-T003).

    They are added as prohibitions (none is ever removed); a concrete allowed path contradicting them is
    rejected before the writer. Idempotent: an already frozen contract is reproduced unchanged."""
    from my_harness.core.engine.documents import layout
    target = layout(context)
    if target is None:
        return data
    owned = [] if RECONCILE_TASK.fullmatch(task_id) else list(target.harness_owned)
    extra = [path for path in (target.archive_dir + "/**", *owned, *target.instructions)
             if path not in data["forbidden_paths"]]
    return {**data, "forbidden_paths": data["forbidden_paths"] + extra} if extra else data


@dataclass(frozen=True)
class AgentRequest:
    id: str
    role: str
    selection: Selection
    prompt: str
    task_json: str | None
    context_json: str
    # No conversation/session handle: every request requires a new session.
    fresh_session: bool = True
    prompt_snapshot_json: str | None = None
    permission_snapshot_json: str | None = None


@dataclass(frozen=True)
class AgentResult:
    payload_json: str | None
    terminal_observed: bool = False
    exit_code: int | None = None
    raw_output: str = ""
    error: str | None = None
    status: str | None = None  # None preserves historical/fake adapter semantics.
    metadata_json: str | None = None


class AgentAdapter(Protocol):
    def invoke(self, context: ProjectContext, request: AgentRequest) -> AgentResult: ...


@dataclass(frozen=True)
class Attempt:
    request: AgentRequest
    result: AgentResult


@dataclass(frozen=True)
class OperationalStop:
    stage: str
    reason: str
    # No review verdict: an operational stop is not an agent judgement.


@dataclass(frozen=True)
class RunHistory:
    id: str
    context_json: str
    task_json: str | None = None
    attempts: tuple[Attempt, ...] = ()
    cycles: tuple["ReviewCycle", ...] = ()
    preparation_json: tuple[str, ...] = ()
    status: str = "planned"
    stop: OperationalStop | None = None
    stops: tuple[OperationalStop, ...] = ()
    acceptance: "AcceptanceDecision | None" = None
    prompt_catalog_json: str | None = None

    @property
    def revisions(self) -> int:
        return max(0, sum(item.request.role == "executor" for item in self.attempts) - 1)


def context_snapshot(context: ProjectContext) -> str:
    if isinstance(context, IntakeContext):
        return freeze({'capabilities': 'project-intake-1', 'root': str(context.root),
                       'policy': policy_payload(context.policy), 'next_steps_file': context.next_steps_file,
                       'state_file': context.state_file, 'documents': context.documents,
                       'work_language': context.work_language})
    profile = asdict(context.profile)
    if not profile['junit_reports']:
        profile.pop('junit_reports')  # Preserves earlier snapshots without reports.
    if not profile['data_model_paths']:
        profile.pop('data_model_paths')  # P008-T003: likewise without data model patterns.
    data = {"root": str(context.root), "profile": profile,
            "policy": policy_payload(context.policy), "next_steps_file": context.next_steps_file,
            "state_file": context.state_file}
    if context.documents is not None:
        data["documents"] = context.documents  # D072: absent preserves earlier snapshots.
    if context.work_language is not None:
        data["work_language"] = context.work_language  # D167: absent preserves earlier snapshots.
    return freeze(data)


def stop_history(history: RunHistory, stage: str, reason: str) -> RunHistory:
    stop = OperationalStop(stage, reason)
    return replace(history, status="stopped", stop=stop, stops=history.stops + (stop,))


def invoke_agent(context: ProjectContext, history: RunHistory, adapter: AgentAdapter,
                 role: str, selection: Selection, prompt: str,
                 journal: "EngineJournal | None" = None, *, prompt_snapshot_json: str | None = None) -> tuple[RunHistory, dict | None]:
    if isinstance(context, IntakeContext) and role != 'definition':
        raise ContractError(tr('profile_proposal.required'))
    request = AgentRequest(str(uuid4()), role, selection, prompt, history.task_json, history.context_json,
                           prompt_snapshot_json=prompt_snapshot_json)
    if journal:
        request = journal.agent_started(history, request) or request
    try:
        from my_harness.core.engine.permissions import snapshot_payload
        if snapshot_payload(request).get('denials'):
            raise ContractError(tr('contracts.explicit_permission_denial_blocks'))
        result = adapter.invoke(context, request)
    except Exception as exc:
        from my_harness.core.engine.journal import JournalError
        if isinstance(exc, JournalError):
            raise
        result = AgentResult(None, False, None, error=f"{type(exc).__name__}: {exc}")
    history = replace(history, attempts=history.attempts + (Attempt(request, result),))
    if journal:
        journal.checkpoint(history, role)
    try:
        if (result.error or result.terminal_observed is not True
                or type(result.exit_code) is not int or result.exit_code != 0):
            raise ContractError(result.error or tr('contracts.agent_stream_failed'))
        data = json.loads(result.payload_json or "")
        if not isinstance(data, dict) or data.get("is_error"):
            raise ContractError(tr('contracts.agent_result_invalid_reports'))
        freeze(data)  # Non-finite JSON is not a valid structured result either.
    except (ValueError, TypeError) as exc:
        return stop_history(history, role, str(exc)), None
    return history, data
