"""T009: both intake paths via protected HTTP, real temporary Git/SQLite, fake reviewer/executor/tools."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from session_client import TestClient
from my_harness.core.engine.context import IntakeContext, ProjectContext
from my_harness.services.local_config import LocalComposer
from my_harness.services.managed import LocalSupervisor
from my_harness.services.profile_preparation import ProfilePreparation
from my_harness.storage.models import (ConfigurationOperationRow, ProjectBootstrapRow, ProjectImportRow,
    RegisteredProjectRow, PlanningProposalRow, ManagedRunRow, ConfigurationScopeRow)
from test_configuration import setup  # noqa: F401
from test_configuration_api import app_for, store, schedule
from test_project_registry import register, confirm as register_confirm, POLICY
from test_project_creation import select_root, request
from test_profile_proposals import candidate, DOCS, SOURCES, apply_documents, profile
from test_profile_preparation import technical, Executor
from test_definition import World, DRAFTS, answer
from test_managed_api import Ports
from test_project_onboarding import checkout, git

BASE = '/api/managed/projects/own'


@pytest.fixture(params=['definition', 'onboarding'])
def journey(request, setup, tmp_path, monkeypatch):
    kind = request.param
    repo, data, _ = setup
    data['registration'] = {'roots': [str(tmp_path)], 'bootstrap_enabled': True}
    data['git']['executable'] = shutil.which('git')
    monkeypatch.setattr(LocalComposer, '_resolve_agents', lambda self, agents: {
        role: replace(agent, cli_version='0.163.0', executable=(sys.executable,)) for role, agent in agents.items()})
    with TestClient(app_for(repo)) as http:
        store(http, data); schedule(http)
    app = app_for(repo)
    with TestClient(app) as http:
        http.headers['X-My-Harness'] = '1'
        runtime = app.state.runtime
        if kind == 'definition':
            parent = tmp_path / 'chosen parent'
            parent.mkdir()
            select_root(runtime.creation, parent)
            change = {'project_id': 'own', 'directory_name': 'own', 'root_version': 1, 'composition': None,
                      'policy': POLICY, 'work_language': 'en'}
            shown = http.post('/api/managed/project-creations/preview', json=change)
            assert shown.status_code == 200, shown.text
            confirmation = {'change': change, 'preview_sha256': shown.json()['preview_sha256'], 'trust_root': shown.json()['target']}
            response = http.post('/api/managed/project-creations/confirm', json=confirmation, headers={'Idempotency-Key': 'new-child'})
            assert response.status_code == 200, response.text
            assert http.post('/api/managed/project-creations/confirm', json=confirmation, headers={'Idempotency-Key': 'new-child'}).json() == response.json()
        else:
            root = tmp_path / 'existing own'
            checkout(root, SOURCES)
            _, response = register_confirm(http, register(root, project_id='own', composition=None))
            assert response.status_code == 200, response.text
        project = runtime.project('own')
        assert isinstance(project.context, IntakeContext)
        writer = runtime.config.commit_factory(project.context, dict(project.versions))
        ports = Ports()
        worker = LocalSupervisor(runtime.repository, lambda c, v: (ports.agents, ports.runner, ports._workspace(c)),
                                 commit_factory=runtime.config.commit_factory)
        world = World(project.context, runtime.repository, writer, worker, ports)
        monkeypatch.setattr('test_definition.VERSIONS', dict(project.versions))
        created = http.post(BASE + '/planning', json={'kind': kind, 'title': 'Synthetic own Go project',
            'brief': 'A synthetic Go calculator' if kind == 'definition' else None}, headers={'Idempotency-Key': 'conversation'})
        assert created.status_code == 201, created.text
        cid = created.json()['id']
        docs = {**DRAFTS, **DOCS, 'CLAUDE.md': '# Claude\n\nRead AGENTS.md.\n',
                'GEMINI.md': '# Gemini\n\nRead AGENTS.md.\n'}
        docs['docs/NEXT_STEPS.md'] = docs['docs/NEXT_STEPS.md'].replace('test-runner check', 'go test ./...')
        p = candidate(docs)
        p['preparation_plan'] = technical()
        p['preparation_plan']['write_paths'].append('.gitignore')
        # In B the initial files are preserved; execution may write these only after the documentary commit.
        p['preparation_plan']['write_paths'] += ['main.go']
        p['profile']['validations'][0]['junit'] = {'path': '.prepare/tests.xml', 'coverage': 'Synthetic Go packages'}
        job = http.post(BASE + f'/planning/{cid}/messages', json={'expected_version': created.json()['version'],
            'text': 'Propose complete documents and Go profile'}, headers={'Idempotency-Key': 'reviewer-turn'})
        assert job.status_code == 202, job.text
        ports.agents.responses.append({**answer(docs), 'profile': p})
        assert worker.run_once().status == 'DONE'
        apply_documents(world, cid)
        executor = Executor()
        effect = executor.effect
        executor.effect = lambda root: (effect(root), (root / '.gitignore').write_text('.prepare/\n'))
        monkeypatch.setattr(ProfilePreparation, '_agent', lambda self, project: executor)
        tool = tmp_path / 'synthetic-go'
        tool.write_text('#!' + sys.executable + '''
from pathlib import Path
root = Path.cwd()
if (root/'.prepare/fail').exists(): raise SystemExit(1)
(root/'.prepare/tests.xml').write_text('<testsuite><testcase name="synthetic-go"/></testsuite>')
''')
        tool.chmod(0o700)
        yield http, runtime, world, cid, kind, tool, executor, repo


def adopt(http, world, cid):
    p = profile(world, cid)
    base = BASE + f'/planning/{cid}/profile'
    body = {'proposal_id': p['id'], 'proposal_sha256': p['proposal_sha256'], 'expected_version': world.view(cid)['version']}
    shown = http.post(base + '/preview', json=body)
    assert shown.status_code == 200 and shown.json()['ready'], shown.text
    result = http.post(base + '/confirm', json={**body, 'preview_sha256': shown.json()['preview_sha256'],
        'confirmed': True, 'reason': 'Reviewed profile'}, headers={'Idempotency-Key': 'adopt-profile'})
    assert result.status_code == 200, result.text


def documents(journey):
    http, runtime, world, cid, kind, *_ = journey
    adopt(http, world, cid)
    base = BASE + f'/planning/{cid}'
    endpoint = '/accept' if kind == 'definition' else '/onboarding'
    shown = http.post(base + endpoint + '/preview', json={})
    assert shown.status_code == 200, shown.text
    shown = shown.json()
    assert shown['profile_proposal_sha256']
    if kind == 'definition':
        assert shown['ready'], shown['blockers']
    body = {'preview_sha256': shown['preview_sha256'], 'confirmed': True, 'reason': 'Reviewed documentary commit'}
    if kind == 'onboarding':
        body['profile_sha256'] = shown['profile_sha256']
    confirm_path = base + endpoint + ('/confirm' if kind == 'onboarding' else '')
    result = http.post(confirm_path, json=body, headers={'Idempotency-Key': 'documentary'})
    assert result.status_code == 202, result.text
    assert world.worker.run_once().status == 'DONE'
    replay = http.post(confirm_path, json=body, headers={'Idempotency-Key': 'documentary'})
    assert replay.status_code == 202 and replay.json()['run_id'] == result.json()['run_id'], replay.text
    with Session(runtime.engine) as session:
        row = session.scalar(select(ProjectBootstrapRow if kind == 'definition' else ProjectImportRow))
        assert row.status == 'COMPLETED', row.result
        assert row.preview['profile_proposal_sha256']
    return result.json()


def save_profile(journey):
    http, runtime, world, cid, kind, tool, *_ = journey
    read = http.get(BASE + '/configuration')
    assert read.status_code == 200, read.text
    state = read.json()
    form = state['form']
    form['commands']['executables']['go'] = str(tool)
    body = {'form': form, 'validated': True, 'expected_version': state['version'], 'base_sha256': state['working_sha256'],
        'active_sha256': None, 'reason': 'Reviewed private tool paths'}
    runtime.project_configuration.candidate('own', form=form)
    shown = http.post(BASE + '/configuration/preview', json=body)
    assert shown.status_code == 200, shown.text
    confirm = {**body, 'preview_sha256': shown.json()['sha256']}
    result = http.post(BASE + '/configuration/save', json=confirm, headers={'Idempotency-Key': 'profile-save'})
    assert result.status_code == 200, result.text
    assert http.post(BASE + '/configuration/save', json=confirm, headers={'Idempotency-Key': 'profile-save'}).json() == result.json()
    return http.get(BASE + '/configuration').json()


def prepare(journey):
    http, runtime, *_ = journey
    state = http.get(BASE + '/configuration').json()
    body = {'contract': 'project-profile-preparation-1', 'expected_version': 1, 'mode': 'offline',
        'configuration_revision': state['saved']['revision'], 'configuration_sha256': state['saved']['sha256'],
        'proposal_id': state['proposal_id'], 'proposal_sha256': state['proposal_sha256']}
    shown = http.post(BASE + '/preparation/preview', json=body)
    assert shown.status_code == 200, shown.text
    confirm = {'change': body, 'preview_sha256': shown.json()['preview_sha256'], 'confirmed': True, 'reason': 'Reviewed preparation'}
    result = http.post(BASE + '/preparation/confirm', json=confirm, headers={'Idempotency-Key': 'prepare'})
    assert result.status_code == 200, result.text
    runtime.preparation.run_once()
    operation = runtime.preparation.repository.read(result.json()['id'])
    assert operation['status'] == 'COMPLETED', operation['diagnostic']
    assert http.post(BASE + '/preparation/confirm', json=confirm, headers={'Idempotency-Key': 'prepare'}).json()['id'] == result.json()['id']
    return operation


def activation(http):
    state = http.get(BASE + '/configuration').json()
    body = {'revision': state['saved']['revision'], 'sha256': state['saved']['sha256'],
        'expected_version': state['version'], 'reason': 'Activate verified own profile'}
    shown = http.post(BASE + '/configuration/activation/preview', json=body)
    assert shown.status_code == 200, shown.text
    assert shown.json()['changes'][0]['sha256'] == state['saved']['sha256']
    assert 'project-config-1' in shown.json()['changes'][0]['diff']
    return {**body, 'preview_sha256': shown.json()['sha256']}


def test_complete_intake_save_prepare_activate_replay_and_restart(journey):
    http, runtime, world, cid, kind, tool, executor, repo = journey
    documents(journey)
    state = save_profile(journey)
    assert state['active'] is None and state['configuration_state'] == 'PREPARATION_REQUIRED'
    refused = http.post(BASE + '/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': 'Implement Go task'},
        headers={'Idempotency-Key': 'too-early'})
    assert refused.status_code == 409, refused.text
    operation = prepare(journey)
    assert len(executor.calls) == 1
    assert http.get(BASE).json()['configuration_state'] == 'READY_TO_ACTIVATE'
    assert isinstance(runtime.project('own').context, IntakeContext)
    body = activation(http)
    result = http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'activate-own'})
    assert result.status_code == 200, result.text
    replay = http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'activate-own'})
    assert replay.json() == result.json(), replay.text
    project = runtime.project('own')
    assert isinstance(project.context, ProjectContext)
    assert http.get(BASE).json()['configuration_state'] == 'ACTIVE'
    assert project.versions['project_configuration_sha256'] == body['sha256']
    # No model executes: admission only. The normal task uses the prepared profile and frozen refs.
    admitted = http.post(BASE + '/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': 'Implement Go task'},
        headers={'Idempotency-Key': 'first-task'})
    assert admitted.status_code == 202, admitted.text
    assert len(executor.calls) == 1
    with Session(runtime.engine) as session:
        run = session.get(ManagedRunRow, admitted.json()['run_id'])
        assert json.loads(run.versions_json)['project_environment_sha256']
        assert session.scalar(select(func.count()).select_from(RegisteredProjectRow)) == 1
    # A restart restores the same immutable project authority without running queued work.
    with TestClient(app_for(repo)) as restarted:
        assert restarted.get(BASE).json()['configuration_state'] == 'ACTIVE'
        assert isinstance(restarted.app.state.runtime.project('own').context, ProjectContext)
        assert restarted.app.state.runtime.worker is None


def test_profile_edit_versions_proposal_and_requires_documentary_adoption(journey):
    http, runtime, world, cid, *_ = journey
    old = profile(world, cid)
    candidate = json.loads(old['content'])['candidate']
    candidate['profile']['executor_instructions'] += ' Preserve the documented CLI.'
    body = {'proposal_id': old['id'], 'proposal_sha256': old['proposal_sha256'], 'expected_version': world.view(cid)['version'],
        'candidate': {'form': candidate}, 'reason': 'Reviewed instruction clarification'}
    base = BASE + f'/planning/{cid}/profile'
    result = http.post(base + '/edit', json=body, headers={'Idempotency-Key': 'edit-profile'})
    assert result.status_code == 200, result.text
    assert http.post(base + '/edit', json=body, headers={'Idempotency-Key': 'edit-profile'}).json() == result.json()
    assert next(p for p in world.view(cid)['proposals'] if p['id'] == old['id'])['content'] == old['content']
    assert next(p for p in world.view(cid)['proposals'] if p['id'] == old['id'])['status'] == 'SUPERSEDED'
    assert http.post(base + '/edit', json={**body, 'reason': 'Different'}, headers={'Idempotency-Key': 'edit-profile'}).status_code == 409
    documents(journey)
    assert http.post(base + '/edit', json=body, headers={'Idempotency-Key': 'edit-profile'}).json() == result.json()


@pytest.mark.parametrize('fault', ['document', 'head', 'tool', 'pending', 'external', 'profile', 'policy'])
def test_activation_rejects_stale_prepared_authority(journey, fault):
    http, runtime, world, cid, kind, tool, executor, repo = journey
    documents(journey); save_profile(journey); prepare(journey)
    body = activation(http)
    root = world.context.root
    if fault == 'document': (root / 'docs/ARCHITECTURE.md').write_text('Foreign document')
    elif fault == 'head':
        (root / 'app/main.go').write_text('Ordinary code changed after preparation')
        git(root, 'add', 'app/main.go'); git(root, 'commit', '-qm', 'Synthetic drift')
    elif fault == 'tool': tool.write_text(tool.read_text() + '\n# drift\n')
    elif fault == 'pending':
        from my_harness.storage.models import CheckoutLockRow
        # A foreign live/uncertain checkout owner blocks the activation barrier.
        with runtime.repository._write() as session:
            session.add(CheckoutLockRow(root=str(root), job_id=None,
                preparation_id=runtime.preparation.read('own')['operation']['id']))
    elif fault == 'external': (repo.directory / 'projects/own/project.toml').write_text('External bytes')
    elif fault in ('profile', 'policy'):
        state = http.get(BASE + '/configuration').json()
        changed = copy.deepcopy(state['form'])
        if fault == 'profile': changed['profile']['executor_instructions'] += ' drift'
        else: changed['policy']['max_revision_cycles'] = 2
        response = http.post(BASE + '/configuration/form', json={'form': changed})
        assert response.status_code == 409, response.text
        return
    refused = http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'stale-activation'})
    assert refused.status_code == 409, refused.text
    assert repo.read('project:own')['active'] is None
    assert isinstance(runtime.project('own').context, IntakeContext)


def test_saved_draft_preserves_active_authority_and_frozen_task_versions(journey):
    http, runtime, world, cid, kind, tool, executor, repo = journey
    documents(journey); save_profile(journey); prepare(journey)
    active = activation(http)
    result = http.post(BASE + '/configuration/activate', json=active, headers={'Idempotency-Key': 'activate-own'})
    assert result.status_code == 200, result.text
    state = http.get(BASE + '/configuration').json()
    changed = copy.deepcopy(state['form'])
    changed['commands']['max_timeout_seconds'] = 900
    body = {'form': changed, 'expected_version': state['version'], 'base_sha256': state['working_sha256'],
            'active_sha256': active['sha256'], 'reason': 'Save a later candidate without activating'}
    shown = http.post(BASE + '/configuration/preview', json=body)
    assert shown.status_code == 200, shown.text
    saved = http.post(BASE + '/configuration/save', json={**body, 'preview_sha256': shown.json()['sha256']},
                      headers={'Idempotency-Key': 'later-save'})
    assert saved.status_code == 200, saved.text
    admitted = http.post(BASE + '/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': 'Use active profile'},
                         headers={'Idempotency-Key': 'active-task'})
    assert admitted.status_code == 202, admitted.text
    with Session(runtime.engine) as session:
        run = session.get(ManagedRunRow, admitted.json()['run_id'])
        assert json.loads(run.versions_json)['project_configuration_sha256'] == active['sha256']
    assert repo.read('project:own')['active']['revision'] == 1
    assert repo.read('project:own')['saved']['revision'] == 2


def test_project_editor_rejects_csrf_origin_unknown_fields_and_reused_activation_key(journey):
    http, runtime, world, cid, *_ = journey
    documents(journey); save_profile(journey); prepare(journey)
    body = activation(http)
    assert http.post(BASE + '/configuration/activate', json=body, headers={
        'Origin': 'https://example.invalid', 'Idempotency-Key': 'wrong-origin'}).status_code == 403
    del http.headers['X-My-Harness']
    assert http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'no-csrf'}).status_code == 403
    http.headers['X-My-Harness'] = '1'
    assert http.post(BASE + '/configuration/activate', json={**body, 'prepared': True},
        headers={'Idempotency-Key': 'forged'}).status_code == 422
    result = http.post(BASE + '/configuration/activate', json=body, headers={'Idempotency-Key': 'exact-key'})
    assert result.status_code == 200, result.text
    conflict = http.post(BASE + '/configuration/activate', json={**body, 'reason': 'Different'},
        headers={'Idempotency-Key': 'exact-key'})
    assert conflict.status_code == 409


def test_immutable_authority_checked_for_owned_job_without_adopting_working_edits(journey):
    http, runtime, world, cid, kind, tool, executor, repo = journey
    documents(journey); save_profile(journey); prepare(journey)
    active = activation(http)
    assert http.post(BASE + '/configuration/activate', json=active, headers={'Idempotency-Key': 'activate-own'}).status_code == 200
    admitted = http.post(BASE + '/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': 'Frozen task'},
        headers={'Idempotency-Key': 'freeze-task'})
    assert admitted.status_code == 202, admitted.text
    claim = runtime.repository.claim(lease_seconds=30)
    assert claim is not None
    # An external working copy cannot inject new values into an already admitted job.
    (repo.directory / 'projects/own/project.toml').write_text('Foreign working copy')
    with runtime.repository._write() as session:
        runtime.repository._owned(session, claim)
    from my_harness.storage.configuration_files import ConfigurationFiles
    immutable = repo.directory.joinpath(*ConfigurationFiles.immutable('project:own', 1, active['sha256']))
    immutable.write_text('Foreign immutable authority')
    from my_harness.storage.managed import Conflict
    with pytest.raises(Conflict):
        with runtime.repository._write() as session:
            runtime.repository._owned(session, claim)


def test_manual_form_toml_roundtrip_rejects_incomplete_editor_shapes(journey):
    http, runtime, world, cid, *_ = journey
    proposal = profile(world, cid)
    original = json.loads(proposal['content'])['candidate']
    base = BASE + f'/planning/{cid}/profile/form'
    converted = http.post(base, json={'form': original, 'validated': False})
    assert converted.status_code == 200, converted.text
    assert http.post(base, json={'text': converted.json()['text'], 'validated': False}).json()['form'] == original
    assert http.post(base, json={'text': 'name = "incomplete"', 'validated': False}).status_code == 422
    adopt(http, world, cid)
    state = http.get(BASE + '/configuration').json()
    assert http.post(BASE + '/configuration/form', json={'form': state['form'], 'validated': False}).status_code == 200
    assert http.post(BASE + '/configuration/form', json={'text': 'format = "project-config-1"', 'validated': False}).status_code == 422
    assert runtime.project_configuration.repository.read('project:own')['saved'] is None
