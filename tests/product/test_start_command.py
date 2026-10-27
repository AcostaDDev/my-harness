"""P013-T003: synthetic installed interpreter/processes; no actual service or providers."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

import pytest

from product.test_install_command import bundle, installer

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
spec = importlib.util.spec_from_file_location('harness_start', SCRIPTS / 'start.py')
starter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(starter)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    root, data, config = (tmp_path / name for name in ('installed with spaces', 'private data', 'private configuration'))
    generation = root / 'generations/gen-synthetic'
    (generation / 'venv/bin').mkdir(parents=True)
    for folder in (root, data, config):
        folder.mkdir(mode=0o700, exist_ok=True)
        folder.chmod(0o700)
    distribution = bundle(generation / 'distribution')
    log = tmp_path / 'processes.jsonl'
    interpreter = generation / 'venv/bin/python'
    interpreter.write_text(f'''#!{sys.executable}
import json, os, pathlib, signal, sys, time
args = sys.argv[1:]
with open({str(log)!r}, 'a') as stream:
    observed = {{k: os.environ[k] for k in ('TMPDIR', 'TMP', 'TEMP', 'PYTHONDONTWRITEBYTECODE', 'PYTHONNOUSERSITE',
                'HARNESS_MANAGED_CONFIG', 'HARNESS_LOCAL_CONFIG', 'HARNESS_DATABASE_URL', 'PYTHONPATH',
                'GIT_INDEX_FILE', 'UV_PYTHON', 'VIRTUAL_ENV') if k in os.environ}}
    stream.write(json.dumps({{'args': args, 'cwd': os.getcwd(), 'env': observed, 'pid': os.getpid()}}) + '\\n')
if '-c' in args:
    database, config = map(pathlib.Path, args[-2:])
    if database.is_file() and database.read_text() not in ('synthetic-db', 'archive'):
        print('Separate D150 migration required', file=sys.stderr); sys.exit(1)
    if database.is_file() and database.read_text() == 'archive':
        sys.exit(20)
elif 'init-db' in args:
    path = pathlib.Path(args[args.index('--database') + 1])
    with path.open('x') as stream: stream.write('synthetic-db')
    if os.environ.get('SYNTHETIC_FAIL_INIT'):
        path.write_text('partial'); sys.exit(8)
elif 'serve' in args:
    if os.environ.get('SYNTHETIC_WAIT'):
        def stop(number, frame):
            pathlib.Path({str(tmp_path / 'signal')!r}).write_text(str(number)); sys.exit(0)
        signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
        pathlib.Path({str(tmp_path / 'ready')!r}).write_text('ready')
        while True: time.sleep(0.01)
    sys.exit(int(os.environ.get('SYNTHETIC_EXIT', '0')))
else:
    sys.exit('Unexpected synthetic command')
''')
    interpreter.chmod(0o700)
    receipt = {'format': 'installation-1', 'status': 'READY',
               'request': {'install_dir': str(root), 'data_dir': str(data), 'config_dir': str(config)},
               'distribution_sha256': installer.digest((distribution / 'SHA256SUMS').read_bytes()),
               'venv': installer.venv_identity(generation / 'venv')}
    installer.write_json(generation / 'installation.json', receipt)
    installer.write_json(root / 'current.json', {'format': 'installation-1', 'generation': generation.name,
        'receipt_sha256': installer.digest((generation / 'installation.json').read_bytes())})
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'must.not:load')
    monkeypatch.setenv('HARNESS_LOCAL_CONFIG', '/must/not/read.toml')
    monkeypatch.setenv('PYTHONPATH', '/must/not/import')
    monkeypatch.setenv('GIT_INDEX_FILE', '/must/not/write')
    monkeypatch.setenv('UV_PYTHON', '/must/not/use')
    args = starter.parse_args(['--install-dir', str(root)])
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        args.port = probe.getsockname()[1]
    return args, data, config, log, generation


def calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_new_database_restart_and_private_environment(installed):
    args, data, config, log, generation = installed
    assert starter.main(['--install-dir', str(args.install_dir), '--port', str(args.port)]) == 0
    database = data / 'harness.sqlite3'
    original = database.read_bytes()
    assert database.stat().st_mode & 0o777 == 0o600
    assert (data / 'tmp').stat().st_mode & 0o777 == 0o700
    assert starter.start(args) == 0
    commands = calls(log)
    assert sum('init-db' in c['args'] for c in commands) == 1
    assert database.read_bytes() == original
    assert not list(config.iterdir())
    assert all(c['cwd'] == str(data) and c['args'][:2] == ['-I', '-B'] for c in commands)
    assert all(c['env']['TMPDIR'] == str(data / 'tmp') for c in commands)
    assert all(not any(k.startswith(('HARNESS_', 'PYTHONPATH', 'GIT_', 'UV_')) for k in c['env']) for c in commands)
    assert all('--config' not in c['args'] for c in commands if 'serve' in c['args'])
    assert installer.current_installation(args.install_dir)[1] == generation


def test_explicit_paths_and_existing_toml_are_preserved(installed):
    args, data, config, log, _ = installed
    args.database = data / 'nested/chosen.sqlite3'
    args.config = config / 'chosen.toml'
    args.config.write_text('synthetic TOML')
    args.temp_dir = data.parent / 'private temporary with spaces'
    assert starter.start(args) == 0
    serve = calls(log)[-1]['args']
    assert serve[-2:] == ['--config', str(args.config)]
    assert serve[serve.index('--configuration-dir') + 1] == str(config)
    assert serve[serve.index('--state-dir') + 1] == str(data)
    assert serve[serve.index('--database') + 1] == str(args.database)
    assert serve[serve.index('--port') + 1] == str(args.port)
    assert calls(log)[-1]['env']['TMPDIR'] == str(args.temp_dir)
    assert args.config.read_text() == 'synthetic TOML'


@pytest.mark.parametrize('explicit', [False, True])
def test_invalid_or_explicitly_missing_config_reaches_protected_setup(installed, explicit):
    args, data, config, log, _ = installed
    if explicit:
        args.config = config / 'missing.toml'
    else:
        (config / 'global.toml').write_text('invalid')
    assert starter.start(args) == 0
    assert (data / 'harness.sqlite3').read_text() == 'synthetic-db'
    assert len(calls(log)) == 3
    if not explicit:
        assert (config / 'global.toml').read_text() == 'invalid'


def test_old_schema_never_migrates_or_serves(installed):
    args, data, _, log, _ = installed
    database = data / 'harness.sqlite3'
    database.write_text('old-schema')
    assert starter.start(args) == 1
    assert database.read_text() == 'old-schema'
    assert len(calls(log)) == 1


def test_archive_ignores_invalid_operational_config(installed):
    args, data, config, log, _ = installed
    (data / 'harness.sqlite3').write_text('archive')
    (config / 'global.toml').write_text('invalid')
    assert starter.start(args) == 0
    assert '--config' not in calls(log)[-1]['args']
    assert not any('init-db' in c['args'] for c in calls(log))


@pytest.mark.parametrize('problem', ['database-outside', 'config-outside', 'temp-overlap', 'checkout', 'symlink',
                                    'hardlink', 'fifo', 'auxiliary', 'receipt', 'venv', 'public-temp', 'port'])
def test_unsafe_paths_and_installations_are_rejected(installed, problem):
    args, data, config, log, generation = installed
    database = data / 'harness.sqlite3'
    if problem == 'database-outside':
        args.database = data.parent / 'elsewhere.sqlite3'
    elif problem == 'config-outside':
        args.config = data.parent / 'elsewhere.toml'
    elif problem == 'temp-overlap':
        args.temp_dir = data
    elif problem == 'checkout':
        (data / '.git').mkdir()
    elif problem == 'symlink':
        database.symlink_to(data.parent / 'absent')
    elif problem == 'hardlink':
        (data / 'original').write_text('keep')
        os.link(data / 'original', database)
    elif problem == 'fifo':
        os.mkfifo(database)
    elif problem == 'auxiliary':
        Path(str(database) + '-wal').write_text('keep')
    elif problem == 'receipt':
        (generation / 'installation.json').write_text('{}')
    elif problem == 'venv':
        (generation / 'venv/bin/python').write_text('changed')
    elif problem == 'public-temp':
        args.temp_dir = data / 'public'
        args.temp_dir.mkdir(mode=0o755)
        args.temp_dir.chmod(0o755)
    else:
        args.port = 0
    with pytest.raises((starter.StartRefused, starter.InstallRefused, OSError, KeyError)):
        starter.start(args)
    assert not calls(log)


def test_busy_port_does_not_initialize_database(installed):
    args, data, _, log, _ = installed
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        args.port = occupied.getsockname()[1]
        with pytest.raises(starter.StartRefused, match='unavailable'):
            starter.start(args)
    assert not calls(log) and not (data / 'harness.sqlite3').exists()


def test_service_and_installer_exclusion(installed):
    args, _, _, log, _ = installed
    with starter.instance_lock(args.install_dir):
        with pytest.raises(starter.StartRefused, match='Another service'):
            starter.start(args)
    with installer.installation_lock(args.install_dir):
        with pytest.raises(starter.InstallRefused, match='in progress'):
            starter.start(args)
    assert not calls(log)


def test_service_failure_is_propagated_without_data_cleanup(installed, monkeypatch):
    args, data, _, _, _ = installed
    monkeypatch.setenv('SYNTHETIC_EXIT', '9')
    assert starter.start(args) == 9
    assert (data / 'harness.sqlite3').read_text() == 'synthetic-db'


def test_failed_initialization_preserves_partial_database_and_never_reinitializes(installed, monkeypatch):
    args, data, _, log, _ = installed
    monkeypatch.setenv('SYNTHETIC_FAIL_INIT', '1')
    assert starter.start(args) == 8
    assert (data / 'harness.sqlite3').read_text() == 'partial'
    assert starter.start(args) == 1
    assert sum('init-db' in c['args'] for c in calls(log)) == 1
    assert not any('serve' in c['args'] for c in calls(log))


@pytest.mark.parametrize('number', [signal.SIGINT, signal.SIGTERM])
def test_detached_wrapper_forwards_signals_and_holds_lock_until_child_exits(installed, number):
    args, data, _, log, generation = installed
    # Delivered scripts only, invoked from outside the source checkout without uv/Node/Vite.
    delivered = generation / 'distribution/scripts/start.py'
    process = subprocess.Popen([sys.executable, '-E', '-s', '-B', str(delivered), '--install-dir', str(args.install_dir),
                                '--port', str(args.port)],
                               cwd=data.parent, env=os.environ | {'SYNTHETIC_WAIT': '1'},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not (data.parent / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (data.parent / 'ready').exists(), process.communicate(timeout=2)
        with pytest.raises(starter.StartRefused, match='Another service'):
            starter.start(args)
        with pytest.raises(installer.InstallRefused, match='in progress'):
            with installer.installation_lock(args.install_dir):
                pytest.fail('Upgrade must not overlap a service')
        process.send_signal(number)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 128 + number, (stdout, stderr)
        assert (data.parent / 'signal').read_text() == str(number)
        with starter.instance_lock(args.install_dir):
            pass
        assert (data / 'harness.sqlite3').exists()
        assert all(c['cwd'] == str(data) for c in calls(log))
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)


def test_preflight_checks_schema_but_leaves_invalid_toml_for_protected_setup(migrated_database, tmp_path):
    # Direct installed-runtime boundary check on synthetic SQLite; no serve/init/provider invocation.
    from sqlalchemy import text
    from my_harness.storage.database import make_engine
    url, _ = migrated_database
    from sqlalchemy.engine import make_url
    database = Path(make_url(url).database)
    config = tmp_path / 'invalid.toml'
    config.write_text('not a TOML document')
    def probe():
        return subprocess.run([sys.executable, '-I', '-B', '-c', starter.PREFLIGHT, str(database), str(config)],
                              capture_output=True, text=True)
    original = database.read_bytes()
    result = subprocess.run([sys.executable, '-I', '-B', '-c', starter.PREFLIGHT, str(database), ''],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert database.read_bytes() == original
    result = probe()
    assert result.returncode == 0, result.stderr
    assert config.read_text() == 'not a TOML document'
    assert database.read_bytes() == original
    engine = make_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = 'old'"))
        result = probe()
        assert result.returncode == 1 and '--writers-stopped' in result.stderr and '--snapshots' in result.stderr
    finally:
        engine.dispose()
    import sqlite3
    from my_harness.storage.backup import RESTORED_USER_VERSION
    from my_harness.storage.schema import SCHEMA_REVISION
    with sqlite3.connect(database) as connection:
        connection.execute('UPDATE alembic_version SET version_num = ?', (SCHEMA_REVISION,))
        connection.execute(f'PRAGMA user_version={RESTORED_USER_VERSION}')
    original = database.read_bytes()
    assert probe().returncode == 20  # invalid TOML is never loaded in consultation mode
    assert database.read_bytes() == original


def test_wrapper_crash_keeps_exclusion_while_synthetic_service_lives(installed):
    args, data, _, log, generation = installed
    process = subprocess.Popen([sys.executable, '-E', '-s', '-B', str(generation / 'distribution/scripts/start.py'),
                                '--install-dir', str(args.install_dir), '--port', str(args.port)],
                               cwd=data.parent, env=os.environ | {'SYNTHETIC_WAIT': '1'},
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child = None
    try:
        deadline = time.monotonic() + 10
        while not (data.parent / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (data.parent / 'ready').exists()
        child = calls(log)[-1]['pid']
        process.kill()
        process.wait(timeout=5)
        with pytest.raises(starter.StartRefused, match='Another service'):
            starter.start(args)
        with pytest.raises(installer.InstallRefused, match='in progress'):
            with installer.installation_lock(args.install_dir):
                pytest.fail('A live service must retain upgrade exclusion')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        if child is not None:
            os.killpg(child, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while not (data.parent / 'signal').exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert (data.parent / 'signal').exists()


def test_restart_accepts_recently_closed_connections_but_still_rejects_listeners(installed):
    args, *_ = installed
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        args.port = listener.getsockname()[1]
        listener.listen()
        with pytest.raises(starter.StartRefused, match='unavailable'):
            starter.start(args)
        with socket.create_connection(('127.0.0.1', args.port)) as client:
            connection, _ = listener.accept()
            connection.close()  # server performs active close, leaving its port in TIME_WAIT
            assert client.recv(1) == b''
    assert starter.start(args) == 0
