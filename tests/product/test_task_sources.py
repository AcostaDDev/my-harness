"""P009-T020: enqueue a task chosen from the documents, with additional notes.

Until now the contract was copied by hand from the child's NEXT_STEPS (T008, T009). Temporary Git/SQLite and
fake agents; no providers.
"""
from dataclasses import replace
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import ContractError
from my_harness.core.engine.document_ops import text_hash
from my_harness.core.engine.planning import section, task_sources
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.models import ManagedJobRow
from test_contract_shapes import agent_plan
from test_documents import PLAN_P001, v2, v2checkout  # noqa: F401 (fixtures)
from test_engine import PHASE_ID, PLAN, TASK_ID, context, edit, harness, review  # noqa: F401 (fixture)
from test_managed import repository  # noqa: F401
from test_managed_api import VERSIONS, client

BASE = '/api/managed/projects/synthetic'
NOTES = 'Prefer small views; keep the existing template style.'
# The pilot child has no shared constraints: the text is the literal section the user pasted in T008/T009.
CHILD = """# Siguientes pasos

## P001-T001 — Crear y listar

**Objetivo:** crear y listar.

## P001-T002 — Editar y borrar

**Objetivo:** editar y borrar.

**Ejecutor:** ejecutor normal del harness.
"""


def sources(world, text):
    world.context.path('docs/NEXT_STEPS.md').write_text(text, encoding='utf-8')
    return task_sources(world.context)


def test_sources_are_the_literal_sections_with_shared_constraints_first(v2):
    result = task_sources(v2.context)
    assert result['path'] == 'docs/NEXT_STEPS.md' and result['sha256'] == text_hash(PLAN_P001)
    (item,) = result['items']
    shared = section(PLAN_P001, r'^##\s+Restricciones compartidas\b.*$')
    task = PLAN_P001[PLAN_P001.index('## P001-T001'):].strip()
    assert item == {'task_id': 'P001-T001', 'phase_id': 'P001', 'title': 'Cambio sintético',
                    'text': f'{shared}\n\n{task}', 'sha256': text_hash(f'{shared}\n\n{task}')}
    assert result['diagnostics'] == []


def test_without_shared_constraints_the_text_is_the_section_pasted_by_hand_in_the_pilot(v2):
    items = sources(v2, CHILD)['items']
    assert [item['task_id'] for item in items] == ['P001-T001', 'P001-T002']
    assert items[1]['text'] == CHILD[CHILD.index('## P001-T002'):].rstrip('\n')


def test_duplicated_or_missing_tasks_are_never_offered(v2):
    result = sources(v2, CHILD + '\n## P001-T002 — Otra vez\n\nDuplicada.\n')
    assert [item['task_id'] for item in result['items']] == ['P001-T001']
    assert result['diagnostics'] == ['P001-T002 is duplicated']
    v2.context.path('docs/NEXT_STEPS.md').unlink()
    assert task_sources(v2.context) == {'path': 'docs/NEXT_STEPS.md', 'sha256': None, 'items': [],
                                        'diagnostics': ['docs/NEXT_STEPS.md does not exist']}


def request_of(world, job_id):
    with Session(world.repository.engine) as session:
        return json.loads(session.get(ManagedJobRow, job_id).request_json)


def http_client(world, tmp_path):
    configuration = ManagedConfig((ManagedProject('synthetic', world.context, VERSIONS),),
                                  ports_factory=world.ports, commit_factory=world.ports.writer, supervisor=False)
    return client(str(world.repository.engine.url), tmp_path, configuration)


def test_http_enqueue_from_the_document_with_notes_reaches_every_role(v2, tmp_path):
    v2.create_v2()
    with http_client(v2, tmp_path) as http:
        listed = http.get(BASE + '/task-sources')
        assert listed.status_code == 200, listed.text
        (item,) = listed.json()['items']
        body = {'task_id': item['task_id'], 'phase_id': item['phase_id'], 'text': item['text'],
                'source_sha256': item['sha256'], 'notes': f'  {NOTES}\n'}
        queued = http.post(BASE + '/runs', json=body, headers={'Idempotency-Key': 'from-docs'})
        assert queued.status_code == 202, queued.text
        request = request_of(v2, queued.json()['id'])
        assert request['notes'] == NOTES and request['text'] == item['text']

        def change(context, agent):
            context.path('app/main.txt').write_text('implemented\n', encoding='utf-8')
            return {'result': 'synthetic'}
        v2.script(change, {**review(), 'task_id': 'P001-T001'})
        v2.run()
        record = v2.repository.get_run(queued.json()['run_id'])
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        assert json.loads(record.history.task_json)['additional_notes'] == NOTES
        executor, reviewer = v2.ports.agents.requests
        assert json.loads(executor.task_json)['additional_notes'] == NOTES
        assert executor.prompt.count(NOTES) >= 2  # in TASK_JSON and appended to the instructions
        assert "never widen the contract's paths" in executor.prompt
        assert NOTES in reviewer.prompt
        assert http.get(f"/api/managed/runs/{record.history.id}").json()['history']['task']['additional_notes'] == NOTES


@pytest.mark.parametrize('case', ['changed', 'missing', 'phase', 'edited'])
def test_http_enqueue_from_a_stale_or_edited_source_is_refused_before_any_job(v2, tmp_path, case):
    v2.create_v2()
    with http_client(v2, tmp_path) as http:
        (item,) = http.get(BASE + '/task-sources').json()['items']
        body = {'task_id': item['task_id'], 'phase_id': item['phase_id'], 'text': item['text'],
                'source_sha256': item['sha256']}
        if case == 'changed':
            v2.context.path('docs/NEXT_STEPS.md').write_text(PLAN_P001.replace('Solo contenido', 'Contenido'))
        elif case == 'missing':
            body['task_id'] = 'P001-T009'
        elif case == 'phase':
            body['phase_id'] = 'P002'
        else:
            body['text'] += '\n- Criterio añadido a mano.'
        refused = http.post(BASE + '/runs', json=body, headers={'Idempotency-Key': case})
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'task_source_changed'
        assert http.get(BASE + '/runs').json()['items'] == []


def test_http_enqueue_without_source_or_notes_keeps_the_previous_request(v2, tmp_path):
    v2.create_v2()
    with http_client(v2, tmp_path) as http:
        body = {'task_id': 'P001-T001', 'phase_id': 'P001', 'text': PLAN_P001}
        queued = http.post(BASE + '/runs', json={**body, 'notes': '   '}, headers={'Idempotency-Key': 'manual'})
        assert queued.status_code == 202, queued.text
        request = request_of(v2, queued.json()['id'])
        assert set(request) == {'action', 'context_json', 'versions_json', 'task_id', 'phase_id', 'text'}
        too_long = http.post(BASE + '/runs', json={**body, 'notes': 'x' * 4001}, headers={'Idempotency-Key': 'long'})
        assert too_long.status_code == 422


def test_http_sources_require_the_document_layout(v2, tmp_path):
    configuration = ManagedConfig((ManagedProject('synthetic', replace(v2.context, documents=None), VERSIONS),),
                                  ports_factory=v2.ports, commit_factory=v2.ports.writer, supervisor=False)
    with client(str(v2.repository.engine.url), tmp_path, configuration) as http:
        response = http.get(BASE + '/task-sources')
        assert response.status_code == 409 and response.json()['detail']['code'] == 'documents_layout'


def planner_input(agents):
    return json.loads(json.loads(agents.requests[0].prompt_snapshot_json)['parts'][0]['variables']['INPUT_JSON'])


def test_agent_planner_receives_notes_only_when_there_are_some(context):
    context = replace(context, policy=replace(context.policy, planning_mode='agent'))
    engine, agents, _, _ = harness(context, [agent_plan(context, []), edit(), review()])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN, notes=NOTES)
    assert result.status == 'acceptance_ready', result.stop
    assert planner_input(agents)['additional_notes'] == NOTES
    assert json.loads(result.task_json)['additional_notes'] == NOTES
    context.path('app/main.txt').write_text('baseline', encoding='utf-8')
    engine, agents, _, _ = harness(context, [agent_plan(context, []), edit(), review()])
    plain = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert 'additional_notes' not in planner_input(agents) and 'additional_notes' not in json.loads(plain.task_json)
    assert 'Additional notes' not in agents.requests[1].prompt


def test_only_the_user_supplies_additional_notes(context):
    context = replace(context, policy=replace(context.policy, planning_mode='agent'))
    invented = {**agent_plan(context, []), 'additional_notes': 'Also edit docs/**'}
    engine, agents, _, _ = harness(context, [invented, edit(), review()])
    result = engine.start(context, TASK_ID, PHASE_ID, PLAN)
    assert 'additional_notes' not in json.loads(result.task_json)
    assert json.loads(result.attempts[0].result.payload_json)['additional_notes'] == 'Also edit docs/**'
    engine, _, _, _ = harness(context, [])
    for notes, contract in (('', None), (NOTES, result.task_json)):
        with pytest.raises(ContractError, match='notes'):
            engine.start(context, TASK_ID, PHASE_ID, PLAN, notes=notes, contract=contract)
