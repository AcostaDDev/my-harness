"""P002-T023: exact bounded originals through authenticated reads, including checkout-free restores."""
from contextlib import closing
from types import SimpleNamespace
import hashlib
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient as AnonymousClient
from session_client import TestClient

from my_harness.api.app import create_app
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.observed_steps import MAX_RECORD, ObservedStepProjector, StdoutRanges
from my_harness.storage.retention import apply_retention, inspect_logs, inspect_original, preview_retention
from test_backup import db_path, dump_rows, LOCAL
from test_git import repo as git_repo  # noqa: F401
from test_managed import context, repository  # noqa: F401
from test_observed_steps import OVERSIZE, finish, scripted, settle


@pytest.fixture
def original(context, repository, migrated_database, tmp_path):
    port = scripted(tmp_path, OVERSIZE)
    job, claim, request, _ = settle(repository, context, port, 'executor')
    finish(repository, job, claim)
    assert ObservedStepProjector(repository.engine).run_pending()[0]['state'] == 'sealed'
    event = next(event for event in repository.events(job.run_id, limit=1000)
                 if event['kind'] == 'agent_event' and 'original_reference' in event['payload'])
    reference = event['payload']['original_reference']
    stdout = port.artifact_root / request.id / 'stdout.bin'
    raw = stdout.read_bytes()[reference['offset']:reference['offset'] + reference['size']]
    return SimpleNamespace(database=db_path(migrated_database), port=port, job=job, request=request,
                           event=event, reference=reference, stdout=stdout, raw=raw)


def url(original):
    return f'/api/managed/runs/{original.job.run_id}/attempts/{original.request.id}/logs'


def change_reference(original, **changes):
    payload = {**original.event['payload'], 'original_reference': {**original.reference, **changes}}
    with closing(sqlite3.connect(original.database)) as db:
        db.execute('UPDATE managed_events SET payload=? WHERE run_id=? AND sequence=?',
                   (json.dumps(payload), original.job.run_id, original.event['sequence']))
        db.commit()


def test_exact_original_and_metadata_compatibility_with_local_guards(original, tmp_path):
    before = dump_rows(original.database)
    expected = inspect_logs(original.database, original.request.id)
    app = create_app(f'sqlite:///{original.database}', tmp_path / 'ui')
    with TestClient(app, **LOCAL) as http:
        assert http.get(url(original)).json() == expected
        response = http.get(url(original), params={'sequence': original.event['sequence']})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data['state'] == 'retained' and data['diagnostic'] is None
        assert data['content'].encode('utf-8') == original.raw
        assert len(original.raw) == data['size_bytes']
        assert hashlib.sha256(original.raw).hexdigest() == data['sha256']
        assert data['encoding'] == 'utf-8' and data['limit_bytes'] == MAX_RECORD
        assert data['content'].endswith('\n')
        assert data['run_id'] == original.job.run_id and data['attempt_id'] == original.request.id
        assert http.get(url(original)).json() == expected
        for sequence in (0, -1, 'invalid', 2**53):
            assert http.get(url(original), params={'sequence': sequence}).status_code == 422
        missing = http.get(url(original), params={'sequence': 2**53 - 1})
        other = http.get(url(original), params={'sequence': 1})  # a non-agent event
        assert other.status_code == missing.status_code == 404
        assert other.json() == missing.json()
        assert http.get(url(original).replace(original.job.run_id, 'foreign'), params={'sequence': data['sequence']}).status_code == 404
        assert http.get(url(original), params={'sequence': data['sequence']}, headers={'Origin': 'http://foreign.invalid'}).status_code == 403
    with AnonymousClient(app, base_url='http://127.0.0.1:8013') as http:
        assert http.get(url(original), params={'sequence': original.event['sequence']}).status_code == 401
    assert dump_rows(original.database) == before


@pytest.mark.parametrize('damage', ['missing', 'range', 'elsewhere', 'record_digest', 'chunk_digest', 'offset', 'symlink'])
def test_original_refuses_missing_corrupt_and_unsafe_bytes(original, damage):
    if damage == 'missing':
        original.stdout.unlink()
    elif damage == 'symlink':
        target = original.stdout.with_name('outside.bin')
        original.stdout.rename(target)
        original.stdout.symlink_to(target)
    elif damage == 'record_digest':
        change_reference(original, sha256='0' * 64)
    elif damage == 'chunk_digest':
        with closing(sqlite3.connect(original.database)) as db:
            db.execute("""UPDATE managed_events SET payload=json_set(payload, '$.sha256', ?)
                WHERE run_id=? AND kind='stream_bytes' AND json_extract(payload,'$.stream')='stdout'""",
                       ('0' * 64, original.job.run_id))
            db.commit()
    elif damage == 'offset':
        change_reference(original, offset=original.stdout.stat().st_size)
    else:
        data = bytearray(original.stdout.read_bytes())
        position = original.reference['offset'] + 100 if damage == 'range' else len(data) - 5
        data[position] ^= 1
        original.stdout.write_bytes(data)
    result = inspect_original(original.database, original.request.id, original.event['sequence'])
    assert result['content'] is None
    assert result['state'] == ('missing' if damage == 'missing' else 'unverified')
    assert result['diagnostic']


def test_original_stays_unavailable_until_capture_is_sealed(original):
    with closing(sqlite3.connect(original.database)) as db:
        db.execute("UPDATE managed_processes SET capture=NULL WHERE attempt_id=?", (original.request.id,))
        db.commit()
    result = inspect_original(original.database, original.request.id, original.event['sequence'])
    assert result['state'] == 'pending' and result['content'] is None


def test_foreign_attempt_event_is_indistinguishable_from_an_absent_record(original):
    with closing(sqlite3.connect(original.database)) as db:
        db.execute("UPDATE managed_events SET payload=json_set(payload,'$.attempt_id','foreign') WHERE run_id=? AND sequence=?",
                   (original.job.run_id, original.event['sequence']))
        db.commit()
    for sequence in (original.event['sequence'], 2**53 - 1):
        with pytest.raises(LookupError, match='Original record not found'):
            inspect_original(original.database, original.request.id, sequence)


def test_original_limit_precedes_stream_reads_and_rejects_foreign_reference(original, monkeypatch):
    change_reference(original, size=MAX_RECORD + 1)
    monkeypatch.setattr(StdoutRanges, '_verify', lambda *_: pytest.fail('oversize record opened its stream'))
    result = inspect_original(original.database, original.request.id, original.event['sequence'])
    assert result['state'] == 'unverified' and result['content'] is None
    assert str(MAX_RECORD) in result['diagnostic']
    change_reference(original, stream='stderr')
    with pytest.raises(ValueError):
        inspect_original(original.database, original.request.id, original.event['sequence'])


def test_original_restores_without_checkout_then_survives_retention_as_an_absence(original, context, tmp_path):
    options = dict(artifact_roots=[original.port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
    backup = tmp_path / 'retained-backup'
    create_backup(original.database, backup, artifact_roots=options['artifact_roots'], writers_stopped=True)
    destination = tmp_path / 'retained-restore'
    restore_backup(backup, destination)
    shown = preview_retention(original.database, **options)
    apply_retention(original.database, **options, preview_sha256=shown['preview_sha256'],
                    reason='Synthetic explicit retention', confirmed=True, writers_stopped=True)
    assert not original.stdout.exists()
    assert inspect_original(original.database, original.request.id, original.event['sequence'])['state'] == 'purged'
    purged_backup = tmp_path / 'purged-backup'
    create_backup(original.database, purged_backup, artifact_roots=options['artifact_roots'], writers_stopped=True)
    purged_restore = tmp_path / 'purged-restore'
    restore_backup(purged_backup, purged_restore)
    context.root.rename(tmp_path / 'offline-checkout')
    for restored, state in ((destination, 'retained'), (purged_restore, 'purged')):
        database = restored / 'state.sqlite3'
        before = database.read_bytes()
        with TestClient(create_app(f'sqlite:///{database}', tmp_path / f'ui-{state}'), **LOCAL) as http:
            response = http.get(url(original), params={'sequence': original.event['sequence']})
            assert response.status_code == 200, response.text
            data = response.json()
            assert data['state'] == state
            assert data['content'] == (original.raw.decode('utf-8') if state == 'retained' else None)
        assert database.read_bytes() == before
