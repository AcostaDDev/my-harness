"""P002-T016 (D276, D299): pure contract of autonomous roadmap runs. Standard library only.

States and transitions (FL02), local bounds and optional caps (contracts §10), failure classes, the start preview
digest and the deterministic readiness predicates already decided in FL01. Values owned by the open gates G11
(default bounds, no-progress equivalence), G12 (reviewer gap classification) and G17 (risk acknowledgement) are
never defaults here: they arrive through an explicit `GatePolicy`. The product policy has none, so the definitive
readiness verdict and a productive confirmation stay blocked until the owner resolves those gates. Proposed
functions are labelled `proposal` and are selected only by a policy that names them.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
from typing import Callable, Mapping

from my_harness.core.engine.contracts import freeze
from my_harness.i18n import tr

PREVIEW_FORMAT = 'autonomous-preview-1'
AUTHORIZATION_FORMAT = 'autonomous-authorization-1'
STATES = ('RUNNING', 'WAITING_FOR_OWNER', 'PAUSED', 'LIMIT_REACHED', 'FAILED', 'RECOVERY_REQUIRED', 'REVOKED',
          'COMPLETED')
TERMINAL = ('REVOKED', 'COMPLETED')
ACTIVE = tuple(state for state in STATES if state not in TERMINAL)
STOPS = tuple(state for state in STATES if state != 'RUNNING')
# FL02. Revocation is always available to the owner while authority exists (D274: immediate for new admissions);
# from RECOVERY_REQUIRED it ends authority but uncertain effects still need stopped-writer evidence (FL13).
TRANSITIONS = {
    'RUNNING': frozenset(STOPS),
    'WAITING_FOR_OWNER': frozenset({'RUNNING', 'REVOKED'}),
    'PAUSED': frozenset({'RUNNING', 'REVOKED'}),
    'LIMIT_REACHED': frozenset({'RUNNING', 'REVOKED'}),
    'FAILED': frozenset({'RUNNING', 'REVOKED'}),
    'RECOVERY_REQUIRED': frozenset({'PAUSED', 'REVOKED'}),
    'REVOKED': frozenset(),
    'COMPLETED': frozenset(),
}
# Resuming from LIMIT_REACHED needs a new confirmed authorization revision; from RECOVERY_REQUIRED, recovery first.
RESUMABLE = ('WAITING_FOR_OWNER', 'PAUSED', 'FAILED')
BOUNDS = ('task_attempts', 'judge_reconsiderations', 'replacement_plans', 'remediation_per_cause', 'no_progress')
# Representation ceiling that keeps every confirmed bound finite; it is not a default (G11 owns defaults).
BOUND_CEILING = 1000
CAPS = ('deadline', 'invocations', 'observed_tokens', 'valuation')
FAILURES = ('quota', 'authentication', 'environment', 'policy', 'operational', 'integrity')
DUTIES = ('permission', 'planning_choice', 'spec_gap', 'blocked_check')
GATES = ('G11', 'G12', 'G17')
GAP_CLASSES = ('blocking', 'owner_answer_required', 'advisory')
READINESS_CHECKS = ('accepted_revision', 'ordered_roadmap', 'criteria_present', 'active_phase', 'profile_prepared',
                    'clients_compatible', 'git_baseline_clean', 'no_uncertain_writer', 'no_pending_effect',
                    'no_active_autonomous_run', 'no_manual_batch', 'bounds_feasible')


class AutonomyRefusal(ValueError):
    """A typed refusal; `code` is stable for clients and tests, the message is localized."""

    def __init__(self, code: str, **detail):
        super().__init__(tr('autonomy.refused', reason=code))
        self.code, self.detail = code, detail


def digest(value) -> str:
    return hashlib.sha256(freeze(value).encode('utf-8')).hexdigest()


def transition(current: str, target: str) -> str:
    if current not in TRANSITIONS or target not in TRANSITIONS[current]:
        raise AutonomyRefusal('transition_refused', current=current, target=target)
    return target


@dataclass(frozen=True)
class GatePolicy:
    """Everything G11/G12/G17 decide. `label` is `product` or `synthetic`; an authorization records both."""
    version: str
    label: str
    default_bounds: Mapping | None = None
    fingerprint: Callable[[Mapping], str] | None = None
    fingerprint_version: str | None = None
    classify_gaps: Callable[[Mapping, Mapping], Mapping] | None = None
    readiness_version: str | None = None
    acknowledgement: Mapping[str, str] | None = None
    acknowledgement_version: str | None = None
    notes: tuple = field(default=())

    def pending(self) -> tuple[str, ...]:
        missing = []
        if self.default_bounds is None or self.fingerprint is None or not self.fingerprint_version:
            missing.append('G11')
        if self.classify_gaps is None or not self.readiness_version:
            missing.append('G12')
        if not self.acknowledgement or not self.acknowledgement_version:
            missing.append('G17')
        return tuple(missing)

    def stamp(self) -> dict:
        return {'version': self.version, 'label': self.label, 'fingerprint_version': self.fingerprint_version,
                'readiness_version': self.readiness_version, 'acknowledgement_version': self.acknowledgement_version,
                'acknowledgement_sha256': digest(dict(self.acknowledgement)) if self.acknowledgement else None,
                'pending_gates': list(self.pending())}


# The policy without any gate value (kept for tests and for the documented pre-resolution behavior).
PENDING_POLICY = GatePolicy('pending', 'product')


def validate_bounds(bounds) -> dict:
    """Every local bound is explicit, integral and finite; none is filled from a default (G11)."""
    if not isinstance(bounds, Mapping) or set(bounds) != set(BOUNDS):
        raise AutonomyRefusal('bounds_incomplete', expected=list(BOUNDS))
    for name in BOUNDS:
        value = bounds[name]
        if type(value) is not int or not 1 <= value <= BOUND_CEILING:
            raise AutonomyRefusal('bound_invalid', bound=name)
    return {name: bounds[name] for name in BOUNDS}


def raised(previous: Mapping, new: Mapping) -> bool:
    """A new authorization revision may keep or raise bounds; lowering below consumption is checked by storage."""
    return all(new[name] >= previous[name] for name in BOUNDS)


def _instant(value):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise AutonomyRefusal('cap_invalid', cap='deadline') from None
    if moment.tzinfo is None:
        raise AutonomyRefusal('cap_invalid', cap='deadline')
    return moment


def validate_caps(caps) -> dict:
    """Optional thresholds (contracts §10): absent means unset. Valuation names one basis and a decimal amount."""
    if not isinstance(caps, Mapping) or set(caps) - set(CAPS):
        raise AutonomyRefusal('caps_invalid')
    clean = {}
    if caps.get('deadline') is not None:
        _instant(caps['deadline'])
        clean['deadline'] = caps['deadline']
    for name in ('invocations', 'observed_tokens'):
        value = caps.get(name)
        if value is not None:
            if type(value) is not int or value < 1:
                raise AutonomyRefusal('cap_invalid', cap=name)
            clean[name] = value
    valuation = caps.get('valuation')
    if valuation is not None:
        if not isinstance(valuation, Mapping) or set(valuation) != {'amount', 'basis'} or not isinstance(
                valuation['basis'], str) or not valuation['basis'].strip():
            raise AutonomyRefusal('cap_invalid', cap='valuation')
        try:
            amount = Decimal(str(valuation['amount']))
        except InvalidOperation:
            raise AutonomyRefusal('cap_invalid', cap='valuation') from None
        if not amount.is_finite() or amount <= 0:
            raise AutonomyRefusal('cap_invalid', cap='valuation')
        clean['valuation'] = {'amount': str(valuation['amount']), 'basis': valuation['basis']}
    return clean


def cap_stop(caps: Mapping, usage: Mapping, now: str) -> dict | None:
    """Checked before admitting each new inference; an in-flight invocation may exceed a threshold (§10).

    `usage` is observed evidence: `invocations`, `tokens` (None when any linked invocation lacks it), and
    `valuation` as {'basis', 'amount'} or None when unknown. Unknown usage stops only when its cap is set."""
    if caps.get('deadline') and _instant(now) >= _instant(caps['deadline']):
        return {'reason': 'cap_deadline', 'cap': 'deadline', 'threshold': caps['deadline'], 'observed': now}
    if caps.get('invocations') is not None and usage.get('invocations', 0) >= caps['invocations']:
        return {'reason': 'cap_invocations', 'cap': 'invocations', 'threshold': caps['invocations'],
                'observed': usage.get('invocations', 0)}
    if caps.get('observed_tokens') is not None:
        tokens = usage.get('tokens')
        if tokens is None:
            return {'reason': 'cap_usage_unknown', 'cap': 'observed_tokens'}
        if tokens >= caps['observed_tokens']:
            return {'reason': 'cap_observed_tokens', 'cap': 'observed_tokens',
                    'threshold': caps['observed_tokens'], 'observed': tokens}
    if caps.get('valuation') is not None:
        valued = usage.get('valuation')
        if valued is not None and (valued.get('status') == 'incompatible'
                                   or valued.get('basis') != caps['valuation']['basis']):
            return {'reason': 'cap_valuation_basis_incompatible', 'cap': 'valuation', 'basis': caps['valuation']['basis']}
        if valued is None or valued.get('status', 'known') != 'known' or valued.get('amount') is None:
            return {'reason': 'cap_usage_unknown', 'cap': 'valuation'}
        if Decimal(str(valued['amount'])) >= Decimal(caps['valuation']['amount']):
            return {'reason': 'cap_valuation', 'cap': 'valuation', 'threshold': caps['valuation']['amount'],
                    'observed': str(valued['amount']), 'basis': valued['basis']}
    return None


def failure_stop(kind: str, detail: Mapping | None = None) -> dict:
    """Typed effect failures to durable stops; never retried, polled or fallen back (FL cross-cutting rules)."""
    detail = dict(detail or {})
    if kind == 'uncertain':
        return {'status': 'RECOVERY_REQUIRED', 'reason': 'effect_uncertain', 'detail': detail}
    if kind in ('escalate', 'owner_required', 'malformed', 'refusal', 'evidence_unavailable'):
        return {'status': 'WAITING_FOR_OWNER', 'reason': f'owner_{kind}', 'detail': detail}
    if kind in FAILURES:
        return {'status': 'FAILED', 'reason': f'{kind}_failure', 'detail': {**detail, 'failure_class': kind}}
    return {'status': 'FAILED', 'reason': 'operational_failure', 'detail': {**detail, 'failure_class': 'operational',
                                                                            'reported': kind}}


def validate_delegation(delegation) -> dict:
    """Enabled judge duties, delegable tiers and duration ceilings shown in the preview (contracts §10)."""
    if not isinstance(delegation, Mapping) or set(delegation) != {'duties', 'tiers', 'duration_ceiling'}:
        raise AutonomyRefusal('delegation_invalid')
    duties = delegation['duties']
    if not isinstance(duties, list) or len(set(duties)) != len(duties) or set(duties) - set(DUTIES):
        raise AutonomyRefusal('delegation_invalid')
    tiers = delegation['tiers']
    if not isinstance(tiers, Mapping) or set(tiers) != {'active', 'delegable', 'owner_only'}:
        raise AutonomyRefusal('delegation_invalid')
    for name in ('active', 'delegable', 'owner_only'):
        if not isinstance(tiers[name], list) or not all(isinstance(v, str) and v for v in tiers[name]):
            raise AutonomyRefusal('delegation_invalid')
    if set(tiers['delegable']) & set(tiers['owner_only']):
        raise AutonomyRefusal('delegation_invalid')
    if 'files.write.task_contract' in tiers['owner_only']:
        raise AutonomyRefusal('delegation_invalid')
    ceiling = delegation['duration_ceiling']
    if not isinstance(ceiling, Mapping) or ceiling.get('kind') not in ('operation', 'time') or (
            ceiling['kind'] == 'time' and (type(ceiling.get('seconds')) is not int or ceiling['seconds'] < 1)):
        raise AutonomyRefusal('delegation_invalid')
    return {'duties': sorted(duties), 'tiers': {k: sorted(tiers[k]) for k in ('active', 'delegable', 'owner_only')},
            'duration_ceiling': dict(ceiling)}


def scope_digest(revision_view: Mapping) -> str:
    """Product meaning a run may not change: phase set/order/objectives, criteria and requirements (tasks excluded).

    Delegated plan adoption changes task members and links only; any other difference is an owner amendment."""
    return digest({key: revision_view.get(key) for key in ('phases', 'criteria', 'requirements')})


def readiness_checks(observation: Mapping, bounds_error: str | None) -> list[dict]:
    """FL01 deterministic structural checks over a typed observation; no model and no persistence."""
    phases = observation.get('roadmap') or []
    active = [p for p in phases if p.get('operational') not in (None, 'CLOSED', 'ABANDONED')]
    results = {
        'accepted_revision': observation.get('revision') is not None,
        'ordered_roadmap': bool(phases) and [p['code'] for p in phases] == sorted(p['code'] for p in phases),
        'criteria_present': bool(phases) and all(p.get('criteria') for p in phases if p['authorized']),
        'active_phase': len(active) == 1 and active[0]['authorized'] and active[0]['code'] == next(
            (p['code'] for p in phases if p.get('operational') not in ('CLOSED', 'ABANDONED')), None),
        'profile_prepared': observation.get('prepared') is True,
        'clients_compatible': observation.get('clients_compatible') is True,
        'git_baseline_clean': observation.get('git_clean') is True,
        'no_uncertain_writer': not observation.get('uncertain_writers'),
        'no_pending_effect': not observation.get('pending_effects'),
        'no_active_autonomous_run': not observation.get('active_run'),
        'no_manual_batch': not observation.get('manual_batches'),
        'bounds_feasible': bounds_error is None,
    }
    return [{'check': name, 'passed': bool(results[name]),
             **({'detail': bounds_error} if name == 'bounds_feasible' and bounds_error else {})}
            for name in READINESS_CHECKS]


def readiness_verdict(checks: list, gap_report: Mapping | None, policy: GatePolicy, context: Mapping | None = None,
                      gap_error: str | None = None) -> dict:
    """BLOCKED on any structural failure; otherwise READY only when G12 classification admits the sealed report.

    Without a resolved G12 policy the verdict is PENDING_GATES and never READY."""
    failed = [c['check'] for c in checks if not c['passed']]
    if failed:
        return {'verdict': 'BLOCKED', 'blocking': failed}
    if 'G12' in policy.pending():
        return {'verdict': 'PENDING_GATES', 'blocking': [], 'pending_gates': ['G12']}
    if gap_error or gap_report is None:
        return {'verdict': 'BLOCKED', 'blocking': [gap_error or 'gap_report_unavailable']}
    classified = policy.classify_gaps(gap_report, context or {})
    if classified['blocking'] or classified['owner_answer_required']:
        return {'verdict': 'BLOCKED', 'blocking': classified['blocking'],
                'owner_answer_required': classified['owner_answer_required']}
    return {'verdict': 'READY', 'blocking': [], 'advisory': classified['advisory']}


# --- G11 accepted equivalence (with the owner's conditions) ----------------------------------------------------

def judge_subject(duty: str, phase_item, cause=None) -> str:
    """G11 canonical judge subject: duty, stable phase identity and cause digest (never an operation identity)."""
    return digest({'duty': duty, 'phase': phase_item, 'cause': cause})


def progress_fingerprint(observation: Mapping) -> str:
    """G11 `g11-1` (accepted with conditions): equivalence of roadmap progress by stable identities only.

    Includes the active phase item, its plan task identities (by D296 family), committed families, the latest
    check classification with its unmet criterion items and open owner questions. Excludes timestamps, run/attempt
    and operation identities, codes and wording, so a resume, rename or split without new committed work or a new
    classification repeats the fingerprint."""
    return digest({
        'phase': observation.get('phase_item'),
        'planned_families': sorted(set(observation.get('planned_families') or [])),
        'committed_families': sorted(set(observation.get('committed_families') or [])),
        'check': observation.get('check_classification'),
        'unmet': sorted(set(observation.get('unmet_criteria') or [])),
        'questions': sorted(set(observation.get('open_questions') or [])),
        'action': observation.get('action'),
        'subject': observation.get('subject'),
    })


def gap_sha256(gap: Mapping) -> str:
    return digest({key: gap.get(key) for key in ('classification', 'citations', 'statement')})


def gap_report_schema() -> dict:
    """Closed JSON Schema of `roadmap-readiness` output (D300); `validate_gap_report` enforces the same shape."""
    citation = {'type': 'object', 'additionalProperties': False, 'required': ['item', 'revision'],
                'properties': {'item': {'type': 'string'}, 'revision': {'type': 'integer'}}}
    gap = {'type': 'object', 'additionalProperties': False, 'required': ['classification', 'statement', 'citations'],
           'properties': {'classification': {'type': 'string', 'enum': list(GAP_CLASSES)},
                          'statement': {'type': 'string'}, 'citations': {'type': 'array', 'items': citation}}}
    return {'type': 'object', 'additionalProperties': False, 'required': ['revision', 'gaps'],
            'properties': {'revision': {'type': 'integer'}, 'gaps': {'type': 'array', 'items': gap}}}


def task_plan_schema() -> dict:
    """Closed JSON Schema of `roadmap-task-plan` output; `validate_task_plan` adds the path and criteria rules.

    The objective and the accepted criteria come from accepted knowledge, never from the model (D301)."""
    texts = {'type': 'array', 'items': {'type': 'string'}}
    return {'type': 'object', 'additionalProperties': False,
            'required': ['task_id', 'allowed_paths', 'acceptance_criteria', 'validation_commands'],
            'properties': {'task_id': {'type': 'string'}, 'allowed_paths': texts, 'acceptance_criteria': texts,
                           'validation_commands': texts}}


def _norm(text):
    return ' '.join(text.split())


UNSAFE = ('\n', '\r', '`', '**', '\t')


def validate_task_plan(plan, *, task_id: str, criteria: list, objective: str, protected: tuple = ()) -> dict:
    """Harness validation of a delegated task contract proposal (D301).

    Exact repository-relative files only, none matching a protected or harness-owned pattern (fnmatch, as T014's
    contract check); every accepted criterion restated as its own exact item and no other item rewording one; no
    text that could introduce a field or change meaning when rendered. The objective is the accepted content."""
    from fnmatch import fnmatchcase
    if not isinstance(plan, Mapping) or set(plan) != {'task_id', 'allowed_paths', 'acceptance_criteria',
                                                       'validation_commands'} or plan['task_id'] != task_id:
        raise AutonomyRefusal('task_plan_malformed')
    lists = [plan[k] for k in ('allowed_paths', 'acceptance_criteria', 'validation_commands')]
    if any(not isinstance(v, list) or len(v) > 50 or any(not isinstance(i, str) or not i.strip() or len(i) > 2000
                                                          for i in v) for v in lists):
        raise AutonomyRefusal('task_plan_malformed')
    if any(u in item for item in (*plan['acceptance_criteria'], *plan['validation_commands'], *plan['allowed_paths'])
           for u in UNSAFE) or any(_norm(i)[:1] in ('#', '-', '>', '*') for i in plan['acceptance_criteria']):
        raise AutonomyRefusal('task_plan_unsafe_text')
    paths = plan['allowed_paths']
    if not paths or len(set(paths)) != len(paths) or any(
            p != p.strip() or p.startswith('/') or '\\' in p or '..' in p.split('/') or '.' in p.split('/')
            or any(c in p for c in '*?[]') or p.endswith('/') or '//' in p
            or any(fnmatchcase(p, pattern) or fnmatchcase(p + '/', pattern) for pattern in protected) for p in paths):
        raise AutonomyRefusal('task_plan_paths_invalid')
    accepted = [_norm(c) for c in criteria]
    items = [_norm(c) for c in plan['acceptance_criteria']]
    if any(c not in items for c in accepted):
        raise AutonomyRefusal('task_plan_weakens_criteria')
    if any(i not in accepted and any(c.casefold() in i.casefold() for c in accepted) for i in items):
        raise AutonomyRefusal('task_plan_rewords_criteria')  # e.g. an inverted criterion containing the accepted one
    if not isinstance(objective, str) or not _norm(objective) or any(u in objective for u in UNSAFE):
        raise AutonomyRefusal('task_plan_objective_unavailable')
    ordered = accepted + [i for i in items if i not in accepted]
    return {'task_id': task_id, 'objective': _norm(objective), 'allowed_paths': list(paths),
            'acceptance_criteria': ordered, 'validation_commands': [_norm(c) for c in plan['validation_commands']]}


def render_task_plan(contract: Mapping, *, title: str, phase: str, executor: tuple[str, str]) -> str:
    """Machine-readable plan section for T014's deterministic contract parser; the caller compares the parsed
    contract field by field with `contract` before sealing it."""
    if any(u in title for u in UNSAFE):
        raise AutonomyRefusal('task_plan_unsafe_text')
    lines = [f"## {contract['task_id']} — {_norm(title)}", f"**Objective:** {contract['objective']}",
             '**Allowed paths:** ' + ', '.join(f'`{p}`' for p in contract['allowed_paths']),
             '**Acceptance criteria:**', *[f'- {c}' for c in contract['acceptance_criteria']]]
    if contract['validation_commands']:
        lines.append('**Validation commands:** ' + ', '.join(f'`{c}`' for c in contract['validation_commands']))
    lines.append(f'**Executor:** {executor[0]} / {executor[1]} — Delegated autonomous task contract')
    return f'# Autonomous task contract ({phase})\n' + '\n'.join(lines) + '\n'


PARSED_FIELDS = ('task_id', 'phase_id', 'title', 'objective', 'allowed_paths', 'acceptance_criteria',
                 'validation_commands')


def compare_parsed_contract(parsed: Mapping, contract: Mapping, *, phase: str, title: str,
                            executor: tuple[str, str]) -> None:
    """Every field T014 will execute must equal the validated contract; anything else is refused."""
    expected = {**{k: contract[k] for k in ('task_id', 'objective', 'allowed_paths', 'acceptance_criteria',
                                            'validation_commands')}, 'phase_id': phase, 'title': _norm(title)}
    selection = parsed.get('executor_selection') or {}
    if (any(parsed.get(k) != expected[k] for k in PARSED_FIELDS)
            or (selection.get('model'), selection.get('effort')) != tuple(executor)):
        raise AutonomyRefusal('task_plan_parser_mismatch')


def validate_gap_report(report) -> dict:
    """Structural schema of a reviewer gap report; anything else is malformed (no verdict, not retried)."""
    if not isinstance(report, Mapping) or set(report) != {'revision', 'gaps'} or type(report['revision']) is not int:
        raise AutonomyRefusal('gap_report_malformed')
    gaps = report['gaps']
    if not isinstance(gaps, list) or len(gaps) > 200:
        raise AutonomyRefusal('gap_report_malformed')
    for gap in gaps:
        if (not isinstance(gap, Mapping) or set(gap) != {'classification', 'statement', 'citations'}
                or not isinstance(gap['statement'], str) or not gap['statement'].strip()
                or len(gap['statement']) > 4000 or not isinstance(gap['classification'], str)
                or not isinstance(gap['citations'], list)):
            raise AutonomyRefusal('gap_report_malformed')
        for citation in gap['citations']:
            if (not isinstance(citation, Mapping) or set(citation) != {'item', 'revision'}
                    or not isinstance(citation['item'], str) or type(citation['revision']) is not int):
                raise AutonomyRefusal('gap_report_malformed')
    return {'revision': report['revision'], 'gaps': [dict(g) for g in gaps]}


def classify_gaps(report: Mapping, context: Mapping) -> dict:
    """G12 (`g12-1`, accepted with conditions): admission of a sealed gap report of the service's frozen revision.

    `context` comes from the service, never from the report: `revision` (number of the frozen revision the service
    holds), `items` (item identities that exist in it) and `answers` (gap digests answered by current owner records
    bound to that revision). A report for another revision blocks as a whole. A gap whose citations are absent,
    name another revision or an item missing from the frozen revision is blocking; `owner_answer_required` needs a
    current owner answer; `advisory` is shown only."""
    revision, items, answers = context['revision'], set(context['items']), set(context['answers'])
    blocking, answer, advisory = [], [], []
    if report.get('revision') != revision:
        return {'blocking': ['report_revision_mismatch'], 'owner_answer_required': [], 'advisory': []}
    for gap in report.get('gaps', []):
        ident = gap_sha256(gap)
        cited = gap.get('citations') or []
        if (gap.get('classification') not in GAP_CLASSES or not cited
                or any(c.get('revision') != revision or c.get('item') not in items for c in cited)):
            blocking.append(ident)
        elif gap['classification'] == 'blocking':
            blocking.append(ident)
        elif gap['classification'] == 'owner_answer_required' and ident not in answers:
            answer.append(ident)
        elif gap['classification'] == 'advisory':
            advisory.append(ident)
    return {'blocking': blocking, 'owner_answer_required': answer, 'advisory': advisory}


INFERENCE_ACTIONS = ('propose_plan', 'plan_task', 'admit_task', 'check_phase', 'judge')
BLOCKED_STOPS = {'authentication': 'authentication', 'environment': 'environment', 'integrity': 'integrity',
                 'writer_uncertain': 'uncertain', 'authority_gap': 'policy', 'quota': 'quota'}


def _stop(status, reason, **detail):
    return {'action': 'stop', 'status': status, 'reason': reason, 'detail': detail}


def task_failure_stop(task: Mapping, code: str) -> dict:
    """A failed delegated task run is a durable stop by its evidence; it is readmitted only after an explicit owner
    resume acknowledged that failure (and then consumes `task_attempts`)."""
    failure = task.get('failure_class') or 'operational'
    detail = {'phase': code, 'task': task['code'], 'run_id': task.get('run_id'), 'failure_class': failure}
    if failure == 'cap':
        return _stop('LIMIT_REACHED', task.get('cap_reason') or 'cap_usage_unknown', **detail)
    if failure == 'authority':  # ended or stale delegated authority: never a cap limit
        return _stop('FAILED', 'delegated_authority_refused', **detail, refusal=task.get('cap_reason'))
    if failure == 'revision_limit':
        return _stop('LIMIT_REACHED', 'task_revision_limit', **detail)
    if failure == 'blocked':
        return {'action': 'wait_owner', 'kind': 'task_blocked', 'phase': code, 'task': task['code'],
                'run_id': task.get('run_id')}
    if failure in ('uncertain',):
        return _stop('RECOVERY_REQUIRED', 'effect_uncertain', **detail)
    if failure == 'review_evidence_changed':  # the continued review found other content than the held work
        return _stop('FAILED', 'held_review_evidence_changed', **detail)
    return _stop('FAILED', f'{failure}_failure', **detail)


def decide(view: Mapping, scope: list) -> dict:
    """FL03/FL07 routing from a typed observation of SQLite state; deterministic, never a model decision.

    The returned action names the phase/task identities it concerns. Effects, bounds and caps are applied by the
    service; this function only classifies what the persisted state requires next."""
    if view.get('uncertain'):
        return _stop('RECOVERY_REQUIRED', 'effect_uncertain', operations=list(view['uncertain']))
    if view.get('in_flight'):
        return {'action': 'wait_jobs', 'jobs': list(view['in_flight'])}
    phases = [p for p in view['phases'] if p['code'] in scope]
    current = next((p for p in phases if p['operational'] != 'CLOSED'), None)
    if current is None:
        return {'action': 'complete'}
    code = current['code']
    if current['operational'] == 'ABANDONED':
        return _stop('FAILED', 'phase_abandoned', phase=code)
    if current['operational'] is None:
        return _stop('FAILED', 'successor_missing', phase=code)
    if current.get('questions'):
        return {'action': 'wait_owner', 'kind': 'phase_questions', 'phase': code, 'questions': current['questions']}
    proposal = current.get('proposal')
    if not current['planned']:
        if proposal and proposal['status'] == 'PROPOSED':
            if proposal.get('blocking_questions'):
                return {'action': 'wait_owner', 'kind': 'planning_questions', 'phase': code,
                        'operation_id': proposal['operation_id']}
            if proposal.get('choice_required'):
                return {'action': 'judge', 'duty': 'planning_choice', 'phase': code,
                        'operation_id': proposal['operation_id']}
            return {'action': 'adopt_plan', 'phase': code, 'proposal': proposal, 'remediation': None}
        if proposal and proposal['status'] == 'FAILED' and proposal.get('failure_class') == 'cap':
            return _stop('LIMIT_REACHED', proposal.get('cap_reason') or 'cap_usage_unknown', phase=code)
        if proposal and proposal['status'] == 'FAILED' and proposal.get('failure_class') == 'authority':
            return _stop('FAILED', 'delegated_authority_refused', phase=code, refusal=proposal.get('cap_reason'))
        if proposal and proposal['status'] == 'FAILED' and proposal.get('failure_class') == 'paused':
            # no inference ran: after the explicit resume the proposal is requested again, not a replacement plan
            return {'action': 'propose_plan', 'phase': code, 'replan': False, 'remediation': None}
        if proposal and proposal['status'] == 'FAILED' and proposal.get('failure_class') in FAILURES:
            return _stop('FAILED', f"{proposal['failure_class']}_failure", phase=code)
        return {'action': 'propose_plan', 'phase': code, 'replan': proposal is not None, 'remediation': None}
    tasks = current['tasks']
    committed = {t['code'] for t in tasks if t['state'] == 'committed'}
    ready = [t for t in tasks if t['state'] != 'committed' and set(t.get('depends_on', ())) <= committed]
    if ready:
        task = ready[0]
        if task['state'] == 'foreign_acceptance':  # never commit an acceptance this run did not admit
            return {'action': 'wait_owner', 'kind': 'foreign_task_acceptance', 'phase': code, 'task': task['code'],
                    'run_id': task.get('run_id')}
        if task['state'] == 'held_review':
            # An owner pause held the reviewer after the executor finished; only RUNNING (after the explicit
            # resume) reaches here. The same T014 run is revalidated once; it is not a new admission.
            return {'action': 'resume_review', 'phase': code, 'task': task['code'], 'run_id': task['run_id'],
                    'held': task['held']}
        if task['state'] == 'failed' and not task.get('retry') and task.get('failure_class') != 'paused':
            return task_failure_stop(task, code)  # a pause-held admission resumes with the explicit owner resume
        if task['state'] == 'accepted':  # reviewed and accepted: commit of accepted content (D272)
            return {'action': 'commit_task', 'phase': code, 'task': task['code'], 'run_id': task['run_id'],
                    'version_sha256': task.get('version_sha256')}
        contract = task.get('contract', 'proposed')
        if contract == 'refused':
            return {'action': 'wait_owner', 'kind': 'task_contract_refused', 'phase': code, 'task': task['code']}
        if contract == 'pending':
            return {'action': 'wait_jobs', 'jobs': [task.get('contract_run_id')]}
        if contract == 'uncertain':
            return _stop('RECOVERY_REQUIRED', 'effect_uncertain', phase=code, task=task['code'],
                         run_id=task.get('contract_run_id'))
        if contract == 'failed' and not task.get('contract_retry') and task.get('contract_failure') != 'paused':
            # A contract job that ran and failed is a durable stop; only an explicit owner resume re-plans it.
            failure = task.get('contract_failure') or 'operational'
            detail = {'phase': code, 'task': task['code'], 'run_id': task.get('contract_run_id'),
                      'failure_class': failure}
            if failure == 'cap':
                return _stop('LIMIT_REACHED', task.get('cap_reason') or 'cap_usage_unknown', **detail)
            if failure == 'authority':
                return _stop('FAILED', 'delegated_authority_refused', **detail)
            return _stop('FAILED', 'task_contract_failed', **detail)
        if contract != 'proposed':
            return {'action': 'plan_task', 'phase': code, 'task': task['code'], 'task_view': task}
        return {'action': 'admit_task', 'phase': code, 'task': task['code'], 'family': task['family'],
                'paths': task['paths'], 'plan_text': task.get('plan_text'), 'retry': task['state'] == 'failed',
                'version_sha256': task.get('version_sha256'), 'contract_sha256': task.get('contract_sha256')}
    if len(committed) != len(tasks):
        return _stop('FAILED', 'dependency_unsatisfiable', phase=code)
    check = current.get('check')
    if check is None or check.get('stale'):
        return {'action': 'check_phase', 'phase': code}
    verdict = check['verdict']
    if verdict == 'READY':
        return {'action': 'close_phase', 'phase': code, 'binding_sha256': check['binding_sha256']}
    if verdict in ('NOT_READY', 'REVISE'):
        cause = digest({'classification': check.get('classification'), 'unmet': sorted(check.get('unmet') or [])})
        if proposal and proposal['status'] == 'PROPOSED' and proposal.get('after_check'):
            return {'action': 'adopt_plan', 'phase': code, 'proposal': proposal, 'remediation': cause}
        return {'action': 'propose_plan', 'phase': code, 'replan': False, 'remediation': cause}
    if verdict == 'BLOCKED':
        classification = check.get('classification')
        if classification == 'planning_ambiguity' and check.get('ruling_id'):
            # A validated ruling informs a remediation proposal and is linked to it; it never adopts or closes.
            cause = digest({'classification': classification, 'unmet': sorted(check.get('unmet') or [])})
            if proposal and proposal['status'] == 'PROPOSED' and proposal.get('after_check'):
                return {'action': 'adopt_plan', 'phase': code, 'proposal': proposal, 'remediation': cause,
                        'ruling_id': check['ruling_id']}
            return {'action': 'propose_plan', 'phase': code, 'replan': False, 'remediation': cause,
                    'ruling_id': check['ruling_id']}
        if classification == 'planning_ambiguity':
            return {'action': 'judge', 'duty': 'blocked_check', 'phase': code, 'operation_id': check['operation_id'],
                    'phase_item': current.get('item'), 'judge_input': check.get('judge_input'),
                    'cause': digest({'classification': classification, 'unmet': sorted(check.get('unmet') or [])})}
        if classification in BLOCKED_STOPS:
            return {'action': 'fail', 'kind': BLOCKED_STOPS[classification], 'phase': code,
                    'classification': classification}
        return {'action': 'wait_owner', 'kind': 'blocked_check', 'phase': code, 'operation_id': check['operation_id']}
    if check.get('failure_class') == 'cap':
        return _stop('LIMIT_REACHED', check.get('cap_reason') or 'cap_usage_unknown', phase=code)
    if check.get('failure_class') == 'authority':
        return _stop('FAILED', 'delegated_authority_refused', phase=code, refusal=check.get('cap_reason'))
    if check.get('failure_class') == 'paused':
        return {'action': 'check_phase', 'phase': code}
    return {'action': 'fail', 'kind': check.get('failure_class') or 'operational', 'phase': code,
            'classification': verdict}


def completion(view: Mapping, scope: list, roadmap: list) -> dict:
    """COMPLETED only when every authorized phase is CLOSED with criterion evidence and final coverage, and each
    successor is the next phase of the sealed roadmap (none after the last). Anything else is not success."""
    phases = {p['code']: p for p in view['phases']}
    missing = []
    for code in scope:
        phase = phases.get(code)
        closure = (phase or {}).get('closure') or {}
        if not phase or phase['operational'] != 'CLOSED':
            missing.append({'phase': code, 'reason': 'not_closed'})
            continue
        if not closure.get('criteria_evidence') or not phase.get('coverage_complete'):
            missing.append({'phase': code, 'reason': 'evidence_incomplete'})
        following = roadmap[roadmap.index(code) + 1] if code in roadmap and roadmap.index(code) + 1 < len(roadmap) else None
        if closure.get('successor') != following:
            missing.append({'phase': code, 'reason': 'successor_mismatch', 'expected': following,
                            'observed': closure.get('successor')})
    # Final requirement coverage of the authorized revision (D276 completion): from accepted relations and the
    # evidence sealed by each closure; a view without requirement data cannot claim it.
    requirements = view.get('requirements')
    if requirements is None:
        missing.append({'reason': 'requirement_coverage_unavailable'})
    else:
        missing += [{'requirement': r['item'], 'reason': 'requirement_uncovered'} for r in requirements if not r['covered']]
    return {'completed': not missing, 'missing': missing}


def preview_sha256(preview: Mapping) -> str:
    return digest({key: value for key, value in preview.items() if key != 'preview_sha256'})


# --- Owner-accepted product policy (2026-11-03; D300) ------------------------------------------------------------

ACKNOWLEDGEMENT_VERSION = 'autonomy-ack-1'
ACKNOWLEDGEMENT_KEY = 'autonomy.acknowledgement.autonomy_ack_1'
# Digest of the accepted en/es texts; a catalog edit that changes them disables the acknowledgement (G17 reopens).
ACKNOWLEDGEMENT_SHA256 = '640e0cfcc0c777f598d2d902b4892ac082ca615cde022c32ef7da19a555edd56'
DEFAULT_BOUNDS = {'task_attempts': 3, 'judge_reconsiderations': 1, 'replacement_plans': 2, 'remediation_per_cause': 2,
                  'no_progress': 3}


def accepted_acknowledgement():
    from my_harness.i18n import message
    texts = {language: message(ACKNOWLEDGEMENT_KEY, language) for language in ('en', 'es')}
    return texts if digest(texts) == ACKNOWLEDGEMENT_SHA256 else None


def product_policy() -> GatePolicy:
    """G11/G12/G17 as accepted by the owner. Defaults only prefill the preview; bounds stay explicit and confirmed."""
    return GatePolicy('product-1', 'product', default_bounds=dict(DEFAULT_BOUNDS), fingerprint=progress_fingerprint,
                      fingerprint_version='g11-1', classify_gaps=classify_gaps, readiness_version='g12-1',
                      acknowledgement=accepted_acknowledgement(), acknowledgement_version=ACKNOWLEDGEMENT_VERSION)
