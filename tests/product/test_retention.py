"""H5.3: deletion is confined to synthetic CLI captures in temporary directories."""

from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3

from session_client import TestClient
import pytest

from my_harness.api.app import create_app
from my_harness.cli import main
from my_harness.core.engine.contracts import Attempt, stop_history
from my_harness.storage.backup import BackupError, create_backup, restore_backup, verify_bundle
from my_harness.storage.retention import apply_retention, preview_retention, inspect_logs
from test_backup import db_path, dump_rows, reseal_database, seal, LOCAL
from test_cli_agents import adapter, setup_invocation
from test_managed import context, repository


@pytest.fixture
def sealed(context, repository, migrated_database, tmp_path):
    port = adapter(tmp_path)
    job, claim, request = setup_invocation(repository, context, port)
    result = port.invoke(context, request)
    repository.close_owner(claim)
    history = repository.get_run(job.run_id).history
    history = stop_history(replace(history, attempts=(Attempt(request, result),)), 'executor', 'Synthetic stop')
    repository.finish(claim, history)
    return db_path(migrated_database), port, job, request


def options(sealed):
    return dict(artifact_roots=[sealed[1].artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)


def preview(sealed, **kwargs):
    return preview_retention(sealed[0], **{**options(sealed), **kwargs})


def apply(sealed, **kwargs):
    return apply_retention(sealed[0], **{**options(sealed), 'preview_sha256': preview(sealed)['preview_sha256'],
                                     'reason': 'Synthetic explicit retention', 'confirmed': True,
                                     'writers_stopped': True, **kwargs})


def mutate(database, sql, params=()):
    with closing(sqlite3.connect(database)) as db:
        db.execute(sql, params)
        db.commit()


def test_policy_preview_preserves_all_bytes_and_is_deterministic(sealed):
    original = dump_rows(sealed[0])
    shown = preview(sealed)
    assert shown == preview(sealed)
    assert len(shown['items']) == 2 and all(i['eligible'] for i in shown['items'])
    assert shown['retire_bytes'] == sum(i['size_bytes'] for i in shown['items'])
    assert all(Path(i['source']).exists() for i in shown['items'])
    assert dump_rows(sealed[0]) == original
    assert not any(i['eligible'] for i in preview(sealed, min_bytes=1000000)['items'])
    assert not any(i['eligible'] for i in preview(sealed, before='2000-01-01T00:00:00Z')['items'])


def test_apply_preserves_contracts_results_hashes_history_and_event_order(sealed, repository):
    old = dump_rows(sealed[0])
    history = repository.get_run(sealed[2].run_id).history
    shown = preview(sealed)
    result = apply(sealed)
    assert result['retired_bytes'] == result['observed_removed_bytes'] == shown['retire_bytes']
    new = dump_rows(sealed[0])
    for table in old:
        if table not in ('managed_runs', 'managed_events'):
            assert new[table] == old[table]
    assert repository.get_run(sealed[2].run_id).history == history
    assert all(not Path(i['source']).exists() for i in shown['items'])
    assert (sealed[1].artifact_root / sealed[3].id / 'prompt.txt').exists()
    events = repository.events(sealed[2].run_id)
    assert [e['sequence'] for e in events] == list(range(1, events[-1]['sequence'] + 1))
    assert [i['state'] for i in inspect_logs(sealed[0], sealed[3].id)] == ['purged', 'purged']
    assert apply(sealed)['retired_bytes'] == 0  # A fresh preview authorizes an empty operation.
    assert dump_rows(sealed[0]) == new


@pytest.mark.parametrize('kwargs', [{'confirmed': False}, {'writers_stopped': False}, {'reason': ''}, {'preview_sha256': '0' * 64}])
def test_missing_or_stale_authorization_has_no_effect(sealed, kwargs):
    before = dump_rows(sealed[0])
    with pytest.raises(ValueError):
        apply(sealed, **kwargs)
    assert dump_rows(sealed[0]) == before
    assert all(Path(i['source']).exists() for i in preview(sealed)['items'])


@pytest.mark.parametrize('sql', [
    "UPDATE managed_runs SET status='RECOVERY_REQUIRED'",
    "UPDATE managed_jobs SET status='QUEUED'",
    "UPDATE managed_attempts SET result_json=NULL",
    "UPDATE managed_attempts SET status='UNKNOWN'",
    "UPDATE managed_processes SET status='UNCERTAIN'",
    "INSERT INTO checkout_locks(root,job_id) SELECT root,(SELECT id FROM managed_jobs LIMIT 1) FROM managed_runs",
])
def test_active_uncertain_or_locked_evidence_is_excluded(sealed, sql):
    mutate(sealed[0], sql)
    assert not any(i['eligible'] for i in preview(sealed)['items'])
    assert apply(sealed)['retired_bytes'] == 0
    assert all(Path(i['source']).exists() for i in preview(sealed)['items'])


def test_open_owner_and_unknown_group_refuse_application(sealed, monkeypatch):
    mutate(sealed[0], 'UPDATE managed_jobs SET owner_closed=0')
    with pytest.raises(ValueError, match='Open service owner'):
        apply(sealed)
    mutate(sealed[0], 'UPDATE managed_jobs SET owner_closed=1')
    monkeypatch.setattr('my_harness.adapters.processes.liveness', lambda *a, **kw: 'unknown')
    assert not any(i['eligible'] for i in preview(sealed)['items'])
    with pytest.raises(ValueError, match='uncertain'):
        apply(sealed)


@pytest.mark.parametrize('change', ['missing', 'corrupt', 'symlink', 'hardlink', 'fifo', 'parent-link'])
def test_loss_replacement_and_unsafe_files_are_never_treated_as_purge(sealed, tmp_path, change):
    old_preview = preview(sealed)['preview_sha256']
    source = Path(preview(sealed)['items'][0]['source'])
    if change == 'parent-link':
        parent = source.parent
        moved = tmp_path / 'moved-capture'
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
    else:
        source.unlink()
        if change == 'corrupt':
            source.write_bytes(b'other version')
        elif change == 'symlink':
            source.symlink_to(tmp_path / 'external')
        elif change == 'hardlink':
            external = tmp_path / 'external'
            external.write_bytes(b'private synthetic bytes')
            os.link(external, source)
        elif change == 'fifo':
            os.mkfifo(source)
    shown = preview(sealed)
    assert not shown['items'][0]['eligible']
    states = inspect_logs(sealed[0], sealed[3].id)
    assert states[0]['state'] in ('missing', 'unverified')
    assert states[0]['authorization'] is None
    with pytest.raises(ValueError, match='Stale preview'):
        apply(sealed, preview_sha256=old_preview)
    with pytest.raises(BackupError):
        create_backup(sealed[0], tmp_path / 'bad-backup', artifact_roots=[sealed[1].artifact_root], writers_stopped=True)


@pytest.mark.parametrize('point', ['intents_saved', 'bytes_removed'])
def test_crash_requires_fresh_preview_and_explicit_reconciliation(sealed, tmp_path, point):
    old_preview = preview(sealed)['preview_sha256']
    def crash(stage):
        if stage == point:
            raise RuntimeError('Synthetic crash')
    with pytest.raises(RuntimeError, match='Synthetic crash'):
        apply(sealed, hook=crash)
    assert all(i['state'] == 'pending' for i in inspect_logs(sealed[0], sealed[3].id))
    with pytest.raises(BackupError, match='pending'):
        create_backup(sealed[0], tmp_path / 'pending-backup', artifact_roots=[sealed[1].artifact_root], writers_stopped=True)
    with pytest.raises(ValueError, match='Stale preview'):
        apply(sealed, preview_sha256=old_preview)
    result = apply(sealed)
    assert len(result['removed']) == 2
    assert all(i['state'] == 'purged' for i in inspect_logs(sealed[0], sealed[3].id))
    if point == 'bytes_removed':
        assert result['observed_removed_bytes'] < result['retired_bytes']
        assert any(i['observed_removed_bytes'] is None for i in result['removed'])


def test_mutation_between_intent_and_effect_is_not_deleted(sealed):
    source = Path(preview(sealed)['items'][0]['source'])
    def change(stage):
        if stage == 'intents_saved':
            source.write_bytes(b'external synthetic change')
    with pytest.raises(ValueError, match='Eligibility'):
        apply(sealed, hook=change)
    assert source.read_bytes() == b'external synthetic change'
    assert not preview(sealed)['items'][0]['eligible']


def test_backup_restore_and_queries_keep_authorized_absences(sealed, tmp_path):
    original_bundle = tmp_path / 'original-backup'
    create_backup(sealed[0], original_bundle, artifact_roots=[sealed[1].artifact_root], writers_stopped=True)
    original_manifest = verify_bundle(original_bundle)
    apply(sealed)
    bundle = tmp_path / 'purged-backup'
    manifest = create_backup(sealed[0], bundle, artifact_roots=[sealed[1].artifact_root], writers_stopped=True)
    assert len(manifest['files']) == 1 and len(manifest['absent_purged']) == 2
    assert verify_bundle(bundle) == manifest
    destination = tmp_path / 'restored-purged'
    restore_backup(bundle, destination)
    restored = destination / 'state.sqlite3'
    assert all(i['state'] == 'purged' for i in inspect_logs(restored, sealed[3].id))
    assert verify_bundle(original_bundle) == original_manifest
    with TestClient(create_app(f'sqlite:///{restored}', tmp_path), **LOCAL) as http:
        url = f'/api/managed/runs/{sealed[2].run_id}/attempts/{sealed[3].id}/logs'
        response = http.get(url)
        assert response.status_code == 200
        assert all(i['state'] == 'purged' for i in response.json())
        assert http.get(url.replace(sealed[2].run_id, 'other')).status_code == 404
    with pytest.raises(ValueError):
        apply_retention(restored, **options(sealed), preview_sha256='0'*64,
                        reason='Never purge restored bundles', confirmed=True, writers_stopped=True)
    assert verify_bundle(destination)['kind'] == 'restored'


def test_old_format_one_bundle_without_retention_field_still_verifies(sealed, tmp_path):
    bundle = tmp_path / 'old-backup'
    create_backup(sealed[0], bundle, artifact_roots=[sealed[1].artifact_root], writers_stopped=True)
    seal(bundle, lambda m: m.pop('absent_purged'))
    verify_bundle(bundle)
    destination = tmp_path / 'old-restored'
    restore_backup(bundle, destination)
    for item in preview(sealed)['items']:
        Path(item['source']).unlink()
    assert all(i['state'] == 'retained' for i in inspect_logs(destination / 'state.sqlite3', sealed[3].id))


@pytest.mark.parametrize('tamper', ['manifest', 'unauthorized', 'hash', 'intent', 'bytes', 'range'])
def test_backup_does_not_admit_forged_purge_or_missing_retained_bytes(sealed, tmp_path, tamper):
    apply(sealed)
    bundle = tmp_path / 'backup'
    create_backup(sealed[0], bundle, artifact_roots=[sealed[1].artifact_root], writers_stopped=True)
    if tamper == 'manifest':
        seal(bundle, lambda m: m.update(absent_purged={}))
    elif tamper == 'bytes':
        item = verify_bundle(bundle)['files'][0]
        (bundle / item['path']).unlink()
    else:
        database = bundle / 'state.sqlite3'
        if tamper in ('unauthorized', 'intent'):
            mutate(database, "DELETE FROM managed_events WHERE kind=?", ('log_retention_intent' if tamper == 'intent' else 'log_retention_removed',))
        else:
            with closing(sqlite3.connect(database)) as db:
                kind = 'stream_bytes' if tamper == 'range' else 'log_retention_removed'
                row = db.execute('SELECT id,payload FROM managed_events WHERE kind=? LIMIT 1', (kind,)).fetchone()
                p = json.loads(row[1]); p['sha256'] = '0'*64
                db.execute('UPDATE managed_events SET payload=? WHERE id=?', (json.dumps(p), row[0])); db.commit()
        reseal_database(bundle)
    with pytest.raises(BackupError):
        verify_bundle(bundle)
    with pytest.raises(BackupError):
        restore_backup(bundle, tmp_path / 'must-not-exist')
    assert not (tmp_path / 'must-not-exist').exists()


def test_reappearing_purged_path_is_not_adopted_by_backup_or_query(sealed, tmp_path):
    source = Path(preview(sealed)['items'][0]['source'])
    apply(sealed)
    source.write_bytes(b'replacement bytes')
    assert inspect_logs(sealed[0], sealed[3].id)[0]['state'] == 'purged'
    with pytest.raises(BackupError, match='reappeared'):
        create_backup(sealed[0], tmp_path / 'replacement-backup', artifact_roots=[sealed[1].artifact_root], writers_stopped=True)
    assert apply(sealed)['retired_bytes'] == 0
    assert source.read_bytes() == b'replacement bytes'


def test_cli_preview_apply_and_inspect_use_explicit_database(sealed, capsys):
    common = [str(sealed[0]), '--artifact-root', str(sealed[1].artifact_root), '--before', '2100-01-01T00:00:00Z', '--min-bytes', '1']
    assert main(['logs-preview', *common]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert main(['logs-apply', *common, '--preview-sha256', shown['preview_sha256'], '--reason', 'Synthetic CLI confirmation', '--confirmed', '--writers-stopped']) == 0
    assert json.loads(capsys.readouterr().out)['retired_bytes'] > 0
    assert main(['logs-inspect', str(sealed[0]), sealed[3].id]) == 0
    assert all(i['state'] == 'purged' for i in json.loads(capsys.readouterr().out))


def test_write_lock_excludes_a_second_retention_writer(sealed):
    with closing(sqlite3.connect(sealed[0], isolation_level=None)) as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            apply(sealed)
        db.rollback()


@pytest.mark.parametrize('kwargs', [{'before': '2026-01-01'}, {'min_bytes': 0}, {'artifact_roots': ['/']}, {'artifact_roots': []}])
def test_invalid_policy_and_unbounded_roots_are_rejected(sealed, kwargs):
    with pytest.raises(ValueError):
        preview(sealed, **kwargs)


def test_http_explicit_inspection_distinguishes_retained_missing_and_corrupt(sealed, tmp_path):
    with TestClient(create_app(f'sqlite:///{sealed[0]}', tmp_path), **LOCAL) as http:
        url = f'/api/managed/runs/{sealed[2].run_id}/attempts/{sealed[3].id}/logs'
        assert all(i['state'] == 'retained' for i in http.get(url).json())
        shown = preview(sealed)
        Path(shown['items'][0]['source']).unlink()
        Path(shown['items'][1]['source']).write_bytes(b'wrong synthetic version')
        states = http.get(url).json()
        assert [i['state'] for i in states] == ['missing', 'unverified']
        assert all(i['sha256'] == old['sha256'] for i, old in zip(states, shown['items']))
        assert http.get(url, headers={'Host': 'external.invalid'}).status_code == 403


def test_shared_reference_is_preserved(sealed, monkeypatch):
    from my_harness.storage import retention
    original = retention._references
    def shared(db):
        refs = original(db)
        source = next(k for k in refs if k.endswith('stdout.bin'))
        refs[source]['labels'].append('migration:synthetic:preserved')
        return refs
    monkeypatch.setattr(retention, '_references', shared)
    shown = preview(sealed)
    assert not shown['items'][0]['eligible']
    assert 'shared' in shown['items'][0]['diagnostic']
    apply(sealed)
    assert Path(shown['items'][0]['source']).exists()


@pytest.mark.parametrize('limit', ['files', 'total', 'file'])
def test_limits_are_explicit_and_never_purge_excluded_bytes(sealed, monkeypatch, limit):
    from my_harness.storage import retention
    if limit == 'files':
        monkeypatch.setattr(retention, 'MAX_FILES', 1)
        with pytest.raises(ValueError, match='Too many'):
            preview(sealed)
    elif limit == 'total':
        monkeypatch.setattr(retention, 'MAX_TOTAL_BYTES', 1)
        with pytest.raises(ValueError, match='limits'):
            preview(sealed)
    else:
        # _read's default is frozen at definition time; use its explicit bounded helper.
        original = retention._read
        monkeypatch.setattr(retention, '_read', lambda path: original(path, 1) if str(path).endswith('.bin') else original(path))
        assert not any(i['eligible'] for i in preview(sealed)['items'])
    assert all(Path(i['source']).exists() for i in inspect_logs(sealed[0], sealed[3].id))


def test_stream_range_corruption_cannot_be_purged(sealed):
    with closing(sqlite3.connect(sealed[0])) as db:
        row = db.execute("SELECT id,payload FROM managed_events WHERE kind='stream_bytes' LIMIT 1").fetchone()
        p = json.loads(row[1]); p['sha256'] = '0'*64
        db.execute('UPDATE managed_events SET payload=? WHERE id=?', (json.dumps(p), row[0])); db.commit()
    assert not all(i['eligible'] for i in preview(sealed)['items'])
    assert any(i['state'] == 'unverified' for i in inspect_logs(sealed[0], sealed[3].id))
