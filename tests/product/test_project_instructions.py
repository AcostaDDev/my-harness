"""P008-T007 (D088 point 8): the project's AGENTS.md in the frozen prompt of each role.

Temporary Git and SQLite, fake agents and synthetic data; no providers or real CLIs."""
from dataclasses import replace
import hashlib
import json
import tomllib

import pytest

from my_harness.adapters.cli_agents import VERSION, CLIConfig, argv_for
from my_harness.core.engine.contracts import ContractError
from my_harness.core.engine.documents import (
    DOCUMENT_LAYOUT, LEGACY_INSTRUCTIONS, MAX_INSTRUCTIONS_BYTES, project_instructions,
)
from my_harness.core.engine.prompts import (
    PROJECT_INSTRUCTIONS, VARIABLES, builtin_catalog, digest, dump_catalog, load_catalog, render_attempt,
)
from test_agent_roles import request
from test_managed import context, repository  # noqa: F401  (fixtures)
from test_managed_api import git
from test_documents import v2, v2checkout  # noqa: F401  (fixtures)
from test_phases import phase_review

ROLES = ('judge-permission', 'judge-planning-choice', 'judge-spec-gap', 'judge-blocked-check', 'plan-task', 'execute-task', 'review-task', 'revise-task', 'close-phase', 'chat-turn', 'plan-phase')


def values(name):
    return {variable: f'synthetic {variable}' for variable in VARIABLES[name] if variable != PROJECT_INSTRUCTIONS}


def provenance(data: bytes) -> dict:
    return {'path': 'AGENTS.md', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def without_instructions(catalog, name):
    """Synthetic version from before P008-T007: same template without the new variable."""
    old = catalog[name].template.replace('{{PROJECT_INSTRUCTIONS}}', '')
    return {**catalog, name: replace(catalog[name], template=old, sha256=digest(old), id='builtin-1:' + digest(old))}


def snapshots(world, role):
    return [json.loads(item.prompt_snapshot_json) for item in world.ports.agents.requests if item.role == role]


def test_every_project_role_renders_agents_md_with_its_hash(v2checkout):
    assert {name for name, variables in VARIABLES.items() if PROJECT_INSTRUCTIONS in variables} == set(ROLES)
    data = (v2checkout.root / 'AGENTS.md').read_bytes()
    for name in ROLES:
        text, frozen = render_attempt(builtin_catalog(), name, values(name), v2checkout)
        frozen = json.loads(frozen)
        assert text.count(data.decode()) == 1 and frozen['rendered'] == text
        assert frozen['project_instructions'] == provenance(data)
        assert frozen['parts'][0]['variables'][PROJECT_INSTRUCTIONS] == data.decode()
        assert '<project-instructions>\n' + data.decode() + '\n</project-instructions>' in text


def test_definition_drafts_agents_md_and_reads_none(v2checkout):
    (v2checkout.root / 'AGENTS.md').unlink()
    text, frozen = render_attempt(builtin_catalog(), 'define-project', values('define-project'), v2checkout)
    assert PROJECT_INSTRUCTIONS not in VARIABLES['define-project'] and 'project_instructions' not in json.loads(frozen)


@pytest.mark.parametrize('case', ['missing', 'symlink', 'directory', 'oversize', 'binary', 'blank', 'nul'])
def test_invalid_agents_md_refuses_the_attempt(v2checkout, tmp_path, case):
    path = v2checkout.root / 'AGENTS.md'
    path.unlink()
    if case == 'symlink':
        outside = tmp_path / 'outside.md'
        outside.write_text('# Ajeno\n', encoding='utf-8')
        path.symlink_to(outside)
    elif case == 'directory':
        path.mkdir()
    elif case == 'oversize':
        path.write_bytes(b'#' * (MAX_INSTRUCTIONS_BYTES + 1))
    elif case == 'binary':
        path.write_bytes(b'\xff\xfe')
    elif case == 'blank':
        path.write_text(' \n', encoding='utf-8')
    elif case == 'nul':
        path.write_text('# A\0B\n', encoding='utf-8')
    with pytest.raises(ContractError, match='AGENTS.md'):
        render_attempt(builtin_catalog(), 'execute-task', values('execute-task'), v2checkout)
    if case == 'oversize':
        path.write_bytes(b'#' * MAX_INSTRUCTIONS_BYTES)  # The exact limit is admitted whole, without truncation.
        assert project_instructions(v2checkout)[1]['bytes'] == MAX_INSTRUCTIONS_BYTES


def test_contexts_without_layout_render_an_explicit_absence(v2checkout):
    legacy = replace(v2checkout, documents=None)
    text, frozen = render_attempt(builtin_catalog(), 'review-task', values('review-task'), legacy)
    assert LEGACY_INSTRUCTIONS in text
    assert json.loads(frozen)['project_instructions'] == {'path': None, 'sha256': None, 'bytes': 0}


def test_the_engine_alone_supplies_the_instructions(v2checkout):
    with pytest.raises(ContractError, match='supplied by the engine'):
        render_attempt(builtin_catalog(), 'execute-task',
                       {**values('execute-task'), PROJECT_INSTRUCTIONS: 'otras instrucciones'}, v2checkout)


def test_earlier_template_versions_stay_readable_but_cannot_invoke_on_a_project(v2checkout):
    catalog = without_instructions(builtin_catalog(), 'execute-task')
    frozen = dump_catalog(catalog)  # Frozen catalogs and previously saved versions stay valid.
    assert dump_catalog(load_catalog(frozen)) == frozen
    with pytest.raises(ContractError, match='lacks'):
        render_attempt(catalog, 'execute-task', values('execute-task'), v2checkout)
    text, _ = render_attempt(catalog, 'execute-task', values('execute-task'), replace(v2checkout, documents=None))
    assert LEGACY_INSTRUCTIONS not in text


def test_task_attempts_freeze_agents_md_and_a_change_reaches_only_later_attempts(v2):
    v2.create_v2()
    first = (v2.context.root / 'AGENTS.md').read_bytes()
    run_id = v2.accept()
    attempts = v2.repository.get_run(run_id).history.attempts
    assert {item.request.role for item in attempts} == {'executor', 'reviewer'}
    for attempt in attempts:
        assert first.decode() in attempt.request.prompt
        assert json.loads(attempt.request.prompt_snapshot_json)['project_instructions'] == provenance(first)
    changed = first + '\n- Regla sintética añadida después del primer intento.\n'.encode()
    (v2.context.root / 'AGENTS.md').write_bytes(changed)
    git(v2.context.root, 'commit', '-qam', 'docs: instrucciones sintéticas')
    pid = v2.phases.by_code(str(v2.context.root), 'P001')
    v2.check(pid, phase_review())
    (phase,) = snapshots(v2, 'phase')
    assert phase['project_instructions'] == provenance(changed) and changed.decode() in phase['rendered']
    stored = v2.repository.get_run(run_id).history.attempts
    assert [item.request.prompt_snapshot_json for item in stored] == [
        item.request.prompt_snapshot_json for item in attempts]


def test_a_project_without_agents_md_stops_before_invoking(v2):
    (v2.context.root / 'AGENTS.md').unlink()
    git(v2.context.root, 'commit', '-qam', 'docs: retirar instrucciones')
    v2.create_v2()
    from test_documents import PLAN_P001
    from test_managed_api import VERSIONS
    job = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    record = v2.repository.get_run(job.run_id)
    assert record.history.stop.stage == 'prompts' and 'AGENTS.md is required' in record.history.stop.reason
    assert v2.ports.agents.requests == [] and record.history.attempts == ()


def test_frozen_versions_identify_the_injection():
    assert VERSION == 'cli-14' and DOCUMENT_LAYOUT == 'd088-12'


@pytest.mark.parametrize('version,role', [(version, role) for version in ('0.163.0', '0.164.0')
                                           for role in ('planner', 'reviewer', 'phase', 'chat', 'planning')]
                         + [('0.164.0', 'executor')])  # Synthetic candidate writer keeps the same instructions guard.
def test_codex_no_longer_loads_its_own_copy_of_the_project_docs(context, version, role):
    args = argv_for(CLIConfig('codex', ('/synthetic/cli',), version, (), 1), context, request(role))
    overrides = tomllib.loads('\n'.join(args[i + 1] for i, value in enumerate(args) if value == '-c'))
    assert overrides['project_doc_max_bytes'] == 0 and '--ignore-rules' in args


@pytest.mark.parametrize('role', ['reviewer', 'executor'])
def test_claude_keeps_setting_sources_empty(context, role):
    args = argv_for(CLIConfig('claude', ('/synthetic/cli',), '2.1.305', (), 1), context, request(role))
    assert args[args.index('--setting-sources') + 1] == ''
    assert json.loads(args[args.index('--settings') + 1]) == {'disableAllHooks': True, 'autoMemoryEnabled': False}
