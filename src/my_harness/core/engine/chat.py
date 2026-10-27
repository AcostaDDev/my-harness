"""H4.1: contextual chat turn. Standard library; authority lives in SQLite.

Each turn is a new read-only invocation of the `chat` role (reviewer agent, Codex or Claude) with the explicit
context frozen when it was queued: project, phase, selected documents and evidence, plus the previous
turns. There is no provider session to resume. The output has a fixed schema; an invalid output stops
the turn without fallback or retry. The turn does not write: checkout evidence is captured before
and after, and any change invalidates the turn and its proposals.
A proposal executes nothing; only an explicit confirmation turns it into a normal task.
"""

from dataclasses import replace
import hashlib
import re

from my_harness.core.engine.contracts import ContractError, RunHistory, Selection, freeze, invoke_agent, stop_history
from my_harness.core.engine.document_text import CHAT_TASK
from my_harness.core.engine.prompts import dump_catalog, render_attempt
from my_harness.i18n import tr

TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
PROPOSAL_FIELDS = ("title", "objective", "scope", "acceptance_criteria", "validation", "rationale")
MAX_PROPOSALS = 5


def digest(value) -> str:
    return hashlib.sha256(freeze(value).encode("utf-8")).hexdigest()


def _text(value, name, *, empty=False, limit=20_000) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit:
        raise ContractError(tr('chat.text_limit' if empty else 'chat.text_required_limit', name=name, limit=limit))
    return value.strip()


def _texts(value, name, *, empty=True, limit=50) -> list[str]:
    if (not isinstance(value, list) or len(value) > limit or (not empty and not value)
            or not all(isinstance(item, str) and item.strip() and len(item) <= 4000 for item in value)):
        raise ContractError(tr('chat.chat_list_most_non', name=name, limit=limit))
    return [item.strip() for item in value]


def validate_chat_result(data: dict) -> dict:
    """Fixed schema: answer, references and structured proposals; nothing else."""
    if not isinstance(data, dict) or set(data) != {"answer", "references", "proposals"}:
        raise ContractError(tr('chat.chat_result_contain_exactly'))
    proposals = data["proposals"]
    if not isinstance(proposals, list) or len(proposals) > MAX_PROPOSALS:
        raise ContractError(tr('chat.chat_proposals_list_most', max_proposals=MAX_PROPOSALS))
    result = []
    for item in proposals:
        if not isinstance(item, dict) or set(item) != set(PROPOSAL_FIELDS):
            raise ContractError(tr('chat.proposal_fields', fields=", ".join(PROPOSAL_FIELDS)))
        result.append({"title": _text(item["title"], "proposal title", limit=200),
                       "objective": _text(item["objective"], "proposal objective", limit=4000),
                       "scope": _text(item["scope"], "proposal scope", empty=True, limit=4000),
                       "acceptance_criteria": _texts(item["acceptance_criteria"], "acceptance criteria", empty=False),
                       "validation": _texts(item["validation"], "validation"),
                       "rationale": _text(item["rationale"], "proposal rationale", empty=True, limit=4000)})
    return {"answer": _text(data["answer"], "answer"), "references": _texts(data["references"], "references"),
            "proposals": result}


def task_text(proposal: dict, task_id: str, origin: dict, language: str = 'en') -> str:
    """Plan section for the normal flow. No machine-readable allowed paths or executor:
    the planner sets the contract under the project policy, never the chat. `language`: the project's work
    language (D169); contexts without one keep the historical English labels."""
    if not TASK_ID.fullmatch(task_id):
        raise ValueError(tr('chat.task_id_1_120'))
    labels = CHAT_TASK[language]
    lines = [f"## {task_id} — {proposal['title']}", f"{labels['objective']} {proposal['objective']}"]
    if proposal["scope"]:
        lines.append(f"{labels['scope']} {proposal['scope']}")
    lines += [labels["acceptance"], *[f"- {item}" for item in proposal["acceptance_criteria"]]]
    if proposal["validation"]:
        lines += [labels["validation"], *[f"- {item}" for item in proposal["validation"]]]
    if proposal["rationale"]:
        lines.append(f"{labels['context']} {proposal['rationale']}")
    lines.append(labels["references"].format(conversation=origin['conversation_id'], turn=origin['turn_number'],
                                             proposal=origin['proposal_id'], sha256=origin['proposal_sha256']))
    return "\n".join(lines) + "\n"


def chat_turn(context, history: RunHistory, snapshot: dict, agents, evidence, journal,
              catalog, language=None) -> tuple[RunHistory, dict]:
    """A single invocation with the frozen request; the checkout evidence cannot change."""

    def done(history, status, reasons, *, result=None, checkout=None):
        return replace(history, status="completed", stop=None) if status == "ANSWERED" else history, {
            "status": status, "reasons": list(reasons), "result": result, "checkout": checkout}

    if digest(snapshot["context"]) != snapshot["context_sha256"]:
        raise ContractError("Frozen chat context changed after it was queued")
    journal.checkpoint(history, "chat")
    try:
        before = evidence.capture(context)
    except Exception as exc:
        reason = tr('chat.evidence_before', error=f"{type(exc).__name__}: {exc}")
        return done(stop_history(history, "evidence", reason), "FAILED", [reason])
    observed = {"base_revision": before.base_revision, "fingerprint": before.fingerprint}
    try:
        catalog_json = dump_catalog(catalog)
        message = snapshot['message']
        if snapshot['context'].get('head'):
            message += ("\nThis turn inspects an exported, read-only tree of commit " + snapshot['context']['head']
                        + ". The current directory is the snapshot; project.root identifies its source only. "
                        "Do not read the live source checkout. Uncommitted changes are not part of this snapshot.")
        prompt, prompt_snapshot = render_attempt(catalog, "chat-turn", {
            "CONTEXT_JSON": freeze(snapshot["context"]), "MESSAGE": message}, context, language)
    except (ValueError, KeyError, TypeError) as exc:
        return done(stop_history(history, "prompts", str(exc)), "FAILED", [str(exc)], checkout={"before": observed})
    history = replace(history, prompt_catalog_json=catalog_json)
    selection = Selection(context.policy.planner_model, context.policy.planner_effort,
                          "Explicit planner policy for read-only chat proposals")
    history, data = invoke_agent(context, history, agents, "chat", selection, prompt, journal,
                                 prompt_snapshot_json=prompt_snapshot)
    try:
        after = evidence.capture(context)
    except Exception as exc:
        reason = tr('chat.evidence_after', error=f"{type(exc).__name__}: {exc}")
        return done(stop_history(history, "evidence", reason) if history.stop is None else history, "FAILED",
                    [reason], result=data, checkout={"before": observed, "after": None})
    checkout = {"before": observed, "after": {"base_revision": after.base_revision, "fingerprint": after.fingerprint},
                "unchanged": after == before}
    if after != before:
        reason = tr('chat.checkout_changed_turn')
        return done(stop_history(history, "chat", reason) if history.stop is None else history, "FAILED", [reason],
                    result=data, checkout=checkout)
    if data is None:
        return done(history, "FAILED", [history.stop.reason], checkout=checkout)
    try:
        result = validate_chat_result(data)
    except ContractError as exc:
        return done(stop_history(history, "chat", str(exc)), "FAILED", [str(exc)], result=data, checkout=checkout)
    return done(history, "ANSWERED", [], result=result, checkout=checkout)
