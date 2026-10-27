"""P009-T014 (D124): a Codex reviewer defines a new project whose folder is not yet a Git repository.

The pinned Codex exec refuses a working directory outside Git unless told to skip that check (D123).
The synthetic CLI reproduces the refusal; no installed CLI, provider or network is used.
"""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from my_harness.adapters import cli_agents
from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter, argv_for
from my_harness.adapters.engine_fake import ScriptedCommandRunner
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot, freeze
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.prompts import digest, output_schema
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.planning import PlanningRepository
from test_definition import BRIEF, answer
from test_managed_api import IDENTITY, VERSIONS, make_context
from test_local_config import PROBE

REFUSAL = 'Not inside a trusted directory and --skip-git-repo-check was not specified.'
READ_ROLES = ('planner', 'reviewer', 'phase', 'chat', 'bootstrap', 'planning')


def snapshot(template, role='definition'):
    schema = output_schema(role)
    return freeze({'parts': [{'version': {'name': template}, 'variables': {}}], 'output_schema': schema,
                   'schema_sha256': digest(freeze(schema))})


def request(context, role='definition', template='define-project'):
    return AgentRequest('00000000-0000-4000-8000-000000000014', role, Selection('m', 'medium', 'r'), 'p', None,
                        context_snapshot(context), prompt_snapshot_json=None if template is None else snapshot(template, role))


def codex(version='0.163.0', executable=('/synthetic/codex',), environment=()):
    return CLIConfig('codex', executable, version, environment, 20)


@pytest.fixture
def child(tmp_path):
    root = tmp_path / 'new-child'
    root.mkdir()
    if any((folder / '.git').exists() for folder in root.parents):
        pytest.skip('The temporary directory is inside a Git repository')
    return replace(make_context(root), documents='v2')


@pytest.mark.parametrize('version', ['0.163.0', '0.164.0', '1.0.0'])
def test_codex_definition_of_a_new_folder_only_adds_the_git_check_skip(child, version):
    argv = argv_for(codex(version), child, request(child))
    assert argv.count('--skip-git-repo-check') == 1
    assert argv[argv.index('--sandbox') + 1] == 'read-only'
    assert not any(value.startswith('projects=') for value in argv)
    for setting in ('features.memories=false', 'memories.use_memories=false', 'history.persistence="none"',
                    'project_doc_max_bytes=0'):
        assert setting in argv
    # Without the frozen define-project template the invocation is exactly the cli-12 one.
    without = argv_for(codex(version), child, request(child, template=None))
    assert tuple(value for value in argv if value != '--skip-git-repo-check') == without


def test_import_definition_and_other_roles_on_live_checkouts_keep_the_check(child):
    assert '--skip-git-repo-check' not in argv_for(codex(), child, request(child, template='import-project'))
    for role in READ_ROLES:
        assert '--skip-git-repo-check' not in argv_for(codex(), child, request(child, role))
    writer = argv_for(codex(), child, request(child, 'executor'))
    assert '--skip-git-repo-check' not in writer and writer[writer.index('--sandbox') + 1] == 'workspace-write'
    claude = CLIConfig('claude', ('/synthetic/claude',), '2.1.304', (), 20)
    assert '--skip-git-repo-check' not in argv_for(claude, child, request(child))


def test_exported_chat_and_onboarding_keep_their_skip(child, tmp_path):
    export = tmp_path / 'export'
    export.mkdir()
    for role, template in (('chat', None), ('definition', 'onboard-project')):
        assert '--skip-git-repo-check' in argv_for(codex(), replace(child, root=export),
                                                   request(child, role, template))


def run_probe(context, req):
    argv = argv_for(codex(executable=(sys.executable, PROBE, 'codex', 'plain')), context, req)
    return subprocess.run(argv, cwd=context.root, input='prompt', capture_output=True, text=True, timeout=30,
                          errors='replace', env={'PATH': '/usr/bin:/bin'})


def test_synthetic_codex_refuses_outside_git_like_the_pinned_cli(child, tmp_path):
    refused = run_probe(child, request(child, template='import-project'))
    assert refused.returncode == 1 and refused.stderr.strip() == REFUSAL and refused.stdout == ''
    assert run_probe(child, request(child)).returncode == 0
    # Inside any repository (here, a subfolder of one) the pinned CLI starts without the skip.
    repository = tmp_path / 'repository'
    nested = repository / 'nested'
    nested.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(repository)], check=True)
    inside = replace(child, root=nested)
    assert run_probe(inside, request(inside, template='import-project')).returncode == 0


def test_failed_turn_leaves_the_conversation_open_for_a_turn_that_starts(child, tmp_path, migrated_database,
                                                                         monkeypatch):
    script, record, artifacts = tmp_path / 'responses.json', tmp_path / 'launches.jsonl', tmp_path / 'artifacts'
    script.write_text(json.dumps({'definition': answer()}))
    environment = (('PATH', '/usr/bin:/bin'), ('PROBE_VERSION', '0.163.0'), ('PROBE_SCRIPT', str(script)),
                   ('PROBE_RECORD', str(record)))
    config = codex(executable=(sys.executable, PROBE, 'codex', 'recipe'), environment=environment)
    agents = {'reviewer': config, 'executor': config}
    versions = {**VERSIONS, **CLIProcessAdapter(agents, artifacts).frozen_versions()}
    assert versions['agent_adapter'] == 'cli-14'
    writer = GitWorkspace(IDENTITY)

    def ports(context, frozen):
        assert frozen == versions
        return CLIProcessAdapter(agents, artifacts), ScriptedCommandRunner(), writer

    engine = make_engine(migrated_database[0])
    try:
        repository = SQLiteManagedRepository(engine)
        planning = PlanningRepository(repository)
        worker = LocalSupervisor(repository, ports, commit_factory=lambda c, v: writer)
        cid = planning.create(child, kind='definition', title='Piloto', brief=BRIEF, writer=writer)

        def turn(key):
            planning.submit_message(child, cid, planning.get(cid)['version'], key=key, versions=versions,
                                    text='Propón los documentos', writer=writer)
            assert worker.run_once().status == 'DONE'
            return planning.get(cid)['turns'][-1]

        # The cli-12 rule (exports only) reproduces T007: the synthetic Codex refuses the folder.
        monkeypatch.setattr(cli_agents, 'skips_git_check', lambda context, request:
                            json.loads(request.context_json)['root'] != str(context.root))
        assert turn('first')['status'] == 'FAILED'
        monkeypatch.undo()
        second = turn('second')
        assert second['status'] == 'ANSWERED', second
        detail = planning.get(cid)
        assert [t['status'] for t in detail['turns']] == ['FAILED', 'ANSWERED'] and detail['proposals']
        launches = [json.loads(line) for line in record.read_text().splitlines()]
        assert ['--skip-git-repo-check' in item['argv'] for item in launches] == [False, True]
        for item in launches:
            assert Path(item['cwd']).resolve() == child.root.resolve()
            assert item['argv'][item['argv'].index('--sandbox') + 1] == 'read-only'
        assert list(child.root.iterdir()) == []  # read-only turns: no drafts, no .git
    finally:
        engine.dispose()


def test_turn_frozen_with_cli_12_is_quarantined_before_any_launch(child, tmp_path, migrated_database):
    record, artifacts = tmp_path / 'launches.jsonl', tmp_path / 'artifacts'
    environment = (('PATH', '/usr/bin:/bin'), ('PROBE_VERSION', '0.163.0'), ('PROBE_RECORD', str(record)))
    config = codex(executable=(sys.executable, PROBE, 'codex', 'recipe'), environment=environment)
    agents = {'reviewer': config, 'executor': config}
    stale = {**VERSIONS, **CLIProcessAdapter(agents, artifacts).frozen_versions(), 'agent_adapter': 'cli-12'}
    writer = GitWorkspace(IDENTITY)
    engine = make_engine(migrated_database[0])
    try:
        repository = SQLiteManagedRepository(engine)
        planning = PlanningRepository(repository)
        worker = LocalSupervisor(repository, lambda c, v: (CLIProcessAdapter(agents, artifacts),
                                                           ScriptedCommandRunner(), writer),
                                 commit_factory=lambda c, v: writer)
        cid = planning.create(child, kind='definition', title='Piloto', brief=BRIEF, writer=writer)
        job = planning.submit_message(child, cid, planning.get(cid)['version'], key='stale', versions=stale,
                                      text='Propón los documentos', writer=writer)
        with pytest.raises(JournalError, match='differs from frozen job versions'):
            worker.run_once()
        assert repository.get_job(job.id).status == repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
        assert not record.exists() and planning.get(cid)['turns'][0]['status'] == 'QUEUED'
    finally:
        engine.dispose()
