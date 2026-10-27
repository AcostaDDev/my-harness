"""Opt-in v8 formatters: synthetic tools/agents, temporary checkouts and native command journals only."""
import copy
from dataclasses import asdict
import hashlib
import json
from unittest.mock import patch

import pytest

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.serialization import restore_context
from my_harness.services.local_config import LocalConfigError, build, summary
from my_harness.services.managed import LocalSupervisor
from test_declared_profiles import django, tool, tools, PLAN, TASK, PHASE  # noqa: F401 (fixture)
from test_local_config import launches, setup, web  # noqa: F401 (fixtures)
from test_typescript_profile import repository  # noqa: F401 (fixture)


def formatted(data):
    value = copy.deepcopy(data)
    value['format'] = 'local-config-8'
    value['profiles']['python-django'].update(formatter_argv=['ruff', 'format', '--'], formatter_paths=['*.py'])
    return value


def test_v8_load_and_summary_disclose_the_formatter_without_processes(django):
    _, data, tmp_path = django
    with patch('subprocess.Popen', side_effect=AssertionError('Configuration must remain data-only')):
        config = build(formatted(data), tmp_path / 'operator/config.toml')
        project = config.projects[0]
        profile = project.context.profile
        assert profile.formatter_argv == ('ruff', 'format', '--') and profile.formatter_paths == ('*.py',)
        assert config.ports_factory(project.context, project.versions)[1].config.formatter_argv == profile.formatter_argv
        shown = summary(config)['profiles']['python-django']
    assert shown['formatter_argv'] == ['ruff', 'format', '--'] and shown['formatter_paths'] == ['*.py']
    assert shown['sha256'] == hashlib.sha256(freeze(asdict(profile)).encode()).hexdigest()
    assert shown['validations'] == [entry['argv'] for entry in data['profiles']['python-django']['validations']]
    assert not launches(tmp_path) and not tools(tmp_path)


@pytest.mark.parametrize('fmt', ['local-config-4', 'local-config-5', 'local-config-6', 'local-config-7'])
def test_older_formats_still_reject_formatter_declarations(django, fmt):
    _, data, tmp_path = django
    value = {**formatted(data), 'format': fmt}
    with pytest.raises(LocalConfigError, match='formatter_argv'):
        build(value, tmp_path / 'operator/config.toml')
    assert not launches(tmp_path) and not tools(tmp_path)


@pytest.mark.parametrize('change', ['argv-only', 'paths-only', 'empty-argv', 'empty-paths', 'wrong-argv-type',
    'wrong-paths-type', 'shell', 'operator', 'substitution', 'absolute-command', 'no-terminator',
    'absolute-pattern', 'escaping-pattern', 'duplicate-pattern', 'nul', 'unmapped', 'unauthorized'])
def test_invalid_formatter_pairs_never_launch_anything(django, change):
    _, data, tmp_path = django
    value = formatted(data)
    profile, composition = value['profiles']['python-django'], value['compositions']['django']
    if change == 'argv-only':
        del profile['formatter_paths']
    elif change == 'paths-only':
        del profile['formatter_argv']
    elif change == 'empty-argv':
        profile['formatter_argv'] = []
    elif change == 'empty-paths':
        profile['formatter_paths'] = []
    elif change == 'wrong-argv-type':
        profile['formatter_argv'] = 'ruff format --'
    elif change == 'wrong-paths-type':
        profile['formatter_paths'] = '*.py'
    elif change == 'shell':
        profile['formatter_argv'] = ['sh', '-c', 'echo synthetic', '--']
    elif change == 'operator':
        profile['formatter_argv'] = ['ruff', 'format', '&&', 'mypy', '--']
    elif change == 'substitution':
        profile['formatter_argv'] = ['ruff', '$(pwd)', '--']
    elif change == 'absolute-command':
        profile['formatter_argv'][0] = '/tools/ruff'
    elif change == 'no-terminator':
        profile['formatter_argv'] = ['ruff', 'format']
    elif change == 'absolute-pattern':
        profile['formatter_paths'] = ['/outside/*.py']
    elif change == 'escaping-pattern':
        profile['formatter_paths'] = ['../outside/*.py']
    elif change == 'duplicate-pattern':
        profile['formatter_paths'] = ['*.py', '*.py']
    elif change == 'nul':
        profile['formatter_argv'][1] += '\0'
    elif change == 'unmapped':
        profile['formatter_argv'][0] = 'unknown-formatter'
    elif change == 'unauthorized':
        composition['authorize_profile_commands'] = False
    with patch('subprocess.Popen', side_effect=AssertionError('Invalid configuration launched a process')):
        with pytest.raises(LocalConfigError):
            build(value, tmp_path / 'operator/config.toml')
    assert not launches(tmp_path) and not tools(tmp_path)


def test_v7_and_v8_without_a_formatter_keep_the_same_context_and_effective_hashes(django):
    _, data, tmp_path = django
    projects = []
    for fmt in ('local-config-7', 'local-config-8'):
        config = build({**data, 'format': fmt}, tmp_path / 'operator/config.toml')
        projects.append(config.projects[0])
        assert 'formatter_argv' not in summary(config)['profiles']['python-django']
    before, after = projects
    assert before.context == after.context
    assert {key for key in before.versions if before.versions[key] != after.versions[key]} == {'local_config'}
    assert not launches(tmp_path) and not tools(tmp_path)


@pytest.mark.parametrize('change', ['enable', 'argv', 'paths'])
def test_formatter_changes_quarantine_old_jobs_before_effects(django, repository, change):
    _, data, tmp_path = django
    value = formatted(data)
    if change == 'enable':
        del value['profiles']['python-django']['formatter_argv']
        del value['profiles']['python-django']['formatter_paths']
    original = build(value, tmp_path / 'operator/config.toml').projects[0]
    job = repository.submit(original.context, TASK, PHASE, PLAN, dict(original.versions), key='before-formatter')
    before = repository.get_run(job.run_id)
    if change == 'enable':
        value = formatted(data)
    elif change == 'argv':
        value['profiles']['python-django']['formatter_argv'] = ['ruff', 'format', '--quiet', '--']
    else:
        value['profiles']['python-django']['formatter_paths'] = ['shop/*.py']
    current = build(value, tmp_path / 'operator/config.toml')
    project = current.projects[0]
    assert project.versions['local_config_sha256'] != original.versions['local_config_sha256']
    assert (project.versions['command_config_sha256'] == original.versions['command_config_sha256']) == (change == 'paths')
    for factory in (current.ports_factory, current.commit_factory):
        with pytest.raises(JournalError, match='differs from the frozen'):
            factory(project.context, original.versions)
    with pytest.raises(JournalError, match='differs from the frozen'):
        LocalSupervisor(repository, current.ports_factory, commit_factory=current.commit_factory).run_once()
    after = repository.get_run(job.run_id)
    assert after.status == 'RECOVERY_REQUIRED' and after.history == before.history
    assert after.versions_json == before.versions_json
    assert not launches(tmp_path) and not tools(tmp_path)


@pytest.mark.parametrize('enabled', [False, True])
def test_native_declared_formatter_precedes_validation_and_binds_the_reviewed_commit(django, repository, enabled):
    checkout, data, tmp_path = django
    value = formatted(data)
    if not enabled:
        del value['profiles']['python-django']['formatter_argv']
        del value['profiles']['python-django']['formatter_paths']
    value['projects'][0]['policy']['max_revision_cycles'] = 0
    # A synthetic style rule, not Ruff or private fixture output. Both forms compute the same result.
    body = '''
from pathlib import Path
path = Path('shop/pricing.py')
if sys.argv[1:3] == ['format', '--']:
    assert sys.argv[3:] == ['shop/pricing.py']
    path.write_text(path.read_text().replace('return tasks * 30', 'return 30 * tasks'))
elif sys.argv[1:] == ['format', '--check', '.']:
    sys.exit(0 if 'return 30 * tasks' in path.read_text() else 1)
'''
    value['compositions']['django']['executables']['ruff'] = tool(tmp_path / 'bin', 'ruff', body)
    config = build(value, tmp_path / 'operator/config.toml')
    project = config.projects[0]
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='format-journey')
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert supervisor.run_once().status == 'DONE'
    record = repository.get_run(job.run_id)
    cycle = record.history.cycles[0]
    assert restore_context(record.history.context_json).profile == project.context.profile
    assert [item.request.role for item in record.history.attempts] == ['executor', 'reviewer']
    calls = [tuple(call) for call in tools(tmp_path)]
    processes = repository.command_processes(job.id)
    if not enabled:
        assert record.status == 'STOPPED' and not cycle.validation.all_passed
        assert cycle.formatting_json is None and all(row['spec']['authorization'] == 'exact-command' for row in processes)
        assert ('ruff', 'format', '--', 'shop/pricing.py') not in calls
        return
    assert record.status == 'ACCEPTANCE_READY' and cycle.validation.all_passed
    formatting = json.loads(cycle.formatting_json)
    assert formatting['paths'] == ['shop/pricing.py'] and formatting['result']['exit_code'] == 0
    assert calls[2] == ('ruff', 'format', '--', 'shop/pricing.py')
    assert calls[3:] == [command.argv for command in project.context.profile.validations]
    assert len(processes) == 9 and processes[2]['spec']['authorization'] == 'formatter-paths'
    assert 'return 30 * tasks' in (checkout / 'shop/pricing.py').read_text()
    review = json.loads(record.history.attempts[-1].request.prompt_snapshot_json)['parts'][0]['variables']['INPUT_JSON']
    assert json.loads(review)['formatting'] == formatting
    assert cycle.evidence == record.history.acceptance.evidence
    repository.submit_commit(job.run_id, key='formatted-commit', expected_version=record.version)
    assert supervisor.run_once().status == 'DONE'
    assert repository.get_run(job.run_id).status == 'COMMITTED'
    from test_git import git
    assert 'return 30 * tasks' in git(checkout, 'show', 'HEAD:shop/pricing.py')
    assert git(checkout, 'status', '--porcelain') == ''
