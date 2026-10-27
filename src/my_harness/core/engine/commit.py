"""H2.4 contract of the accepted commit: intent, result and orchestration.

Standard library and ports. Git subprocesses and SQLite live in adapters.
The commit is created from the reviewed tree (and only declared mechanical
updates) and its identity is deterministic: after a crash it is checked before
being repeated. ACCEPT/acceptance_ready do not amount to an existing commit.
"""

from dataclasses import asdict, dataclass
import base64
from datetime import datetime, timezone
import json
import re
from typing import Callable, Protocol
from uuid import uuid4

from my_harness.core.engine.acceptance import assess_acceptance
from my_harness.core.engine.context import ProjectContext, relative_path
from my_harness.core.engine.contracts import RunHistory, freeze, stop_history
from my_harness.core.engine.evidence import ContentEvidence, matches
from my_harness.i18n import tr

GIT_FORMAT = "git-v1"
_OBJECT_ID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


class CommitError(RuntimeError):
    """Invalid precondition or commit contract; no effect is created."""


class CommitUncertain(CommitError):
    """What happened cannot be determined; requires manual recovery with evidence."""


@dataclass(frozen=True)
class GitIdentity:
    name: str
    email: str

    def __post_init__(self):
        for value in (self.name, self.email):
            if (not isinstance(value, str) or not value.strip() or value != value.strip()
                    or any(char in value for char in "<>\n\r\0")):
                raise ValueError(tr('commit.explicit_commit_identity_required'))


@dataclass(frozen=True)
class MechanicalUpdate:
    """Content written by the harness; UTF-8 by default, base64 bytes or deletion for the D088 archive."""

    path: str
    content: str | None
    reason: str
    encoding: str = 'utf-8'

    def __post_init__(self):
        relative_path(self.path)
        if self.path.startswith(".git/") or self.path == ".git":
            raise ValueError(tr('commit.mechanical_updates_cannot_target'))
        if self.encoding not in ('utf-8', 'base64'):
            raise ValueError('Unknown mechanical content encoding')
        if self.content is not None and (not isinstance(self.content, str) or "\0" in self.content):
            raise ValueError(tr('commit.mechanical_content_nul_free'))
        self.bytes()  # also validates the base64 before sealing the intent
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(tr('commit.mechanical_updates_require_explicit'))

    def bytes(self) -> bytes | None:
        """None deletes the file; base64 keeps binary phase artifacts byte for byte."""
        if self.content is None:
            return None
        return (base64.b64decode(self.content, validate=True) if self.encoding == 'base64'
                else self.content.encode('utf-8'))


@dataclass(frozen=True)
class GitProvenance:
    base_revision: str
    base_tree: str
    worktree_tree: str
    index_tree: str


def git_provenance(evidence: ContentEvidence) -> GitProvenance:
    if evidence.provenance_json is None:
        raise CommitError(tr('commit.evidence_has_no_git'))
    try:
        data = json.loads(evidence.provenance_json)
        if not isinstance(data, dict) or data.get("format") != GIT_FORMAT:
            raise ValueError
        values = [evidence.base_revision] + [data[key] for key in ("base_tree", "worktree_tree", "index_tree")]
        if not all(isinstance(item, str) and _OBJECT_ID.fullmatch(item) for item in values):
            raise ValueError
    except (ValueError, KeyError) as exc:
        raise CommitError("Evidence provenance is not valid Git provenance") from exc
    return GitProvenance(evidence.base_revision, data["base_tree"], data["worktree_tree"], data["index_tree"])


@dataclass(frozen=True)
class CommitPlan:
    """Data fixed before the adapter computes the expected tree/commit."""

    base_revision: str
    reviewed_tree: str
    mechanical: tuple[MechanicalUpdate, ...]
    message: str
    author_name: str
    author_email: str
    committed_at: int


@dataclass(frozen=True)
class CommitIntent:
    operation_id: str
    run_id: str
    task_id: str
    base_revision: str
    reviewed_fingerprint: str
    reviewed_tree: str
    reviewed_index_tree: str
    reviewed_paths: tuple[str, ...]
    mechanical: tuple[MechanicalUpdate, ...]
    expected_tree: str
    expected_commit: str
    message: str
    author_name: str
    author_email: str
    committed_at: int

    def to_json(self) -> str:
        return freeze(asdict(self))

    @staticmethod
    def from_json(text: str) -> "CommitIntent":
        data = json.loads(text)
        data["reviewed_paths"] = tuple(data["reviewed_paths"])
        data["mechanical"] = tuple(MechanicalUpdate(**item) for item in data["mechanical"])
        return CommitIntent(**data)


@dataclass(frozen=True)
class CommitOutcome:
    # committed: this execution moved the reference. reconciled: it already existed.
    # invalidated: no effect; the reviewed content/base are no longer current.
    status: str
    operation_id: str | None
    commit: str | None = None
    tree: str | None = None
    head: str | None = None
    diagnostic: str | None = None
    observed_fingerprint: str | None = None
    index: str | None = None  # refreshed | already_current | left_untouched

    def __post_init__(self):
        if self.status not in {"committed", "reconciled", "invalidated"}:
            raise ValueError("Unknown commit outcome status")

    def to_json(self) -> str:
        return freeze(asdict(self))

    @staticmethod
    def from_json(text: str) -> "CommitOutcome":
        return CommitOutcome(**json.loads(text))


class CommitWriter(Protocol):
    identity: GitIdentity

    def capture(self, context: ProjectContext) -> ContentEvidence: ...
    def seal(self, context: ProjectContext, plan: CommitPlan) -> tuple[str, str]: ...
    def execute(self, context: ProjectContext, intent: CommitIntent) -> CommitOutcome: ...


class CommitJournal(Protocol):
    def pending_commit(self) -> CommitIntent | None: ...
    def commit_intent(self, intent: CommitIntent) -> None: ...
    def commit_result(self, outcome: CommitOutcome) -> None: ...
    def commit_invalidated(self, outcome: CommitOutcome) -> None: ...


def validate_mechanical_updates(context: ProjectContext, reviewed_paths: tuple[str, ...],
                                updates: tuple[MechanicalUpdate, ...], block_paths: frozenset[str] = frozenset()) -> None:
    """Harness-owned paths: never sensitive nor overlapping with the reviewed content.

    D072: `block_paths` are reviewed documents whose only mechanical change is regenerating a managed
    block over the reviewed content (phase reconciliation); the reviewed prose is preserved."""
    seen: set[str] = set()
    for update in updates:
        if not isinstance(update, MechanicalUpdate):
            raise CommitError("Mechanical updates must be explicit MechanicalUpdate values")
        if update.path in seen:
            raise CommitError(tr('commit.duplicate_mechanical_update_path'))
        seen.add(update.path)
        if update.path in reviewed_paths and update.path not in block_paths:
            raise CommitError(tr('commit.mechanical_update_overlaps_reviewed'))
        profile = context.profile
        if matches(update.path, profile.sensitive_paths) and not matches(update.path, profile.sensitive_allowlist):
            raise CommitError(tr('commit.mechanical_update_targets_sensitive'))
        try:
            context.path(update.path)
        except ValueError as exc:
            raise CommitError(tr('commit.mechanical_update_path_unsafe', exc=exc)) from exc


def commit_message(prefix: str, task: dict, run_id: str, operation_id: str, fingerprint: str,
                   reviewed_tree: str, updates: tuple[MechanicalUpdate, ...]) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", prefix):
        raise CommitError(tr('commit.invalid_commit_message_prefix'))
    title = " ".join(str(task["title"]).split())
    lines = [f"{prefix}: accept {task['task_id']} - {title}", "",
             f"Harness-Operation: {operation_id}", f"Harness-Run: {run_id}",
             f"Harness-Reviewed-Fingerprint: {fingerprint}", f"Harness-Reviewed-Tree: {reviewed_tree}"]
    lines += [f"Harness-Mechanical: {update.path}" for update in sorted(updates, key=lambda item: item.path)]
    return "\n".join(lines) + "\n"


def _invalidated(reason: str, observed: ContentEvidence, expected_fingerprint: str) -> CommitOutcome:
    return CommitOutcome(
        "invalidated", None, head=observed.base_revision, observed_fingerprint=observed.fingerprint,
        diagnostic=tr('commit.invalidated_fingerprint', reason=reason, reviewed=expected_fingerprint,
                      observed=observed.fingerprint))


def prepare_commit(context: ProjectContext, history: RunHistory, writer: CommitWriter, *,
                   mechanical: tuple[MechanicalUpdate, ...] = (), message_prefix: str = "harness",
                   now: Callable[[], datetime] | None = None,
                   operation_id: str | None = None,
                   block_paths: frozenset[str] = frozenset()) -> CommitIntent | CommitOutcome:
    """Checks current acceptance and fixes the intent; no effects on refs or files."""
    if (history.status != "acceptance_ready" or history.acceptance is None or not history.acceptance.eligible
            or not history.cycles or history.task_json is None):
        raise CommitError(tr('managed.eligible_acceptance_ready_run'))
    cycle = history.cycles[-1]
    reviewed = history.acceptance.evidence
    if cycle.evidence != reviewed:
        raise CommitError(tr('commit.acceptance_evidence_does_not'))
    provenance = git_provenance(reviewed)
    current = writer.capture(context)
    decision = assess_acceptance(cycle, current, context)
    if not decision.eligible:
        return _invalidated("; ".join(decision.reasons), current, reviewed.fingerprint)
    task = json.loads(history.task_json)
    validate_mechanical_updates(context, reviewed.changed_paths, tuple(mechanical), block_paths)
    operation = operation_id or str(uuid4())
    message = commit_message(message_prefix, task, history.id, operation, reviewed.fingerprint,
                             provenance.worktree_tree, tuple(mechanical))
    instant = (now or (lambda: datetime.now(timezone.utc)))()
    if instant.tzinfo is None:
        raise ValueError("Clock must return an aware time")
    plan = CommitPlan(provenance.base_revision, provenance.worktree_tree, tuple(mechanical), message,
                      writer.identity.name, writer.identity.email, int(instant.timestamp()))
    expected_tree, expected_commit = writer.seal(context, plan)
    return CommitIntent(
        operation_id=operation, run_id=history.id, task_id=task["task_id"],
        base_revision=provenance.base_revision, reviewed_fingerprint=reviewed.fingerprint,
        reviewed_tree=provenance.worktree_tree, reviewed_index_tree=provenance.index_tree,
        reviewed_paths=tuple(reviewed.changed_paths), mechanical=tuple(mechanical),
        expected_tree=expected_tree, expected_commit=expected_commit, message=message,
        author_name=plan.author_name, author_email=plan.author_email, committed_at=plan.committed_at)


def commit_accepted(context: ProjectContext, history: RunHistory, writer: CommitWriter,
                    journal: CommitJournal, *, mechanical: tuple[MechanicalUpdate, ...] = (),
                    message_prefix: str = "harness", now: Callable[[], datetime] | None = None,
                    operation_id: str | None = None,
                    block_paths: frozenset[str] = frozenset()) -> tuple[RunHistory, CommitOutcome]:
    """Intent persisted before the effect, result afterwards, reconciling on resume."""
    intent = journal.pending_commit()
    if intent is not None:
        if intent.run_id != history.id:
            raise CommitError("Pending commit intent belongs to a different run")
    else:
        prepared = prepare_commit(context, history, writer, mechanical=mechanical,
                                  message_prefix=message_prefix, now=now, operation_id=operation_id,
                                  block_paths=block_paths)
        if isinstance(prepared, CommitOutcome):
            # No intent and no effect: the fact is kept and revalidation is required.
            journal.commit_invalidated(prepared)
            return stop_history(history, "commit", prepared.diagnostic or tr('commit.acceptance_invalidated')), prepared
        intent = prepared
        journal.commit_intent(intent)
    outcome = writer.execute(context, intent)
    journal.commit_result(outcome)
    if outcome.status == "invalidated":
        history = stop_history(history, "commit", outcome.diagnostic or tr('commit.acceptance_invalidated'))
    return history, outcome
