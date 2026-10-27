"""Single development command: migration with a previous snapshot and API/UI supervision. Offline."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time

from alembic import command
import pytest

from my_harness.adapters.processes import identity
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.migrate import MigrationRefused, _config, prepare_database
from my_harness.storage.schema import SCHEMA_REVISION

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import dev  # noqa: E402


def revision(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT version_num FROM alembic_version').fetchone()[0]


def at_previous_revision(tmp_path):
    database = tmp_path / 'state.sqlite3'
    assert prepare_database(str(database), tmp_path / 'snapshots').action == 'created'
    command.downgrade(_config(f'sqlite:///{database}'), '0012_chat')
    with closing(sqlite3.connect(database)) as db:
        db.execute("INSERT INTO simulations (id, title, created_at, events) VALUES ('kept', 't', '2026-10-13', '[]')")
        db.commit()
    return database


def test_new_database_is_created_at_head_without_snapshot(tmp_path):
    outcome = prepare_database(str(tmp_path / 'new.sqlite3'), tmp_path / 'snapshots')
    assert (outcome.action, outcome.previous, outcome.revision, outcome.snapshot) == ('created', None, SCHEMA_REVISION, None)
    assert revision(tmp_path / 'new.sqlite3') == SCHEMA_REVISION
    assert not (tmp_path / 'snapshots').exists()


def test_current_database_is_left_untouched(tmp_path):
    database = tmp_path / 'state.sqlite3'
    prepare_database(str(database), tmp_path / 'snapshots')
    before = database.read_bytes()
    outcome = prepare_database(str(database), tmp_path / 'snapshots')
    assert outcome.action == 'current' and outcome.snapshot is None
    assert database.read_bytes() == before and not (tmp_path / 'snapshots').exists()


def test_pending_migration_takes_verified_snapshot_first(tmp_path):
    database = at_previous_revision(tmp_path)
    outcome = prepare_database(str(database), tmp_path / 'snapshots')
    assert (outcome.action, outcome.previous, outcome.revision) == ('migrated', '0012_chat', SCHEMA_REVISION)
    assert revision(database) == SCHEMA_REVISION
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT title FROM simulations WHERE id='kept'").fetchone() == ('t',)
    snapshot = outcome.snapshot
    assert snapshot.parent == tmp_path / 'snapshots' and oct(snapshot.stat().st_mode & 0o777) == '0o600'
    assert revision(snapshot) == '0012_chat'
    manifest = json.loads(snapshot.with_suffix('.json').read_text())
    assert manifest['sha256'] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert (manifest['source_revision'], manifest['target_revision']) == ('0012_chat', SCHEMA_REVISION)
    with closing(sqlite3.connect(snapshot)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


@pytest.mark.parametrize('problem', ['unknown_revision', 'restored_archive', 'no_alembic', 'live_writer'])
def test_refused_databases_are_not_copied_or_changed(tmp_path, problem):
    database = at_previous_revision(tmp_path)
    with closing(sqlite3.connect(database)) as db:
        if problem == 'unknown_revision':
            db.execute("UPDATE alembic_version SET version_num='9999_future'")
        elif problem == 'restored_archive':
            db.execute(f'PRAGMA user_version={RESTORED_USER_VERSION}')
        elif problem == 'no_alembic':
            db.execute('DROP TABLE alembic_version')
        else:
            db.execute("INSERT INTO managed_jobs (idempotency_key, run_id, request_json, status, created_at, "
                       "process_owner, owner_closed) VALUES ('k', 'r', '{}', 'ACTIVE', 'now', ?, 0)",
                       (json.dumps(identity()),))
        db.commit()
    before = database.read_bytes()
    with pytest.raises(MigrationRefused):
        prepare_database(str(database), tmp_path / 'snapshots')
    assert database.read_bytes() == before and not (tmp_path / 'snapshots').exists()


def test_frontend_reinstalls_only_when_lock_changes(tmp_path):
    (tmp_path / 'frontend').mkdir()
    (tmp_path / 'frontend/package-lock.json').write_text('{"v": 1}')
    stamp = tmp_path / 'stamp'
    assert dev.frontend_install_needed(tmp_path, stamp)
    (tmp_path / 'frontend/node_modules').mkdir()
    stamp.write_text(dev.lock_digest(tmp_path) + '\n')
    assert not dev.frontend_install_needed(tmp_path, stamp)
    (tmp_path / 'frontend/package-lock.json').write_text('{"v": 2}')
    assert dev.frontend_install_needed(tmp_path, stamp)


def test_config_and_environment_composition_are_exclusive(tmp_path, monkeypatch):
    monkeypatch.delenv('HARNESS_MANAGED_CONFIG', raising=False)
    argv, env = dev.api_command(tmp_path / 'db.sqlite3', tmp_path / 'local.toml')
    assert env['HARNESS_LOCAL_CONFIG'] == str(tmp_path / 'local.toml')
    assert env['HARNESS_DATABASE_URL'] == f'sqlite:///{tmp_path / "db.sqlite3"}' and '--factory' in argv
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'examples.managed_demo:build')
    with pytest.raises(SystemExit):
        dev.api_command(tmp_path / 'db.sqlite3', tmp_path / 'local.toml')


def child(code):
    # Each child also creates a grandchild in its group, to check that the whole group is stopped.
    return [sys.executable, '-c', 'import subprocess, sys, time; '
            'subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"]); ' + code]


def group_gone(pgid, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # macOS: EPERM while the group only keeps zombies not yet reaped
        time.sleep(0.05)
    return False


def test_one_service_exiting_stops_the_other_group(tmp_path):
    services = dev.Services()
    survivor = services.start('ui', child('time.sleep(60)'))
    services.start('api', child('time.sleep(0.5); sys.exit(3)'))
    assert services.run() == 3
    assert group_gone(survivor.pid)


def test_stop_request_terminates_both_groups(tmp_path):
    services = dev.Services()
    first = services.start('api', child('time.sleep(60)'))
    second = services.start('ui', child('time.sleep(60)'))
    services.request_stop(signal.SIGINT, None)
    assert services.run() == 0
    assert group_gone(first.pid) and group_gone(second.pid)
