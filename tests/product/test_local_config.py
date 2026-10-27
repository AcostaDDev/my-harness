"""local-config-1: operator TOML → real composition; synthetic CLIs, real Node/npm/Git, temporary SQLite."""
from dataclasses import replace
import copy
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys

import pytest

from my_harness.adapters.cli_agents import CLIProcessAdapter
from my_harness.adapters.commands import ManagedCommandRunner
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.journal import JournalError
from my_harness.services.local_config import (CONFIG_ENV, LocalConfigError, build, from_environment,
                                                 load_local_config)
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage.managed import SQLiteManagedRepository
from test_typescript_profile import PHASE, PLAN, TASK, task_checkout, web  # noqa: F401 (fixture)
from test_typescript_profile import repository  # noqa: F401 (fixture)

PROBE = str(Path(__file__).with_name('cli_process_probe.py'))
SENTINEL = 'sentinel-environment-value'
USER = pwd.getpwuid(os.getuid()).pw_name


def dumps(data):
    """Minimal TOML writer for these tests: inline tables and arrays only."""
    def value(item):
        if isinstance(item, bool):
            return 'true' if item else 'false'
        if isinstance(item, (int, float)):
            return repr(item)
        if isinstance(item, str):
            return json.dumps(item)
        if isinstance(item, list):
            return '[' + ', '.join(value(x) for x in item) + ']'
        return '{' + ', '.join(f'{json.dumps(k)} = {value(x)}' for k, x in item.items()) + '}'
    return ''.join(f'{json.dumps(key)} = {value(item)}\n' for key, item in data.items())


@pytest.fixture
def setup(web, tmp_path):
    context, fixture_runner = task_checkout(web, tmp_path)
    state = tmp_path / 'state'
    state.mkdir()
    folder = tmp_path / 'operator'
    folder.mkdir()
    provider_env = {'USER': USER, 'PROBE_RECORD': str(tmp_path / 'launches.jsonl'), 'SECRETLESS': SENTINEL}
    data = {
        'format': 'local-config-1',
        'service': {'state_dir': str(state), 'supervisor': False},
        'git': {'executable': shutil.which('git'), 'author_name': 'Local Writer',
                'author_email': 'local@example.invalid'},
        'providers': {
            'codex': {'executable': [sys.executable, PROBE, 'codex', 'web'], 'cli_version': '0.163.0',
                      'timeout_seconds': 20, 'environment': provider_env},
            'claude': {'executable': [sys.executable, PROBE, 'claude', 'web'], 'cli_version': '2.1.304',
                       'timeout_seconds': 20, 'environment': provider_env,
                       'tools': ['Read', 'Edit'], 'allowed_tools': ['Read', 'Edit']}},
        'projects': [{
            'id': 'web', 'root': str(context.root), 'repository_trusted': True, 'profile': 'typescript-web',
            'policy': {'executor_models': ['synthetic-executor'], 'executor_efforts': ['medium'],
                       'planner_model': 'synthetic-planner', 'planner_effort': 'medium',
                       'reviewer_model': 'synthetic-reviewer', 'reviewer_effort': 'high',
                       'max_revision_cycles': 1},
            'commands': {'authorize_profile_commands': True,
                         'executables': dict(fixture_runner.executables),
                         'environment': {**fixture_runner.environment, 'SECRETLESS': SENTINEL}}}]}
    return context, data, folder, tmp_path


def write(folder, data, name='my-harness.toml', mode=0o600):
    path = folder / name
    path.write_text(dumps(data))
    path.chmod(mode)
    return path


def launches(tmp_path):
    path = tmp_path / 'launches.jsonl'
    return path.read_text().splitlines() if path.exists() else []


def test_valid_configuration_composes_fresh_ports_without_processes(setup):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, data))
    (project,) = config.projects
    assert project.id == 'web' and project.context.root == context.root
    assert project.context.profile.name == 'typescript-web' and project.context.policy.reviewer_effort == 'high'
    assert not config.supervisor and config.migrations_dir == tmp_path / 'state/migrations'
    versions = project.versions
    assert versions['local_config'] == 'local-config-1' and versions['commands'] == 'commands-1'
    assert versions['agent_adapter'] == 'cli-14' and versions['engine'].startswith('harness-local-')
    assert {'cli_config_sha256', 'command_config_sha256', 'local_config_sha256'} <= versions.keys()
    first, second = config.ports_factory(project.context, versions), config.ports_factory(project.context, versions)
    assert [type(port) for port in first] == [CLIProcessAdapter, ManagedCommandRunner, GitWorkspace]
    assert all(a is not b for a, b in zip(first, second))
    assert first[0].artifact_root == tmp_path / 'state/artifacts/web'
    assert first[1].config.authorized_commands == (project.context.profile.preparation
                                                   + project.context.profile.validations)
    assert first[2].executable == shutil.which('git')
    assert isinstance(config.commit_factory(project.context, versions), GitWorkspace)
    assert not launches(tmp_path) and not (tmp_path / 'state/artifacts').exists()
    # Same file, same frozen identity; the example template documents the same keys.
    assert load_local_config(write(folder, data)).projects[0].versions == versions


def test_projects_without_documents_use_the_mandatory_unified_layout_and_quarantine_older_jobs(setup):
    """D088: omitting `documents` equals "v2"; the layout version is among the frozen ones, so a job admitted
    with the previous composition receives no ports or writer (the supervisor quarantines it)."""
    context, data, folder, tmp_path = setup
    (project,) = load_local_config(write(folder, data)).projects
    assert 'documents' not in data['projects'][0] and project.context.documents == 'v2'
    assert project.versions['document_layout'] == 'd088-12'
    explicit = copy.deepcopy(data)
    explicit['projects'][0]['documents'] = 'v2'
    config = load_local_config(write(folder, explicit))
    assert config.projects[0].context == project.context
    for previous in (None, 'd088-1', 'd088-2', 'd088-3', 'd088-4', 'd088-5', 'd088-6', 'd088-7', 'd088-8', 'd088-9', 'd088-10', 'd088-11'):
        older = {key: value for key, value in config.projects[0].versions.items() if key != 'document_layout'}
        if previous is not None:
            older['document_layout'] = previous
        for factory in (config.ports_factory, config.commit_factory):
            with pytest.raises(JournalError, match='differs from the frozen one'):
                factory(project.context, older)
    legacy = copy.deepcopy(data)
    legacy['projects'][0]['documents'] = 'v1'
    with pytest.raises(LocalConfigError, match='D088'):
        load_local_config(write(folder, legacy))
    assert not launches(tmp_path)


def mutate(data, change):
    data = copy.deepcopy(data)
    project, codex = data['projects'][0], data['providers']['codex']
    if change == 'unknown-key':
        data['service']['extra'] = 1
    elif change == 'format':
        data['format'] = 'local-config-0'
    elif change == 'relative-root':
        project['root'] = 'checkout'
    elif change == 'missing-root':
        project['root'] = str(Path(project['root']) / 'missing')
    elif change == 'untrusted':
        project['repository_trusted'] = False
    elif change == 'trust-not-bool':
        project['repository_trusted'] = 'yes'
    elif change == 'profile':
        project['profile'] = 'undeclared'
    elif change == 'models':
        del project['policy']['reviewer_model']
    elif change == 'user':
        codex['environment'] = {**codex['environment'], 'USER': USER + '-other'}
    elif change == 'no-user':
        codex['environment'] = {k: v for k, v in codex['environment'].items() if k != 'USER'}
    elif change == 'cli-version':
        codex['cli_version'] = 'invalid'
    elif change == 'cli-relative':
        codex['executable'] = ['codex']
    elif change == 'git-relative':
        data['git']['executable'] = 'git'
    elif change == 'state-inside':
        data['service']['state_dir'] = project['root']
    elif change == 'not-authorized':
        project['commands']['authorize_profile_commands'] = False
    elif change == 'executable-missing':
        project['commands']['executables']['npm'] = '/missing/npm'
    elif change == 'duplicate':
        data['projects'].append(copy.deepcopy(project))
    elif change == 'env-type':
        project['commands']['environment']['CI'] = 1
    elif change == 'infinite':
        data['service']['lease_seconds'] = float('inf')
    elif change == 'tag-kind':
        project['tag_kind'] = 'signed'
    elif change == 'project-id':
        project['id'] = '../escape'
    elif change == 'authority':
        project['permission_authority'] = {'global': {}}
    return data


@pytest.mark.parametrize('change', ['unknown-key', 'format', 'relative-root', 'missing-root', 'untrusted',
    'trust-not-bool', 'profile', 'models', 'user', 'no-user', 'cli-version', 'cli-relative', 'git-relative',
    'state-inside', 'not-authorized', 'executable-missing', 'duplicate', 'env-type', 'infinite', 'tag-kind',
    'project-id', 'authority'])
def test_invalid_configuration_rejected_without_effects(setup, change):
    context, data, folder, tmp_path = setup
    with pytest.raises(LocalConfigError):
        build(mutate(data, change), folder / 'my-harness.toml')
    assert not launches(tmp_path)


def test_exact_extra_authorization_is_added_not_substituted(setup):
    context, data, folder, _ = setup
    data['projects'][0]['commands']['authorized'] = [{'argv': ['npm', 'run', 'test'], 'timeout_seconds': 1800}]
    config = build(data, folder / 'my-harness.toml')
    runner = config.ports_factory(config.projects[0].context, config.projects[0].versions)[1]
    authorized = runner.config.authorized_commands
    assert len(authorized) == len(context.profile.preparation + context.profile.validations) + 1
    assert authorized[-1].argv == ('npm', 'run', 'test') and authorized[-1].timeout_seconds == 1800


@pytest.mark.parametrize('problem', ['symlink', 'group-writable', 'inside-checkout', 'oversized', 'not-utf8',
                                     'relative', 'invalid-toml'])
def test_configuration_file_must_be_private_local_authority(setup, problem):
    context, data, folder, tmp_path = setup
    path = write(folder, data)
    if problem == 'symlink':
        link = folder / 'link.toml'
        link.symlink_to(path)
        path = link
    elif problem == 'group-writable':
        path.chmod(0o620)
    elif problem == 'inside-checkout':
        path = write(context.root, data)
    elif problem == 'oversized':
        path.write_text(path.read_text() + '#' * 70000)
    elif problem == 'not-utf8':
        path.write_bytes(b'format = "\xff"\n')
    elif problem == 'relative':
        path = Path(os.path.relpath(path))
    else:
        path.write_text('format = \n')
    with pytest.raises(LocalConfigError):
        load_local_config(path)


@pytest.mark.parametrize('change', ['composition', 'document_contract'])
def test_changed_composition_after_admission_quarantines_before_effects(setup, repository, change):
    context, data, folder, tmp_path = setup
    admitted = load_local_config(write(folder, data))
    project = admitted.projects[0]
    frozen_versions = dict(project.versions)
    if change == 'document_contract':
        frozen_versions['document_layout'] = 'd088-3'
    job = repository.submit(project.context, TASK, PHASE, PLAN, frozen_versions, key='changed')
    if change == 'composition':
        data['projects'][0]['commands']['environment']['CI'] = 'changed'
    current = load_local_config(write(folder, data))
    if change == 'composition':
        assert current.projects[0].versions['local_config_sha256'] != project.versions['local_config_sha256']
    supervisor = LocalSupervisor(repository, current.ports_factory, commit_factory=current.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not launches(tmp_path) and not repository.command_processes(job.id)
    assert not repository.get_run(job.run_id).history.attempts


def git_log(root, fmt):
    return subprocess.run(['git', '-C', str(root), 'log', '-1', f'--format={fmt}'], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_offline_typescript_journey_through_local_configuration(setup, repository, migrated_database):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, data))
    project = config.projects[0]
    runtime = ManagedRuntime(repository.engine, config)
    runtime.start()
    try:
        # The runtime binds the work language confirmed in SQLite (synthetic `en` here, D167); nothing else changes.
        assert runtime.project('web').context == replace(project.context, work_language='en')
        assert replace(runtime.project('web'), context=project.context) == project and runtime.worker is None
    finally:
        runtime.stop()
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='journey')
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert supervisor.run_once().status == 'DONE'
    record = repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    attempts = record.history.attempts
    assert [a.request.role for a in attempts] == ['executor', 'reviewer']
    assert all(a.result.status == 'complete' and a.request.fresh_session for a in attempts)
    assert len(launches(tmp_path)) == 2
    rows = repository.command_processes(job.id)
    assert len(rows) == 6 and all(r['status'] == 'STOPPED' for r in rows)
    assert {r['spec']['config_sha256'] for r in rows} == {project.versions['command_config_sha256']}
    validation = record.history.cycles[0].validation
    assert validation.all_passed and validation.entries[1].reports[0].status == 'complete'
    assert 'tasks * 30' in context.path('src/estimate.ts').read_text()
    repository.submit_commit(job.run_id, key='commit', expected_version=record.version)
    assert supervisor.run_once().status == 'DONE'
    assert repository.get_run(job.run_id).status == 'COMMITTED'
    assert git_log(context.root, '%an <%ae>') == 'Local Writer <local@example.invalid>'
    assert len(launches(tmp_path)) == 2 and supervisor.run_once() is None
    restarted = SQLiteManagedRepository(repository.engine)
    assert restarted.get_run(job.run_id) == repository.get_run(job.run_id)


def test_check_config_summary_without_environment_values_and_preflight(setup, capsys):
    from my_harness.cli import main
    context, data, folder, tmp_path = setup
    path = write(folder, data)
    assert main(['check-config', str(path)]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['projects'][0]['id'] == 'web' and 'preflight' not in result
    assert SENTINEL not in output and str(tmp_path / 'launches.jsonl') not in output
    assert main(['check-config', str(path), '--preflight']) == 0
    result = json.loads(capsys.readouterr().out)
    assert all(report['available'] for report in result['preflight'].values())
    assert not launches(tmp_path)  # version/help only; no invocation record
    data['projects'][0]['repository_trusted'] = False
    assert main(['check-config', str(write(folder, data))]) == 1
    assert 'explicit trust' in capsys.readouterr().err


def test_entry_points_require_one_explicit_composition(setup, monkeypatch, tmp_path):
    from my_harness.launcher import serve
    from my_harness.services.managed_runtime import CONFIG_ENV as MANAGED_ENV
    context, data, folder, _ = setup
    path = write(folder, data)
    monkeypatch.setenv(MANAGED_ENV, 'examples.managed_demo:build')
    with pytest.raises(ValueError, match='incompatible'):
        serve(str(tmp_path / 'absent.sqlite3'), 8013, str(path))
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    with pytest.raises(LocalConfigError):
        from_environment()
    monkeypatch.setenv(CONFIG_ENV, str(path))
    assert from_environment().projects[0].id == 'web'
