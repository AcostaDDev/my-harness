"""P008-T008: profiles declared in the local TOML (`local-config-4`), starting with `python-django`.

The profile comes from `examples/local_config.example.toml`. Synthetic CLIs through the real adapter, fake Python
tools (pytest, ruff, mypy, python) with exact argv, temporary Git and SQLite; no providers or network.
"""
import copy
import json
from pathlib import Path
import shutil
import sys
import tomllib

import pytest

from my_harness.adapters.git import GitWorktrees
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.serialization import restore_context
from my_harness.services.local_config import LocalConfigError, build, load_local_config, summary
from my_harness.services.managed import LocalSupervisor
from test_git import git
from test_local_config import PROBE, USER, dumps, launches, setup, write  # noqa: F401 (fixture)
from test_project_registry import v3
from test_typescript_profile import repository, web  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / 'examples/local_config.example.toml'
TASK, PHASE = 'P001-T001', 'P001'
PLAN = """# Synthetic Django task
## P001-T001 — Correct the estimate
**Objective:** Calculate thirty minutes per task.
**Allowed paths:** `shop/pricing.py`
**Acceptance criteria:**
- Three tasks take ninety minutes.
**Validation commands:**
**Executor:** synthetic-executor / medium — Explicit offline selection
"""
VERSIONS = {'codex': '0.163.0', 'claude': '2.1.304'}
# Fake tools: they record their argv; pytest checks the real checkout code and writes JUnit.
PYTEST = """
import os, pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.getcwd())
from shop.pricing import estimate
ok = estimate(3) == 90
report = pathlib.Path(next(a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('--junitxml=')))
report.parent.mkdir(exist_ok=True)
failure = '' if ok else '<failure message="estimate(3) != 90"/>'
report.write_text('<testsuite name="pytest" tests="1"><testcase classname="shop.tests" name="test_estimate" '
                  f'time="0.01">{failure}</testcase></testsuite>')
sys.exit(0 if ok else 1)
"""


def django_profile():
    return copy.deepcopy(tomllib.loads(EXAMPLE.read_text())['profiles']['python-django'])


def tool(folder, name, body=''):
    path = folder / name
    record = "import json, os, sys\nwith open(os.environ['TOOLS_RECORD'], 'a') as log:\n" \
             "    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + '\\n')\n"
    path.write_text(f'#!{sys.executable}\n{record}{body or "print(\'ok\')"}\n')
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def django(tmp_path):
    """Synthetic Django checkout with a regression, its task worktree and `local-config-4` data."""
    main = tmp_path / 'shop-main'
    (main / 'shop').mkdir(parents=True)
    (main / 'docs').mkdir()
    (main / 'shop/__init__.py').write_text('')
    (main / 'shop/pricing.py').write_text('def estimate(tasks: int) -> int:\n    return tasks * 45\n')
    (main / 'shop/models.py').write_text('from django.db import models\n\n\nclass Order(models.Model):\n'
                                         '    tasks = models.IntegerField()\n')
    (main / 'manage.py').write_text('"""Synthetic manage.py; never executed by the fake python."""\n')
    (main / '.gitignore').write_text('.local/\n__pycache__/\n')
    (main / 'docs/STATE.md').write_text('Synthetic Django state\n')
    (main / 'docs/NEXT_STEPS.md').write_text(PLAN)
    (main / 'docs/DDBB-DIAGRAM.md').write_text('# Datos\n\nOrder(tasks)\n')
    (main / 'AGENTS.md').write_text('# Synthetic Django\n\nInstrucciones sintéticas para agentes.\n')
    git(main, 'init', '-q', '-b', 'main')
    git(main, 'add', '-A')
    git(main, 'commit', '-q', '-m', 'synthetic django baseline')
    checkout = GitWorktrees().prepare(main, tmp_path / 'shop-task', branch='harness/P001-T001').path
    for folder in ('state', 'operator', 'bin', 'home'):
        (tmp_path / folder).mkdir()
    bin_ = tmp_path / 'bin'
    executables = {'python': tool(bin_, 'python'), 'pytest': tool(bin_, 'pytest', PYTEST),
                   'ruff': tool(bin_, 'ruff'), 'mypy': tool(bin_, 'mypy')}
    provider_env = {'USER': USER, 'PROBE_RECORD': str(tmp_path / 'launches.jsonl'), 'PROBE_MEMORY_REQUIRED': '1',
                    'PROBE_TRUST_REQUIRED': '1'}

    def agent(provider, reviewer):
        value = {'provider': provider, 'executable': [sys.executable, PROBE, provider, 'django'],
                 'cli_version': VERSIONS[provider], 'timeout_seconds': 20,
                 'environment': {**provider_env, 'PROBE_VERSION': VERSIONS[provider]}}
        if reviewer:
            value.update(model='synthetic-reviewer', effort='high')
        else:
            value.update(tools=['Read', 'Edit'], allowed_tools=['Read', 'Edit'])
        return value

    data = {
        'format': 'local-config-4',
        'service': {'state_dir': str(tmp_path / 'state'), 'supervisor': False},
        'git': {'executable': shutil.which('git'), 'author_name': 'Local Writer',
                'author_email': 'local@example.invalid'},
        'agents': {'reviewer': agent('codex', True), 'executor': agent('claude', False)},
        'registration': {'roots': [], 'bootstrap_enabled': False},
        'profiles': {'python-django': django_profile()},
        'compositions': {'django': {
            'profile': 'python-django', 'authorize_profile_commands': True, 'executables': executables,
            'environment': {'PATH': '/usr/bin:/bin', 'HOME': str(tmp_path / 'home'), 'LANG': 'C.UTF-8',
                            'TOOLS_RECORD': str(tmp_path / 'tools.jsonl')}}},
        'projects': [{'id': 'shop', 'root': str(checkout), 'repository_trusted': True, 'composition': 'django',
                      'policy': {'planning_mode': 'deterministic', 'executor_mode': 'catalog',
                                 'executor_models': ['synthetic-executor'], 'executor_efforts': ['medium'],
                                 'max_revision_cycles': 1}}]}
    return checkout, data, tmp_path


def tools(tmp_path):
    path = tmp_path / 'tools.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_python_django_profile_from_the_example_composes_without_processes(django):
    checkout, data, tmp_path = django
    config = load_local_config(write(tmp_path / 'operator', data))
    (project,) = config.projects
    profile = project.context.profile
    assert profile.name == 'python-django' and project.versions['profile'] == 'python-django'
    assert project.versions['local_config'] == 'local-config-4' and config.registrar.registrable
    assert [c.argv for c in profile.validations] == [
        ('pytest', '--junitxml=.local/junit.xml', '-q'), ('ruff', 'check', '.'), ('ruff', 'format', '--check', '.'),
        ('mypy', '.'), ('python', 'manage.py', 'check'),
        ('python', 'manage.py', 'makemigrations', '--check', '--dry-run', '--noinput')]
    (junit,) = profile.junit_reports
    assert junit.command == profile.validations[0] and junit.path == '.local/junit.xml'
    assert profile.data_model_paths == ('**/models.py', '**/models/**', '**/migrations/**')
    assert 'docs/DECISIONS.md' in profile.protected_paths and profile.sensitive_allowlist == ('.env.example',)
    runner = config.ports_factory(project.context, project.versions)[1]
    assert runner.config.authorized_commands == profile.preparation + profile.validations
    shown = summary(config)
    assert shown['profiles']['python-django']['validations'][0] == ['pytest', '--junitxml=.local/junit.xml', '-q']
    assert shown['registration']['compositions'][0]['profile'] == 'python-django'
    assert not launches(tmp_path) and not tools(tmp_path)


def test_check_config_validates_the_declared_profile_and_rejects_shell(django, capsys):
    from my_harness.cli import main
    checkout, data, tmp_path = django
    assert main(['check-config', str(write(tmp_path / 'operator', data))]) == 0
    result = json.loads(capsys.readouterr().out)
    assert set(result['profiles']) == {'python-django'} and len(result['profiles']['python-django']['sha256']) == 64
    data['profiles']['python-django']['validations'].append({'argv': ['bash', '-c', 'pytest'], 'timeout_seconds': 5})
    assert main(['check-config', str(write(tmp_path / 'operator', data))]) == 1
    assert 'shell' in capsys.readouterr().err
    assert not launches(tmp_path) and not tools(tmp_path)


def mutate(data, change):
    data = copy.deepcopy(data)
    profile, composition = data['profiles']['python-django'], data['compositions']['django']
    validations = profile['validations']
    if change == 'unknown-key':
        profile['formatter_argv'] = ['ruff', 'format']
    elif change == 'missing-key':
        del profile['data_model_paths']
    elif change == 'unknown-command-key':
        validations[1]['shell'] = True
    elif change == 'unknown-junit-key':
        validations[0]['junit']['format'] = 'xunit2'
    elif change == 'shell-executable':
        validations[1]['argv'] = ['sh', '-c', 'ruff check .']
    elif change == 'shell-operator':
        validations[1]['argv'] = ['ruff', 'check', '.', '&&', 'mypy', '.']
    elif change == 'shell-substitution':
        validations[1]['argv'] = ['ruff', 'check', '$(pwd)']
    elif change == 'path-executable':
        validations[1]['argv'] = ['/usr/bin/ruff', 'check', '.']
    elif change == 'shell-prefix':
        profile['allowed_command_prefixes'].append(['bash'])
    elif change == 'shell-mapped':
        composition['executables']['ruff'] = '/bin/sh'
    elif change == 'no-validations':
        profile['validations'] = []
    elif change == 'duplicate-validation':
        validations.append(copy.deepcopy(validations[1]))
    elif change == 'no-timeout':
        del validations[1]['timeout_seconds']
    elif change == 'junit-outside':
        validations[0]['junit']['path'] = '../junit.xml'
    elif change == 'escaping-pattern':
        profile['protected_paths'].append('../outside/**')
    elif change == 'empty-protected':
        profile['protected_paths'] = []
    elif change == 'empty-instructions':
        profile['executor_instructions'] = ' '
    elif change == 'builtin-name':
        data['profiles']['typescript-web'] = data['profiles'].pop('python-django')
    elif change == 'bad-name':
        data['profiles']['Python Django'] = data['profiles'].pop('python-django')
    elif change == 'undeclared':
        composition['profile'] = 'python-flask'
    elif change == 'unauthorized-executable':
        del composition['executables']['mypy']
    elif change == 'profiles-in-v3':
        data['format'] = 'local-config-3'
    return data


@pytest.mark.parametrize('change', ['unknown-key', 'missing-key', 'unknown-command-key', 'unknown-junit-key',
    'shell-executable', 'shell-operator', 'shell-substitution', 'path-executable', 'shell-prefix', 'shell-mapped',
    'no-validations', 'duplicate-validation', 'no-timeout', 'junit-outside', 'escaping-pattern', 'empty-protected',
    'empty-instructions', 'builtin-name', 'bad-name', 'undeclared', 'unauthorized-executable', 'profiles-in-v3'])
def test_invalid_declared_profiles_are_rejected_without_effects(django, change):
    checkout, data, tmp_path = django
    with pytest.raises(LocalConfigError):
        build(mutate(data, change), tmp_path / 'operator/my-harness.toml')
    assert not launches(tmp_path) and not tools(tmp_path)


def test_profile_content_enters_the_frozen_hash_and_quarantines_pending_jobs(django, repository):
    checkout, data, tmp_path = django
    folder = tmp_path / 'operator'
    admitted = load_local_config(write(folder, data)).projects[0]
    job = repository.submit(admitted.context, TASK, PHASE, PLAN, dict(admitted.versions), key='changed')
    data['profiles']['python-django']['executor_instructions'] += ' Prefer small functions.'
    current = load_local_config(write(folder, data))
    project = current.projects[0]
    assert project.versions['local_config_sha256'] != admitted.versions['local_config_sha256']
    assert project.versions['command_config_sha256'] == admitted.versions['command_config_sha256']
    for factory in (current.ports_factory, current.commit_factory):
        with pytest.raises(JournalError, match='differs from the frozen one'):
            factory(project.context, admitted.versions)
    supervisor = LocalSupervisor(repository, current.ports_factory, commit_factory=current.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not launches(tmp_path) and not tools(tmp_path)
    # The same file gives the same frozen identity again.
    assert load_local_config(write(folder, data)).projects[0].versions == project.versions


def test_offline_django_journey_through_validation_junit_and_commit(django, repository):
    checkout, data, tmp_path = django
    config = load_local_config(write(tmp_path / 'operator', data))
    project = config.projects[0]
    profile = project.context.profile
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='django')
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert supervisor.run_once().status == 'DONE'
    record = repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    assert restore_context(record.history.context_json).profile == profile
    assert [a.request.role for a in record.history.attempts] == ['executor', 'reviewer']
    assert len(launches(tmp_path)) == 2
    # Profile preparation and validations, by exact argv and in order, with the frozen configuration.
    assert [tuple(call) for call in tools(tmp_path)] == [c.argv for c in profile.preparation + profile.validations]
    rows = repository.command_processes(job.id)
    assert len(rows) == 8 and {r['spec']['config_sha256'] for r in rows} == {project.versions['command_config_sha256']}
    validation = record.history.cycles[0].validation
    assert validation.all_passed and validation.evidence.changed_paths == ('shop/pricing.py',)
    (report,) = validation.entries[0].reports
    assert report.status == 'complete' and report.freshness == 'created'
    assert [(case.name, case.result) for case in report.cases] == [('test_estimate', 'passed')]
    assert all(not entry.reports for entry in validation.entries[1:])
    assert 'tasks * 30' in (checkout / 'shop/pricing.py').read_text()
    repository.submit_commit(job.run_id, key='commit', expected_version=record.version)
    assert supervisor.run_once().status == 'DONE'
    assert repository.get_run(job.run_id).status == 'COMMITTED'
    assert git(checkout, 'log', '-1', '--format=%an <%ae>') == 'Local Writer <local@example.invalid>'
    assert git(checkout, 'status', '--porcelain') == ''


def test_builtin_profiles_keep_their_behaviour_under_local_config_4(setup):
    """The same `typescript-web` composition in v3 and v4: same profile and commands; only the file identity
    changes (format and hash, which in v4 includes the profile). v3 does not accept `[profiles]`."""
    context, data, folder, tmp_path = setup
    old = v3(data, [], toml_project=True)
    new = {**copy.deepcopy(old), 'format': 'local-config-4'}
    before, after = (load_local_config(write(folder, item)).projects[0] for item in (old, new))
    assert after.context == before.context and after.context.profile.name == 'typescript-web'
    changed = {key for key in before.versions if before.versions[key] != after.versions[key]}
    assert changed == {'local_config', 'local_config_sha256'}
    assert summary(load_local_config(write(folder, new)))['profiles'] == {}
    assert not launches(tmp_path)
