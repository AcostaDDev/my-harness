"""Configuration bundles use synthetic files/SQLite; never clients or original restore paths."""
from pathlib import Path
import shutil

import pytest

from session_client import TestClient
from my_harness.api.app import create_app
from my_harness.services.configuration import digest
from my_harness.storage.backup import (BackupError, create_backup, verify_bundle, restore_backup)
from my_harness.storage.configuration import ConfigurationRepository, ConfigurationConflict
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository
from test_configuration import setup, dumps, change, save, activate, active_global  # noqa: F401
from test_backup import seal


def bundle(repo, target, **extra):
    return create_backup(Path(repo.managed.engine.url.database), target, artifact_roots=[repo.directory],
                         writers_stopped=True, **extra)


def test_pending_and_draft_are_preserved_without_originals(setup, tmp_path, monkeypatch):
    repo, data, root = setup
    active_global(repo, data)
    data['git']['author_name'] = 'Pending author'
    save(repo, [change(repo, dumps(data))], key='second')
    activate(repo, key='pending')
    save(repo, [change(repo, 'format="local-config-9"', validated=False)], key='draft')
    target = tmp_path / 'bundle'
    manifest = bundle(repo, target)
    assert manifest['format'] == 2
    assert len(manifest['configuration']['revisions']) == 3
    restored = tmp_path / 'restored'
    restore_backup(target, restored)
    shutil.rmtree(root)
    monkeypatch.setenv('HARNESS_LOCAL_CONFIG', '/absent/must-not-be-read')
    engine = make_engine(f'sqlite:///{restored / "state.sqlite3"}')
    try:
        archive = ConfigurationRepository(SQLiteManagedRepository(engine), root, state_dir=repo.state_dir)
        state = archive.read()
        assert state['status'] == 'READ_ONLY_ARCHIVE'
        assert state['active']['revision'] == 1 and state['pending']['revision'] == 2
        assert state['saved']['status'] == 'DRAFT'
        assert archive.document('global', 2) == dumps(data)
        with pytest.raises(ConfigurationConflict, match='read_only_archive'):
            archive.discard_external('global', expected_version=state['version'], observed_sha256=None,
                                     reason='Forbidden', key='forbidden')
    finally:
        engine.dispose()
    with TestClient(create_app(f'sqlite:///{restored / "state.sqlite3"}', configuration_dir=root,
                              state_dir=repo.state_dir)) as http:
        assert http.get('/api/managed/configuration').json()['text'] == 'format="local-config-9"'
        result = http.get('/api/managed/configuration/revisions/global/2')
        assert result.status_code == 200 and result.json()['text'] == dumps(data)
        for path in ('form', 'detect', 'preview', 'save', 'activate', 'check-clients', 'assistance/preview'):
            assert http.post('/api/managed/configuration/' + path, json={}, headers={'X-My-Harness': '1'}).status_code == 409
    assert verify_bundle(restored)['execution_authorized'] is False


@pytest.mark.parametrize('stage', ['intended', 'immutable_written', 'working_written', 'files_written'])
def test_partial_intent_is_archived_without_repair(setup, tmp_path, stage):
    repo, data, _ = setup
    def crash(point):
        if point == stage:
            raise RuntimeError('Synthetic crash')
    repo.checkpoint = crash
    with pytest.raises(RuntimeError):
        save(repo, [change(repo, dumps(data))])
    target = tmp_path / 'bundle'
    manifest = bundle(repo, target)
    assert manifest['configuration']['operations'][0]['status'] in ('INTENDED', 'RECOVERY_REQUIRED')
    assert verify_bundle(target) == manifest
    restore_backup(target, tmp_path / 'restored')
    assert repo.read()['active'] is None


@pytest.mark.parametrize('damage', ['missing', 'changed', 'permissions', 'hardlink', 'symlink', 'copy-race'])
def test_bad_authority_or_race_cannot_publish_bundle(setup, tmp_path, damage):
    repo, data, root = setup
    save(repo, [change(repo, dumps(data))])
    path = next((root / 'versions').rglob('*.toml'))
    if damage == 'missing':
        path.unlink()
    elif damage == 'changed':
        path.write_text('format="local-config-9"')
    elif damage == 'permissions':
        path.chmod(0o644)
    elif damage == 'hardlink':
        import os
        os.link(path, root / 'other')
    elif damage == 'symlink':
        path.unlink()
        path.symlink_to(root / 'global.toml')
    def hook(stage):
        if stage == 'artifact_copied' and damage == 'copy-race':
            path.write_text('unknown=true')
    target = tmp_path / 'bundle'
    with pytest.raises(BackupError):
        bundle(repo, target, hook=hook)
    assert not (target / 'COMPLETE').exists()


@pytest.mark.parametrize('tamper', ['inventory', 'downgrade', 'omit', 'bytes'])
def test_resealed_manifest_still_checks_sqlite_configuration(setup, tmp_path, tamper):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    target = tmp_path / 'bundle'
    manifest = bundle(repo, target)
    if tamper == 'inventory':
        seal(target, lambda m: m['configuration']['revisions'].clear())
    elif tamper == 'downgrade':
        seal(target, lambda m: m.update(format=1))
    elif tamper == 'omit':
        seal(target, lambda m: m['files'].pop())
    else:
        item = next(item for item in manifest['files'] if any(':revision:' in x for x in item['labels']))
        raw = b'unknown=true'
        (target / item['path']).write_bytes(raw)
        seal(target, lambda m: next(x for x in m['files'] if x['path'] == item['path']).update(
            sha256=digest(raw), size_bytes=len(raw)))
    with pytest.raises(BackupError):
        restore_backup(target, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_format_one_without_configuration_remains_readable(setup, tmp_path):
    repo, _, _ = setup
    target = tmp_path / 'bundle'
    bundle(repo, target)
    seal(target, lambda m: (m.update(format=1), m.pop('configuration')))
    assert verify_bundle(target)['format'] == 1
    restore_backup(target, tmp_path / 'restored')


def test_assistance_evidence_is_copied_and_live_owner_is_rejected(setup, tmp_path):
    from my_harness.adapters.processes import identity
    from my_harness.storage.models import ConfigurationOperationRow
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    artifacts = tmp_path / 'synthetic-assistance'
    artifacts.mkdir(mode=0o700)
    contents = {'prompt.txt': b'Synthetic prompt', 'stdout.bin': b'Synthetic answer', 'stderr.bin': b''}
    for name, raw in contents.items():
        (artifacts / name).write_bytes(raw)
    payload = {'owner': identity(), 'owner_closed': False, 'process': {
        'spec': {'artifacts': str(artifacts), 'prompt_path': str(artifacts / 'prompt.txt'),
                 'prompt_sha256': digest(contents['prompt.txt'])},
        'identity': None, 'capture': {'artifacts': {stream: {'path': str(artifacts / (stream + '.bin')),
            'sha256': digest(contents[stream + '.bin']), 'size': len(contents[stream + '.bin'])}
            for stream in ('stdout', 'stderr')}}}}
    with repo.managed._write() as session:
        session.add(ConfigurationOperationRow(id='synthetic-assist', format='configuration-operation-1',
            kind='ASSIST', status='RECOVERY_REQUIRED', idempotency_key='synthetic-assist', request_sha256='a' * 64,
            payload=payload, created_at=repo.managed._now(), updated_at=repo.managed._now()))
    with pytest.raises(BackupError, match='Live|vivo'):
        bundle(repo, tmp_path / 'live')
    assert not (tmp_path / 'live').exists()
    with repo.managed._write() as session:
        row = session.get(ConfigurationOperationRow, 'synthetic-assist')
        row.payload = {**row.payload, 'owner_closed': True}
    target = tmp_path / 'bundle'
    manifest = create_backup(Path(repo.managed.engine.url.database), target,
        artifact_roots=[repo.directory, artifacts], writers_stopped=True)
    assert len([f for f in manifest['files'] if f['labels'][0].startswith('assistance:')]) == 3
    shutil.rmtree(artifacts)
    assert verify_bundle(target) == manifest
