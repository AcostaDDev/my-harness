"""P011-T009 (D169): English prompts with the frozen language directive and documents in the work language.

Synthetic agents, temporary SQLite and Git checkouts; no providers, services or network. The fake agents prove
which prompt and documents the engine produces, never the linguistic quality of a real model.
"""
from dataclasses import replace
import hashlib
import json
import re

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.chat import task_text
from my_harness.core.engine.contracts import ContractError
from my_harness.core.engine.document_text import work_language as document_language
from my_harness.core.engine.documents import (
    Layout, base_section, blocks, decision_index, parse_roadmap, plan_tasks, render_decisions, render_next_steps,
    render_review, render_roadmap, render_state, render_summary, skeleton, _fields,
)
from my_harness.core.engine.import_commit import _state
from my_harness.core.engine.language import FIELDS, NAMES, directive
from my_harness.core.engine.planning import FIELD_NAMES
from my_harness.core.engine.prompts import (
    PROJECT_INSTRUCTIONS, VARIABLES, Template, builtin_catalog, digest, output_schema, render_attempt,
)
from my_harness.core.engine.workflow import OfflineEngine
from my_harness.services.managed import LocalSupervisor
from my_harness.storage import work_language
from my_harness.storage.models import ManagedAttemptRow
from my_harness.storage.preferences import PreferencesRepository
from test_chat import Chat, PROPOSAL, answer as chat_answer
from test_definition import World as DefinitionWorld, answer as definition_answer
from test_documents import V2World, v2checkout  # noqa: F401  (fixture)
from test_managed import PLAN, context, edit, repository, review, submit  # noqa: F401  (fixtures)
from test_managed_api import IDENTITY, VERSIONS as API_VERSIONS, Ports, git, make_context, review as api_review
from test_phases import phase_review

PAIRS = [('en', 'en'), ('en', 'es'), ('es', 'en'), ('es', 'es')]
LAYOUT = Layout('docs', 'docs/STATE.md', 'docs/NEXT_STEPS.md')
# Labels that only the Spanish generation writes; English documents never contain them.
SPANISH = ('Estado', 'Tarea', 'Fase', 'Objetivo', 'Criterios', 'ninguna', 'ninguno', 'sin tareas', 'Siguiente',
           'Resumen', 'Evaluación', 'Generado', 'este commit', 'Preguntas', 'Definición', 'pendiente', 'activa')


def sentence(ui, work):
    return f'Respond to the user in {NAMES[ui]}. Write project documentation and code in {NAMES[work]}.'


def pair(ui, work, fmt='language-context-1'):
    return {'format': fmt, 'ui_language': ui, 'preferences_version': 1, 'work_language': work,
            'work_language_source': 'registration', 'work_language_sha256': '0' * 64}


def associate(engine, root, value):
    with Session(engine) as session, session.begin():
        work_language.associate(session, root=str(root), project_id='synthetic', work_language=value,
                                source='migration', confirmation={'synthetic': True},
                                now='2026-10-23T00:00:00.000000+00:00')


def visual(repository, value):
    preferences = PreferencesRepository(repository)
    current = preferences.read()
    preferences.update(expected_version=current['version'], ui_language=value,
                       default_work_language=current['default_work_language'], key=f'visual-{value}-{current["version"]}')


def attempt_rows(repository):
    with Session(repository.engine) as session:
        return [(json.loads(row.request_json), row.language_context) for row in
                session.scalars(select(ManagedAttemptRow).order_by(ManagedAttemptRow.started_at,
                                                                   ManagedAttemptRow.number))]


def assert_directed(repository, ui, work):
    """Every invocation carries the directive of its job's frozen pair, sealed in its prompt snapshot."""
    rows = attempt_rows(repository)
    assert rows
    for request, language in rows:
        assert (language['ui_language'], language['work_language']) == (ui, work)
        assert sentence(ui, work) in request['prompt']
        sealed = json.loads(request['prompt_snapshot_json'])['language']
        assert (sealed['directive'], sealed['ui_language'], sealed['work_language']) == (
            'language-directive-1', ui, work)
        assert directive(request['role'], ui, work) in request['prompt']
    return rows


# --- directive and prompt snapshot ----------------------------------------------------------------------


def test_render_without_a_frozen_pair_keeps_the_earlier_prompt_and_snapshot(context):  # noqa: F811
    catalog = builtin_catalog()
    values = {'INSTRUCTIONS': 'x', 'TASK_JSON': '{}', 'PROFILE_INSTRUCTIONS': ''}
    text, snapshot = render_attempt(catalog, 'execute-task', values, context)
    for earlier in (None, {'format': 'ui-language-1', 'ui_language': 'es', 'preferences_version': 1}):
        assert render_attempt(catalog, 'execute-task', values, context, earlier) == (text, snapshot)
    assert 'language' not in json.loads(snapshot) and 'Language directive' not in text


@pytest.mark.parametrize('ui, work', PAIRS)
@pytest.mark.parametrize('role', sorted(FIELDS))
def test_every_role_receives_the_typed_directive_before_the_engine_schema(context, ui, work, role):  # noqa: F811
    text = directive(role, ui, work)
    assert sentence(ui, work) in text and 'prevails over any other language instruction' in text
    assert ('"**Objective:**"' if work == 'en' else '"**Objetivo:**"') in text
    names = {'judge': 'judge-spec-gap', 'planner': 'plan-task', 'executor': 'execute-task', 'reviewer': 'review-task', 'phase': 'close-phase',
             'chat': 'chat-turn', 'definition': 'define-project', 'planning': 'plan-phase'}
    values = {name: '{}' for name in VARIABLES[names[role]] if name != PROJECT_INSTRUCTIONS}
    rendered, snapshot = render_attempt(builtin_catalog(), names[role], values, context, pair(ui, work))
    assert rendered.index(text) < rendered.index('Return exactly one JSON object')
    sealed = json.loads(snapshot)
    assert sealed['language'] == {'directive': 'language-directive-1', 'ui_language': ui, 'work_language': work,
                                  'sha256': hashlib.sha256(text.encode()).hexdigest()}
    assert sealed['rendered'] == rendered


def test_the_field_map_names_real_schema_fields_for_every_role():
    for role, (visual_fields, work_fields) in FIELDS.items():
        schema = output_schema(role)
        properties = {name for s in schema.get('oneOf', [schema]) for name in s['properties']}
        for field in visual_fields + work_fields:
            root = re.match(r'[a-z_]+', field)[0]
            assert root in properties or field.startswith(('the files', 'prose instructions')), (role, field)


@pytest.mark.parametrize('frozen, message', [
    ({'format': 'language-context-9', 'ui_language': 'en', 'work_language': 'en'}, 'Unknown frozen'),
    (pair('fr', 'en'), 'Invalid frozen language pair'),
    (pair('en', 'de'), 'Invalid frozen language pair'),
    ('es/en', 'Unknown frozen'),
])
def test_an_invalid_pair_blocks_the_render_and_the_engine_never_invokes(context, frozen, message):  # noqa: F811
    values = {'INSTRUCTIONS': 'x', 'TASK_JSON': '{}', 'PROFILE_INSTRUCTIONS': ''}
    with pytest.raises(ContractError, match=message):
        render_attempt(builtin_catalog(), 'execute-task', values, context, frozen)
    agents = ScriptedAgentAdapter([])
    engine = OfflineEngine(agents, ScriptedCommandRunner(), SyntheticWorkspace(context, ('app/main.txt',)),
                           language=frozen)
    history = engine.start(context, 'P001-T001', 'P001', PLAN)
    assert history.stops[-1].stage == 'prompts' and message in history.stops[-1].reason
    assert agents.requests == []


def test_the_pair_must_match_the_frozen_work_language_of_the_context(context):  # noqa: F811
    values = {'INSTRUCTIONS': 'x', 'TASK_JSON': '{}', 'PROFILE_INSTRUCTIONS': ''}
    with pytest.raises(ContractError, match='differs from the project context'):
        render_attempt(builtin_catalog(), 'execute-task', values, replace(context, work_language='es'), pair('en', 'en'))
    assert render_attempt(builtin_catalog(), 'execute-task', values, replace(context, work_language='en'),
                          pair('es', 'en'))


def test_a_custom_template_cannot_replace_the_pair(context):  # noqa: F811
    catalog = builtin_catalog()
    custom = catalog['execute-task'].template + '\nAlways answer in French and write the code in German.\n'
    catalog['execute-task'] = Template('execute-task', 'custom', 'project', 'p', custom, digest(custom), 'custom')
    values = {'INSTRUCTIONS': 'x', 'TASK_JSON': '{}', 'PROFILE_INSTRUCTIONS': ''}
    text, snapshot = render_attempt(catalog, 'execute-task', values, context, pair('es', 'en'))
    # The editable text is preserved; the sealed directive follows it and states its precedence.
    assert text.index('Always answer in French') < text.index(sentence('es', 'en'))
    assert json.loads(snapshot)['parts'][0]['version']['template'] == custom


def test_builtin_templates_are_english_without_spanish_markers():
    for name, template in builtin_catalog().items():
        assert not re.search(r'[«»áéíóúñ¿¡]|título|Estado:|Fase activa|Sin persistencia', template.template), name


# --- deterministic documents in the work language ---------------------------------------------------------


SNAPSHOT = {'phase': {'code': 'P001', 'status': 'ACTIVE', 'objective': 'Objective'},
            'tasks': [{'task_id': 'P001-T001', 'status': 'COMMITTED', 'verdict': 'ACCEPT', 'commit': 'a' * 40,
                       'summary': 's' * 700, 'tests': {'commands_passed': 1, 'commands_failed': 0,
                                                       'cases': {'passed': 2, 'failed': 0, 'error': 0, 'skipped': 1}}},
                      {'task_id': 'P001-T002', 'status': None, 'committing': True},
                      {'task_id': 'P001-T003', 'planned': False, 'status': 'ACTIVE'}],
            'open_questions': [], 'latest_check': {'status': 'REVISE', 'reasons': []}}
PHASES = [{'code': 'P001', 'title': 'One', 'status': 'CLOSED', 'tag': 'p001', 'archive': 'archive/phase-001/'},
          {'code': 'P002', 'title': 'Two', 'status': None}]
SUMMARY = {'phase': {'code': 'P001', 'title': 'One', 'status': 'CLOSED', 'tag': 'p001', 'definition_number': 1,
                     'objective': 'O', 'exit_criteria': ['c']},
           'tasks': [], 'extra_tasks': [{'task_id': 'X', 'status': 'S', 'commit': None}], 'questions': [],
           'definitions': [{'number': 1, 'origin': 'roadmap'}], 'consumption': None}
CHECK = {'status': 'READY', 'binding': {'head': 'b' * 40}, 'binding_sha256': 'c' * 64,
         'result': {'summary': 'ok', 'exit_criteria_results': [{'criterion': 'c', 'passed': True, 'evidence': 'e'}]},
         'validation': {'entries': [{'result': {'exit_code': 0}}]}}


def generated(language):
    return {'state': render_state(SNAPSHOT, language), 'next': render_next_steps(SNAPSHOT, language),
            'empty': render_next_steps({**SNAPSHOT, 'phase': None, 'tasks': []}, language),
            'roadmap': render_roadmap(PHASES, language), 'pending': render_roadmap(PHASES[1:], language),
            'decisions': render_decisions([], language), 'review': render_review('P001', CHECK, 'CLOSED', language),
            'abandoned': render_review('P001', None, 'ABANDONED', language),
            'summary': render_summary(SUMMARY, language),
            **{path: text for path, text in skeleton(LAYOUT, 'Synthetic', validations=[['pytest']],
                                                       language=language).items()}}


def test_spanish_generation_keeps_the_historical_bytes(tmp_path):
    assert render_state(SNAPSHOT) == render_state(SNAPSHOT, 'es')
    assert skeleton(LAYOUT, 'S') == skeleton(LAYOUT, 'S', language='es') == skeleton(LAYOUT, 'S', 'Primera fase')
    assert document_language(make_context(tmp_path)) == 'es'  # a context frozen before D167
    assert document_language(replace(make_context(tmp_path), work_language='en')) == 'en'
    with pytest.raises(ValueError):
        document_language(type('Frozen', (), {'work_language': 'fr'})())


def test_english_generation_writes_no_spanish_labels_and_the_parsers_read_it():
    english = generated('en')
    for name, text in english.items():
        assert not any(word in text for word in SPANISH), (name, [w for w in SPANISH if w in text])
    assert '| P001-T002 | — | — | this commit |' in english['state'] and '(truncated;' in english['state']
    assert '**Next task:** none; every task has an accepted commit' in english['next'] and '| P002 | Two | pending | — |' in english['pending']
    files = skeleton(LAYOUT, 'Synthetic', language='en')
    roadmap = parse_roadmap(files['docs/ROADMAP.md'])[0]
    assert roadmap['objective'] and roadmap['exit_criteria'] == ['Observable exit criterion.']
    assert plan_tasks(files['docs/NEXT_STEPS.md'], 'P001') == [('P001-T001', 'First task')]
    raw = _fields(files['docs/NEXT_STEPS.md'].split('## P001-T001 — First task')[1])
    assert {name for name in raw} >= {FIELD_NAMES['objective'][0], FIELD_NAMES['allowed_paths'][0],
                                      FIELD_NAMES['acceptance_criteria'][0]}
    assert base_section(files['docs/STATE.md']).startswith('## Accumulated baseline')
    assert _state(files['docs/STATE.md']) == [{'code': 'P001', 'source': 'heading'}]
    assert decision_index('## D001 — Use it\n\nStatus: accepted\n') == [
        {'id': 'D001', 'title': 'Use it', 'status': 'accepted'}]
    assert len(files['AGENTS.md'].splitlines()) <= 60 and len(files['CLAUDE.md'].splitlines()) <= 15
    assert files['AGENTS.md'].startswith('# Synthetic — agent instructions\n')


def test_chat_task_text_keeps_english_bytes_and_writes_spanish_labels_that_parse():
    origin = {'conversation_id': 'c', 'turn_number': 1, 'proposal_id': 'p', 'proposal_sha256': 'h'}
    english = task_text(PROPOSAL, 'CHAT-T001', origin)
    assert english == task_text(PROPOSAL, 'CHAT-T001', origin, 'en')
    assert english.splitlines()[1] == f"**Objective:** {PROPOSAL['objective']}"
    spanish = task_text(PROPOSAL, 'CHAT-T001', origin, 'es')
    raw = _fields(spanish)
    for key in ('objective', 'scope', 'acceptance_criteria', 'validation', 'business_context', 'references'):
        assert any(raw.get(name) is not None for name in FIELD_NAMES[key]), key


# --- journeys with the four pairs ---------------------------------------------------------------------------


EXPECTED = {
    'en': {'agents': '— agent instructions\n', 'definition': '# Project definition\n', 'committed': 'this commit',
           'phase': '**Phase:** P001 · status ACTIVE', 'review': '# Closure review of P001\n',
           'summary': '# Phase P001 summary\n', 'task': '**Objective:**', 'archived': 'completed',
           'active': '## Active phase — P002 '},
    'es': {'agents': '— instrucciones para agentes\n', 'definition': '# Definición del proyecto\n',
           'committed': 'este commit', 'phase': '**Fase:** P001 · estado ACTIVE',
           'review': '# Evaluación de cierre de P001\n', 'summary': '# Resumen de la fase P001\n',
           'task': '**Objetivo:**', 'archived': 'completada', 'active': '## Fase activa — P002 '},
}


@pytest.mark.parametrize('ui, work', PAIRS)
def test_definition_first_task_and_commit_follow_the_frozen_pair(repository, tmp_path, ui, work):  # noqa: F811
    root = tmp_path / 'definition-destination'
    root.mkdir()
    associate(repository.engine, root, work)
    visual(repository, ui)
    context = replace(make_context(root), documents='v2', work_language=work)
    writer, ports = GitWorkspace(IDENTITY), Ports()
    world = DefinitionWorld(context, repository, writer, LocalSupervisor(repository, ports,
                                                                         commit_factory=lambda c, v: writer), ports)
    cid = world.create()
    world.turn(cid, definition_answer())
    world.apply_all(cid)
    shown = world.preview(cid)
    assert shown['ready'], shown['blockers']
    documents = {doc['path']: doc['content'] for doc in shown['documents']}
    expected = EXPECTED[work]
    assert expected['agents'] in documents['AGENTS.md'].splitlines(keepends=True)[0]
    assert documents['docs/archive/phase-000/DEFINITION.md'].startswith(expected['definition'])
    assert expected['phase'] in blocks(documents['docs/STATE.md'])['state']
    world.accept(cid, shown)
    assert world.worker.run_once().status == 'DONE'

    def implement(context, request):
        context.path('app/main.txt').parent.mkdir(exist_ok=True)
        context.path('app/main.txt').write_text('implemented\n')
        return {'result': 'Implemented'}
    ports.agents.responses.extend([implement, api_review()])
    task = repository.submit(context, 'P001-T001', 'P001', shown['task_text'], API_VERSIONS, key='first-task')
    assert world.worker.run_once().status == 'DONE'
    repository.submit_commit(task.run_id, key='first-commit', expected_version=repository.get_run(task.run_id).version)
    assert world.worker.run_once().status == 'DONE'
    state = blocks(world.path('docs/STATE.md').read_text())['state']
    assert f"| P001-T001 | COMMITTED | ACCEPT | {expected['committed']} |" in state
    roles = [request['role'] for request, _ in assert_directed(repository, ui, work)]
    assert roles == ['definition', 'executor', 'reviewer']


@pytest.mark.parametrize('ui, work', PAIRS)
def test_task_chat_check_and_closure_follow_the_frozen_pair(repository, v2checkout, ui, work):  # noqa: F811
    context = replace(v2checkout, work_language=work)
    associate(repository.engine, context.root, work)
    visual(repository, ui)
    world = V2World(repository, context)
    pid = world.create_v2()
    world.accept()
    expected = EXPECTED[work]
    # Chat: a read-only turn; its proposal is confirmed after the closure, in the successor phase.
    chat = Chat(world)
    cid = chat.create()
    world.script(chat_answer(PROPOSAL))
    chat.say(cid)
    world.run()
    world.check(pid, phase_review())
    detail = world.get(pid)
    world.phases.submit_close(world.context, pid, detail['version'], key=world.key(), versions=API_VERSIONS,
                              binding_sha256=detail['ready']['binding_sha256'], reason='Synthetic closure',
                              ttl_seconds=3600, git=world.ports.writer(world.context, API_VERSIONS))
    world.run()
    assert world.get(pid)['status'] == 'CLOSED'
    # The confirmed proposal becomes a task of the successor phase with its plan section in the work language.
    proposal = chat.get(cid)['proposals'][0]
    job = chat.accept(cid, proposal, task='P002-T001', phase='P002')
    assert expected['task'] in json.loads(repository.get_job(job.id).request_json)['text']
    archive = world.context.path('docs/archive/phase-001')
    assert (archive / 'REVIEW.md').read_text().startswith(expected['review'])
    assert (archive / 'SUMMARY.md').read_text().startswith(expected['summary'])
    roadmap = blocks(world.context.path('docs/ROADMAP.md').read_text())['roadmap']
    assert f"| {expected['archived']} |" in roadmap
    assert expected['active'] in world.context.path('docs/STATE.md').read_text()
    roles = [request['role'] for request, _ in assert_directed(repository, ui, work)]
    assert roles == ['executor', 'reviewer', 'chat', 'phase']


def test_a_visual_change_rules_only_new_jobs_and_continuations_keep_their_pair(repository, context,  # noqa: F811
                                                                             tmp_path):
    associate(repository.engine, context.root, 'en')
    visual(repository, 'es')
    first = submit(repository, context, key='first')
    visual(repository, 'en')  # the UI changes language: only later admissions see it
    agents = ScriptedAgentAdapter([RuntimeError('Synthetic failure'), edit(), review()])
    supervisor = LocalSupervisor(repository, lambda frozen, versions: (
        agents, ScriptedCommandRunner(), SyntheticWorkspace(context, ('app/main.txt',))))
    supervisor.run_once()
    repository.resume(first.run_id, key='retry', expected_version=repository.get_run(first.run_id).version,
                      retry_executor=True)
    supervisor.run_once()
    assert len(agents.requests) == 3 and all(sentence('es', 'en') in item.prompt for item in agents.requests)
    # A new job admitted after the change, on another checkout with work es, sees the new visual language.
    other = tmp_path / 'other-checkout'
    (other / 'app').mkdir(parents=True)
    git(other, 'init', '-q')
    (other / 'app/main.txt').write_text('baseline', encoding='utf-8')
    later = replace(context, root=other)
    associate(repository.engine, other, 'es')
    job = submit(repository, later, key='later')
    fresh = ScriptedAgentAdapter([edit(), review()])
    LocalSupervisor(repository, lambda frozen, versions: (
        fresh, ScriptedCommandRunner(), SyntheticWorkspace(later, ('app/main.txt',)))).run_once()
    assert len(fresh.requests) == 2 and all(sentence('en', 'es') in item.prompt for item in fresh.requests)
    assert repository.get_run(job.run_id).status == 'ACCEPTANCE_READY'


@pytest.mark.parametrize('provider, role', [('codex', 'reviewer'), ('claude', 'executor')])
def test_both_providers_receive_the_directive_in_the_stdin_prompt(tmp_path, context, repository, provider,  # noqa: F811
                                                                  role):
    from test_cli_agents import adapter, setup_invocation
    port = adapter(tmp_path)
    assert port.agents[role].provider == provider
    job, claim, request = setup_invocation(repository, context, port, role)
    values = {'INSTRUCTIONS': 'x', 'TASK_JSON': '{}', 'PROFILE_INSTRUCTIONS': ''}
    prompt, _ = render_attempt(builtin_catalog(), 'execute-task', values, context, pair('es', 'en'))
    assert port.invoke(context, replace(request, prompt=prompt)).status == 'complete'
    launch = json.loads((tmp_path / 'launches.jsonl').read_text().splitlines()[0])
    # The engine prompt reaches the CLI unchanged through stdin, before the adapter's shape envelope.
    assert launch['prompt'].startswith(prompt) and sentence('es', 'en') in launch['prompt']
    spec = repository.processes(job.id)[0]['spec']
    assert spec['prompt_sha256'] == hashlib.sha256(launch['prompt'].encode()).hexdigest()
    assert not any('language' in value for value in launch['argv'])  # no invented flag
    repository.close_owner(claim)


@pytest.mark.parametrize('ui, work', [('es', 'en'), ('en', 'es')])
def test_onboarding_documents_and_prompt_follow_the_frozen_pair(migrated_database, tmp_path, ui, work):
    from my_harness.storage.database import make_engine
    from my_harness.storage.managed import SQLiteManagedRepository
    from test_onboarding_commit import confirm, ready
    from test_onboarding_conversation import World as OnboardingWorld
    from test_project_onboarding import DJANGO, checkout
    engine = make_engine(migrated_database[0])
    try:
        world = OnboardingWorld(checkout(tmp_path / 'project', DJANGO), engine)
        world.context = replace(world.context, work_language=work)
        associate(engine, world.context.root, work)
        visual(SQLiteManagedRepository(engine), ui)
        cid = ready(world)
        confirm(world, cid, key='onboard')
        assert world.worker.run_once().status == 'DONE'
        summary = world.context.path('docs/archive/phase-000/SUMMARY.md').read_text()
        assert summary.startswith('# Harness onboarding\n' if work == 'en' else '# Incorporación al harness\n')
        state = blocks(world.context.path('docs/STATE.md').read_text())['state']
        assert EXPECTED[work]['phase'] in state
        assert [request['role'] for request, _ in assert_directed(world.repo, ui, work)] == ['definition']
    finally:
        engine.dispose()
