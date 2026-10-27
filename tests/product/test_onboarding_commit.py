"""P008-T015: onboarding and recovery with synthetic data, without running the project's tools."""
from dataclasses import replace
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.commit import CommitIntent
from my_harness.core.engine.definition import required_documents, definition_layout
from my_harness.services.local_config import _profile
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PhaseRow, ProjectImportRow
from my_harness.storage.onboarding_commit import OnboardingRepository
from onboarding_helpers import checkout_state
from test_onboarding_conversation import World, DRAFTS, world  # noqa: F401
from onboarding_helpers import answer
from test_managed_api import VERSIONS, Ports, client
from test_project_onboarding import DJANGO, TYPESCRIPT, checkout, git


def ready(world, replacements=None):
    cid = world.create()
    # The selected composition is explicit operator authority, never a profile installed by the agent.
    from my_harness.adapters.project_onboarding import read_inventory
    proposal = read_inventory(world.context.root)['profile_proposal']
    name, profile = next(iter(proposal['profiles'].items()))
    world.context = replace(world.context, profile=_profile(name, profile))
    drafts = {**DRAFTS, 'docs/ROADMAP.md': '# Roadmap\n\n## P001 — Continuidad\n\n'
              '**Objetivo:** Documentar la base existente.\n\n**Criterios de salida:**\n- Base revisada.\n',
              **(replacements or {})}
    world.turn(cid, answer(drafts))
    world.apply_all(cid)
    return cid


def preview(world, cid):
    return OnboardingRepository(world.repo).preview(world.context, cid, VERSIONS, world.writer)


def confirm(world, cid, shown=None, key=None, **overrides):
    shown = shown or preview(world, cid)
    args = dict(key=key or world.key(), preview_sha256=shown['preview_sha256'], reason='Synthetic review',
        confirmed=True, profile_sha256=shown['profile_sha256'], resume_operation_id=shown['resume_operation_id'],
        expected_version=shown['expected_version'])
    return OnboardingRepository(world.repo).submit(world.context, cid, VERSIONS, world.writer,
                                                  **{**args, **overrides})


@pytest.mark.parametrize('files', [DJANGO, TYPESCRIPT])
def test_confirm_one_documentary_commit_preserves_code_and_adopts_p001(migrated_database, tmp_path, files):
    engine = make_engine(migrated_database[0])
    world = World(checkout(tmp_path / 'project', {**files, 'AGENTS.md': '# Previous rules\n',
                                              'CLAUDE.md': '# Previous Claude\n'}), engine)
    before = {p: world.context.path(p).read_bytes() for p in (*files, 'AGENTS.md', 'CLAUDE.md')}
    cid = ready(world, {'README.md': '# Reviewed introduction\n'})
    saved = checkout_state(world.context.root)
    shown = preview(world, cid)
    assert shown == preview(world, cid) and checkout_state(world.context.root) == saved
    assert shown['flow'] == 'onboarding' and shown['phase']['code'] == 'P001'
    assert shown['profile']['name'] == world.context.profile.name
    assert shown['profile_proposal']['requires_confirmation']
    expected_originals = {'AGENTS.md', 'CLAUDE.md'} | ({'README.md'} if 'README.md' in files else set())
    assert {p['source'] for p in shown['preserved']} == expected_originals
    job = confirm(world, cid, shown, key='onboard')
    assert world.view(cid)['created'] and not world.view(cid)['actions']
    assert world.worker.run_once().status == 'DONE'
    assert confirm(world, cid, shown, key='onboard').id == job.id
    assert git(world.context.root, 'rev-list', '--count', 'HEAD') == '2'
    assert git(world.context.root, 'log', '-1', '--format=%s') == 'docs: incorporar al control del harness'
    assert git(world.context.root, 'status', '--porcelain') == ''
    for path, content in before.items():
        if path in {p['source'] for p in shown['preserved']}:
            assert world.context.path('docs/archive/phase-000/onboarding-originals/' + path).read_bytes() == content
        else:
            assert world.context.path(path).read_bytes() == content
    assert all(world.context.path(path).is_file() for path in required_documents(definition_layout(world.context)))
    archive = world.context.path('docs/archive/phase-000')
    assert json.loads((archive / 'INVENTORY.json').read_text())['head'] == shown['head']
    assert 'P001 ACTIVE' in (archive / 'SUMMARY.md').read_text()
    with Session(engine) as session:
        phase = session.scalar(select(PhaseRow))
        assert phase.code == 'P001' and phase.status == 'ACTIVE' and phase.documents == shown['baseline']
        assert session.scalar(select(ProjectImportRow)).decision['profile_sha256'] == shown['profile_sha256']
    again = preview(world, cid)
    assert again['already_imported'] and not again['documents'] and not again['mechanical']
    with pytest.raises(Conflict, match='no changes'):
        confirm(world, cid, again)
    assert world.ports.roles() == ['definition']  # The commit invokes no agent or project commands.
    engine.dispose()


@pytest.mark.parametrize('point', ['before', 'write', 'commit', 'register'])
def test_crash_reconciles_same_intent_commit_and_phase(world, monkeypatch, point):
    cid = ready(world)
    job = confirm(world, cid)
    with Session(world.engine) as session:
        sealed = session.scalar(select(ProjectImportRow)).intent
    intent = CommitIntent.from_json(sealed)
    if point == 'register':
        def fail(*args):
            raise RuntimeError('synthetic crash')
        monkeypatch.setattr(world.repo, 'finish', fail)
    else:
        name = '_write_mechanical' if point == 'write' else 'execute_documents'
        original = getattr(world.writer, name)
        def fail(*args):
            if point != 'before':
                original(*args)
            raise RuntimeError('synthetic crash')
        monkeypatch.setattr(world.writer, name, fail)
    with pytest.raises(RuntimeError, match='synthetic crash'):
        world.worker.run_once()
    assert world.repo.get_job(job.id).status == 'RECOVERY_REQUIRED'
    world.repo.confirm_stopped(job.id, owner_token=world.repo.get_job(job.id).owner_token,
        expected_version=world.repo.get_run(job.run_id).version, reason='Synthetic writer stopped')
    monkeypatch.undo()
    resumed = confirm(world, cid)
    assert resumed.run_id == job.run_id
    assert world.worker.run_once().status == 'DONE'
    assert git(world.context.root, 'rev-parse', 'HEAD') == intent.expected_commit
    assert git(world.context.root, 'rev-list', '--count', 'HEAD') == '2'
    with Session(world.engine) as session:
        assert session.scalar(select(ProjectImportRow)).intent == sealed
        assert len(session.scalars(select(PhaseRow)).all()) == 1


def test_exact_profile_confirmation_and_stale_composition_are_required(world):
    cid = ready(world)
    shown = preview(world, cid)
    for value in (None, '0' * 64):
        with pytest.raises(Conflict, match='profile hash'):
            confirm(world, cid, shown, profile_sha256=value)
    world.context = replace(world.context, profile=replace(world.context.profile, executor_instructions='Edited'))
    with pytest.raises(Conflict, match='profile hash|preview changed'):
        confirm(world, cid, shown)
    assert OnboardingRepository(world.repo).get(world.context.root) is None


@pytest.mark.parametrize('change', ['dirty', 'staged', 'untracked', 'head', 'draft'])
def test_stale_base_or_drafts_refuse_without_writes(world, change):
    cid = ready(world)
    shown = preview(world, cid)
    if change == 'draft':
        world.planning.edit_draft(world.context, cid, world.view(cid)['version'], path='README.md',
                                  content='# Edited\n', base_sha256=None, writer=None)
    elif change == 'untracked':
        world.context.path('external.txt').write_text('external\n')
    else:
        world.context.path('manage.py').write_text('# Changed\n')
        if change in ('staged', 'head'):
            git(world.context.root, 'add', 'manage.py')
        if change == 'head':
            git(world.context.root, 'commit', '-qm', 'Later HEAD')
    before = checkout_state(world.context.root)
    with pytest.raises(Conflict):
        confirm(world, cid, shown)
    assert checkout_state(world.context.root) == before
    assert OnboardingRepository(world.repo).get(world.context.root) is None


def test_questions_missing_documents_limits_and_phase_block(world):
    cid = ready(world)
    world.turn(cid, answer({}, questions=[{'text': '¿Continuidad?', 'blocking': True}]))
    with pytest.raises(Conflict, match='Blocking questions'):
        preview(world, cid)
    q = world.view(cid)['questions'][0]
    world.planning.defer(cid, world.view(cid)['version'], question_id=q['id'], reason='Plan posterior')
    assert preview(world, cid)['warnings']
    diagram = world.area(cid) / 'docs/DDBB-DIAGRAM.md'
    diagram.unlink()
    with pytest.raises(Conflict, match='Required documents'):
        preview(world, cid)
    diagram.write_text(DRAFTS['docs/DDBB-DIAGRAM.md'])
    (world.area(cid) / 'AGENTS.md').write_text('# Rule\n' * 61)
    with pytest.raises(Conflict, match='60 lines'):
        preview(world, cid)


def test_checkout_drift_after_confirmation_prevents_adoption(world):
    cid = ready(world)
    confirm(world, cid)
    world.context.path('manage.py').write_text('# External change\n')
    assert world.worker.run_once().status == 'DONE'
    assert OnboardingRepository(world.repo).get(world.context.root)['status'] == 'INTERRUPTED'
    assert git(world.context.root, 'rev-list', '--count', 'HEAD') == '1'
    assert world.context.path('manage.py').read_text() == '# External change\n'
    with pytest.raises(Conflict, match='already confirmed'):
        world.create()


def test_local_git_filters_are_rejected_without_executing_them(world):
    cid = ready(world)
    git(world.context.root, 'config', 'filter.synthetic.clean', 'false')
    with pytest.raises(Conflict, match='Git filters'):
        preview(world, cid)


def test_archive_collision_never_overwrites_existing_history(world):
    path = world.context.path('docs/archive/phase-000/INVENTORY.json')
    path.parent.mkdir(parents=True)
    path.write_text('{"previous": true}\n')
    git(world.context.root, 'add', '.')
    git(world.context.root, 'commit', '-qm', 'Existing synthetic archive')
    cid = ready(world)
    before = checkout_state(world.context.root)
    with pytest.raises(Conflict, match='destinations conflict'):
        preview(world, cid)
    assert checkout_state(world.context.root) == before


def test_ignored_destinations_refuse_before_writing(world):
    world.context.path('.gitignore').write_text('docs/\n')
    git(world.context.root, 'add', '.gitignore')
    git(world.context.root, 'commit', '-qm', 'Synthetic ignored docs')
    cid = ready(world)
    with pytest.raises(Conflict, match='ignored by Git'):
        preview(world, cid)
    assert not world.context.path('docs').exists()


def test_unreplaced_non_utf8_readme_is_preserved(world):
    world.context.path('README.md').write_bytes(b'\xffSynthetic original\n')
    git(world.context.root, 'add', 'README.md')
    git(world.context.root, 'commit', '-qm', 'Synthetic original bytes')
    cid = ready(world)
    shown = preview(world, cid)
    assert not any(d['path'] == 'README.md' for d in shown['documents'])
    confirm(world, cid, shown)
    assert world.worker.run_once().status == 'DONE'
    assert world.context.path('README.md').read_bytes() == b'\xffSynthetic original\n'


def test_wrong_initial_phase_and_non_document_paths_are_refused(world):
    cid = ready(world, {path: DRAFTS[path].replace('P001', 'P002') for path in
                       ('docs/STATE.md', 'docs/NEXT_STEPS.md')})
    (world.area(cid) / 'docs/ROADMAP.md').write_text('# Roadmap\n\n## P002 — Work\n\n'
        '**Objetivo:** Work.\n\n**Criterios de salida:**\n- Work done.\n')
    with pytest.raises(Conflict, match='adopt P001'):
        preview(world, cid)
    (world.area(cid) / 'manage.py').write_text('# Illegal\n')
    with pytest.raises(Conflict, match='foreign entries'):
        preview(world, cid)


def test_readme_is_kept_without_replacement_and_git_transformations_block(world):
    # The original README has CRLF; attributes must not silently normalize its archived bytes.
    readme = world.context.path('README.md')
    readme.write_bytes(b'# Original\r\n')
    git(world.context.root, 'add', '.')
    git(world.context.root, 'commit', '-qm', 'Synthetic original CRLF')
    cid = ready(world)
    assert not any(doc['path'] == 'README.md' for doc in preview(world, cid)['documents'])
    # No external filter: a built-in Git conversion also cannot alter the confirmed bytes.
    (world.context.root / '.git/info/attributes').write_text('*.md text eol=lf\n')
    world.planning.edit_draft(world.context, cid, world.view(cid)['version'], path='README.md',
        content='# New\r\n', base_sha256=None, writer=None)
    with pytest.raises(Conflict, match='transform|checkout changed'):
        preview(world, cid)
    assert readme.read_bytes() == b'# Original\r\n'


def test_first_task_uses_confirmed_profile_and_documents(world):
    from test_definition import DRAFTS as DEFINITION
    cid = ready(world, {'docs/NEXT_STEPS.md': DEFINITION['docs/NEXT_STEPS.md'].replace('test-runner check', 'pytest -q')})
    shown = preview(world, cid)
    confirm(world, cid, shown)
    assert world.worker.run_once().status == 'DONE'
    plan = world.context.path('docs/NEXT_STEPS.md').read_text()
    job = world.repo.submit(world.context, 'P001-T001', 'P001', plan, VERSIONS, key='first-task')

    def implement(context, request):
        assert context.profile.name == shown['profile']['name']
        context.path('app').mkdir()
        context.path('app/main.txt').write_text('implemented\n')
        return {'result': 'Synthetic implementation'}

    world.ports.agents.responses.extend([implement, {'task_id': 'P001-T001', 'verdict': 'ACCEPT',
        'findings': [], 'blocking_questions': [], 'scope_grants': []}])
    assert world.worker.run_once().status == 'DONE'
    run = world.repo.get_run(job.run_id)
    assert run.status == 'ACCEPTANCE_READY', run.history.stop
    world.repo.submit_commit(job.run_id, key='first-commit', expected_version=run.version)
    assert world.worker.run_once().status == 'DONE'
    assert world.repo.get_run(job.run_id).status == 'COMMITTED'


def test_http_confirmation_requires_profile_hash_and_is_idempotent(world, migrated_database, tmp_path):
    cid = ready(world)
    ports = Ports()
    config = ManagedConfig((ManagedProject('library', world.context, VERSIONS),), ports_factory=ports,
                           commit_factory=lambda c, v: world.writer, supervisor=False)
    with client(migrated_database[0], tmp_path, config) as http:
        base = f'/api/managed/projects/library/planning/{cid}/onboarding'
        response = http.post(base + '/preview', json={})
        assert response.status_code == 200, response.text
        shown = response.json()
        body = {'preview_sha256': shown['preview_sha256'], 'reason': 'Synthetic review', 'confirmed': True}
        headers = {'Idempotency-Key': 'http-confirm'}
        assert http.post(base + '/confirm', json=body, headers=headers).status_code == 422
        body['profile_sha256'] = shown['profile_sha256']
        response = http.post(base + '/confirm', json=body, headers=headers)
        assert response.status_code == 202, response.text
        assert world.worker.run_once().status == 'DONE'
        assert http.post(base + '/confirm', json=body, headers=headers).json()['id'] == response.json()['id']
        entry = http.get('/api/managed/projects/library/onboarding').json()
        assert entry['operation']['status'] == 'COMPLETED'
