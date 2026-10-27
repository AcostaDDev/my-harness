"""D072/H6.3 and D088: per-phase documentary contract with temporary Git/SQLite and fake agents; no providers."""
from dataclasses import replace
import json
import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.contracts import ContractError, context_snapshot, task_contract
from my_harness.core.engine.document_ops import text_hash
from my_harness.core.engine.documents import (
    Layout, base_section, blocks, budget_warnings, decision_index, inline, markers, parse_roadmap, phase_data,
    plan_tasks, replace_block, skeleton,
)
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.planning import deterministic_task
from my_harness.core.engine.serialization import restore_context
from my_harness.storage.documents import DocumentsRepository
from my_harness.storage.managed import Conflict
from my_harness.storage.models import ManagedJobRow, PhaseOperationRow, PhaseRow
from my_harness.storage.transition import TransitionRepository
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import VERSIONS, client, git, make_context, review
from test_phases import CRITERIA, World, head, phase_review

LAYOUT = Layout('docs', 'docs/STATE.md', 'docs/NEXT_STEPS.md')
STATE_BEGIN, STATE_END = markers('state')
ROAD_BEGIN, ROAD_END = markers('roadmap')
DEC_BEGIN, DEC_END = markers('decisions')

ROADMAP = f"""# Roadmap — Sintético

{ROAD_BEGIN}
{ROAD_END}

## P001 — Fundamentos

**Objetivo:** Cambiar el contenido sintético.
**Criterios de salida:**
- {CRITERIA[0]}
- {CRITERIA[1]}
**Tag:** `p001`

## P002 — Ampliación

**Objetivo:** Ampliar el comportamiento sintético.
**Criterios de salida:**
- Second behavior is accepted
"""

PLAN_P001 = f"""# P001 — Fundamentos

Objetivo y criterios en [ROADMAP](ROADMAP.md).

{STATE_BEGIN}
{STATE_END}

## Restricciones compartidas

Solo contenido sintético.

## P001-T001 — Cambio sintético

**Objetivo:** Cambiar el contenido sintético.
**Rutas permitidas:** `app/**` `docs/flows/**`
**Criterios de aceptación:**
- Synthetic behavior is present.
**Comandos de validación:** `test-runner check`
**Ejecutor:** synthetic-executor / medium — Selección explícita de prueba
"""

PLAN_P002 = """# P002 — Ampliación

## P002-T001 — Segundo cambio

**Objetivo:** Ampliar el contenido sintético.
**Rutas permitidas:** `app/**`
**Criterios de aceptación:**
- Second behavior is present.
**Ejecutor:** synthetic-executor / medium — Selección explícita de prueba
"""

STATE = f"""# Estado — Sintético

{STATE_BEGIN}
{STATE_END}

## Base acumulada

- Contenido sintético base disponible.
- Línea literal con `código` y | barra.

## Fase activa — P001 Fundamentos

Sin notas todavía.
"""

D001 = """## D001 — Usar Git como historial

**Estado:** aceptada
Párrafo que no entra en el índice.
**Fecha:** 2026-10-14
**Fase:** P000
**Contexto:** sintético.
"""

DECISIONS = f"""# Decisiones — Sintético

Registro único con índice gestionado (D088).

{DEC_BEGIN}
{DEC_END}

{D001}"""


def v2_files(roadmap=ROADMAP):
    files = skeleton(LAYOUT, 'Sintético')
    files.update({'docs/ROADMAP.md': roadmap, 'docs/NEXT_STEPS.md': PLAN_P001, 'docs/STATE.md': STATE,
                  'docs/DECISIONS.md': DECISIONS,
                  'app/main.txt': 'baseline\n'})
    return files


@pytest.fixture
def v2checkout(tmp_path):
    root = tmp_path / 'v2-checkout'
    for path, text in v2_files().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'v2 baseline')
    return replace(make_context(root), documents='v2')


class V2World(World):
    def create_v2(self, code='P001', plan=PLAN_P001):
        roadmap = self.context.path('docs/ROADMAP.md').read_text(encoding='utf-8')
        entry = next(item for item in parse_roadmap(roadmap) if item['code'] == code)
        return self.phases.create(self.context, phase_data(LAYOUT, entry, plan_tasks(plan, code)))

    def accept(self, task='P001-T001', plan=PLAN_P001, change=None):
        def default(context, request):
            context.path('app/main.txt').write_text(f'implemented {task}\n', encoding='utf-8')
            return {'result': f'Implementado {task} | con <b>marcado</b>\n## no es encabezado'}
        self.script(change or default, {**review(), 'task_id': task})
        job = self.repository.submit(self.context, task, task.split('-')[0], plan, VERSIONS, key=self.key())
        self.run()
        record = self.repository.get_run(job.run_id)
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        self.repository.submit_commit(job.run_id, key=self.key(), expected_version=record.version)
        self.run()
        assert self.repository.get_run(job.run_id).status == 'COMMITTED'
        return job.run_id

    def close_ready(self, pid):
        self.check(pid, phase_review())
        _, closed = self.close(pid)
        assert closed['status'] == 'CLOSED', closed['operations'][-1]
        return closed


@pytest.fixture
def v2(repository, v2checkout, _legacy_close):  # noqa: F811
    return V2World(repository, v2checkout)


def text(world, path):
    return world.context.path(path).read_text(encoding='utf-8')


def transitions(world):
    return TransitionRepository(world.repository)


def transition_view(world, pid, plan=PLAN_P002):
    return transitions(world).preview(world.context, pid, world.ports.writer(world.context, VERSIONS), plan)


def queue_transition(world, pid, view=None, plan=PLAN_P002, key=None):
    view = view or transition_view(world, pid, plan)
    return transitions(world).submit(world.context, pid, view['expected_version'], key=key or world.key(),
                                     versions=VERSIONS, preview_sha256=view['preview_sha256'],
                                     reason='Reviewed synthetic transition', confirmed=True,
                                     git=world.ports.writer(world.context, VERSIONS), next_steps=plan,
                                     resume_operation_id=view['resume_operation_id'])


def editor(world):
    return DocumentsRepository(world.repository)


def edit_view(world, source='content', changes=None):
    return editor(world).preview(world.context, world.ports.writer(world.context, VERSIONS), source=source,
                                 changes=changes)


def queue_edit(world, source='content', changes=None, view=None, key=None):
    view = view or edit_view(world, source, changes)
    return editor(world).submit(world.context, key=key or world.key(), versions=VERSIONS,
                                preview_sha256=view['preview_sha256'], reason='Reviewed synthetic edit',
                                confirmed=True, git=world.ports.writer(world.context, VERSIONS), source=source,
                                changes=changes, resume_operation_id=view['resume_operation_id'])


def confirm(world, job):
    row = world.repository.get_job(job.id)
    world.repository.confirm_stopped(job.id, owner_token=row.owner_token,
                                     expected_version=world.repository.get_run(job.run_id).version,
                                     reason='Synthetic writer stopped')


def phase_rows(world):
    with Session(world.repository.engine) as session:
        return [(row.code, row.status) for row in session.scalars(select(PhaseRow).order_by(PhaseRow.created_at))]


def fresh_session(root) -> dict:
    """What a new session rebuilds by reading only the Markdown of the checkout, without SQLite."""
    docs = {name: (root / 'docs' / name).read_text(encoding='utf-8')
            for name in ('STATE.md', 'NEXT_STEPS.md', 'ROADMAP.md', 'DECISIONS.md')}
    block = blocks(docs['NEXT_STEPS.md'])['state']
    active = re.search(r'\*\*Fase:\*\* (P\d{3})', block).group(1)
    # The rendered Markdown does not show the escape backslashes of the block.
    following = re.search(r'\*\*Siguiente tarea:\*\* (\S+)', block).group(1).replace('\\', '')
    road = blocks(docs['ROADMAP.md'])['roadmap']
    return {'phase': active, 'next_task': following,
            'task_heading': next(title for task, title in plan_tasks(docs['NEXT_STEPS.md']) if task == following),
            'roadmap_status': dict(re.findall(r'^\| (P\d{3}) \| [^|]+ \| ([^|]+?) \|', road, re.MULTILINE)),
            'base': base_section(docs['STATE.md']),
            'decisions': re.findall(r'^\| (D\d{3}) \|', blocks(docs['DECISIONS.md'])['decisions'], re.MULTILINE)}


# --- pure contract -----------------------------------------------------------------------------


def test_named_blocks_validate_markers_and_inline_values_cannot_inject_markdown():
    body = 'x\n'
    text = f'# T\r\n{ROAD_BEGIN}\r\nold\r\n{ROAD_END}\r\ntail\r\n'
    assert replace_block(text, body, 'roadmap') == f'# T\r\n{ROAD_BEGIN}\nx\n{ROAD_END}\r\ntail\r\n'
    assert replace_block('# T', body, 'decisions') == f'# T\n{DEC_BEGIN}\nx\n{DEC_END}\n'
    with pytest.raises(ValueError, match='markers'):
        replace_block(f'{ROAD_BEGIN}\n{ROAD_BEGIN}\n{ROAD_END}\n', body, 'roadmap')
    with pytest.raises(ValueError, match='Unknown or partial'):
        blocks(f'# T\n<!-- harness-local:managed-other:start -->\n')
    hostile = f'a\n## b {STATE_END} <script>`|*_[x](y)\n```'
    escaped = inline(hostile)
    assert '\n' not in escaped and '<' not in escaped and '`' not in escaped.replace('\\`', '')
    assert 'harness-local:managed' in escaped and '&lt;!--' in escaped and '\\|' in escaped
    assert blocks(replace_block('# T\n', escaped + '\n', 'state')) == {
        'state': f'{STATE_BEGIN}\n{escaped}\n{STATE_END}'}
    long = inline('x' * 700, 600)
    assert long.endswith('(recortado; texto completo en el historial de SQLite)')


def test_roadmap_plan_decisions_and_base_are_read_structurally():
    entries = parse_roadmap(ROADMAP)
    assert [(e['code'], e['title'], e['tag']) for e in entries] == [('P001', 'Fundamentos', 'p001'),
                                                                  ('P002', 'Ampliación', None)]
    assert entries[0]['exit_criteria'] == CRITERIA and entries[1]['objective'] == 'Ampliar el comportamiento sintético.'
    english = '## P009 — English\n**Objective:** Do it.\n**Exit criteria:**\n- Done\n'
    assert parse_roadmap(english)[0]['exit_criteria'] == ['Done']
    with pytest.raises(ValueError, match='Duplicate'):
        parse_roadmap(english + english)
    assert plan_tasks(PLAN_P001, 'P001') == [('P001-T001', 'Cambio sintético')]
    with pytest.raises(ValueError, match='belong to phase'):
        plan_tasks(PLAN_P002, 'P001')
    plain = '## D010 — Z\n\nEstado: decidido por el usuario;\ncontinúa en otra línea.\n\n## D003 — Sin estado\n'
    index = decision_index(DECISIONS + '# D002 — Nivel 1, ignorado\n\n' + plain)
    assert index == [{'id': 'D001', 'title': 'Usar Git como historial', 'status': 'aceptada'},
                     {'id': 'D003', 'title': 'Sin estado', 'status': None},
                     {'id': 'D010', 'title': 'Z', 'status': 'decidido por el usuario;'}]
    block = replace_block(DECISIONS, '| D099 | fila | — |\n## D098 — dentro del bloque\n', 'decisions')
    assert [entry['id'] for entry in decision_index(block)] == ['D001']  # the block is never read as a source
    for duplicate in ('## D001 — Otra vez\n', '## D0001 — Otro relleno\n'):
        with pytest.raises(ValueError, match='Duplicate decision number'):
            decision_index(DECISIONS + duplicate)
    assert decision_index(None) == [] and decision_index('# Decisiones\n') == []
    assert base_section(STATE).startswith('## Base acumulada\n\n- Contenido') and 'Fase activa' not in base_section(STATE)
    assert budget_warnings(LAYOUT, {'docs/STATE.md': STATE}) == []
    huge = STATE.replace('Sin notas todavía.', 'x' * 30_000)
    assert len(budget_warnings(LAYOUT, {'docs/STATE.md': huge})) == 1
    # D088: DECISIONS has no budget.
    assert budget_warnings(LAYOUT, {'docs/DECISIONS.md': DECISIONS + 'x' * 100_000}) == []


def test_skeleton_is_a_valid_v2_document_set_with_spanish_deterministic_plan(tmp_path):
    files = skeleton(LAYOUT, 'Proyecto <nuevo>')
    assert sorted(files) == ['AGENTS.md', 'CLAUDE.md', 'GEMINI.md', 'README.md', 'docs/ARCHITECTURE.md',
                             'docs/DDBB-DIAGRAM.md', 'docs/DECISIONS.md', 'docs/NEXT_STEPS.md', 'docs/ROADMAP.md',
                             'docs/SPECIFICATION.md', 'docs/STATE.md']
    assert not any(part in path for path in files for part in ('decisions/', 'architecture/', 'research/'))
    assert '<nuevo>' not in files['README.md'] and '&lt;nuevo&gt;' in files['README.md']
    assert 'Sin persistencia.' in files['docs/DDBB-DIAGRAM.md'] and decision_index(files['docs/DECISIONS.md']) == []
    for path in LAYOUT.phase_documents:
        blocks(files[path])
    assert parse_roadmap(files['docs/ROADMAP.md'])[0]['code'] == 'P001'
    assert plan_tasks(files['docs/NEXT_STEPS.md'], 'P001') == [('P001-T001', 'Primera tarea')]
    context = replace(make_context(tmp_path), documents='v2')
    contract = json.loads(deterministic_task(context, 'P001-T001', 'P001', PLAN_P001))
    assert contract['allowed_paths'] == ['app/**', 'docs/flows/**']
    assert contract['implementation_constraints'][0].startswith('Shared constraints: ## Restricciones compartidas')
    assert contract['executor_selection']['reason'] == 'Selección explícita de prueba'
    assert {'docs/archive/**', 'docs/STATE.md', 'docs/NEXT_STEPS.md', 'docs/ROADMAP.md',
            'docs/DECISIONS.md'} <= set(contract['forbidden_paths'])


def test_generated_instruction_files_respect_their_line_budgets_and_list_profile_commands():
    """D088 point 1: AGENTS ≤60 lines with discovery, rules and commands; CLAUDE and GEMINI ≤15 that import it."""
    from my_harness.core.engine.documents import MAX_AGENTS_LINES, MAX_WRAPPER_LINES
    plain = skeleton(LAYOUT, 'Sintético')
    assert 'Sin comandos declarados' in plain['AGENTS.md']
    many = [('pytest', '-q', f'tests/test_{n}.py') for n in range(40)]
    files = skeleton(LAYOUT, 'Sintético', preparation=[('uv', 'sync', '--frozen')],
                     validations=[('ruff', 'check', 'src dir'), ('echo', 'a\n```\nb'), *many])
    agents = files['AGENTS.md']
    assert 0 < len(agents.splitlines()) <= MAX_AGENTS_LINES
    assert len(plain['AGENTS.md'].splitlines()) <= MAX_AGENTS_LINES
    for heading in ('## Discovery al empezar una sesión', '## Reglas inquebrantables', '## Comandos'):
        assert heading in agents
    assert 'uv sync --frozen' in agents and "ruff check 'src dir'" in agents and 'más declarados en el perfil' in agents
    assert agents.count('```') == 4 and 'comando omitido' in agents  # no argv closes the code block
    for name in ('CLAUDE.md', 'GEMINI.md'):
        assert len(files[name].splitlines()) <= MAX_WRAPPER_LINES and '\n@AGENTS.md\n' in files[name]
    worst = skeleton(LAYOUT, 'x' * 300, preparation=many, validations=many)['AGENTS.md']
    assert len(worst.splitlines()) <= MAX_AGENTS_LINES  # both groups trimmed at once


def test_context_snapshot_keeps_v1_shape_and_round_trips_v2(tmp_path):
    v1 = make_context(tmp_path)
    assert 'documents' not in json.loads(context_snapshot(v1))
    v2 = replace(v1, documents='v2')
    assert restore_context(context_snapshot(v2)) == v2 and restore_context(context_snapshot(v1)) == v1
    with pytest.raises(ValueError, match='layout'):
        replace(v1, documents='v3')
    with pytest.raises(ValueError, match='one documentation directory'):
        replace(v1, documents='v2', next_steps_file='plan/NEXT_STEPS.md')


def test_v2_contracts_forbid_harness_documents_except_reconcile_prose(tmp_path):
    context = replace(make_context(tmp_path), documents='v2')
    base = {'task_id': 'P001-T001', 'phase_id': 'P001', 'title': 't', 'objective': 'o', 'executor_prompt': 'p',
            'allowed_paths': ['docs/**'], 'forbidden_paths': [], 'acceptance_criteria': ['c'],
            'validation_commands': [], 'executor_selection': {'model': 'synthetic-executor', 'effort': 'medium',
                                                               'reason': 'r'}}
    frozen = task_contract(context, base, 'P001-T001', 'P001')
    assert task_contract(context, json.loads(frozen), 'P001-T001', 'P001') == frozen  # idempotent
    assert json.loads(frozen)['forbidden_paths'] == ['docs/archive/**', *LAYOUT.harness_owned, *LAYOUT.instructions]
    with pytest.raises(ContractError, match='also forbidden'):
        task_contract(context, {**base, 'allowed_paths': ['docs/STATE.md']}, 'P001-T001', 'P001')
    reconcile = {**base, 'task_id': 'P001-RECONCILE-1', 'allowed_paths': ['docs/STATE.md', 'docs/ROADMAP.md']}
    # D088: reconciliation also edits the prose of DECISIONS (single record); the archive and the instructions
    # stay forbidden (P008-T003).
    assert json.loads(task_contract(context, reconcile, 'P001-RECONCILE-1', 'P001'))['forbidden_paths'] == [
        'docs/archive/**', *LAYOUT.instructions]
    with pytest.raises(ContractError, match='also forbidden'):
        task_contract(context, {**reconcile, 'allowed_paths': ['docs/archive/phase-001/STATE.md']},
                      'P001-RECONCILE-1', 'P001')
    v1 = make_context(tmp_path)
    assert json.loads(task_contract(v1, {**base, 'allowed_paths': ['docs/STATE.md']}, 'P001-T001', 'P001'))[
        'forbidden_paths'] == []


# --- task commits ----------------------------------------------------------------------------------


def test_task_commit_regenerates_blocks_adopts_hashes_and_keeps_prose(v2):
    pid = v2.create_v2()
    assert v2.get(pid)['definition']['documents'] == list(LAYOUT.phase_documents)
    before = {path: text(v2, path) for path in LAYOUT.phase_documents}
    base = head(v2)

    def change(context, request):
        context.path('app/main.txt').write_text('implemented\n', encoding='utf-8')
        context.path('docs/flows/tareas.md').parent.mkdir(exist_ok=True)
        context.path('docs/flows/tareas.md').write_text('# Flujo\n\n```mermaid\nflowchart LR\n  a --> b\n```\n',
                                                        encoding='utf-8')
        return {'result': 'Implementado | con <b>marcado</b>'}
    run_id = v2.accept(change=change)
    assert v2.ports.roles() == ['executor', 'reviewer']  # deterministic plan with Spanish fields
    assert git(v2.context.root, 'rev-parse', 'HEAD^') == base and git(v2.context.root, 'status', '--porcelain') == ''
    changed = git(v2.context.root, 'diff', '--name-only', 'HEAD^', 'HEAD').splitlines()
    assert set(changed) == {'app/main.txt', 'docs/flows/tareas.md', *LAYOUT.phase_documents}
    after = {path: text(v2, path) for path in LAYOUT.phase_documents}
    for path in LAYOUT.phase_documents:
        name = 'state' if path in (LAYOUT.state, LAYOUT.next_steps) else path.split('/')[-1][:-3].lower()
        start, end = markers(name)
        prose = lambda t: t[:t.index(start)] + t[t.index(end):]  # noqa: E731
        assert prose(after[path]) == prose(before[path])
    state = blocks(after[LAYOUT.state])['state']
    assert '| P001-T001 | COMMITTED | ACCEPT | este commit | comandos 1/1 OK |' in state
    assert 'Implementado \\| con &lt;b&gt;marcado&lt;/b&gt;' in state
    assert '**Siguiente tarea:** ninguna' in blocks(after[LAYOUT.next_steps])['state']
    assert '| P001 | Fundamentos | activa | — |' in blocks(after[LAYOUT.roadmap])['roadmap']
    assert '| P002 | Ampliación | pendiente | — |' in blocks(after[LAYOUT.roadmap])['roadmap']
    assert re.findall(r'^\| (D\d{3}) \|', blocks(after[LAYOUT.decisions])['decisions'], re.M) == ['D001']
    detail = v2.get(pid)
    assert detail['documents']['drift'] == []
    assert detail['documents']['baseline'] == {path: text_hash(after[path]) for path in LAYOUT.phase_documents}
    assert v2.repository.get_run(run_id).status == 'COMMITTED'
    assert 'Harness-Mechanical: docs/STATE.md' in git(v2.context.root, 'log', '-1', '--format=%B')


def test_executor_cannot_edit_harness_documents_and_dirty_checkout_never_starts(v2):
    v2.create_v2()

    def tamper(context, request):
        context.path('docs/STATE.md').write_text('rewritten by executor\n', encoding='utf-8')
        return {'result': 'tampered'}
    v2.script(tamper, {**review(), 'task_id': 'P001-T001'})
    job = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    record = v2.repository.get_run(job.run_id)
    assert record.status != 'ACCEPTANCE_READY'
    git(v2.context.root, 'checkout', '--', 'docs/STATE.md')
    roles = list(v2.ports.roles())
    v2.context.path('docs/SPECIFICATION.md').write_text('local edit\n', encoding='utf-8')
    dirty = v2.repository.submit(v2.context, 'P001-T001', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    v2.run()
    stopped = v2.repository.get_run(dirty.run_id)
    assert stopped.status == 'STOPPED' and 'Uncommitted changes' in stopped.history.stop.reason
    assert v2.ports.roles() == roles and text(v2, 'docs/SPECIFICATION.md') == 'local edit\n'


def test_reconcile_task_rewrites_prose_and_harness_regenerates_only_the_block(v2):
    pid = v2.create_v2()
    v2.accept()
    job = v2.phases.submit_reconcile_task(v2.context, pid, v2.get(pid)['version'], key=v2.key(), versions=VERSIONS)
    contract = json.loads(json.loads(v2.repository.get_job(job.id).request_json)['contract_json'])
    assert {'docs/DECISIONS.md', 'docs/SPECIFICATION.md', 'docs/DDBB-DIAGRAM.md', 'docs/flows/**',
            'docs/phase/**'} <= set(contract['allowed_paths'])
    assert 'docs/archive/**' in contract['forbidden_paths'] and 'docs/DECISIONS.md' not in contract['forbidden_paths']
    assert any('"## DNNN — title" sections of docs/DECISIONS.md' in item for item in contract['implementation_constraints'])
    assert any('Base acumulada' in item for item in contract['implementation_constraints'])

    def compact(context, request):
        current = context.path('docs/STATE.md').read_text(encoding='utf-8')
        context.path('docs/STATE.md').write_text(
            current.replace('- Contenido sintético base disponible.', '- Contenido sintético implementado (P001).'),
            encoding='utf-8')
        decisions = context.path('docs/DECISIONS.md')
        decisions.write_text(decisions.read_text(encoding='utf-8') + '\n## D002 — Decisión de la fase\n\n'
                             'Estado: aceptada en la reconciliación\n', encoding='utf-8')
        return {'result': 'Base compactada'}
    v2.script(compact, {**review(), 'task_id': 'P001-RECONCILE-1'})
    v2.run()
    record = v2.repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    v2.repository.submit_commit(job.run_id, key=v2.key(), expected_version=record.version)
    v2.run()
    state = text(v2, 'docs/STATE.md')
    assert '- Contenido sintético implementado (P001).' in state
    assert '| P001-RECONCILE-1 | COMMITTED |' in blocks(state)['state']
    index = blocks(text(v2, 'docs/DECISIONS.md'))['decisions']
    assert '| D002 | Decisión de la fase | aceptada en la reconciliación |' in index
    detail = v2.get(pid)
    # reviewed prose: explicit adoption (D034)
    assert detail['documents']['drift'] == ['docs/DECISIONS.md', 'docs/STATE.md']
    v2.phases.reconcile(v2.context, pid, detail['version'], documents_sha256=detail['documents']['current_sha256'],
                        reason='Adopt reconciled synthetic STATE')
    assert v2.get(pid)['documents']['drift'] == []


# --- phase transition --------------------------------------------------------------------------


def test_transition_archives_bytes_opens_fresh_documents_and_installs_next_phase(v2):
    pid = v2.create_v2()
    v2.accept()
    closed = v2.close_ready(pid)
    tag = git(v2.context.root, 'rev-parse', 'refs/tags/p001')
    archived = {path: v2.context.path(path).read_bytes() for path in (LAYOUT.state, LAYOUT.next_steps)}
    old_head = head(v2)
    a, b = transition_view(v2, pid), transition_view(v2, pid)
    assert a == b and head(v2) == old_head and not v2.context.path('docs/archive').exists()
    assert a['next']['code'] == 'P002' and a['next']['tasks'] == ['P002-T001'] and a['warnings'] == []
    assert a['next']['documents'] == list(LAYOUT.phase_documents) and a['next']['tag'] is None
    job = queue_transition(v2, pid, a, key='transition-once')
    assert queue_transition(v2, pid, a, key='transition-once').id == job.id
    v2.run()
    assert git(v2.context.root, 'rev-parse', 'HEAD^') == old_head and git(v2.context.root, 'status', '--porcelain') == ''
    assert git(v2.context.root, 'rev-parse', 'refs/tags/p001') == tag  # the tag keeps the evaluated HEAD
    archive = v2.context.root / 'docs/archive/phase-001'
    assert sorted(item.name for item in archive.iterdir()) == ['NEXT_STEPS.md', 'REVIEW.md', 'STATE.md', 'SUMMARY.md']
    assert (archive / 'STATE.md').read_bytes() == archived[LAYOUT.state]
    assert (archive / 'NEXT_STEPS.md').read_bytes() == archived[LAYOUT.next_steps]
    review_text = (archive / 'REVIEW.md').read_text()
    assert '**Veredicto:** READY' in review_text and f'| {inline(CRITERIA[0])} | sí |' in review_text
    summary = (archive / 'SUMMARY.md').read_text()
    assert '**Título:** Fundamentos' in summary and '**Tag:** `p001`' in summary
    assert '| P001-T001 | COMMITTED | ACCEPT | executor 1, reviewer 1 |' in summary
    state = text(v2, 'docs/STATE.md')
    assert base_section(STATE).rstrip() in state and '## Fase activa — P002 Ampliación' in state
    assert state.startswith('# Estado — Sintético\n') and 'P001-T001' not in state
    plan = text(v2, 'docs/NEXT_STEPS.md')
    assert plan.startswith(PLAN_P002) and '**Siguiente tarea:** P002-T001' in plan
    session_view = fresh_session(v2.context.root)
    assert session_view['phase'] == 'P002' and session_view['roadmap_status'] == {'P001': 'cerrada', 'P002': 'activa'}
    assert session_view['next_task'] == 'P002-T001' and session_view['task_heading'] == 'Segundo cambio'
    assert session_view['decisions'] == ['D001']
    assert session_view['base'].startswith('## Base acumulada')
    assert '| P001 | Fundamentos | cerrada | `p001` |' in blocks(text(v2, 'docs/ROADMAP.md'))['roadmap']
    assert phase_rows(v2) == [('P001', 'CLOSED'), ('P002', 'ACTIVE')]
    with Session(v2.repository.engine) as session:
        new = session.scalar(select(PhaseRow).where(PhaseRow.code == 'P002'))
        assert new.definition['objective'] == 'Ampliar el comportamiento sintético.'
        assert new.definition['exit_criteria'] == ['Second behavior is accepted']
        assert new.documents == {path: text_hash(text(v2, path)) for path in LAYOUT.phase_documents}
        new_id = new.id
    assert v2.get(new_id)['documents']['drift'] == []
    old = v2.get(pid)
    assert old['status'] == 'CLOSED' and old['operations'][-1]['kind'] == 'transition'
    assert old['operations'][-1]['result']['next_phase_id'] == new_id and closed['status'] == 'CLOSED'
    assert v2.repository.get_run(job.run_id).status == 'COMMITTED' and v2.ports.roles() == [
        'executor', 'reviewer', 'phase']  # the transition invokes no agents
    assert queue_transition(v2, pid, a, key='transition-once').id == job.id and v2.worker.run_once() is None
    with pytest.raises(Conflict, match='latest phase'):
        transition_view(v2, pid)
    # The next session works on the new phase with its plan and fresh blocks.
    v2.accept('P002-T001', text(v2, 'docs/NEXT_STEPS.md'))
    assert '| P002-T001 | COMMITTED | ACCEPT | este commit |' in blocks(text(v2, 'docs/STATE.md'))['state']
    assert v2.get(new_id)['documents']['drift'] == []


TRANSITION_REFUSALS = {
    'active': 'Close or abandon', 'dirty': 'clean checkout', 'drift': 'changed externally',
    'archive_exists': 'already exists; nothing is overwritten', 'no_plan': 'Provide the NEXT_STEPS plan of P002',
    'wrong_prefix': 'must belong to phase P002', 'not_in_roadmap': 'ROADMAP has no section for P001',
    'plan_markers': 'only the managed-state block', 'existing_code': 'Phase P002 already exists'}


@pytest.mark.parametrize('case', sorted(TRANSITION_REFUSALS))
def test_transition_preview_fails_closed_without_effects(v2, case):
    pid = v2.create_v2()
    plan = PLAN_P002
    if case != 'active':
        v2.accept()
        v2.close_ready(pid)
    if case == 'dirty':
        v2.context.path('app/main.txt').write_text('local\n')
    elif case == 'drift':
        v2.context.path('docs/STATE.md').write_text(STATE + '\nexternal\n')
        git(v2.context.root, 'commit', '-qam', 'external STATE')
    elif case == 'archive_exists':
        v2.context.path('docs/archive/phase-001').mkdir(parents=True)
    elif case == 'no_plan':
        plan = None
    elif case == 'wrong_prefix':
        plan = PLAN_P002.replace('P002-T001', 'P003-T001')
    elif case == 'not_in_roadmap':
        v2.context.path('docs/ROADMAP.md').write_text(ROADMAP.replace('## P001 — Fundamentos', '## Fundamentos'))
        git(v2.context.root, 'commit', '-qam', 'roadmap edit')
        detail = v2.get(pid)
        with Session(v2.repository.engine) as session:  # adopted base equal to the disk: only the section fails
            row = session.get(PhaseRow, pid)
            row.documents = {**row.documents, 'docs/ROADMAP.md': detail['documents']['current']['docs/ROADMAP.md']}
            session.commit()
    elif case == 'plan_markers':
        plan = PLAN_P002 + f'{ROAD_BEGIN}\n{ROAD_END}\n'
    elif case == 'existing_code':
        with Session(v2.repository.engine) as session:
            row = session.get(PhaseRow, pid)
            clone = PhaseRow(**{c.name: getattr(row, c.name) for c in PhaseRow.__table__.columns
                                if c.name not in ('id', 'code', 'created_at')},
                             id='synthetic-old-p002', code='P002', created_at='2000-01-01T00:00:00+00:00')
            session.add(clone)
            session.commit()
    before = head(v2)
    with pytest.raises((Conflict, ValueError), match=TRANSITION_REFUSALS[case]):
        transition_view(v2, pid, plan)
    assert head(v2) == before and not (v2.context.root / 'docs/archive/phase-001/STATE.md').exists()


def test_transition_without_next_phase_only_archives(repository, tmp_path, _legacy_close):  # noqa: F811
    root = tmp_path / 'single'
    for path, value in v2_files(ROADMAP.split('## P002')[0]).items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(value, encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'single phase')
    world = V2World(repository, replace(make_context(root), documents='v2'))
    pid = world.create_v2()
    # Inherited terminal phase, from before the unified documentary closure.
    with Session(world.repository.engine) as session:
        session.get(PhaseRow, pid).status = 'ABANDONED'
        session.commit()
    with pytest.raises(Conflict, match='only archives'):
        transition_view(world, pid, PLAN_P002)
    view = transition_view(world, pid, None)
    assert view['next'] is None
    queue_transition(world, pid, view, plan=None)
    world.run()
    assert text(world, 'docs/NEXT_STEPS.md').startswith('# Sin fase activa')
    assert '**Fase activa:** ninguna' in blocks(text(world, 'docs/STATE.md'))['state']
    assert 'ABANDONED sin un check READY' in text(world, 'docs/archive/phase-001/REVIEW.md')
    assert '| P001 | Fundamentos | abandonada | — |' in blocks(text(world, 'docs/ROADMAP.md'))['roadmap']
    assert phase_rows(world) == [('P001', 'ABANDONED')]


@pytest.mark.parametrize('point', ['before_write', 'partial_write', 'after_commit', 'before_adoption'])
def test_transition_crash_recovery_reuses_intent_and_creates_one_phase(v2, point, monkeypatch):
    pid = v2.create_v2()
    v2.accept()
    v2.close_ready(pid)
    original_head = head(v2)
    job = queue_transition(v2, pid)
    original_write, original_execute = GitWorkspace._write_mechanical, GitWorkspace.execute
    import my_harness.storage.transition as module
    original_settle = module.settle
    once = [False]

    def write(self, context, intent):
        if not once[0]:
            once[0] = True
            if point == 'partial_write':
                from dataclasses import replace as clone
                original_write(self, context, clone(intent, mechanical=intent.mechanical[:2]))
            raise RuntimeError('synthetic write crash')
        return original_write(self, context, intent)

    def execute(self, context, intent):
        result = original_execute(self, context, intent)
        if not once[0]:
            once[0] = True
            raise RuntimeError('synthetic post commit crash')
        return result

    def settle(*args):
        original_settle(*args)
        if not once[0]:
            once[0] = True
            raise RuntimeError('synthetic adoption crash')
    if point in ('before_write', 'partial_write'):
        monkeypatch.setattr(GitWorkspace, '_write_mechanical', write)
    elif point == 'after_commit':
        monkeypatch.setattr(GitWorkspace, 'execute', execute)
    else:
        monkeypatch.setattr(module, 'settle', settle)
    with pytest.raises((RuntimeError, JournalError), match='synthetic'):
        v2.run()
    with Session(v2.repository.engine) as session:
        op = session.scalar(select(PhaseOperationRow).where(PhaseOperationRow.run_id == job.run_id))
        expected = json.loads(op.request['commit_intent'])['expected_commit']
        assert op.status == 'INTENT'
        assert session.get(ManagedJobRow, job.id).status == 'RECOVERY_REQUIRED'
    assert phase_rows(v2) == [('P001', 'CLOSED')]
    with pytest.raises(Conflict, match='unfinished'):
        transition_view(v2, pid)
    with pytest.raises(Conflict, match='awaits reconciliation|unfinished'):
        v2.repository.submit(v2.context, 'P001-T009', 'P001', PLAN_P001, VERSIONS, key=v2.key())
    confirm(v2, job)
    recovered = transition_view(v2, pid)
    assert recovered['resume_operation_id'] == op.id
    resumed = queue_transition(v2, pid, recovered)
    assert resumed.run_id == job.run_id
    v2.run()
    assert head(v2) == expected and git(v2.context.root, 'rev-parse', 'HEAD^') == original_head
    assert git(v2.context.root, 'status', '--porcelain') == ''
    assert phase_rows(v2) == [('P001', 'CLOSED'), ('P002', 'ACTIVE')]
    assert v2.worker.run_once() is None


# --- confirmed document editing -----------------------------------------------------------------


def test_content_edit_commits_reviewed_bytes_regenerates_index_and_adopts(v2):
    pid = v2.create_v2()
    old = head(v2)
    decisions = text(v2, 'docs/DECISIONS.md') + '\n## D003 — Otra\n\n**Estado:** aceptada\n'
    duplicate = [{'path': 'docs/DECISIONS.md', 'content': decisions + '\n## D003 — Repetida\n'}]
    with pytest.raises(ValueError, match='Duplicate decision number'):
        edit_view(v2, changes=duplicate)
    changes = [{'path': 'docs/SPECIFICATION.md', 'content': '# Especificación\n\nNueva.\n'},
               {'path': 'docs/DECISIONS.md', 'content': decisions}]
    a, b = edit_view(v2, changes=changes), edit_view(v2, changes=changes)
    assert a == b and head(v2) == old and text(v2, 'docs/SPECIFICATION.md') != changes[0]['content']
    assert sorted(doc['path'] for doc in a['documents']) == ['docs/DECISIONS.md', 'docs/SPECIFICATION.md']
    shown = next(doc['content'] for doc in a['documents'] if doc['path'] == 'docs/DECISIONS.md')
    assert shown != decisions and shown.endswith('## D003 — Otra\n\n**Estado:** aceptada\n')
    job = queue_edit(v2, changes=changes, view=a, key='edit-once')
    assert queue_edit(v2, changes=changes, view=a, key='edit-once').id == job.id
    v2.run()
    assert git(v2.context.root, 'rev-parse', 'HEAD^') == old and git(v2.context.root, 'status', '--porcelain') == ''
    assert text(v2, 'docs/SPECIFICATION.md') == changes[0]['content']
    assert re.findall(r'^\| (D\d{3}) \|', blocks(text(v2, 'docs/DECISIONS.md'))['decisions'], re.M) == ['D001', 'D003']
    detail = v2.get(pid)
    assert detail['documents']['drift'] == [] and detail['operations'][-1]['kind'] == 'document_edit'
    assert detail['operations'][-1]['result']['adopted'] == {'docs/DECISIONS.md': text_hash(text(v2, 'docs/DECISIONS.md'))}
    assert v2.ports.roles() == []


def test_worktree_edit_confirms_exact_local_document_changes(v2):
    pid = v2.create_v2()
    edited = STATE.replace('Sin notas todavía.', 'Nota escrita en el editor.')
    v2.context.path('docs/STATE.md').write_text(edited, encoding='utf-8')
    v2.context.path('docs/phase').mkdir()
    v2.context.path('docs/phase/spike.md').write_text('# Spike\n', encoding='utf-8')
    view = edit_view(v2, 'worktree')
    assert [doc['path'] for doc in view['documents']] == ['docs/STATE.md', 'docs/phase/spike.md']
    assert view['documents'][0]['before_sha256'] == text_hash(STATE) and view['documents'][1]['before_sha256'] is None
    queue_edit(v2, 'worktree', view=view)
    v2.run()
    assert git(v2.context.root, 'status', '--porcelain') == '' and text(v2, 'docs/STATE.md') == edited
    assert git(v2.context.root, 'show', 'HEAD:docs/phase/spike.md') == '# Spike'
    assert v2.get(pid)['documents']['drift'] == []


EDIT_REFUSALS = {'outside': 'outside editable documents: app/main.txt', 'archive': 'outside editable documents',
                 'block': 'managed blocks are generated', 'deletion': 'Deleted files',
                 'new_marker': 'managed blocks are generated', 'clean': 'no local document changes'}


@pytest.mark.parametrize('case', sorted(EDIT_REFUSALS))
def test_worktree_edit_rejects_anything_but_editable_prose(v2, case):
    v2.create_v2()
    if case == 'outside':
        v2.context.path('docs/STATE.md').write_text(STATE + 'x\n')
        v2.context.path('app/main.txt').write_text('code change\n')
    elif case == 'archive':
        v2.context.path('docs/archive/phase-001').mkdir(parents=True)
        v2.context.path('docs/archive/phase-001/STATE.md').write_text('forged\n')
    elif case == 'block':
        v2.context.path('docs/STATE.md').write_text(STATE.replace(f'{STATE_BEGIN}\n', f'{STATE_BEGIN}\nforged\n'))
    elif case == 'deletion':
        v2.context.path('docs/SPECIFICATION.md').unlink()
    elif case == 'new_marker':
        v2.context.path('docs/SPECIFICATION.md').write_text(f'# S\n{ROAD_BEGIN}\n{ROAD_END}\n')
    before = head(v2)
    with pytest.raises(Conflict, match=EDIT_REFUSALS[case]):
        edit_view(v2, 'worktree')
    assert head(v2) == before


def test_content_edit_rejections_and_external_change_after_queue(v2):
    v2.create_v2()
    for changes, match in (([{'path': 'docs/archive/phase-001/STATE.md', 'content': 'x'}], 'not an editable'),
                           ([{'path': 'src/app.py', 'content': 'x'}], 'not an editable'),
                           ([{'path': '../outside.md', 'content': 'x'}], 'not an editable'),
                           ([{'path': 'docs/STATE.md', 'content': STATE.replace(STATE_END, 'forged\n' + STATE_END)}],
                            'managed blocks are generated'),
                           ([{'path': 'docs/SPECIFICATION.md', 'content': text(v2, 'docs/SPECIFICATION.md')}],
                            'nothing to commit'),
                           ([], 'at least one document')):
        with pytest.raises((Conflict, ValueError), match=match):
            edit_view(v2, changes=changes)
    changes = [{'path': 'docs/ARCHITECTURE.md', 'content': '# Arquitectura nueva\n'}]
    job = queue_edit(v2, changes=changes)
    v2.context.path('docs/ARCHITECTURE.md').write_text('external\n')
    before = head(v2)
    v2.run()
    assert text(v2, 'docs/ARCHITECTURE.md') == 'external\n' and head(v2) == before
    assert v2.repository.get_run(job.run_id).status == 'STOPPED'


def test_documents_status_reports_drift_changes_warnings_and_archive(v2):
    pid = v2.create_v2()
    status = editor(v2).status(v2.context, v2.ports.writer(v2.context, VERSIONS))
    assert status['phase']['code'] == 'P001' and status['uncommitted'] == [] and status['warnings'] == []
    # D088: `flows/` and `phase/` have no template; they exist when they are used.
    assert status['folders'] == [{'path': 'docs/flows', 'exists': False}, {'path': 'docs/phase', 'exists': False}]
    assert 'docs/DDBB-DIAGRAM.md' in [item['path'] for item in status['documents'] if item['kind'] == 'product']
    v2.context.path('docs/STATE.md').write_text(STATE.replace('Sin notas todavía.', 'x' * 30_000))
    v2.context.path('app/main.txt').write_text('code\n')
    status = editor(v2).status(v2.context, v2.ports.writer(v2.context, VERSIONS))
    state = next(item for item in status['documents'] if item['path'] == 'docs/STATE.md')
    assert state['drift'] is True and state['blocks'] == ['state'] and len(status['warnings']) == 1
    assert status['uncommitted'] == [{'path': 'app/main.txt', 'editable': False},
                                     {'path': 'docs/STATE.md', 'editable': True}]
    assert status['decisions'] == [{'id': 'D001', 'title': 'Usar Git como historial', 'status': 'aceptada',
                                    'file': 'DECISIONS.md', 'date': None, 'phase': None}]
    assert editor(v2).read(v2.context, 'docs/DECISIONS.md')['editable'] is True
    with pytest.raises(LookupError):
        editor(v2).read(v2.context, 'app/main.txt')
    with pytest.raises(ValueError, match='v2'):
        editor(v2).status(replace(v2.context, documents=None))
    assert pid


def test_http_documents_edit_without_retired_transition(v2, tmp_path):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
    pid = v2.create_v2()
    v2.accept()
    configuration = ManagedConfig((ManagedProject('synthetic', v2.context, VERSIONS),),
                                  ports_factory=v2.ports, commit_factory=v2.ports.writer, supervisor=False)
    with client(str(v2.repository.engine.url), tmp_path, configuration) as http:
        assert http.get('/api/managed/projects/synthetic').json()['documents'] == 'v2'
        status = http.get('/api/managed/projects/synthetic/documents')
        assert status.status_code == 200, status.text
        assert status.json()['phase']['code'] == 'P001'
        read = http.get('/api/managed/projects/synthetic/documents/content', params={'path': 'docs/ROADMAP.md'})
        assert read.status_code == 200 and read.json()['blocks'] == ['roadmap']
        assert http.get('/api/managed/projects/synthetic/documents/content',
                        params={'path': 'app/main.txt'}).status_code == 404
        body = {'source': 'content', 'changes': [{'path': 'README.md', 'content': '# Sintético\n\nLegible.\n'}]}
        preview = http.post('/api/managed/projects/synthetic/documents/edit/preview', json=body)
        assert preview.status_code == 200, preview.text
        create = {**body, 'preview_sha256': preview.json()['preview_sha256'], 'reason': 'HTTP edit', 'confirmed': True}
        assert http.post('/api/managed/projects/synthetic/documents/edit', json=create).status_code == 422
        queued = http.post('/api/managed/projects/synthetic/documents/edit', json=create,
                           headers={'Idempotency-Key': 'http-edit'})
        assert queued.status_code == 202, queued.text
        v2.run()
        assert http.get(f"/api/managed/runs/{queued.json()['run_id']}").json()['purpose'] == 'document_edit'
        assert text(v2, 'README.md') == '# Sintético\n\nLegible.\n'
        v2.check(pid, phase_review())
        v2.close(pid)
        phase = http.get(f'/api/managed/phases/{pid}').json()
        assert 'transition' not in phase['actions']  # only the recovery of old intentions is announced
        assert http.post(f'/api/managed/phases/{pid}/transition/preview', json={'next_steps': PLAN_P002}).status_code == 404
        assert http.post(f'/api/managed/phases/{pid}/transition', json={},
                         headers={'Idempotency-Key': 'retired'}).status_code == 404
        schema = http.app.openapi()['paths']
        assert '/api/managed/projects/{project_id}/documents' in schema
        assert not any('/transition' in path for path in schema)
        assert not any('/bootstrap/' in path for path in schema)
        assert set(schema['/api/managed/projects/{project_id}/bootstrap']) == {'get'}


def test_v1_projects_keep_their_behavior(repository, tmp_path):  # noqa: F811
    from test_phases import checkout as _checkout  # noqa: F401
    root = tmp_path / 'v1'
    (root / 'app').mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / 'app/main.txt').write_text('baseline\n')
    (root / 'docs/STATE.md').write_text('# State\n')
    (root / 'docs/NEXT_STEPS.md').write_text('# Next\n')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'baseline')
    world = World(repository, make_context(root))
    world.accept_task()
    assert git(root, 'show', '--stat', '--format=', 'HEAD').count('|') == 1  # only what was reviewed
    with pytest.raises(ValueError, match='v2'):
        editor(world).status(world.context)


def test_worktree_decision_edit_regenerates_index_in_the_same_commit(v2):
    pid = v2.create_v2()
    local = text(v2, 'docs/DECISIONS.md') + '\n## D004 — Desde el editor\n\n**Estado:** propuesta\n'
    v2.context.path('docs/DECISIONS.md').write_text(local)
    view = edit_view(v2, 'worktree')
    assert [doc['path'] for doc in view['documents']] == ['docs/DECISIONS.md']
    assert [item['path'] for item in view['regenerated']] == ['docs/DECISIONS.md']  # index over local bytes
    queue_edit(v2, 'worktree', view=view)
    v2.run()
    assert git(v2.context.root, 'status', '--porcelain') == ''
    index = blocks(text(v2, 'docs/DECISIONS.md'))['decisions']
    assert re.findall(r'^\| (D\d{3}) \|', index, re.M) == ['D001', 'D004'] and '| propuesta |' in index
    assert v2.get(pid)['documents']['drift'] == []


def test_d036_export_renders_v2_blocks_for_every_adopted_phase_document(v2):
    from my_harness.storage.document_export import DocumentExportRepository
    pid = v2.create_v2()
    v2.phases.raise_question(pid, v2.get(pid)['version'], text='¿Formato <b>final</b>?')
    exporter = DocumentExportRepository(v2.repository)
    writer = v2.ports.writer(v2.context, VERSIONS)
    view = exporter.preview(v2.context, pid, writer)
    assert view['snapshot']['layout'] == 'v2' and '```json' not in view['diff']
    assert [doc['path'] for doc in view['documents']] == list(LAYOUT.phase_documents)
    job = exporter.submit(v2.context, pid, view['expected_version'], key='v2-export', versions=VERSIONS,
                          preview_sha256=view['preview_sha256'], reason='Export v2 blocks', confirmed=True, git=writer)
    v2.run()
    assert v2.repository.get_run(job.run_id).status == 'COMMITTED'
    state = blocks(text(v2, 'docs/STATE.md'))['state']
    assert '- ¿Formato &lt;b&gt;final&lt;/b&gt;?' in state and '**Fase:** P001 · estado BLOCKED' in state
    assert '| P001 | Fundamentos | bloqueada | — |' in blocks(text(v2, 'docs/ROADMAP.md'))['roadmap']
    assert v2.get(pid)['documents']['drift'] == []
