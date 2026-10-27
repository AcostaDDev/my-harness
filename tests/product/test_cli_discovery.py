"""Automatic detection and frozen launch integrity using independently scripted local clients only."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from my_harness import i18n
from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.adapters.cli_compatibility import CompatibilityError, MINIMUM, discover, launch_identity
from my_harness.adapters.cli_diagnostics import preflight_config
from my_harness.core.engine.journal import JournalError
from my_harness.services.local_config import load_local_config
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedRuntime
from test_agent_roles import PAIRS, journey
from test_cli_agents import setup_invocation
from test_local_config import PROBE, launches, setup, write  # noqa: F401 (fixture)
from test_managed_api import client
from test_project_agents import selection, v5
from test_typescript_profile import PHASE, PLAN, TASK, repository, web  # noqa: F401 (fixtures)


def fake_client(folder, provider, version=None):
    folder.mkdir(exist_ok=True)
    path = folder / provider
    version = version or MINIMUM[provider]
    line = f'codex-cli {version}' if provider == 'codex' else f'{version} (Claude Code)'
    path.write_text(f'''#!{sys.executable}
import json, os, runpy, sys
from pathlib import Path
record = os.environ.get('PROBE_CALLS')
if record:
    with open(record, 'a') as stream: stream.write(json.dumps({{'provider': {provider!r}, 'args': sys.argv[1:]}}) + '\\n')
if sys.argv[1:] == ['--version']:
    print({line!r}); sys.exit(0)
sys.argv = [{PROBE!r}, {provider!r}, 'web', *sys.argv[1:]]
runpy.run_path({PROBE!r}, run_name='__main__')
''')
    path.chmod(0o700)
    return path


def automatic(data, folder, tmp_path, *, reviewer='codex', executor='claude', presets=True, work='en', fmt='local-config-7'):
    binaries = tmp_path / 'bin'
    for provider in ('codex', 'claude'):
        fake_client(binaries, provider)
    value = v5(data, [], toml_project=True, selection=selection(reviewer, executor) if presets else None)
    value['format'] = fmt
    value['projects'][0]['work_language'] = work
    # These cases exercise CLI admission, not npm's descendant-process lifecycle (covered separately).
    # A direct Python validation still checks the edit through the real journal/process-group boundary.
    value['profiles'] = {'cli-discovery': {
        'preparation': [], 'validations': [{'argv': ['python', '-c',
            "from pathlib import Path; assert 'tasks * 30' in Path('src/estimate.ts').read_text()"],
            'timeout_seconds': 10}],
        'allowed_command_prefixes': [['python']], 'protected_paths': ['docs/**'],
        'sensitive_paths': ['.env'], 'data_model_paths': [], 'executor_instructions': 'Preserve the frozen task paths.'}}
    value['compositions']['web'] = {'profile': 'cli-discovery', 'executables': {'python': sys.executable},
                                   'environment': {}, 'authorize_profile_commands': True}
    for declaration in [*value['agents'].values(), *value['agent_presets'].values()]:
        declaration.pop('executable')
        declaration.pop('cli_version')
        declaration['environment'].pop('PROBE_VERSION', None)
        declaration['environment']['PATH'] = str(binaries)
        declaration['environment']['PROBE_CALLS'] = str(tmp_path / 'calls.jsonl')
    return load_local_config(write(folder, value)), value


@pytest.mark.parametrize('fmt', ['local-config-7', 'local-config-8'])
def test_loading_is_data_only_and_unresolved_versions_cannot_be_queued(setup, repository, fmt):
    _, data, folder, tmp_path = setup
    config, _ = automatic(data, folder, tmp_path, fmt=fmt)
    project = config.projects[0]
    assert project.versions['reviewer_cli'] is None and project.versions['executor_cli'] is None
    assert not (tmp_path / 'calls.jsonl').exists()
    with pytest.raises(CompatibilityError, match='discovery must finish'):
        repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='unresolved')
    assert repository.claim() is None


@pytest.mark.parametrize('reviewer,executor', PAIRS)
@pytest.mark.parametrize('ui,work', [('en', 'en'), ('en', 'es'), ('es', 'en'), ('es', 'es')])
@pytest.mark.parametrize('fmt', ['local-config-7', 'local-config-8'])
def test_automatic_clients_all_pairings_and_languages(setup, repository, reviewer, executor, ui, work, fmt):
    _, data, folder, tmp_path = setup
    config, _ = automatic(data, folder, tmp_path, reviewer=reviewer, executor=executor, work=work, fmt=fmt)
    from my_harness.storage.preferences import PreferencesRepository
    from my_harness.storage.work_language import associate
    preferences = PreferencesRepository(repository)
    preferences.update(expected_version=preferences.read()['version'], ui_language=ui, default_work_language=work, key='languages')
    with repository._write() as session:
        associate(session, root=str(config.projects[0].context.root), project_id='operator', work_language=work,
                  source='migration', confirmation={'synthetic': True}, now=repository._now())
    with i18n.emission(ui):
        config = config.registrar.resolve_config(config)
        project = config.projects[0]
        assert project.versions['reviewer_cli'] == MINIMUM[reviewer]
        assert project.versions['executor_cli'] == MINIMUM[executor]
        job, run = journey(repository, config, 'automatic')
    assert run.status == 'ACCEPTANCE_READY', run.history.stop
    specs = [row['spec'] for row in repository.processes(job.id)]
    assert len(specs) == 3
    for spec in specs:
        observed = spec['preflight_observed']
        assert observed['compatibility']['policy'] == 'cli-capabilities-1'
        assert observed['compatibility']['internal_effects_verified'] is False
        assert observed['launch_sha256'] == project.versions[f"{spec['agent']}_cli_launch_sha256"]
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert {row['provider'] for row in calls} == {reviewer, executor}
    # Discovery plus bind plus three attempts must not reuse a single job's old help result.
    assert sum(row['args'] == ['--version'] for row in calls) >= 7


def test_unused_presets_and_unselected_provider_are_not_probed(setup):
    _, data, folder, tmp_path = setup
    config, _ = automatic(data, folder, tmp_path, reviewer='codex', executor='codex')
    (tmp_path / 'bin/claude').unlink()
    config.registrar.resolve_config(config)
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert {row['provider'] for row in calls} == {'codex'}


@pytest.mark.parametrize('provider,version', [('codex', '0.162.1'), ('claude', '2.1.303')])
@pytest.mark.parametrize('language', ['en', 'es'])
def test_minimum_diagnostic_is_localized_and_does_not_launch_model(tmp_path, provider, version, language):
    fake_client(tmp_path, provider, version)
    config = CLIConfig(provider, (), None, (('PATH', str(tmp_path)),), 2)
    with i18n.emission(language):
        report = preflight_config(config, access='write')
    assert not report['available'] and report['diagnostics'][0]['code'] == 'minimum_version'
    text = report['diagnostics'][0]['correction']
    assert version in text and MINIMUM[provider] in text
    assert ('Actualiza' if language == 'es' else 'Update') in text
    assert set(report['probes']) == {'version'}


@pytest.mark.parametrize('path', ['', '.', '/usr/bin:', 'relative/bin'])
def test_discovery_never_searches_cwd_or_inherits_path(tmp_path, monkeypatch, path):
    fake_client(tmp_path, 'codex')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PATH', str(tmp_path))
    config = CLIConfig('codex', (), None, (('PATH', path),), 2)
    report = preflight_config(config)
    assert report['diagnostics'][0]['code'] == 'discovery_path'


def test_missing_client_and_optional_explicit_path_are_sanitized(tmp_path):
    config = CLIConfig('codex', (), None, (('PATH', str(tmp_path)),), 2)
    report = preflight_config(config)
    assert report['diagnostics'][0]['code'] == 'client_missing'
    assert str(tmp_path) not in json.dumps(report)
    binary = fake_client(tmp_path, 'codex')
    explicit = replace(config, executable=(str(binary),), environment=())
    assert preflight_config(explicit)['available']


def test_module_entrypoint_is_not_imported_to_guess_its_identity(tmp_path):
    marker = tmp_path / 'must-not-run'
    config = CLIConfig('codex', (sys.executable, '-m', 'untrusted_module', str(marker)), None, (), 2)
    report = preflight_config(config)
    assert report['diagnostics'][0]['code'] == 'identity_unknown'
    assert report['probes'] == {} and not marker.exists()


@pytest.mark.parametrize('restart', [False, True])
def test_updated_client_is_detected_for_new_work_but_old_job_is_quarantined(setup, repository, restart):
    _, data, folder, tmp_path = setup
    config, _ = automatic(data, folder, tmp_path)
    config = config.registrar.resolve_config(config)
    original = config.projects[0]
    job = repository.submit(original.context, TASK, PHASE, PLAN, dict(original.versions), key='old-client')
    before = repository.get_run(job.run_id)
    fake_client(tmp_path / 'bin', 'codex', '0.164.0')
    if restart:
        config = load_local_config(config.registrar.source)
        config = config.registrar.resolve_config(config)
        current = config.projects[0]
    else:
        current = config.registrar.refresh(original)
    assert current.versions['reviewer_cli'] == '0.164.0'
    assert current.versions['reviewer_cli_launch_sha256'] != original.versions['reviewer_cli_launch_sha256']
    with pytest.raises(JournalError, match='differs from the frozen'):
        LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory).run_once()
    after = repository.get_run(job.run_id)
    assert after.status == 'RECOVERY_REQUIRED' and after.versions_json == before.versions_json
    assert after.history == before.history and not launches(tmp_path)


def test_same_version_changed_script_between_bind_and_invoke_is_refused(setup, repository):
    _, data, _, tmp_path = setup
    executable = fake_client(tmp_path / 'bin', 'codex')
    env = tuple({**data['providers']['codex']['environment'], 'PATH': str(tmp_path / 'bin')}.items())
    cfg = CLIConfig('codex', (str(executable),), MINIMUM['codex'], env, 3)
    port = CLIProcessAdapter({'reviewer': cfg, 'executor': cfg}, tmp_path / 'captures')
    job, claim, request = setup_invocation(repository, setup[0], port, 'reviewer')
    executable.write_text(executable.read_text() + '\n# changed build, same version\n')
    with pytest.raises(JournalError, match='launch files changed'):
        port.invoke(setup[0], request)
    process = repository.processes(job.id)[0]
    assert process['identity'] is None and process['spec']['launch_permitted'] is False
    assert process['spec']['preflight_observed']['diagnostics'][0]['code'] == 'identity_changed'
    assert not launches(tmp_path)
    repository.close_owner(claim)


def test_symlink_replacement_changes_local_identity_even_for_equal_version(tmp_path):
    one = fake_client(tmp_path / 'one', 'codex')
    two = fake_client(tmp_path / 'two', 'codex')
    link = tmp_path / 'codex'
    link.symlink_to(one)
    config = CLIConfig('codex', (str(link),), None, (), 3)
    original = launch_identity(config)[1]
    link.unlink()
    link.symlink_to(two)
    assert launch_identity(config)[1] != original


@pytest.mark.parametrize('version', ['0.163.0-beta', '00.163.0', '9999999.0.0', '0.163.0 extra'])
def test_auto_version_parser_refuses_ambiguous_or_unstable_output(tmp_path, version):
    fake_client(tmp_path, 'codex', version)
    report = preflight_config(CLIConfig('codex', (), None, (('PATH', str(tmp_path)),), 2))
    assert not report['available'] and report['observed_version'] is None
    assert report['diagnostics'][0]['code'] == 'unexpected_output'


@pytest.mark.parametrize('change', ['replace', 'delete'])
def test_pre_go_replacement_stops_the_gated_group_without_invoking_client(setup, repository, monkeypatch, change):
    _, data, _, tmp_path = setup
    executable = fake_client(tmp_path / 'bin', 'codex')
    env = tuple(data['providers']['codex']['environment'].items())
    cfg = CLIConfig('codex', (str(executable),), MINIMUM['codex'], env, 3)
    port = CLIProcessAdapter({'reviewer': cfg, 'executor': cfg}, tmp_path / 'captures')
    job, claim, request = setup_invocation(repository, setup[0], port, 'reviewer')
    original = port.journal.process_update

    def update(attempt_id, kind, payload):
        original(attempt_id, kind, payload)
        if kind == 'process_spawned':
            if change == 'replace':
                executable.write_text(executable.read_text() + '\n# replacement before GO\n')
            else:
                executable.unlink()

    monkeypatch.setattr(port.journal, 'process_update', update)
    with pytest.raises(JournalError, match='launch files changed'):
        port.invoke(setup[0], request)
    process = repository.processes(job.id)[0]
    assert process['identity'] is not None and process['status'] == 'STOPPED'
    assert process['capture']['group_state'] == 'dead'
    assert process['capture']['diagnostic_code'] == 'identity_changed'
    assert not launches(tmp_path)
    repository.close_owner(claim)


def test_api_startup_resolves_and_client_update_keeps_read_only_views_usable(setup, migrated_database):
    _, data, folder, tmp_path = setup
    config, _ = automatic(data, folder, tmp_path)
    with client(migrated_database[0], tmp_path, config) as http:
        shown = http.get('/api/managed/projects/operator').json()
        assert shown['versions']['reviewer_cli'] == MINIMUM['codex']
        fake_client(tmp_path / 'bin', 'codex', '0.164.0')
        queued = http.post('/api/managed/projects/operator/runs', json={
            'task_id': TASK, 'phase_id': PHASE, 'text': PLAN}, headers={'Idempotency-Key': 'auto-http'})
        assert queued.status_code == 202, queued.text
        run = http.get(f"/api/managed/runs/{queued.json()['run_id']}").json()
        assert run['versions']['reviewer_cli'] == '0.164.0'
        (tmp_path / 'bin/codex').unlink()
        before = (tmp_path / 'calls.jsonl').read_bytes()
        assert http.get('/api/managed/projects/operator').status_code == 200
        http.get('/api/managed/projects/operator/documents')
        assert (tmp_path / 'calls.jsonl').read_bytes() == before
        refused = http.post('/api/managed/projects/operator/runs', json={
            'task_id': TASK, 'phase_id': PHASE, 'text': PLAN}, headers={'Idempotency-Key': 'missing-http'})
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'client_missing'
