from pathlib import Path

import pytest
from sqlalchemy import text

from my_harness.cli import main
from my_harness.launcher import initialize, local_database, serve
from my_harness.storage.database import make_engine
from my_harness.storage.schema import require_schema


def test_initialize_independent_of_cwd_and_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HARNESS_DATABASE_URL', 'sqlite:///wrong.sqlite3')
    path = tmp_path / 'new' / 'synthetic %.sqlite3'
    initialize(str(path))
    engine = make_engine(local_database(str(path))[1])
    try:
        require_schema(engine)
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM managed_jobs')) == 0
    finally:
        engine.dispose()
    assert not (tmp_path / 'wrong.sqlite3').exists()
    original = path.read_bytes()
    assert main(['init-db', '--database', str(path)]) == 1
    assert path.read_bytes() == original


@pytest.mark.parametrize('kind', ['file', 'symlink', 'directory'])
def test_initialize_preserves_existing_destination(tmp_path, kind):
    target = tmp_path / 'existing'
    if kind == 'file':
        target.write_text('foreign')
    elif kind == 'symlink':
        target.symlink_to(tmp_path / 'absent')
    else:
        target.mkdir()
    with pytest.raises(ValueError, match='already exists'):
        initialize(str(target))
    with pytest.raises(ValueError, match='ya existe'):
        initialize(str(target), 'es')


def test_start_rejects_missing_and_relative_database_without_creation(tmp_path, capsys):
    assert main(['serve', '--database', 'relative.sqlite3']) == 1
    assert 'absolute path' in capsys.readouterr().err
    assert main(['--ui-language', 'es', 'serve', '--database', 'relative.sqlite3']) == 1
    assert 'ruta absoluta' in capsys.readouterr().err
    path = tmp_path / 'missing.sqlite3'
    assert main(['serve', '--database', str(path)]) == 1
    assert 'init-db' in capsys.readouterr().err
    assert not path.exists()


@pytest.mark.parametrize('port', [0, 65536, -1])
def test_invalid_port_has_no_effects(tmp_path, port):
    with pytest.raises(ValueError, match='port'):
        serve(str(tmp_path / 'absent'), port)
    assert not (tmp_path / 'absent').exists()


def test_api_assets_ignore_cwd(migrated_database, tmp_path, monkeypatch):
    from session_client import TestClient
    from my_harness.api.app import create_app
    rogue = tmp_path / 'frontend/dist'
    rogue.mkdir(parents=True)
    (rogue / 'index.html').write_text('unexpected cwd content')
    monkeypatch.chdir(tmp_path)
    with TestClient(create_app(migrated_database[0]), base_url='http://127.0.0.1') as client:
        assert 'unexpected cwd content' not in client.get('/').text
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/not-a-route').status_code == 404


def test_explicit_development_assets(migrated_database, tmp_path):
    from session_client import TestClient
    from my_harness.api.app import create_app
    (tmp_path / 'index.html').write_text('<html>explicit</html>')
    with TestClient(create_app(migrated_database[0], ui_dir=tmp_path)) as client:
        assert client.get('/').text == '<html>explicit</html>'
        assert client.get('/api/not-a-route').status_code == 404


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_initialize_preserves_orphan_sidecars(tmp_path, suffix):
    path = tmp_path / 'new.sqlite3'
    sidecar = Path(str(path) + suffix)
    sidecar.write_bytes(b'foreign evidence')
    with pytest.raises(ValueError, match='auxiliary'):
        initialize(str(path))
    assert sidecar.read_bytes() == b'foreign evidence'
    assert not path.exists()
