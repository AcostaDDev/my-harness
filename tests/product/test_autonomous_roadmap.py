"""P002-T016 (D276, D299): autonomous roadmap runs over the real SQLite authority, LangGraph runtime and journal.

Synthetic only: migrated temporary SQLite, disposable Git checkout, an in-memory roadmap behind the typed
`RoadmapEffects` port and labelled synthetic gate policies. No provider, CLI, network or service. The G11/G12
proposal functions are exercised as proposals (parametrized with an alternative), never as product defaults.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from my_harness.core.engine import autonomy
from my_harness.core.engine.autonomy import AutonomyRefusal, GatePolicy
from my_harness.orchestration.roadmap import RoadmapGraphs
from my_harness.services.autonomous_roadmap import AutonomousRoadmap
from my_harness.services.permission_lifecycle import PermissionLifecycle
from my_harness.storage import autonomous_runs as store
from my_harness.storage.models import (
    AutonomousAuthorizationRow, AutonomousChildRow, AutonomousConsumptionRow, AutonomousRunRow, GraphThreadRow,
    KnowledgeProjectRow, PermissionRecordRow, PhaseAuthorizationRow, PhaseRow, WorkflowOperationRow,
)
from my_harness.storage.operation_journal import OperationJournal
from test_managed import context, repository  # noqa: F401  (fixtures)

BOUNDS = {'task_attempts': 3, 'judge_reconsiderations': 2, 'replacement_plans': 2, 'remediation_per_cause': 2,
          'no_progress': 4}
DELEGATION = {'duties': ['planning_choice', 'blocked_check'],
              'tiers': {'active': ['files.write.task_contract'], 'delegable': ['files.write.task_contract'],
                        'owner_only': ['push', 'publication', 'secrets']},
              'duration_ceiling': {'kind': 'operation'}}
REQUEST = {'bounds': BOUNDS, 'caps': {}, 'delegation': DELEGATION}


def synthetic_policy(fingerprint=autonomy.progress_fingerprint, version='synthetic-test-1'):
    """Labelled synthetic policy: accepted G11/G12 functions, test bounds and a synthetic acknowledgement."""
    return GatePolicy(version, 'synthetic', default_bounds=dict(BOUNDS), fingerprint=fingerprint,
                      fingerprint_version='g11-1', classify_gaps=autonomy.classify_gaps,
                      readiness_version='g12-1', acknowledgement={'en': 'Synthetic acknowledgement.',
                                                                            'es': 'Synthetic acknowledgement (es).'},
                      acknowledgement_version='synthetic-ack-1')


def strict_fingerprint(observation):
    """Alternative equivalence for parametrization: any observable difference is progress."""
    return autonomy.digest(observation)


class Crash(BaseException):
    """Simulates the service process dying inside an effect: not an Exception, so nothing in-process settles it."""


class FakeRoadmap:
    """In-memory roadmap state with the observation shapes the production adapter must supply."""

    def __init__(self, root, codes, *, tasks_per_phase=1):
        self.root, self.codes = root, list(codes)
        self.revision = 1
        self.scope = 'scope-1'
        self.head = 'head-1'
        self.git_clean = True
        self.uncertain_writers = []
        self.manual_batches = []
        self.phases = {code: {'code': code, 'item': 'item-' + code, 'operational': 'ACTIVE' if i == 0 else None,
                              'planned': False, 'proposal': None, 'check': None, 'questions': [], 'closure': None,
                              'tasks': [], 'coverage_complete': False, 'width': tasks_per_phase}
                       for i, code in enumerate(self.codes)}
        self.effects = []          # (name, key) of every effect actually performed
        self.invocations, self.tokens, self.valuation = 0, 0, None
        self.script = {}           # name -> list of outcomes consumed in order
        self.task_script = {}      # task code -> list of 'committed'/'failed'
        self.check_script = {}     # phase code -> list of check dicts
        self.after_adopt = {}      # phase code -> callable(phase)
        self.in_flight = []
        self.settled = True
        self.crash_on = None
        self.gaps = []
        self.requirements = []
        self.gap_calls = 0
        self.items = ['R001', 'criterion-P001']
        self.report_override = None

    # observations ------------------------------------------------------------------------------------------------
    def readiness(self):
        roadmap = [{'code': c, 'item': p['item'], 'criteria': ['criterion-' + c], 'operational': p['operational'],
                    'authorized': p['operational'] not in ('CLOSED', 'ABANDONED')} for c, p in self.phases.items()]
        return {'project_id': self.project_id, 'roadmap': roadmap, 'scope_sha256': self.scope,
                'revision': {'id': f'rev-{self.revision}', 'number': self.revision, 'sha256': f'sha-{self.revision}'},
                'prepared': True, 'clients_compatible': True, 'git_clean': self.git_clean,
                'git': {'head': self.head, 'fingerprint': 'fp'}, 'uncertain_writers': list(self.uncertain_writers),
                'pending_effects': [], 'active_run': self.active_run(), 'manual_batches': list(self.manual_batches),
                'standing_grants': [], 'versions_sha256': 'versions-1'}

    def active_run(self):
        with Session(self.engine) as session:
            run = store.active_run(session, self.root)
            return run.id if run else None

    def observe(self):
        phases = []
        for code, p in self.phases.items():
            phases.append({**copy.deepcopy({k: v for k, v in p.items() if k != 'width'})})
        return {'phases': phases, 'in_flight': list(self.in_flight), 'uncertain': [],
                'requirements': list(self.requirements)}

    def versions_sha256(self):
        return 'versions-1'

    def usage(self, children, basis=None):
        return {'invocations': self.invocations, 'tokens': self.tokens, 'valuation': self.valuation}

    def writers_settled(self, children):
        return {'settled': self.settled, 'active': [] if self.settled else ['job-1']}

    def revision_items(self, revision):
        return list(self.items)

    def gap_report(self, revision):
        self.gap_calls += 1
        if self.report_override is not None:
            return self.report_override
        return {'revision': revision['number'], 'gaps': [dict(g) for g in self.gaps]}

    # effects -----------------------------------------------------------------------------------------------------
    def _record(self, name, key):
        if self.crash_on == name:
            self.crash_on = None
            self.effects.append((name, key))
            raise Crash(name)
        self.effects.append((name, key))
        scripted = self.script.get(name)
        outcome = scripted.pop(0) if scripted else None
        if outcome and outcome['status'] == 'pending':
            self.in_flight = list(outcome['detail']['jobs'])  # a queued job the graph now waits on
        return outcome

    def propose_plan(self, action, key):
        outcome = self._record('propose_plan', key)
        self.invocations += 1
        if outcome:
            return outcome
        phase = self.phases[action['phase']]
        remediation = bool(action.get('remediation'))
        phase['proposal'] = {'operation_id': 'plan-' + key[-8:], 'status': 'PROPOSED', 'sha256': key[-16:],
                             'blocking_questions': False, 'choice_required': False, 'after_check': remediation}
        return {'status': 'done', 'detail': {}}

    def prepare_adoption(self, action):
        proposal = self.phases[action['phase']]['proposal']
        return {'phase_id': action['phase'], 'expected_version': 1, 'draft_id': None, 'coverage': {},
                'preview_sha256': autonomy.digest(proposal), 'revision_id': f'rev-{self.revision}',
                'proposal_operation_id': proposal['operation_id'], 'proposal_sha256': proposal['sha256']}

    def adopt_plan(self, action, child, key):
        outcome = self._record('adopt_plan', key)
        if outcome:
            return outcome
        assert child['origin'] == 'owner_delegated'
        phase = self.phases[action['phase']]
        if action.get('remediation'):
            number = len(phase['tasks']) + 1
            phase['tasks'].append(self._task(phase['code'], number))
        else:
            phase['tasks'] = [self._task(phase['code'], n) for n in range(1, phase['width'] + 1)]
        phase['planned'], phase['proposal'], phase['check'] = True, None, None
        hook = self.after_adopt.pop(phase['code'], None)
        if hook:
            hook(phase)
        return {'status': 'done', 'detail': {}}

    @staticmethod
    def _task(code, number):
        task = f'{code}-T{number:03d}'
        return {'code': task, 'item': 'item-' + task, 'family': [task], 'state': 'pending', 'depends_on': [],
                'paths': ['app/main.txt']}

    def admit_task(self, action, child, key):
        outcome = self._record('admit_task', key)
        self.invocations += 1
        if outcome:
            return outcome
        assert child['permission_record_id'] and child['origin'] == 'owner_delegated'
        task = next(t for t in self.phases[action['phase']]['tasks'] if t['code'] == action['task'])
        task['run_id'] = 'run-' + key[-12:]  # each admission is a new managed run
        scripted = self.task_script.get(task['code'])
        task['state'] = scripted.pop(0) if scripted else 'committed'
        return {'status': 'done', 'detail': {}}

    def check_phase(self, action, key):
        outcome = self._record('check_phase', key)
        self.invocations += 1
        if outcome:
            return outcome
        phase = self.phases[action['phase']]
        scripted = self.check_script.get(phase['code'])
        phase['check'] = scripted.pop(0) if scripted else {'operation_id': 'check-' + key[-8:], 'verdict': 'READY',
                                                           'classification': None, 'unmet': [],
                                                           'binding_sha256': 'b' * 64, 'stale': False}
        return {'status': 'done', 'detail': {}}

    def close_phase(self, action, child, key):
        outcome = self._record('close_phase', key)
        if outcome:
            return outcome
        phase = self.phases[action['phase']]
        index = self.codes.index(phase['code'])
        following = self.codes[index + 1] if index + 1 < len(self.codes) else None
        phase['operational'], phase['coverage_complete'] = 'CLOSED', True
        phase['closure'] = {'criteria_evidence': True, 'successor': following}
        if following:
            self.phases[following]['operational'] = 'ACTIVE'
        return {'status': 'done', 'detail': {}}

    def judge(self, action, key):
        outcome = self._record('judge', key)
        self.invocations += 1
        if outcome:
            return outcome
        phase = self.phases[action['phase']]
        if action['duty'] == 'planning_choice':
            phase['proposal']['choice_required'] = False
        else:
            phase['check'] = {**phase['check'], 'stale': True}
        return {'status': 'done', 'detail': {}}


@pytest.fixture
def world(repository, context):  # noqa: F811
    root = str(context.root)
    with repository._write() as session:
        session.add(KnowledgeProjectRow(id=str(uuid4()), root=root, created_at=repository._now()))
    with Session(repository.engine) as session:
        project = store.project_id(session, root)
    permissions = PermissionLifecycle(repository.engine)
    journal = OperationJournal(repository.engine)

    def build(fake, policy=None, segment_limit=50):
        fake.project_id, fake.engine = project, repository.engine
        return AutonomousRoadmap(repository, permissions, lambda r: fake, journal=journal,
                                 graphs=lambda service: RoadmapGraphs(repository.engine, service,
                                                                      segment_limit=segment_limit),
                                 policy=policy or synthetic_policy())
    return SimpleNamespace(root=root, project=project, repository=repository, permissions=permissions,
                           journal=journal, build=build, engine=repository.engine)


def start(world, fake, *, policy=None, request=REQUEST, key=None, segment_limit=50):
    service = world.build(fake, policy, segment_limit)
    shown = service.preview(world.root, request)
    run = service.confirm(world.root, request, preview_sha256=shown['preview_sha256'], key=key or str(uuid4()),
                          reason='Synthetic owner start.', confirmed=True,
                          acknowledgement_version=service.policy.acknowledgement_version)
    return service, run


def count(world, row):
    with Session(world.engine) as session:
        return session.scalar(select(func.count()).select_from(row))


def assert_no_duplicate_effects(fake):
    keys = [key for _, key in fake.effects]
    assert len(keys) == len(set(keys)), fake.effects


# --- pure contract ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize('current', autonomy.STATES)
@pytest.mark.parametrize('target', autonomy.STATES)
def test_state_machine_matches_fl02(current, target):
    allowed = {
        'RUNNING': set(autonomy.STOPS),
        'WAITING_FOR_OWNER': {'RUNNING', 'REVOKED'}, 'PAUSED': {'RUNNING', 'REVOKED'},
        'LIMIT_REACHED': {'RUNNING', 'REVOKED'}, 'FAILED': {'RUNNING', 'REVOKED'},
        'RECOVERY_REQUIRED': {'PAUSED', 'REVOKED'}, 'REVOKED': set(), 'COMPLETED': set()}
    if target in allowed[current]:
        assert autonomy.transition(current, target) == target
    else:
        with pytest.raises(AutonomyRefusal):
            autonomy.transition(current, target)


@pytest.mark.parametrize('bounds', [None, {}, {**BOUNDS, 'no_progress': 0}, {**BOUNDS, 'task_attempts': 1001},
                                    {**BOUNDS, 'task_attempts': 2.0}, {**BOUNDS, 'extra': 1}])
def test_bounds_are_explicit_and_finite_without_defaults(bounds):
    with pytest.raises(AutonomyRefusal):
        autonomy.validate_bounds(bounds)


@pytest.mark.parametrize('caps, usage, reason', [
    ({'deadline': '2026-01-01T00:00:00+00:00'}, {}, 'cap_deadline'),
    ({'invocations': 2}, {'invocations': 2}, 'cap_invocations'),
    ({'observed_tokens': 10}, {'tokens': None}, 'cap_usage_unknown'),
    ({'observed_tokens': 10}, {'tokens': 10}, 'cap_observed_tokens'),
    ({'valuation': {'amount': '1.50', 'basis': 'synthetic-basis'}}, {'valuation': None}, 'cap_usage_unknown'),
    ({'valuation': {'amount': '1.50', 'basis': 'synthetic-basis'}},
     {'valuation': {'basis': 'other-basis', 'amount': '0.1'}}, 'cap_valuation_basis_incompatible'),
    ({'valuation': {'amount': '1.50', 'basis': 'synthetic-basis'}},
     {'valuation': {'status': 'incompatible', 'basis': 'synthetic-basis', 'amount': None}},
     'cap_valuation_basis_incompatible'),
    ({'valuation': {'amount': '1.50', 'basis': 'synthetic-basis'}},
     {'valuation': {'status': 'unknown', 'basis': 'synthetic-basis', 'amount': None}}, 'cap_usage_unknown'),
    ({'valuation': {'amount': '1.50', 'basis': 'synthetic-basis'}},
     {'valuation': {'basis': 'synthetic-basis', 'amount': '1.5'}}, 'cap_valuation'),
    ({}, {'tokens': None, 'valuation': None}, None),
])
def test_optional_caps_are_thresholds_and_stop_on_unknown_usage_only_when_set(caps, usage, reason):
    stop = autonomy.cap_stop(autonomy.validate_caps(caps), usage, '2026-11-03T10:00:00+00:00')
    assert (stop or {}).get('reason') == reason


@pytest.mark.parametrize('kind, status', [('quota', 'FAILED'), ('authentication', 'FAILED'),
                                          ('environment', 'FAILED'), ('uncertain', 'RECOVERY_REQUIRED'),
                                          ('escalate', 'WAITING_FOR_OWNER'), ('malformed', 'WAITING_FOR_OWNER'),
                                          ('surprise', 'FAILED')])
def test_failure_classes_are_distinct_durable_stops(kind, status):
    stop = autonomy.failure_stop(kind)
    assert stop['status'] == status
    if status == 'FAILED':
        assert stop['detail']['failure_class'] in autonomy.FAILURES


def test_g11_proposal_fingerprint_ignores_rename_timestamps_and_identity_noise():
    base = {'phase_item': 'item-P001', 'planned_families': ['P001-T001'], 'committed_families': [],
            'check_classification': None, 'unmet_criteria': [], 'open_questions': [], 'action': 'admit_task',
            'subject': 'P001-T001'}
    noisy = {**base, 'run_id': 'other', 'timestamp': 'now', 'code': 'renamed'}
    assert autonomy.progress_fingerprint(noisy) == autonomy.progress_fingerprint(base)
    progressed = {**base, 'committed_families': ['P001-T001']}
    assert autonomy.progress_fingerprint(progressed) != autonomy.progress_fingerprint(base)


def test_g12_classification_uses_the_service_revision_items_and_owner_answers():
    cited = [{'item': 'R001', 'revision': 4}]
    gaps = [{'classification': 'advisory', 'citations': cited, 'statement': 'a'},
            {'classification': 'owner_answer_required', 'citations': cited, 'statement': 'b'},
            {'classification': 'advisory', 'citations': [], 'statement': 'uncited'},
            {'classification': 'advisory', 'citations': [{'item': 'R001', 'revision': 3}], 'statement': 'old'},
            {'classification': 'advisory', 'citations': [{'item': 'R999', 'revision': 4}], 'statement': 'ghost'}]
    context = {'revision': 4, 'items': ['R001'], 'answers': []}
    result = autonomy.classify_gaps({'revision': 4, 'gaps': gaps}, context)
    assert (len(result['blocking']), len(result['owner_answer_required']), len(result['advisory'])) == (3, 1, 1)
    answered = autonomy.gap_sha256(gaps[1])
    assert not autonomy.classify_gaps({'revision': 4, 'gaps': gaps[1:2]},
                                      {**context, 'answers': [answered]})['owner_answer_required']
    assert autonomy.classify_gaps({'revision': 3, 'gaps': gaps[:1]}, context)['blocking'] == ['report_revision_mismatch']
    with pytest.raises(AutonomyRefusal):  # answers can never come from the report itself
        autonomy.validate_gap_report({'revision': 4, 'gaps': gaps[1:2], 'answers': [{'gap_sha256': answered}]})


def test_g11_split_family_and_new_operation_cannot_refill_budgets():
    base = {'phase_item': 'item-P001', 'planned_families': ['P001-T001'], 'committed_families': [],
            'check_classification': None, 'unmet_criteria': [], 'open_questions': [], 'action': 'admit_task',
            'subject': 'P001-T001'}
    split = {**base, 'planned_families': ['P001-T001', 'P001-T001']}  # two members of one family after a split
    assert autonomy.progress_fingerprint(split) == autonomy.progress_fingerprint(base)
    assert autonomy.judge_subject('blocked_check', 'item-P001', 'cause') == autonomy.judge_subject(
        'blocked_check', 'item-P001', 'cause')
    view = {'phases': [{'code': 'P001', 'item': 'item-P001', 'tasks': [
        {'code': 'P001-T002', 'family': ['P001-T001', 'P001-T002'], 'state': 'pending'},
        {'code': 'P001-T003', 'family': ['P001-T001', 'P001-T003'], 'state': 'pending'}]}]}
    service = AutonomousRoadmap.__new__(AutonomousRoadmap)
    progress = service._progress(view, {'action': 'admit_task', 'phase': 'P001', 'family': ['P001-T001', 'P001-T002']})
    assert progress['planned_families'] == ['P001-T001']
    first = service._bound(view, {'action': 'judge', 'duty': 'blocked_check', 'phase': 'P001', 'operation_id': 'op-1',
                                  'cause': 'c'})
    second = service._bound(view, {'action': 'judge', 'duty': 'blocked_check', 'phase': 'P001', 'operation_id': 'op-2',
                                   'cause': 'c'})
    assert first == second


def test_product_policy_is_the_owner_accepted_one():
    policy = autonomy.product_policy()
    assert policy.pending() == () and policy.label == 'product'
    assert policy.default_bounds == {'task_attempts': 3, 'judge_reconsiderations': 1, 'replacement_plans': 2,
                                     'remediation_per_cause': 2, 'no_progress': 3}
    assert (policy.fingerprint_version, policy.readiness_version, policy.acknowledgement_version) == (
        'g11-1', 'g12-1', 'autonomy-ack-1')
    assert autonomy.digest(policy.acknowledgement) == autonomy.ACKNOWLEDGEMENT_SHA256
    assert 'already running may exceed' in policy.acknowledgement['en']
    assert 'ya en curso puede superarlos' in policy.acknowledgement['es']


# --- gates, readiness and admission -----------------------------------------------------------------------------

def test_pending_policy_keeps_readiness_and_confirmation_blocked(world):
    fake = FakeRoadmap(world.root, ['P001', 'P002'])
    service = world.build(fake, autonomy.PENDING_POLICY)
    report = service.readiness(world.root, REQUEST)
    assert all(check['passed'] for check in report['checks'])
    assert report['verdict'] == 'PENDING_GATES' and report['gates']['pending_gates'] == ['G11', 'G12', 'G17']
    shown = service.preview(world.root, REQUEST)
    assert shown['acknowledgement'] == {'version': None, 'sha256': None, 'text': None}
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='k', reason='r',
                        confirmed=True, acknowledgement_version=None)
    assert refused.value.code == 'gates_pending' and refused.value.detail['gates'] == ['G11', 'G12', 'G17']
    assert count(world, AutonomousAuthorizationRow) == count(world, AutonomousRunRow) == 0
    assert count(world, PermissionRecordRow) == 0
    assert fake.effects == []


@pytest.mark.parametrize('field, value, check', [
    ('git_clean', False, 'git_baseline_clean'), ('uncertain_writers', ['job-9'], 'no_uncertain_writer'),
    ('manual_batches', ['batch-1'], 'no_manual_batch'), ('scope_missing_criteria', True, 'criteria_present'),
    ('no_active_phase', True, 'active_phase'), ('bounds', None, 'bounds_feasible')])
def test_structural_readiness_failures_block_without_any_model(world, field, value, check):
    fake = FakeRoadmap(world.root, ['P001', 'P002'])
    request = dict(REQUEST)
    if field == 'bounds':
        request['bounds'] = None
    elif field == 'scope_missing_criteria':
        original = fake.readiness
        fake.readiness = lambda: {**original(), 'roadmap': [{**p, 'criteria': []} for p in original()['roadmap']]}
    elif field == 'no_active_phase':
        fake.phases['P001']['operational'] = None
    else:
        setattr(fake, field, value)
    service = world.build(fake)
    report = service.readiness(world.root, request)
    assert report['verdict'] == 'BLOCKED' and check in report['blocking']
    shown = service.preview(world.root, request)
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, request, preview_sha256=shown['preview_sha256'], key='k', reason='r',
                        confirmed=True, acknowledgement_version='synthetic-ack-1')
    assert refused.value.code == 'readiness_not_ready'
    assert fake.effects == []


def test_g12_reviewer_runs_once_after_structural_checks_and_answers_come_from_owner_records(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.gaps = [{'classification': 'owner_answer_required', 'statement': 'Ambiguous R001',
                  'citations': [{'item': 'R001', 'revision': 1}]}]
    service = world.build(fake)
    fake.git_clean = False
    assert service.readiness(world.root, REQUEST)['verdict'] == 'BLOCKED' and fake.gap_calls == 0
    fake.git_clean = True
    report = service.readiness(world.root, REQUEST)
    assert report['verdict'] == 'BLOCKED' and report['owner_answer_required'] and fake.gap_calls == 1
    assert report['default_bounds'] == BOUNDS
    gap = report['gaps'][0]['gap_sha256']
    with pytest.raises(AutonomyRefusal):
        service.answer_gap(world.root, gap_sha256='0' * 64, text='Unknown gap.', key='g0')
    service.answer_gap(world.root, gap_sha256=gap, text='R001 means the synthetic reading.', key='g1')
    fake.revision = 2  # a new frozen revision: the answer is no longer current and a new report is requested
    fake.gaps = [{**fake.gaps[0], 'citations': [{'item': 'R001', 'revision': 2}]}]
    moved = service.readiness(world.root, REQUEST)
    assert moved['verdict'] == 'BLOCKED' and moved['owner_answer_required'] and fake.gap_calls == 2
    fake.revision = 1
    shown = service.preview(world.root, REQUEST)
    assert shown['readiness']['verdict'] == 'READY' and fake.gap_calls == 2  # sealed revision-1 report reused
    fake.gaps = [{'classification': 'blocking', 'statement': 'Different report', 'citations': []}]
    run = service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='start',
                          reason='Synthetic start.', confirmed=True, acknowledgement_version='synthetic-ack-1')
    assert run['status'] == 'COMPLETED' and fake.gap_calls == 2  # confirmation never generates another report


@pytest.mark.parametrize('produced, blocking', [
    ({'revision': 1, 'gaps': [{'classification': 'advisory', 'statement': 's',
                               'citations': [{'item': 'R404', 'revision': 1}]}]}, 1),
    ({'revision': 7, 'gaps': []}, 'report_revision_mismatch'),
    ({'revision': 1, 'gaps': 'not a list'}, 'gap_report_malformed'),
])
def test_g12_report_is_validated_against_the_frozen_revision_and_never_retried(world, produced, blocking):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.report_override = produced
    service = world.build(fake)
    report = service.readiness(world.root, REQUEST)
    assert report['verdict'] == 'BLOCKED'
    assert (len(report['blocking']) == blocking) if isinstance(blocking, int) else (blocking in report['blocking'])
    service.readiness(world.root, REQUEST)
    assert fake.gap_calls == 1


def test_confirmation_without_a_sealed_report_is_refused(world):
    fake = FakeRoadmap(world.root, ['P001'])
    service = world.build(fake)
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, REQUEST, preview_sha256='0' * 64, key='no-preview', reason='r', confirmed=True,
                        acknowledgement_version='synthetic-ack-1')
    assert refused.value.code in ('preview_stale', 'readiness_not_ready') and fake.gap_calls == 0


def test_confirmation_is_exact_idempotent_and_revalidated(world):
    fake = FakeRoadmap(world.root, ['P001'])
    service = world.build(fake)
    shown = service.preview(world.root, REQUEST)
    common = dict(reason='Synthetic owner start.', confirmed=True, acknowledgement_version='synthetic-ack-1')
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='k1',
                        **{**common, 'acknowledgement_version': 'other'})
    assert refused.value.code == 'acknowledgement_required'
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='k1',
                        **{**common, 'confirmed': False})
    assert refused.value.code == 'explicit_owner_confirmation_required'
    fake.head = 'head-2'  # the Git baseline moved after the preview
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='k1', **common)
    assert refused.value.code == 'preview_stale'
    shown = service.preview(world.root, REQUEST)
    first = service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='k1', **common)
    again = service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='k1', **common)
    assert first['id'] == again['id'] and first['status'] == 'COMPLETED'
    with pytest.raises(AutonomyRefusal) as refused:
        service.confirm(world.root, {**REQUEST, 'caps': {'invocations': 9}}, preview_sha256=shown['preview_sha256'],
                        key='k1', **common)
    assert refused.value.code == 'idempotency_conflict'
    assert count(world, AutonomousAuthorizationRow) == count(world, AutonomousRunRow) == 1
    with Session(world.engine) as session:
        auth = session.scalar(select(AutonomousAuthorizationRow))
        parent = session.get(PermissionRecordRow, auth.permission_record_id)
    assert auth.origin == 'owner_confirmed' and auth.preview_sha256 == shown['preview_sha256']
    assert auth.preview['bounds'] == BOUNDS and auth.preview['delegation']['tiers'] == {
        k: sorted(v) for k, v in DELEGATION['tiers'].items()}
    assert auth.policy['label'] == 'synthetic' and auth.preview['acknowledgement']['version'] == 'synthetic-ack-1'
    assert parent.payload['origin'] == 'owner_confirmed' and parent.payload['targets'] == []
    assert parent.payload['autonomous']['phases'] == ['P001']


def test_one_active_authorization_per_root_under_concurrent_starts(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.script['admit_task'] = [{'status': 'pending', 'detail': {'jobs': ['job-1']}}]
    services = [world.build(fake), world.build(fake)]
    shown = services[0].preview(world.root, REQUEST)
    barrier = threading.Barrier(2)

    def attempt(index):
        barrier.wait()
        try:
            return services[index].confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'],
                                           key=f'concurrent-{index}', reason='Synthetic start.', confirmed=True,
                                           acknowledgement_version='synthetic-ack-1')
        except AutonomyRefusal as error:
            return error.code
    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    refusals = [o for o in outcomes if isinstance(o, str)]
    assert len(refusals) == 1 and refusals[0] in ('autonomous_run_active', 'preview_stale')
    assert count(world, AutonomousRunRow) == 1
    with Session(world.engine) as session:
        session.execute(text('SELECT 1'))
        with pytest.raises(Exception):
            with world.repository._write() as write:
                run = write.scalar(select(AutonomousRunRow))
                write.add(AutonomousRunRow(id=str(uuid4()), root=world.root, lineage_id=str(uuid4()),
                                           authorization_id=run.authorization_id, thread_id='other', status='PAUSED',
                                           version=1, created_at='t', updated_at='t'))


def _phase(world, status='ACTIVE'):
    phase_id = str(uuid4())
    with world.repository._write() as session:
        session.add(PhaseRow(id=phase_id, root=world.root, code='P001', definition={'tasks': ['P001-T001']},
                             definition_sha256='0' * 64, documents={}, status=status, version=1,
                             created_at='t', updated_at='t'))
    return phase_id


def test_manual_batches_and_autonomous_runs_exclude_each_other(world, monkeypatch):
    from my_harness.storage import knowledge_exchange
    from my_harness.storage.managed import Conflict
    from my_harness.storage.phases import PhaseRepository
    monkeypatch.setattr(knowledge_exchange, 'require_documentary_lane', lambda session, root: None)
    phase_id = _phase(world)
    phases = PhaseRepository(world.repository)

    def version():
        with Session(world.engine) as session:
            return session.get(PhaseRow, phase_id).version
    phases.authorize_batch(phase_id, version(), tasks=['P001-T001'], ttl_seconds=60, reason='Manual batch.')
    fake = FakeRoadmap(world.root, ['P001'])
    with Session(world.engine) as session:
        fake.manual_batches = store.active_batches(session, world.root)
    with pytest.raises(AutonomyRefusal):
        start(world, fake)
    with world.repository._write() as session:
        for row in session.scalars(select(PhaseAuthorizationRow)):
            row.status = 'REVOKED'
    fake.manual_batches = []
    fake.script['admit_task'] = [{'status': 'pending', 'detail': {'jobs': ['job-1']}}]
    fake.in_flight = []
    service, run = start(world, fake)
    assert run['status'] == 'RUNNING'
    with pytest.raises(Conflict):
        phases.authorize_batch(phase_id, version(), tasks=['P001-T001'], ttl_seconds=60, reason='Manual batch.')
    service.revoke(world.root, run['id'], expected_version=service.status_by_id(run['id'])['version'],
                   reason='Owner ends the run.')
    phases.authorize_batch(phase_id, version(), tasks=['P001-T001'], ttl_seconds=60, reason='Manual batch again.')


def test_interrupted_run_creation_is_reconciled_without_duplicates(world):
    fake = FakeRoadmap(world.root, ['P001', 'P002'])
    service = world.build(fake)
    shown = service.preview(world.root, REQUEST)
    real = service._graph_factory
    service._graph_factory = lambda svc: (_ for _ in ()).throw(RuntimeError('process stopped before the graph'))
    with pytest.raises(RuntimeError):
        service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='interrupted',
                        reason='Synthetic start.', confirmed=True, acknowledgement_version='synthetic-ack-1')
    assert count(world, AutonomousAuthorizationRow) == count(world, AutonomousRunRow) == 1
    assert count(world, GraphThreadRow) == 0
    restarted = world.build(fake)
    assert restarted.reconcile(world.root)['status'] == 'COMPLETED'
    replay = restarted.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='interrupted',
                               reason='Synthetic start.', confirmed=True, acknowledgement_version='synthetic-ack-1')
    assert replay['status'] == 'COMPLETED'
    assert count(world, AutonomousAuthorizationRow) == count(world, AutonomousRunRow) == count(world, GraphThreadRow) == 1
    assert real is not None


# --- normal routes ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('fingerprint', [autonomy.progress_fingerprint, strict_fingerprint])
def test_multi_phase_roadmap_completes_through_delegated_children(world, fingerprint):
    fake = FakeRoadmap(world.root, ['P001', 'P002', 'P003'], tasks_per_phase=2)
    service, run = start(world, fake, policy=synthetic_policy(fingerprint))
    assert run['status'] == 'COMPLETED' and run['reason'] == 'roadmap_completed'
    kinds = [c['kind'] for c in run['children']]
    assert kinds == ['plan_proposal', 'plan_adoption', 'task_admission', 'task_admission', 'phase_check',
                     'phase_closure'] * 3
    assert all(c['origin'] == 'owner_delegated' and c['authorization_id'] == run['authorization']['id']
               for c in run['children'])
    assert_no_duplicate_effects(fake)
    with Session(world.engine) as session:
        tasks = [session.get(PermissionRecordRow, c['permission_record_id']) for c in run['children']
                 if c['kind'] == 'task_admission']
        parent = run['authorization']
        auth = session.get(AutonomousAuthorizationRow, parent['id'])
    assert all(t.payload['origin'] == 'owner_delegated' and t.payload['parent'] == auth.permission_record_id
               and t.payload['purpose'].startswith('task:') for t in tasks)
    events = [e['kind'] for e in service.events(world.root, run['id'], limit=100)]
    assert events[0] == 'run_started' and events[-1] == 'run_completed'
    assert all(e['dedupe_key'] for e in service.events(world.root, run['id'], limit=100))
    assert run['consumption']['task_attempts'] == {f'P00{p}-T00{t}': 1 for p in (1, 2, 3) for t in (1, 2)}


def test_long_roadmap_crosses_durable_segments_without_a_phase_cap(world):
    codes = [f'P{n:03d}' for n in range(1, 13)]
    fake = FakeRoadmap(world.root, codes)
    service, run = start(world, fake, segment_limit=5)
    assert run['status'] == 'COMPLETED'
    with Session(world.engine) as session:
        thread = session.get(GraphThreadRow, run['thread_id'])
    assert thread.status == 'COMPLETED' and thread.segments >= 5
    assert sum(1 for c in run['children'] if c['kind'] == 'phase_closure') == 12
    assert_no_duplicate_effects(fake)


def test_planning_choice_and_blocked_check_use_judge_children_without_replacing_ready(world):
    fake = FakeRoadmap(world.root, ['P001'])
    original = fake.propose_plan

    def choosing(action, key):
        result = original(action, key)
        fake.phases['P001']['proposal']['choice_required'] = True
        return result
    fake.propose_plan = choosing
    fake.check_script['P001'] = [{'operation_id': 'check-1', 'verdict': 'BLOCKED',
                                  'classification': 'planning_ambiguity', 'unmet': [], 'binding_sha256': None,
                                  'stale': False}]
    service, run = start(world, fake)
    assert run['status'] == 'COMPLETED'
    kinds = [c['kind'] for c in run['children']]
    assert kinds.count('judge_request') == 2 and kinds.index('judge_request') < kinds.index('plan_adoption')
    assert kinds[-2:] == ['phase_check', 'phase_closure']  # READY came from a fresh check, not from the ruling


def test_remediation_is_bounded_per_cause_and_keeps_lineage(world):
    fake = FakeRoadmap(world.root, ['P001'])
    missing = {'operation_id': 'check-x', 'verdict': 'NOT_READY', 'classification': 'missing_work',
               'unmet': ['criterion-P001'], 'binding_sha256': None, 'stale': False}
    fake.check_script['P001'] = [dict(missing), dict(missing), dict(missing)]
    service, run = start(world, fake, request={**REQUEST, 'bounds': {**BOUNDS, 'remediation_per_cause': 2}})
    assert run['status'] == 'LIMIT_REACHED' and run['reason'] == 'bound_remediation_per_cause'
    assert sum(run['consumption']['remediation_per_cause'].values()) == 2
    assert [t['code'] for t in fake.phases['P001']['tasks']] == ['P001-T001', 'P001-T002', 'P001-T003']


# --- waits, answers, limits, caps --------------------------------------------------------------------------------

def test_question_answer_validation_stale_answers_and_explicit_resume(world):
    fake = FakeRoadmap(world.root, ['P001', 'P002'])
    fake.after_adopt['P002'] = lambda phase: phase['questions'].append('question-p002')
    service, run = start(world, fake)
    assert run['status'] == 'WAITING_FOR_OWNER' and run['reason'] == 'owner_phase_questions'
    [question] = run['questions']
    assert question['binding']['authorization_id'] == run['authorization']['id']
    with pytest.raises(AutonomyRefusal) as refused:
        service.resume(world.root, run['id'], expected_version=run['version'])
    assert refused.value.code == 'questions_open'
    with pytest.raises(AutonomyRefusal) as refused:
        service.answer(world.root, run['id'], question['id'], expected_version=question['version'] + 1,
                       answer={'text': 'Answer.'}, key='a1')
    assert refused.value.code == 'question_stale'
    fake.revision = 2  # the accepted revision moved since the question was asked
    superseded = service.answer(world.root, run['id'], question['id'], expected_version=question['version'],
                                answer={'text': 'Answer.'}, key='a1')
    assert superseded['superseded'] and superseded['status'] == 'SUPERSEDED'
    fake.phases['P002']['questions'] = []  # the owner answered the phase question through the phase controls
    run = service.status_by_id(run['id'])
    resumed = service.resume(world.root, run['id'], expected_version=run['version'])
    assert resumed['status'] == 'COMPLETED'
    assert_no_duplicate_effects(fake)


def test_answer_is_idempotent_and_bound_to_current_state(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.after_adopt['P001'] = lambda phase: phase['questions'].append('question-p001')
    service, run = start(world, fake)
    [question] = run['questions']
    answered = service.answer(world.root, run['id'], question['id'], expected_version=1,
                              answer={'text': 'Use the first option.'}, key='answer-1')
    assert answered['status'] == 'ANSWERED' and answered['answer']['origin'] == 'owner_confirmed'
    assert service.answer(world.root, run['id'], question['id'], expected_version=1,
                          answer={'text': 'Use the first option.'}, key='answer-1')['version'] == 2
    with pytest.raises(AutonomyRefusal) as refused:
        service.answer(world.root, run['id'], question['id'], expected_version=1, answer={'text': 'Other.'},
                       key='answer-1')
    assert refused.value.code == 'idempotency_conflict'
    with pytest.raises(AutonomyRefusal):
        service.answer(world.root, run['id'], question['id'], expected_version=2, answer={'text': 'Again.'},
                       key='answer-2')


def retry_until_stopped(world, service, run, reason):
    """A failed delegated task is a durable stop; each retry needs an explicit owner resume."""
    for _ in range(10):
        if run['status'] != 'FAILED':
            break
        assert run['reason'] == 'operational_failure'
        run = service.resume(world.root, run['id'], expected_version=run['version'])
    assert run['status'] == 'LIMIT_REACHED' and run['reason'] == reason, (run['status'], run['reason'])
    return run


def test_failed_task_is_a_durable_stop_until_an_explicit_resume(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.task_script['P001-T001'] = ['failed']
    service, run = start(world, fake)
    assert (run['status'], run['reason']) == ('FAILED', 'operational_failure')
    admissions = [n for n, _ in fake.effects].count('admit_task')
    for _ in range(3):
        service.advance_all()
    assert [n for n, _ in fake.effects].count('admit_task') == admissions == 1  # never readmitted on its own
    assert service.resume(world.root, run['id'], expected_version=run['version'])['status'] == 'COMPLETED'
    assert [n for n, _ in fake.effects].count('admit_task') == 2


def test_task_attempt_bound_persists_across_resume_revision_and_replacement(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.task_script['P001-T001'] = ['failed'] * 10
    request = {**REQUEST, 'bounds': {**BOUNDS, 'task_attempts': 2, 'no_progress': 50}}
    service, run = start(world, fake, request=request)
    run = retry_until_stopped(world, service, run, 'bound_task_attempts')
    with pytest.raises(AutonomyRefusal) as refused:
        service.resume(world.root, run['id'], expected_version=run['version'])
    assert refused.value.code == 'run_not_resumable'
    # The owner adopts a replacement task in the same D296 family: it is counted together, never refilled.
    task = fake.phases['P001']['tasks'][0]
    task.update(code='P001-T002', family=['P001-T001', 'P001-T002'])
    fake.task_script['P001-T002'] = ['failed'] * 10
    lower = {**request, 'bounds': {**request['bounds'], 'task_attempts': 1}}
    shown = service.preview(world.root, lower, lineage=run['authorization']['lineage_id'])
    with pytest.raises(AutonomyRefusal) as refused:
        service.revise(world.root, run['id'], lower, preview_sha256=shown['preview_sha256'], key='lower',
                       reason='Lower.', confirmed=True, acknowledgement_version='synthetic-ack-1')
    assert refused.value.code == 'bounds_cannot_decrease'
    raised = {**request, 'bounds': {**request['bounds'], 'task_attempts': 3}}
    shown = service.preview(world.root, raised, lineage=run['authorization']['lineage_id'])
    revised = service.revise(world.root, run['id'], raised, preview_sha256=shown['preview_sha256'], key='raise',
                             reason='Owner raises the bound.', confirmed=True,
                             acknowledgement_version='synthetic-ack-1')
    assert revised['authorization']['number'] == 2
    revised = retry_until_stopped(world, service, revised, 'bound_task_attempts')
    attempts = revised['consumption']['task_attempts']
    assert attempts == {'P001-T001': 2, 'P001-T002': 1}  # three in the family: the raised bound, not a reset
    with Session(world.engine) as session:
        old, new = session.scalars(select(AutonomousAuthorizationRow).order_by(AutonomousAuthorizationRow.number))
        assert not world.permissions.active(session, session.get(PermissionRecordRow, old.permission_record_id))
        assert world.permissions.active(session, session.get(PermissionRecordRow, new.permission_record_id))


@pytest.mark.parametrize('fingerprint', [autonomy.progress_fingerprint, strict_fingerprint])
def test_no_progress_bound_stops_equivalent_repetition(world, fingerprint):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.task_script['P001-T001'] = ['failed'] * 10
    request = {**REQUEST, 'bounds': {**BOUNDS, 'task_attempts': 50, 'no_progress': 3}}
    service, run = start(world, fake, policy=synthetic_policy(fingerprint), request=request)
    run = retry_until_stopped(world, service, run, 'bound_no_progress')
    assert run['consumption']['task_attempts'] == {'P001-T001': 3}


@pytest.mark.parametrize('caps, setup, reason', [
    ({'observed_tokens': 1000}, lambda f: setattr(f, 'tokens', None), 'cap_usage_unknown'),
    ({'valuation': {'amount': '5', 'basis': 'synthetic-basis'}}, lambda f: None, 'cap_usage_unknown'),
    ({'invocations': 2}, lambda f: None, 'cap_invocations'),
    ({'deadline': '2020-01-01T00:00:00+00:00'}, lambda f: None, 'cap_deadline'),
])
def test_caps_are_checked_before_each_inference(world, caps, setup, reason):
    fake = FakeRoadmap(world.root, ['P001'])
    setup(fake)
    _, run = start(world, fake, request={**REQUEST, 'caps': caps})
    assert run['status'] == 'LIMIT_REACHED' and run['reason'] == reason
    inferences = [name for name, _ in fake.effects if name in autonomy.INFERENCE_ACTIONS]
    assert len(inferences) == (2 if reason == 'cap_invocations' else 0)


@pytest.mark.parametrize('failure', ['quota', 'authentication', 'environment'])
def test_quota_auth_and_environment_stop_without_retry_or_polling(world, failure):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.script['check_phase'] = [{'status': failure, 'detail': {}}]
    service, run = start(world, fake)
    assert run['status'] == 'FAILED' and run['detail']['stop']['failure_class'] == failure
    assert [n for n, _ in fake.effects].count('check_phase') == 1
    resumed = service.resume(world.root, run['id'], expected_version=run['version'])
    assert resumed['status'] == 'COMPLETED'
    assert [n for n, _ in fake.effects].count('check_phase') == 2


def test_pause_is_observed_at_the_next_boundary_and_resume_revalidates(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.script['admit_task'] = [{'status': 'pending', 'detail': {'jobs': ['job-1']}}]
    service, run = start(world, fake)
    assert run['status'] == 'RUNNING'
    paused = service.pause(world.root, run['id'], expected_version=run['version'], reason='Owner pause.')
    assert paused['status'] == 'PAUSED'
    fake.in_flight = []
    task = fake.phases['P001']['tasks'][0]
    task['state'] = 'committed'
    assert service.advance_waiting(world.root) is None  # a paused run is never advanced by the harness
    fake.git_clean = False
    with pytest.raises(AutonomyRefusal) as refused:
        service.resume(world.root, run['id'], expected_version=paused['version'])
    assert 'git_baseline_clean' in refused.value.detail['reasons']
    fake.git_clean = True
    assert service.resume(world.root, run['id'], expected_version=paused['version'])['status'] == 'COMPLETED'


def test_scope_amendment_waits_for_a_new_authorization_revision(world):
    fake = FakeRoadmap(world.root, ['P001', 'P002'])
    fake.after_adopt['P002'] = lambda phase: setattr(fake, 'scope', 'scope-2')  # owner changed criteria
    service, run = start(world, fake)
    assert run['status'] == 'WAITING_FOR_OWNER' and run['reason'] == 'scope_amended'
    shown = service.preview(world.root, REQUEST, lineage=run['authorization']['lineage_id'])
    revised = service.revise(world.root, run['id'], REQUEST, preview_sha256=shown['preview_sha256'], key='amend',
                             reason='Owner accepts the amended scope.', confirmed=True,
                             acknowledgement_version='synthetic-ack-1')
    assert revised['status'] == 'COMPLETED' and revised['authorization']['number'] == 2
    assert [q['status'] for q in revised['questions']] == ['SUPERSEDED']


# --- revocation, recovery, abandonment and authority boundaries ------------------------------------------------

def test_revocation_blocks_admissions_and_ends_delegated_authority(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.script['admit_task'] = [{'status': 'pending', 'detail': {'jobs': ['job-1']}}]
    service, run = start(world, fake)
    child = next(c for c in run['children'] if c['kind'] == 'task_admission')
    revoked = service.revoke(world.root, run['id'], expected_version=run['version'], reason='Owner revokes.')
    assert revoked['status'] == 'REVOKED'
    with Session(world.engine) as session:
        assert not world.permissions.active(session, session.get(PermissionRecordRow, child['permission_record_id']))
        assert session.get(GraphThreadRow, run['thread_id']).status == 'REVOKED'
    fake.in_flight = []
    assert service.advance_waiting(world.root) is None
    with pytest.raises(AutonomyRefusal):
        service.resume(world.root, run['id'], expected_version=revoked['version'])
    effects = len(fake.effects)
    assert service.status_by_id(run['id'])['status'] == 'REVOKED' and len(fake.effects) == effects


def test_crash_recovery_requires_stopped_writer_and_never_reissues_the_effect(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.crash_on = 'check_phase'
    service = world.build(fake)
    shown = service.preview(world.root, REQUEST)
    with pytest.raises(Crash):
        service.confirm(world.root, REQUEST, preview_sha256=shown['preview_sha256'], key='crash',
                        reason='Synthetic start.', confirmed=True, acknowledgement_version='synthetic-ack-1')
    crashed_key = next(key for name, key in fake.effects if name == 'check_phase')
    restarted = world.build(fake)
    run = restarted.reconcile(world.root)
    assert run['status'] == 'RECOVERY_REQUIRED' and run['reason'] == 'graph_writer_unconfirmed'
    with pytest.raises(AutonomyRefusal):
        restarted.resume(world.root, run['id'], expected_version=run['version'])
    with pytest.raises(AutonomyRefusal) as refused:
        restarted.recover(world.root, run['id'], expected_version=run['version'], writer_stopped=False, reason='x')
    assert refused.value.code == 'writer_stop_confirmation_required'
    fake.settled = False
    with pytest.raises(AutonomyRefusal) as refused:
        restarted.recover(world.root, run['id'], expected_version=run['version'], writer_stopped=True,
                          reason='Owner checked the process.')
    assert refused.value.code == 'writer_not_confirmed_stopped'
    fake.settled = True
    recovered = restarted.recover(world.root, run['id'], expected_version=run['version'], writer_stopped=True,
                                  reason='Owner confirmed the writer stopped.')
    assert recovered['status'] == 'PAUSED' and recovered['detail']['recovered']['abandoned']
    with Session(world.engine) as session:
        operation = session.scalar(select(WorkflowOperationRow).where(WorkflowOperationRow.key == crashed_key))
        assert operation.status == 'ABANDONED'
    done = restarted.resume(world.root, run['id'], expected_version=recovered['version'])
    assert done['status'] == 'COMPLETED'
    assert [key for name, key in fake.effects if name == 'check_phase'].count(crashed_key) == 1
    assert_no_duplicate_effects(fake)


def test_node_failure_continues_on_a_new_thread_only_without_pending_operations(world):
    fake = FakeRoadmap(world.root, ['P001'])
    original = fake.observe
    calls = {'n': 0}

    def flaky():
        calls['n'] += 1
        if calls['n'] == 3:
            raise RuntimeError('synthetic node failure')
        return original()
    fake.observe = flaky
    service, run = start(world, fake)
    assert run['status'] == 'FAILED' and run['reason'] == 'node_failed'
    resumed = service.resume(world.root, run['id'], expected_version=run['version'])
    assert resumed['status'] == 'COMPLETED' and resumed['thread_id'].endswith('-c1')
    assert_no_duplicate_effects(fake)


@pytest.mark.parametrize('case', ['abandoned', 'successor_missing', 'evidence_incomplete'])
def test_abandonment_or_missing_successor_is_never_success(world, case):
    fake = FakeRoadmap(world.root, ['P001', 'P002'])
    original = fake.close_phase

    def close(action, child, key):
        result = original(action, child, key)
        if action['phase'] == 'P001':
            if case == 'abandoned':
                fake.phases['P002']['operational'] = 'ABANDONED'
            elif case == 'successor_missing':
                fake.phases['P002']['operational'] = None
        elif case == 'evidence_incomplete':
            fake.phases['P002']['coverage_complete'] = False
        return result
    fake.close_phase = close
    _, run = start(world, fake)
    assert run['status'] == 'FAILED'
    assert run['reason'] == {'abandoned': 'phase_abandoned', 'successor_missing': 'successor_missing',
                             'evidence_incomplete': 'completion_evidence_incomplete'}[case]


def test_task_children_satisfy_t014_scope_and_cascade_on_revocation(world, context):  # noqa: F811
    from my_harness.storage.managed import Conflict
    permissions, project = world.permissions, world.project
    contract = '{"allowed_paths": ["app/main.txt"]}'
    with world.repository._write() as session:
        parent = permissions.roadmap_parent(session, project, authorization_id=str(uuid4()), phases=['P001'],
                                            tiers=DELEGATION['tiers'], delegation=None, actor={'user': 'owner'})
        child = permissions.task_child(session, project, parent=parent, phase='P001', task='P001-T001',
                                       paths=['app/main.txt'], rule='roadmap.task_admission@1')
        for phase, paths in (('P009', ['app/main.txt']), ('P001', [])):  # out of scope, or no exact target
            with pytest.raises(Exception):
                with session.begin_nested():
                    permissions.task_child(session, project, parent=parent, phase=phase, task=phase + '-T001',
                                           paths=paths, rule='roadmap.task_admission@1')
        world.repository._check_delegated_scope(session, world.root, 'P001', 'P001-T001', child, contract)
        permissions.end_roadmap(session, project, parent, reason='Owner revokes.', actor={'user': 'owner'})
        with pytest.raises(Conflict):
            world.repository._check_delegated_scope(session, world.root, 'P001', 'P001-T001', child, contract)
    narrow = {**DELEGATION['tiers'], 'delegable': []}
    with world.repository._write() as session:
        other = permissions.roadmap_parent(session, project, authorization_id=str(uuid4()), phases=['P001'],
                                           tiers=narrow, delegation=None, actor={'user': 'owner'})
        with pytest.raises(Exception):
            permissions.task_child(session, project, parent=other, phase='P001', task='P001-T001',
                                   paths=['app/main.txt'], rule='roadmap.task_admission@1')


def test_insert_only_evidence_cannot_be_rewritten(world):
    fake = FakeRoadmap(world.root, ['P001'])
    start(world, fake)
    for table in ('autonomous_authorizations', 'autonomous_children', 'autonomous_consumption', 'autonomous_events'):
        with pytest.raises(Exception):
            with world.repository._write() as session:
                session.execute(text(f'DELETE FROM {table}'))
    assert count(world, AutonomousChildRow) == 5 and count(world, AutonomousConsumptionRow) >= 5


def test_revoked_parent_cancels_the_delegated_writer_through_existing_process_control(world, context):  # noqa: F811
    from my_harness.storage.models import ManagedEventRow
    from test_managed import submit
    manual = submit(world.repository, context, key='manual-run')
    delegated = submit(world.repository, context, key='delegated-run')
    with world.repository._write() as session:
        parent = world.permissions.roadmap_parent(session, world.project, authorization_id=str(uuid4()),
                                                  phases=['P001'], tiers=DELEGATION['tiers'], delegation=None,
                                                  actor={'user': 'owner'})
        child = world.permissions.task_child(session, world.project, parent=parent, phase='P001', task='P001-T001',
                                             paths=['app/main.txt'], rule='roadmap.task_admission@1')
        session.add(ManagedEventRow(run_id=delegated.run_id, sequence=999, kind='task_delegated', recorded_at='t',
                                    payload={'authorization_id': child, 'contract_json': '{}'}))
    with Session(world.engine) as session:
        assert not world.permissions.cancelled(session, delegated.run_id)
        assert not world.permissions.cancelled(session, manual.run_id)
    with world.repository._write() as session:
        world.permissions.end_roadmap(session, world.project, parent, reason='Owner revokes.', actor={'user': 'o'})
    with Session(world.engine) as session:
        assert world.permissions.cancelled(session, delegated.run_id)  # the supervisor's cancellation poll fires
        assert not world.permissions.cancelled(session, manual.run_id)  # manual runs are unaffected


def test_http_controls_refuse_a_start_that_is_not_ready(tmp_path, migrated_database, monkeypatch, context):  # noqa: F811
    from my_harness.services.managed_runtime import CONFIG_ENV
    from test_managed_api import client, config
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    body = {'bounds': BOUNDS, 'caps': {}, 'delegation': DELEGATION}
    with client(migrated_database[0], tmp_path, config(context, commit=False, supervisor=False)) as http:
        base = '/api/managed/projects/synthetic/autonomous'
        report = http.post(base + '/readiness', json=body)
        assert report.status_code == 200, report.text
        assert report.json()['verdict'] == 'BLOCKED' and 'accepted_revision' in report.json()['blocking']
        assert report.json()['gates']['pending_gates'] == [] and report.json()['default_bounds']['task_attempts'] == 3
        shown = http.post(base + '/preview', json=body)
        assert shown.status_code == 200 and shown.json()['acknowledgement']['version'] == 'autonomy-ack-1'
        refused = http.post(base + '/confirm', headers={'Idempotency-Key': 'start'}, json={
            'request': body, 'preview_sha256': shown.json()['preview_sha256'], 'reason': 'Owner start.',
            'confirmed': True, 'acknowledgement_version': 'autonomy-ack-1'})
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'readiness_not_ready'
        assert http.get(base).status_code == 404
        no_defaults = http.post(base + '/readiness', json={'delegation': DELEGATION})
        assert 'bounds_feasible' in no_defaults.json()['blocking'] or no_defaults.json()['verdict'] == 'BLOCKED'
        missing_key = http.post(base + '/confirm', json={'request': body, 'preview_sha256': '0' * 64,
                                                         'reason': 'r', 'confirmed': True})
        assert missing_key.status_code == 422


def test_run_revocation_succeeds_after_the_parent_was_ended_elsewhere(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.script['admit_task'] = [{'status': 'pending', 'detail': {'jobs': ['job-1']}}]
    service, run = start(world, fake)
    with world.repository._write() as session:
        auth = session.get(AutonomousAuthorizationRow, run['authorization']['id'])
        world.permissions.respond(session, world.project, 'revoke', {'record_id': auth.permission_record_id,
                                  'reason': 'Owner ended it in the permission controls.'}, {'user': 'owner'})
    fake.in_flight = []
    advanced = service.advance_waiting(world.root)
    assert advanced['status'] == 'FAILED' and advanced['reason'] == 'authority_inactive'
    revoked = service.revoke(world.root, run['id'], expected_version=advanced['version'], reason='Owner revokes.')
    assert revoked['status'] == 'REVOKED'


def _view(task=None, check=None, proposal=None):
    tasks = [task] if task else []
    return {'phases': [{'code': 'P001', 'item': 'item-P001', 'operational': 'ACTIVE', 'planned': True,
                        'tasks': tasks, 'proposal': proposal, 'check': check, 'questions': [], 'closure': None}],
            'in_flight': [], 'uncertain': []}


@pytest.mark.parametrize('task, action', [
    ({'code': 'P001-T001', 'family': ['P001-T001'], 'state': 'pending', 'contract': 'missing'}, 'plan_task'),
    ({'code': 'P001-T001', 'family': ['P001-T001'], 'state': 'pending', 'contract': 'refused'}, 'wait_owner'),
    ({'code': 'P001-T001', 'family': ['P001-T001'], 'state': 'accepted', 'run_id': 'r', 'contract': 'proposed'},
     'commit_task'),
    ({'code': 'P001-T001', 'family': ['P001-T001'], 'state': 'failed', 'contract': 'proposed', 'paths': ['a'],
      'failure_class': 'operational'}, 'stop'),
])
def test_task_routing_plans_contracts_commits_accepted_work_and_never_retries_operational_failures(task, action):
    assert autonomy.decide(_view(task), ['P001'])['action'] == action


def test_validated_ruling_informs_remediation_and_is_linked_but_never_adopts_alone():
    done = {'code': 'P001-T001', 'family': ['P001-T001'], 'state': 'committed'}
    blocked = {'operation_id': 'c', 'verdict': 'BLOCKED', 'classification': 'planning_ambiguity', 'unmet': [],
               'binding_sha256': None, 'stale': False}
    assert autonomy.decide(_view(done, blocked), ['P001'])['action'] == 'judge'
    ruled = autonomy.decide(_view(done, {**blocked, 'ruling_id': 'ruling-1'}), ['P001'])
    assert (ruled['action'], ruled['ruling_id'], ruled['remediation'] is not None) == ('propose_plan', 'ruling-1', True)
    proposal = {'operation_id': 'p', 'status': 'PROPOSED', 'sha256': 's', 'after_check': True}
    adopted = autonomy.decide(_view(done, {**blocked, 'ruling_id': 'ruling-1'}, proposal), ['P001'])
    assert (adopted['action'], adopted['ruling_id']) == ('adopt_plan', 'ruling-1')  # adoption still needs its child


def test_completion_requires_requirement_coverage_data_and_coverage(world):
    fake = FakeRoadmap(world.root, ['P001'])
    fake.requirements = [{'item': 'R001', 'covered': False}]
    _, run = start(world, fake)
    assert (run['status'], run['reason']) == ('FAILED', 'completion_evidence_incomplete')
    assert run['detail']['stop']['missing'] == [{'requirement': 'R001', 'reason': 'requirement_uncovered'}]
    view = {'phases': [{'code': 'P001', 'operational': 'CLOSED', 'coverage_complete': True,
                        'closure': {'criteria_evidence': True, 'successor': None}}]}
    assert autonomy.completion(view, ['P001'], ['P001'])['missing'] == [{'reason': 'requirement_coverage_unavailable'}]
