"""H5.2: synthetic databases, checkouts, streams and XML only."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from session_client import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from my_harness.api.app import create_app
from my_harness.cli import main
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedConfig
from my_harness.storage.backup import (
    BackupError, RESTORED_USER_VERSION, create_backup, restore_backup, verify_bundle, restored_artifact,
)
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.managed_views import SQLiteManagedViews
from my_harness.storage.models import Base
from test_cli_agents import adapter, setup_invocation
from test_git import repo as git_repo
from test_junit import managed_run, simple_xml
from test_managed import context, repository
from onboarding_helpers import tree_state as tree

LOCAL = {'base_url': 'http://127.0.0.1:8013', 'headers': {'X-My-Harness': '1'}}


def db_path(migrated_database):
    return Path(migrated_database[0].removeprefix('sqlite:///'))


def dump_rows(path):
    with closing(sqlite3.connect(path)) as db:
        return {name: db.execute(f'SELECT * FROM "{name}"').fetchall() for name in Base.metadata.tables}


def backup(migrated_database, tmp_path, **kwargs):
    destination = tmp_path / 'backup'
    create_backup(db_path(migrated_database), destination, writers_stopped=True, **kwargs)
    return destination


def seal(bundle, change):
    """Recomputing external integrity shows that internal contracts are verified too."""
    manifest = json.loads((bundle / 'manifest.json').read_bytes())
    change(manifest)
    raw = json.dumps(manifest).encode()
    (bundle / 'manifest.json').write_bytes(raw)
    (bundle / 'COMPLETE').write_text(hashlib.sha256(raw).hexdigest())


def reseal_database(bundle):
    raw = (bundle / 'state.sqlite3').read_bytes()
    seal(bundle, lambda m: m['database'].update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw)))


def test_sqlite_backup_includes_live_wal_and_leaves_original_rows(migrated_database, tmp_path):
    source = db_path(migrated_database)
    with closing(sqlite3.connect(source, isolation_level=None)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO simulations VALUES('wal-row','Solo en WAL','2026-10-13', '[\"persistido\"]')")
        assert Path(str(source) + '-wal').stat().st_size > 0
        before = dump_rows(source)
        bundle = backup(migrated_database, tmp_path)
        assert dump_rows(bundle / 'state.sqlite3') == before == dump_rows(source)
    destination = tmp_path / 'restored'
    restore_backup(bundle, destination)
    assert dump_rows(destination / 'state.sqlite3') == before
    assert verify_bundle(destination)['kind'] == 'restored'
    with closing(sqlite3.connect(destination / 'state.sqlite3')) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == RESTORED_USER_VERSION


def test_junit_snapshots_events_and_http_queries_survive_restore(git_repo, migrated_database, tmp_path, monkeypatch):
    ctx, repo, _, job, agents = managed_run(git_repo, migrated_database, data=simple_xml(3))
    before = repo.get_run(job.run_id)
    events = repo.events(job.run_id)
    original = SQLiteManagedViews(repo.engine).test_original(job.run_id, 0, 0, 0)[0]
    original_rows, checkout = dump_rows(db_path(migrated_database)), tree(ctx.root)
    bundle = backup(migrated_database, tmp_path)
    assert len(agents.requests) == 2
    assert tree(ctx.root) == checkout
    ctx.path('ignored/junit.xml').unlink()
    dest = tmp_path / 'restored'
    restore_backup(bundle, dest)
    restored_engine = make_engine(f'sqlite:///{dest / "state.sqlite3"}')
    try:
        restored = SQLiteManagedRepository(restored_engine)
        assert restored.get_run(job.run_id) == before
        assert restored.events(job.run_id) == events
        assert dump_rows(dest / 'state.sqlite3') == original_rows
        assert SQLiteManagedViews(restored_engine).test_original(job.run_id, 0, 0, 0)[0] == original
    finally:
        restored_engine.dispose()
    # Not even an ambient configuration that could launch effects is imported.
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'module_that_must_never_be_imported:build')
    with TestClient(create_app(f'sqlite:///{dest / "state.sqlite3"}', tmp_path,
                              managed=ManagedConfig(supervisor=True)), **LOCAL) as http:
        assert http.get('/api/managed/supervisor').json()['enabled'] is False
        assert http.get(f'/api/managed/runs/{job.run_id}').json()['actions'] == []
        prefix = f'/api/managed/runs/{job.run_id}/cycles/0/validations/0/reports/0'
        assert len(http.get(prefix).json()['items']) == 3
        assert http.get(prefix + '/original').content == original
        for method, url in [('post', '/api/simulations'), ('post', f'/api/managed/runs/{job.run_id}/actions'),
                            ('put', '/api/legacy/projects/absent/observation')]:
            result = getattr(http, method)(url, json={})
            assert result.status_code == 409 and result.json()['code'] == 'restored_read_only'
    assert dump_rows(dest / 'state.sqlite3') == original_rows
    assert verify_bundle(dest)['kind'] == 'restored'
    repo.engine.dispose()


def test_cli_streams_unknown_attempt_and_lock_remain_verifiable(context, repository, migrated_database, tmp_path):
    port = adapter(tmp_path)
    job, claim, request = setup_invocation(repository, context, port)
    result = port.invoke(context, request)  # Synthetic Python process, never a real CLI.
    assert result.status == 'complete'
    repository.close_owner(claim)
    repository.quarantine(claim, 'Resultado sin checkpoint; incertidumbre sintética')
    before = dump_rows(db_path(migrated_database))
    roots = [port.artifact_root]
    bundle = backup(migrated_database, tmp_path, artifact_roots=roots)
    assert len(verify_bundle(bundle)['files']) == 3
    source_bytes = {i['source']: Path(i['source']).read_bytes() for i in verify_bundle(bundle)['files']}
    dest = tmp_path / 'restored'
    restore_backup(bundle, dest)
    assert dump_rows(dest / 'state.sqlite3') == before
    engine = make_engine(f'sqlite:///{dest / "state.sqlite3"}')
    try:
        restored = SQLiteManagedRepository(engine)
        assert restored.get_job(job.id).status == 'RECOVERY_REQUIRED'
        for source, raw in source_bytes.items():
            Path(source).unlink()  # The mapping never uses the original again.
            assert restored_artifact(engine, source).read_bytes() == raw
        # Historical references do not query original paths, nor their new links.
        Path(next(iter(source_bytes))).symlink_to(tmp_path / 'unrelated-absent')
        assert verify_bundle(dest)['files'] == verify_bundle(bundle)['files']
        with pytest.raises(OperationalError, match='readonly'):
            LocalSupervisor(restored, lambda *_: pytest.fail('No efectos al restaurar')).run_once()
        assert dump_rows(dest / 'state.sqlite3') == before
    finally:
        engine.dispose()




def test_missing_declaration_and_live_owner_are_rejected_without_copy(context, repository, migrated_database, tmp_path):
    path = db_path(migrated_database)
    with pytest.raises(BackupError, match='writers-stopped'):
        create_backup(path, tmp_path / 'undeclared')
    assert not (tmp_path / 'undeclared').exists()
    port = adapter(tmp_path)
    job, claim, _ = setup_invocation(repository, context, port)
    with pytest.raises(BackupError, match='Live'):
        create_backup(path, tmp_path / 'live', writers_stopped=True)
    assert not (tmp_path / 'live').exists()
    repository.close_owner(claim)
    repository.quarantine(claim, 'Sin invocar')


@pytest.mark.parametrize('corruption', ['database', 'manifest', 'complete', 'schema', 'codec', 'foreign-key', 'missing-table'])
def test_corrupt_or_incompatible_backup_never_creates_restore(migrated_database, tmp_path, corruption):
    bundle = backup(migrated_database, tmp_path)
    if corruption in ('database', 'manifest'):
        filename = 'state.sqlite3' if corruption == 'database' else 'manifest.json'
        with (bundle / filename).open('ab') as handle:
            handle.write(b'corrupt')
    elif corruption == 'complete':
        (bundle / 'COMPLETE').unlink()
    else:
        with closing(sqlite3.connect(bundle / 'state.sqlite3')) as db:
            if corruption == 'schema':
                db.execute("UPDATE alembic_version SET version_num='future'")
            elif corruption == 'codec':
                # Relational integrity is valid but the codec is from the future.
                db.execute("INSERT INTO managed_runs VALUES('r','/synthetic','t','p','{}','{}',?, 'STOPPED','stop',0,0,0,'now','now','task')", ('{"format":99,"history":{}}',))
            elif corruption == 'foreign-key':
                db.execute("INSERT INTO checkout_locks(root,job_id) VALUES('/synthetic',999)")
            else:
                db.execute('DROP TABLE simulations')
            db.commit()
        reseal_database(bundle)
    with pytest.raises(BackupError):
        restore_backup(bundle, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


@pytest.mark.parametrize('failure', ['missing', 'changed', 'symlink', 'hardlink', 'fifo', 'undeclared-root', 'during-copy'])
def test_artifact_failures_are_not_published(context, repository, migrated_database, tmp_path, failure):
    port = adapter(tmp_path)
    _, claim, request = setup_invocation(repository, context, port)
    assert port.invoke(context, request).status == 'complete'
    repository.close_owner(claim)
    repository.quarantine(claim, 'Sintético')
    prompt = port.artifact_root / request.id / 'prompt.txt'
    if failure == 'missing':
        prompt.unlink()
    elif failure == 'changed':
        prompt.write_bytes(b'changed')
    elif failure in ('symlink', 'hardlink'):
        external = tmp_path / 'external'
        external.write_bytes(prompt.read_bytes())
        prompt.unlink()
        if failure == 'symlink':
            prompt.symlink_to(external)
        else:
            os.link(external, prompt)
    elif failure == 'fifo':
        prompt.unlink()
        os.mkfifo(prompt)
    roots = [] if failure == 'undeclared-root' else [port.artifact_root]
    changed = False
    def hook(stage):
        nonlocal changed
        if stage == 'artifact_copied' and failure == 'during-copy' and not changed:
            changed = True
            prompt.write_bytes(b'changed during copy')
    with pytest.raises((BackupError, OSError)):
        backup(migrated_database, tmp_path, artifact_roots=roots, hook=hook)
    assert not (tmp_path / 'backup/COMPLETE').exists()
    with pytest.raises(BackupError):
        verify_bundle(tmp_path / 'backup')


def test_existing_destinations_and_checkout_destinations_are_preserved(migrated_database, tmp_path, context, repository):
    from test_managed import submit
    submit(repository, context)
    bundle = backup(migrated_database, tmp_path)
    for destination in (bundle, context.root, tmp_path / 'empty'):
        if not destination.exists():
            destination.mkdir()
        before = tree(destination)
        with pytest.raises(BackupError):
            restore_backup(bundle, destination)
        assert tree(destination) == before
    with pytest.raises(BackupError, match='checkouts'):
        restore_backup(bundle, context.root / 'new')
    assert not (context.root / 'new').exists()
    with pytest.raises(BackupError):
        create_backup(db_path(migrated_database), bundle, writers_stopped=True)


def test_write_lock_rejects_racing_database_writer(migrated_database, tmp_path):
    source = db_path(migrated_database)
    attempts = []
    def hook(stage):
        if stage == 'database_copied':
            with closing(sqlite3.connect(source, timeout=0)) as competing:
                with pytest.raises(sqlite3.OperationalError, match='locked'):
                    competing.execute("INSERT INTO simulations VALUES('race','race','now','[]')")
                attempts.append(True)
    bundle = backup(migrated_database, tmp_path, hook=hook)
    assert attempts == [True]
    assert dump_rows(bundle / 'state.sqlite3') == dump_rows(source)


def test_restored_guard_survives_moving_database_and_blocks_library_writes(migrated_database, tmp_path):
    bundle = backup(migrated_database, tmp_path)
    dest = tmp_path / 'restored'
    restore_backup(bundle, dest)
    moved = tmp_path / 'moved.sqlite3'
    moved.write_bytes((dest / 'state.sqlite3').read_bytes())
    engine = make_engine(f'sqlite:///{moved}')
    try:
        with engine.begin() as db:
            assert db.scalar(text('PRAGMA query_only')) == 1
            with pytest.raises(OperationalError, match='readonly'):
                db.execute(text("INSERT INTO simulations VALUES('no','no','now','[]')"))
    finally:
        engine.dispose()


def test_cli_backup_round_trip_and_errors_are_explicit(migrated_database, tmp_path, capsys):
    bundle, dest = tmp_path / 'backup', tmp_path / 'restored'
    assert main(['backup-create', str(db_path(migrated_database)), str(bundle)]) == 1
    assert 'writers-stopped' in capsys.readouterr().err
    assert main(['backup-create', str(db_path(migrated_database)), str(bundle), '--writers-stopped']) == 0
    assert json.loads(capsys.readouterr().out)['format'] == 2
    assert main(['backup-verify', str(bundle)]) == 0
    capsys.readouterr()
    assert main(['backup-restore', str(bundle), str(dest)]) == 0
    assert json.loads(capsys.readouterr().out)['execution_authorized'] is False
    assert main(['backup-restore', str(bundle), str(dest)]) == 1
    assert 'destination' in capsys.readouterr().err
    assert main(['backup-create', str(tmp_path / 'missing.sqlite3'), str(tmp_path / 'unused'), '--writers-stopped']) == 1
    assert not (tmp_path / 'missing.sqlite3').exists()


@pytest.mark.parametrize('tamper', ['missing-file', 'bytes', 'omitted-ref', 'escape', 'absolute-path', 'duplicate', 'version'])
def test_artifact_bundle_integrity_and_manifest_paths(context, repository, migrated_database, tmp_path, tamper):
    port = adapter(tmp_path)
    _, claim, request = setup_invocation(repository, context, port)
    port.invoke(context, request)
    repository.close_owner(claim)
    repository.quarantine(claim, 'Sin checkpoint sintético')
    bundle = backup(migrated_database, tmp_path, artifact_roots=[port.artifact_root])
    manifest = verify_bundle(bundle)
    if tamper == 'missing-file':
        (bundle / manifest['files'][0]['path']).unlink()
    elif tamper == 'bytes':
        (bundle / manifest['files'][0]['path']).write_bytes(b'corrupt')
    elif tamper == 'omitted-ref':
        seal(bundle, lambda m: m['files'].pop())
    elif tamper in ('escape', 'absolute-path'):
        seal(bundle, lambda m: m['files'][0].update(path='../external' if tamper == 'escape' else '/external'))
    elif tamper == 'duplicate':
        seal(bundle, lambda m: m['files'].append(m['files'][0]))
    else:
        seal(bundle, lambda m: m.update(format=99))
    with pytest.raises(BackupError):
        restore_backup(bundle, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def pending_process(context, repository, tmp_path, *, with_stream):
    port = adapter(tmp_path)
    job, claim, request = setup_invocation(repository, context, port)
    directory = port.artifact_root / request.id
    directory.mkdir(parents=True)
    prompt = 'Prompt sintético congelado'.encode()
    (directory / 'prompt.txt').write_bytes(prompt)
    repository.process_intent(claim, request.id, {'artifacts': str(directory),
        'prompt_path': str(directory / 'prompt.txt'), 'prompt_sha256': hashlib.sha256(prompt).hexdigest()})
    if with_stream:
        # The fsync precedes the checkpoint: there may be an unrecorded tail at the crash.
        (directory / 'stdout.bin').write_bytes(b'prefix-uncheckpointed-tail')
        repository.process_update(claim, request.id, 'stream_bytes', {'stream': 'stdout',
            'offset': 0, 'size': 6, 'sha256': hashlib.sha256(b'prefix').hexdigest()})
    repository.close_owner(claim)
    repository.quarantine(claim, 'Resultado incierto sintético')
    return port, job, directory


@pytest.mark.parametrize('with_stream', [False, True])
def test_partial_or_not_launched_process_retains_uncertainty_and_all_observed_bytes(context, repository, migrated_database, tmp_path, with_stream):
    port, job, directory = pending_process(context, repository, tmp_path, with_stream=with_stream)
    bundle = backup(migrated_database, tmp_path, artifact_roots=[port.artifact_root])
    manifest = verify_bundle(bundle)
    assert len(manifest['absent_optional']) == (1 if with_stream else 2)
    assert len(manifest['files']) == (2 if with_stream else 1)
    dest = tmp_path / 'restored'
    restore_backup(bundle, dest)
    engine = make_engine(f'sqlite:///{dest / "state.sqlite3"}')
    try:
        assert SQLiteManagedRepository(engine).get_job(job.id).status == 'RECOVERY_REQUIRED'
        if with_stream:
            assert restored_artifact(engine, directory / 'stdout.bin').read_bytes() == b'prefix-uncheckpointed-tail'
    finally:
        engine.dispose()


@pytest.mark.parametrize('failure', ['missing', 'range-hash', 'offset-gap'])
def test_observed_stream_range_is_required_even_without_capture(context, repository, migrated_database, tmp_path, failure):
    port, _, directory = pending_process(context, repository, tmp_path, with_stream=True)
    if failure == 'missing':
        (directory / 'stdout.bin').unlink()
    elif failure == 'range-hash':
        (directory / 'stdout.bin').write_bytes(b'bad-prefix')
    else:
        with repository.engine.begin() as db:
            payload = json.loads(db.scalar(text("SELECT payload FROM managed_events WHERE kind='stream_bytes'")))
            payload['offset'] = 2
            db.execute(text("UPDATE managed_events SET payload=:p WHERE kind='stream_bytes'"), {'p': json.dumps(payload)})
    with pytest.raises(BackupError):
        backup(migrated_database, tmp_path, artifact_roots=[port.artifact_root])
    assert not (tmp_path / 'backup/COMPLETE').exists()


def test_embedded_junit_corruption_is_detected_after_database_hash_is_resealed(git_repo, migrated_database, tmp_path):
    _, repo, _, _, _ = managed_run(git_repo, migrated_database, data=simple_xml())
    bundle = backup(migrated_database, tmp_path)
    with closing(sqlite3.connect(bundle / 'state.sqlite3')) as db:
        history = json.loads(db.execute('SELECT history_json FROM managed_runs').fetchone()[0])
        history['history']['cycles'][0]['validation']['entries'][0]['reports'][0]['original_base64'] = 'Y29ycnVwdA=='
        db.execute('UPDATE managed_runs SET history_json=?', (json.dumps(history),))
        db.commit()
    reseal_database(bundle)
    with pytest.raises(BackupError, match='JUnit'):
        restore_backup(bundle, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()
    repo.engine.dispose()


def test_limits_do_not_publish_truncated_bundle(context, repository, migrated_database, tmp_path, monkeypatch):
    from my_harness.storage import backup as module
    port, _, _ = pending_process(context, repository, tmp_path, with_stream=True)
    monkeypatch.setattr(module, 'MAX_TOTAL_BYTES', 1)
    with pytest.raises(BackupError, match='total limit'):
        backup(migrated_database, tmp_path, artifact_roots=[port.artifact_root])
    assert not (tmp_path / 'backup/COMPLETE').exists()


def test_restore_does_not_trust_changed_file_after_initial_verification(context, repository, migrated_database, tmp_path, monkeypatch):
    from my_harness.storage import backup as module
    port, _, _ = pending_process(context, repository, tmp_path, with_stream=True)
    bundle = backup(migrated_database, tmp_path, artifact_roots=[port.artifact_root])
    original_verify = module.verify_bundle
    def racing_verify(path):
        manifest = original_verify(path)
        (bundle / manifest['files'][0]['path']).write_bytes(b'raced')
        return manifest
    monkeypatch.setattr(module, 'verify_bundle', racing_verify)
    with pytest.raises(BackupError, match='changed'):
        restore_backup(bundle, tmp_path / 'restored')
    assert not (tmp_path / 'restored/COMPLETE').exists()


def test_backup_itself_cannot_start_pending_jobs(context, repository, migrated_database, tmp_path, monkeypatch):
    from test_managed import submit
    job = submit(repository, context)
    bundle = backup(migrated_database, tmp_path)
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'do_not_load:build')
    with TestClient(create_app(f'sqlite:///{bundle / "state.sqlite3"}', tmp_path,
                              managed=ManagedConfig(supervisor=True)), **LOCAL) as http:
        assert http.get('/api/managed/supervisor').json()['enabled'] is False
        assert http.get(f'/api/managed/jobs/{job.id}').json()['status'] == 'QUEUED'
        assert http.post('/api/simulations', json={'title': 'no'}).status_code == 409
    assert verify_bundle(bundle)['kind'] == 'backup'


def test_unmanifested_wal_is_rejected_even_if_main_database_hash_matches(migrated_database, tmp_path):
    bundle = backup(migrated_database, tmp_path)
    initial = (bundle / 'state.sqlite3').read_bytes()
    with closing(sqlite3.connect(bundle / 'state.sqlite3', isolation_level=None)) as outside_writer:
        outside_writer.execute('PRAGMA wal_autocheckpoint=0')
        outside_writer.execute("INSERT INTO simulations VALUES('outside','outside','now','[]')")
        assert (bundle / 'state.sqlite3').read_bytes() == initial
        with pytest.raises(BackupError, match='WAL'):
            restore_backup(bundle, tmp_path / 'restored')
        assert not (tmp_path / 'restored').exists()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_source_sqlite_sidecars_are_validated_before_connecting(migrated_database, tmp_path, kind):
    source = db_path(migrated_database)
    sidecar = Path(str(source) + '-wal')
    assert not sidecar.exists()
    external = tmp_path / 'external'
    external.write_bytes(b'conservar original externo')
    if kind == 'symlink':
        sidecar.symlink_to(external)
    elif kind == 'hardlink':
        os.link(external, sidecar)
    else:
        os.mkfifo(sidecar)
    with pytest.raises(BackupError):
        backup(migrated_database, tmp_path)
    assert not (tmp_path / 'backup').exists()
    assert external.read_bytes() == b'conservar original externo'


@pytest.mark.parametrize('kind', ['backup', 'restored'])
def test_archive_signal_and_run_evidence_without_checkout(git_repo, migrated_database, tmp_path, monkeypatch, kind):
    """T012: identical bounded reads, no original checkout/configuration or history decoding."""
    import shutil
    from test_managed import submit
    from test_run_projection import Probe

    ctx, repo, supervisor, job, _ = managed_run(git_repo, migrated_database, data=simple_xml(3))
    repo.submit_commit(job.run_id, expected_version=repo.get_run(job.run_id).version,
                             key='archive-commit')
    assert supervisor.run_once().status == 'DONE'
    queued = submit(repo, ctx, key='archive-queued')
    prefix = f'/api/managed/runs/{job.run_id}'
    report = prefix + '/cycles/0/validations/0/reports/0'
    paths = [prefix, prefix + '/jobs?limit=1', prefix + '/attempts?limit=1', prefix + '/events?limit=1',
             prefix + '/cycles?limit=1', prefix + '/cycles/0/diff?offset=0', report + '?limit=1',
             report + '/original', f'/api/managed/metrics/attempts?run_id={job.run_id}&limit=1',
             f'/api/managed/runs/{queued.run_id}']
    with TestClient(create_app(migrated_database[0], tmp_path, managed=ManagedConfig()), **LOCAL) as http:
        assert http.get('/api/managed/supervisor').json()['read_only_archive'] is False
        responses = {path: http.get(path) for path in paths}
        assert all(response.status_code == 200 for response in responses.values())
        expected = {path: response.content for path, response in responses.items()}
        assert responses[prefix].json()['status'] == 'COMMITTED'
        assert responses[paths[-1]].json()['status'] == 'QUEUED'
    bundle = backup(migrated_database, tmp_path)
    destination = bundle
    if kind == 'restored':
        destination = tmp_path / 'restored'
        restore_backup(bundle, destination)
    before = dump_rows(destination / 'state.sqlite3')
    shutil.rmtree(ctx.root)
    monkeypatch.setenv('HARNESS_MANAGED_CONFIG', 'must_not_import:build')
    archive_engine = make_engine(f'sqlite:///{destination / "state.sqlite3"}')
    monkeypatch.setattr('my_harness.api.app.make_engine', lambda *_: archive_engine)
    app = create_app(f'sqlite:///{destination / "state.sqlite3"}', tmp_path,
                     managed=ManagedConfig(supervisor=True, ports_factory=lambda *_: pytest.fail('No ports')))
    with TestClient(app, **LOCAL) as http:
        status = http.get('/api/managed/supervisor').json()
        assert status == {'read_only_archive': True, 'enabled': False, 'alive': False, 'last_error': None,
                          'ports_configured': False, 'commit_writer_configured': False, 'configuration_mode': None}
        assert http.get('/api/managed/projects').json() == []
        probe = Probe(archive_engine, monkeypatch)
        for path in paths:
            assert http.get(path).content == expected[path], path
        assert probe.clean()
        assert http.get('/api/managed/runs/unknown').status_code == 404
        for path in [prefix + '/actions', '/api/managed/runs', '/api/managed/registry/apply']:
            response = http.post(path, json={})
            assert response.status_code == 409
        with archive_engine.connect() as db:
            assert db.scalar(text('PRAGMA query_only')) == 1
    assert dump_rows(destination / 'state.sqlite3') == before
    repo.engine.dispose()
