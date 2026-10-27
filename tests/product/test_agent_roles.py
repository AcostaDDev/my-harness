"""D052 (`cli-5`, `cli-6` since D058; `local-config-2`): reviewer and executor, each Codex or Claude.

Synthetic CLIs through the real adapter, local configuration, supervisor, real
Node/npm/Git and temporary SQLite. No provider, authentication or network.
"""
import copy
from dataclasses import replace
import json

import pytest

from my_harness.adapters.cli_agents import EFFORTS, CLIConfig, CLIProcessAdapter, argv_for
from my_harness.core.engine.context import EnginePolicy
from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.serialization import restore_context
from my_harness.services.local_config import LocalConfigError, build, inspect_local_config, load_local_config
from my_harness.services.managed import LocalSupervisor
from test_local_config import PROBE, SENTINEL, launches, setup, write  # noqa: F401 (fixture)
from test_typescript_profile import PHASE, PLAN, TASK, repository, web  # noqa: F401 (fixtures)

VERSIONS = {'codex': '0.163.0', 'claude': '2.1.304'}
PAIRS = [('codex', 'claude'), ('claude', 'claude'), ('codex', 'codex'), ('claude', 'codex')]
# Each provider as reviewer and as executor: enough to wire versions or presets already covered by PAIRS.
MIXED_PAIRS = [('codex', 'claude'), ('claude', 'codex')]


def agent(base, provider, *, reviewer, **environment):
    value = {'provider': provider, 'executable': [base['executable'][0], PROBE, provider, 'web'],
             'cli_version': VERSIONS[provider], 'timeout_seconds': 20,
             'environment': {**base['environment'], 'PROBE_VERSION': VERSIONS[provider], **environment}}
    if reviewer:
        value.update(model='synthetic-reviewer', effort='high')
    elif provider == 'claude':
        value.update(tools=['Read', 'Edit'], allowed_tools=['Read', 'Edit'])
    return value


def v2(data, reviewer='codex', executor='claude', *, mode='catalog', planning='agent', selection=None):
    """`local-config-1` fixture data rewritten as `local-config-2`."""
    data = copy.deepcopy(data)
    base = data.pop('providers')['codex']
    environment = {'PROBE_ALLOWED': 'src/estimate.ts', 'PROBE_VALIDATION': '[]', 'PROBE_MEMORY_REQUIRED': '1',
                   'PROBE_TRUST_REQUIRED': '1',
                   'PROBE_SELECTION': json.dumps(selection or {'model': 'synthetic-executor', 'effort': 'medium'})}
    data['format'] = 'local-config-2'
    data['agents'] = {'reviewer': agent(base, reviewer, reviewer=True, **environment),
                      'executor': agent(base, executor, reviewer=False, **environment)}
    data['projects'][0]['policy'] = {'planning_mode': planning, 'executor_mode': mode,
                                     'executor_models': ['synthetic-executor'], 'executor_efforts': ['medium'],
                                     'max_revision_cycles': 1}
    return data


def journey(repository, config, key):
    project = config.projects[0]
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key=key)
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert supervisor.run_once().status == 'DONE'
    return job, repository.get_run(job.run_id)


@pytest.mark.parametrize('reviewer,executor', PAIRS)
def test_matrix_of_four_provider_pairings_through_the_real_adapter(setup, repository, reviewer, executor):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, reviewer, executor)))
    project = config.projects[0]
    versions = project.versions
    assert versions['agent_adapter'] == 'cli-14' and versions['local_config'] == 'local-config-2'
    assert (versions['reviewer_provider'], versions['executor_provider']) == (reviewer, executor)
    # The reviewer always plans, with its own user-fixed selection.
    policy = project.context.policy
    assert (policy.planner_model, policy.planner_effort) == (policy.reviewer_model, policy.reviewer_effort)
    assert policy.executor_effort_vocabulary == EFFORTS[executor]
    job, record = journey(repository, config, f'{reviewer}-{executor}')
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    assert [a.request.role for a in record.history.attempts] == ['planner', 'executor', 'reviewer']
    assert 'tasks * 30' in context.path('src/estimate.ts').read_text()
    specs = [row['spec'] for row in repository.processes(job.id)]
    assert [(s['agent'], s['provider']) for s in specs] == [
        ('reviewer', reviewer), ('executor', executor), ('reviewer', reviewer)]
    records = [json.loads(line) for line in launches(tmp_path)]
    assert [r['provider'] for r in records] == [reviewer, executor, reviewer]
    for item in records:
        args, writer = item['argv'], item is records[1]
        if item['provider'] == 'codex':
            assert args[args.index('--sandbox') + 1] == ('workspace-write' if writer else 'read-only')
            assert ('sandbox_workspace_write.network_access=false' in args) is writer
        else:
            assert ('--json-schema' in args) is not writer and ('--restricted' in args) is not writer
            assert args[args.index('--tools') + 1] == ('Read,Edit' if writer else 'Read,Glob,Grep')
        assert args[args.index('--model') + 1] == ('synthetic-executor' if writer else 'synthetic-reviewer')
    assert all(SENTINEL not in json.dumps(s) for s in specs)


@pytest.mark.parametrize('mode,selection,accepted', [
    ('open', {'model': 'free-model-9', 'effort': 'xhigh'}, True),
    ('catalog', {'model': 'free-model-9', 'effort': 'xhigh'}, False),
    ('open', {'model': 'free-model-9', 'effort': 'minimal'}, False),  # Codex-only effort, Claude executor
    ('open', {'model': '-flag', 'effort': 'high'}, False),
])
def test_reviewer_selection_validated_by_catalog_or_open_mode(setup, repository, mode, selection, accepted):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, 'claude', 'claude', mode=mode, selection=selection)))
    job, record = journey(repository, config, mode)
    if accepted:
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        execution = record.history.attempts[1].request
        assert (execution.selection.model, execution.selection.effort) == ('free-model-9', 'xhigh')
        args = json.loads(launches(tmp_path)[1])['argv']
        assert args[args.index('--model') + 1] == 'free-model-9' and args[args.index('--effort') + 1] == 'xhigh'
        prompt = json.loads(launches(tmp_path)[0])['prompt']
        assert 'Executor selection policy (open)' in prompt and '"provider":"claude"' in prompt
    else:
        assert record.status == 'STOPPED' and record.history.stop.stage == 'planner'
        assert 'outside explicit policy' in record.history.stop.reason
        assert [a.request.role for a in record.history.attempts] == ['planner'] and len(launches(tmp_path)) == 1


@pytest.mark.parametrize('mode,accepted', [('open', True), ('catalog', False)])
def test_deterministic_planning_takes_the_next_steps_selection_by_mode(setup, repository, mode, accepted):
    context, data, folder, tmp_path = setup
    changed = v2(data, 'codex', 'codex', mode=mode, planning='deterministic')
    # The NEXT_STEPS line (synthetic-executor / medium) is outside this catalog.
    changed['projects'][0]['policy'].update(executor_models=['reference-model'], executor_efforts=['low'])
    config = load_local_config(write(folder, changed))
    job, record = journey(repository, config, mode)
    if accepted:
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        assert [a.request.role for a in record.history.attempts] == ['executor', 'reviewer']
        assert record.history.attempts[0].request.selection.model == 'synthetic-executor'
    else:
        assert record.history.stop.stage == 'planner' and not record.history.attempts and not launches(tmp_path)


def test_changing_selection_mode_quarantines_pending_jobs(setup, repository):
    context, data, folder, tmp_path = setup
    admitted = load_local_config(write(folder, v2(data)))
    project = admitted.projects[0]
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='pending')
    current = load_local_config(write(folder, v2(data, mode='open')))
    assert current.projects[0].versions['local_config_sha256'] != project.versions['local_config_sha256']
    supervisor = LocalSupervisor(repository, current.ports_factory, commit_factory=current.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED' and not launches(tmp_path)


def test_local_config_1_still_reads_as_codex_reviewer_and_claude_executor(setup):
    context, data, folder, tmp_path = setup
    project = load_local_config(write(folder, data)).projects[0]
    assert (project.versions['reviewer_provider'], project.versions['executor_provider']) == ('codex', 'claude')
    assert project.versions['local_config'] == 'local-config-1'
    # Same policy as before: separate planner selection and no D052 keys in the snapshot.
    assert project.context.policy.planner_model == 'synthetic-planner'
    policy = json.loads(context_snapshot(project.context))['policy']
    assert 'executor_mode' not in policy and 'executor_effort_vocabulary' not in policy


def test_previous_and_new_policy_snapshots_round_trip(setup):
    context = setup[0]
    for policy in (context.policy, replace(context.policy, executor_mode='open',
                                           executor_effort_vocabulary=EFFORTS['claude'])):
        snapshot = context_snapshot(replace(context, policy=policy))
        assert context_snapshot(restore_context(snapshot)) == snapshot
    with pytest.raises(ValueError, match='vocabulary'):
        replace(context.policy, executor_mode='open')
    with pytest.raises(ValueError, match='vocabulary'):
        replace(context.policy, executor_effort_vocabulary=('low',))  # 'medium' outside it


def mutate(data, change):
    data = v2(data)
    reviewer, executor = data['agents']['reviewer'], data['agents']['executor']
    policy = data['projects'][0]['policy']
    if change == 'provider':
        executor['provider'] = 'gemini'
    elif change == 'reviewer-effort':
        reviewer['effort'] = 'ultra'  # Codex-only
        reviewer['provider'] = 'claude'
    elif change == 'reviewer-tools':
        reviewer['tools'] = ['Read']
    elif change == 'executor-model':
        executor['model'] = 'x'
    elif change == 'codex-tools':
        data['agents']['executor'] = {**agent({'executable': executor['executable'],
                                               'environment': executor['environment']}, 'codex', reviewer=False),
                                      'tools': ['Bash']}
    elif change == 'codex-writer-version':
        executor.update(provider='codex', cli_version='invalid')
        executor.pop('tools'), executor.pop('allowed_tools')
    elif change == 'planning-auto':
        policy['planning_mode'] = 'auto'
    elif change == 'mode':
        policy['executor_mode'] = 'free'
    elif change == 'no-mode':
        del policy['executor_mode']
    elif change == 'planner-key':
        policy['planner_model'] = 'x'
    elif change == 'efforts-vocabulary':
        policy['executor_efforts'] = ['minimal']
    elif change == 'providers-table':
        data['providers'] = {}
    elif change == 'v1-with-agents':
        data['format'] = 'local-config-1'
    return data


@pytest.mark.parametrize('change', ['provider', 'reviewer-effort', 'reviewer-tools', 'executor-model', 'codex-tools',
                                    'codex-writer-version', 'planning-auto', 'mode', 'no-mode', 'planner-key',
                                    'efforts-vocabulary', 'providers-table', 'v1-with-agents'])
def test_invalid_agent_configuration_rejected_without_effects(setup, change):
    context, data, folder, tmp_path = setup
    with pytest.raises(LocalConfigError):
        build(mutate(data, change), folder / 'my-harness.toml')
    assert not launches(tmp_path)


def test_check_config_shows_agents_and_preflights_each_access_mode(setup, capsys):
    from my_harness.cli import main
    context, data, folder, tmp_path = setup
    path = write(folder, v2(data, 'claude', 'codex', mode='open'))
    assert main(['check-config', str(path), '--preflight']) == 0
    result = json.loads(capsys.readouterr().out)
    agents = result['projects'][0]['agents']
    assert result['format'] == 'local-config-2'
    assert agents['reviewer'] == {'provider': 'claude', 'model': 'synthetic-reviewer', 'effort': 'high'}
    assert agents['executor']['provider'] == 'codex' and agents['executor']['selection_mode'] == 'open'
    assert set(result['preflight']) == {'reviewer', 'executor'}
    assert '--json-schema' in result['preflight']['reviewer']['required_flags']
    assert '--json-schema' not in result['preflight']['executor']['required_flags']
    assert SENTINEL not in json.dumps(result) and not launches(tmp_path)
    # A Claude CLI without the read-only flags cannot serve as reviewer.
    _, agents = inspect_local_config(path)
    reviewer = replace(agents['reviewer'], executable=agents['reviewer'].executable[:-1] + ('no_read_flags',))
    from my_harness.adapters.cli_diagnostics import preflight_config
    report = preflight_config(reviewer, access='read')
    assert report['available'] is False and report['missing_flags'] == ['--restricted', '--json-schema']
    assert preflight_config(reviewer, access='write')['available'] is True


def request(role, effort='medium', model='m'):
    return AgentRequest('00000000-0000-4000-8000-000000000005', role, Selection(model, effort, 'r'), 'p', None, '{}')


def test_argv_by_provider_and_access_without_launch(setup):
    context = setup[0]
    codex = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    claude = CLIConfig('claude', ('/synthetic/claude',), '2.1.305', (), 1, tools=('Read', 'Edit'),
                       allowed_tools=('Read', 'Edit'))
    writer = argv_for(codex, context, request('executor'))
    assert writer[writer.index('--sandbox') + 1] == 'workspace-write' and 'approval_policy="never"' in writer
    assert 'sandbox_workspace_write.network_access=false' in writer and 'web_search="disabled"' in writer
    with pytest.raises(ValueError, match='0.163.0'):
        argv_for(replace(codex, cli_version='0.162.1'), context, request('executor'))
    for role in ('planner', 'reviewer', 'phase', 'chat', 'bootstrap'):
        reader = argv_for(claude, context, request(role))
        assert reader[reader.index('--tools') + 1] == reader[reader.index('--allowedTools') + 1] == 'Read,Glob,Grep'
        assert '--restricted' in reader and json.loads(reader[reader.index('--json-schema') + 1])['type'] == 'object'
        reader = argv_for(codex, context, request(role))
        assert reader[reader.index('--sandbox') + 1] == 'read-only'
    with pytest.raises(ValueError, match='vocabulary'):
        argv_for(claude, context, request('executor', effort='minimal'))
    with pytest.raises(ValueError, match='vocabulary'):
        argv_for(codex, context, request('reviewer', effort='turbo'))
    with pytest.raises(ValueError, match='Unknown agent role'):
        argv_for(codex, context, request('observer'))
    with pytest.raises(ValueError, match='Claude-only'):
        replace(codex, tools=('Bash',))


def test_adapter_assignment_is_part_of_the_frozen_identity(tmp_path):
    codex = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    claude = CLIConfig('claude', ('/synthetic/claude',), '2.1.305', (), 1)
    pairs = {(r, e): CLIProcessAdapter({'reviewer': r, 'executor': e}, tmp_path).frozen_versions()
             for r in (codex, claude) for e in (codex, claude)}
    assert len({v['cli_config_sha256'] for v in pairs.values()}) == 4
    assert pairs[(claude, codex)]['reviewer_provider'] == 'claude' and pairs[(claude, codex)]['executor_cli'] == '0.164.0'
    # The two-provider sequence is the local-config-1 reading.
    assert CLIProcessAdapter((codex, claude), tmp_path).frozen_versions() == pairs[(codex, claude)]
    capabilities = CLIProcessAdapter({'reviewer': claude, 'executor': codex}, tmp_path).capabilities()['agents']
    assert capabilities == {'reviewer': {'provider': 'claude', 'access': 'read', 'grants': []},
                            'executor': {'provider': 'codex', 'access': 'write', 'grants': []}}
    with pytest.raises(ValueError, match='fixed tool inventory'):
        CLIProcessAdapter({'reviewer': replace(claude, tools=('Read',)), 'executor': codex}, tmp_path)
    historical = CLIProcessAdapter({'reviewer': claude, 'executor': replace(codex, cli_version='0.161.0')}, tmp_path)
    assert historical.frozen_versions()['executor_cli'] == '0.161.0'  # readable; admission/invocation enforce the floor
    with pytest.raises(ValueError):
        CLIProcessAdapter({'reviewer': claude}, tmp_path)


def test_open_policy_shape_without_cli():
    policy = EnginePolicy(('ref',), ('low',), 'r', 'high', 'r', 'high', executor_mode='open',
                          executor_effort_vocabulary=EFFORTS['codex'])
    assert policy.executor_mode == 'open'
    with pytest.raises(ValueError, match='catalog or open'):
        replace(policy, executor_mode='free')
