"""D116: synthetic authority and children; temporary SQLite/FS, no Git/providers/creation installs."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

from alembic import command
import pytest
from sqlalchemy import text

from my_harness.services.local_config import load_local_config
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.database import make_engine
from test_project_registry import POLICY, v3, operator  # noqa: F401
from test_local_config import setup, web, write, launches, SENTINEL  # noqa: F401
from test_managed_api import client

ROOT = '/api/managed/project-creation-root'
CREATE = '/api/managed/project-creations'


@pytest.fixture
def creation(operator, migrated_database):
    context, data, folder, tmp_path = operator
    parent = tmp_path / 'chosen'
    parent.mkdir()
    config = load_local_config(write(folder, v3(data, [], bootstrap=True)))
    engine = make_engine(migrated_database[0])
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    yield runtime.creation, parent, config, migrated_database[0]
    runtime.stop()
    engine.dispose()
    assert not launches(tmp_path)


def select_root(service, parent, key='root', action='select'):
    change = {'action': action, 'expected_version': service.read_root()['version']}
    if action == 'select':
        change['path'] = str(parent)
    preview = service.root_preview(change)
    body = {'change': change, 'preview_sha256': preview['preview_sha256'], 'confirm_path': preview['root']['path']}
    return service.root_apply(body, key), body


def change(service, name='child', **extra):
    return {'project_id': name, 'directory_name': name, 'root_version': service.read_root()['version'],
            'composition': 'web', 'policy': POLICY, 'documents': 'v2', 'tag_kind': 'lightweight',
            'work_language': 'en', **extra}


def request(service, name='child', **extra):
    body = change(service, name, **extra)
    preview = service.preview(body)
    return {'change': body, 'preview_sha256': preview['preview_sha256'], 'trust_root': preview['target']}


def test_new_child_preview_and_confirm_without_toml_roots_restart_and_revocation(creation):
    service, parent, config, url = creation
    assert service.read_root()['status'] == 'ABSENT'
    with pytest.raises(RegistryError, match='current'):
        service.preview(change(service, root_version=1))
    selected, root_body = select_root(service, str(parent) + '//./')
    assert selected['root']['path'] == str(parent)
    assert service.root_apply(root_body, 'root')['replayed']
    body = request(service, directory_name='different')
    assert not (parent / 'different').exists()
    result = service.confirm(body, 'create')
    assert result['status'] == 'REGISTERED' and result['result']['project_id'] == 'child'
    assert list((parent / 'different').iterdir()) == []  # neither .git nor a marker foreign to the bootstrap
    assert service.confirm(body, 'create') == result
    item = service.registry.read('child')
    assert item['creation_id'] == result['id'] and item['trust']['root'] == str(parent / 'different')
    assert service.runtime.project('child').versions == result['intent']['versions']
    assert result['intent']['agents']['reviewer']['model'] == service.runtime.project('child').context.policy.reviewer_model
    assert result['intent']['profile_details']['sha256'] and result['intent']['composition']['name'] == 'web'
    old_versions = dict(service.runtime.project('child').versions)
    select_root(service, parent, 'retire', 'retire')
    assert service.confirm(body, 'create') == result  # replay does not revalidate a revoked permission
    engine = make_engine(url)
    restarted = ManagedRuntime(engine, config)
    restarted.start()
    try:
        assert restarted.creation.read_root()['status'] == 'REVOKED'
        assert restarted.project('child').versions == old_versions
        assert restarted.creation.repository.read(result['id']) == result
    finally:
        restarted.stop()
        engine.dispose()
    with pytest.raises(RegistryError) as error:
        service.root_apply({**root_body, 'reason': 'other payload'}, 'root')
    assert error.value.code == 'idempotency_conflict'


@pytest.mark.parametrize('name', ['..', '../escape', '/absolute', 'bad/name', 'a\\b', 'Bad', 'a\0b', '.'])
def test_names_never_escape(creation, name):
    service, parent, *_ = creation
    select_root(service, parent)
    with pytest.raises(RegistryError):
        service.preview(change(service, directory_name=name))
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize('kind', ['empty', 'file', 'symlink', 'dangling'])
def test_existing_targets_never_adopted(creation, kind):
    service, parent, *_ = creation
    select_root(service, parent)
    target = parent / 'child'
    if kind == 'empty':
        target.mkdir()
    elif kind == 'file':
        target.write_text('foreign')
    else:
        target.symlink_to(parent if kind == 'symlink' else parent / 'missing')
    with pytest.raises(RegistryError) as error:
        service.preview(change(service))
    assert error.value.code == 'target_exists'


def test_root_boundaries_and_service_conflicts(creation, monkeypatch):
    service, parent, config, _ = creation
    for value in ('relative', str(parent / '..'), str(parent / 'missing')):
        with pytest.raises(RegistryError):
            service.root_preview({'action': 'select', 'expected_version': 0, 'path': value})
    link = parent / 'link'
    link.symlink_to(parent)
    with pytest.raises(RegistryError):
        select_root(service, link)
    git = parent / '.git'
    git.write_text('gitdir: does-not-matter')
    with pytest.raises(RegistryError) as error:
        select_root(service, parent)
    assert error.value.code == 'root_in_repository'
    git.unlink()
    with pytest.raises(RegistryError):
        select_root(service, config.registrar.state)
    monkeypatch.setattr(os, 'access', lambda *args, **kwargs: False)
    with pytest.raises(RegistryError) as error:
        select_root(service, parent)
    assert error.value.code == 'root_unwritable'


def test_parent_can_contain_siblings_and_state_but_new_target_cannot_conflict(creation):
    service, parent, config, _ = creation
    # A common parent is allowed; its state/configuration child stays excluded.
    select_root(service, parent.parent)
    for name in ('state', 'operator', 'synthetic.sqlite3', 'new'):
        with pytest.raises(RegistryError):
            service.preview(change(service, name))
    assert service.confirm(request(service, 'sibling'), 'first')['status'] == 'REGISTERED'
    select_root(service, parent.parent, 'again')
    assert service.confirm(request(service, 'sibling2'), 'second')['status'] == 'REGISTERED'
    with pytest.raises(RegistryError):
        select_root(service, parent.parent / 'sibling')


class Crash(BaseException):
    pass


@pytest.mark.parametrize('point', ['before_mkdir', 'after_mkdir', 'after_checkpoint', 'after_register'])
def test_crashes_conserve_evidence_and_never_adopt_uncertain_folder(creation, monkeypatch, point):
    service, parent, *_ = creation
    select_root(service, parent)
    body = request(service)
    original_mkdir, original_event = os.mkdir, service.repository.event
    def mkdir(*args, **kwargs):
        if point == 'before_mkdir':
            raise Crash()
        original_mkdir(*args, **kwargs)
        if point == 'after_mkdir':
            raise Crash()
    def event(session, row, kind, **kwargs):
        if point == 'after_checkpoint' and kind == 'registered':
            raise Crash()
        return original_event(session, row, kind, **kwargs)
    monkeypatch.setattr(os, 'mkdir', mkdir)
    monkeypatch.setattr(service.repository, 'event', event)
    if point == 'after_register':
        monkeypatch.setattr(service.registry, 'load', lambda: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        service.confirm(body, 'create')
    monkeypatch.undo()
    operation = service.repository.operations()[0]
    assert service.confirm(body, 'create')['id'] == operation['id']
    assert operation['status'] == {'before_mkdir': 'INTENDED', 'after_mkdir': 'INTENDED',
                                  'after_checkpoint': 'DIRECTORY_CREATED', 'after_register': 'REGISTERED'}[point]
    if point == 'after_register':
        service.registry.load()
        assert service.runtime.project('child').id == 'child'
    elif point == 'after_mkdir':
        with pytest.raises(RegistryError) as error:
            service.resume_preview(operation['id'], {'expected_version': operation['version'], 'root_version': 1})
        assert error.value.code == 'recovery_required'
        assert (parent / 'child').is_dir() and service.registry.repository.rows() == []
        service.reconcile()
        assert service.repository.read(operation['id'])['status'] == 'RECOVERY_REQUIRED'
    else:
        resume(service, operation)
        assert service.repository.read(operation['id'])['status'] == 'REGISTERED'


def resume(service, operation, key='resume'):
    change = {'expected_version': operation['version'], 'root_version': service.read_root()['version']}
    preview = service.resume_preview(operation['id'], change)
    return service.resume(operation['id'], {'change': change, 'preview_sha256': preview['preview_sha256']}, key)


def pause(service, monkeypatch):
    original = service.repository.event
    def event(session, row, kind, **kwargs):
        if kind == 'registered':
            raise Crash()
        return original(session, row, kind, **kwargs)
    monkeypatch.setattr(service.repository, 'event', event)
    with pytest.raises(Crash):
        service.confirm(request(service), 'create')
    monkeypatch.undo()
    return service.repository.operations()[0]


def test_revoke_reselect_and_resume_owned_child_preserves_original_intent(creation, monkeypatch):
    service, parent, *_ = creation
    select_root(service, parent)
    op = pause(service, monkeypatch)
    select_root(service, parent, 'retire', 'retire')
    op = service.repository.read(op['id'])
    assert op['status'] == 'BLOCKED'
    with pytest.raises(RegistryError):
        resume(service, op)
    select_root(service, parent, 'reselect')
    result = resume(service, op)
    assert result['status'] == 'REGISTERED'
    assert result['intent'] == op['intent'] and result['authority']['version'] == 3
    assert result['intent']['authority']['version'] == 1
    assert len(service.registry.repository.history('child')) == 1
    history = result['history']
    assert all(digest({k: v for k, v in e.items() if k != 'sha256'}) == e['sha256'] for e in history)
    assert all(history[i]['previous_sha256'] == history[i-1]['sha256'] for i in range(1, len(history)))


@pytest.mark.parametrize('drift', ['content', 'child_identity', 'parent_identity', 'composition', 'profile'])
def test_resume_drift_blocks_without_touching_foreign_bytes(creation, monkeypatch, drift):
    service, parent, *_ = creation
    select_root(service, parent)
    op = pause(service, monkeypatch)
    if drift == 'content':
        (parent / 'child' / 'foreign').write_text('preserve')
    elif drift == 'child_identity':
        (parent / 'child').rename(parent / 'original')
        (parent / 'child').mkdir()
    elif drift == 'parent_identity':
        parent.rename(parent.with_name('original-parent'))
        parent.mkdir()
    elif drift == 'profile':
        from dataclasses import replace
        profiles = service.registry.registrar.profiles
        profiles['typescript-web'] = replace(profiles['typescript-web'], protected_paths=('new-protected/**',))
    else:
        service.registry.registrar._authority['state_dir'] += '-changed'
    with pytest.raises((RegistryError, OSError)):
        resume(service, op)
    assert service.registry.repository.rows() == []
    if drift == 'content':
        assert (parent / 'child' / 'foreign').read_text() == 'preserve'


def test_concurrent_keys_and_cross_runtime_reservations(creation, monkeypatch):
    service, parent, config, url = creation
    select_root(service, parent)
    body = request(service)
    engine = make_engine(url)
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    services = (service, runtime.creation)
    def confirm(index):
        try:
            return services[index].confirm(body, 'same')
        except RegistryError as error:
            return error.code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm, range(2)))
        assert all(isinstance(r, dict) for r in results), results
        assert results[0]['id'] == results[1]['id']
        assert len(service.registry.repository.rows()) == 1
        with pytest.raises(RegistryError) as error:
            service.confirm({**body, 'reason': 'changed'}, 'same')
        assert error.value.code == 'idempotency_conflict'
        with pytest.raises(RegistryError):
            runtime.creation.confirm(body, 'different')
    finally:
        runtime.stop()
        engine.dispose()


def test_cancel_keeps_uncertain_reservation_and_blocks_existing_registration(creation, monkeypatch):
    service, parent, *_ = creation
    select_root(service, parent)
    op = pause(service, monkeypatch)
    body = {'expected_version': op['version'], 'intent_sha256': op['intent_sha256']}
    result = service.cancel(op['id'], body, 'cancel')
    assert result['reserved'] and result['status'] == 'CANCELLED'
    assert service.cancel(op['id'], body, 'cancel') == result
    assert (parent / 'child').is_dir()
    from test_project_registry import register
    # empty roots do not authorize an existing registration; even with a TOML root the reservation is not adopted.
    service.registry.registrar.roots = (parent,)
    with pytest.raises(RegistryError) as error:
        service.registry.preview(register(parent / 'child'))
    assert error.value.code == 'target_reserved'
    # Synthetic external resolution: a new versioned check may release the reservation.
    (parent / 'child').rmdir()
    released = service.cancel(op['id'], {'expected_version': result['version'],
                                       'intent_sha256': result['intent_sha256']}, 'absence-recheck')
    assert released['status'] == 'CANCELLED' and not released['reserved']
    assert service.confirm(request(service), 'after-resolution')['status'] == 'REGISTERED'


def test_api_strict_contract_and_same_result_after_lost_reply(creation):
    service, parent, config, url = creation
    with client(url, parent.parent, config) as http:
        root = http.get(ROOT).json()
        assert root['available'] and root['path'] is None
        change = {'action': 'select', 'expected_version': 0, 'path': str(parent)}
        preview = http.post(ROOT + '/preview', json=change)
        assert preview.status_code == 200, preview.text
        body = {'change': change, 'preview_sha256': preview.json()['preview_sha256'], 'confirm_path': str(parent)}
        assert http.post(ROOT + '/apply', json=body).status_code == 422
        response = http.post(ROOT + '/apply', json=body, headers={'Idempotency-Key': 'root'})
        assert response.status_code == 200, response.text
        create = {'project_id': 'child', 'directory_name': 'child', 'root_version': 1,
                  'composition': 'web', 'policy': POLICY, 'work_language': 'en'}
        assert http.post(CREATE + '/preview', json={**create, 'root': str(parent)}).status_code == 422
        preview = http.post(CREATE + '/preview', json=create)
        assert preview.status_code == 200, preview.text
        body = {'change': create, 'preview_sha256': preview.json()['preview_sha256'],
                'trust_root': preview.json()['target']}
        response = http.post(CREATE + '/confirm', json=body, headers={'Idempotency-Key': 'child'})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result['status'] == 'REGISTERED'
        assert http.post(CREATE + '/confirm', json=body, headers={'Idempotency-Key': 'child'}).json() == result
        assert http.get(CREATE + '/' + result['id']).json() == result
        assert SENTINEL not in json.dumps(http.get(ROOT).json())
        assert http.get('/api/managed/projects/child').status_code == 200
        assert http.post(CREATE + '/preview', json={**create, 'project_id': 'new'}).status_code == 422


def test_additive_migration_preserves_prior_registered_row_and_event(creation, migrated_database):
    service, parent, config, url = creation
    engine = service.runtime.engine
    # Without creation history, 0021 can be downgraded; D078 keeps its previous rows.
    service.runtime.stop()
    command.downgrade(migrated_database[1], '0020_project_imports')
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO registered_projects '
            '(id, version, status, root, composition, profile, row, row_sha256, trust, created_at, updated_at) '
            "VALUES ('old', 1, 'ACTIVE', '/synthetic/old', 'web', 'typescript-web', '{}', :sha, '{}', 'old', 'old')"),
            {'sha': 'a' * 64})
        connection.execute(text('INSERT INTO registered_project_events '
            '(project_id, version, action, row, row_sha256, preview_sha256, actor, recorded_at) '
            "VALUES ('old', 1, 'register', '{}', :sha, :sha, '{}', 'old')"), {'sha': 'a' * 64})
    command.upgrade(migrated_database[1], 'head')
    command.check(migrated_database[1])
    with engine.connect() as connection:
        assert connection.execute(text('SELECT creation_id FROM registered_projects')).all() == [(None,)]
        assert connection.scalar(text('SELECT count(*) FROM registered_project_events')) == 1
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []


def test_authority_rejects_stale_preview_and_never_revives_intent_without_ownership(creation, monkeypatch):
    service, parent, *_ = creation
    select_root(service, parent)
    body = request(service)
    select_root(service, parent, 'new-revision')
    with pytest.raises(RegistryError) as error:
        service.confirm(body, 'stale')
    assert error.value.code == 'root_revoked' and list(parent.iterdir()) == []
    monkeypatch.setattr(service, 'advance', lambda operation_id: None)
    op = service.confirm(request(service), 'pending')
    monkeypatch.undo()
    assert op['status'] == 'INTENDED'
    select_root(service, parent, 'retire', 'retire')
    select_root(service, parent, 'selected-again')
    op = service.repository.read(op['id'])
    with pytest.raises(RegistryError) as error:
        resume(service, op)
    assert error.value.code == 'recovery_required'
    cancelled = service.cancel(op['id'], {'expected_version': op['version'], 'intent_sha256': op['intent_sha256']}, 'cancel')
    assert not cancelled['reserved'] and list(parent.iterdir()) == []
    assert service.confirm(request(service), 'fresh')['status'] == 'REGISTERED'


def test_preview_loses_validity_after_parent_identity_change(creation):
    service, parent, *_ = creation
    change = {'action': 'select', 'expected_version': 0, 'path': str(parent)}
    preview = service.root_preview(change)
    parent.rename(parent.with_name('original'))
    parent.mkdir()
    with pytest.raises(RegistryError) as error:
        service.root_apply({'change': change, 'preview_sha256': preview['preview_sha256'], 'confirm_path': str(parent)}, 'root')
    assert error.value.code == 'preview_changed'
    assert service.repository.root()['status'] == 'ABSENT'


def test_old_formats_and_bootstrap_ceiling_do_not_gain_creation_authority(creation):
    service, parent, config, url = creation
    service.registry.registrar.bootstrap_enabled = False
    assert not service.read_root()['bootstrap_enabled']
    select_root(service, parent)
    with pytest.raises(RegistryError) as error:
        service.preview(change(service))
    assert error.value.code == 'bootstrap_not_allowed'
    service.registry.registrar.format = 'local-config-2'
    assert not service.read_root()['available']
    with pytest.raises(RegistryError) as error:
        service.root_preview({'action': 'select', 'expected_version': 1, 'path': str(parent)})
    assert error.value.code == 'registry_unavailable'
    assert list(parent.iterdir()) == []


def test_creation_authority_and_journal_survive_backup_as_read_only(creation):
    from my_harness.storage.backup import create_backup, restore_backup
    service, parent, config, url = creation
    select_root(service, parent)
    result = service.confirm(request(service), 'create')
    source = Path(url.removeprefix('sqlite:///'))
    bundle, restored = parent.parent / 'backup', parent.parent / 'restored'
    create_backup(source, bundle, writers_stopped=True)
    restore_backup(bundle, restored)
    with client(f'sqlite:///{restored / "state.sqlite3"}', parent.parent, config) as http:
        read = http.get(ROOT).json()
        assert read['status'] == 'ACTIVE' and not read['available']
        assert read['operations'][0]['id'] == result['id']
        assert http.get(CREATE + '/' + result['id']).json() == result
        denied = http.post(ROOT + '/preview', json={'action': 'retire', 'expected_version': 1})
        assert denied.status_code == 409 and denied.json()['code'] == 'restored_read_only'
        assert http.get('/api/managed/projects').json() == []


def test_two_installations_keep_independent_root_selection(creation, tmp_path, monkeypatch):
    from alembic.config import Config
    service, parent, config, url = creation
    other = parent.parent / 'second-parent'
    other.mkdir()
    second_url = f'sqlite:///{tmp_path / "second.sqlite3"}'
    alembic = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
    alembic.attributes['database_url'] = second_url
    command.upgrade(alembic, 'head')
    engine = make_engine(second_url)
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    try:
        assert runtime.creation.read_root()['path'] is None
        select_root(service, parent)
        select_root(runtime.creation, other)
        assert service.read_root()['path'] == str(parent)
        assert runtime.creation.read_root()['path'] == str(other)
        runtime.stop()
        runtime.start()
        assert runtime.creation.read_root()['path'] == str(other)
    finally:
        runtime.stop()
        engine.dispose()


def test_local_config_4_creates_with_the_same_frozen_versions_as_preview(creation, operator):
    service, parent, _, _ = creation
    _, data, folder, _ = operator
    value = v3(data, [], bootstrap=True)
    value['format'] = 'local-config-4'
    config = load_local_config(write(folder, value))
    runtime = ManagedRuntime(service.runtime.engine, config)
    runtime.start()
    try:
        select_root(runtime.creation, parent)
        body = request(runtime.creation)
        result = runtime.creation.confirm(body, 'v4')
        assert result['status'] == 'REGISTERED'
        versions = runtime.project('child').versions
        assert versions == result['intent']['versions'] and versions['local_config'] == 'local-config-4'
    finally:
        runtime.stop()


def test_retirement_between_checkpoint_and_registration_stops_next_effect(creation, monkeypatch):
    from contextlib import contextmanager
    from threading import Event
    service, parent, config, url = creation
    select_root(service, parent)
    body = request(service)
    engine = make_engine(url)
    other = ManagedRuntime(engine, config)
    other.start()
    checkpoint, proceed = Event(), Event()
    original = service.runtime.repository._write
    calls = 0
    @contextmanager
    def write():
        nonlocal calls
        with original() as session:
            yield session
        calls += 1
        if calls == 2:  # confirmed intention and confirmed DIRECTORY_CREATED checkpoint
            checkpoint.set()
            assert proceed.wait(5)
    monkeypatch.setattr(service.runtime.repository, '_write', write)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.confirm, body, 'create')
            try:
                assert checkpoint.wait(5)
                select_root(other.creation, parent, 'revoke', 'retire')
            finally:
                proceed.set()
            result = future.result(timeout=5)
        assert result['status'] == 'BLOCKED'
        assert service.registry.repository.rows() == []
        assert (parent / 'child').is_dir() and list((parent / 'child').iterdir()) == []
        assert service.read_root()['status'] == 'REVOKED'
    finally:
        proceed.set()
        other.stop()
        engine.dispose()


def test_case_aliases_cannot_enter_service_state_or_a_registered_empty_child(creation):
    service, parent, config, _ = creation
    state = config.registrar.state
    alias = state.with_name(state.name.upper())
    if not alias.exists():
        pytest.skip('Case-sensitive filesystem; that physical alias does not exist.')
    with pytest.raises(RegistryError) as error:
        select_root(service, alias)
    assert error.value.code == 'root_service_state'
    select_root(service, parent)
    assert service.confirm(request(service), 'create')['status'] == 'REGISTERED'
    alias = (parent / 'child').with_name('CHILD')
    with pytest.raises(RegistryError) as error:
        select_root(service, alias, 'nested-alias')
    assert error.value.code == 'root_taken'


def test_case_aliases_preserve_reservations_before_mkdir(creation, monkeypatch):
    service, parent, *_ = creation
    alias = parent.with_name(parent.name.upper())
    if not alias.exists():
        pytest.skip('Case-sensitive filesystem; that physical alias does not exist.')
    select_root(service, parent)
    monkeypatch.setattr(service, 'advance', lambda operation_id: None)
    service.confirm(request(service), 'intended')
    monkeypatch.undo()
    select_root(service, alias, 'same-physical-parent')
    with pytest.raises(RegistryError) as error:
        service.preview(change(service, 'other', directory_name='child'))
    assert error.value.code == 'target_reserved'
    assert list(parent.iterdir()) == []
