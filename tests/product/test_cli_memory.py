"""D066: memory controls requested in transport; no real CLI/auth/OS guarantee."""
from dataclasses import replace
import json
from pathlib import Path
import tomllib

import pytest

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter, argv_for
from my_harness.core.engine.journal import JournalError
from my_harness.services.local_config import load_local_config
from my_harness.services.managed import LocalSupervisor
from test_agent_roles import request, v2
from test_cli_agents import adapter, setup_invocation
from test_local_config import launches, setup, write  # noqa: F401 (fixture)
from test_managed import context, repository  # noqa: F401 (fixtures)
from test_typescript_profile import PHASE, PLAN, TASK, web  # noqa: F401 (fixture)


@pytest.mark.parametrize('provider,version', [('codex', '0.164.0'), ('claude', '2.1.305')])
@pytest.mark.parametrize('role', ['planner', 'executor', 'reviewer', 'phase', 'chat', 'bootstrap'])
def test_all_roles_request_no_automatic_memory_without_redirecting_auth(context, provider, version, role):
    environment = (('HOME', '/synthetic/original-home'), ('USER', 'synthetic-user'),
                   ('TMPDIR', '/synthetic/temporary'))
    config = CLIConfig(provider, ('/synthetic/cli',), version, environment, 1)
    original = request(role)
    args = argv_for(config, context, original)
    assert config.environment == environment and config.executable == ('/synthetic/cli',)
    assert '--resume' not in args and '--continue' not in args
    assert 'CODEX_HOME' not in dict(environment) and 'CLAUDE_CONFIG_DIR' not in dict(environment)
    if provider == 'codex':
        overrides = tomllib.loads('\n'.join(args[i + 1] for i, value in enumerate(args) if value == '-c'))
        assert overrides['features']['memories'] is False
        assert overrides['memories'] == {'generate_memories': False, 'use_memories': False}
        assert overrides['history']['persistence'] == 'none' and '--ephemeral' in args
        assert not {'cli_auth_credentials_store', 'sqlite_home', 'log_dir'} & overrides.keys()
        assert overrides.get('projects') == ({str(context.root): {'trust_level': 'untrusted'}}
                                              if role == 'executor' else None)
    else:
        assert json.loads(args[args.index('--settings') + 1]) == {
            'disableAllHooks': True, 'autoMemoryEnabled': False}
        assert '--no-session-persistence' in args
    assert original == request(role)  # Frozen request/prompt/context are not rewritten.


@pytest.mark.parametrize('value', ['0', '', 'false', 'true', 'unexpected'])
def test_conflicting_claude_memory_environment_is_refused_before_effects(tmp_path, value):
    with pytest.raises(ValueError, match='automatic memory must remain disabled'):
        CLIConfig('claude', ('/synthetic/cli',), '2.1.305',
                  (('CLAUDE_CODE_DISABLE_AUTO_MEMORY', value),), 1)
    assert list(tmp_path.iterdir()) == []
    assert CLIConfig('claude', ('/synthetic/cli',), '2.1.305',
                     (('CLAUDE_CODE_DISABLE_AUTO_MEMORY', '1'),), 1)


@pytest.mark.parametrize('provider,role', [('codex', 'planner'), ('claude', 'executor')])
def test_missing_memory_control_fails_once_with_original_capture(
        context, repository, tmp_path, monkeypatch, provider, role):
    from my_harness.adapters import cli_agents
    base = adapter(tmp_path)
    port = CLIProcessAdapter({agent: replace(config, environment=config.environment +
        (('PROBE_MEMORY_REQUIRED', '1'),)) for agent, config in base.agents.items()}, base.artifact_root)
    job, claim, attempt = setup_invocation(repository, context, port, role)
    original = cli_agents.argv_for

    def broken(config, ctx, request):
        args = list(original(config, ctx, request))
        if provider == 'codex':
            pos = args.index('memories.use_memories=false')
            args[pos - 1:pos + 1] = []
        else:
            pos = args.index('--settings') + 1
            args[pos] = '{"disableAllHooks":true}'
        return tuple(args)

    monkeypatch.setattr(cli_agents, 'argv_for', broken)
    with pytest.raises(JournalError, match='required permissions'):
        port.invoke(context, attempt)
    assert not (tmp_path / 'launches.jsonl').exists()
    process = repository.processes(job.id)[0]
    assert process['identity'] is None and process['status'] == 'STOPPED'
    assert process['spec']['launch_permitted'] is False
    assert process['spec']['diagnostic_code'] == 'guard_contract'
    repository.close_owner(claim)


@pytest.mark.parametrize('old_version', ['cli-7', 'cli-8'])
def test_old_job_is_quarantined_without_launch_or_history_change(setup, repository, old_version):
    _, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data)))
    project = config.projects[0]
    versions = {**project.versions, 'agent_adapter': old_version}
    job = repository.submit(project.context, TASK, PHASE, PLAN, versions, key=old_version+'-memory')
    before = repository.get_run(job.run_id)
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    after = repository.get_run(job.run_id)
    assert after.status == 'RECOVERY_REQUIRED' and after.versions_json == before.versions_json
    assert after.history == before.history and not launches(tmp_path) and repository.processes(job.id) == []


def test_missing_trust_override_refuses_synthetic_writer_before_edit(context, repository, tmp_path, monkeypatch):
    from my_harness.adapters import cli_agents
    base = adapter(tmp_path)
    codex_writer = replace(base.agents['reviewer'], cli_version='0.164.0',
                           environment=base.agents['reviewer'].environment + (('PROBE_VERSION', '0.164.0'),))
    agents = {**base.agents, 'executor': codex_writer}
    port = CLIProcessAdapter({agent: replace(config, environment=config.environment +
        (('PROBE_TRUST_REQUIRED', '1'),)) for agent, config in agents.items()}, base.artifact_root)
    job, claim, attempt = setup_invocation(repository, context, port, 'executor')
    original = cli_agents.argv_for

    def broken(config, ctx, request):
        args = list(original(config, ctx, request))
        pos = next(i for i, arg in enumerate(args) if arg.startswith('projects='))
        args[pos - 1:pos + 1] = []
        return tuple(args)

    monkeypatch.setattr(cli_agents, 'argv_for', broken)
    with pytest.raises(JournalError, match='required permissions'):
        port.invoke(context, attempt)
    assert not (tmp_path / 'launches.jsonl').exists()
    process = repository.processes(job.id)[0]
    assert process['identity'] is None and process['status'] == 'STOPPED'
    assert process['spec']['diagnostic_code'] == 'guard_contract'
    repository.close_owner(claim)
