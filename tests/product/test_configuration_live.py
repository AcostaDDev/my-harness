"""OT001 (D238): live global activation in the same process, synthetic probes/SQLite only."""
import copy
import sys
import time

from sqlalchemy.orm import Session

from session_client import TestClient
from my_harness.services.configuration import parse
from my_harness.storage.models import ConfigurationOperationRow as Operation
from test_configuration import setup  # noqa: F401
from test_configuration_api import BASE, LOCAL, app_for, hold, request_for, schedule, store


def change(http, data, key, *, wait=False):
    """Save `data` and confirm its activation; returns the ACTIVATE operation."""
    store(http, data, key=key)
    state = http.get(BASE).json()
    body = {'references': state['activation_references'], 'reason': 'Apply synthetic agent settings'}
    shown = http.post(BASE + '/activation/preview', json=body, headers=LOCAL)
    assert shown.status_code == 200, shown.text
    assert shown.json()['apply'] == 'live' and shown.json()['restart_required'] is False
    result = http.post(BASE + '/activate', json={**body, 'preview_sha256': shown.json()['sha256']},
                       headers={**LOCAL, 'Idempotency-Key': key + '-activate'})
    assert result.status_code == 200, result.text
    return result.json()


def executor(runtime):
    return runtime.config.registrar.agents['executor']


def test_idle_timeout_change_applies_in_same_process_and_session(setup):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
        runtime = app.state.runtime
        loaded = runtime.config
        state = http.get(BASE).json()
        form = copy.deepcopy(state['form'])
        form['agents']['executor']['timeout_seconds'] = 45
        body = request_for(state, form)
        preview = http.post(BASE + '/preview', json=body, headers=LOCAL).json()
        # Only the timeout changes; every other field, including advanced ones, is preserved.
        candidate = parse(preview['changes'][0]['text'], 'global')
        expected = copy.deepcopy(state['form'])
        expected['agents']['executor']['timeout_seconds'] = 45
        assert candidate == expected and preview['changes'][0]['removed_fields'] == []
        operation = change(http, form, 'timeout')
        assert operation['result']['state'] == 'APPLY_PENDING'
        state = http.get(BASE).json()
        assert state['mode'] == 'READY' and state['active']['revision'] == 2 and state['pending'] is None
        assert runtime.config is not loaded and executor(runtime).timeout_seconds == 45
        assert runtime.setup.loaded['revision'] == 2
        # The same authenticated client keeps working: no restart, reinstall or new access key.
        assert http.post('/api/managed/registry/preview', json={}, headers=LOCAL).status_code == 422
        with Session(runtime.engine) as session:
            kinds = [row.kind for row in session.query(Operation).order_by(Operation.created_at)]
        assert kinds[-2:] == ['ACTIVATE', 'PROMOTE']


def test_explicit_removal_is_named_in_the_save_preview(setup):
    repo, data, _ = setup
    with TestClient(app_for(repo)) as http:
        store(http, data)
        schedule(http)
        state = http.get(BASE).json()
        form = copy.deepcopy(state['form'])
        del form['agents']['executor']['timeout_seconds']
        body = {**request_for(state, form), 'validated': False}
        preview = http.post(BASE + '/preview', json=body, headers=LOCAL)
        assert preview.status_code == 200, preview.text
        assert preview.json()['changes'][0]['removed_fields'] == ['agents.executor.timeout_seconds']


def test_missing_client_refuses_before_switch_with_correction(setup):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
        runtime = app.state.runtime
        before = runtime.config
        broken = copy.deepcopy(data)
        broken['agents']['executor']['executable'] = ['/nonexistent/synthetic/codex']
        store(http, broken, key='broken')
        state = http.get(BASE).json()
        body = {'references': state['activation_references'], 'reason': 'Try a missing client'}
        refused = http.post(BASE + '/activation/preview', json=body, headers=LOCAL)
        assert refused.status_code == 409, refused.text
        detail = refused.json()['detail']
        assert detail['code'] == 'live_configuration_refused'
        assert [(item['role'], item['setting']) for item in detail['details']] == [('executor', 'agents.executor')]
        assert detail['details'][0]['code'] and detail['details'][0]['diagnostic']
        assert http.get(BASE).json()['active']['revision'] == 1 and runtime.config is before


def test_waiting_work_defers_switch_until_it_is_resolved(setup):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
        runtime = app.state.runtime
        hold(repo)
        form = copy.deepcopy(data)
        form['agents']['reviewer']['model'] = 'later-synthetic'
        operation = change(http, form, 'model')
        assert operation['result'] == {**operation['result'], 'state': 'APPLY_PENDING', 'waiting': ['project_creation']}
        state = http.get(BASE).json()
        assert state['mode'] == 'APPLY_PENDING' and state['blockers'] == []
        assert state['live_activation']['waiting'] == ['project_creation']
        assert state['active']['revision'] == 1 and runtime.config.registrar.reviewer[0] == 'synthetic'
        # The active authority keeps admitting writes while the set waits.
        with runtime.repository._write():
            pass
        # A second confirmation cannot race the pending set.
        store_refused = http.post(BASE + '/activation/preview', json={
            'references': state['activation_references'] or [{'scope': 'global', 'revision': 2,
                'sha256': state['saved']['sha256'], 'expected_version': state['version']}],
            'reason': 'Second activation'}, headers=LOCAL)
        assert store_refused.status_code == 409
        hold(repo, reserved=False)
        state = http.get(BASE).json()  # the read applies the set at the boundary
        assert state['mode'] == 'READY' and state['active']['revision'] == 2
        assert runtime.config.registrar.reviewer[0] == 'later-synthetic'


def test_candidate_failing_at_boundary_is_withdrawn_and_active_stays(setup, tmp_path):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
        runtime = app.state.runtime
        probe = tmp_path / 'later-probe.py'
        probe.write_text((tmp_path / 'probe.py').read_text())
        form = copy.deepcopy(data)
        form['agents']['executor']['executable'] = [sys.executable, str(probe)]
        hold(repo)
        operation = change(http, form, 'vanishing')
        probe.unlink()  # the client disappears while the set waits
        hold(repo, reserved=False)
        state = http.get(BASE).json()
        assert state['mode'] == 'READY' and state['active']['revision'] == 1 and state['pending'] is None
        failure = state['live_activation']
        assert failure['state'] == 'FAILED' and failure['activation_id'] == operation['id']
        assert failure['code'] == 'live_configuration_refused'
        assert failure['details'][0]['role'] == 'executor'
        assert runtime.setup.loaded['revision'] == 1
        with runtime.repository._write():
            pass  # the previous authority remains usable


def test_restart_before_boundary_loads_previous_then_applies(setup):
    repo, data, _ = setup
    with TestClient(app_for(repo)) as http:
        store(http, data)
        schedule(http)
        hold(repo)
        form = copy.deepcopy(data)
        form['agents']['executor']['timeout_seconds'] = 33
        change(http, form, 'crash')
        assert http.get(BASE).json()['mode'] == 'APPLY_PENDING'
    # Simulated crash/restart while work still waits: the previous active set is loaded.
    app = app_for(repo)
    with TestClient(app) as http:
        state = http.get(BASE).json()
        assert state['mode'] == 'APPLY_PENDING' and state['active']['revision'] == 1
        assert executor(app.state.runtime).timeout_seconds == 10
        hold(repo, reserved=False)
        assert http.get(BASE).json()['active']['revision'] == 2
        assert executor(app.state.runtime).timeout_seconds == 33
    with TestClient(app_for(repo)) as http:
        assert http.get(BASE).json()['mode'] == 'READY'


def test_running_worker_applies_at_idle_and_classifies_service_fields(setup):
    repo, data, _ = setup
    data['service']['supervisor'] = True
    data['service']['poll_seconds'] = 0.05
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
        runtime = app.state.runtime
        # The first live set starts the stopped supervisor with its values.
        assert runtime.worker is not None and runtime.worker.alive()
        hold(repo)
        form = copy.deepcopy(data)
        form['agents']['executor']['timeout_seconds'] = 21
        change(http, form, 'worker')
        hold(repo, reserved=False)
        deadline = time.monotonic() + 10
        while executor(runtime).timeout_seconds != 21 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert executor(runtime).timeout_seconds == 21  # applied by the idle writer lane, without a read
        # Worker loop settings cannot be switched under a running worker: restart, named before confirming.
        form['service']['lease_seconds'] = 60.0
        store(http, form, key='lease')
        state = http.get(BASE).json()
        shown = http.post(BASE + '/activation/preview', json={'references': state['activation_references'],
                          'reason': 'Lease change'}, headers=LOCAL)
        assert shown.status_code == 200, shown.text
        assert shown.json()['apply'] == 'restart' and shown.json()['restart_fields'] == ['service.lease_seconds']


def test_read_only_archive_never_applies(setup, monkeypatch):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
    monkeypatch.setattr('my_harness.storage.backup.is_read_only_archive', lambda engine: True)
    assert app.state.runtime.apply_pending() is None


def test_failure_during_switch_rolls_back_both_sqlite_and_runtime(setup, monkeypatch):
    repo, data, _ = setup
    app = app_for(repo)
    with TestClient(app) as http:
        store(http, data)
        schedule(http)
        runtime = app.state.runtime
        before = (runtime.config, runtime.setup.loaded)
        hold(repo)
        form = copy.deepcopy(data)
        form['agents']['executor']['timeout_seconds'] = 77
        change(http, form, 'inject')
        hold(repo, reserved=False)
        original = runtime._install_staging
        def crash(staging):
            original(staging)
            raise OSError('Synthetic failure inside the promotion transaction')
        monkeypatch.setattr(runtime, '_install_staging', crash)
        state = http.get(BASE).json()  # the read survives the failed switch
        assert state['mode'] == 'APPLY_PENDING' and state['active']['revision'] == 1
        assert (runtime.config, runtime.setup.loaded) == before
        with runtime.repository._write():
            pass  # the previous authority stays consistent and usable
        monkeypatch.setattr(runtime, '_install_staging', original)
        assert http.get(BASE).json()['active']['revision'] == 2
        assert executor(runtime).timeout_seconds == 77
