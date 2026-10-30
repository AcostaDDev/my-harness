"""D273/G16: closed duty contracts. Candidates never grant, adopt, accept or waive guards."""
from dataclasses import dataclass
import json

from my_harness.core.engine.contracts import MODEL_FORM
from my_harness.core.engine.domain_catalogue import _object as domain_object, digest, validate, CATALOGUE
from my_harness.core.engine.tool_bridge import NATIVE, qualification
from my_harness.i18n import tr


def _object(fields, required=None):
    return domain_object(fields, tuple(fields) if required is None else required)


DUTIES = ('permission', 'planning_choice', 'spec_gap', 'blocked_check')
FORMAT = 'judge-contract-1'
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 4000}
IDS = {'type': 'array', 'maxItems': 50, 'items': {'type': 'string', 'minLength': 1, 'maxLength': 100}}
DURATION = _object({'kind': {'enum': ['operation', 'time_limited', 'permanent']},
                    'seconds': {'type': ['integer', 'null'], 'minimum': 1}})
OWNER_ONLY = frozenset(('secrets', 'global_configuration', 'outside_root', 'policy', 'destructive_git',
                        'publication', 'undelegated_install', 'objectives', 'phases', 'requirement_meaning',
                        'criteria', 'judge_policy', 'acceptance', 'integrity', 'ready'))
SAFE_CAPABILITIES = ('root_files', 'command', 'network_destination', 'planning')
INPUTS = {
    'permission': _object({'dimension': {'enum': ['files', 'tools', 'network', 'product', 'acceptance']},
        'targets': {**IDS, 'minItems': 1}, 'purpose': TEXT, 'blocker': TEXT,
        'capability': {'enum': [*SAFE_CAPABILITIES, *sorted(OWNER_ONLY)]}, 'duration': DURATION}),
    'planning_choice': _object({'options': {'type': 'array', 'maxItems': 50, 'items': _object({
        'id': TEXT, 'admissible': {'type': 'boolean'}, 'tradeoffs': TEXT, 'criterion_ids': {**IDS, 'minItems': 1}})},
        'criterion_ids': {**IDS, 'minItems': 1}}),
    'spec_gap': _object({'gap': TEXT, 'requirement_ids': {**IDS, 'minItems': 1}, 'intent_id': TEXT,
                         'delegated_intent': TEXT}),
    'blocked_check': _object({'classification': {'enum': ['planning_ambiguity', 'authentication', 'environment',
        'integrity', 'writer_uncertainty', 'authority']}, 'blocked_evidence': TEXT, 'intent_id': TEXT}),
}


def result_schema(duty):
    outcomes = {'permission': ['grant', 'deny'], 'planning_choice': ['select'],
                'spec_gap': ['propose'], 'blocked_check': ['propose']}[duty]
    fields = {'duty': {'enum': [duty]}, 'outcome': {'enum': [*outcomes, 'escalate', 'abstain']},
              'rationale': TEXT, 'evidence_ids': IDS}
    optional = {'permission': {'duration': DURATION, 'alternative': {'type': ['string', 'null'], 'maxLength': 100}},
                'planning_choice': {'option_id': TEXT},
                'spec_gap': {'proposal': _object({'text': TEXT, 'intent_id': TEXT, 'requirement_ids': IDS})},
                'blocked_check': {'proposal': _object({'text': TEXT, 'intent_id': TEXT})}}[duty]
    return _object({**fields, **optional}, tuple(fields))


def input_check(duty, inputs):
    if duty not in DUTIES:
        raise ValueError(tr('judge.invalid'))
    validate(INPUTS[duty], inputs)
    if duty == 'permission':
        duration_check(inputs['duration'])
        targets = inputs['targets']
        if len(set(targets)) != len(targets):
            raise ValueError(tr('judge.invalid'))
        if inputs['dimension'] == 'files':
            from my_harness.core.engine.context import relative_path
            for target in targets:
                relative_path(target)
    if duty == 'planning_choice':
        options = inputs['options']
        if len({o['id'] for o in options}) != len(options) or any(
                not set(o['criterion_ids']) <= set(inputs['criterion_ids']) for o in options):
            raise ValueError(tr('judge.invalid'))


def duration_check(value):
    if (value['kind'] == 'time_limited') != (value['seconds'] is not None):
        raise ValueError(tr('judge.invalid'))


def within(duration, ceiling):
    duration_check(duration)
    duration_check(ceiling)
    rank = {'operation': 0, 'time_limited': 1, 'permanent': 2}
    return rank[duration['kind']] <= rank[ceiling['kind']] and (
        duration['kind'] != 'time_limited' or ceiling['kind'] == 'permanent' or
        duration['seconds'] <= ceiling['seconds'])


def eligibility(duty, inputs, policy):
    """Policy is bound by trusted infrastructure; never supplied by the model. No productive provider exists yet."""
    input_check(duty, inputs)
    if not policy or not policy.get('active') or duty not in policy.get('duties', ()):
        return 'not_delegated'
    if duty == 'permission':
        if inputs['capability'] in OWNER_ONLY or inputs['dimension'] == 'acceptance':
            return 'owner_only'
        expected = {'root_files': 'files', 'command': 'tools', 'network_destination': 'network', 'planning': 'product'}
        if expected.get(inputs['capability']) != inputs['dimension'] or not policy.get('compound_safe', False):
            return 'owner_only'
        allowed = policy.get('delegable', {}).get(inputs['dimension'], ())
        if not set(inputs['targets']) <= set(allowed):
            return 'not_delegated'
    if duty == 'planning_choice' and not any(o['admissible'] for o in inputs['options']):
        return 'no_admissible_option'
    if duty == 'blocked_check' and inputs['classification'] != 'planning_ambiguity':
        return 'ineligible_blocker'
    if duty in ('spec_gap', 'blocked_check') and inputs['intent_id'] not in policy.get('intent_ids', ()):
        return 'not_delegated'
    return None


def candidate(duty, inputs, evidence, policy, raw):
    """Returns a candidate only. Deterministic checks cannot establish the semantic truth of model prose."""
    value = json.loads(raw)
    validate(result_schema(duty), value)
    if eligibility(duty, inputs, policy):
        raise ValueError(tr('judge.invalid'))
    if not set(value['evidence_ids']) <= set(evidence):
        raise ValueError(tr('judge.invalid'))
    outcome = value['outcome']
    if outcome in ('abstain', 'escalate'):
        if set(value) != {'duty', 'outcome', 'rationale', 'evidence_ids'}:
            raise ValueError(tr('judge.invalid'))
        return value
    if not value['evidence_ids'] or not evidence:
        raise ValueError(tr('judge.invalid'))
    extra = set(value) - {'duty', 'outcome', 'rationale', 'evidence_ids'}
    required = {'grant': {'duration'}, 'deny': {'alternative'}, 'select': {'option_id'}, 'propose': {'proposal'}}[outcome]
    if extra != required:
        raise ValueError(tr('judge.invalid'))
    if outcome == 'grant':
        if (not within(inputs['duration'], policy['duration_ceiling']) or
                not within(value['duration'], policy['duration_ceiling']) or
                not within(value['duration'], inputs['duration'])):
            raise ValueError(tr('judge.invalid'))
    if outcome == 'deny' and value['alternative'] is not None and value['alternative'] not in policy.get('permitted_alternatives', ()):
        raise ValueError(tr('judge.invalid'))
    if outcome == 'select' and not any(o['id'] == value['option_id'] and o['admissible'] for o in inputs['options']):
        raise ValueError(tr('judge.invalid'))
    if outcome == 'propose':
        proposal = value['proposal']
        if proposal['intent_id'] != inputs['intent_id'] or (duty == 'spec_gap' and (
                not proposal['requirement_ids'] or not set(proposal['requirement_ids']) <= set(inputs['requirement_ids']))):
            raise ValueError(tr('judge.invalid'))
    return value


@dataclass(frozen=True)
class Profile:
    provider: str
    model: str
    effort: str
    cli_version: str
    evidence: str
    provenance: str


def admit_profile(agents, versions, *, efforts, qualifications=NATIVE):
    config = agents.get('judge')
    model, effort = versions.get('judge_model'), versions.get('judge_effort')
    if (config is None or versions.get('judge_provider') != config.provider or
            versions.get('judge_cli') != config.cli_version or not isinstance(model, str) or
            not MODEL_FORM.fullmatch(model) or effort not in efforts.get(config.provider, ())):
        raise ValueError(tr('judge.profile_required'))
    cell = qualification(qualifications, config.provider, config.cli_version, 'judge')
    return Profile(config.provider, model, effort, config.cli_version, cell.evidence, cell.provenance)


def refs(duty):
    return frozenset(CATALOGUE.current(n).ref for n in ('knowledge.lookup', 'knowledge.search', f'judge.{duty}.submit'))


def marker_check(snapshot, role, selected):
    if role != 'judge':
        return
    marker = snapshot.get('judge')
    if not isinstance(marker, dict) or marker.get('duty') not in DUTIES or selected != refs(marker['duty']):
        raise ValueError(tr('judge.invalid'))
    profile = marker.get('profile', {})
    scoped = snapshot.get('scoped_tools')
    if scoped and any(profile.get(k) != scoped.get(other) for k, other in
                      (('provider', 'client'), ('cli_version', 'version'), ('evidence', 'evidence'), ('provenance', 'provenance'))):
        raise ValueError(tr('judge.invalid'))
