"""Review validation and characterization of the legacy no-progress cycle."""

from dataclasses import dataclass
import json

from my_harness.core.engine.context import ProjectContext
from my_harness.core.engine.contracts import ContractError, executor_selection, freeze
from my_harness.core.engine.evidence import ContentEvidence, PathPolicyResult
from my_harness.core.engine.validation import ValidationReport
from my_harness.i18n import tr


# D088 point 2 (P008-T003): the executor does not edit DECISIONS; it proposes ADRs in its output and the reviewer
# returns those it endorses. Bounded and without effect on the verdict or acceptance; they are consolidated during
# reconciliation or through a confirmed edit.
MAX_DECISION_PROPOSALS = 5
DECISION_FIELDS = {'title': 200, 'decision': 4000, 'rationale': 4000}


def decision_proposals(value: object) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_DECISION_PROPOSALS:
        raise ContractError(tr('review.decision_proposals_list_most', max_decision_proposals=MAX_DECISION_PROPOSALS))
    for item in value:
        if (not isinstance(item, dict) or set(item) != set(DECISION_FIELDS)
                or not all(isinstance(item[key], str) and item[key].strip() and len(item[key]) <= limit
                           for key, limit in DECISION_FIELDS.items())):
            raise ContractError(tr('review.each_decision_proposal_needs'))
    return value


def review_contract(context: ProjectContext, task: dict, review: dict) -> str:
    if review.get("task_id") != task["task_id"] or review.get("verdict") not in ("ACCEPT", "REVISE", "BLOCKED"):
        raise ContractError(tr('review.review_task_verdict_mismatch'))
    for field in ("findings", "blocking_questions", "scope_grants"):
        if field in review and not isinstance(review[field], list):
            raise ContractError(tr('review.invalid_review', field=field))
    for finding in review.get("findings", []):
        if not isinstance(finding, dict) or not all(isinstance(finding.get(key, ""), str)
                for key in ("severity", "category", "file", "problem")):
            raise ContractError(tr('review.invalid_review_finding'))
    if "decision_proposals" in review:
        decision_proposals(review["decision_proposals"])
    if review["verdict"] == "REVISE":
        executor_selection(context, review.get("executor_selection"))
        if not isinstance(review.get("next_prompt"), str) or not review["next_prompt"].strip():
            raise ContractError(tr('review.revise_requires_fresh_selection'))
    return freeze(review)


def stalled_review_signature(review: dict, validation: ValidationReport) -> str:
    findings = sorted((item.get("category", ""), item.get("file", ""), item.get("problem", ""))
                      for item in review.get("findings", []) if item.get("severity") != "info")
    commands = [(entry.requested, entry.result.passed, entry.result.exit_code) for entry in validation.entries]
    return freeze([findings, commands])


@dataclass(frozen=True)
class ReviewCycle:
    number: int
    evidence: ContentEvidence
    policy: PathPolicyResult
    validation: ValidationReport
    review_json: str | None
    before_execution: ContentEvidence | None
    permission_denials_json: str = "[]"
    # P009-T019 (D133): profile formatting after the executor attempt (command, paths and result); None if none ran.
    formatting_json: str | None = None

    @property
    def verdict(self) -> str | None:
        value = json.loads(self.review_json).get("verdict") if self.review_json else None
        return value if isinstance(value, str) else None
