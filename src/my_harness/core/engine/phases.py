"""H3.3: phase gates with explicit ports. Standard library; authority lives in SQLite.

READY is bound to exact content: definition, clean Git HEAD/fingerprint, adopted
documents, commits of accepted tasks and questions. Closing observes that content
again before any Git effect. D088: closing and archiving in a single flow,
with an optional tag on the evaluated HEAD and a reconcilable document commit.
Earlier snapshots keep the closing protocol they froze.
"""

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import re
from typing import Protocol

from my_harness.core.engine.commit import CommitError, git_provenance
from my_harness.core.engine.context import ProjectContext, relative_path
from my_harness.core.engine.contracts import (
    ContractError, RunHistory, Selection, freeze, invoke_agent, stop_history,
)
from my_harness.core.engine.evidence import ContentEvidence, PathPolicyResult, strip_empty_provenance
from my_harness.core.engine.prompts import dump_catalog, render_attempt
from my_harness.core.engine.validation import run_validations, validation_payload
from my_harness.core.engine.review import ReviewCycle
from my_harness.i18n import tr

PHASE_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
TAG_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*")
VERDICTS = ("READY", "REVISE", "BLOCKED")
TAG_KINDS = ("lightweight", "annotated")
# Check result → phase status. FAILED returns to the status before the check.
CHECK_STATUS = {"READY": "READY_TO_CLOSE", "REVISE": "NEEDS_RECONCILIATION", "BLOCKED": "BLOCKED",
                "NEEDS_RECONCILIATION": "NEEDS_RECONCILIATION", "NOT_READY": "ACTIVE"}


def digest(value) -> str:
    return hashlib.sha256(freeze(value).encode("utf-8")).hexdigest()


def _texts(value, name, *, empty=False) -> list[str]:
    if (not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value)
            or (not empty and not value) or len(set(value)) != len(value)):
        raise ContractError(tr('phases.phase_list_distinct_non', name=name))
    return [item.strip() for item in value]


def phase_definition(context: ProjectContext, data: dict) -> dict:
    """Definition frozen by whoever creates the phase; an agent never widens it."""
    if not isinstance(data, dict) or set(data) != {"code", "objective", "exit_criteria", "tasks", "documents", "tag"}:
        raise ContractError(tr('phases.phase_requires_code_objective'))
    code, objective, tag = data["code"], data["objective"], data["tag"]
    if not isinstance(code, str) or not PHASE_CODE.fullmatch(code):
        raise ContractError(tr('phases.phase_code_1_120'))
    if not isinstance(objective, str) or not objective.strip():
        raise ContractError(tr('phases.phase_objective_required'))
    documents = _texts(data["documents"], "documents")
    for path in documents:
        relative_path(path)
        context.path(path)
    if tag is not None and (not isinstance(tag, str) or len(tag) > 100 or not TAG_NAME.fullmatch(tag)
                            or tag.endswith(".lock")):
        raise ContractError(tr('phases.tag_null_simple_tag'))
    return {"code": code, "objective": objective.strip(), "exit_criteria": _texts(data["exit_criteria"], "exit criteria"),
            "tasks": _texts(data["tasks"], "tasks", empty=True), "documents": documents, "tag": tag}


def document_hashes(context: ProjectContext, paths) -> dict[str, str | None]:
    """SHA-256 of regular files without links; None if they do not exist (explicit absence)."""
    result = {}
    for path in paths:
        item = context.path(path)
        if item.is_symlink() or (item.exists() and not item.is_file()):
            raise ValueError(tr('phases.phase_document_regular_file', path=path))
        result[path] = hashlib.sha256(item.read_bytes()).hexdigest() if item.exists() else None
    return result


class PhaseGit(Protocol):
    def capture(self, context: ProjectContext) -> ContentEvidence: ...
    def contains(self, context: ProjectContext, commit: str) -> bool: ...
    def seal_tag(self, context: ProjectContext, intent: dict) -> str: ...
    def tag(self, context: ProjectContext, intent: dict) -> dict: ...


def tag_message(definition: dict, binding_sha256: str) -> str:
    """No operation identifier: a later reconciling close produces the same object."""
    return (f"Phase {definition['code']} closed\n\nHarness-Phase: {definition['code']}\n"
            f"Harness-Ready-Binding: {binding_sha256}\n")


def tag_intent(snapshot: dict, git: PhaseGit, context: ProjectContext, now=None) -> dict:
    """Complete intent before the effect. An annotated tag fixes message, identity and date, and with
    them its id; if an earlier close left an uncertain intent for the same READY, it is reused."""
    ready, name = snapshot["ready"], snapshot["definition"]["tag"]
    kind = snapshot.get("tag_kind", "lightweight")
    if kind not in TAG_KINDS:
        raise ValueError("Unknown tag kind")
    intent = {"operation_id": snapshot["operation_id"], "ref": f"refs/tags/{name}", "kind": kind,
              "target": ready["binding"]["head"], "binding_sha256": ready["binding_sha256"]}
    if kind == "annotated":
        previous = snapshot.get("previous_tag_intent") or {}
        if all(previous.get(key) == intent[key] for key in ("ref", "kind", "target", "binding_sha256")):
            fixed = {key: previous[key] for key in ("message", "tagger_name", "tagger_email", "tagged_at")}
        else:
            instant = (now or (lambda: datetime.now(timezone.utc)))()
            if instant.tzinfo is None:
                raise ValueError("Clock must return an aware time")
            fixed = {"message": tag_message(snapshot["definition"], ready["binding_sha256"]),
                     "tagger_name": git.identity.name, "tagger_email": git.identity.email,
                     "tagged_at": int(instant.timestamp())}
        intent.update(fixed)
        intent["object"] = git.seal_tag(context, intent)
    return intent


def binding(snapshot: dict, evidence: ContentEvidence, documents: dict) -> dict:
    return {"definition_sha256": snapshot["definition_sha256"], "head": evidence.base_revision,
            "fingerprint": evidence.fingerprint, "documents": documents,
            "tasks": {task: (None if item is None else {"run_id": item["run_id"], "commit": item["commit"]})
                      for task, item in snapshot["tasks"].items()},
            "questions_sha256": snapshot["questions_sha256"]}


def observe(context: ProjectContext, snapshot: dict, git: PhaseGit):
    """Current content and the reasons it cannot be ready; reads only."""
    definition = snapshot["definition"]
    documents = document_hashes(context, definition["documents"])
    drift = sorted(path for path, value in documents.items() if snapshot["documents"].get(path) != value)
    evidence = git.capture(context)
    reasons = []
    try:
        git_provenance(evidence)
    except CommitError as exc:
        reasons.append(tr('phases.phase_gates_require_git', exc=exc))
    if evidence.changed_paths:
        reasons.append(tr('phases.uncommitted_changes', paths=", ".join(evidence.changed_paths[:20])))
    for task in (() if snapshot.get('terminal') == 'ABANDONED' else definition["tasks"]):
        item = snapshot["tasks"].get(task)
        if item is None:
            reasons.append(tr('phases.task_has_no_committed', task=task))
        elif not git.contains(context, item["commit"]):
            reasons.append(tr('phases.task_commit_not_reachable', task=task, commit=item['commit']))
    return evidence, documents, drift, reasons


def validate_phase_result(definition: dict, data: dict) -> dict:
    if data.get("phase_id") != definition["code"] or data.get("verdict") not in VERDICTS:
        raise ContractError(tr('phases.phase_review_name_phase'))
    if not isinstance(data.get("summary"), str):
        raise ContractError(tr('phases.phase_review_summary_required'))
    for key in ("required_actions", "blocking_questions"):
        value = data.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
            raise ContractError(tr('phases.phase_review_list_texts', key=key))
    results = data.get("exit_criteria_results")
    if (not isinstance(results, list) or not all(
            isinstance(item, dict) and isinstance(item.get("criterion"), str) and type(item.get("passed")) is bool
            and isinstance(item.get("evidence"), str) for item in results)
            or sorted(item["criterion"] for item in results) != sorted(definition["exit_criteria"])):
        raise ContractError(tr('phases.phase_review_evaluate_each'))
    if data["verdict"] == "READY" and (not all(item["passed"] for item in results)
                                       or data["required_actions"] or data["blocking_questions"]):
        raise ContractError(tr('phases.ready_requires_every_exit'))
    if data["verdict"] == "REVISE" and not data["required_actions"]:
        raise ContractError(tr('phases.revise_requires_concrete_required'))
    return data


def check_phase(context: ProjectContext, history: RunHistory, snapshot: dict, agents, commands, git: PhaseGit,
                journal, catalog, language=None) -> tuple[RunHistory, dict]:
    """Deterministic gates before spending a call; the agent only evaluates."""
    definition = snapshot["definition"]

    def outcome(verdict, reasons, *, bound=None, result=None, validation=None, questions=()):
        return {"verdict": verdict, "reasons": list(reasons), "binding": bound,
                "binding_sha256": digest(bound) if bound else None, "result": result,
                "validation": validation, "questions": list(questions)}

    def done(history, value):
        return replace(history, status="completed", stop=None), value

    if snapshot["open_questions"]:
        return done(history, outcome("BLOCKED", [tr('phases.questions_first')]))
    journal.checkpoint(history, "phase")
    try:
        evidence, documents, drift, reasons = observe(context, snapshot, git)
    except Exception as exc:
        return done(stop_history(history, "evidence", f"{type(exc).__name__}: {exc}"),
                    outcome("FAILED", [tr('phases.evidence_not_captured', error=exc)]))
    if drift:
        return done(history, outcome("NEEDS_RECONCILIATION",
                                     [tr('phases.documents_drift', paths=", ".join(drift))]))
    from my_harness.core.engine.documents import BUDGETS, base_section
    try:
        state = context.path(context.state_file).read_bytes()
        base = base_section(state.decode('utf-8')) or ''
    except (ValueError, OSError, UnicodeError) as exc:
        return done(history, outcome('FAILED', [tr('phases.state_unreadable', error=exc)]))
    if len(state) > BUDGETS['state'] or len(base.encode('utf-8')) > BUDGETS['base']:
        return done(history, outcome("NEEDS_RECONCILIATION", [
            tr('phases.compact_state')]))
    if reasons:
        return done(history, outcome("NOT_READY", reasons))
    bound = binding(snapshot, evidence, documents)
    journal.checkpoint(history, "validation")
    report = run_validations(context, {"validation_commands": []}, evidence, commands, journal, run_id=history.id)
    if any(entry.reports for entry in report.entries):
        history = replace(history, cycles=history.cycles + (
            ReviewCycle(len(history.cycles), evidence, PathPolicyResult(()), report, None, None),))
        journal.checkpoint(history, 'validation')
    validation = strip_empty_provenance(validation_payload(report, include_cases=False))
    if not report.all_passed:
        return done(history, outcome("NOT_READY", [tr('phases.baseline_failed')], validation=validation))
    try:
        catalog_json = dump_catalog(catalog)
        payload = {"phase": definition, "head": evidence.base_revision, "fingerprint": evidence.fingerprint,
                   "documents": documents, "tasks": snapshot["task_evidence"], "validation": validation,
                   "answered_questions": snapshot["answered_questions"]}
        prompt, prompt_snapshot = render_attempt(catalog, "close-phase", {
            "PHASE_ID": definition["code"], "EVIDENCE_JSON": freeze(payload)}, context, language)
    except (ValueError, KeyError, TypeError) as exc:
        return done(stop_history(history, "prompts", str(exc)), outcome("FAILED", [str(exc)], validation=validation))
    history = replace(history, prompt_catalog_json=catalog_json)
    selection = Selection(context.policy.reviewer_model, context.policy.reviewer_effort,
                          "Explicit independent phase review policy")
    history, data = invoke_agent(context, history, agents, "phase", selection, prompt, journal,
                                 prompt_snapshot_json=prompt_snapshot)
    if data is None:
        return done(history, outcome("FAILED", [history.stop.reason], validation=validation))
    try:
        validate_phase_result(definition, data)
    except ContractError as exc:
        return done(stop_history(history, "phase", str(exc)),
                    outcome("FAILED", [str(exc)], result=data, validation=validation))
    try:
        after = observe(context, snapshot, git)
    except Exception as exc:
        return done(stop_history(history, "evidence", f"{type(exc).__name__}: {exc}"),
                    outcome("FAILED", [tr('phases.evidence_not_recaptured', error=exc)], result=data))
    if after[0] != evidence or after[1] != documents:
        return done(history, outcome("NOT_READY", [tr('phases.content_changed_check')],
                                     result=data, validation=validation))
    verdict = data["verdict"]
    reasons = [] if verdict == "READY" else (data["required_actions"] or [data["summary"]])
    return done(history, outcome(verdict, reasons, bound=bound if verdict == "READY" else None, result=data,
                                 validation=validation, questions=data["blocking_questions"]))


def close_phase(context: ProjectContext, history: RunHistory, snapshot: dict, git: PhaseGit,
                journal, now=None) -> tuple[RunHistory, dict]:
    """Re-observes READY; seals, tags and archives. An existing intent is only reconciled."""
    ready = snapshot["ready"]
    done = replace(history, status="completed", stop=None)
    closure = snapshot.get('closure')
    continuing = closure and closure.get('commit_intent')
    if not continuing and not snapshot["authorization"]["usable"]:
        return done, {"status": "EXPIRED", "reasons": [tr('phases.close_expired')]}
    journal.checkpoint(history, "phase")
    if not continuing:
        evidence, documents, drift, reasons = observe(context, snapshot, git)
        current = binding(snapshot, evidence, documents)
        if drift:
            reasons.append(tr('phases.documents_changed_ready', paths=", ".join(drift)))
        changed = sorted(key for key in current if current[key] != ready["binding"].get(key))
        if changed:
            reasons.append(tr('phases.ready_stale_changed', parts=", ".join(changed)))
        if reasons:
            return done, {"status": "STALE", "reasons": reasons, "observed_sha256": digest(current)}
    if closure:
        from my_harness.core.engine.document_ops import seal_operation, BaseChanged
        try:
            sealed = seal_operation(context, history, closure, git, journal, now,
                                    label=f"archive {snapshot['definition']['code']}")
        except BaseChanged as exc:
            return done, {'status': 'STALE', 'reasons': [str(exc)]}
    tag = None
    if snapshot["definition"]["tag"] is not None and snapshot.get('terminal', 'CLOSED') == 'CLOSED':
        intent = snapshot.get('tag_intent') or tag_intent(snapshot, git, context, now)
        if not snapshot.get('tag_intent'):
            journal.tag_intent(intent)
        tag = git.tag(context, intent)
        if tag["status"] == "conflict":
            return done, {"status": "FAILED", "reasons": [tag["diagnostic"]], "tag": tag}
    result = {'status': snapshot.get('terminal', 'CLOSED'), 'reasons': [], 'tag': tag,
              'binding_sha256': ready['binding_sha256']}
    if closure:
        outcome = git.execute_documents(context, sealed, closure['preview']['documents'])
        if outcome.status == 'invalidated':
            return done, {'status': 'STALE', 'reasons': [outcome.diagnostic], 'tag': tag}
        result.update(commit=outcome.commit, tree=outcome.tree, archive=closure['preview']['archive'],
                      reconciled=outcome.status == 'reconciled')
        from my_harness.core.engine.documents import require_layout
        work = context.path(require_layout(context).phase_dir)
        if work.exists():
            for folder in sorted(work.rglob('*'), key=lambda item: len(item.parts), reverse=True):
                if folder.is_dir() and not folder.is_symlink():
                    folder.rmdir()
    return done, result
