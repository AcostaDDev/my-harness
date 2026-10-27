"""P008-T004: unified closure with synthetic repositories, Git, SQLite and providers."""
from dataclasses import replace
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.documents import DOCUMENT_LAYOUT, base_section, blocks, plan_tasks
from my_harness.storage.managed import Conflict
from my_harness.storage.documents import DocumentsRepository
from my_harness.storage.models import PhaseRow
from my_harness.storage.phase_plan import PhasePlanRepository
from my_harness.storage.transition import TransitionRepository
from test_managed import repository  # noqa: F401
from test_managed_api import VERSIONS, git, client
from test_documents import V2World, v2checkout, STATE, PLAN_P002, confirm, queue_edit  # noqa: F401
from my_harness.core.engine.journal import JournalError
from test_phases import head, phase_review


@pytest.fixture
def unified(repository, v2checkout):
    return V2World(repository, v2checkout)


def queue(world, pid, key=None):
    detail = world.get(pid)
    return world.phases.submit_close(world.context, pid, detail['version'], key=key or world.key(), versions=VERSIONS,
                                    binding_sha256=detail['ready']['binding_sha256'], reason='Synthetic closure',
                                    ttl_seconds=3600, git=world.ports.writer(world.context, VERSIONS))


def ready(world):
    work = world.context.path('docs/phase/nested')
    work.mkdir(parents=True)
    (work / 'image.bin').write_bytes(bytes(range(256)))
    world.context.path('docs/phase/notes.md').write_bytes(b'notes\r\nwithout final newline')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-qm', 'synthetic artifacts')
    pid = world.create_v2()
    world.accept()
    world.check(pid, phase_review())
    return pid


def test_unified_closure_exact_archive_and_successor_without_plan(unified):
    world = unified
    pid = ready(world)
    previous = head(world)
    original = {path: world.context.path(path).read_bytes() for path in (
        'docs/STATE.md', 'docs/NEXT_STEPS.md', 'docs/phase/nested/image.bin', 'docs/phase/notes.md')}
    job = queue(world, pid, 'close-once')
    world.run()
    assert git(world.context.root, 'rev-parse', 'HEAD^') == previous
    assert git(world.context.root, 'rev-parse', 'refs/tags/p001') == previous
    assert git(world.context.root, 'status', '--porcelain') == ''
    for path, data in original.items():
        name = path.removeprefix('docs/phase/') if '/phase/' in path else path.removeprefix('docs/')
        assert world.context.path('docs/archive/phase-001/' + name).read_bytes() == data
    assert list(world.context.path('docs/phase').iterdir()) == []
    assert base_section(STATE).rstrip() in world.context.path('docs/STATE.md').read_text()
    assert plan_tasks(world.context.path('docs/NEXT_STEPS.md').read_text()) == []
    road = world.context.path('docs/ROADMAP.md').read_text()
    assert '| Archivo |' in road and '[archivo](archive/phase-001/)' in road and 'completada' in road
    with Session(world.repository.engine) as session:
        following = session.scalar(select(PhaseRow).where(PhaseRow.code == 'P002'))
        assert following.status == 'ACTIVE' and following.definition['tasks'] == []
        assert following.definition['objective'] == 'Ampliar el comportamiento sintético.'
    assert world.repository.get_run(job.run_id).status == 'COMMITTED'
    assert world.get(pid)['operations'][-1]['result']['commit'] == head(world)
    original = json.loads(job.request_json)
    duplicate = world.phases.submit_close(world.context, pid, original['expected_version'], key='close-once',
        versions=VERSIONS, binding_sha256=original['binding_sha256'], reason=original['reason'],
        ttl_seconds=original['ttl_seconds'], git=world.ports.writer(world.context, VERSIONS))
    assert duplicate.id == job.id and world.worker.run_once() is None
    with pytest.raises(Conflict, match='latest phase'):
        TransitionRepository(world.repository).preview(world.context, pid, world.ports.writer(world.context, VERSIONS))


@pytest.mark.parametrize('case', ['dirty', 'index', 'drift', 'archive', 'pending', 'collision', 'symlink'])
def test_closure_refuses_before_tag_or_writes(unified, case):
    world = unified
    pid = ready(world)
    if case in ('dirty', 'index'):
        world.context.path('app/main.txt').write_text('external\n')
        if case == 'index':
            git(world.context.root, 'add', 'app/main.txt')
    elif case == 'drift':
        world.context.path('docs/STATE.md').write_text('external\n')
        git(world.context.root, 'commit', '-qam', 'drift')
    elif case == 'archive':
        world.context.path('docs/archive/phase-001').mkdir(parents=True)
    elif case == 'pending':
        world.repository.submit(world.context, 'P001-T002', 'P001', PLAN_P002.replace('P002', 'P001'),
                                VERSIONS, key=world.key())
    elif case == 'collision':
        world.context.path('docs/phase/STATE.md').write_text('reserved')
        git(world.context.root, 'add', '-A')
        git(world.context.root, 'commit', '-qm', 'reserved')
    else:
        world.context.path('docs/phase/link').symlink_to(world.context.path('app/main.txt'))
        git(world.context.root, 'add', '-A')
        git(world.context.root, 'commit', '-qm', 'symlink')
    before = head(world)
    with pytest.raises(Conflict):
        queue(world, pid)
    assert head(world) == before and git(world.context.root, 'tag', '--list') == ''
    assert not world.context.path('docs/archive/phase-001/STATE.md').exists()


@pytest.mark.parametrize('point', ['tag', 'write', 'partial', 'delete', 'commit', 'record'])
def test_closure_recovery_reuses_tag_commit_and_successor(unified, point, monkeypatch):
    world = unified
    pid = ready(world)
    previous = head(world)
    job = queue(world, pid)
    once = [False]
    def patch(owner, name, when='after'):
        original = getattr(owner, name)
        def failing(*args, **kwargs):
            if point == 'delete' and not any(update.content is None for update in args[2].mechanical):
                return original(*args, **kwargs)
            if when == 'after':
                result = original(*args, **kwargs)
            if not once[0]:
                once[0] = True
                if point == 'partial':
                    self, context, intent = args
                    original(self, context, replace(intent, mechanical=intent.mechanical[:3]))
                raise RuntimeError('synthetic crash')
            return result if when == 'after' else original(*args, **kwargs)
        monkeypatch.setattr(owner, name, failing)
    if point == 'tag':
        patch(GitWorkspace, 'tag')
    elif point in ('write', 'partial', 'delete'):
        patch(GitWorkspace, '_write_mechanical', 'after' if point == 'delete' else 'before')
    elif point == 'commit':
        patch(GitWorkspace, 'execute')
    else:
        import my_harness.storage.phases as module
        patch(module, 'settle')
    with pytest.raises((RuntimeError, JournalError), match='synthetic'):
        world.run()
    assert world.repository.get_job(job.id).status == 'RECOVERY_REQUIRED'
    intent = world.get(pid)['operations'][-1]['request']['commit_intent']
    confirm(world, job)
    detail = world.get(pid)
    resumed = world.phases.submit_close(world.context, pid, detail['version'], key=world.key(), versions=VERSIONS,
        binding_sha256=detail['ready']['binding_sha256'], reason='Resume exact closure', ttl_seconds=3600,
        git=world.ports.writer(world.context, VERSIONS))
    world.run()
    assert world.repository.get_run(resumed.run_id).status == 'COMMITTED'
    assert head(world) == json.loads(intent)['expected_commit']
    assert git(world.context.root, 'rev-list', '--count', previous + '..HEAD') == '1'
    assert git(world.context.root, 'rev-parse', 'refs/tags/p001') == previous
    assert world.get(pid)['operations'][-1]['request']['commit_intent'] == intent
    with Session(world.repository.engine) as session:
        assert len(session.scalars(select(PhaseRow).where(PhaseRow.code == 'P002')).all()) == 1


@pytest.mark.parametrize('kind', ['state', 'base'])
def test_state_budgets_require_reconciliation_without_agent(unified, kind):
    world = unified
    state = '# Estado\n\n## Base acumulada\n\n' + ('é' * 6200 if kind == 'base' else 'compacta')
    state += '\n\n## Fase activa\n\n' + ('é' * 13000 if kind == 'state' else 'activa')
    world.context.path('docs/STATE.md').write_text(state)
    git(world.context.root, 'commit', '-qam', 'oversized STATE')
    pid = world.create_v2()
    world.accept()
    before = list(world.ports.roles())
    _, result = world.check(pid)
    assert result['status'] == 'NEEDS_RECONCILIATION'
    assert world.ports.roles() == before


def test_plan_after_closure_is_confirmed_document_commit_and_definition_version(unified):
    world = unified
    pid = ready(world)
    queue(world, pid)
    world.run()
    following = world.phases.by_code(str(world.context.root), 'P002')
    plans = PhasePlanRepository(world.repository, following, PLAN_P002)
    writer = world.ports.writer(world.context, VERSIONS)
    shown = plans.preview(world.context, writer)
    previous = head(world)
    assert world.get(following)['definition']['tasks'] == []
    job = plans.submit(world.context, key=world.key(), versions=VERSIONS, preview_sha256=shown['preview_sha256'],
        reason='Confirmed synthetic plan', confirmed=True, git=writer, source='content', changes=None)
    world.run()
    detail = world.get(following)
    assert world.repository.get_run(job.run_id).status == 'COMMITTED'
    assert git(world.context.root, 'rev-parse', 'HEAD^') == previous
    assert detail['definition']['tasks'] == ['P002-T001'] and detail['definition_number'] == 2
    assert detail['documents']['drift'] == []
    assert '| Archivo |' in world.context.path('docs/ROADMAP.md').read_text()


def test_abandon_archives_without_ready_and_does_not_create_tag(unified):
    world = unified
    pid = world.create_v2()
    job = world.phases.abandon(pid, world.get(pid)['version'], reason='Synthetic abandonment', context=world.context,
                              git=world.ports.writer(world.context, VERSIONS), key=world.key(), versions=VERSIONS)
    world.run()
    assert world.get(pid)['status'] == 'ABANDONED'
    assert world.repository.get_run(job.run_id).status == 'COMMITTED'
    assert git(world.context.root, 'tag', '--list') == ''
    assert 'ABANDONED' in world.context.path('docs/archive/phase-001/REVIEW.md').read_text()


def test_final_phase_archives_without_creating_another_phase(unified):
    world = unified
    road = world.context.path('docs/ROADMAP.md')
    road.write_text(road.read_text().split('## P002')[0])
    git(world.context.root, 'commit', '-qam', 'final phase')
    pid = ready(world)
    detail = world.get(pid)
    world.phases.submit_close(world.context, pid, detail['version'], key=world.key(), versions=VERSIONS,
        binding_sha256=detail['ready']['binding_sha256'], reason='Final phase', ttl_seconds=3600,
        git=world.ports.writer(world.context, VERSIONS), tag_kind='annotated')
    world.run()
    assert git(world.context.root, 'cat-file', '-t', 'refs/tags/p001') == 'tag'
    assert world.context.path('docs/NEXT_STEPS.md').read_text().startswith('# Sin fase activa')
    assert len(world.phases.list(str(world.context.root))) == 1
    with pytest.raises(Conflict, match='retired'):
        TransitionRepository(world.repository).preview(world.context, pid, world.ports.writer(world.context, VERSIONS))


@pytest.mark.parametrize('source', ['text', 'proposal'])
def test_http_closure_and_confirmed_plan_use_the_current_protocol(unified, tmp_path, source):
    world = unified
    pid = ready(world)
    from test_managed_api import config
    with client(str(world.repository.engine.url), tmp_path, config(world.context, world.ports, supervisor=False)) as http:
        detail = world.get(pid)
        body = {'action': 'close', 'expected_version': detail['version'],
                'binding_sha256': detail['ready']['binding_sha256'], 'reason': 'HTTP closure', 'confirmed': True}
        response = http.post(f'/api/managed/phases/{pid}/actions', json=body, headers={'Idempotency-Key': 'http-close'})
        assert response.status_code == 202, response.text
        # This test's runtime starts no providers or background supervisor.
        world.run()
        closed = http.get(f'/api/managed/phases/{pid}').json()
        assert closed['status'] == 'CLOSED' and closed['closure']['archive'] == 'docs/archive/phase-001'
        assert closed['closure']['archive_altered'] == [] and closed['closure']['changed'] is None
        following = world.phases.by_code(str(world.context.root), 'P002')
        if source == 'proposal':
            from test_definition import planning_answer
            base = '/api/managed/projects/synthetic/planning'
            created = http.post(base, json={'kind': 'phase_planning', 'title': 'Plan de P002', 'phase_id': following},
                                headers={'Idempotency-Key': 'plan-conversation'})
            assert created.status_code == 201, created.text
            conversation = created.json()['id']
            world.script(planning_answer())
            sent = http.post(base + f'/{conversation}/messages', json={'expected_version': 0, 'text': 'Planifica P002'},
                             headers={'Idempotency-Key': 'plan-turn'})
            assert sent.status_code == 202, sent.text
            world.run()
            plan = http.get(base + f'/{conversation}').json()['proposals'][0]
            body = {'plan_proposal': {'conversation_id': conversation, 'proposal_id': plan['id'],
                                      'proposal_sha256': plan['proposal_sha256']}}
        else:
            body = {'next_steps': PLAN_P002}
        shown = http.post(f'/api/managed/phases/{following}/plan/preview', json=body)
        assert shown.status_code == 200, shown.text
        proposal = {**body, 'preview_sha256': shown.json()['preview_sha256'], 'reason': 'HTTP plan', 'confirmed': True}
        assert http.post(f'/api/managed/phases/{following}/plan', json=proposal).status_code == 422
        rejected = http.post(f'/api/managed/phases/{following}/plan', json={**proposal, 'preview_sha256': '0' * 64},
                             headers={'Idempotency-Key': 'stale-plan'})
        assert rejected.status_code == 409
        created = http.post(f'/api/managed/phases/{following}/plan', json=proposal,
                            headers={'Idempotency-Key': 'http-plan'})
        assert created.status_code == 202, created.text
        world.run()
        assert world.get(following)['definition']['tasks'] == ['P002-T001']


@pytest.mark.parametrize('previous', ['d088-1', 'd088-2', 'd088-3'])
def test_sealed_legacy_transition_recovers_with_layout_version_upgrade(unified, monkeypatch, previous):
    world = unified
    pid = ready(world)
    from my_harness.storage import closure
    with monkeypatch.context() as legacy:
        legacy.setattr(closure, 'prepare', lambda *args: None)
        queue(world, pid)
        world.run()
    transitions = TransitionRepository(world.repository)
    writer = world.ports.writer(world.context, VERSIONS)
    older = {**VERSIONS, 'document_layout': previous}
    current = {**VERSIONS, 'document_layout': DOCUMENT_LAYOUT}
    seen = []
    def factory(context, versions):
        seen.append(versions)
        return writer
    world.worker.commit_factory = factory
    original = GitWorkspace._write_mechanical
    with monkeypatch.context() as legacy:
        legacy.setattr(TransitionRepository, '_retired', lambda self: None)
        shown = transitions.preview(world.context, pid, writer, PLAN_P002)
        job = transitions.submit(world.context, pid, shown['expected_version'], key=world.key(), versions=older,
            preview_sha256=shown['preview_sha256'], reason='Frozen legacy transition', confirmed=True,
            git=writer, next_steps=PLAN_P002)
        def fail(*args):
            raise RuntimeError('synthetic crash')
        legacy.setattr(GitWorkspace, '_write_mechanical', fail)
        with pytest.raises(RuntimeError, match='synthetic'):
            world.run()
    confirm(world, job)
    assert GitWorkspace._write_mechanical is original
    shown = transitions.preview(world.context, pid, writer)
    resumed = transitions.submit(world.context, pid, shown['expected_version'], key=world.key(), versions=current,
        preview_sha256=shown['preview_sha256'], reason='Resume frozen intent', confirmed=True,
        git=writer, resume_operation_id=shown['resume_operation_id'])
    world.run()
    assert world.repository.get_run(resumed.run_id).status == 'COMMITTED'
    assert json.loads(world.repository.get_run(resumed.run_id).versions_json) == older
    assert seen[-1] == current


def test_active_empty_phase_accepts_its_conversation_plan(unified):
    world = unified
    pid = ready(world)
    queue(world, pid)
    world.run()
    following = world.phases.by_code(str(world.context.root), 'P002')
    from my_harness.storage.planning import PlanningRepository
    from test_definition import planning_answer
    planning = PlanningRepository(world.repository)
    cid = planning.create(world.context, kind='phase_planning', title='Plan active P002', phase_id=following)
    world.script(planning_answer())
    turn = planning.submit_message(world.context, cid, planning.get(cid)['version'], key=world.key(),
                                   versions=VERSIONS, text='Planifica la fase activa P002')
    world.run()
    assert planning.snapshot(turn.run_id)['context']['next']['code'] == 'P002'
    frozen = planning.snapshot(turn.run_id)['context']
    assert frozen['phase']['status'] == 'ACTIVE'
    assert {'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', 'docs/DDBB-DIAGRAM.md'} <= {
        doc['path'] for doc in frozen['documents']}
    request = world.repository.get_run(turn.run_id).history.attempts[-1].request
    assert 'ACTIVE phase without tasks left by unified closure' in request.prompt
    assert 'phase transition separately' not in request.prompt
    proposal = planning.get(cid)['proposals'][0]
    reference = {'conversation_id': cid, 'proposal_id': proposal['id'], 'proposal_sha256': proposal['proposal_sha256']}
    plans = PhasePlanRepository(world.repository, following, plan_proposal=reference)
    writer = world.ports.writer(world.context, VERSIONS)
    shown = plans.preview(world.context, writer)
    plans.submit(world.context, key=world.key(), versions=VERSIONS, preview_sha256=shown['preview_sha256'],
        reason='Confirm the exact conversation plan', confirmed=True, git=writer, source='content', changes=None)
    assert planning.get(cid)['proposals'][0]['status'] == 'ACCEPTED'
    world.run()
    assert world.get(following)['definition']['tasks'] == ['P002-T001']


# --- P010-T005: evidence of a closed phase -------------------------------------------------------


def final_roadmap(world):
    road = world.context.path('docs/ROADMAP.md')
    road.write_text(road.read_text().split('## P002')[0])
    git(world.context.root, 'commit', '-qam', 'final phase')


def drifted(world):
    return sorted(d['path'] for d in DocumentsRepository(world.repository).status(world.context)['documents']
                  if d['drift'])


def test_open_phase_has_no_closure_and_keeps_its_guards(unified):
    world = unified
    pid = ready(world)
    detail = world.get(pid)
    assert detail['closure'] is None and detail['ready'] is not None and 'close' in detail['actions']
    world.context.path('docs/STATE.md').write_text(STATE + '\nCambio sin confirmar.\n')
    detail = world.get(pid)
    assert detail['closure'] is None and detail['documents']['drift'] == ['docs/STATE.md']
    assert 'documents changed since READY' in detail['ready']['stale_reasons'] and 'close' not in detail['actions']
    assert drifted(world) == ['docs/STATE.md']


def test_closed_phase_without_successor_separates_renewal_from_real_drift(unified):
    world = unified
    final_roadmap(world)
    pid = ready(world)
    ready_view = world.get(pid)['ready']
    queue(world, pid)
    world.run()
    detail = world.get(pid)
    closure = detail['closure']
    assert detail['status'] == 'CLOSED' and detail['successor'] is None and detail['ready'] is None
    assert closure['commit'] == head(world) and closure['archive'] == 'docs/archive/phase-001'
    assert closure['binding']['binding_sha256'] == ready_view['binding_sha256']
    assert closure['binding']['head'] == ready_view['binding']['head'] and closure['reason'] == 'Synthetic closure'
    assert closure['check']['verdict'] == 'READY' and closure['check']['operation_id'] == ready_view['operation_id']
    assert closure['tag']['status'] == 'created'
    # Renewing STATE/NEXT_STEPS/ROADMAP/DECISIONS at closure is the expected difference, not a check failure.
    assert detail['documents']['drift'] == closure['renewed'] and 'docs/STATE.md' in closure['renewed']
    assert closure['changed'] == [] and closure['archive_altered'] == [] and drifted(world) == []
    assert 'docs/archive/phase-001/STATE.md' in closure['archive_files']
    assert detail['documents']['baseline'] == ready_view['binding']['documents']  # the historical base does not change
    # A confirmed edit after the closure is expected as well.
    roadmap = world.context.path('docs/ROADMAP.md').read_text() + '\nNota posterior al cierre.\n'
    queue_edit(world, changes=[{'path': 'docs/ROADMAP.md', 'content': roadmap}])
    world.run()
    closure = world.get(pid)['closure']
    assert closure['changed'] == [] and 'docs/ROADMAP.md' in closure['renewed'] and drifted(world) == []
    # An external change to a live document or to the archive is real drift and is shown.
    world.context.path('docs/NEXT_STEPS.md').write_text('# Editado fuera del harness\n')
    world.context.path('docs/archive/phase-001/SUMMARY.md').write_text('# Alterado\n')
    world.context.path('docs/archive/phase-001/STATE.md').unlink()
    closure = world.get(pid)['closure']
    assert closure['changed'] == ['docs/NEXT_STEPS.md'] and drifted(world) == ['docs/NEXT_STEPS.md']
    assert closure['archive_altered'] == ['docs/archive/phase-001/STATE.md', 'docs/archive/phase-001/SUMMARY.md']
    assert world.get(pid)['status'] == 'CLOSED' and world.get(pid)['actions'] == []


def test_closed_phase_with_successor_leaves_live_documents_to_it(unified):
    world = unified
    pid = ready(world)
    queue(world, pid)
    world.run()
    detail = world.get(pid)
    assert detail['successor'] == 'P002' and detail['closure']['changed'] is None
    assert detail['closure']['renewed'] and detail['closure']['archive_altered'] == []
    world.context.path('docs/STATE.md').write_text(STATE)
    assert world.get(pid)['closure']['changed'] is None  # the live drift belongs to P002
    assert drifted(world) == ['docs/STATE.md']


def test_abandoned_phase_shows_its_closure_without_check(unified):
    world = unified
    pid = world.create_v2()
    world.phases.abandon(pid, world.get(pid)['version'], reason='Synthetic abandonment', context=world.context,
                         git=world.ports.writer(world.context, VERSIONS), key=world.key(), versions=VERSIONS)
    world.run()
    closure = world.get(pid)['closure']
    assert closure['status'] == 'ABANDONED' and closure['check'] is None and closure['tag'] is None
    assert closure['archive'] == 'docs/archive/phase-001' and closure['archive_altered'] == []
    assert closure['binding']['binding_sha256'] and closure['reason'] == 'Synthetic abandonment'
