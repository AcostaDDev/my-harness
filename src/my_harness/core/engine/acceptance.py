"""Pure decision: ACCEPT, validation and policy do not amount to a commit."""

from dataclasses import dataclass
import json

from my_harness.core.engine.context import ProjectContext
from my_harness.core.engine.evidence import ContentEvidence, matches
from my_harness.core.engine.review import ReviewCycle
from my_harness.i18n import tr


@dataclass(frozen=True)
class AcceptanceDecision:
    eligible: bool
    reasons: tuple[str, ...]
    evidence: ContentEvidence


def documentation_parity(context: ProjectContext, changed_paths) -> dict | None:
    """D088 point 6 (P008-T003): what the diff touched among data models, diagram and flows. None outside layout v2."""
    from my_harness.core.engine.documents import layout
    target = layout(context)
    if target is None:
        return None
    models = [path for path in changed_paths
              if path != target.ddbb_diagram and matches(path, context.profile.data_model_paths)]
    return {'data_model_paths': list(context.profile.data_model_paths), 'data_model_changes': models,
            'ddbb_diagram': target.ddbb_diagram, 'ddbb_diagram_changed': target.ddbb_diagram in changed_paths,
            'flows_dir': target.flows_dir,
            'flows_changed': [path for path in changed_paths if path.startswith(target.flows_dir + '/')]}


def parity_reasons(context: ProjectContext, changed_paths) -> list[str]:
    """Deterministic reason: a data model change without the data diagram is not accepted. Business flow parity
    is judged by the reviewer (`review-task`)."""
    parity = documentation_parity(context, changed_paths)
    if parity is None or not parity['data_model_changes'] or parity['ddbb_diagram_changed']:
        return []
    return [tr('acceptance.data_model_without_diagram', diagram=parity['ddbb_diagram'],
               paths=", ".join(parity['data_model_changes'][:20]))]


def assess_acceptance(cycle: ReviewCycle, current: ContentEvidence, context: ProjectContext) -> AcceptanceDecision:
    review = json.loads(cycle.review_json) if cycle.review_json else {}
    reasons = []
    if review.get("verdict") != "ACCEPT":
        reasons.append(tr('acceptance.independent_review_did_not'))
    if review.get("blocking_questions") or review.get("scope_grants"):
        reasons.append(tr('acceptance.unresolved_questions_scope_grants'))
    if cycle.policy.hard_failure:
        reasons.append(tr('acceptance.file_policy_failure'))
    if not cycle.validation.all_passed:
        reasons.append(tr('acceptance.deterministic_validation_failed'))
    reasons += parity_reasons(context, cycle.evidence.changed_paths)
    if cycle.validation.evidence != cycle.evidence or current != cycle.evidence:
        reasons.append(tr('acceptance.content_changed_since_evidence'))
    return AcceptanceDecision(not reasons, tuple(reasons), cycle.evidence)
