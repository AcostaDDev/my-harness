"""P013-T004: synthetic files/SQLite only; no clients, services, network or managed runs launched."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import pwd
import stat
import sys

from alembic import command
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from my_harness.services.configuration import digest, parse
from my_harness.services.local_config import build, LocalConfigError
from my_harness.storage.configuration import ConfigurationRepository, ConfigurationConflict
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.models import ConfigurationOperationRow as Operation, RegisteredProjectRow
from my_harness.storage.schema import require_schema
from test_cli_diagnostics import probe_config


def dumps(data):
    def value(item):
        if isinstance(item, bool):
            return 'true' if item else 'false'
        if isinstance(item, (int, float)):
            return repr(item)
        if isinstance(item, str):
            return json.dumps(item)
        if isinstance(item, list):
            return '[' + ', '.join(value(x) for x in item) + ']'
        return '{' + ', '.join(f'{json.dumps(k)} = {value(v)}' for k, v in item.items()) + '}'
    return ''.join(f'{json.dumps(k)} = {value(v)}\n' for k, v in data.items())


@pytest.fixture
def setup(migrated_database, tmp_path):
    engine = make_engine(migrated_database[0])
    managed = SQLiteManagedRepository(engine)
    root = tmp_path / 'private configuration'
    root.mkdir(mode=0o700)
    state = tmp_path / 'state'
    state.mkdir()
    # A synthetic version/help probe: live activation (D238) preflights both roles before switching.
    probe_cli = probe_config(tmp_path)
    cli = {'timeout_seconds': 10, 'executable': list(probe_cli.executable),
           'environment': {'USER': pwd.getpwuid(os.getuid()).pw_name, **dict(probe_cli.environment)}}
    agents = {'reviewer': {**copy.deepcopy(cli), 'provider': 'codex', 'model': 'synthetic', 'effort': 'medium'},
              'executor': {**copy.deepcopy(cli), 'provider': 'codex'}}
    data = {'format': 'local-config-9', 'service': {'state_dir': str(state), 'supervisor': False},
            'git': {'executable': sys.executable, 'author_name': 'Synthetic', 'author_email': 'test@example.invalid'},
            'agents': agents, 'registration': {'roots': [], 'bootstrap_enabled': False}}
    repository = ConfigurationRepository(managed, root, state_dir=state)
    yield repository, data, root
    engine.dispose()


def change(repo, text, scope='global', **extra):
    state = repo.read(scope)
    return {'scope': scope, 'text': text, 'validated': True, 'expected_version': state['version'],
            'base_sha256': state['actual_sha256'], 'active_sha256': state['active']['sha256'] if state['active'] else None,
            'import_external': False, **extra}


def save(repo, changes, key='save'):
    preview = repo.preview(changes, reason='Synthetic change')
    return repo.save(changes, reason='Synthetic change', preview_sha256=preview['sha256'], key=key)


def activate(repo, scopes=('global',), key='activate'):
    refs = []
    for scope in scopes:
        state = repo.read(scope)
        refs.append({k: state['saved'][k] for k in ('scope', 'revision', 'sha256')} |
                    {'expected_version': state['version']})
    preview = repo.activation_preview(refs, reason='Synthetic activation')
    return repo.activate(refs, reason='Synthetic activation', preview_sha256=preview['sha256'], key=key)


def active_global(repo, data):
    save(repo, [change(repo, dumps(data))])
    activation = activate(repo)
    repo.promote_pending(activation_id=activation['id'], key='startup', restarted=True)


def register(repo, root, project_id):
    root.mkdir()
    with repo.managed._write() as session:
        session.add(RegisteredProjectRow(id=project_id, root=str(root), version=1, status='ACTIVE',
            composition='synthetic', profile='synthetic', row={}, row_sha256='a' * 64, trust={},
            created_at=repo.managed._now(), updated_at=repo.managed._now()))


def project_data(data, repo, root, project_id):
    ref = repo.read()['active']
    return {'format': 'project-config-1', 'project': {'id': project_id, 'root': str(root)},
        'global': {'revision': ref['revision'], 'sha256': ref['sha256']},
        'profile_name': 'synthetic-profile',
        'profile': {'preparation': [], 'validations': [{'argv': ['python', '-c', 'print(1)'], 'timeout_seconds': 10}],
                    'allowed_command_prefixes': [], 'protected_paths': ['docs/**'], 'sensitive_paths': ['.env*'],
                    'data_model_paths': [], 'executor_instructions': 'Synthetic fixture'},
        'commands': {'executables': {'python': sys.executable}, 'environment': {}, 'authorize_profile_commands': True},
        'agents': copy.deepcopy(data['agents']),
        'policy': {'planning_mode': 'deterministic', 'executor_mode': 'catalog', 'executor_models': ['synthetic'],
                   'executor_efforts': ['medium']}}


def test_global_save_preview_activation_restart_and_replay(setup):
    repo, data, root = setup
    changes = [change(repo, dumps(data))]
    preview = repo.preview(changes, reason='Synthetic change')
    assert preview['changes'][0]['diff'] and not list(root.iterdir())
    result = save(repo, changes)
    assert result['status'] == 'SAVED' and repo.read()['active'] is None
    assert save_replay(repo, changes, preview) == result
    assert repo.document('global', 1) == dumps(data)
    for path in root.rglob('*'):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    operation = activate(repo)
    assert repo.read()['status'] == 'RESTART_REQUIRED' and repo.read()['active'] is None
    with pytest.raises(ConfigurationConflict, match='restart_required'):
        repo.promote_pending(activation_id=operation['id'], key='start')
    promoted = repo.promote_pending(activation_id=operation['id'], key='start', restarted=True)
    assert promoted == repo.promote_pending(activation_id=operation['id'], key='start', restarted=True)
    assert repo.read()['active']['revision'] == 1 and repo.read()['status'] == 'READY'
    # Working copies never define active authority; an ordinary save retains the old active reference.
    data['git']['author_name'] = 'Another synthetic author'
    save(repo, [change(repo, dumps(data))], key='second')
    assert repo.read()['saved']['revision'] == 2 and repo.read()['active']['revision'] == 1
    assert 'Another' not in repo.document('global', 1)


def save_replay(repo, changes, preview):
    return repo.save(changes, reason='Synthetic change', preview_sha256=preview['sha256'], key='save')


def test_invalid_draft_legacy_import_and_no_processes(setup, monkeypatch):
    repo, data, _ = setup
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('Parser invoked a process'))
    parse(dumps(data), 'global')  # No composition required by v9.
    legacy = {**data, 'format': 'local-config-8', 'compositions': {}}
    with pytest.raises(LocalConfigError):
        build(legacy, None)  # Empty compositions remain invalid in v8.
    with pytest.raises(ValueError, match='Explicit import'):
        parse(dumps(legacy), 'global')
    with pytest.raises(ValueError):
        repo.preview([change(repo, 'format = [')], reason='Invalid')
    with pytest.raises(ValueError):
        repo.preview([change(repo, 'format = "local-config-9"')], reason='Incomplete')
    save(repo, [change(repo, 'format = "local-config-9"', validated=False)])
    with pytest.raises(ConfigurationConflict, match='draft_not_activatable'):
        activate(repo)


@pytest.mark.parametrize('alter', [
    lambda d: d.update(unknown='forbidden'),
    lambda d: d['agents']['executor']['environment'].update(API_TOKEN='synthetic-credential'),
    lambda d: d['git'].update(author_name='Bearer synthetic'),
    lambda d: d.update(projects=[]),
])
def test_forbidden_fields(setup, alter):
    repo, data, _ = setup
    alter(data)
    with pytest.raises(ValueError):
        repo.preview([change(repo, dumps(data))], reason='Rejected')


def test_size_state_path_and_external_edit(setup):
    repo, data, root = setup
    with pytest.raises(ValueError):
        parse('a' * 65537, 'global')
    bad = copy.deepcopy(data)
    bad['service']['state_dir'] = str(root)
    with pytest.raises(ConfigurationConflict, match='state_directory'):
        repo.preview([change(repo, dumps(bad))], reason='Invalid state move')
    active_global(repo, data)
    old = repo.document('global', 1)
    (root / 'global.toml').write_text('format = "local-config-9"\n# external')
    assert repo.read()['status'] == 'EXTERNAL_CHANGE'
    with pytest.raises(ConfigurationConflict, match='external_configuration_change'):
        save(repo, [change(repo, old)], key='external')
    state = repo.read()
    repo.discard_external('global', expected_version=state['version'], observed_sha256=state['actual_sha256'],
                          reason='Discard external bytes', key='discard')
    assert (root / 'global.toml').read_text() == old and repo.read()['active']['revision'] == 1
    # Explicit import is separate from activation.
    edited = copy.deepcopy(data)
    edited['git']['author_name'] = 'Externally edited author'
    (root / 'global.toml').write_text(dumps(edited))
    save(repo, [change(repo, dumps(edited), import_external=True)], key='external-import')
    assert repo.read()['status'] == 'READY' and repo.read()['active']['revision'] == 1


@pytest.mark.parametrize('stage', ['intended', 'immutable_written', 'working_written', 'files_written', 'before_final_commit'])
def test_crash_recovery_is_explicit_and_idempotent(setup, stage):
    repo, data, _ = setup
    active_global(repo, data)
    data['git']['author_name'] = 'Candidate after crash'
    changes = [change(repo, dumps(data))]
    preview = repo.preview(changes, reason='Synthetic change')
    def crash(point):
        if point == stage:
            raise RuntimeError('Injected crash')
    repo.checkpoint = crash
    with pytest.raises(RuntimeError, match='Injected crash'):
        repo.save(changes, reason='Synthetic change', preview_sha256=preview['sha256'], key='crash')
    with Session(repo.managed.engine) as session:
        operation = session.scalar(select(Operation).where(Operation.idempotency_key == 'crash'))
        operation_id = operation.id
    # Simulates a fresh service, retaining the same paths/database.
    repo = ConfigurationRepository(repo.managed, repo.directory, state_dir=repo.state_dir)
    assert repo.read()['status'] == 'RECOVERY_REQUIRED' and repo.read()['active']['revision'] == 1
    with pytest.raises(ConfigurationConflict, match='recovery_required'):
        repo.preview([change(repo, dumps(data))], reason='Another save')
    recovery = repo.recovery_preview(operation_id)
    with pytest.raises(ConfigurationConflict, match='writers_not_confirmed'):
        repo.recover(operation_id, preview_sha256=recovery['sha256'])
    final = repo.recover(operation_id, preview_sha256=recovery['sha256'], writers_stopped=True)
    assert final['status'] == 'SAVED' and repo.read()['saved']['revision'] == 2
    assert repo.read()['active']['revision'] == 1
    assert repo.save(changes, reason='Synthetic change', preview_sha256=preview['sha256'], key='crash') == final


def test_unknown_bytes_and_recovery_preview_race(setup):
    repo, data, root = setup
    repo.checkpoint = lambda stage: (_ for _ in ()).throw(RuntimeError()) if stage == 'intended' else None
    with pytest.raises(RuntimeError):
        save(repo, [change(repo, dumps(data))])
    with Session(repo.managed.engine) as session:
        operation_id = session.scalar(select(Operation.id))
    recovery = repo.recovery_preview(operation_id)
    (root / 'global.toml').write_text('unknown = "foreign"')
    (root / 'global.toml').chmod(0o600)
    with pytest.raises(ConfigurationConflict, match='unknown_configuration_bytes'):
        repo.recover(operation_id, preview_sha256=recovery['sha256'], writers_stopped=True)
    assert (root / 'global.toml').read_text() == 'unknown = "foreign"'


def test_concurrent_editors_and_idempotency_collision(setup):
    repo, data, _ = setup
    changes = [change(repo, dumps(data))]
    preview = repo.preview(changes, reason='Synthetic change')
    def attempt(key):
        try:
            return repo.save(changes, reason='Synthetic change', preview_sha256=preview['sha256'], key=key)['status']
        except (ConfigurationConflict, BlockingIOError):
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ['one', 'two']))
    assert sorted(results) == ['CONFLICT', 'SAVED']
    with Session(repo.managed.engine) as session:
        key = session.scalar(select(Operation.idempotency_key))
    with pytest.raises(ConfigurationConflict, match='key_reused'):
        repo.save(changes, reason='Other reason', preview_sha256=preview['sha256'], key=key)
    with pytest.raises(ConfigurationConflict, match='stale_configuration_preview'):
        save(repo, changes, key='stale')


@pytest.mark.parametrize('unsafe', ['symlink', 'hardlink', 'permissions', 'fifo', 'parent_symlink'])
def test_private_file_guards(setup, unsafe):
    repo, data, root = setup
    save(repo, [change(repo, dumps(data))])
    path = root / 'global.toml'
    if unsafe == 'parent_symlink':
        moved = root.with_name('moved')
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
    elif unsafe == 'symlink':
        path.unlink()
        path.symlink_to(root / 'absent')
    elif unsafe == 'hardlink':
        os.link(path, root / 'other.toml')
    elif unsafe == 'permissions':
        path.chmod(0o644)
    else:
        path.unlink()
        os.mkfifo(path)
    with pytest.raises((ValueError, OSError)):
        repo.read()


def test_immutable_drift_missing_and_cancel(setup):
    repo, data, root = setup
    active_global(repo, data)
    immutable = next((root / 'versions').rglob('*.toml'))
    immutable.write_text('unknown = true')
    assert repo.read()['status'] == 'INVALID'
    with pytest.raises(ConfigurationConflict, match='immutable_configuration_changed'):
        repo.document('global', 1)
    immutable.unlink()
    assert repo.read()['status'] == 'INVALID'


def test_failed_restart_keeps_previous_authority_and_cancellation(setup):
    repo, data, root = setup
    active_global(repo, data)
    data['git']['author_name'] = 'New candidate'
    save(repo, [change(repo, dumps(data))], key='new')
    pending = activate(repo, key='new-activation')
    (root / 'global.toml').write_text('external = true')
    with pytest.raises(ConfigurationConflict, match='external_change'):
        repo.promote_pending(activation_id=pending['id'], key='restart-new', restarted=True)
    assert repo.read()['active']['revision'] == 1 and repo.read()['pending']['revision'] == 2
    cancelled = repo.cancel_pending(activation_id=pending['id'], expected_versions={'global': repo.read()['version']},
                                    reason='Cancel pending', key='cancel')
    assert cancelled['result']['state'] == 'CANCELLED' and repo.read()['pending'] is None


def test_project_validation_preparation_gate_and_isolation(setup, tmp_path):
    repo, data, _ = setup
    active_global(repo, data)
    root = tmp_path / 'project-one'
    register(repo, root, 'one')
    project = project_data(data, repo, root, 'one')
    save(repo, [change(repo, dumps(project), 'project:one')], key='project-save')
    with pytest.raises(ConfigurationConflict, match='preparation_verifier_required'):
        activate(repo, ('project:one',), key='project-activate')
    repo.project_verifier = lambda session, scope, data: {'synthetic_receipt': digest(dumps(data).encode())}
    activate(repo, ('project:one',), key='project-activate')
    assert repo.read('project:one')['active']['revision'] == 1
    assert repo.read()['active']['revision'] == 1
    assert repo.read('project:two')['active'] is None
    project['project']['id'] = 'two'
    with pytest.raises(ValueError, match='identity'):
        save(repo, [change(repo, dumps(project), 'project:one')], key='wrong-id')


def test_global_impact_requires_complete_exact_project_set(setup, tmp_path):
    repo, data, _ = setup
    active_global(repo, data)
    root = tmp_path / 'one'
    register(repo, root, 'one')
    project = project_data(data, repo, root, 'one')
    repo.project_verifier = lambda *args: {'synthetic_receipt': 'unchanged-technical-content'}
    save(repo, [change(repo, dumps(project), 'project:one')], key='project')
    activate(repo, ('project:one',), key='activate-project')
    data['git']['author_name'] = 'New global author'
    text = dumps(data)
    save(repo, [change(repo, text)], key='new-global')
    with pytest.raises(ConfigurationConflict, match='requires_project_revisions'):
        activate(repo, key='new-global-activation')
    project['global'] = {'revision': 2, 'sha256': digest(text.encode())}
    save(repo, [change(repo, dumps(project), 'project:one')], key='derived-project')
    pending = activate(repo, ('global', 'project:one'), key='bundle')
    assert repo.read('project:one')['active']['revision'] == 1
    repo.promote_pending(activation_id=pending['id'], key='restart-bundle', restarted=True)
    assert repo.read()['active']['revision'] == repo.read('project:one')['active']['revision'] == 2


def test_multifile_partial_recovery(setup, tmp_path):
    repo, data, _ = setup
    active_global(repo, data)
    changes = []
    for project_id in ('one', 'two'):
        root = tmp_path / project_id
        register(repo, root, project_id)
        changes.append(change(repo, dumps(project_data(data, repo, root, project_id)), 'project:' + project_id))
    count = 0
    def crash(stage):
        nonlocal count
        if stage == 'working_written':
            count += 1
            if count == 1:
                raise RuntimeError('Partial publication')
    repo.checkpoint = crash
    with pytest.raises(RuntimeError):
        save(repo, changes, key='bundle-save')
    with Session(repo.managed.engine) as session:
        op_id = session.scalar(select(Operation.id).where(Operation.idempotency_key == 'bundle-save'))
    repo.checkpoint = lambda stage: None
    preview = repo.recovery_preview(op_id)
    repo.recover(op_id, preview_sha256=preview['sha256'], writers_stopped=True)
    assert all(repo.read('project:' + name)['saved']['revision'] == 1 for name in ('one', 'two'))


def test_restored_database_never_reads_original_paths(setup, monkeypatch):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    from my_harness.storage import configuration
    monkeypatch.setattr(configuration, 'is_read_only_archive', lambda engine: True)
    monkeypatch.setattr(repo, '_files', lambda session: pytest.fail('Archive accessed original paths'))
    assert repo.read()['status'] == 'READ_ONLY_ARCHIVE'
    with pytest.raises(ConfigurationConflict, match='read_only_archive'):
        repo.preview([], reason='Forbidden')
    with pytest.raises(ConfigurationConflict, match='read_only_archive'):
        repo.recover('unknown', preview_sha256='unknown', writers_stopped=True)


def test_additive_migration_and_metadata(setup, migrated_database):
    repo, _, _ = setup
    assert len(inspect(repo.managed.engine).get_table_names()) == 80  # 79 product tables + alembic_version
    command.downgrade(migrated_database[1], '0025_project_work_languages')
    with pytest.raises(RuntimeError):
        require_schema(repo.managed.engine)
    command.upgrade(migrated_database[1], 'head')
    require_schema(repo.managed.engine)


def test_history_prevents_lossy_downgrade(setup, migrated_database):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    with pytest.raises(RuntimeError, match='history cannot be represented'):
        command.downgrade(migrated_database[1], '0025_project_work_languages')
    require_schema(repo.managed.engine)


def test_pending_allows_draft_without_replacing_confirmed_candidate(setup):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    pending = activate(repo)
    save(repo, [change(repo, 'format = "local-config-9"', validated=False)], key='draft-while-pending')
    assert repo.read()['saved']['status'] == 'DRAFT' and repo.read()['pending']['revision'] == 1
    repo.promote_pending(activation_id=pending['id'], key='restart', restarted=True)
    assert repo.read()['active']['revision'] == 1 and repo.read()['saved']['revision'] == 2


def test_intent_is_bound_to_installation_paths(setup, tmp_path):
    repo, data, _ = setup
    repo.checkpoint = lambda stage: (_ for _ in ()).throw(RuntimeError()) if stage == 'intended' else None
    with pytest.raises(RuntimeError):
        save(repo, [change(repo, dumps(data))])
    with Session(repo.managed.engine) as session:
        op_id = session.scalar(select(Operation.id))
    other = tmp_path / 'other-private-directory'
    other.mkdir(mode=0o700)
    moved = ConfigurationRepository(repo.managed, other, state_dir=repo.state_dir)
    with pytest.raises(ConfigurationConflict, match='directory_changed'):
        moved.recovery_preview(op_id)
    assert list(other.iterdir()) == []


def test_discard_replays_after_working_copy_is_restored(setup):
    repo, data, root = setup
    save(repo, [change(repo, dumps(data))])
    (root / 'global.toml').write_bytes(b'\xff invalid external bytes')
    state = repo.read()
    args = {'expected_version': state['version'], 'observed_sha256': state['actual_sha256'],
            'reason': 'Discard invalid bytes', 'key': 'discard'}
    result = repo.discard_external('global', **args)
    assert repo.discard_external('global', **args) == result
    assert (root / 'global.toml').read_text() == dumps(data)


def test_activation_rechecks_under_barrier_after_preview(setup, monkeypatch):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    state = repo.read()
    refs = [{**{k: state['saved'][k] for k in ('scope', 'revision', 'sha256')}, 'expected_version': state['version']}]
    preview = repo.activation_preview(refs, reason='Confirm exact content')
    monkeypatch.setattr(repo, '_blockers', lambda *args: (_ for _ in ()).throw(ConfigurationConflict('pending_work')))
    with pytest.raises(ConfigurationConflict, match='pending_work'):
        repo.activate(refs, reason='Confirm exact content', preview_sha256=preview['sha256'], key='raced')
    assert repo.read()['pending'] is None and repo.read()['active'] is None


def test_draft_rejects_unknown_nested_permissions(setup):
    repo, _, _ = setup
    with pytest.raises(ValueError, match='Unknown configuration fields'):
        save(repo, [change(repo, 'format = "local-config-9"\n[service]\nimplicit_network = true', validated=False)])


def test_backup_requires_explicit_root_for_versioned_files(setup, tmp_path):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    from my_harness.storage.backup import BackupError, create_backup
    target = tmp_path / 'unsupported-backup'
    with pytest.raises(BackupError, match='root|raíz'):
        create_backup(Path(repo.managed.engine.url.database), target, writers_stopped=True)
    assert not (target / 'COMPLETE').exists()


def test_fsync_failure_retains_intent_and_recovers(setup, monkeypatch):
    repo, data, _ = setup
    from my_harness.storage import configuration_files
    real_sync = configuration_files.os.fsync
    failed = False
    def sync(fd):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError('Synthetic fsync failure')
        return real_sync(fd)
    monkeypatch.setattr(configuration_files.os, 'fsync', sync)
    with pytest.raises(OSError, match='fsync failure'):
        save(repo, [change(repo, dumps(data))])
    with Session(repo.managed.engine) as session:
        op_id = session.scalar(select(Operation.id).where(Operation.kind == 'SAVE'))
    assert repo.read()['status'] == 'RECOVERY_REQUIRED'
    preview = repo.recovery_preview(op_id)
    repo.recover(op_id, preview_sha256=preview['sha256'], writers_stopped=True)
    assert repo.read()['saved']['revision'] == 1


def test_concurrent_activations_commit_one_authority(setup):
    repo, data, _ = setup
    save(repo, [change(repo, dumps(data))])
    state = repo.read()
    refs = [{**{k: state['saved'][k] for k in ('scope', 'revision', 'sha256')}, 'expected_version': state['version']}]
    preview = repo.activation_preview(refs, reason='Concurrent activation')
    def attempt(key):
        try:
            return repo.activate(refs, reason='Concurrent activation', preview_sha256=preview['sha256'], key=key)['status']
        except ConfigurationConflict:
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ['first', 'second']))
    assert sorted(results) == ['APPLIED', 'CONFLICT']
    assert repo.read()['pending']['revision'] == 1


# This fixture creates only a synthetic checkout. No worker or provider is launched.
from test_managed import context  # noqa: E402,F401


@pytest.mark.parametrize('status', ['QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED', 'ACCEPTANCE_READY'])
def test_real_pending_work_blocks_activation_but_allows_save(setup, context, status):
    repo, data, _ = setup
    from test_managed import submit
    from my_harness.storage.models import ManagedJobRow, ManagedRunRow
    job = submit(repo.managed, context)
    with repo.managed._write() as session:
        session.get(ManagedJobRow, job.id).status = status if status != 'ACCEPTANCE_READY' else 'COMPLETED'
        if status == 'ACCEPTANCE_READY':
            session.get(ManagedRunRow, job.run_id).status = status
    save(repo, [change(repo, dumps(data))])
    with pytest.raises(ConfigurationConflict, match='pending_work'):
        activate(repo)
    assert repo.read()['saved']['revision'] == 1 and repo.read()['pending'] is None


def test_global_activation_includes_unregistered_definition_roots(setup, context, tmp_path):
    repo, data, _ = setup
    from test_managed import submit
    from my_harness.storage.models import ManagedJobRow, PlanningConversationRow, PlanningTurnRow
    job = submit(repo.managed, context)
    other_root = str(tmp_path / 'unregistered-definition')
    with repo.managed._write() as session:
        session.get(ManagedJobRow, job.id).status = 'COMPLETED'
        now = repo.managed._now()
        session.add(PlanningConversationRow(id='synthetic-conversation', root=other_root, kind='definition',
            title='Synthetic definition', known={}, deferred={}, log=[], actor={}, version=1, created_at=now, updated_at=now))
        session.flush()
        session.add(PlanningTurnRow(id='synthetic-turn', conversation_id='synthetic-conversation', number=1,
            run_id=job.run_id, status='ANSWERED', message='Synthetic', request={}, request_sha256='a' * 64,
            result={}, actor={}, created_at=now))
    save(repo, [change(repo, dumps(data))])
    with pytest.raises(ConfigurationConflict, match='pending_work'):
        activate(repo)


def failed_intake(repo, context, kind):
    """Two finished, unchanged synthetic failures; no provider or worker is invoked."""
    from test_managed import submit
    from my_harness.storage.models import ManagedJobRow, PlanningConversationRow, PlanningTurnRow
    now = repo.managed._now()
    with repo.managed._write() as session:
        session.add(PlanningConversationRow(id='failed-intake', root=str(context.root), kind=kind,
            title='Synthetic intake', known={}, deferred={}, log=[], actor={}, version=2,
            created_at=now, updated_at=now))
    for number in (1, 2):
        job = submit(repo.managed, context, key=f'failed-turn-{number}')
        with repo.managed._write() as session:
            session.get(ManagedJobRow, job.id).status = 'DONE'
            session.add(PlanningTurnRow(id=f'failed-turn-{number}', conversation_id='failed-intake',
                number=number, run_id=job.run_id, status='FAILED', message='Synthetic', request={},
                request_sha256='a' * 64, result={'status': 'FAILED', 'result': None,
                    'observed': {'before': {'drafts': {}}, 'after': {'drafts': {}}, 'unchanged': True}},
                actor={}, created_at=now, finished_at=now))


@pytest.mark.parametrize('kind', ['definition', 'onboarding'])
def test_empty_failed_intake_allows_timeout_activation_without_rewriting_history(setup, context, kind):
    repo, data, _ = setup
    failed_intake(repo, context, kind)
    from my_harness.storage.models import PlanningTurnRow, PlanningConversationRow
    with Session(repo.managed.engine) as session:
        before = [(t.id, t.status, t.result) for t in session.scalars(select(PlanningTurnRow))]
    data['agents']['reviewer']['timeout_seconds'] = 3600
    save(repo, [change(repo, dumps(data))])
    operation = activate(repo)
    assert repo.read()['pending']['revision'] == 1
    repo.promote_pending(activation_id=operation['id'], key='restart', restarted=True)
    assert repo.read()['active']['revision'] == 1
    with Session(repo.managed.engine) as session:
        assert [(t.id, t.status, t.result) for t in session.scalars(select(PlanningTurnRow))] == before
        assert session.get(PlanningConversationRow, 'failed-intake').version == 2


@pytest.mark.parametrize('blocker', ['answered', 'queued', 'unknown', 'no_observation', 'changed',
    'partial_result', 'observed_draft', 'known', 'edit_log', 'deferred', 'proposal'])
def test_failed_intake_exception_keeps_adoptable_or_uncertain_work_blocked(setup, context, blocker):
    repo, data, _ = setup
    failed_intake(repo, context, 'onboarding')
    from my_harness.storage.models import PlanningConversationRow, PlanningTurnRow, PlanningProposalRow
    with repo.managed._write() as session:
        conversation = session.get(PlanningConversationRow, 'failed-intake')
        turn = session.get(PlanningTurnRow, 'failed-turn-1')
        result = copy.deepcopy(turn.result)
        if blocker in ('answered', 'queued', 'unknown'):
            turn.status = blocker.upper()
        elif blocker == 'no_observation':
            result['observed'] = None
        elif blocker == 'changed':
            result['observed']['unchanged'] = False
        elif blocker == 'partial_result':
            result['result'] = {'answer': 'Synthetic rejected output'}
        elif blocker == 'observed_draft':
            for side in ('before', 'after'):
                result['observed'][side]['drafts'] = {'AGENTS.md': 'b' * 64}
        elif blocker == 'known':
            conversation.known = {'AGENTS.md': 'b' * 64}
        elif blocker == 'edit_log':
            conversation.log = [{'source': 'api', 'path': 'AGENTS.md'}]
        elif blocker == 'deferred':
            conversation.deferred = {'question': {'reason': 'Synthetic deferral'}}
        else:
            session.add(PlanningProposalRow(id='synthetic-proposal', conversation_id=conversation.id,
                turn_id=turn.id, number=1, kind='draft', path='AGENTS.md', content='Synthetic',
                reason='Synthetic', content_sha256='a' * 64, proposal_sha256='b' * 64,
                status='PROPOSED', version=1, created_at=repo.managed._now()))
        turn.result = result
    save(repo, [change(repo, dumps(data))])
    with pytest.raises(ConfigurationConflict, match='pending_work'):
        activate(repo)
    assert repo.read()['pending'] is None


def test_editor_errors_follow_visual_language(setup):
    from my_harness.i18n import emission
    with emission('es'), pytest.raises(ValueError, match='TOML de configuración inválido'):
        parse('invalid = [', 'global')
    with emission('es'), pytest.raises(ValueError, match='Ámbito de configuración inválido'):
        parse('format = "local-config-9"', 'project:../invalid')


def test_restart_verifies_pending_bytes_after_a_newer_draft_was_saved(setup):
    repo, data, root = setup
    save(repo, [change(repo, dumps(data))])
    pending = activate(repo)
    save(repo, [change(repo, 'format = "local-config-9"', validated=False)], key='draft')
    immutable = next((root / 'versions' / 'global').glob('1-*.toml'))
    altered = copy.deepcopy(data)
    altered['git']['author_name'] = 'Unconfirmed replacement'
    immutable.write_text(dumps(altered))
    with pytest.raises(ConfigurationConflict, match='immutable_configuration_changed'):
        repo.promote_pending(activation_id=pending['id'], key='restart', restarted=True)
    state = repo.read()
    assert state['active'] is None and state['pending']['revision'] == 1 and state['status'] == 'INVALID'


def test_lost_acknowledgement_after_final_commit_keeps_saved_result(setup, monkeypatch):
    repo, data, _ = setup
    from contextlib import contextmanager
    original = repo.managed._write
    calls = 0
    @contextmanager
    def write():
        nonlocal calls
        calls += 1
        current = calls
        with original() as session:
            yield session
        if current == 3:  # Intent, file publication, final revision commit.
            raise RuntimeError('Synthetic lost commit acknowledgement')
    monkeypatch.setattr(repo.managed, '_write', write)
    changes = [change(repo, dumps(data))]
    preview = repo.preview(changes, reason='Synthetic change')
    result = save(repo, changes)
    assert result['status'] == 'SAVED' and repo.read()['saved']['revision'] == 1
    assert save_replay(repo, changes, preview) == result
