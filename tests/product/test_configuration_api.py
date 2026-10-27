"""P013-T005: authenticated TestClient, synthetic files/SQLite and CLI probes only."""
import copy
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from session_client import TestClient
from fastapi.testclient import TestClient as AnonymousClient
from my_harness.api.app import create_app
from my_harness.services.managed_runtime import ManagedConfig
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.configuration import ConfigurationConflict
from my_harness.storage.models import ConfigurationOperationRow as Operation, ProjectCreationOperationRow
from test_configuration import setup, dumps  # noqa: F401
from test_cli_diagnostics import config as fake_cli, calls  # noqa: F401

BASE = '/api/managed/configuration'
LOCAL = {'X-My-Harness': '1'}


def app_for(repo, **kwargs):
    return create_app(str(repo.managed.engine.url), configuration_dir=repo.directory,
                      state_dir=repo.state_dir, **kwargs)


def request_for(state, data):
    return {'form': copy.deepcopy(data), 'validated': True, 'expected_version': state['version'],
            'base_sha256': state['actual_sha256'], 'active_sha256': state['active']['sha256'] if state['active'] else None,
            'reason': 'Synthetic initial setup'}


def store(http, data, key='save'):
    state = http.get(BASE).json()
    body = request_for(state, data)
    preview = http.post(BASE + '/preview', json=body, headers=LOCAL)
    assert preview.status_code == 200, preview.text
    response = http.post(BASE + '/save', json={**body, 'preview_sha256': preview.json()['sha256']},
                         headers={**LOCAL, 'Idempotency-Key': key})
    assert response.status_code == 200, response.text
    return response.json(), body, preview.json()['sha256']


def schedule(http):
    state = http.get(BASE).json()
    body = {'references': [{**{key: state['saved'][key] for key in ('scope', 'revision', 'sha256')},
                           'expected_version': state['version']}], 'reason': 'Explicit synthetic activation'}
    preview = http.post(BASE + '/activation/preview', json=body, headers=LOCAL)
    assert preview.status_code == 200, preview.text
    body['preview_sha256'] = preview.json()['sha256']
    result = http.post(BASE + '/activate', json=body, headers={**LOCAL, 'Idempotency-Key': 'activate'})
    assert result.status_code == 200, result.text
    assert http.post(BASE + '/activate', json=body, headers={**LOCAL, 'Idempotency-Key': 'activate'}).json() == result.json()
    return result.json()


def hold(repo, reserved=True):
    """Synthetic current work: a reserved project creation is a waiting reason of a live set (D238)."""
    with repo.managed._write() as session:
        row = session.get(ProjectCreationOperationRow, 'held')
        if row is None:
            now = repo.managed._now()
            session.add(ProjectCreationOperationRow(id='held', idempotency_key='held', request_sha256='0' * 64,
                version=1, project_id='held', directory_name='held', target='/nonexistent/held', reserved=reserved,
                authority={}, intent={}, intent_sha256='0' * 64, status='RECOVERY_REQUIRED', created_at=now, updated_at=now))
        else:
            row.reserved = reserved


def test_first_setup_separates_save_and_live_activation(setup, monkeypatch):
    repo, data, root = setup
    original = subprocess.Popen
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Passive setup launched a process'))
    first = app_for(repo)
    with TestClient(first) as http:
        assert http.get(BASE).json()['mode'] == 'UNCONFIGURED'
        public = http.get('/api/managed/supervisor').json()
        assert public['configuration_mode'] == 'UNCONFIGURED'
        assert not any(key in public for key in ('text', 'form', 'environment', 'state_dir'))
        refused = http.post('/api/managed/registry/preview', json={}, headers=LOCAL)
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'configuration_not_ready'
        saved, body, sha = store(http, data)
        assert saved['status'] == 'SAVED' and http.get(BASE).json()['active'] is None
        assert http.get(BASE).json()['text'] == dumps(data)
        assert http.get(BASE).json()['form'] == data
        assert http.post(BASE + '/save', json={**body, 'preview_sha256': sha},
                         headers={**LOCAL, 'Idempotency-Key': 'save'}).json() == saved
        # Activation preview and switch are the explicit steps that preflight the selected clients.
        monkeypatch.setattr(subprocess, 'Popen', original)
        operation = schedule(http)
        assert operation['result']['state'] == 'APPLY_PENDING'  # accepted for the idle boundary, here immediate
        state = http.get(BASE).json()
        assert state['mode'] == 'READY' and state['active']['revision'] == 1 and state['pending'] is None
        assert state['live_activation'] is None
        assert http.get('/api/managed/supervisor').json()['configuration_mode'] == 'READY'
        assert first.state.runtime.config.registrar.format == 'local-config-9'
        assert first.state.runtime.worker is None
        # The same process and session now reach domain validation; no restart or new key.
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 422
        assert http.get(BASE + '/operations/' + operation['id']).json() == operation
    second = app_for(repo)
    with TestClient(second) as http:
        state = http.get(BASE).json()
        assert state['mode'] == 'READY' and state['active']['revision'] == 1 and state['pending'] is None
        assert http.get('/api/managed/supervisor').json()['configuration_mode'] == 'READY'
        assert second.state.runtime.config.registrar.format == 'local-config-9'
        assert second.state.runtime.registry.registrar is not None  # T007 admits documentary intakes.
        assert second.state.runtime.projects == {} and second.state.runtime.worker is None
        # Valid global authority permits requests to reach their existing domain validation.
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 422
        assert http.get('/api/managed/projects').json() == []


def test_guards_cover_setup_and_openapi_before_any_detection(setup, monkeypatch):
    repo, _, _ = setup
    app = app_for(repo)
    monkeypatch.setattr('my_harness.services.configuration_setup.shutil.which',
                        lambda *a, **k: pytest.fail('Unauthenticated detection'))
    with AnonymousClient(app, base_url='http://127.0.0.1') as http:
        assert http.get(BASE).status_code == 401
        assert http.get('/openapi.json').status_code == 401
        assert http.post(BASE + '/detect', json={'path': '/usr/bin'}, headers=LOCAL).status_code == 401
        login = http.post('/api/session', json={'key': app.state.sessions.path.read_text()}, headers=LOCAL)
        assert login.status_code == 200
        assert http.post(BASE + '/detect', json={'path': '/usr/bin'}).status_code == 403
        for headers in ({**LOCAL, 'Origin': 'https://foreign.invalid'},
                        {**LOCAL, 'Host': 'foreign.invalid'}, {**LOCAL, 'Sec-Fetch-Site': 'cross-site'}):
            assert http.post(BASE + '/detect', json={'path': '/usr/bin'}, headers=headers).status_code == 403


def test_detection_uses_only_explicit_path_and_no_processes(setup, tmp_path, monkeypatch):
    repo, _, _ = setup
    binary = tmp_path / 'selected clients'
    binary.mkdir()
    (binary / 'codex').write_text('synthetic')
    (binary / 'codex').chmod(0o700)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Detection invoked CLI'))
    monkeypatch.setenv('UNRELATED_SECRET', 'never copy this')
    with TestClient(app_for(repo)) as http:
        result = http.post(BASE + '/detect', json={'path': str(binary)}, headers=LOCAL)
        assert result.status_code == 200
        assert result.json()['candidates'] == {'codex': str(binary / 'codex'), 'claude': None, 'git': None}
        assert 'never copy this' not in result.text
        for path in ('', 'relative', ':/usr/bin', '/usr/bin:relative'):
            assert http.post(BASE + '/detect', json={'path': path}, headers=LOCAL).status_code == 422


def test_explicit_preflight_keeps_d174_and_never_infers(setup, fake_cli):
    repo, data, _ = setup
    for role in ('reviewer', 'executor'):
        data['agents'][role].update(executable=list(fake_cli.executable),
                                   environment={**data['agents'][role]['environment'], **dict(fake_cli.environment)})
    with TestClient(app_for(repo)) as http:
        assert http.post(BASE + '/preview', json=request_for(http.get(BASE).json(), data), headers=LOCAL).status_code == 200
        assert calls(fake_cli) == []
        result = http.post(BASE + '/check-clients', json={'form': data}, headers=LOCAL)
        assert result.status_code == 200, result.text
        assert all(report['available'] for report in result.json()['reports'].values())
        assert result.json()['inference_performed'] is False
        assert result.json()['internal_effects_verified'] is False
        assert calls(fake_cli) == [['--version'], ['exec', '--help']] * 2
        assert http.get(BASE).json()['active'] is None


def test_invalid_draft_conflict_idempotency_and_localization(setup):
    repo, data, _ = setup
    with TestClient(app_for(repo)) as http:
        body = request_for(http.get(BASE).json(), data)
        invalid = {**body, 'form': {**data, 'credentials': 'synthetic secret'}}
        result = http.post(BASE + '/preview', json=invalid, headers=LOCAL)
        assert result.status_code == 422 and 'synthetic secret' not in result.text
        draft = {**body, 'form': {'format': 'local-config-9'}, 'validated': False}
        preview = http.post(BASE + '/preview', json=draft, headers=LOCAL).json()
        result = http.post(BASE + '/save', json={**draft, 'preview_sha256': preview['sha256']},
                           headers={**LOCAL, 'Idempotency-Key': 'draft'})
        assert result.status_code == 200, result.text
        state = http.get(BASE).json()
        activation = {'references': [{**{k: state['saved'][k] for k in ('scope', 'revision', 'sha256')},
                                     'expected_version': state['version']}], 'reason': 'Reject draft'}
        result = http.post(BASE + '/activation/preview', json=activation, headers=LOCAL)
        assert result.status_code == 409 and result.json()['detail']['code'] == 'configuration_draft_not_activatable'
        assert http.post(BASE + '/preview', json=body, headers=LOCAL).status_code == 409
        store(http, data)
        body = request_for(http.get(BASE).json(), data)
        preview = http.post(BASE + '/preview', json=body, headers=LOCAL).json()
        assert http.post(BASE + '/save', json={**body, 'preview_sha256': preview['sha256']},
                         headers={**LOCAL, 'Idempotency-Key': 'save'}).status_code == 409


def test_invalid_source_remains_readable_and_is_never_overwritten(setup):
    repo, _, root = setup
    source = root / 'global.toml'
    source.write_text('invalid TOML = [')
    source.chmod(0o600)
    with TestClient(app_for(repo, config_source=source)) as http:
        assert http.get(BASE).json()['mode'] == 'INVALID'
        assert http.get('/api/health').status_code == 200
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 409
    assert source.read_text() == 'invalid TOML = ['


def test_pending_cancel_and_tampered_immutable_fail_closed(setup):
    repo, data, root = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        hold(repo)
        activation = schedule(http)
        state = http.get(BASE).json()
        assert state['mode'] == 'APPLY_PENDING' and state['live_activation']['waiting'] == ['project_creation']
        assert state['active'] is None and state['pending']['revision'] == 1
        result = http.post(BASE + '/cancel', json={'activation_id': activation['id'],
            'expected_version': state['version'], 'reason': 'Cancel synthetic activation'},
            headers={**LOCAL, 'Idempotency-Key': 'cancel'})
        assert result.status_code == 200 and http.get(BASE).json()['mode'] == 'UNCONFIGURED'
        hold(repo, reserved=False)
        assert app.state.runtime.apply_pending() is None  # a cancelled set is never applied later
        # The database write barrier also checks authority, beyond the HTTP guard.
        with pytest.raises(ConfigurationConflict):
            with app.state.runtime.repository._write():
                pytest.fail('Unconfigured write entered transaction')
    immutable = next(root.rglob('1-*.toml'))
    immutable.write_text('format="local-config-9"')
    with TestClient(app_for(repo)) as http:
        assert http.get(BASE).json()['mode'] == 'INVALID'


def test_read_only_archive_never_reads_source_or_detects(setup, monkeypatch):
    repo, _, _ = setup
    with repo.managed.engine.begin() as connection:
        connection.exec_driver_sql(f'PRAGMA user_version={RESTORED_USER_VERSION}')
    monkeypatch.setattr('my_harness.api.app.verify_bundle', lambda path: None)
    monkeypatch.setattr('my_harness.services.configuration_setup.legacy._read',
                        lambda *a: pytest.fail('Archive read original TOML'))
    with TestClient(app_for(repo, config_source=Path('/missing/private/config.toml'))) as http:
        assert http.get(BASE).json()['mode'] == 'READ_ONLY_ARCHIVE'
        for suffix in ('/detect', '/form', '/preview', '/save', '/activate', '/check-clients', '/cancel'):
            assert http.post(BASE + suffix, json={}, headers=LOCAL).status_code == 409


def test_editor_form_toml_roundtrip_preserves_advanced_fields_without_processes(setup, monkeypatch):
    repo, data, _ = setup
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Form conversion launched a process'))
    data['agents']['executor'].update(provider='claude', tools=['Read'], allowed_tools=['Read'])
    data['agents']['executor']['environment']['CUSTOM'] = 'value with "quotes" and \nnewlines'
    data['service'].update(lease_seconds=17, poll_seconds=0.7)
    data['git']['author_name'] = 'Synthetic "quoted" name'
    with TestClient(app_for(repo)) as http:
        converted = http.post(BASE + '/form', json={'form': data}, headers=LOCAL)
        assert converted.status_code == 200, converted.text
        assert converted.json()['form'] == data
        text = converted.json()['text']
        back = http.post(BASE + '/form', json={'text': text}, headers=LOCAL)
        assert back.json() == converted.json()
        state = http.get(BASE).json()
        assert state['version'] == 0 and state['saved'] is None
        draft = http.post(BASE + '/form', json={'form': {'git': {'author_name': 'Draft'}}, 'validated': False}, headers=LOCAL)
        assert draft.status_code == 200
        assert draft.json()['form']['format'] == 'local-config-9'
        assert draft.json()['form']['service']['state_dir'] == str(repo.state_dir)
        for candidate in ({'text': 'invalid = ['}, {'text': 'format = "local-config-8"'},
                          {'form': {'credentials': 'must-not-appear'}}, {'form': data, 'text': text}):
            rejected = http.post(BASE + '/form', json={**candidate, 'validated': False}, headers=LOCAL)
            assert rejected.status_code == 422
            assert 'must-not-appear' not in rejected.text
        assert http.post(BASE + '/form', json={'form': data}, headers={}).status_code == 403


def test_recovery_requires_exact_preview_and_stopped_declaration(setup):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        configured = app.state.runtime.setup.repository
        configured.checkpoint = lambda stage: (_ for _ in ()).throw(RuntimeError('Synthetic crash')) if stage == 'intended' else None
        state = http.get(BASE).json()
        body = request_for(state, data)
        preview = http.post(BASE + '/preview', json=body, headers=LOCAL).json()
        with pytest.raises(RuntimeError):
            http.post(BASE + '/save', json={**body, 'preview_sha256': preview['sha256']},
                      headers={**LOCAL, 'Idempotency-Key': 'crash'})
        assert http.get(BASE).json()['mode'] == 'RECOVERY_REQUIRED'
        with Session(repo.managed.engine) as session:
            operation_id = session.scalar(select(Operation.id))
        path = BASE + '/operations/' + operation_id + '/recovery'
        recovery = http.post(path + '/preview', headers=LOCAL).json()
        configured.checkpoint = lambda stage: None
        assert http.post(path + '/confirm', json={'preview_sha256': recovery['sha256']}, headers=LOCAL).status_code == 409
        result = http.post(path + '/confirm', json={'preview_sha256': recovery['sha256'], 'writers_stopped': True}, headers=LOCAL)
        assert result.status_code == 200, result.text
        assert result.json()['status'] == 'SAVED' and http.get(BASE).json()['active'] is None


def test_legacy_explicit_authority_requires_import_and_preferences_still_work(setup):
    repo, data, _ = setup
    with TestClient(app_for(repo, managed=ManagedConfig())) as http:
        assert http.get(BASE).json()['legacy'] is True
        assert http.get(BASE).json()['mode'] == 'READY'
        result = http.post(BASE + '/preview', json=request_for(http.get(BASE).json(), data), headers=LOCAL)
        assert result.status_code == 409 and result.json()['detail']['code'] == 'configuration_import_required'
    with TestClient(app_for(repo)) as http:
        prefs = http.get('/api/managed/preferences').json()
        result = http.put('/api/managed/preferences', json={'expected_version': prefs['version'],
            'ui_language': 'es', 'default_work_language': 'en'}, headers={**LOCAL, 'Idempotency-Key': 'spanish'})
        assert result.status_code == 200, result.text
        invalid = http.post(BASE + '/preview', json={'form': {'unknown': 'synthetic secret'},
            **{k: v for k, v in request_for(http.get(BASE).json(), data).items() if k != 'form'}}, headers=LOCAL)
        assert invalid.status_code == 422 and 'Configuración no válida' in invalid.text
        assert 'synthetic secret' not in invalid.text


def test_changed_working_copy_closes_admission_without_adopting_values(setup):
    repo, data, root = setup
    with TestClient(app_for(repo)) as http:
        store(http, data)
        schedule(http)
    app = app_for(repo)
    with TestClient(app) as http:
        assert http.get(BASE).json()['mode'] == 'READY'
        (root / 'global.toml').write_text('format="local-config-9"\n# external')
        assert http.get(BASE).json()['mode'] == 'INVALID'
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 409
        with pytest.raises(ConfigurationConflict):
            with app.state.runtime.repository._write():
                pytest.fail('External change bypassed transaction guard')
        assert app.state.runtime.setup.loaded['revision'] == 1


def test_failed_startup_promotion_preserves_pending_and_avoids_consumers(setup, monkeypatch):
    repo, data, root = setup
    with TestClient(app_for(repo)) as http:
        store(http, data)
        hold(repo)
        operation = schedule(http)
    immutable = next(root.rglob('1-*.toml'))
    immutable.write_text('format="local-config-9"')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Invalid startup launched client'))
    app = app_for(repo)
    with TestClient(app) as http:
        state = http.get(BASE).json()
        assert state['mode'] == 'INVALID' and state['pending_activation_id'] == operation['id']
        assert state['active'] is None and state['pending']['revision'] == 1
        assert app.state.runtime.worker is None


def test_manual_text_and_form_use_same_validation_and_fixed_storage(setup):
    repo, data, _ = setup
    with TestClient(app_for(repo)) as http:
        body = request_for(http.get(BASE).json(), data)
        wrong = copy.deepcopy(body)
        wrong['form']['service']['state_dir'] = str(repo.directory)
        result = http.post(BASE + '/preview', json=wrong, headers=LOCAL)
        assert result.status_code == 409 and result.json()['detail']['code'] == 'state_directory_fixed_at_startup'
        for candidate in ({**body, 'text': dumps(data)}, {**body, 'validated': 'true'}):
            assert http.post(BASE + '/preview', json=candidate, headers=LOCAL).status_code == 422
        body['text'] = dumps(body.pop('form'))
        assert http.post(BASE + '/preview', json=body, headers=LOCAL).status_code == 200


def test_invalid_legacy_factory_spec_never_reports_ready(setup, monkeypatch):
    repo, _, _ = setup
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'invalid')
    with TestClient(app_for(repo)) as http:
        assert http.get(BASE).json()['mode'] == 'INVALID'
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 409


def test_invalid_runtime_composition_leaves_protected_editor_available(setup):
    repo, _, _ = setup
    with TestClient(app_for(repo, managed=ManagedConfig(supervisor=True))) as http:
        assert http.get(BASE).json()['mode'] == 'INVALID'
        assert http.app.state.runtime.worker is None
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 409


def test_unreadable_private_files_preserve_durable_references(setup):
    repo, data, root = setup
    with TestClient(app_for(repo)) as http:
        store(http, data)
        schedule(http)
    with TestClient(app_for(repo)) as http:
        state = http.get(BASE).json()
        root.chmod(0o755)
        try:
            unreadable = http.get(BASE).json()
            assert unreadable['mode'] == 'INVALID'
            assert unreadable['active'] == state['active'] and unreadable['saved'] == state['saved']
        finally:
            root.chmod(0o700)
