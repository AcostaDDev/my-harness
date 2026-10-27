"""H5.6 uses anonymous clients deliberately; no authentication test bypass."""
import asyncio
import json
import os
import stat

from fastapi.testclient import TestClient
import pytest

from my_harness.api.app import create_app

LOCAL = 'http://127.0.0.1:8013'
CSRF = {'X-My-Harness': '1'}


@pytest.fixture
def http(migrated_database, tmp_path):
    ui = tmp_path / 'ui'
    ui.mkdir()
    (ui / 'index.html').write_text('<html>login shell</html>')
    app = create_app(migrated_database[0], ui)
    with TestClient(app, base_url=LOCAL) as client:
        yield client


def login(http):
    return http.post('/api/session', json={'key': http.app.state.sessions.path.read_text()}, headers=CSRF)


@pytest.mark.parametrize('path', [
    '/api/health', '/api/simulations', '/api/simulations/00000000-0000-0000-0000-000000000000',
    '/api/legacy/projects', '/api/legacy/updates', '/api/legacy/events',
    '/api/legacy/projects/p/artifacts/a/content', '/api/legacy/projects/p/artifacts/a/entries',
    '/api/managed/projects', '/api/managed/runs/r', '/api/managed/runs/r/logs',
    '/api/managed/runs/r/tests', '/api/unknown', '/openapi.json', '/api/session',
])
def test_anonymous_reads_are_denied(http, path):
    response = http.get(path, headers=CSRF)
    assert response.status_code == 401
    assert response.json()['detail']['code'] == 'session_required'
    assert response.headers['cache-control'] == 'no-store'
    assert 'access-control-allow-origin' not in response.headers


@pytest.mark.parametrize('method,path', [('POST', '/api/simulations'), ('PUT', '/api/legacy/projects/p/observation'),
    ('POST', '/api/managed/projects/p/runs'), ('DELETE', '/api/session')])
def test_anonymous_mutations_do_not_reach_product(http, method, path):
    assert http.request(method, path, headers=CSRF, json={}).status_code == 401
    assert login(http).status_code == 200
    assert http.get('/api/simulations').json() == []


def test_private_file_cookie_logout_expiry_and_restart(http, capsys):
    sessions = http.app.state.sessions
    path = sessions.path
    key = path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.stat().st_uid == os.getuid()
    assert key not in capsys.readouterr().out
    assert key not in http.get('/').text
    response = login(http)
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api' in cookie
    assert key not in response.text and key not in cookie
    old = http.cookies.get(sessions.cookie)
    assert http.get('/api/health').status_code == 200
    assert http.delete('/api/session', headers=CSRF).status_code == 204
    http.cookies.set(sessions.cookie, old)
    assert http.get('/api/simulations').status_code == 401
    http.cookies.clear()
    assert login(http).status_code == 200
    now = sessions.clock()
    sessions.clock = lambda: now + sessions.lifetime + 1
    assert http.get('/api/session').status_code == 401
    assert http.post('/api/simulations', headers=CSRF, json={'title': 'expired'}).status_code == 401
    sessions.stop()
    assert not path.exists() and not path.parent.exists()
    sessions.start()
    assert sessions.path.read_text() != key
    assert http.get('/api/simulations').status_code == 401
    assert http.post('/api/session', headers=CSRF, json={'key': key}).status_code == 401


@pytest.mark.parametrize('origin', ['https://evil.example', 'null', 'http://localhost:8013',
    'http://127.0.0.1:9999', 'https://127.0.0.1:8013', 'http://user@127.0.0.1:8013',
    'http://127.0.0.1:8013/path', 'http://[broken'])
def test_origin_rejected_even_with_session(http, origin):
    assert login(http).status_code == 200
    for path in ['/api/session', '/api/simulations', '/api/legacy/events']:
        assert http.get(path, headers={'Origin': origin}).status_code == 403
    assert http.post('/api/session', headers=CSRF | {'Origin': origin}, json={'key': 'x'}).status_code == 403


@pytest.mark.parametrize('host', ['evil.example', '127.0.0.1.evil.example', 'localhost.evil', '[broken'])
def test_bad_host_never_serves_shell_or_data(http, host):
    for path in ['/', '/api/simulations', '/api/session']:
        assert http.get(path, headers={'Host': host}).status_code == 403


def test_csrf_and_exact_origin(http):
    key = http.app.state.sessions.path.read_text()
    assert http.post('/api/session', json={'key': key}).status_code == 403
    assert http.post('/api/session', headers=CSRF | {'Origin': LOCAL}, json={'key': key}).status_code == 200
    assert http.post('/api/simulations', json={'title': 'csrf'}).status_code == 403
    assert http.get('/api/simulations', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert http.post('/api/simulations', headers=CSRF | {'Origin': LOCAL}, json={'title': 'valid'}).status_code == 201
    assert http.get('/api/simulations', headers={'Origin': LOCAL}).status_code == 200


@pytest.mark.parametrize('body', [b'{"key":', b'{"key":123}', b'{"key":"\\ud800"}',
    b'[]', b'{"key":"wrong","extra":"secret"}', b'x' * 257])
def test_invalid_login_never_echoes_input(http, body):
    response = http.post('/api/session', headers=CSRF, content=body)
    assert response.status_code in {400, 401}
    assert 'secret' not in response.text and 'wrong' not in response.text and 'input' not in response.text
    assert 'set-cookie' not in response.headers


def test_login_rate_limit(http):
    for _ in range(10):
        assert http.post('/api/session', headers=CSRF, json={'key': 'wrong'}).status_code == 401
    assert login(http).status_code == 429
    assert http.get('/api/session').status_code == 401




def test_all_registered_product_routes_require_session(http):
    from fastapi.routing import APIRoute
    for route in http.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if route.path == '/api/session' and method == 'POST':
                continue
            assert http.request(method, route.path, headers=CSRF).status_code == 401, (method, route.path)


def test_new_login_revokes_old_cookie_and_tokens_are_not_in_openapi(http):
    assert login(http).status_code == 200
    sessions = http.app.state.sessions
    first = http.cookies.get(sessions.cookie)
    assert login(http).status_code == 200
    second = http.cookies.get(sessions.cookie)
    assert first != second
    assert sessions.remaining(first) == 0 and sessions.remaining(second) > 0
    schema = http.get('/openapi.json').text
    assert first not in schema and second not in schema and sessions.path.read_text() not in schema


def test_vite_proxy_preserved_host_uses_browser_origin(migrated_database):
    with TestClient(create_app(migrated_database[0]), base_url='http://127.0.0.1:5173') as client:
        key = client.app.state.sessions.path.read_text()
        assert client.post('/api/session', json={'key': key}, headers=CSRF | {'Origin': 'http://127.0.0.1:5173'}).status_code == 200
        assert client.get('/api/simulations').status_code == 200


def test_shutdown_removes_private_key_and_invalidates_sessions(migrated_database):
    app = create_app(migrated_database[0])
    assert app.state.sessions.path is None  # constructing/exporting never creates credentials
    with TestClient(app, base_url=LOCAL) as client:
        assert login(client).status_code == 200
        path = app.state.sessions.path
        token = client.cookies.get(app.state.sessions.cookie)
    assert not path.exists() and not path.parent.exists()
    assert app.state.sessions.remaining(token) == 0
