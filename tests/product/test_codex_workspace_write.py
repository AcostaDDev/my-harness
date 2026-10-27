"""D059 (`cli-7`): bounded explicit Codex writer roots; no installed agents.

The probe checks the transport contract only. It cannot certify what Codex's
model sees or whether it will edit; D057 had no attempted write to reproduce.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from my_harness.adapters.cli_agents import CLIConfig, argv_for
from my_harness.core.engine.journal import JournalError
from my_harness.services.local_config import load_local_config
from my_harness.services.managed import LocalSupervisor
from test_agent_roles import journey, request, v2
from test_local_config import PROBE, launches, setup, write  # noqa: F401 (fixture)
from test_managed import context  # noqa: F401 (fixture)
from test_typescript_profile import PHASE, PLAN, TASK, repository, web  # noqa: F401 (fixtures)


def overrides(args):
    return tomllib.loads('\n'.join(args[i + 1] for i, value in enumerate(args) if value == '-c'))


@pytest.mark.parametrize('name', ['checkout', 'checkout "quoted" \\ path', 'checkout café 🚀\nline'])
def test_writer_root_is_canonical_and_toml_escaped(context, tmp_path, name):
    root = tmp_path / name
    root.mkdir()
    ctx = replace(context, root=root)
    config = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    args = argv_for(config, ctx, request('executor'))
    workspace = overrides(args)['sandbox_workspace_write']
    assert workspace == {'network_access': False, 'writable_roots': [str(root.resolve())],
                         'exclude_slash_tmp': True}
    assert args[args.index('--cd') + 1] == str(ctx.root)
    assert 'approval_policy="never"' in args and 'web_search="disabled"' in args
    assert overrides(args)['projects'] == {str(ctx.root): {'trust_level': 'untrusted'}}
    assert all(not args[i + 1].startswith('projects.') for i, arg in enumerate(args) if arg == '-c')
    assert 'exclude_tmpdir_env_var' not in workspace  # CLI default for the explicit environment.
    for role in ('planner', 'reviewer', 'phase', 'chat', 'bootstrap'):
        reader = argv_for(config, ctx, request(role))
        assert reader[reader.index('--sandbox') + 1] == 'read-only'
        assert 'sandbox_workspace_write' not in overrides(reader)
        assert 'projects' not in overrides(reader)


@pytest.mark.parametrize('bad', ['cli-6', 'parent-root', 'extra-root', 'slash-tmp'])
def test_synthetic_writer_rejects_previous_or_broader_roots_before_editing(tmp_path, bad):
    workspace = {'network_access': False, 'writable_roots': [str(tmp_path.resolve())], 'exclude_slash_tmp': True}
    if bad == 'cli-6':
        workspace = {'network_access': False}
    elif bad == 'parent-root':
        workspace['writable_roots'] = [str(tmp_path.parent.resolve())]
    elif bad == 'extra-root':
        workspace['writable_roots'].append('/another-checkout')
    else:
        workspace['exclude_slash_tmp'] = False
    # The Git check comes first (D124); skip it to reach the writable-root contract.
    args = [sys.executable, PROBE, 'codex', 'web', '--skip-git-repo-check', '--sandbox', 'workspace-write']
    for key, value in workspace.items():
        args += ['-c', f'sandbox_workspace_write.{key}={json.dumps(value)}']
    result = subprocess.run(args, cwd=tmp_path, env={}, input='', capture_output=True, encoding='utf-8')
    assert result.returncode == 1 and 'explicit checkout root' in result.stderr and not result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('reviewer', ['codex', 'claude'])
def test_codex_writer_journey_freezes_requested_access_without_changing_contract(setup, repository, reviewer):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, reviewer, 'codex')))
    job, record = journey(repository, config, reviewer + '-writer')
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    assert [a.request.role for a in record.history.attempts] == ['planner', 'executor', 'reviewer']
    launch = json.loads(launches(tmp_path)[1])
    assert overrides(launch['argv'])['sandbox_workspace_write']['writable_roots'] == [str(context.root)]
    attempt = record.history.attempts[1]
    assert json.loads(attempt.request.task_json)['allowed_paths'] == ['src/estimate.ts']
    assert 'Requested executor filesystem access:' not in attempt.request.prompt
    assert 'Requested executor filesystem access:' in launch['prompt']
    assert json.dumps(str(context.root), ensure_ascii=False) in launch['prompt']
    assert 'actual tool denials must still be respected' in launch['prompt']
    assert all('Requested executor filesystem access:' not in json.loads(line)['prompt']
               for line in launches(tmp_path)[0::2])
    spec = repository.processes(job.id)[1]['spec']
    prompt = Path(spec['prompt_path']).read_bytes()
    assert spec['adapter_version'] == 'cli-14' and prompt.decode() == launch['prompt']
    assert spec['prompt_sha256'] == hashlib.sha256(prompt).hexdigest()
    assert 'tasks * 30' in context.path('src/estimate.ts').read_text()


def test_cli6_job_is_quarantined_without_preflight_process_or_history_rewrite(setup, repository):
    context, data, folder, tmp_path = setup
    config = load_local_config(write(folder, v2(data, 'codex', 'codex')))
    project = config.projects[0]
    versions = {**project.versions, 'agent_adapter': 'cli-6'}
    job = repository.submit(project.context, TASK, PHASE, PLAN, versions, key='cli-6')
    before = repository.get_run(job.run_id)
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    after = repository.get_run(job.run_id)
    assert after.status == 'RECOVERY_REQUIRED' and after.versions_json == before.versions_json
    assert after.history == before.history and not launches(tmp_path) and repository.processes(job.id) == []
