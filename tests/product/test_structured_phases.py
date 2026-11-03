"""T015: temporary Git/SQLite, HTTP owner actions and synthetic reviewer/executor ports."""
from dataclasses import replace
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.phases import digest
from my_harness.storage.knowledge import KnowledgeRepository
from my_harness.storage.structured_phases import StructuredPhases
from my_harness.storage.phases import PhaseRepository
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.models import PhaseRow, PhaseAuthorizationRow
from my_harness.services.managed import LocalSupervisor
from my_harness.core.engine.journal import JournalError
from my_harness.adapters.git import GitWorkspace
from test_managed import repository  # noqa: F401
from test_managed_api import VERSIONS, PLAN, git, make_context, client, config, edit, review, settle
from test_knowledge import phase, task, criterion, section, OWNER
from test_knowledge_documents import prepare_export, KnowledgeDelivery, IDENTITY
from test_phases import World


@pytest.fixture
def structured(repository, tmp_path):
    root = tmp_path / 'structured-phase'
    (root / 'app').mkdir(parents=True)
    (root / 'app/main.txt').write_text('baseline\n')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A'); git(root, 'commit', '-qm', 'Synthetic baseline')
    knowledge = KnowledgeRepository(repository.engine)
    project = knowledge.project(str(root))
    from my_harness.storage.work_language import associate
    with Session(repository.engine) as session, session.begin():
        associate(session, root=str(root), project_id=project, work_language='en', source='migration',
                  confirmation={'synthetic': True}, now=repository._now())
    draft = knowledge.open_draft(project, None)
    p = knowledge.put(draft, 'phase', 'P001', {**phase(), 'tag': 'p001'})
    t = knowledge.put(draft, 'task', 'P001-T001', task())
    c = knowledge.put(draft, 'criterion', 'C001', criterion('Synthetic accepted behavior.'))
    knowledge.put(draft, 'section', 'rules', section('Rules', 'Use accepted knowledge.'),
                  document='instructions', root_position=0)
    knowledge.link(draft, 'part_of', t, p, position=0)
    knowledge.link(draft, 'criterion_of', c, p, position=0)
    p2 = knowledge.put(draft, 'phase', 'P002', phase('Successor objective.'))
    c2 = knowledge.put(draft, 'criterion', 'C002', criterion('Successor evidence.'))
    knowledge.link(draft, 'criterion_of', c2, p2, position=0)
    knowledge.adopt(draft, None, origin='owner_confirmed', actor=OWNER)
    export = prepare_export(repository.engine, root, project)
    KnowledgeDelivery(repository.engine, root, project).execute(export['record_id'], export['preview_sha256'], IDENTITY)
    context = replace(make_context(root), documents='v2')
    world = World(repository, context)
    world.knowledge, world.project = knowledge, project
    world.structured = StructuredPhases(repository)
    return world


def adopt(world, **args):
    shown = world.structured.preview(world.context, 'P001', **args)
    return world.structured.adopt(world.context, 'P001', preview_sha256=shown['preview_sha256'],
        key=world.key(), reason='Owner confirms exact phase contract.', confirmed=True, **args)


def planned(world):
    pid = adopt(world)
    adopt(world, phase_id=pid, expected_version=world.get(pid)['version'], coverage={'C001': ['P001-T001']})
    return pid


def evaluation(world, pid, verdict='READY', evidence='Synthetic code and committed task prove the criterion.'):
    return {'phase_id': 'P001', 'verdict': verdict, 'summary': 'Synthetic phase evaluation.',
        'exit_criteria_results': [{'criterion': c, 'passed': verdict == 'READY', 'evidence': evidence}
                                 for c in world.get(pid)['definition']['exit_criteria']],
        'required_actions': ['Add missing behavior.'] if verdict == 'REVISE' else [],
        'blocking_questions': ['Clarify implementation intent.'] if verdict == 'BLOCKED' else []}


def prepared(world):
    pid = planned(world)
    world.accept_task()
    world.check(pid, evaluation(world, pid))
    assert world.get(pid)['status'] == 'READY_TO_CLOSE', world.get(pid)['operations'][-1]
    return pid


def queue_close(world, pid):
    detail = world.get(pid)
    return world.phases.submit_close(world.context, pid, detail['version'], key=world.key(), versions=VERSIONS,
        binding_sha256=(detail['ready'] or {}).get('binding_sha256', '0' * 64), reason='Owner confirms exact READY.', ttl_seconds=3600,
        git=world.ports.writer(world.context, VERSIONS))


def test_complete_structured_closure_uses_accepted_roadmap_and_preserves_bytes(structured):
    w = structured
    artifacts = w.context.path('docs/phase/nested'); artifacts.mkdir(parents=True)
    raw = bytes(range(256)) * 4096; (artifacts / 'image.bin').write_bytes(raw)
    git(w.context.root, 'add', '-A'); git(w.context.root, 'commit', '-qm', 'Synthetic artifacts')
    pid = prepared(w)
    before = git(w.context.root, 'rev-parse', 'HEAD')
    job = queue_close(w, pid); w.run()
    detail = w.get(pid)
    assert detail['status'] == 'CLOSED', detail['operations'][-1]
    assert detail['successor'] == 'P002'
    assert w.repository.get_run(job.run_id).status == 'COMMITTED'
    assert git(w.context.root, 'rev-parse', 'p001') == before
    assert git(w.context.root, 'rev-list', '--count', before + '..HEAD') == '1'
    assert w.context.path('docs/archive/phase-001/artifacts/nested/image.bin').read_bytes() == raw
    sealed = json.loads(w.context.path('docs/archive/phase-001/knowledge.json').read_text())
    assert sealed['revision']['id'] == w.knowledge.revision(w.project).id
    assert w.context.path('docs/archive/phase-001/evidence.json').exists()
    from my_harness.storage.knowledge_exchange import completed_for_project
    with Session(w.repository.engine) as session:
        delivered = completed_for_project(session, w.project)
        assert delivered and delivered['result']['commit'] == git(w.context.root, 'rev-parse', 'HEAD')
    assert git(w.context.root, 'status', '--porcelain') == ''
    next_id = w.phases.by_code(str(w.context.root), 'P002')
    successor = w.get(next_id)
    assert successor['status'] == 'ACTIVE' and successor['definition']['tasks'] == []
    assert successor['definition']['knowledge']['planned'] is False
    assert 'Planning pending.' in w.context.path('docs/STATE.md').read_text()


def test_structured_final_phase_no_invented_successor(structured):
    w = structured
    rev = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, rev.id)
    w.knowledge.put(draft, 'phase', 'P002', {**phase(), 'status': 'withdrawn'})
    w.knowledge.adopt(draft, rev.id, origin='owner_confirmed', actor=OWNER)
    pid = prepared(w)
    queue_close(w, pid); w.run()
    assert w.get(pid)['successor'] is None
    assert 'Active phase: None' in w.context.path('docs/STATE.md').read_text()


def test_pending_plan_and_tasks_are_deterministic_without_reviewer(structured):
    w = structured; pid = adopt(w)
    _, detail = w.check(pid)
    assert detail['operations'][-1]['status'] == 'NOT_READY'
    assert w.ports.roles() == []
    adopt(w, phase_id=pid, expected_version=detail['version'], coverage={'C001': ['P001-T001']})
    _, detail = w.check(pid)
    assert detail['operations'][-1]['status'] == 'NOT_READY'
    assert w.ports.roles() == []


@pytest.mark.parametrize('verdict', ['READY', 'REVISE', 'BLOCKED'])
def test_typed_check_outcomes_and_actual_reviewer_context(structured, verdict):
    w = structured; pid = planned(w); w.accept_task()
    _, detail = w.check(pid, evaluation(w, pid, verdict))
    op = detail['operations'][-1]
    assert op['status'] == verdict, op
    assert op['result']['reviewer']['participated']
    assert op['result']['deterministic_actor'] == 'Harness'
    request = w.ports.agents.requests[-1]
    assert 'canonical_context' in json.loads(request.prompt_snapshot_json)
    if verdict == 'BLOCKED':
        assert detail['questions'][0]['status'] == 'OPEN'


@pytest.mark.parametrize('change', ['code', 'knowledge', 'question'])
def test_ready_invalidation_by_exact_inputs(structured, change):
    w = structured; pid = prepared(w)
    if change == 'code':
        w.context.path('app/main.txt').write_text('later\n')
        git(w.context.root, 'commit', '-qam', 'Synthetic later code')
    elif change == 'knowledge':
        rev = w.knowledge.revision(w.project)
        draft = w.knowledge.open_draft(w.project, rev.id)
        w.knowledge.put(draft, 'task', 'P001-T001', task('New accepted version'))
        w.knowledge.adopt(draft, rev.id, origin='owner_confirmed', actor=OWNER)
    else:
        w.phases.raise_question(pid, w.get(pid)['version'], text='Owner question')
    with pytest.raises(Conflict): queue_close(w, pid)
    assert git(w.context.root, 'tag', '--list') == ''


def test_coverage_preview_cas_and_no_documentary_definition(structured):
    w = structured; pid = adopt(w)
    with pytest.raises(Conflict, match='coverage'):
        w.structured.preview(w.context, 'P001', phase_id=pid, expected_version=w.get(pid)['version'])
    with pytest.raises(Conflict):
        w.phases.create(w.context, {'code': 'P099'})
    args = {'phase_id': pid, 'expected_version': w.get(pid)['version'], 'coverage': {'C001': ['P001-T001']}}
    shown = w.structured.preview(w.context, 'P001', **args)
    body = dict(preview_sha256=shown['preview_sha256'], key='same-plan', reason='Owner review', confirmed=True, **args)
    assert w.structured.adopt(w.context, 'P001', **body) == pid
    assert StructuredPhases(w.repository).adopt(w.context, 'P001', **body) == pid
    with pytest.raises(Conflict): w.structured.adopt(w.context, 'P001', **{**body, 'key': 'stale'})


@pytest.mark.parametrize('change', ['criteria', 'objective'])
def test_plan_cannot_weaken_product_meaning(structured, change):
    w = structured; pid = planned(w); rev = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, rev.id)
    if change == 'criteria': w.knowledge.put(draft, 'criterion', 'C001', criterion('Weakened criterion.'))
    else: w.knowledge.put(draft, 'phase', 'P001', phase('Different objective.'))
    with pytest.raises(Conflict, match='product_meaning'):
        w.structured.preview(w.context, 'P001', phase_id=pid, expected_version=w.get(pid)['version'],
                             draft_id=draft, coverage={'C001': ['P001-T001']})


def test_insufficient_reviewer_evidence_cannot_be_ready(structured):
    w = structured; pid = planned(w); w.accept_task()
    _, detail = w.check(pid, evaluation(w, pid, evidence=''))
    assert detail['operations'][-1]['status'] == 'FAILED'
    assert detail['ready'] is None


@pytest.mark.parametrize('point', ['tag', 'partial', 'commit', 'record'])
def test_reopen_reconciles_same_closure_effects(structured, point, monkeypatch):
    w = structured; pid = prepared(w)
    before = git(w.context.root, 'rev-parse', 'HEAD')
    job = queue_close(w, pid)
    once = [False]
    if point == 'record':
        import my_harness.storage.phases as target
        name = 'settle'
    else:
        target = GitWorkspace; name = {'tag': 'tag', 'partial': '_write_mechanical', 'commit': 'execute'}[point]
    original = getattr(target, name)
    def fail(*args, **kwargs):
        value = original(*args, **kwargs)
        if not once[0]:
            once[0] = True
            raise RuntimeError('Synthetic crash boundary')
        return value
    monkeypatch.setattr(target, name, fail)
    with pytest.raises((RuntimeError, JournalError), match='Synthetic'): w.run()
    assert w.repository.get_job(job.id).status == 'RECOVERY_REQUIRED'
    intent = w.get(pid)['operations'][-1]['request']['commit_intent']
    from test_documents import confirm
    confirm(w, job)
    from my_harness.storage.database import make_engine
    url = str(w.repository.engine.url)
    w.repository.engine.dispose()
    w.repository = SQLiteManagedRepository(make_engine(url))
    w.phases = PhaseRepository(w.repository)
    w.worker = LocalSupervisor(w.repository, w.ports, commit_factory=w.ports.writer)
    resumed = queue_close(w, pid); w.run()
    assert w.repository.get_run(resumed.run_id).status == 'COMMITTED'
    assert w.get(pid)['operations'][-1]['request']['commit_intent'] == intent
    assert git(w.context.root, 'rev-list', '--count', before + '..HEAD') == '1'
    assert git(w.context.root, 'rev-parse', 'p001') == before
    assert w.ports.roles().count('phase') == 1
    with Session(w.repository.engine) as session:
        assert len(session.scalars(select(PhaseRow).where(PhaseRow.code == 'P002')).all()) == 1


def test_missing_or_forged_closure_authority_before_effect(structured):
    w = structured; pid = prepared(w); job = queue_close(w, pid)
    with w.repository._write() as session:
        auth = session.scalar(select(PhaseAuthorizationRow).where(PhaseAuthorizationRow.phase_id == pid))
        auth.scope = {**auth.scope, 'binding_sha256': '0' * 64}
    with pytest.raises((RuntimeError, JournalError, Conflict)): w.run()
    assert git(w.context.root, 'tag', '--list') == ''


def test_abandonment_without_ready_or_tag(structured):
    w = structured; pid = planned(w)
    job = w.phases.abandon(pid, w.get(pid)['version'], reason='Owner abandons', context=w.context,
                          git=w.ports.writer(w.context, VERSIONS), key=w.key(), versions=VERSIONS)
    w.run()
    assert w.repository.get_run(job.run_id).status == 'COMMITTED'
    assert w.get(pid)['status'] == 'ABANDONED'
    assert git(w.context.root, 'tag', '--list') == ''


def test_structured_http_owner_journey(structured, tmp_path):
    w = structured
    with client(str(w.repository.engine.url), tmp_path, config(w.context, w.ports)) as http:
        base = '/api/managed'
        def post(path, body, key=None):
            response = http.post(base + path, json=body, headers={'Idempotency-Key': key or w.key()})
            assert response.status_code in (200, 201, 202), response.text
            return response.json()
        args = {'code': 'P001'}
        shown = post('/projects/synthetic/phases/accepted/preview', args)
        accepted = post('/projects/synthetic/phases/accepted/adopt', {**args,
            'preview_sha256': shown['preview_sha256'], 'confirmed': True, 'reason': 'Owner phase activation'})
        pid = accepted['id']
        candidate = proposal()
        candidate['knowledge'] = {'items': [], 'links': []}
        candidate['coverage'] = {'C001': ['P001-T001']}
        w.script(candidate)
        job = post('/phases/' + pid + '/plan/propose', {'expected_version': accepted['version']})
        settle(http, job['run_id'])
        detail = http.get(base + '/phases/' + pid).json()
        op = detail['operations'][-1]
        assert op['status'] == 'PROPOSED', op
        staged = post('/phases/' + pid + '/plan/stage', {'expected_version': detail['version'],
            'operation_id': op['id'], 'proposal_sha256': op['result']['proposal_sha256']})
        detail = http.get(base + '/phases/' + pid).json()
        args.update(phase_id=pid, expected_version=detail['version'], **staged)
        shown = post('/projects/synthetic/phases/accepted/preview', args)
        accepted = post('/projects/synthetic/phases/accepted/adopt', {**args,
            'preview_sha256': shown['preview_sha256'], 'confirmed': True, 'reason': 'Owner adopts plan'})
        w.script(edit, review())
        job = post('/projects/synthetic/runs', {'task_id': 'P001-T001', 'phase_id': 'P001', 'text': PLAN})
        run = settle(http, job['run_id']); assert run['status'] == 'ACCEPTANCE_READY', run
        job = post('/runs/' + run['id'] + '/actions', {'action': 'commit', 'expected_version': run['version']})
        assert settle(http, job['run_id'])['status'] == 'COMMITTED'
        detail = http.get(base + '/phases/' + pid).json()
        w.script(evaluation(w, pid))
        job = post('/phases/' + pid + '/actions', {'action': 'check', 'expected_version': detail['version']})
        settle(http, job['run_id'])
        detail = http.get(base + '/phases/' + pid).json()
        assert detail['status'] == 'READY_TO_CLOSE', detail
        body = {'action': 'close', 'expected_version': detail['version'], 'binding_sha256': detail['ready']['binding_sha256'],
                'reason': 'Owner confirms closure', 'ttl_seconds': 3600, 'confirmed': True}
        job = post('/phases/' + pid + '/actions', body, 'http-close')
        assert settle(http, job['run_id'])['status'] == 'COMMITTED'
        assert post('/phases/' + pid + '/actions', body, 'http-close')['id'] == job['id']
        detail = http.get(base + '/phases/' + pid).json()
        assert detail['status'] == 'CLOSED' and detail['successor'] == 'P002'


def proposal():
    source = {'kind': 'observation', 'reference': 'Synthetic phase plan', 'sha256': digest('synthetic')}
    return {'answer': 'Add a bounded task for the same criterion.', 'questions': [], 'pending': [], 'plan': None,
        'coverage': {'C001': ['P001-T001', 'P001-T002']},
        'knowledge': {'items': [{'op': 'put', 'kind': 'task', 'code': 'P001-T002', 'content': task('More evidence'),
                                'provenance': 'inferred', 'source': source}],
            'links': [{'kind': 'part_of', 'source': 'task::P001-T002', 'target': 'phase::P001', 'position': 1}]}}


def test_reviewer_proposal_requires_stage_validation_and_separate_owner_adoption(structured):
    w = structured; pid = planned(w); old = w.knowledge.revision(w.project)
    w.script(proposal())
    job = w.structured.propose(w.context, pid, w.get(pid)['version'], key=w.key(), versions=VERSIONS)
    w.run()
    op = w.get(pid)['operations'][-1]
    assert op['status'] == 'PROPOSED', op
    assert w.knowledge.revision(w.project).id == old.id
    assert w.get(pid)['definition']['tasks'] == ['P001-T001']
    staged = w.structured.stage(w.context, pid, op['id'], w.get(pid)['version'], proposal_sha256=op['result']['proposal_sha256'])
    assert w.knowledge.revision(w.project).id == old.id
    shown = w.structured.preview(w.context, 'P001', phase_id=pid, expected_version=w.get(pid)['version'], **staged)
    assert 'P001-T002' in shown['definition']['tasks']
    args = dict(phase_id=pid, expected_version=w.get(pid)['version'], **staged)
    w.structured.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], key=w.key(),
                       reason='Owner separately reviews the proposal.', confirmed=True, **args)
    assert w.get(pid)['definition']['tasks'] == ['P001-T001', 'P001-T002']
    assert w.knowledge.revision(w.project).id != old.id
    assert w.ports.roles() == ['planning']
    assert 'Successor objective.' not in w.ports.agents.requests[-1].prompt
    assert shown['definition']['knowledge']['dependencies'] == {'P001-T001': [], 'P001-T002': []}
    assert w.repository.get_run(job.run_id).history.attempts


def test_remediation_preserves_task_identity_lineage_and_budget(structured):
    from my_harness.storage.task_lineage import budget
    w = structured; pid = planned(w); w.accept_task(); w.check(pid, evaluation(w, pid, 'REVISE'))
    rev = w.knowledge.revision(w.project); old = rev.item('task', 'P001-T001').item_id
    draft = w.knowledge.open_draft(w.project, rev.id)
    w.knowledge.put(draft, 'task', 'P001-T001', {**task(), 'status': 'withdrawn'})
    new = w.knowledge.put(draft, 'task', 'P001-T002', task('Criterion remediation'))
    w.knowledge.link(draft, 'part_of', new, rev.item('phase', 'P001').item_id, position=1)
    args = {'phase_id': pid, 'expected_version': w.get(pid)['version'], 'draft_id': draft,
            'coverage': {'C001': ['P001-T002']}}
    with pytest.raises(Conflict, match='lineage'): w.structured.preview(w.context, 'P001', **args)
    w.knowledge.link(draft, 'replaces', new, old)
    shown = w.structured.preview(w.context, 'P001', **args)
    w.structured.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], reason='Owner adopts remediation',
                       confirmed=True, key=w.key(), **args)
    with Session(w.repository.engine) as session:
        state = budget(session, str(w.context.root), 'P001-T002', 9)
        assert state['tasks'] == ['P001-T001', 'P001-T002']
        assert state['executions'] == 1 and state['revision_limit'] == 1
    assert w.get(pid)['ready'] is None


@pytest.mark.parametrize('bad', ['dirty', 'symlink', 'hardlink', 'archive', 'case_collision'])
def test_untrusted_target_refused_before_tag(structured, bad):
    import os
    w = structured; pid = prepared(w)
    if bad == 'dirty': w.context.path('docs/STATE.md').write_text('Owner edit not committed.')
    elif bad == 'symlink':
        w.context.path('docs/STATE.md').unlink(); w.context.path('docs/STATE.md').symlink_to('../app/main.txt')
    elif bad == 'hardlink':
        w.context.path('docs/STATE.md').unlink(); os.link(w.context.path('app/main.txt'), w.context.path('docs/STATE.md'))
    elif bad == 'archive': w.context.path('docs/archive/phase-001').mkdir(parents=True)
    else:
        w.context.path('docs/phase/Notes.md').parent.mkdir(parents=True, exist_ok=True)
        w.context.path('docs/phase/Notes.md').write_text('a')
        w.context.path('docs/phase/notes.md').write_text('b')
    with pytest.raises((Conflict, ValueError)): queue_close(w, pid)
    assert git(w.context.root, 'tag', '--list') == ''


def test_generated_closure_views_roundtrip_never_imports_operational_authority(structured):
    from my_harness.core.engine import knowledge_documents as d
    w = structured; pid = prepared(w); queue_close(w, pid); w.run()
    files = {p: w.context.path(p).read_text() for p in w.get(pid)['definition']['documents']}
    data, report, _ = d.parse(files)
    assert not any(item['blocking'] for item in report), report
    assert any(item['code'] == 'operational_view_not_imported' for item in report)
    assert data['revision']['id'] == w.knowledge.revision(w.project).id


def test_manual_batch_never_checks_or_closes_and_plan_adoption_invalidates_it(structured):
    w = structured; pid = planned(w)
    auth = w.phases.authorize_batch(pid, w.get(pid)['version'], tasks=['P001-T001'], ttl_seconds=3600,
                                   reason='Owner batch of tasks only')
    assert w.get(pid)['authorizations'][-1]['id'] == auth
    adopt(w, phase_id=pid, expected_version=w.get(pid)['version'], coverage={'C001': ['P001-T001']})
    assert w.get(pid)['authorizations'][-1]['status'] == 'INVALIDATED'
    assert w.get(pid)['ready'] is None and git(w.context.root, 'tag', '--list') == ''


def test_changed_task_revision_cannot_reuse_old_committed_acceptance(structured):
    w = structured; pid = prepared(w)
    rev = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, rev.id)
    w.knowledge.put(draft, 'task', 'P001-T001', task('New task contract.'))
    w.knowledge.adopt(draft, rev.id, origin='owner_confirmed', actor=OWNER)
    adopt(w, phase_id=pid, expected_version=w.get(pid)['version'], coverage={'C001': ['P001-T001']})
    _, detail = w.check(pid)
    assert detail['check']['verdict'] == 'NOT_READY'
    assert detail['tasks']['P001-T001'] is None
    assert len([r for r in w.ports.roles() if r == 'phase']) == 1


def test_reviewer_cannot_adopt_or_weaken_criteria_through_its_plan(structured):
    w = structured; pid = planned(w); rev = w.knowledge.revision(w.project)
    data = proposal()
    data['knowledge']['items'].append({'op': 'put', 'kind': 'criterion', 'code': 'C001',
        'content': criterion('Remove the real acceptance requirement.'), 'provenance': 'inferred',
        'source': {'kind': 'observation', 'reference': 'Synthetic model output'}})
    w.script(data)
    w.structured.propose(w.context, pid, w.get(pid)['version'], key=w.key(), versions=VERSIONS); w.run()
    op = w.get(pid)['operations'][-1]
    with pytest.raises(Conflict, match='product_meaning'):
        w.structured.stage(w.context, pid, op['id'], w.get(pid)['version'], proposal_sha256=op['result']['proposal_sha256'])
    assert w.knowledge.revision(w.project).id == rev.id
    assert w.get(pid)['definition']['tasks'] == ['P001-T001']


@pytest.mark.parametrize('fake', ['revoked', 'origin', 'scope', 'actor', 'expired'])
def test_authority_chain_tampering_fails_closed(structured, fake):
    w = structured; pid = prepared(w); queue_close(w, pid)
    with w.repository._write() as session:
        auth = session.scalar(select(PhaseAuthorizationRow).where(PhaseAuthorizationRow.phase_id == pid))
        if fake == 'revoked': auth.status = 'REVOKED'
        elif fake == 'actor': auth.actor = {}
        elif fake == 'expired': auth.expires_at = '2000-01-01T00:00:00+00:00'
        elif fake == 'origin': auth.scope = {**auth.scope, 'origin': 'owner_delegated', 'parent': 'fabricated'}
        else: auth.scope = {**auth.scope, 'tag_kind': 'annotated'}
        auth.fingerprint = digest({'phase_id': pid, 'scope': auth.scope, 'expires_at': auth.expires_at})
    # Expiry is a typed refusal; altered persisted authority never reaches a tag or archive writer.
    try: w.run()
    except (RuntimeError, JournalError, Conflict): pass
    assert w.get(pid)['status'] != 'CLOSED'
    assert git(w.context.root, 'tag', '--list') == ''
    assert not w.context.path('docs/archive/phase-001/knowledge.json').exists()


def test_uncertain_inference_is_not_reissued_after_restart(structured, monkeypatch):
    w = structured; pid = planned(w); w.accept_task()
    version = w.get(pid)['version']; key = w.key()
    w.script(evaluation(w, pid))
    job = w.phases.submit_check(w.context, pid, version, key=key, versions=VERSIONS)
    original = w.repository.checkpoint
    def crash(claim, history, stage, **kwargs):
        if history.attempts:
            raise RuntimeError('Synthetic lost inference receipt')
        return original(claim, history, stage, **kwargs)
    monkeypatch.setattr(w.repository, 'checkpoint', crash)
    with pytest.raises((RuntimeError, JournalError)): w.run()
    assert w.repository.get_job(job.id).status == 'RECOVERY_REQUIRED'
    assert w.phases.submit_check(w.context, pid, version, key=key, versions=VERSIONS).id == job.id
    restarted = SQLiteManagedRepository(w.repository.engine)
    assert LocalSupervisor(restarted, w.ports, commit_factory=w.ports.writer).run_once() is None
    assert w.ports.roles().count('phase') == 1


def test_missing_required_document_is_pending_work_without_reviewer(structured):
    w = structured; pid = planned(w); w.accept_task()
    w.context.path('docs/STATE.md').unlink()
    git(w.context.root, 'commit', '-qam', 'Synthetic missing required document')
    _, detail = w.check(pid)
    assert detail['check']['classification'] == 'missing_work'
    assert not detail['check']['reviewer']['participated']


def test_dependency_cycle_refused_before_plan_adoption(structured):
    from my_harness.core.engine.contracts import ContractError
    w = structured; pid = planned(w); rev = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, rev.id)
    old = rev.item('task', 'P001-T001').item_id
    new = w.knowledge.put(draft, 'task', 'P001-T002', task('Cycle candidate'))
    w.knowledge.link(draft, 'part_of', new, rev.item('phase', 'P001').item_id, position=1)
    w.knowledge.link(draft, 'depends_on', new, old)
    w.knowledge.link(draft, 'depends_on', old, new)
    with pytest.raises(ContractError):
        w.structured.preview(w.context, 'P001', phase_id=pid, expected_version=w.get(pid)['version'],
            draft_id=draft, coverage={'C001': ['P001-T001', 'P001-T002']})
    assert w.knowledge.revision(w.project).id == rev.id


def test_closed_phase_keeps_its_historical_task_contract_after_later_knowledge_changes(structured):
    w = structured; pid = prepared(w); queue_close(w, pid); w.run()
    historical = w.get(pid)['tasks']
    revision = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, revision.id)
    w.knowledge.put(draft, 'task', 'P001-T001', task('Later accepted meaning.'))
    w.knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    assert w.get(pid)['tasks'] == historical
    assert historical['P001-T001'] is not None
    assert w.get(pid)['actions'] == []


def test_withdrawn_canonical_phase_can_be_explicitly_abandoned(structured):
    w = structured; pid = planned(w)
    revision = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, revision.id)
    w.knowledge.put(draft, 'phase', 'P001', {**phase(), 'tag': 'p001', 'status': 'withdrawn'})
    w.knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    job = w.phases.abandon(pid, w.get(pid)['version'], reason='Owner abandons withdrawn scope', context=w.context,
                          git=w.ports.writer(w.context, VERSIONS), key=w.key(), versions=VERSIONS)
    w.run()
    assert w.repository.get_run(job.run_id).status == 'COMMITTED'
    assert w.get(pid)['status'] == 'ABANDONED' and w.get(pid)['successor'] == 'P002'
    assert git(w.context.root, 'tag', '--list') == ''


def test_http_read_exposes_stale_code_binding_before_close(structured, tmp_path):
    w = structured; pid = prepared(w)
    with client(str(w.repository.engine.url), tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        path = '/api/managed/phases/' + pid
        before = http.get(path).json()
        assert 'close' in before['actions']
        w.context.path('app/main.txt').write_text('Later committed code\n')
        git(w.context.root, 'commit', '-qam', 'Synthetic code invalidation')
        after = http.get(path).json()
        assert after['ready']['stale_reasons'] and 'close' not in after['actions']


def test_failed_invocation_does_not_claim_observed_reviewer_participation(structured):
    from my_harness.core.engine.contracts import AgentResult
    w = structured; pid = planned(w); w.accept_task()
    _, detail = w.check(pid, AgentResult(None, error='Synthetic missing response'))
    assert detail['check']['verdict'] == 'FAILED'
    assert detail['check']['reviewer']['attempt_count'] == 1
    assert detail['check']['reviewer']['participated'] is None


def test_lost_writer_fence_prevents_git_effect_without_releasing_lock(structured, monkeypatch):
    from my_harness.storage.models import ManagedJobRow, CheckoutLockRow
    from my_harness.storage.managed import OwnershipLost
    w = structured; pid = prepared(w); job = queue_close(w, pid)
    original = w.repository.tag_intent
    def lose_fence(claim, intent):
        original(claim, intent)
        with w.repository._write() as session:
            session.get(ManagedJobRow, job.id).status = 'RECOVERY_REQUIRED'
    monkeypatch.setattr(w.repository, 'tag_intent', lose_fence)
    with pytest.raises((RuntimeError, JournalError, OwnershipLost)): w.run()
    assert git(w.context.root, 'tag', '--list') == ''
    assert not w.context.path('docs/archive/phase-001/knowledge.json').exists()
    with Session(w.repository.engine) as session:
        assert session.get(CheckoutLockRow, str(w.context.root)).job_id == job.id


def test_revocation_between_export_targets_prevents_subsequent_writes(structured, monkeypatch):
    import my_harness.storage.structured_phases as module
    w = structured; pid = prepared(w); queue_close(w, pid)
    observed = []
    original = module.record_export_target
    def revoke_after_first(managed, run_id, path):
        original(managed, run_id, path)
        observed.append(path)
        if len(observed) == 1:
            with managed._write() as session:
                auth = session.scalar(select(PhaseAuthorizationRow).where(PhaseAuthorizationRow.phase_id == pid))
                auth.status = 'REVOKED'
    monkeypatch.setattr(module, 'record_export_target', revoke_after_first)
    before = git(w.context.root, 'rev-parse', 'HEAD')
    with pytest.raises((RuntimeError, JournalError, Conflict)): w.run()
    assert len(observed) == 1
    assert git(w.context.root, 'rev-parse', 'HEAD') == before
    assert w.get(pid)['status'] != 'CLOSED'


def test_plan_revision_preserves_unanswered_question_and_blocked_status(structured):
    w = structured; pid = planned(w)
    w.phases.raise_question(pid, w.get(pid)['version'], text='Owner question remains unresolved.')
    question = w.get(pid)['questions'][0]
    adopt(w, phase_id=pid, expected_version=w.get(pid)['version'], coverage={'C001': ['P001-T001']})
    detail = w.get(pid)
    assert detail['status'] == 'BLOCKED' and detail['questions'][0] == question
    assert detail['ready'] is None and 'check' not in detail['actions']
    w.phases.answer(pid, question['id'], detail['version'], expected_question_version=question['version'], answer='Owner answer.')
    assert w.get(pid)['status'] == 'ACTIVE'


def test_http_recovery_action_survives_expected_partial_archive_changes(structured, tmp_path, monkeypatch):
    w = structured; pid = prepared(w); job = queue_close(w, pid)
    original = GitWorkspace._write_mechanical
    first = [True]
    def partial(*args, **kwargs):
        original(*args, **kwargs)
        if first[0]:
            first[0] = False
            raise RuntimeError('Synthetic partial archive before HTTP recovery')
    monkeypatch.setattr(GitWorkspace, '_write_mechanical', partial)
    with pytest.raises((RuntimeError, JournalError)): w.run()
    from test_documents import confirm
    confirm(w, job)
    with client(str(w.repository.engine.url), tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        response = http.get('/api/managed/phases/' + pid)
        assert response.status_code == 200, response.text
        assert 'close' in response.json()['actions']
        assert response.json()['ready']['binding_sha256'] == w.get(pid)['ready']['binding_sha256']


@pytest.mark.parametrize('published', [True, False])
def test_closure_recovery_after_knowledge_adoption(structured, monkeypatch, published):
    from test_documents import confirm
    from my_harness.storage import knowledge_exchange as exchange

    w = structured
    pid = prepared(w)
    job = queue_close(w, pid)
    method = 'execute' if published else '_write_mechanical'
    original = getattr(GitWorkspace, method)

    def lose_receipt(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic lost closure receipt')

    with monkeypatch.context() as patch:
        patch.setattr(GitWorkspace, method, lose_receipt)
        with pytest.raises((RuntimeError, JournalError)):
            w.run()
    head = git(w.context.root, 'rev-parse', 'HEAD')
    tag = git(w.context.root, 'rev-parse', 'p001')
    confirm(w, job)
    operation = w.get(pid)['operations'][-1]
    revision = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, revision.id)
    w.knowledge.put(draft, 'section', 'rules', section('Rules', 'Later accepted instructions.'),
                    document='instructions', root_position=0)
    adopted = w.knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)

    if published:
        # The sealed commit supplies the archive evidence even if a live file has changed.
        w.context.path('AGENTS.md').write_text('Uncommitted owner edit\n')
        resumed = queue_close(w, pid)
        w.run()
        assert resumed.run_id == job.run_id
        detail = w.get(pid)
        assert detail['status'] == 'CLOSED' and detail['successor'] == 'P002'
        assert detail['operations'][-1]['id'] == operation['id']
        assert detail['operations'][-1]['result']['published_recovery']
        assert w.context.path('AGENTS.md').read_text() == 'Uncommitted owner edit\n'
        with Session(w.repository.engine) as session:
            result = exchange.latest(session, w.project, 'export_completed').payload
            assert result['revision_id'] == revision.id
            assert result['commit'] == head
        assert w.knowledge.revision(w.project).id == adopted.id
    else:
        with pytest.raises(Conflict, match='stale'):
            queue_close(w, pid)
        assert w.get(pid)['status'] != 'CLOSED'
    assert git(w.context.root, 'rev-parse', 'HEAD') == head
    assert git(w.context.root, 'rev-parse', 'p001') == tag
    assert w.ports.roles().count('phase') == 1


@pytest.mark.parametrize('first_status', ['CLOSED', 'ABANDONED'])
def test_roadmap_preserves_two_completed_archives_through_regeneration(structured, first_status):
    from my_harness.core.engine import knowledge_documents as documents
    from test_knowledge_documents import disk_baseline, payload, run

    w = structured
    revision = w.knowledge.revision(w.project)
    draft = w.knowledge.open_draft(w.project, revision.id)
    second = w.knowledge.put(draft, 'task', 'P002-T001', task('Second phase task'))
    w.knowledge.link(draft, 'part_of', second, revision.item('phase', 'P002').item_id, position=0)
    w.knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    first = prepared(w)
    if first_status == 'CLOSED':
        queue_close(w, first)
    else:
        w.phases.abandon(first, w.get(first)['version'], reason='Owner abandons the first phase.',
                         context=w.context, git=GitWorkspace(IDENTITY), key=w.key(), versions=VERSIONS)
    w.run()
    pid = w.phases.by_code(str(w.context.root), 'P002')
    args = {'phase_id': pid, 'expected_version': w.get(pid)['version'], 'coverage': {'C002': ['P002-T001']}}
    shown = w.structured.preview(w.context, 'P002', **args)
    w.structured.adopt(w.context, 'P002', preview_sha256=shown['preview_sha256'], key=w.key(),
                       reason='Owner adopts second plan.', confirmed=True, **args)
    w.script(edit, {**review(), 'task_id': 'P002-T001'})
    job = w.repository.submit(w.context, 'P002-T001', 'P002', PLAN.replace('P001', 'P002'), VERSIONS, key=w.key())
    w.run()
    accepted = w.repository.get_run(job.run_id)
    assert accepted.status == 'ACCEPTANCE_READY'
    w.repository.submit_commit(job.run_id, key=w.key(), expected_version=accepted.version)
    w.run()
    roadmap = w.context.path('docs/ROADMAP.md')
    first_link = f'[P001: {first_status}](archive/phase-001/)'
    assert first_link in roadmap.read_text()
    w.check(pid, {**evaluation(w, pid), 'phase_id': 'P002'})
    queue_close(w, pid)
    w.run()
    assert w.get(pid)['status'] == 'CLOSED'
    links = [first_link, '[P002: CLOSED](archive/phase-002/)']
    assert all(link in roadmap.read_text() for link in links)

    engine, root = w.repository.engine, w.context.root
    paths = w.get(pid)['definition']['documents']
    captured = disk_baseline(root, paths)
    captured['ownership_id'] = run(engine, root, 'documents.bundle', {})['ownership_id']
    shown = run(engine, root, 'documents.export.prepare', payload(captured), w.key())
    KnowledgeDelivery(engine, root, w.project).execute(shown['record_id'], shown['preview_sha256'], IDENTITY)
    assert all(link in roadmap.read_text() for link in links)
    parsed, report, _ = documents.parse({path: w.context.path(path).read_text() for path in paths})
    assert not any(item['blocking'] for item in report)
    assert any(item['code'] == 'operational_view_not_imported' for item in report)
    assert 'archive/phase-' not in json.dumps(parsed)


@pytest.mark.parametrize('provider', ['claude', 'codex'])
def test_native_structured_planning_contract_and_owner_adoption(structured, tmp_path, provider):
    import sys
    from test_cli_agents import adapter, PROBE
    from my_harness.adapters.cli_agents import CLIProcessAdapter
    from my_harness.core.engine.domain_catalogue import validate, SchemaError

    w = structured
    pid = planned(w)
    old = w.knowledge.revision(w.project).id
    candidate = proposal()
    script = tmp_path / 'phase-response.json'
    script.write_text(json.dumps({'structured_phase_plan': candidate}))
    base = next(cfg for cfg in adapter(tmp_path).agents.values() if cfg.provider == provider)
    cfg = replace(base, executable=(sys.executable, PROBE, provider, 'recipe'),
                  environment=(*base.environment, ('PROBE_SCRIPT', str(script))))
    ports = CLIProcessAdapter({'reviewer': cfg, 'executor': cfg}, tmp_path / 'phase-captures')
    versions = {**VERSIONS, **ports.frozen_versions()}
    worker = LocalSupervisor(w.repository, lambda *_: (ports, w.ports.runner, None),
                             commit_factory=lambda *_: GitWorkspace(IDENTITY))
    job = w.structured.propose(w.context, pid, w.get(pid)['version'], key=w.key(), versions=versions)
    worker.run_once()
    op = w.get(pid)['operations'][-1]
    assert op['status'] == 'PROPOSED', op
    attempt = w.repository.get_run(job.run_id).history.attempts[-1]
    schema = json.loads(attempt.request.prompt_snapshot_json)['output_schema']
    launch = json.loads((tmp_path / 'launches.jsonl').read_text().splitlines()[-1])
    assert json.loads(launch['prompt'].rsplit('Shape:\n', 1)[1]) == schema
    if provider == 'claude':
        assert json.loads(launch['argv'][launch['argv'].index('--json-schema') + 1]) == schema
    validate(schema, candidate)
    for invalid in ({key: candidate[key] for key in ('answer', 'questions', 'pending', 'plan')},
                    {**candidate, 'plan': {'content': 'Old plan', 'reason': 'Old shape'}}):
        with pytest.raises(SchemaError):
            validate(schema, invalid)
    staged = w.structured.stage(w.context, pid, op['id'], w.get(pid)['version'],
                               proposal_sha256=op['result']['proposal_sha256'])
    assert w.knowledge.revision(w.project).id == old
    args = dict(phase_id=pid, expected_version=w.get(pid)['version'], **staged)
    shown = w.structured.preview(w.context, 'P001', **args)
    w.structured.adopt(w.context, 'P001', preview_sha256=shown['preview_sha256'], key=w.key(),
                       reason='Owner confirms candidate.', confirmed=True, **args)
    assert w.get(pid)['definition']['tasks'] == ['P001-T001', 'P001-T002']


@pytest.mark.parametrize('change', ['worktree', 'index', 'head'])
def test_new_tag_rejects_checkout_changes_after_sealing_intent(structured, monkeypatch, change):
    w = structured
    pid = prepared(w)
    job = queue_close(w, pid)
    original = w.repository.tag_intent
    before = git(w.context.root, 'rev-parse', 'HEAD')
    owner_file = w.context.path('app/main.txt')
    owner_bytes = b'Synthetic owner bytes after sealing the tag.\n'

    def change_after_seal(claim, intent):
        original(claim, intent)
        if change == 'head':
            git(w.context.root, 'commit', '--allow-empty', '-m', 'Synthetic later HEAD')
        else:
            owner_file.write_bytes(owner_bytes)
            if change == 'index':
                git(w.context.root, 'add', 'app/main.txt')

    monkeypatch.setattr(w.repository, 'tag_intent', change_after_seal)
    w.run()
    result = w.get(pid)['operations'][-1]
    assert result['status'] == 'STALE'
    assert result['request']['tag_intent']['target'] == before
    assert git(w.context.root, 'tag', '--list') == ''
    assert not w.context.path('docs/archive/phase-001').exists()
    head = git(w.context.root, 'rev-parse', 'HEAD')
    assert head != json.loads(result['request']['commit_intent'])['expected_commit']
    if change == 'head':
        assert git(w.context.root, 'log', '-1', '--format=%s') == 'Synthetic later HEAD'
        assert git(w.context.root, 'rev-parse', 'HEAD^') == before
    else:
        assert head == before
        assert owner_file.read_bytes() == owner_bytes
        staged = git(w.context.root, 'diff', '--cached', '--name-only')
        assert staged == ('app/main.txt' if change == 'index' else '')
    assert w.repository.get_job(job.id).status == 'DONE'


def test_new_tag_transaction_rejects_head_move_after_capture(structured, monkeypatch):
    from my_harness.adapters.git import Git

    w = structured
    pid = prepared(w)
    queue_close(w, pid)
    original = Git.run
    moved = False

    def move_head_at_publish(adapter, *args, **kwargs):
        nonlocal moved
        if args[0] == 'update-ref' and b'create refs/tags/p001 ' in (kwargs.get('input') or b''):
            git(w.context.root, 'commit', '--allow-empty', '-m', 'Synthetic ref race')
            moved = True
        return original(adapter, *args, **kwargs)

    monkeypatch.setattr(Git, 'run', move_head_at_publish)
    w.run()
    assert moved
    assert w.get(pid)['operations'][-1]['status'] == 'STALE'
    assert git(w.context.root, 'tag', '--list') == ''
    assert git(w.context.root, 'log', '-1', '--format=%s') == 'Synthetic ref race'
    assert not w.context.path('docs/archive/phase-001').exists()


def test_partial_archive_recovery_rejects_foreign_edit_and_keeps_existing_tag(structured, monkeypatch):
    from test_documents import confirm

    w = structured
    pid = prepared(w)
    job = queue_close(w, pid)
    original = GitWorkspace._write_mechanical

    def stop_after_first_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic partial archive')

    with monkeypatch.context() as patch:
        patch.setattr(GitWorkspace, '_write_mechanical', stop_after_first_write)
        with pytest.raises((RuntimeError, JournalError), match='Synthetic partial archive'):
            w.run()
    head = git(w.context.root, 'rev-parse', 'HEAD')
    assert git(w.context.root, 'rev-parse', 'p001') == head
    confirm(w, job)
    owner_file = w.context.path('app/main.txt')
    owner_file.write_bytes(b'Unrelated owner edit during recovery\n')
    queue_close(w, pid)
    w.run()
    result = w.get(pid)['operations'][-1]
    assert result['status'] == 'STALE'
    assert result['result']['tag']['status'] == 'reconciled'
    assert git(w.context.root, 'rev-parse', 'HEAD') == head
    assert git(w.context.root, 'rev-parse', 'p001') == head
    assert owner_file.read_bytes() == b'Unrelated owner edit during recovery\n'
