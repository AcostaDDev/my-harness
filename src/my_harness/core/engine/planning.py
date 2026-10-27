"""Document planning characterized from the legacy engine (H0.1)."""

import re

from my_harness.core.engine.context import ProjectContext
from my_harness.core.engine.contracts import IncompleteContract, ContractError, task_contract
from my_harness.i18n import tr


# D072: «Restricciones compartidas» is the Spanish alias of the shared section.
SHARED_HEADING = r"^##\s+(?:Shared|Restricciones compartidas)\b.*$"
TASK_RE = re.compile(r"^##\s+(P\d{3}-T\d{3})\s+[—-]\s+(.+?)\s*$", re.MULTILINE)
FIELD_RE = re.compile(r"^\*\*([^*\n]+?)(?::\*\*|\*\*:?)[ \t]*(.*)$")
BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")
EXECUTOR_RE = re.compile(r"^`?([a-z0-9.-]+)`?\s*/\s*`?([a-z]+)`?\s*(?:[—–-]+\s*(.*))?$", re.DOTALL)
# D072: Spanish aliases after the English ones; an English plan is interpreted as before.
FIELD_NAMES = {
    "objective": ("objective", "objetivo"), "business_context": ("business context", "contexto de negocio"),
    "scope": ("implementation scope / allowed scope", "implementation scope", "scope", "alcance"),
    "allowed_paths": ("allowed paths", "rutas permitidas"), "forbidden_paths": ("forbidden paths", "rutas prohibidas"),
    "forbidden_scope": ("forbidden scope", "out of scope", "fuera de alcance"),
    "acceptance_criteria": ("acceptance criteria", "criterios de aceptación"),
    "constraints": ("implementation constraints", "known constraints", "constraints", "restricciones"),
    "validation": ("validation", "validación"), "validation_commands": ("validation commands", "comandos de validación"),
    "deliverables": ("deliverables", "expected deliverables", "entregables"),
    "references": ("references", "documentation references", "referencias"),
    "risk_notes": ("risk notes", "risks", "riesgos"), "executor": ("executor", "ejecutor"),
}


def next_task_id(text: str, last_accepted_task: str | None) -> str | None:
    ids = [match.group(1) for match in TASK_RE.finditer(text)]
    if not ids or len(ids) != len(set(ids)):
        raise ContractError(tr('planning.missing_duplicate_task_headings'))
    if last_accepted_task is None:
        return ids[0]
    if last_accepted_task not in ids:
        raise ContractError(tr('planning.last_accepted_task_absent'))
    index = ids.index(last_accepted_task) + 1
    return ids[index] if index < len(ids) else None


def section(text: str, heading: str) -> str:
    match = re.search(heading, text, re.MULTILINE)
    if not match:
        return ""
    following = re.search(r"^##\s", text[match.end():], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[match.start():end].strip()


def task_heading(task_id: str) -> str:
    return rf"^##\s+{re.escape(task_id)}\s+[—-].*$"


def task_sources(context: ProjectContext) -> dict:
    """P009-T020: tasks of the live NEXT_STEPS, to queue them without writing the contract. The text of each one
    is its literal section, preceded by the shared constraints when the document has them: exactly what the
    planner reads from the submitted text (`section`). A repeated id is not offered, since it cannot be chosen."""
    from my_harness.core.engine.document_ops import read_text, text_hash
    text = read_text(context, context.next_steps_file)
    result = {"path": context.next_steps_file, "sha256": None, "items": [], "diagnostics": []}
    if text is None:
        return {**result, "diagnostics": [tr('planning.next_steps_missing', path=context.next_steps_file)]}
    shared = section(text, SHARED_HEADING)
    ids = [match.group(1) for match in TASK_RE.finditer(text)]
    for match in TASK_RE.finditer(text):
        task_id = match.group(1)
        if ids.count(task_id) > 1:
            if f"{task_id} is duplicated" not in result["diagnostics"]:
                result["diagnostics"].append(f"{task_id} is duplicated")
            continue
        body = section(text, task_heading(task_id))
        value = f"{shared}\n\n{body}" if shared else body
        result["items"].append({"task_id": task_id, "phase_id": task_id.split("-")[0], "title": match.group(2),
                                "text": value, "sha256": text_hash(value)})
    return {**result, "sha256": text_hash(text)}


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def bullet_items(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        match = BULLET_RE.match(line)
        if match:
            items.append(match.group(1).strip())
        elif items and line.strip():
            items[-1] += " " + line.strip()
    return items


def text_items(text: str) -> list[str]:
    return bullet_items(text) or ([collapse(text)] if text.strip() else [])


def backticked(text: str) -> list[str]:
    return [value.strip() for value in re.findall(r"`([^`\n]+)`", text) if value.strip()]


def deterministic_task(context: ProjectContext, task_id: str, phase_id: str, text: str) -> str:
    task_section = section(text, task_heading(task_id))
    if not task_section:
        raise IncompleteContract(tr('planning.task_section_absent'))
    heading = TASK_RE.search(task_section)
    if heading is None:
        raise IncompleteContract(tr('planning.task_heading_invalid'))
    raw: dict[str, str] = {}
    current = None
    for line in task_section.splitlines()[1:]:
        match = FIELD_RE.match(line.strip())
        if match:
            current = match.group(1).strip().rstrip(":").lower()
            raw[current] = match.group(2).strip()
        elif current is not None:
            raw[current] += "\n" + line
    fields = {key: next((raw[name].strip() for name in names if raw.get(name, "").strip()), "")
              for key, names in FIELD_NAMES.items()}
    criteria = bullet_items(fields["acceptance_criteria"])
    if not all((fields["objective"], criteria, fields["allowed_paths"], fields["executor"])):
        raise IncompleteContract(tr('planning.task_lacks_machine_readable'))
    allowed = backticked(fields["allowed_paths"])
    if not allowed and collapse(fields["allowed_paths"]).lower().rstrip(".") != "none":
        raise IncompleteContract(tr('planning.allowed_paths_require_backticked'))
    match = EXECUTOR_RE.match(collapse(fields["executor"]))
    if not match:
        raise IncompleteContract(tr('planning.executor_requires_model_effort'))
    shared = section(text, SHARED_HEADING)
    constraints = ["Shared constraints: " + shared] if shared else []
    for label, key in (("Scope", "scope"), ("Out of scope", "forbidden_scope"), ("Validation expectations", "validation")):
        if fields[key]:
            constraints.append(f"{label}: {collapse(fields[key])}")
    constraints += text_items(fields["constraints"])
    data = {
        "task_id": task_id, "phase_id": phase_id, "title": heading.group(2),
        "objective": collapse(fields["objective"]), "business_context": collapse(fields["business_context"]),
        "allowed_paths": allowed,
        "forbidden_paths": list(dict.fromkeys((*context.profile.protected_paths, *backticked(fields["forbidden_paths"])))),
        "acceptance_criteria": criteria, "implementation_constraints": constraints,
        "validation_commands": backticked(fields["validation_commands"]),
        "documentation_refs": [f"{context.next_steps_file} ({task_id} and shared constraints)"] + text_items(fields["references"]),
        "deliverables": text_items(fields["deliverables"]), "risk_notes": text_items(fields["risk_notes"]),
        "executor_prompt": "Implement exactly the frozen task contract. Preserve existing edits; leave acceptance to independent review.",
        "executor_selection": {"model": match.group(1), "effort": match.group(2),
                               "reason": (match.group(3) or "Selected by the phase plan in NEXT_STEPS.").strip()},
        "contract_source": f"{context.next_steps_file} (deterministic, no agent planner)",
    }
    return task_contract(context, data, task_id, phase_id)
