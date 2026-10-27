"""D058 (`cli-6`): the Claude reader receives the typed engine schema as --json-schema.

D057 observed a real Claude reader return lists and objects as JSON text under
the `cli-5` schema, which only declared `required`. Synthetic CLIs through the
real adapter, local configuration, supervisor, real Node/npm/Git and temporary
SQLite. No provider, authentication or network.
"""
import json
import os
import subprocess
import sys

import pytest

from my_harness.adapters import cli_agents
from my_harness.adapters.cli_agents import CLIConfig, argv_for, reader_schema
from my_harness.core.engine.contracts import AgentRequest, Selection, freeze
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.prompts import builtin_catalog, output_schema, render_attempt
from my_harness.services.local_config import load_local_config
from my_harness.services.managed import LocalSupervisor
from test_agent_roles import journey, v2
from test_local_config import PROBE, launches, setup, write  # noqa: F401 (fixture)
from test_typescript_profile import PHASE, PLAN, TASK, repository, web  # noqa: F401 (fixtures)

READERS = ('planner', 'reviewer', 'phase', 'chat', 'bootstrap')
CLI5_PLANNER = {'type': 'object', 'required': list(output_schema('planner')['required'])}


def schema_of(argv):
    return json.loads(argv[argv.index('--json-schema') + 1])


def request(role, snapshot=None):
    return AgentRequest('00000000-0000-4000-8000-000000000058', role, Selection('m', 'medium', 'r'), 'p', None,
                        '{}', prompt_snapshot_json=snapshot)


def test_reader_schema_is_the_typed_engine_schema_of_each_role(setup):
    context = setup[0]
    claude = CLIConfig('claude', ('/synthetic/claude',), '2.1.305', (), 1)
    codex = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    for role in READERS:
        schema = schema_of(argv_for(claude, context, request(role)))
        assert schema == output_schema(role) and schema['additionalProperties'] is True
        assert all('type' in schema['properties'][field] for field in schema['required'])
        assert '--json-schema' not in argv_for(codex, context, request(role))
    planner = output_schema('planner')['properties']
    assert planner['allowed_paths']['type'] == 'array'
    assert planner['allowed_paths']['items'] == {'type': 'string'}
    assert 'Complete allowlist' in planner['allowed_paths']['description']
    assert planner['executor_selection']['type'] == 'object'
    # The writer keeps the cli-5 argv: no schema, no restriction.
    writer = argv_for(CLIConfig('claude', ('/synthetic/claude',), '2.1.305', (), 1, tools=('Read', 'Edit'),
                                allowed_tools=('Read', 'Edit')), context, request('executor'))
    assert '--json-schema' not in writer and '--restricted' not in writer


def test_reader_schema_comes_from_the_frozen_prompt_snapshot(setup):
    context = setup[0]
    _, snapshot = render_attempt(builtin_catalog(), 'review-task', {'INPUT_JSON': '{}'}, context)
    assert reader_schema(request('reviewer', snapshot)) == json.loads(snapshot)['output_schema']
    # A frozen schema that differs from the current one is still the attempt's contract.
    frozen = json.loads(snapshot)
    frozen['output_schema'] = {**frozen['output_schema'], 'description': 'frozen earlier'}
    frozen['schema_sha256'] = cli_agents.digest(freeze(frozen['output_schema']))
    assert reader_schema(request('reviewer', freeze(frozen)))['description'] == 'frozen earlier'
    for broken in ({**frozen, 'schema_sha256': '0' * 64}, {k: v for k, v in frozen.items() if k != 'output_schema'}):
        with pytest.raises(ValueError, match='consistent output schema'):
            argv_for(CLIConfig('claude', ('/synthetic/claude',), '2.1.305', (), 1), context,
                     request('reviewer', freeze(broken)))


def test_claude_reader_journey_sends_the_attempt_schema_and_gets_typed_lists(setup, repository):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, 'claude', 'claude')))
    assert config.projects[0].versions['agent_adapter'] == 'cli-14'
    job, record = journey(repository, config, 'typed')
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    readers = [json.loads(line) for line in launches(tmp_path)][0::2]
    attempts = [a for a in record.history.attempts if a.request.role != 'executor']
    assert [a.request.role for a in attempts] == ['planner', 'reviewer'] and len(readers) == 2
    for launch, attempt in zip(readers, attempts):
        assert schema_of(launch['argv']) == json.loads(attempt.request.prompt_snapshot_json)['output_schema']
    planned = json.loads(attempts[0].result.payload_json)
    assert planned['allowed_paths'] == ['src/estimate.ts'] and isinstance(planned['executor_selection'], dict)


def test_untyped_cli5_schema_reproduces_d057_and_text_lists_stay_rejected(setup, repository, monkeypatch):
    context, data, folder, tmp_path = setup
    data = v2(data, 'claude', 'claude')
    data['agents']['reviewer']['environment']['PROBE_UNTYPED'] = 'text'
    config = load_local_config(write(folder, data))
    monkeypatch.setattr(cli_agents, 'reader_schema', lambda request: CLI5_PLANNER)
    job, record = journey(repository, config, 'd057')
    # D058: no normalization of JSON text into lists; the engine stops as in D057.
    assert record.history.stop.stage == 'planner' and record.history.stop.reason == 'Invalid task allowed_paths'
    [attempt] = record.history.attempts
    original = json.loads(attempt.result.payload_json)
    assert original['allowed_paths'] == '["src/estimate.ts"]' and original['validation_commands'] == '[]'
    assert isinstance(original['executor_selection'], str) and json.loads(original['executor_selection'])
    assert len(launches(tmp_path)) == 1 and 'tasks * 45' in context.path('src/estimate.ts').read_text()


def test_synthetic_claude_reader_requires_typed_properties(tmp_path):
    def run(schema, **environment):
        argv = [sys.executable, PROBE, 'claude', 'flow', '--tools', 'Read,Glob,Grep', '--mcp-config',
                '{"mcpServers":{}}', '--restricted', '--json-schema', freeze(schema)]
        return subprocess.run(argv, input='Plan exactly', capture_output=True, encoding='utf-8', errors='replace',
                              cwd=tmp_path, env={'PATH': os.environ['PATH'], **environment})
    refused = run(CLI5_PLANNER)
    assert refused.returncode == 1 and 'untyped --json-schema' in refused.stderr and not refused.stdout
    typed = [json.loads(line) for line in run(output_schema('planner')).stdout.splitlines()]
    assert typed[-1]['structured_output']['allowed_paths'] == ['app/**']
    text = [json.loads(line) for line in run(CLI5_PLANNER, PROBE_UNTYPED='text').stdout.splitlines()]
    assert text[-1]['structured_output']['allowed_paths'] == '["app/**"]'


def test_job_frozen_with_cli5_is_quarantined_before_any_launch(setup, repository):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, 'claude', 'codex')))
    project = config.projects[0]
    job = repository.submit(project.context, TASK, PHASE, PLAN, {**project.versions, 'agent_adapter': 'cli-5'},
                            key='cli-5')
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not launches(tmp_path) and not repository.get_run(job.run_id).history.attempts
