"""P010-T012: explicit installed migration; only synthetic databases and process identities."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from alembic import command
import pytest

from my_harness.adapters.processes import identity
from my_harness.cli import main
from my_harness.storage import migrate, run_projection
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.schema import SCHEMA_REVISION
from test_run_projection import FEATURES, insert_run, synthetic


@pytest.fixture
def previous(migrated_database):
    url, config = migrated_database
    command.downgrade(config, '0022_project_preparation')
    return Path(url.removeprefix('sqlite:///'))


def invoke(database, snapshots, *, stopped=True):
    args = ['migrate', '--database', str(database), '--snapshots', str(snapshots)]
    return main(args + (['--writers-stopped'] if stopped else []))


def test_migrate_backfills_all_formats_preserves_frozen_bytes_and_serve_accepts(
        previous, tmp_path, monkeypatch, capsys):
    histories = {f'run-{fmt}': synthetic(f'run-{fmt}', fmt) for fmt in FEATURES}
    with closing(sqlite3.connect(previous)) as db:
        for run_id, history in histories.items():
            insert_run(db, run_id, history)
        db.commit()
        frozen = db.execute('SELECT id,context_json,versions_json,history_json FROM managed_runs ORDER BY id').fetchall()
    snapshots = tmp_path / 'copies'
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('HARNESS_DATABASE_URL', f'sqlite:///{tmp_path / "wrong.sqlite3"}')
    assert invoke(previous, snapshots) == 0
    result = json.loads(capsys.readouterr().out)
    assert (result['action'], result['previous'], result['revision']) == (
        'migrated', '0022_project_preparation', SCHEMA_REVISION)
    snapshot = Path(result['snapshot'])
    manifest = json.loads(snapshot.with_suffix('.json').read_text())
    assert manifest['format'] == 'premigration-1'
    assert manifest['sha256'] == hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert manifest['size_bytes'] == snapshot.stat().st_size
    with closing(sqlite3.connect(snapshot)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0022_project_preparation'
        assert db.execute('SELECT id,context_json,versions_json,history_json FROM managed_runs ORDER BY id').fetchall() == frozen
    with closing(sqlite3.connect(previous)) as db:
        assert db.execute('SELECT id,context_json,versions_json,history_json FROM managed_runs ORDER BY id').fetchall() == frozen
        for run_id, history in histories.items():
            run_projection.verify(db, run_id, history)
    assert not (tmp_path / 'wrong.sqlite3').exists()
    # Exercise serve's real schema gate; no network listener or service is started.
    from my_harness import launcher
    import uvicorn
    package = tmp_path / 'package'
    (package / 'web').mkdir(parents=True)
    (package / 'web/index.html').write_text('synthetic assets')
    monkeypatch.setattr(launcher, '__file__', str(package / 'launcher.py'))
    calls = []
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: calls.append(kwargs))
    launcher.serve(str(previous), 8013)
    assert calls[0]['host'] == '127.0.0.1'
    before = previous.read_bytes()
    assert invoke(previous, snapshots) == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'current'
    assert previous.read_bytes() == before and len(list(snapshots.glob('*.sqlite3'))) == 1


@pytest.mark.parametrize('problem', ['declaration', 'unknown', 'restored', 'unversioned', 'live_owner',
                                     'live_preparation', 'live_group', 'live_command'])
def test_refusals_preserve_database_and_do_not_create_snapshots(previous, tmp_path, capsys, problem):
    owner = json.dumps(identity())
    group = json.dumps({**identity(), 'pgid': os.getpgrp()})
    with closing(sqlite3.connect(previous)) as db:
        if problem == 'unknown':
            db.execute("UPDATE alembic_version SET version_num='9999_future'")
        elif problem == 'restored':
            db.execute(f'PRAGMA user_version={RESTORED_USER_VERSION}')
        elif problem == 'unversioned':
            db.execute('DROP TABLE alembic_version')
        elif problem == 'live_owner':
            db.execute("INSERT INTO managed_jobs (idempotency_key,run_id,request_json,status,created_at,process_owner) "
                       "VALUES ('key','synthetic','{}','ACTIVE','now',?)", (owner,))
        elif problem == 'live_preparation':
            # Reuse the real table, including its required authority fields.
            columns = db.execute('PRAGMA table_info(project_preparation_operations)').fetchall()
            values = {row[1]: 'synthetic' for row in columns if row[3] and row[4] is None}
            values.update(id='prep', process_owner=owner, owner_closed=0)
            names = ','.join(values)
            db.execute(f'INSERT INTO project_preparation_operations ({names}) VALUES ({",".join("?" for _ in values)})',
                       tuple(values.values()))
        elif problem == 'live_group':
            db.execute("INSERT INTO managed_processes (id,attempt_id,job_id,spec,status,identity) "
                       "VALUES ('process','attempt',1,'{}','RUNNING',?)", (group,))
        elif problem == 'live_command':
            db.execute("INSERT INTO managed_events (run_id,sequence,kind,recorded_at,payload) "
                       "VALUES ('run',1,'command_process_spawned','now',?)", ('{"identity":' + group + '}',))
        db.commit()
    before = previous.read_bytes()
    snapshots = tmp_path / 'copies'
    assert invoke(previous, snapshots, stopped=problem != 'declaration') == 1
    assert capsys.readouterr().err
    assert previous.read_bytes() == before and not snapshots.exists()


@pytest.mark.parametrize('kind', ['missing', 'relative', 'directory', 'link', 'dangling', 'parent_link', 'sidecar_link'])
def test_invalid_database_paths_are_rejected(previous, tmp_path, kind):
    database = previous
    if kind == 'missing':
        database = tmp_path / 'absent' / 'missing.sqlite3'
    elif kind == 'relative':
        database = Path('relative.sqlite3')
    elif kind == 'directory':
        database = tmp_path
    elif kind in ('link', 'dangling'):
        database = tmp_path / 'linked.sqlite3'
        database.symlink_to(previous if kind == 'link' else tmp_path / 'absent')
    elif kind == 'parent_link':
        alias = tmp_path / 'alias'
        alias.symlink_to(tmp_path, target_is_directory=True)
        database = alias / previous.name
    else:
        Path(str(database) + '-wal').symlink_to(tmp_path / 'absent-wal')
    before = previous.read_bytes()
    assert invoke(database, tmp_path / 'copies') == 1
    assert previous.read_bytes() == before and not (tmp_path / 'copies').exists()
    assert not (tmp_path / 'absent').exists()


@pytest.mark.parametrize('kind', ['relative', 'git', 'registered', 'link'])
def test_snapshot_destinations_are_explicit_unlinked_and_outside_checkouts(previous, tmp_path, kind):
    directory = tmp_path / 'checkout' / 'copies'
    if kind == 'relative':
        directory = Path('copies')
    elif kind == 'git':
        directory.parent.mkdir()
        (directory.parent / '.git').write_text('gitdir: synthetic')
    elif kind == 'registered':
        with closing(sqlite3.connect(previous)) as db:
            insert_run(db, 'run', synthetic('run', 8))
            db.execute('UPDATE managed_runs SET root=?', (str(directory.parent),))
            db.commit()
    else:
        directory.parent.mkdir()
        directory.symlink_to(tmp_path / 'elsewhere', target_is_directory=True)
    before = previous.read_bytes()
    assert invoke(previous, directory) == 1
    assert previous.read_bytes() == before and not directory.exists()


def test_failure_keeps_snapshot_and_database_without_automatic_restore(previous, tmp_path, monkeypatch, capsys):
    original = previous.read_bytes()
    with closing(sqlite3.connect(previous)) as db:
        original_dump = tuple(db.iterdump())

    def fail(*args):
        with closing(sqlite3.connect(previous)) as db:
            db.execute("INSERT INTO simulations VALUES ('partial','synthetic','now','[]')")
            db.commit()
        raise RuntimeError('synthetic failure')
    monkeypatch.setattr(migrate.command, 'upgrade', fail)
    assert invoke(previous, tmp_path / 'copies') == 1
    assert 'database and snapshot kept' in capsys.readouterr().err
    [snapshot] = (tmp_path / 'copies').glob('*.sqlite3')
    with closing(sqlite3.connect(snapshot)) as db:
        assert tuple(db.iterdump()) == original_dump
    assert previous.read_bytes() != original
    with closing(sqlite3.connect(previous)) as db:
        assert db.execute('SELECT title FROM simulations').fetchall() == [('synthetic',)]


def test_snapshot_failure_never_runs_upgrade(previous, tmp_path, monkeypatch):
    original = previous.read_bytes()
    def fail(*args):
        raise OSError('synthetic disk full')
    monkeypatch.setattr(migrate, '_snapshot', fail)
    monkeypatch.setattr(migrate.command, 'upgrade', lambda *args: pytest.fail('upgrade before verified snapshot'))
    assert invoke(previous, tmp_path / 'copies') == 1
    assert previous.read_bytes() == original


def test_real_migration_failure_preserves_original_history_and_snapshot(previous, tmp_path, capsys):
    with closing(sqlite3.connect(previous)) as db:
        insert_run(db, 'invalid', '{"format":999}')
        db.commit()
    assert invoke(previous, tmp_path / 'copies') == 1
    assert 'database and snapshot kept' in capsys.readouterr().err
    [snapshot] = (tmp_path / 'copies').glob('*.sqlite3')
    for path in (previous, snapshot):
        with closing(sqlite3.connect(path)) as db:
            assert db.execute('SELECT history_json FROM managed_runs').fetchall() == [('{"format":999}',)]
            assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0022_project_preparation'
            assert db.execute("SELECT name FROM sqlite_master WHERE name='run_projections'").fetchall() == []


def test_current_database_creates_no_snapshot_directory(migrated_database, tmp_path, capsys):
    database = Path(migrated_database[0].removeprefix('sqlite:///'))
    original = database.read_bytes()
    assert invoke(database, tmp_path / 'copies') == 0
    assert json.loads(capsys.readouterr().out)['action'] == 'current'
    assert not (tmp_path / 'copies').exists() and database.read_bytes() == original


@pytest.mark.parametrize('revision', ['0001_simulations', '0004_managed_queue'])
def test_old_known_schemas_without_owner_columns_migrate(previous, tmp_path, revision):
    command.downgrade(migrate._config(f'sqlite:///{previous}'), revision)
    assert invoke(previous, tmp_path / 'copies') == 0
