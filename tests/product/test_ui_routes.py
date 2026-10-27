"""H6.2 E1 (D076): UI routes served by the wheel and code reads for their URLs."""
import pytest

from test_managed_api import PLAN, Ports, client
from test_phases import checkout  # noqa: F401  (fixture)


@pytest.fixture
def ui(tmp_path):
    assets = tmp_path / 'web'
    (assets / 'assets').mkdir(parents=True)
    (assets / 'index.html').write_text('<html>shell</html>')
    (assets / 'assets/app.js').write_text('console.log(1)')
    return assets


@pytest.mark.parametrize('path', ['/', '/projects/new', '/projects/demo', '/projects/demo/phases/P001/tasks/P001-T001',
                                  '/projects/demo/phases/v1.2', '/legacy', '/ruta/desconocida', '/projects/demo/docs',
                                  '/projects/demo/docs/docs/STATE.md', '/projects/demo/docs/docs/assets/guia.md',
                                  '/projects/demo/setup', '/projects/demo/setup/docs/decisions/D001-x.md',
                                  '/projects/demo/phases/P001/plan', '/projects/demo/phases/P001/plan/c-1',
                                  '/projects/demo/chat', '/projects/demo/chat/conversation-1', '/stats',
                                  '/projects/demo/stats'])
def test_ui_routes_receive_the_shell_on_direct_load(migrated_database, ui, path):
    from session_client import TestClient
    from my_harness.api.app import create_app
    with TestClient(create_app(migrated_database[0], ui_dir=ui)) as http:
        response = http.get(path)
        assert response.status_code == 200 and response.text == '<html>shell</html>'
        assert http.head(path).status_code == 200


def test_api_and_assets_keep_their_404(migrated_database, ui):
    from session_client import TestClient
    from my_harness.api.app import create_app
    with TestClient(create_app(migrated_database[0], ui_dir=ui)) as http:
        assert http.get('/assets/app.js').text == 'console.log(1)'
        for path in ('/assets/missing.js', '/favicon.ico', '/projects/demo/logo.svg'):
            assert http.get(path).status_code == 404, path
        missing = http.get('/api/not-a-route')
        assert missing.status_code == 404 and missing.headers['content-type'].startswith('application/json')
        assert http.get('/api/managed/not-a-route').status_code == 404
        assert http.post('/projects/demo', json={}).status_code != 200


def test_phase_by_code_tasks_and_filtered_runs(tmp_path, migrated_database, checkout, monkeypatch):  # noqa: F811
    from my_harness.services.managed_runtime import CONFIG_ENV
    from test_managed_api import config
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    with client(migrated_database[0], tmp_path, config(checkout, Ports([]), commit=False, supervisor=False)) as http:
        base = '/api/managed/projects/synthetic'
        assert http.get(f'{base}/phases/P001').status_code == 404
        phase = http.post(f'{base}/phases', json={
            'code': 'P001', 'objective': 'Synthetic', 'exit_criteria': ['c'], 'tasks': ['P001-T003', 'P001-T001'],
            'documents': ['docs/STATE.md'], 'tag': None}).json()
        by_code = http.get(f'{base}/phases/P001')
        assert by_code.status_code == 200 and by_code.json()['id'] == phase['id']
        runs = []
        for number, (task, phase_code) in enumerate([('P001-T001', 'P001'), ('P001-T002', 'P001'),
                                                     ('P001-T001', 'P001'), ('P002-T001', 'P002')]):
            response = http.post(f'{base}/runs', json={'task_id': task, 'phase_id': phase_code, 'text': PLAN},
                                 headers={'Idempotency-Key': f'run-{number}'})
            assert response.status_code == 202, response.text
            runs.append(response.json()['run_id'])
        tasks = http.get(f'{base}/phases/P001/tasks').json()
        assert [(t['task_id'], t['planned'], t['runs']) for t in tasks['items']] == [
            ('P001-T003', True, 0), ('P001-T001', True, 2), ('P001-T002', False, 1)]
        assert tasks['items'][0]['latest'] is None
        assert tasks['items'][1]['latest']['id'] == runs[2]
        assert tasks['items'][1]['latest']['project_id'] == 'synthetic'
        first = http.get(f'{base}/phases/P001/tasks', params={'limit': 2}).json()
        assert len(first['items']) == 2 and first['next_offset'] == 2
        assert http.get(f'{base}/phases/P001/tasks', params={'offset': 2}).json()['items'][0]['task_id'] == 'P001-T002'
        filtered = http.get(f'{base}/runs', params={'phase': 'P001', 'task': 'P001-T001'}).json()
        assert [r['id'] for r in filtered['items']] == [runs[2], runs[0]]
        assert {r['id'] for r in http.get(f'{base}/runs', params={'phase': 'P001'}).json()['items']} == set(runs[:3])
        assert len(http.get(f'{base}/runs').json()['items']) == 4
        undefined = http.get(f'{base}/phases/P002/tasks').json()['items']
        assert [(t['task_id'], t['planned'], t['runs']) for t in undefined] == [('P002-T001', False, 1)]
        assert http.get(f'{base}/phases/P009/tasks').json() == {'items': [], 'offset': 0, 'next_offset': None}
        assert http.get('/api/managed/projects/unknown/phases/P001/tasks').status_code == 404
        assert http.get('/api/managed/projects/unknown/phases/P001').status_code == 404
