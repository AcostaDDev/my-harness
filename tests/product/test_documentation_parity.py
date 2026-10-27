"""P008-T003 (D088 points 2, 6 and 8): executor and harness paths, diagram‑code parity and ADR proposals.

Temporary Git and SQLite, fake agents and synthetic data; no providers."""
from dataclasses import replace
import json

import pytest

from my_harness.core.engine.acceptance import documentation_parity, parity_reasons
from my_harness.core.engine.contracts import task_contract
from my_harness.core.engine.documents import blocks, executor_protected, protected_write
from my_harness.core.engine.evidence import ContentEvidence, check_paths
from my_harness.profiles.typescript_web import typescript_web_profile
from my_harness.storage.managed import Conflict
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import VERSIONS, git, review
from test_documents import PLAN_P001, text, v2, v2checkout  # noqa: F401  (fixtures)

HARNESS = ('docs/STATE.md', 'docs/NEXT_STEPS.md', 'docs/ROADMAP.md', 'docs/DECISIONS.md',
           'docs/archive/phase-001/SUMMARY.md', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md')
PRODUCT = ('docs/flows/alta.md', 'docs/DDBB-DIAGRAM.md', 'docs/ARCHITECTURE.md', 'docs/SPECIFICATION.md',
           'docs/phase/notas.md')
PLAN_MODELS = PLAN_P001.replace('`app/**` `docs/flows/**`', '`app/**` `docs/flows/**` `docs/DDBB-DIAGRAM.md`')
PROPOSAL = {'title': 'Usar SQLite como estado', 'decision': 'El estado operativo vive en SQLite.',
            'rationale': 'Transacciones locales sin servidor.'}


def web_protection(world):
    """`typescript-web` protections over the synthetic profile (without its npm commands)."""
    profile = replace(world.context.profile, protected_paths=typescript_web_profile().protected_paths)
    world.context = replace(world.context, profile=profile)


def contract(context, task_id, allowed=('docs/**', 'app/**')):
    policy = context.policy
    return json.loads(task_contract(context, {
        'task_id': task_id, 'phase_id': 'P001', 'title': 'Sintética', 'objective': 'o', 'executor_prompt': 'p',
        'allowed_paths': list(allowed), 'forbidden_paths': [], 'acceptance_criteria': ['c'],
        'validation_commands': [], 'executor_selection': {
            'model': policy.executor_models[0], 'effort': policy.executor_efforts[0], 'reason': 'r'}},
        task_id, 'P001'))


def reviewer_input(world):
    prompt = [item for item in world.ports.agents.requests if item.role == 'reviewer'][-1].prompt
    return json.loads(next(line for line in prompt.splitlines() if line.startswith('{"') and '"evidence"' in line))


def changed(*paths):
    return ContentEvidence('base', 'fingerprint', tuple(paths), '')


def test_profile_protects_control_documents_not_product_documentation(v2):
    web_protection(v2)
    task = contract(v2.context, 'P001-T001')
    assert set(HARNESS[:4]) | {'docs/archive/**', 'AGENTS.md', 'CLAUDE.md', 'GEMINI.md'} <= set(task['forbidden_paths'])
    assert check_paths(v2.context, task, changed(*PRODUCT, 'app/main.txt')).violations == ()
    for path in HARNESS:
        assert check_paths(v2.context, task, changed(path)).violations == (path,), path
        assert executor_protected(v2.context, 'P001-T001', path), path
    # Reconciliation edits the prose of the harness documents; never the archive or the instructions.
    assert not any(executor_protected(v2.context, 'P001-RECONCILE-1', path) for path in HARNESS[:4])
    assert all(executor_protected(v2.context, 'P001-RECONCILE-1', path) for path in HARNESS[4:])
    reconcile = contract(v2.context, 'P001-RECONCILE-1', ('docs/**',))
    assert not set(HARNESS[:4]) & set(reconcile['forbidden_paths'])
    assert check_paths(v2.context, reconcile, changed(*HARNESS[:4], *PRODUCT)).violations == ()
    assert check_paths(v2.context, reconcile, changed(*HARNESS[4:])).violations == tuple(sorted(HARNESS[4:]))
    # Outside the v2 layout the profile rules, reconciliation included (D081).
    v1 = replace(v2.context, documents=None)
    assert executor_protected(v1, 'P001-RECONCILE-1', 'docs/STATE.md')
    assert not executor_protected(v1, 'P001-T001', 'docs/flows/alta.md')


def test_instruction_files_are_editable_by_confirmed_writes_only(v2):
    web_protection(v2)
    from my_harness.core.engine.documents import layout
    target = layout(v2.context)
    assert all(target.editable(path) for path in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md'))
    assert not target.editable('docs/archive/phase-001/SUMMARY.md') and not target.editable('agents.md')
    assert not any(protected_write(v2.context, path) for path in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md'))
    assert protected_write(replace(v2.context, documents=None), 'AGENTS.md')


def test_executor_writes_flows_but_not_control_documents(v2):
    web_protection(v2)
    v2.create_v2()

    def flows(context, request):
        context.path('app/main.txt').write_text('implemented\n', encoding='utf-8')
        context.path('docs/flows').mkdir(exist_ok=True)
        context.path('docs/flows/alta.md').write_text('# Flujo — alta\n', encoding='utf-8')
        return {'result': 'Flujo documentado'}
    v2.script(flows, {**review(), 'task_id': 'P001-T001'})
    job = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    record = v2.repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    v2.repository.submit_commit(job.run_id, key=v2.key(), expected_version=record.version)
    v2.run()
    assert v2.repository.get_run(job.run_id).status == 'COMMITTED'
    assert text(v2, 'docs/flows/alta.md') == '# Flujo — alta\n'

    def agents(context, request):
        context.path('app/main.txt').write_text('again\n', encoding='utf-8')
        context.path('AGENTS.md').write_text('# Reescrito por el ejecutor\n', encoding='utf-8')
        return {'result': 'tampered'}
    v2.script(agents, {**review(), 'task_id': 'P001-T001'})
    tampered = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    record = v2.repository.get_run(tampered.run_id)
    assert record.status == 'STOPPED' and 'AGENTS.md' in record.history.cycles[-1].policy.violations


def models(with_diagram):
    def response(context, request):
        context.path('app/models.py').write_text('class Pedido: ...\n', encoding='utf-8')
        if with_diagram:
            context.path('docs/DDBB-DIAGRAM.md').write_text('# Datos\n\n```mermaid\nerDiagram\n    PEDIDO\n```\n',
                                                            encoding='utf-8')
        return {'result': 'Modelo Pedido'}
    return response


@pytest.mark.parametrize('with_diagram', [False, True])
def test_data_model_change_requires_the_data_diagram(v2, with_diagram):
    web_protection(v2)
    v2.context = replace(v2.context, profile=replace(v2.context.profile, data_model_paths=('**/models.py',)))
    v2.create_v2(plan=PLAN_MODELS)
    v2.script(models(with_diagram), {**review(), 'task_id': 'P001-T001'})
    job = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_MODELS, VERSIONS, key=v2.key())
    v2.run()
    record = v2.repository.get_run(job.run_id)
    reviewer = reviewer_input(v2)
    assert reviewer['documentation'] == {
        'data_model_paths': ['**/models.py'], 'data_model_changes': ['app/models.py'],
        'ddbb_diagram': 'docs/DDBB-DIAGRAM.md', 'ddbb_diagram_changed': with_diagram,
        'flows_dir': 'docs/flows', 'flows_changed': []}
    if with_diagram:
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        v2.repository.submit_commit(job.run_id, key=v2.key(), expected_version=record.version)
        v2.run()
        assert v2.repository.get_run(job.run_id).status == 'COMMITTED'
        return
    reason = 'Data model changed without docs/DDBB-DIAGRAM.md (D088): app/models.py'
    assert record.status == 'STOPPED' and record.history.stop.stage == 'acceptance'
    assert reason in record.history.acceptance.reasons
    with pytest.raises(Conflict):
        v2.repository.submit_commit(job.run_id, key=v2.key(), expected_version=record.version)


def test_parity_rule_applies_only_to_declared_models_in_the_v2_layout(v2):
    profile = replace(v2.context.profile, data_model_paths=('**/models.py', '**/migrations/**'))
    context = replace(v2.context, profile=profile)
    assert parity_reasons(context, ('app/main.txt', 'docs/flows/alta.md')) == []
    assert parity_reasons(context, ('app/migrations/0001.py', 'docs/DDBB-DIAGRAM.md')) == []
    assert parity_reasons(context, ('app/migrations/0001.py',)) == [
        'Data model changed without docs/DDBB-DIAGRAM.md (D088): app/migrations/0001.py']
    assert documentation_parity(context, ('docs/flows/alta.md',))['flows_changed'] == ['docs/flows/alta.md']
    v1 = replace(context, documents=None)
    assert documentation_parity(v1, ('app/models.py',)) is None and parity_reasons(v1, ('app/models.py',)) == []


def test_decision_proposals_are_recorded_without_writing_decisions(v2):
    pid = v2.create_v2()
    decisions = text(v2, 'docs/DECISIONS.md')

    def propose(context, request):
        context.path('app/main.txt').write_text('implemented\n', encoding='utf-8')
        return {'result': 'synthetic', 'decision_proposals': [PROPOSAL]}
    v2.script(propose, {**review(), 'task_id': 'P001-T001', 'decision_proposals': [PROPOSAL]})
    job = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    reviewer = reviewer_input(v2)
    assert reviewer['executor_decision_proposals'] == [PROPOSAL]
    record = v2.repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    assert json.loads(record.history.cycles[-1].review_json)['decision_proposals'] == [PROPOSAL]
    v2.repository.submit_commit(job.run_id, key=v2.key(), expected_version=record.version)
    v2.run()
    assert v2.repository.get_run(job.run_id).status == 'COMMITTED'
    # Outside the managed index, which the commit regenerates, DECISIONS does not change: no proposal is written.
    after = text(v2, 'docs/DECISIONS.md')
    assert after.replace(blocks(after)['decisions'], '') == decisions.replace(blocks(decisions)['decisions'], '')
    assert 'Usar SQLite' not in git(v2.context.root, 'show', 'HEAD:docs/DECISIONS.md')
    # Reconciliation receives them to consolidate them and may edit DECISIONS even if the profile protects it.
    web_protection(v2)
    reconcile = v2.phases.submit_reconcile_task(v2.context, pid, v2.get(pid)['version'], key=v2.key(),
                                                versions=VERSIONS)
    task = json.loads(json.loads(v2.repository.get_job(reconcile.id).request_json)['contract_json'])
    assert '"decision_proposals":{"P001-T001":[' in task['executor_prompt']
    assert any('Consolidate the reviewer decision_proposals' in item for item in task['implementation_constraints'])
    assert 'docs/DECISIONS.md' not in task['forbidden_paths'] and 'AGENTS.md' in task['forbidden_paths']


@pytest.mark.parametrize('role', ['executor', 'reviewer'])
def test_malformed_decision_proposals_stop_the_run(v2, role):
    v2.create_v2()
    bad = [{**PROPOSAL, 'extra': 'x'}]

    def edit(context, request):
        context.path('app/main.txt').write_text('implemented\n', encoding='utf-8')
        return {'result': 'synthetic', **({'decision_proposals': bad} if role == 'executor' else {})}
    v2.script(edit, *([{**review(), 'task_id': 'P001-T001', 'decision_proposals': bad}] if role == 'reviewer' else []))
    job = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    record = v2.repository.get_run(job.run_id)
    assert record.status == 'STOPPED' and record.history.stop.stage == role
    assert 'decision proposal' in record.history.stop.reason
    assert v2.ports.roles() == (['executor'] if role == 'executor' else ['executor', 'reviewer'])


def test_profile_protecting_all_docs_still_requires_manual_reconciliation(v2):
    pid = v2.create_v2()
    v2.accept()
    v2.context = replace(v2.context, profile=replace(v2.context.profile, protected_paths=('docs/**',)))
    with pytest.raises(Conflict, match='reconcile it by hand'):
        v2.phases.submit_reconcile_task(v2.context, pid, v2.get(pid)['version'], key=v2.key(), versions=VERSIONS)


def test_context_snapshot_keeps_the_previous_shape_without_data_model_paths(v2):
    from my_harness.core.engine.contracts import context_snapshot
    from my_harness.core.engine.serialization import restore_context
    assert 'data_model_paths' not in json.loads(context_snapshot(v2.context))['profile']
    declared = replace(v2.context, profile=replace(v2.context.profile, data_model_paths=('**/models.py',)))
    frozen = context_snapshot(declared)
    assert json.loads(frozen)['profile']['data_model_paths'] == ['**/models.py']
    assert restore_context(frozen) == declared and context_snapshot(restore_context(frozen)) == frozen
