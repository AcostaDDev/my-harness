"""Legacy conversion with synthetic TOML, temporary Git/SQLite and a fake executor."""
import copy
from pathlib import Path
import shutil
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from session_client import TestClient
from my_harness.api.app import create_app
from my_harness.services.local_config import LocalComposer, build
from my_harness.services.profile_preparation import ProfilePreparation
from my_harness.storage.configuration import ConfigurationConflict
from my_harness.storage.models import ConfigurationOperationRow, RegisteredProjectRow
from test_configuration import setup, dumps  # noqa: F401
from test_definition import DRAFTS
from test_project_onboarding import checkout
from test_profile_preparation import Executor

BASE = '/api/managed/configuration'


@pytest.fixture
def legacy_install(setup, tmp_path, monkeypatch):
    repo, data, _ = setup
    root = tmp_path / 'synthetic project'
    checkout(root, {**DRAFTS, 'AGENTS.md': '# Synthetic instructions\n', '.gitignore': '.prepare/\n', 'sample.txt': 'Synthetic\n'})
    profile = {'preparation': [], 'validations': [{'argv': ['python', '-c', 'print(1)'], 'timeout_seconds': 10}],
        'allowed_command_prefixes': [], 'protected_paths': ['docs/**', 'AGENTS.md'], 'sensitive_paths': ['.env*'],
        'data_model_paths': [], 'executor_instructions': 'Validate the synthetic project.'}
    data.update(format='local-config-8', profiles={'synthetic': profile},
        compositions={'own': {'profile': 'synthetic', 'executables': {'python': sys.executable},
                             'environment': {}, 'authorize_profile_commands': True}},
        projects=[{'id': 'own', 'root': str(root), 'repository_trusted': True, 'composition': 'own',
            'policy': {'planning_mode': 'deterministic', 'executor_mode': 'catalog',
                       'executor_models': ['synthetic'], 'executor_efforts': ['medium']}}])
    data['git']['executable'] = shutil.which('git')
    for agent in data['agents'].values():
        agent.update(executable=[sys.executable], cli_version='0.163.0')
    source = tmp_path / 'original.toml'
    source.write_text(dumps(data)); source.chmod(0o640)
    # Runtime discovery/preflight is already tested separately. Conversion itself must launch nothing.
    monkeypatch.setattr(LocalComposer, 'resolve_config', lambda self, config: config)
    executor = Executor(); executor.effect = lambda root: None
    monkeypatch.setattr(ProfilePreparation, '_agent', lambda self, project: executor)
    def app(source_path=source):
        return create_app(str(repo.managed.engine.url), configuration_dir=repo.directory,
                          state_dir=repo.state_dir, config_source=source_path)
    return repo, data, source, root, app, executor


def convert(http, source, key='import'):
    request = {'source': str(source), 'reason': 'Explicit legacy conversion'}
    preview = http.post(BASE + '/import/preview', json=request)
    assert preview.status_code == 200, preview.text
    body = {**request, 'preview_sha256': preview.json()['sha256']}
    saved = http.post(BASE + '/import/save', json=body, headers={'Idempotency-Key': key})
    assert saved.status_code == 200, saved.text
    assert http.post(BASE + '/import/save', json=body, headers={'Idempotency-Key': key}).json() == saved.json()
    return preview.json(), saved.json(), body


def test_import_drafts_replay_and_original_hashes_unchanged(legacy_install):
    repo, data, source, root, app, executor = legacy_install
    before = source.read_bytes(), source.stat().st_mode
    versions = build(data, source).projects[0].versions
    with TestClient(app()) as http:
        http.headers['X-My-Harness'] = '1'
        runtime = http.app.state.runtime
        preview, saved, body = convert(http, source)
        assert [c['status'] for c in preview['changes']] == ['VALIDATED', 'DRAFT']
        assert runtime.setup.state()['mode'] == 'READY' and runtime.setup.legacy
        assert runtime.project('own').versions == versions
        assert runtime.setup.repository.read('project:own')['active'] is None
        assert http.get('/api/managed/projects/own/configuration').json()['preparation']['prepared'] is False
        state = http.get(BASE).json()
        assert state['imported_projects'] == ['own']
        attempt = http.post(BASE + '/activation/preview', json={'references': state['activation_references'], 'reason': 'Try activation'})
        assert attempt.status_code == 409
        assert attempt.json()['detail']['code'] == 'configuration_draft_not_activatable'
    with TestClient(app()) as http:
        http.headers['X-My-Harness'] = '1'
        assert http.get(BASE).json()['mode'] == 'READY'
        assert http.post(BASE + '/import/save', json=body, headers={'Idempotency-Key': 'import'}).json() == saved
    assert (source.read_bytes(), source.stat().st_mode) == before
    assert build(data, source).projects[0].versions == versions
    assert executor.calls == []


def test_source_or_registry_change_invalidates_confirmation(legacy_install):
    repo, data, source, root, app, _ = legacy_install
    with TestClient(app()) as http:
        http.headers['X-My-Harness'] = '1'
        body = {'source': str(source), 'reason': 'CAS conversion'}
        shown = http.post(BASE + '/import/preview', json=body).json()
        source.write_text(dumps({**data, 'git': {**data['git'], 'author_name': 'Changed'}}))
        response = http.post(BASE + '/import/save', json={**body, 'preview_sha256': shown['sha256']},
                             headers={'Idempotency-Key': 'stale'})
        assert response.status_code == 409
        assert repo.read()['saved'] is None
        source.write_text(dumps(data))
        with repo.managed._write() as session:
            session.add(RegisteredProjectRow(id='own', root=str(root), version=1, status='ACTIVE',
                composition='own', profile='synthetic', row=data['projects'][0], row_sha256='a' * 64,
                trust={}, created_at=repo.managed._now(), updated_at=repo.managed._now()))
        assert http.post(BASE + '/import/preview', json=body).status_code == 409


def test_import_prepares_then_promotes_complete_set(legacy_install):
    repo, data, source, root, app, executor = legacy_install
    with TestClient(app()) as http:
        http.headers['X-My-Harness'] = '1'
        convert(http, source)
        base = '/api/managed/projects/own/configuration'
        current = http.post(base + '/edit-base', json={})
        assert current.status_code == 200, current.text
        form = current.json()['form']
        form['edit']['preparation_plan'].update(write_paths=['.prepare/**'], local_paths=['.prepare/**'],
            instructions='Validate the synthetic fixture without changing sources.')
        form['commands']['environment'] = {'HOME': str(root / '.prepare/home'), 'TMPDIR': str(root / '.prepare/tmp')}
        state = http.get(base).json()
        request = {'form': form, 'validated': True, 'expected_version': state['version'],
            'base_sha256': state['actual_sha256'], 'active_sha256': None, 'reason': 'Explicit preparation settings'}
        preview = http.post(base + '/preview', json=request)
        assert preview.status_code == 200, preview.text
        response = http.post(base + '/save', json={**request, 'preview_sha256': preview.json()['sha256']},
                             headers={'Idempotency-Key': 'profile'})
        assert response.status_code == 200, response.text
        state = http.get(base).json()
        body = {'contract': 'project-profile-preparation-1', 'expected_version': state['preparation']['project_version'],
            'configuration_revision': state['saved']['revision'], 'configuration_sha256': state['saved']['sha256'],
            'proposal_id': state['proposal_id'], 'proposal_sha256': state['proposal_sha256'], 'mode': 'offline'}
        shown = http.post('/api/managed/projects/own/preparation/preview', json=body)
        assert shown.status_code == 200, shown.text
        # Use the same public confirmation shape as all generic preparation operations.
        confirmed = http.post('/api/managed/projects/own/preparation/confirm', json={'change': body,
            'preview_sha256': shown.json()['preview_sha256'], 'confirmed': True,
            'reason': 'Explicit imported profile validation'}, headers={'Idempotency-Key': 'prepare'})
        assert confirmed.status_code == 200, confirmed.text
        runtime = http.app.state.runtime
        result = runtime.preparation.generic().run_once()
        assert result is not None
        state = http.get(base).json()
        assert state['preparation']['prepared'], state
        global_state = http.get(BASE).json()
        refs = global_state['activation_references']
        request = {'references': refs, 'reason': 'Activate prepared imported set'}
        shown = http.post(BASE + '/activation/preview', json=request)
        assert shown.status_code == 200, shown.text
        response = http.post(BASE + '/activate', json={**request, 'preview_sha256': shown.json()['sha256']},
                             headers={'Idempotency-Key': 'activate-import'})
        assert response.status_code == 200, response.text
        assert http.get(BASE).json()['mode'] == 'RESTART_REQUIRED'
    # Managed authority is selected explicitly on restart, with no original file as a second source.
    source.unlink()
    with TestClient(app(None)) as http:
        state = http.get(BASE).json()
        assert state['mode'] == 'READY', state
        assert state['legacy'] is False and state['active']['revision'] == 1
        runtime = http.app.state.runtime
        assert runtime.setup.repository.read('project:own')['active']['revision'] == 2
        assert runtime.project('own').versions['project_configuration'] == 'project-config-1'
        protected = root / 'AGENTS.md'
        original = protected.read_bytes()
        protected.write_bytes(original + b'Unconfirmed drift\n')
        assert http.get('/api/managed/projects/own/configuration').json()['configuration_state'] == 'PREPARATION_REQUIRED'
        protected.write_bytes(original)
    assert len(executor.calls) == 1


@pytest.mark.parametrize('version', range(1, 9))
def test_all_legacy_loaders_keep_hashes_and_import_only_explicitly(legacy_install, version):
    repo, data, source, root, app, executor = legacy_install
    data = copy.deepcopy(data)
    data['format'] = f'local-config-{version}'
    if version <= 3:
        data.pop('profiles')
        data['compositions']['own'].update(profile='typescript-web', executables={'node': sys.executable, 'npm': sys.executable})
    if version <= 2:
        data.pop('registration')
        composition = data.pop('compositions')['own']
        data['projects'][0].pop('composition')
        data['projects'][0].update(profile=composition.pop('profile'), commands=composition)
    if version == 1:
        reviewer, executor_data = data.pop('agents').values()
        data['providers'] = {'codex': {k: v for k, v in reviewer.items() if k not in ('provider', 'model', 'effort')},
                             'claude': {**{k: v for k, v in executor_data.items() if k != 'provider'}, 'cli_version': '2.1.304'}}
        data['projects'][0]['policy'] = {'executor_models': ['synthetic'], 'executor_efforts': ['medium'],
            'reviewer_model': 'synthetic', 'reviewer_effort': 'medium', 'planner_model': 'synthetic',
            'planner_effort': 'medium', 'planning_mode': 'deterministic'}
    source.write_text(dumps(data))
    original = source.read_bytes()
    before = build(data, source).projects[0].versions
    with TestClient(app()) as http:
        http.headers['X-My-Harness'] = '1'
        assert repo.read()['version'] == 0
        assert http.get(BASE).json()['legacy'] is True
        assert repo.read()['version'] == 0  # Reading or starting never converts.
        shown, saved, _ = convert(http, source)
        assert shown['legacy_import']['format'] == f'local-config-{version}'
        assert saved['status'] == 'SAVED'
        assert http.app.state.runtime.project('own').versions == before
    assert source.read_bytes() == original
    assert build(data, source).projects[0].versions == before
    assert executor.calls == []


@pytest.mark.parametrize('stage', ['intended', 'immutable_written', 'working_written', 'files_written', 'before_final_commit'])
def test_import_recovery_never_duplicates_registry_or_versions(legacy_install, stage):
    repo, data, source, root, app, executor = legacy_install
    with TestClient(app()) as http:
        runtime = http.app.state.runtime
        from my_harness.services.configuration_import import ConfigurationImport
        service = ConfigurationImport(runtime)
        shown = service.preview(str(source), 'Recoverable conversion')
        def crash(point):
            if point == stage:
                raise RuntimeError('Injected import crash')
        runtime.setup.repository.checkpoint = crash
        with pytest.raises(RuntimeError):
            service.save(str(source), 'Recoverable conversion', shown['sha256'], 'crash')
        with Session(repo.managed.engine) as session:
            operation_id = session.scalar(select(ConfigurationOperationRow.id).where(
                ConfigurationOperationRow.idempotency_key == 'crash'))
        recovery = runtime.setup.repository.recovery_preview(operation_id)
        with pytest.raises(ConfigurationConflict, match='writers_not_confirmed'):
            runtime.setup.repository.recover(operation_id, preview_sha256=recovery['sha256'])
        runtime.setup.repository.checkpoint = lambda stage: None
        result = runtime.setup.repository.recover(operation_id, preview_sha256=recovery['sha256'], writers_stopped=True)
        assert result['status'] == 'SAVED'
        assert service.save(str(source), 'Recoverable conversion', shown['sha256'], 'crash') == result
        with Session(repo.managed.engine) as session:
            assert len(list(session.scalars(select(RegisteredProjectRow)))) == 1
        assert repo.read()['saved']['revision'] == 1
    assert executor.calls == []
