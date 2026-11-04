"""P002-T016 integral route: production effects over T014/T015, the real supervisor, journal and LangGraph runtime.

Migrated temporary SQLite, a disposable Git checkout with accepted structured knowledge (T015 fixture), scripted
reviewer/executor ports and the owner-accepted product policy (D300). No provider, network or service process.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.orchestration.roadmap import RoadmapGraphs
from my_harness.services.autonomous_effects import ManagedRoadmapEffects
from my_harness.services.autonomous_roadmap import AutonomousRoadmap
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedProject
from my_harness.services.permission_lifecycle import PermissionLifecycle
from my_harness.storage import autonomous_runs as store
from my_harness.storage.models import (AutonomousChildRow, ManagedJobRow, PhaseAuthorizationRow, PhaseRow,
                                       WorkflowOperationRow)
from my_harness.storage.operation_journal import OperationJournal
from my_harness.core.engine.autonomy import AutonomyRefusal, DEFAULT_BOUNDS, ACKNOWLEDGEMENT_VERSION
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import VERSIONS, git, review
from test_structured_phases import structured, adopt, proposal  # noqa: F401  (fixture and helpers)

DELEGATION = {'duties': [], 'duration_ceiling': {'kind': 'operation'},
              'tiers': {'active': ['files.write.task_contract'], 'delegable': ['files.write.task_contract'],
                        'owner_only': ['secrets', 'push', 'publication', 'deployment']}}
REQUEST = {'bounds': dict(DEFAULT_BOUNDS), 'caps': {}, 'delegation': DELEGATION}


def plan_response(phase, task=None, criterion='C001'):
    """A structured phase plan: an existing task, or a new task identity linked to the phase."""
    if task is None:
        return {'answer': 'Plan the accepted task.', 'questions': [], 'pending': [], 'plan': None,
                'coverage': {criterion: [f'{phase}-T001']}, 'knowledge': {'items': [], 'links': []}}
    base = proposal()
    item = {**base['knowledge']['items'][0], 'code': task}
    return {**base, 'coverage': {criterion: [task]},
            'knowledge': {'items': [item], 'links': [{'kind': 'part_of', 'source': f'task::{task}',
                                                      'target': f'phase::{phase}', 'position': 0}]}}


def task_plan(task, criterion):
    return {'task_id': task, 'allowed_paths': ['app/main.txt'], 'acceptance_criteria': [criterion],
            'validation_commands': []}


def edit(text):
    def change(context, request):
        context.path('app/main.txt').write_text(text, encoding='utf-8')
        return {'result': 'synthetic'}
    return change


def evaluation_for(world, code):
    def respond(context, request):
        pid = world.phases.by_code(str(world.context.root), code)
        criteria = world.get(pid)['definition']['exit_criteria']
        return {'phase_id': code, 'verdict': 'READY', 'summary': 'Synthetic phase evaluation.',
                'exit_criteria_results': [{'criterion': c, 'passed': True, 'evidence': 'Synthetic evidence.'}
                                          for c in criteria], 'required_actions': [], 'blocking_questions': []}
    return respond


@pytest.fixture
def journey(structured):  # noqa: F811
    w = structured
    adopt(w)  # the owner activates the first accepted phase (pending planning), as in the manual lane
    engine = w.repository.engine
    project = ManagedProject('synthetic', w.context, VERSIONS)
    permissions = PermissionLifecycle(engine)

    def build(segment_limit=50):
        effects = lambda root: ManagedRoadmapEffects(w.repository, project, w.ports.writer(w.context, VERSIONS),
                                                     permissions)
        return AutonomousRoadmap(w.repository, permissions, effects, journal=OperationJournal(engine),
                                 graphs=lambda s: RoadmapGraphs(engine, s, segment_limit=segment_limit))
    service = build()
    worker = LocalSupervisor(w.repository, w.ports, commit_factory=w.ports.writer, autonomy=service.advance_all)
    return SimpleNamespace(w=w, root=str(w.context.root), service=service, worker=worker, build=build,
                           permissions=permissions, engine=engine)


def revision_number(j):
    return j.w.knowledge.revision(j.w.project).number


def ready_and_start(j, key='start', request=REQUEST):
    first = j.service.readiness(j.root, request)
    assert first['verdict'] == 'BLOCKED' and first['blocking'] == ['gap_report_pending'], first
    again = j.service.readiness(j.root, request)  # same frozen revision: no second job, still only pending
    assert again['blocking'] == ['gap_report_pending'] and pending_jobs(j) == 1
    j.w.ports.agents.responses.appendleft({'revision': revision_number(j), 'gaps': []})  # the first invocation
    j.worker.run_once()
    shown = j.service.preview(j.root, request)
    assert shown['readiness']['verdict'] == 'READY', shown['blocking']
    assert shown['acknowledgement']['version'] == ACKNOWLEDGEMENT_VERSION
    return j.service.confirm(j.root, request, preview_sha256=shown['preview_sha256'], key=key,
                             reason='Owner starts the synthetic autonomous run.', confirmed=True,
                             acknowledgement_version=ACKNOWLEDGEMENT_VERSION)


def script_phase(j, phase, *, new_task=False, criterion_code='C001', statement='Synthetic accepted behavior.',
                 text='implemented\n'):
    task = f'{phase}-T001'
    j.w.script(plan_response(phase, task if new_task else None, criterion_code), task_plan(task, statement),
               edit(text), {**review(), 'task_id': task}, evaluation_for(j.w, phase))


def drive(j, limit=80):
    for _ in range(limit):
        status = j.service.status(j.root)
        if status['status'] != 'RUNNING':
            return status
        if j.worker.run_once() is None:
            j.service.advance_all()
            if j.service.status(j.root)['status'] == 'RUNNING' and not pending_jobs(j):
                return j.service.status(j.root)
    raise AssertionError('run did not settle')


def pending_jobs(j):
    with Session(j.engine) as session:
        return session.scalar(select(func.count()).select_from(ManagedJobRow).where(
            ManagedJobRow.status.in_(('QUEUED', 'ACTIVE'))))


def test_managed_journey_completes_two_phases_through_delegated_production_effects(journey):
    j = journey
    script_phase(j, 'P001')
    script_phase(j, 'P002', new_task=True, criterion_code='C002', statement='Successor evidence.', text='second\n')
    run = ready_and_start(j)
    assert run['status'] == 'RUNNING'
    done = drive(j)
    assert done['status'] == 'COMPLETED', (done['reason'], done['detail'])
    kinds = [c['kind'] for c in done['children']]
    per_phase = ['plan_proposal', 'plan_adoption', 'task_plan', 'task_admission', 'task_commit', 'phase_check',
                 'phase_closure']
    assert kinds == per_phase * 2
    w = j.w
    phases = {code: w.get(w.phases.by_code(j.root, code)) for code in ('P001', 'P002')}
    assert [p['status'] for p in phases.values()] == ['CLOSED', 'CLOSED']
    assert phases['P001']['successor'] == 'P002' and phases['P002']['successor'] is None
    assert git(w.context.root, 'rev-parse', 'p001') and git(w.context.root, 'status', '--porcelain') == ''
    with Session(j.engine) as session:
        closures = session.scalars(select(PhaseAuthorizationRow).where(PhaseAuthorizationRow.kind == 'close')).all()
        assert [c.scope['origin'] for c in closures] == ['owner_delegated', 'owner_delegated']
        assert all(c.actor['principal'] == 'harness' and c.scope['parent'] for c in closures)
    revisions = [w.knowledge.revision(w.project, n).origin for n in range(1, revision_number(j) + 1)]
    assert 'owner_delegated' in revisions  # the P002 task identity was adopted under the delegated child
    assert w.ports.roles().count('planning') == 5  # readiness report, two plans, two task contracts
    # Re-entry: repeated notifications and a restarted service create no further jobs or children.
    before = (pending_jobs(j), len(done['children']))
    for _ in range(3):
        j.service.advance_all()
        j.build().advance_all()
    assert (pending_jobs(j), len(j.service.status(j.root)['children'])) == before


def test_background_advancement_waits_for_jobs_and_never_continues_an_owner_stop(journey):
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    assert pending_jobs(j) == 1  # the plan proposal job; the graph holds without a process or lease
    assert j.service.advance_all() == []  # nothing to continue while the job is queued
    j.worker.run_once()  # runs the plan job; the next hook call continues the graph once
    with Session(j.engine) as session:
        children = session.scalar(select(func.count()).select_from(AutonomousChildRow))
    paused = j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'],
                             reason='Owner pauses before adoption.')
    assert paused['status'] == 'PAUSED'
    for _ in range(3):
        j.service.advance_all()
    with Session(j.engine) as session:
        assert session.scalar(select(func.count()).select_from(AutonomousChildRow)) == children
    resumed = j.service.resume(j.root, run['id'], expected_version=paused['version'])
    assert resumed['status'] == 'RUNNING' and len(resumed['children']) > children


def test_delegated_adoption_and_closure_refuse_missing_stale_revoked_or_out_of_scope_children(journey):
    from my_harness.storage.structured_phases import StructuredPhases
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    j.worker.run_once()  # plan proposal
    j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'], reason='Inspect.')
    w = j.w
    pid = w.phases.by_code(j.root, 'P001')
    op = w.get(pid)['operations'][-1]
    phases = StructuredPhases(w.repository)
    staged = phases.stage(w.context, pid, op['id'], w.get(pid)['version'], proposal_sha256=op['result']['proposal_sha256'])
    args = dict(phase_id=pid, expected_version=w.get(pid)['version'], **staged)
    shown = phases.preview(w.context, 'P001', **args)
    effects = ManagedRoadmapEffects(w.repository, ManagedProject('synthetic', w.context, VERSIONS), None, j.permissions)
    with Session(j.engine) as session:
        proposal_child = session.scalar(select(AutonomousChildRow).where(AutonomousChildRow.kind == 'plan_proposal'))
    cases = {'missing': {'id': 'no-such-child', 'rule': 'r', 'authorization_id': 'a'},
             'wrong_kind': {'id': proposal_child.id, 'rule': proposal_child.rule,
                            'authorization_id': proposal_child.authorization_id}}
    for name, child in cases.items():
        with pytest.raises(AutonomyRefusal):
            phases.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], key='forged-' + name,
                         reason='Forged delegated adoption.', confirmed=False,
                         delegated=effects.delegation(child, 'plan_adoption', phase='P001'), **args)
    with pytest.raises(Exception):  # a ruling, plan or reviewer output alone has no authority: no child at all
        phases.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], key='no-authority',
                     reason='No authority.', confirmed=False, **args)
    with pytest.raises(AutonomyRefusal) as refused:  # a child of this run for another phase is out of scope
        with Session(j.engine) as session:
            store.verify_child(session, j.permissions, proposal_child.id, kind='plan_proposal', root=j.root,
                               phase='P002')
    assert refused.value.code == 'delegated_scope'
    status = j.service.status(j.root)
    j.service.revoke(j.root, run['id'], expected_version=status['version'], reason='Owner revokes.')
    with pytest.raises(AutonomyRefusal) as refused:  # revoked: the same child no longer passes the boundary
        with Session(j.engine) as session:
            store.verify_child(session, j.permissions, proposal_child.id, kind='plan_proposal', root=j.root,
                               phase='P001')
    assert refused.value.code == 'delegated_run_inactive'
    # Manual regression: the owner-confirmed path still adopts the same exact preview.
    phases.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], key='owner', confirmed=True,
                 reason='Owner adopts manually.', **args)
    assert w.get(pid)['definition']['knowledge']['planned'] is True


def test_revocation_during_delegated_closure_prevents_the_tag_and_keeps_ready_exact(journey):
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    manual = LocalSupervisor(j.w.repository, j.w.ports, commit_factory=j.w.ports.writer)  # jobs only, no hook
    for _ in range(40):  # up to the queued delegated closure job, before any worker claims it
        with Session(j.engine) as session:
            close = session.scalar(select(PhaseAuthorizationRow).where(PhaseAuthorizationRow.kind == 'close'))
        if close is not None:
            break
        if pending_jobs(j):
            manual.run_once()
        else:
            j.service.advance_all()
    assert close is not None and close.scope['origin'] == 'owner_delegated'
    status = j.service.status(j.root)
    j.service.revoke(j.root, run['id'], expected_version=status['version'], reason='Owner revokes before the tag.')
    with pytest.raises(Exception, match='closure_authority_stale_or_invalid'):
        manual.run_once()  # the closure job observes the revoked child under the writer fence and stops
    w = j.w
    phase = w.get(w.phases.by_code(j.root, 'P001'))
    assert phase['status'] != 'CLOSED'
    assert git(w.context.root, 'tag', '--list') == ''
    with Session(j.engine) as session:  # the existing recovery path owns the stopped job; nothing is retried
        assert session.scalar(select(ManagedJobRow.status).order_by(ManagedJobRow.id.desc()).limit(1)) == 'RECOVERY_REQUIRED'
    with Session(j.engine) as session:
        row = session.scalar(select(PhaseRow).where(PhaseRow.code == 'P002'))
    assert row is None  # no successor without a completed closure


def test_stale_ready_binding_is_refused_at_the_delegated_closure_boundary(journey):
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    for _ in range(40):
        phase = j.w.get(j.w.phases.by_code(j.root, 'P001'))
        if phase['status'] == 'READY_TO_CLOSE':
            break
        if j.worker.run_once() is None:
            j.service.advance_all()
    j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'], reason='Inspect READY.')
    with Session(j.engine) as session:
        check = session.scalar(select(AutonomousChildRow).where(AutonomousChildRow.kind == 'phase_check'))
        with pytest.raises(AutonomyRefusal) as refused:
            store.verify_child(session, j.permissions, check.id, kind='phase_closure', root=j.root, phase='P001',
                               binding='0' * 64)
    assert refused.value.code == 'delegated_child_missing'  # a check child is never closure authority
    effects = ManagedRoadmapEffects(j.w.repository, ManagedProject('synthetic', j.w.context, VERSIONS),
                                    j.w.ports.writer(j.w.context, VERSIONS), j.permissions)
    with pytest.raises(AutonomyRefusal):
        with Session(j.engine) as session:
            store.verify_child(session, j.permissions, 'forged', kind='phase_closure', root=j.root, phase='P001')
    refused = effects.close_phase({'phase': 'P001', 'binding_sha256': 'f' * 64},
                                  {'id': check.id, 'rule': check.rule, 'authorization_id': check.authorization_id},
                                  'stale-close')
    assert refused['status'] == 'owner_required'  # stale READY binding: refused before any authorization row
    with Session(j.engine) as session:
        assert session.scalar(select(PhaseAuthorizationRow).where(PhaseAuthorizationRow.kind == 'close')) is None


def test_long_production_roadmap_crosses_segments(journey):
    j = journey
    j.service = j.build(segment_limit=3)
    j.worker.autonomy = j.service.advance_all
    script_phase(j, 'P001')
    script_phase(j, 'P002', new_task=True, criterion_code='C002', statement='Successor evidence.', text='second\n')
    ready_and_start(j)
    done = drive(j)
    assert done['status'] == 'COMPLETED'
    with Session(j.engine) as session:
        operations = session.scalars(select(WorkflowOperationRow.status).where(
            WorkflowOperationRow.thread_id == done['thread_id'])).all()
    assert operations and set(operations) == {'COMPLETED'}


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_versioned_review_prompts_run_through_fake_clis(journey, tmp_path, provider):
    """`roadmap-readiness` and `roadmap-task-plan` through the real CLI adapter with fake Claude/Codex processes."""
    import json
    import sys
    from dataclasses import replace
    from my_harness.adapters.cli_agents import CLIProcessAdapter
    from my_harness.adapters.git import GitWorkspace
    from my_harness.core.engine.autonomy import gap_report_schema, task_plan_schema
    from my_harness.core.engine.domain_catalogue import validate
    from my_harness.storage import autonomous_jobs as jobs
    from test_cli_agents import adapter, PROBE
    from test_knowledge_documents import IDENTITY
    j = journey
    revision = j.w.knowledge.revision(j.w.project)
    item = next(m for m in revision.members.values() if m.kind == 'requirement' or m.kind == 'criterion')
    report = {'revision': revision.number, 'gaps': [{'classification': 'advisory', 'statement': 'Synthetic note.',
                                                     'citations': [{'item': item.item_id, 'revision': revision.number}]}]}
    script = tmp_path / 'review-response.json'
    script.write_text(json.dumps({'roadmap_readiness': report,
                                  'roadmap_task_plan': task_plan('P001-T001', 'Synthetic accepted behavior.')}))
    base = next(cfg for cfg in adapter(tmp_path).agents.values() if cfg.provider == provider)
    cfg = replace(base, executable=(sys.executable, PROBE, provider, 'recipe'),
                  environment=(*base.environment, ('PROBE_SCRIPT', str(script))))
    fresh = lambda: CLIProcessAdapter({'reviewer': cfg, 'executor': cfg}, tmp_path / 'review-captures')
    versions = {**VERSIONS, **fresh().frozen_versions()}
    worker = LocalSupervisor(j.w.repository, lambda *_: (fresh(), j.w.ports.runner, GitWorkspace(IDENTITY)),
                             commit_factory=lambda *_: GitWorkspace(IDENTITY))
    stamp = {'id': revision.id, 'number': revision.number, 'sha256': revision.revision_sha256}
    items = sorted(m.item_id for m in revision.members.values() if m.kind in ('phase', 'criterion', 'requirement'))
    jobs.queue(j.w.repository, j.w.context, versions, kind='readiness', key='cli-readiness', phase_id='ROADMAP',
               payload={'revision': stamp, 'version': 'g12-1', 'item_ids': items})
    worker.run_once()
    launch = json.loads((tmp_path / 'launches.jsonl').read_text().splitlines()[-1])
    shown = json.loads(launch['prompt'].rsplit('Shape:\n', 1)[1])
    assert shown == gap_report_schema()
    assert 'Report readiness gaps for an autonomous roadmap run' in launch['prompt']
    validate(gap_report_schema(), report)
    with Session(j.engine) as session:
        sealed = store.gap_report(session, j.root, revision.id, 'g12-1')
    assert sealed.payload == {'status': 'reported', 'report': report, 'readiness_version': 'g12-1',
                              'job_id': sealed.payload['job_id']}
    phase = next(m for m in revision.members.values() if m.kind == 'phase' and m.code == 'P001')
    jobs.queue(j.w.repository, j.w.context, versions, kind='task_plan', key='cli-task-plan', phase_id='P001',
               payload={'revision': stamp, 'item_ids': [phase.item_id], 'task_id': 'P001-T001', 'phase_id': 'P001',
                        'title': 'Synthetic task', 'criteria': ['Synthetic accepted behavior.'],
                        'objective': 'A login form.', 'version_sha256': '0' * 64,
                        'inputs': {'task_id': 'P001-T001'}})
    worker.run_once()
    launch = json.loads((tmp_path / 'launches.jsonl').read_text().splitlines()[-1])
    assert json.loads(launch['prompt'].rsplit('Shape:\n', 1)[1]) == task_plan_schema()
    with Session(j.engine) as session:
        proposed = jobs.task_plan(session, j.root, 'P001-T001', '0' * 64)
    assert proposed.payload['status'] == 'proposed' and '`app/main.txt`' in proposed.payload['plan_text']


def test_judge_request_binds_the_parent_delegation_and_escalates_with_its_exact_ruling(journey):
    from my_harness.services.judge import JudgeService
    from my_harness.services.domain_operations import DomainOperations
    j = journey
    script_phase(j, 'P001')
    request = {**REQUEST, 'delegation': {**DELEGATION, 'duties': ['blocked_check']}}
    run = ready_and_start(j, request=request)
    j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'], reason='Inspect judge.')
    with Session(j.engine) as session:
        auth = store.authorization(session, run['authorization']['id'])
        parent = j.permissions.get(session, auth.project_id, auth.permission_record_id, 'authorization')
        delegation = parent.payload['delegation']
    assert delegation['duties'] == ['blocked_check'] and delegation['reconsiderations'] == DEFAULT_BOUNDS[
        'judge_reconsiderations'] and delegation['id'] == auth.id
    phase_item = j.w.get(j.w.phases.by_code(j.root, 'P001'))['definition']['knowledge']['phase_item_id']
    effects = j.service.effects(j.root)
    outcome = effects.judge({'duty': 'blocked_check', 'phase': 'P001', 'operation_id': 'check-op',
                             'phase_item': phase_item, 'parent': auth.permission_record_id, 'judge_identity': 'a' * 64,
                             'judge_input': {'classification': 'planning_ambiguity',
                                             'blocked_evidence': 'Synthetic ambiguity.', 'intent_id': 'check-op'}},
                            'judge-key')
    assert outcome['status'] == 'owner_required' and outcome['detail']['ruling_status'] == 'ESCALATED'
    judges = JudgeService(DomainOperations(j.engine, authorizations=j.permissions))
    state = judges.read(auth.project_id, outcome['detail']['judge_request_id'])
    assert state['payload']['policy'] == delegation  # bound to the parent's exact delegation contract
    assert state['ruling']['id'] == outcome['detail']['ruling_id']


@pytest.mark.parametrize('caps, reason, inferences', [({'invocations': 2}, 'cap_invocations', 2),
                                                      ({'observed_tokens': 10_000}, 'cap_usage_unknown', 1)])
def test_production_caps_count_the_ledger_of_delegated_jobs_before_each_inference(journey, caps, reason, inferences):
    j = journey
    script_phase(j, 'P001')
    ready_and_start(j, request={**REQUEST, 'caps': caps})
    done = drive(j)
    assert (done['status'], done['reason']) == ('LIMIT_REACHED', reason), done['detail']
    # the readiness report is not part of the run; the delegated inferences are counted from the ledger
    assert j.w.ports.roles().count('planning') + j.w.ports.roles().count('executor') - 1 == inferences


def _until(j, predicate, limit=40):
    """Drive jobs and graph steps separately until `predicate()` holds, without letting a hook claim further."""
    manual = LocalSupervisor(j.w.repository, j.w.ports, commit_factory=j.w.ports.writer)
    for _ in range(limit):
        if predicate():
            return manual
        if pending_jobs(j):
            manual.run_once()
        else:
            j.service.advance_all()
    raise AssertionError('condition not reached')


def _child(j, kind):
    with Session(j.engine) as session:
        row = session.scalar(select(AutonomousChildRow).where(AutonomousChildRow.kind == kind))
        return None if row is None else {'id': row.id, 'rule': row.rule, 'authorization_id': row.authorization_id,
                                         'subject': dict(row.subject), 'operation_key': row.operation_key}


def test_delegated_adoption_is_bound_to_the_exact_proposal_preview_and_revision(journey):
    from my_harness.storage.structured_phases import StructuredPhases
    j = journey
    w = j.w
    script_phase(j, 'P001')
    run = ready_and_start(j)
    manual = _until(j, lambda: _child(j, 'plan_adoption') is not None)
    original = _child(j, 'plan_adoption')
    assert {'proposal_operation_id', 'proposal_sha256', 'draft_id', 'preview_sha256', 'revision_id',
            'expected_version', 'coverage'} <= set(original['subject'])
    while pending_jobs(j):  # the task contract job the next step queued
        manual.run_once()
    j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'], reason='Inspect.')
    pid = w.phases.by_code(j.root, 'P001')
    phases = StructuredPhases(w.repository)
    w.ports.agents.responses.appendleft(proposal())  # a second valid proposal of the same phase
    phases.propose(w.context, pid, w.get(pid)['version'], key='second-proposal', versions=VERSIONS)
    manual.run_once()
    second = w.get(pid)['operations'][-1]
    assert second['status'] == 'PROPOSED'
    staged = phases.stage(w.context, pid, second['id'], w.get(pid)['version'],
                          proposal_sha256=second['result']['proposal_sha256'])
    args = dict(phase_id=pid, expected_version=w.get(pid)['version'], **staged)
    shown = phases.preview(w.context, 'P001', **args)
    before = (w.knowledge.revision(w.project).id, w.get(pid)['definition_sha256'], w.get(pid)['ready'])
    effects = j.service.effects(j.root)
    with pytest.raises(AutonomyRefusal) as refused:  # the real child names another proposal and preview
        phases.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], key='other-proposal',
                     reason='Reuse of a sealed child.', confirmed=False,
                     delegated=effects.delegation(original, 'plan_adoption', phase='P001'), **args)
    assert refused.value.code == 'delegated_adoption_mismatch'
    assert (w.knowledge.revision(w.project).id, w.get(pid)['definition_sha256'], w.get(pid)['ready']) == before
    # Idempotent re-entry of the original sealed adoption: same key, no new effect.
    replay = effects.adopt_plan({'phase': 'P001'}, original, original['operation_key'])
    assert replay['status'] == 'done'
    assert (w.knowledge.revision(w.project).id, w.get(pid)['definition_sha256'], w.get(pid)['ready']) == before


def with_tokens(engine, response, total):
    """Synthetic observed usage: the invocation records a capture with known components before it returns."""
    from uuid import uuid4
    from my_harness.storage.models import UsageCaptureRow
    from my_harness.storage.accounting import key

    def respond(context, request):
        evidence = {'components': [{'semantics': 'claude-cli-1', 'input_tokens': total - 100, 'cache_read_tokens': 0,
                                    'cache_write_tokens': 0, 'write_5m': 0, 'write_1h': 0, 'output_tokens': 100,
                                    'reasoning_tokens': 0}], 'coverage': 'complete'}
        with Session(engine) as session, session.begin():
            session.add(UsageCaptureRow(invocation_id=key('managed_attempt', request.id), version='synthetic-test-1',
                                        digest=uuid4().hex * 2, document={'synthetic': True}, evidence=evidence,
                                        evidence_digest=uuid4().hex * 2, source='capture', recorded_at='2026-11-04T00:00:00+00:00'))
        return response(context, request) if callable(response) else response
    return respond


def test_invocation_cap_is_enforced_inside_a_job_that_needs_more_than_one_inference(journey):
    j = journey
    script_phase(j, 'P001')
    # plan proposal and task contract consume two; the task job's executor takes the last one; its reviewer
    # inference is refused at the fenced admission, without launching a process.
    ready_and_start(j, request={**REQUEST, 'caps': {'invocations': 3}})
    done = drive(j)
    assert (done['status'], done['reason']) == ('LIMIT_REACHED', 'cap_invocations'), done['detail']
    roles = j.w.ports.roles()
    assert roles.count('executor') == 1 and 'reviewer' not in roles
    with Session(j.engine) as session:
        from my_harness.storage.models import ManagedEventRow
        refused = session.scalars(select(ManagedEventRow).where(ManagedEventRow.kind == 'autonomy_admission_refused')).all()
    assert len(refused) == 1 and refused[0].payload['stop']['reason'] == 'cap_invocations'
    assert done['detail']['stop']['failure_class'] == 'cap'


@pytest.mark.parametrize('known', [True, False])
def test_token_cap_reads_known_observed_usage_and_stops_on_unknown(journey, known):
    j = journey
    task = 'P001-T001'
    responses = [plan_response('P001'), task_plan(task, 'Synthetic accepted behavior.'), edit('implemented\n'),
                 {**review(), 'task_id': task}, evaluation_for(j.w, 'P001')]
    j.w.script(*[with_tokens(j.engine, r, 400) if known else r for r in responses])
    j.w.script(plan_response('P002', 'P002-T001', 'C002'))
    ready_and_start(j, request={**REQUEST, 'caps': {'observed_tokens': 2000}})
    done = drive(j)
    if known:  # 5 × 400 observed: P001 closes; the P002 plan admission meets the threshold
        assert (done['status'], done['reason']) == ('LIMIT_REACHED', 'cap_observed_tokens'), done['detail']
        assert j.w.get(j.w.phases.by_code(j.root, 'P001'))['status'] == 'CLOSED'
    else:  # the first delegated inference leaves usage unknown: the next admission stops before it starts
        assert (done['status'], done['reason']) == ('LIMIT_REACHED', 'cap_usage_unknown'), done['detail']
        assert j.w.get(j.w.phases.by_code(j.root, 'P001'))['status'] != 'CLOSED'


def test_prior_manual_acceptance_is_never_committed_by_delegation(journey):
    from test_managed_api import PLAN
    j = journey
    w = j.w
    # The owner's own earlier run of the same task code reached ACCEPTANCE_READY (manual lane, not committed); it
    # rewrote identical bytes, so the checkout stays clean and readiness can pass.
    w.script(edit('baseline\n'), {**review(), 'task_id': 'P001-T001'})
    pid = w.phases.by_code(j.root, 'P001')
    from test_structured_phases import adopt as owner_adopt
    owner_adopt(w, phase_id=pid, expected_version=w.get(pid)['version'], coverage={'C001': ['P001-T001']})
    manual = w.repository.submit(w.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='manual-run')
    w.run()
    assert w.repository.get_run(manual.run_id).status == 'ACCEPTANCE_READY'
    run = ready_and_start(j)
    done = drive(j)
    assert (done['status'], done['reason']) == ('WAITING_FOR_OWNER', 'owner_foreign_task_acceptance'), done['reason']
    assert w.repository.get_run(manual.run_id).status == 'ACCEPTANCE_READY'  # untouched, not committed
    assert not any(c['kind'] == 'task_commit' for c in done['children'])
    assert run['id'] == done['id']


def test_operational_port_failure_stops_without_a_second_admission(journey):
    j = journey
    w = j.w
    w.script(plan_response('P001'), task_plan('P001-T001', 'Synthetic accepted behavior.'),
             RuntimeError('synthetic executor port failure'))
    ready_and_start(j)
    done = drive(j)
    assert (done['status'], done['reason']) == ('FAILED', 'operational_failure'), done['reason']
    admissions = [c for c in done['children'] if c['kind'] == 'task_admission']
    for _ in range(3):
        j.service.advance_all()
    assert len(admissions) == 1 and len(j.service.status(j.root)['children']) == len(done['children'])
    assert j.w.ports.roles().count('executor') == 1


@pytest.mark.parametrize('change, reason', [
    ({'acceptance_criteria': ['It is false that Synthetic accepted behavior.']}, 'task_plan_weakens_criteria'),
    ({'acceptance_criteria': ['Synthetic accepted behavior.', 'Synthetic accepted behavior. is optional']},
     'task_plan_rewords_criteria'),
    ({'acceptance_criteria': ['Synthetic accepted behavior.', 'Extra\n**Allowed paths:** `docs/STATE.md`']},
     'task_plan_unsafe_text'),
    ({'allowed_paths': ['app']}, 'task_plan_paths_invalid'),
    ({'allowed_paths': ['AGENTS.md']}, 'task_plan_paths_invalid'),
    ({'allowed_paths': ['docs/STATE.md']}, 'task_plan_paths_invalid'),
    ({'allowed_paths': ['./app/main.txt']}, 'task_plan_paths_invalid'),
    ({'validation_commands': ['rm -rf app']}, 'task_plan_command_outside_profile'),
])
def test_delegated_task_contract_rejects_weakened_criteria_protected_paths_and_foreign_commands(journey, change,
                                                                                                reason):
    from my_harness.services.autonomous_review import task_contract
    j = journey
    request = {'task_id': 'P001-T001', 'phase_id': 'P001', 'title': 'Login form', 'objective': 'A login form.',
               'criteria': ['Synthetic accepted behavior.']}
    accepted = task_contract(j.w.context, request, task_plan('P001-T001', 'Synthetic accepted behavior.'))
    assert accepted['status'] == 'PROPOSED' and accepted['result']['objective'] == 'A login form.'
    refused = task_contract(j.w.context, request, {**task_plan('P001-T001', 'Synthetic accepted behavior.'), **change})
    assert (refused['status'], refused['reason']) == ('REFUSED', reason)


def test_delegated_task_contract_is_refused_when_the_parser_disagrees(journey, monkeypatch):
    import json
    from my_harness.core.engine import planning
    from my_harness.services.autonomous_review import task_contract
    j = journey
    original = planning.deterministic_task

    def widened(context, task_id, phase_id, text):  # a parser result that differs from the proposal
        data = json.loads(original(context, task_id, phase_id, text))
        return json.dumps({**data, 'allowed_paths': [*data['allowed_paths'], 'app/other.txt']})
    monkeypatch.setattr(planning, 'deterministic_task', widened)
    request = {'task_id': 'P001-T001', 'phase_id': 'P001', 'title': 'Login form', 'objective': 'A login form.',
               'criteria': ['Synthetic accepted behavior.']}
    refused = task_contract(j.w.context, request, task_plan('P001-T001', 'Synthetic accepted behavior.'))
    assert (refused['status'], refused['reason']) == ('REFUSED', 'task_plan_parser_mismatch')


def test_all_phases_closed_without_requirement_coverage_is_not_completed(journey):
    from test_knowledge import OWNER, requirement
    j = journey
    w = j.w
    revision = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, revision.id)
    w.knowledge.put(draft, 'requirement', 'R001', requirement('Nothing in the roadmap evidences this.'))
    covered = w.knowledge.put(draft, 'requirement', 'R002', requirement('The successor phase evidences this.'))
    w.knowledge.link(draft, 'addresses', revision.item('phase', 'P002').item_id, covered)
    w.knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    script_phase(j, 'P001')
    script_phase(j, 'P002', new_task=True, criterion_code='C002', statement='Successor evidence.', text='second\n')
    ready_and_start(j)
    done = drive(j)
    phases = [w.get(w.phases.by_code(j.root, code))['status'] for code in ('P001', 'P002')]
    assert phases == ['CLOSED', 'CLOSED'] and done['status'] == 'FAILED', (phases, done['status'], done['reason'])
    assert done['reason'] == 'completion_evidence_incomplete'
    missing = done['detail']['stop']['missing']
    uncovered = w.knowledge.revision(w.project).item('requirement', 'R001').item_id
    assert missing == [{'requirement': uncovered, 'reason': 'requirement_uncovered'}]  # R002 is covered


def _attempts(j, run_id):
    from my_harness.storage.models import ManagedAttemptRow
    with Session(j.engine) as session:
        return session.scalar(select(func.count()).select_from(ManagedAttemptRow).where(
            ManagedAttemptRow.run_id == run_id))


def _job_run(j, child):
    with Session(j.engine) as session:
        return session.scalar(select(ManagedJobRow.run_id).where(ManagedJobRow.idempotency_key == child['operation_key']))


def _end_parent_from_panel(j, run):
    from test_knowledge import OWNER
    with Session(j.engine) as session, session.begin():
        auth = store.authorization(session, run['authorization']['id'])
        j.permissions.respond(session, auth.project_id, 'revoke', {'record_id': auth.permission_record_id,
                                                                    'reason': 'Owner ends it in the panel.'}, OWNER)


@pytest.mark.parametrize('kind', ['plan_proposal', 'phase_check'])
def test_queued_delegated_job_does_not_infer_after_the_parent_is_ended(journey, kind):
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    manual = _until(j, lambda: _child(j, kind) is not None and pending_jobs(j) > 0)
    requests = len(j.w.ports.agents.requests)
    _end_parent_from_panel(j, run)
    manual.run_once()  # the queued job reaches its attempt start after the parent ended
    managed = _job_run(j, _child(j, kind))
    assert len(j.w.ports.agents.requests) == requests and _attempts(j, managed) == 0  # the port is never invoked
    with Session(j.engine) as session:
        refusal = store.admission_refusal(session, managed)
    assert refusal['kind'] == 'authority' and refusal['reason'] == 'delegated_authority_revoked'
    j.service.advance_all()
    status = j.service.status(j.root)
    assert status['status'] == 'FAILED' and status['reason'] in ('authority_inactive', 'delegated_authority_refused')
    assert status['reason'] != 'LIMIT_REACHED'


def test_pause_holds_the_next_inference_of_a_queued_job_and_resume_continues(journey):
    j = journey
    script_phase(j, 'P001')
    script_phase(j, 'P002', new_task=True, criterion_code='C002', statement='Successor evidence.', text='second\n')
    run = ready_and_start(j)
    manual = LocalSupervisor(j.w.repository, j.w.ports, commit_factory=j.w.ports.writer)
    requests = len(j.w.ports.agents.requests)
    paused = j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'],
                             reason='Owner pauses with the plan job queued.')
    manual.run_once()
    managed = _job_run(j, _child(j, 'plan_proposal'))
    assert len(j.w.ports.agents.requests) == requests and _attempts(j, managed) == 0
    with Session(j.engine) as session:
        assert store.admission_refusal(session, managed)['kind'] == 'state'
    resumed = j.service.resume(j.root, run['id'], expected_version=j.service.status(j.root)['version'])
    assert resumed['status'] == 'RUNNING' and paused['status'] == 'PAUSED'
    assert drive(j)['status'] == 'COMPLETED'


def test_task_contract_port_failure_is_a_durable_stop_without_a_second_reviewer(journey):
    j = journey
    j.w.script(plan_response('P001'), RuntimeError('synthetic reviewer port failure'))
    ready_and_start(j)
    done = drive(j)
    assert (done['status'], done['reason']) == ('FAILED', 'task_contract_failed'), done['reason']
    plans = [c for c in done['children'] if c['kind'] == 'task_plan']
    requests, jobs = len(j.w.ports.agents.requests), pending_jobs(j)
    for _ in range(3):
        j.worker.run_once()
        j.service.advance_all()
    after = j.service.status(j.root)
    assert len(plans) == 1 and len([c for c in after['children'] if c['kind'] == 'task_plan']) == 1
    assert (len(j.w.ports.agents.requests), pending_jobs(j), after['status']) == (requests, jobs, 'FAILED')


def _amend_criterion(j, statement):
    from test_knowledge import OWNER, criterion
    w = j.w
    revision = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, revision.id)
    w.knowledge.put(draft, 'criterion', 'C001', criterion(statement))
    w.knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)


def test_changed_criterion_never_reuses_the_previous_contract(journey):
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    manual = _until(j, lambda: _child(j, 'task_plan') is not None)
    while pending_jobs(j):
        manual.run_once()  # the contract for the original criterion is sealed
    effects = j.service.effects(j.root)
    [before] = [t for p in effects.observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    assert before['contract'] == 'proposed'
    j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'], reason='Owner edits.')
    _amend_criterion(j, 'Changed accepted behavior.')  # only the criterion changes, not the task item
    [after] = [t for p in effects.observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    assert after['version_sha256'] != before['version_sha256'] and after['contract'] == 'missing'
    assert after['criteria'] == ['Changed accepted behavior.']
    stale = {'id': 'c', 'rule': 'r', 'authorization_id': 'a', 'permission_record_id': 'p',
             'subject': {'version_sha256': before['version_sha256'], 'contract_sha256': before['contract_sha256']}}
    refused = effects.admit_task({'task': 'P001-T001', 'phase': 'P001', 'plan_text': before['plan_text'],
                                  'contract_sha256': before['contract_sha256']}, stale, 'stale-admission')
    assert refused == {'status': 'owner_required', 'detail': {'refusal': 'task_contract_mismatch'}}


def test_changed_criterion_never_commits_the_previous_delegated_acceptance(journey):
    j = journey
    script_phase(j, 'P001')
    run = ready_and_start(j)
    _until(j, lambda: _admission_run(j) is not None and j.w.repository.get_run(_admission_run(j)).status ==
           'ACCEPTANCE_READY')
    j.service.pause(j.root, run['id'], expected_version=j.service.status(j.root)['version'], reason='Owner edits.')
    effects = j.service.effects(j.root)
    [own] = [t for p in effects.observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    assert own['state'] == 'accepted'
    _amend_criterion(j, 'Changed accepted behavior.')
    [after] = [t for p in effects.observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    assert after['state'] == 'foreign_acceptance' and after['run_id'] == own['run_id']
    refused = effects.commit_task({'phase': 'P001', 'task': 'P001-T001', 'run_id': own['run_id'],
                                   'version_sha256': own['version_sha256']}, {}, 'stale-commit')
    assert refused == {'status': 'owner_required', 'detail': {'refusal': 'acceptance_not_delegated'}}
    assert j.w.repository.get_run(own['run_id']).status == 'ACCEPTANCE_READY'


def _admission_run(j):
    child = _child(j, 'task_admission')
    return _job_run(j, child) if child else None


# --- review blockers (2026-11-04, third pass): held review and T014 transaction boundary ---------------------------

def _pause_inside_executor(j, text='paused executor changes\n'):
    """Executor port that writes inside its contract and has the owner pause before it returns control."""
    def change(context, request):
        result = edit(text)(context, request)
        run = j.service.status(j.root)
        j.service.pause(j.root, run['id'], expected_version=run['version'], reason='Owner pauses mid-executor.')
        return result
    return change


def _task_attempts(j, task):
    from my_harness.storage.models import AutonomousConsumptionRow
    with Session(j.engine) as session:
        return session.scalar(select(func.count()).select_from(AutonomousConsumptionRow).where(
            AutonomousConsumptionRow.bound == 'task_attempts', AutonomousConsumptionRow.identity == task))


def _jobs_of(j, run_id):
    with Session(j.engine) as session:
        return list(session.scalars(select(ManagedJobRow.id).where(ManagedJobRow.run_id == run_id)
                                    .order_by(ManagedJobRow.id)))


def _held_journey(j):
    j.w.script(plan_response('P001'), task_plan('P001-T001', 'Synthetic accepted behavior.'), _pause_inside_executor(j),
               {**review(), 'task_id': 'P001-T001'}, evaluation_for(j.w, 'P001'))
    script_phase(j, 'P002', new_task=True, criterion_code='C002', statement='Successor evidence.', text='second\n')
    run = ready_and_start(j)
    paused = drive(j)
    assert paused['status'] == 'PAUSED', (paused['status'], paused['reason'])
    managed = _admission_run(j)
    assert j.w.repository.get_run(managed).status == 'STOPPED'
    return run, managed


def test_pause_between_executor_and_reviewer_resumes_review_in_the_same_t014_run(journey):
    from my_harness.storage.models import ManagedEventRow
    j = journey
    run, managed = _held_journey(j)
    with Session(j.engine) as session:
        refusal = session.scalar(select(ManagedEventRow.payload).where(
            ManagedEventRow.run_id == managed, ManagedEventRow.kind == 'autonomy_admission_refused'))
    assert refusal['role'] == 'reviewer' and refusal['stop']['kind'] == 'state'
    assert j.w.ports.roles().count('executor') == 1 and 'reviewer' not in j.w.ports.roles()
    assert git(j.root, 'status', '--porcelain') == 'M app/main.txt'  # the executor's work is kept, uncommitted
    [task] = [t for p in j.service.effects(j.root).observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    assert task['state'] == 'held_review' and task['run_id'] == managed
    attempts, jobs, requests = _task_attempts(j, 'P001-T001'), _jobs_of(j, managed), len(j.w.ports.agents.requests)
    # The reviewer waits for the explicit resume: supervisor ticks and graph notifications do nothing while paused.
    for _ in range(3):
        j.worker.run_once()
        j.service.advance_all()
    assert (j.service.status(j.root)['status'], _jobs_of(j, managed)) == ('PAUSED', jobs)
    assert len(j.w.ports.agents.requests) == requests
    paused = j.service.status(j.root)
    resumed = j.service.resume(j.root, run['id'], expected_version=paused['version'])
    assert resumed['status'] == 'RUNNING'
    with pytest.raises(AutonomyRefusal) as again:  # a repeated resume is refused by version, never a second continuation
        j.service.resume(j.root, run['id'], expected_version=paused['version'])
    assert again.value.code in ('run_version_stale', 'run_not_resumable')
    for _ in range(3):
        j.service.advance_all()
        j.build().advance_all()
    continuation = _jobs_of(j, managed)
    assert len(continuation) == len(jobs) + 1 and pending_jobs(j) == 1  # exactly one continuation of the same run
    with Session(j.engine) as session:
        request = session.get(ManagedJobRow, continuation[-1]).request_json
    assert '"action":"revalidate"' in request.replace(' ', '')  # T014 revalidation, never retry_executor
    assert __import__('json').loads(request)['expected_evidence'] == task['held']['evidence']  # bound to the work
    done = drive(j)
    assert done['status'] == 'COMPLETED', (done['reason'], done['detail'])
    roles = [r.role for r in j.w.ports.agents.requests]
    assert roles.count('executor') == 2  # P001 once (kept) and P002 once; P001's executor was never reinvoked
    reviews = [r for r in j.w.ports.agents.requests if r.role == 'reviewer']
    assert 'app/main.txt' in reviews[0].prompt and 'paused executor changes' in reviews[0].prompt
    assert _task_attempts(j, 'P001-T001') == attempts == 1
    assert len([c for c in done['children'] if c['kind'] == 'task_admission']) == 2  # one per phase, no readmission
    commit = j.w.repository.commit_record(managed)  # the reviewed work of the same run is what was committed
    assert commit.status == 'COMMITTED'
    assert git(j.root, 'show', f'{commit.intent.expected_commit}:app/main.txt') == 'paused executor changes'


@pytest.mark.parametrize('foreign', ['new_file', 'same_path'])
def test_foreign_change_after_a_held_review_refuses_the_resume(journey, foreign):
    j = journey
    run, managed = _held_journey(j)
    path = j.w.context.path('app/other.txt' if foreign == 'new_file' else 'app/main.txt')
    original = path.read_text(encoding='utf-8') if path.exists() else None
    path.write_text('foreign change\n', encoding='utf-8')
    paused = j.service.status(j.root)
    with pytest.raises(AutonomyRefusal) as refused:
        j.service.resume(j.root, run['id'], expected_version=paused['version'])
    assert refused.value.code == 'resume_revalidation_failed'
    assert {'git_baseline_clean', 'held_review_checkout_mismatch'} <= set(refused.value.detail['reasons'])
    assert j.service.status(j.root)['status'] == 'PAUSED' and pending_jobs(j) == 0
    assert 'reviewer' not in j.w.ports.roles() and j.w.ports.roles().count('executor') == 1
    # Removing the foreign change restores exactly the executor's evidence; only then can the review continue.
    if original is None:
        path.unlink()
    else:
        path.write_text(original, encoding='utf-8')
    assert j.service.resume(j.root, run['id'], expected_version=paused['version'])['status'] == 'RUNNING'
    assert len(_jobs_of(j, managed)) == 2


def test_t014_queue_transaction_refuses_a_contract_made_stale_by_a_concurrent_adoption(journey, monkeypatch):
    from my_harness.storage.models import ManagedRunRow
    j = journey
    j.w.script(plan_response('P001'), task_plan('P001-T001', 'Synthetic accepted behavior.'))
    ready_and_start(j)
    manual = _until(j, lambda: _child(j, 'task_plan') is not None)
    while pending_jobs(j):
        manual.run_once()  # the contract for the original C001 is sealed
    effects = j.service.effects(j.root)
    [before] = [t for p in effects.observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    pid = j.w.phases.by_code(j.root, 'P001')
    phase_version = j.w.get(pid)['version']
    original, interleaved = j.w.repository.submit, []

    def owner_adopts_first(*args, **kwargs):  # deterministic interleaving: just before T014's transaction
        _amend_criterion(j, 'Changed accepted behavior.')  # only C001 changes
        adopt(j.w, phase_id=pid, expected_version=j.w.get(pid)['version'], coverage={'C001': ['P001-T001']})
        interleaved.append(kwargs['key'])
        return original(*args, **kwargs)

    monkeypatch.setattr(j.w.repository, 'submit', owner_adopts_first)
    j.service.advance_all()
    assert len(interleaved) == 1
    [after] = [t for p in effects.observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    assert after['version_sha256'] != before['version_sha256'] and after['criteria'] == ['Changed accepted behavior.']
    phase = j.w.get(pid)
    assert phase['version'] > phase_version and phase['definition']['knowledge']['planned']  # updated plan adopted
    assert pending_jobs(j) == 0
    with Session(j.engine) as session:
        assert session.scalar(select(func.count()).select_from(ManagedRunRow).where(
            ManagedRunRow.task_id == 'P001-T001', ManagedRunRow.purpose == 'task')) == 0
        assert session.scalar(select(ManagedJobRow.id).where(ManagedJobRow.idempotency_key == interleaved[0])) is None
        operation = session.scalar(select(WorkflowOperationRow).where(WorkflowOperationRow.key == interleaved[0]))
    status = j.service.status(j.root)
    assert status['status'] == 'WAITING_FOR_OWNER', (status['status'], status['reason'])
    assert status['detail']['stop']['refusal'] == 'task_contract_stale'  # durable evidence of the refusal
    assert operation is not None and operation.status == 'COMPLETED'
    assert _child(j, 'task_admission')['subject']['version_sha256'] == before['version_sha256']


def test_t014_commit_queue_refuses_a_delegated_acceptance_made_stale_concurrently(journey, monkeypatch):
    j = journey
    script_phase(j, 'P001')
    ready_and_start(j)
    _until(j, lambda: _admission_run(j) is not None and j.w.repository.get_run(_admission_run(j)).status ==
           'ACCEPTANCE_READY')
    managed = _admission_run(j)
    original, interleaved = j.w.repository.submit_commit, []

    def owner_amends_first(*args, **kwargs):
        _amend_criterion(j, 'Changed accepted behavior.')
        interleaved.append(kwargs['key'])
        return original(*args, **kwargs)

    monkeypatch.setattr(j.w.repository, 'submit_commit', owner_amends_first)
    j.service.advance_all()
    assert len(interleaved) == 1 and pending_jobs(j) == 0
    assert j.w.repository.commit_record(managed) is None and j.w.repository.get_run(managed).status == 'ACCEPTANCE_READY'
    with Session(j.engine) as session:
        assert session.scalar(select(ManagedJobRow.id).where(ManagedJobRow.idempotency_key == interleaved[0])) is None
    status = j.service.status(j.root)
    assert status['status'] == 'WAITING_FOR_OWNER', (status['status'], status['reason'])
    assert status['detail']['stop']['refusal'] == 'acceptance_identity_stale'
    assert any(c['kind'] == 'task_commit' for c in status['children'])  # sealed child, but no commit effect


def test_replayed_delegated_requests_return_their_recorded_jobs_without_a_second_effect(journey):
    import json
    j = journey
    script_phase(j, 'P001')
    ready_and_start(j)
    manual = _until(j, lambda: _admission_run(j) is not None)
    admission = _child(j, 'task_admission')
    with Session(j.engine) as session:
        job = session.scalar(select(ManagedJobRow).where(ManagedJobRow.idempotency_key == admission['operation_key']))
        job_id, request = job.id, json.loads(job.request_json)

    def never(*_):
        raise AssertionError('a recorded request must replay before any new check or effect')

    replay = j.w.repository.submit(j.w.context, request['task_id'], request['phase_id'], request['text'], VERSIONS,
                                   key=admission['operation_key'],
                                   delegated_authorization=request['delegated_authorization'], delegated=never)
    assert replay.id == job_id and len(_jobs_of(j, job.run_id)) == 1
    _until(j, lambda: _child(j, 'task_commit') is not None and pending_jobs(j) > 0)
    commit = _child(j, 'task_commit')
    with Session(j.engine) as session:
        queued = session.scalar(select(ManagedJobRow).where(ManagedJobRow.idempotency_key == commit['operation_key']))
        commit_job, version = queued.id, json.loads(queued.request_json)['expected_version']
    again = j.w.repository.submit_commit(job.run_id, key=commit['operation_key'], expected_version=version,
                                         delegated=never)
    assert again.id == commit_job and len(_jobs_of(j, job.run_id)) == 2
    while pending_jobs(j):
        manual.run_once()
    assert j.w.repository.commit_record(job.run_id).status == 'COMMITTED'


def test_foreign_edit_between_continuation_queue_and_execution_is_never_reviewed_or_committed(journey):
    import json
    from my_harness.storage.models import ManagedRunRow
    j = journey
    run, managed = _held_journey(j)
    [task] = [t for p in j.service.effects(j.root).observe()['phases'] for t in p['tasks'] if t['code'] == 'P001-T001']
    resumed = j.service.resume(j.root, run['id'], expected_version=j.service.status(j.root)['version'])
    assert resumed['status'] == 'RUNNING' and pending_jobs(j) == 1
    with Session(j.engine) as session:
        queued = session.get(ManagedJobRow, _jobs_of(j, managed)[-1])
        assert json.loads(queued.request_json)['expected_evidence'] == task['held']['evidence']
    # After the continuation was verified and queued, a foreign edit lands on a path the contract allows.
    j.w.context.path('app/main.txt').write_text('foreign edit after resume\n', encoding='utf-8')
    restarted = LocalSupervisor(j.w.repository, j.w.ports, commit_factory=j.w.ports.writer)  # binding read from SQLite
    assert restarted.run_once().id == queued.id
    with Session(j.engine) as session:
        stage = session.get(ManagedRunRow, managed).stage
    assert j.w.repository.get_run(managed).status == 'STOPPED' and stage == 'continuation'
    done = drive(j)
    assert (done['status'], done['reason']) == ('FAILED', 'held_review_evidence_changed'), done['reason']
    assert 'reviewer' not in j.w.ports.roles() and j.w.ports.roles().count('executor') == 1
    assert j.w.repository.commit_record(managed) is None
    assert j.w.context.path('app/main.txt').read_text(encoding='utf-8') == 'foreign edit after resume\n'
    assert git(j.root, 'status', '--porcelain') == 'M app/main.txt'  # left for the owner, nothing reverted
    children, jobs = len(done['children']), _jobs_of(j, managed)
    for _ in range(3):  # no automatic readmission, review or commit
        j.worker.run_once()
        j.service.advance_all()
    after = j.service.status(j.root)
    assert (after['status'], len(after['children']), _jobs_of(j, managed), pending_jobs(j)) == (
        'FAILED', children, jobs, 0)
    assert _task_attempts(j, 'P001-T001') == 1 and j.w.ports.roles().count('executor') == 1
