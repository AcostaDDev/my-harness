"""P002-T020 (D304, D306, D309, D311): work-map and trace read projections over synthetic projects only.

The world is built by the real writers (knowledge adoption, structured phase plan, task run with executor, reviewer,
validation and commit, phase check, owner question) plus synthetic in-flight attempts written as the supervisor
would persist them (attempt without a result, PENDING/RUNNING process, ledger row) for lane concurrency. Nothing
calls a provider, a real agent or the network.
"""
from contextlib import closing
import os
import re
from hashlib import sha256
import json
import sqlite3
import uuid

from fastapi.testclient import TestClient as AnonymousClient
import pytest
from sqlalchemy import text

from my_harness.api.app import create_app
from my_harness.core.engine import work_map as wm
from my_harness.services.managed_runtime import ManagedConfig
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.knowledge import KnowledgeRepository
from my_harness.storage.observed_steps import ObservedStepProjector
from session_client import TestClient
from test_managed import context, repository  # noqa: F401
from test_managed_api import LOCAL, client, config
from test_git import repo as git_repo  # noqa: F401  (fixture)
from test_structured_phases import prepared, structured  # noqa: F401

MAP = '/api/managed/map'
CSRF = {'X-My-Harness': '1'}
SECRET = 'sk-synthetic012345678901234567890'
NOW = '2026-11-05T10:00:00.000000+00:00'


def get(http, path, status=200, **params):
    response = http.get(MAP + path, params=params)
    assert response.status_code == status, (path, response.text)
    return response.json()


def pages(http, path, key='items', **params):
    """Every page of a level, following `next_cursor`; returns the items in order and the page count."""
    items, cursor, count = [], None, 0
    while True:
        data = get(http, path, **params, **({'cursor': cursor} if cursor else {}))
        items += data[key]
        count += 1
        cursor = data['next_cursor']
        if cursor is None:
            return items, count, data


def inflight(engine, run_id, *, role, purpose_role=None, process='RUNNING', number=None, at=NOW):
    """An attempt in flight as the supervisor persists it: no result, a PENDING/RUNNING process, its ledger row."""
    attempt = str(uuid.uuid4())
    with engine.begin() as db:
        run = db.execute(text('SELECT root, phase_id, task_id, purpose FROM managed_runs WHERE id = :id'),
                         {'id': run_id}).mappings().one()
        job = db.scalar(text('SELECT id FROM managed_jobs WHERE run_id = :id ORDER BY id DESC LIMIT 1'), {'id': run_id})
        number = number or (db.scalar(text('SELECT coalesce(max(number), 0) FROM managed_attempts WHERE run_id = :id'),
                                      {'id': run_id}) + 1)
        db.execute(text("""INSERT INTO managed_attempts (id, run_id, number, request_json, versions_json, status,
            started_at) VALUES (:id, :run, :n, :req, '{}', 'ACTIVE', :at)"""),
            {'id': attempt, 'run': run_id, 'n': number, 'req': json.dumps({'role': role}), 'at': at})
        db.execute(text("""INSERT INTO managed_processes (id, attempt_id, job_id, spec, status)
            VALUES (:id, :id, :job, :spec, :status)"""),
            {'id': attempt, 'job': job, 'spec': json.dumps({'provider': 'codex'}), 'status': process})
        db.execute(text("""INSERT INTO usage_invocations (id, source_kind, source_id, attempt_id, run_id, root, phase_code,
            task_id, purpose, role, agent, requested_model, requested_effort, versions, launch, started_at, recorded_at,
            updated_at) VALUES (:id, 'managed_attempt', :a, :a, :run, :root, :phase, :task, :purpose, :role, 'codex',
            'synthetic-model', 'medium', '{}', 'pending', :at, :at, :at)"""),
            {'id': 'inv-' + attempt, 'a': attempt, 'run': run_id, 'root': run['root'], 'phase': run['phase_id'],
             'task': run['task_id'], 'purpose': run['purpose'], 'role': purpose_role or role, 'at': at})
    return attempt


def chat_run(engine, root, phase_id):
    """A chat turn's run on the phase conversation, as the chat service queues it."""
    run, conversation = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as db:
        db.execute(text("""INSERT INTO managed_runs (id, root, task_id, phase_id, context_json, versions_json,
            history_json, status, stage, revisions, revision_limit, version, created_at, updated_at, purpose)
            VALUES (:id, :root, 'CHAT', 'CHAT', '{}', '{}', '{}', 'ANSWERING', 'chat', 0, 0, 1, :at, :at, 'chat')"""),
            {'id': run, 'root': root, 'at': NOW})
        db.execute(text("""INSERT INTO managed_jobs (idempotency_key, run_id, request_json, status, created_at)
            VALUES (:key, :run, '{"action": "chat"}', 'ACTIVE', :at)"""), {'key': 'chat-' + run, 'run': run, 'at': NOW})
        db.execute(text("""INSERT INTO chat_conversations (id, root, title, phase_id, actor, version, created_at,
            updated_at) VALUES (:id, :root, 'Synthetic', :phase, '{}', 1, :at, :at)"""),
            {'id': conversation, 'root': root, 'phase': phase_id, 'at': NOW})
        db.execute(text("""INSERT INTO chat_turns (id, conversation_id, number, run_id, status, message, request,
            request_sha256, actor, created_at) VALUES (:id, :c, 1, :run, 'QUEUED', :m, '{}', :sha, '{}', :at)"""),
            {'id': str(uuid.uuid4()), 'c': conversation, 'run': run, 'm': f'Private chat text {SECRET}',
             'sha': '0' * 64, 'at': NOW})
    return run


def table_marks(path):
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {name: db.execute(f'SELECT count(*), max(rowid) FROM "{name}"').fetchone() for name in names
                if name != 'sqlite_sequence'}


@pytest.fixture
def world(structured, migrated_database):
    w = structured
    pid = prepared(w)
    w.phase_id = pid
    ObservedStepProjector(w.repository.engine).run_pending()
    w.url = migrated_database[0]
    return w


def test_levels_project_real_sources_with_attribution_concurrency_and_parity(world, tmp_path):
    w = world
    engine = w.repository.engine
    with engine.connect() as db:
        task_run = db.scalar(text("SELECT id FROM managed_runs WHERE purpose = 'task' AND root = :r"),
                             {'r': str(w.context.root)})
        check_run = db.scalar(text("SELECT run_id FROM phase_operations WHERE kind = 'check'"))
    managed = config(w.context, w.ports, supervisor=False)
    with client(w.url, tmp_path, managed) as http:
        [card] = get(http, '/projects')['items']
        assert card['id'] == w.project and card['registered_project_id'] == 'synthetic'
        assert card['knowledge_project_id'] == w.project and card['configuration_source'] == 'supplied'
        assert card['active_phase']['code'] == 'P001' and card['active_phase']['status'] == {
            'code': 'READY_TO_CLOSE', 'class': 'waiting'}
        # P001 open and P002 roadmap identity; nothing closed yet.
        assert card['phases'] == {'value': 0, 'source': 'derived', 'reason': None, 'total': 2,
                                  'meaning': 'phases closed / total'}
        assert card['status']['class'] == 'waiting'  # the READY confirmation waits for the owner (bubble on H)
        assert card['bubbles']['by_kind'] == {'lifecycle': 1} and card['bubbles']['by_circle'] == {'H': 1}
        assert {c['circle'] for c in card['circles']} == {'R', 'E', 'H'}  # no judge profile, no judge invocation
        assert not any(c['active'] for c in card['circles']) and card['active_invocations'] == []

        phases = get(http, f"/projects/{w.project}/phases")
        p1, p2 = phases['items']
        assert [p1['code'], p2['code']] == ['P001', 'P002'] and phases['edges'] == [
            {'kind': 'roadmap_order', 'source': 'P001', 'target': 'P002'}]
        assert p1['tasks'] == {'value': 1, 'source': 'derived', 'reason': None, 'total': 1,
                               'meaning': 'tasks committed / total'}
        assert p1['ready'] and p1['last_check']['status'] == {'code': 'READY', 'class': 'done'}
        assert p1['slots']['check']['run_id'] == check_run and p1['slots']['close'] is None
        assert [a['circle'] for a in p1['slots']['check']['actors']] == ['R']  # the reviewer actually took part
        assert p2['origin'] == 'roadmap' and p2['instance'] is None
        assert p2['status'] == {'code': 'planned', 'class': 'pending'}
        assert p2['tasks'] == {'value': None, 'source': 'absent', 'reason': 'no_tasks', 'total': None,
                               'meaning': 'tasks committed / total'}
        assert p1['bubbles']['items'][0]['topic'] == 'phase_ready' and p1['bubbles']['items'][0]['circle'] == 'H'

        tasks = get(http, f"/projects/{w.project}/phases/P001/tasks")
        [node] = tasks['items']
        assert node['code'] == 'P001-T001' and node['in_plan'] and node['identity']['status']['code'] == 'planned'
        assert node['status'] == {'code': 'COMMITTED', 'class': 'done'} and node['latest']['run_id'] == task_run
        assert node['latest']['commit']['status']['code'] == 'COMMITTED'
        assert node['latest']['acceptance'] == {'state': 'eligible', 'eligible': True, 'reasons': [],
                                                'source': 'derived', 'reason': None}
        # Inspector texts of the accepted identity, with their source; the plan task has them.
        assert node['problem']['value'] and node['problem']['source'] == 'supplied'
        assert node['expected_result']['value'] and not node['expected_result']['truncated']
        assert node['latest']['attempts']['value'] == 1 and node['latest']['attempts']['revision_limit'] >= 1

        runs = get(http, f"/projects/{w.project}/phases/P001/tasks/P001-T001/runs")
        assert [r['run_id'] for r in runs['items']] == [task_run] and runs['latest_run_id'] == task_run

        steps = get(http, f"/projects/{w.project}/runs/{task_run}/steps")
        sequence = [(s['kind'], s.get('role') or s.get('stage')) for s in steps['items']]
        assert sequence[:2] == [('invocation', 'executor'), ('harness', 'format')]
        assert ('harness', 'validate') in sequence and sequence[-1] == ('harness', 'commit')
        assert sequence.index(('harness', 'validate')) < sequence.index(('invocation', 'reviewer'))
        executor = steps['items'][0]
        assert executor['circle'] == 'E' and executor['harness_attempt'] == {'value': 1, 'source': 'supplied', 'reason': None}
        assert executor['revision_round']['value'] == 1
        # Fake ports spawn no process: termination and duration are absent, never invented.
        assert executor['duration_ms']['source'] == 'absent'
        assert executor['reported_model']['source'] == 'absent'
        assert executor['identity']['requested_model'] is not None and executor['identity']['source'] == 'supplied'
        assert all(s['circle'] == 'H' for s in steps['items'] if s['kind'] == 'harness')
        assert executor['steps']['state'] == 'sealed'

        invocation = executor['invocation_id']
        head = get(http, f"/projects/{w.project}/invocations/{invocation}")
        assert head['owner']['lane'] == 'task' and [c['level'] for c in head['owner']['breadcrumb']] == [
            'project', 'phase', 'task', 'run', 'invocation']
        assert head['owner']['breadcrumb'][-1]['ordinal'] == 1 and head['steps']['state'] == 'sealed'
        assert head['evidence']['run_events'] == f'/api/managed/runs/{task_run}/events'
        trace, count, last = pages(http, f"/projects/{w.project}/invocations/{invocation}/steps")
        assert last['state'] == 'sealed' and trace and trace[0]['kind'] == 'not_observed'  # scripted agent: no stream
        assert all('source_record' not in s for s in trace)
        related = get(http, f"/projects/{w.project}/invocations/{invocation}/related", group='records')
        assert all(item['kind'] in ('knowledge.delivered', 'knowledge.receipt', 'tool.discovered', 'broker.called',
                                    'broker.result', 'tool.called', 'tool.result', 'judge.requested', 'judge.ruled',
                                    'context.intended', 'invocation.observed') for item in related['items'])
        assert get(http, f"/projects/{w.project}/invocations/{invocation}/related", group='permissions')['items'] == []

        # Check lane: a phase operation without a task, navigable from its own owner context.
        check_steps = get(http, f"/projects/{w.project}/runs/{check_run}/steps")['items']
        reviewer = next(s for s in check_steps if s['kind'] == 'invocation')
        owner = get(http, f"/projects/{w.project}/invocations/{reviewer['invocation_id']}")['owner']
        assert owner['lane'] == 'phase_operation' and owner['phase'] == 'P001'
        assert owner['phase_operation']['kind'] == 'check'

        # Concurrent lanes: an executor on a task run and a reviewer chat on the phase conversation at once.
        before = get(http, '/projects')
        idle = http.get(MAP + '/activity', params={'scope': [before['scope'], phases['scope']]})
        assert idle.status_code == 200 and len(idle.content) <= 8 * 1024 and not idle.json()['active']
        executor_attempt = inflight(engine, task_run, role='executor')
        chat = chat_run(engine, str(w.context.root), w.phase_id)
        chat_attempt = inflight(engine, chat, role='chat', process='PENDING')
        poll = get(http, '/activity', scope=[before['scope'], phases['scope']])
        assert poll['active'] and {s['scope'] for s in poll['scopes']} == {before['scope'], phases['scope']}
        assert all(s['version'] != v for s, v in zip(poll['scopes'], (before['version'], phases['version'])))
        lanes = {a['attempt_id']: a for a in poll['active_invocations']}
        assert lanes[executor_attempt]['circle'] == 'E' and not lanes[executor_attempt]['chat']
        assert lanes[chat_attempt]['circle'] == 'R' and lanes[chat_attempt]['chat']
        assert lanes[chat_attempt]['scope']['phase'] == 'P001' and lanes[chat_attempt]['project_id'] == w.project
        [card] = get(http, '/projects')['items']
        lit = {c['circle']: c for c in card['circles']}
        assert lit['E']['active'] and lit['R']['active'] and lit['R']['chat'] and not lit['H']['active']
        assert card['status']['class'] == 'waiting'  # an owner wait outranks work in progress (§5.2)
        p1 = get(http, f"/projects/{w.project}/phases")['items'][0]
        assert {a['attempt_id'] for a in p1['active_invocations']} == {executor_attempt, chat_attempt}
        [node] = get(http, f"/projects/{w.project}/phases/P001/tasks")['items']
        assert [a['attempt_id'] for a in node['active_invocations']] == [executor_attempt]
        running = get(http, f"/projects/{w.project}/runs/{task_run}/steps")['items']
        flight = next(s for s in running if s.get('attempt_id') == executor_attempt)
        assert flight['active'] and flight['status'] == {'code': 'RUNNING', 'class': 'progress', 'process': 'RUNNING'}
        assert flight['steps']['state'] == 'not_settled' and flight['label'] == {'role': 'executor', 'ordinal': 2}
        assert flight['revision_round']['value'] == 2

        # An owner question blocks the phase: a failed class with its raw code; the question has no agent origin.
        w.phases.raise_question(w.phase_id, w.get(w.phase_id)['version'], text=f'Which output is intended? {SECRET}')
        [card] = get(http, '/projects')['items']
        assert card['status']['class'] == 'failed' and card['errors'][0] == {
            'kind': 'phase', 'id': 'P001', 'status': {'code': 'BLOCKED', 'class': 'failed'}}
        assert card['bubbles']['by_kind'] == {'question': 1} and card['bubbles']['unattributed'] == 1

        dump = json.dumps([get(http, '/projects'), get(http, f"/projects/{w.project}/phases"),
                           get(http, f"/projects/{w.project}/phases/P001/tasks"),
                           get(http, f"/projects/{w.project}/runs/{task_run}/steps"),
                           get(http, f"/projects/{w.project}/runs/{chat}/steps"), head, trace, related,
                           get(http, '/activity', scope=[before['scope']])])
        assert SECRET not in dump and 'Private chat text' not in dump and 'Which output' not in dump
        assert 'history_json' not in dump and str(w.context.root) not in dump


def strip(value):
    """Responses minus what legitimately differs between ordinary and archive service: composition and tokens."""
    if isinstance(value, dict):
        return {k: strip(v) for k, v in value.items()
                if k not in ('read_only_archive', 'configuration', 'configuration_source', 'registered_project_id',
                             'version', 'next_cursor', 'name', 'name_source', 'project', 'scope', 'scopes')}
    if isinstance(value, list):
        return [strip(v) for v in value]
    return value


def snapshot(http, project, run, invocation):
    return {'projects': get(http, '/projects'), 'phases': get(http, f'/projects/{project}/phases'),
            'tasks': get(http, f'/projects/{project}/phases/P001/tasks'),
            'runs': get(http, f'/projects/{project}/phases/P001/tasks/P001-T001/runs'),
            'steps': get(http, f'/projects/{project}/runs/{run}/steps'),
            'invocation': get(http, f'/projects/{project}/invocations/{invocation}'),
            'trace': get(http, f'/projects/{project}/invocations/{invocation}/steps'),
            'records': get(http, f'/projects/{project}/invocations/{invocation}/related', group='records'),
            'permissions': get(http, f'/projects/{project}/invocations/{invocation}/related', group='permissions')}


def test_guards_isolation_cursors_and_restored_query_only_archive(world, tmp_path):
    w = world
    engine = w.repository.engine
    foreign = KnowledgeRepository(engine).project(str(tmp_path / 'foreign'))
    with engine.connect() as db:
        run = db.scalar(text("SELECT id FROM managed_runs WHERE purpose = 'task'"))
        invocation = db.scalar(text("SELECT id FROM usage_invocations WHERE run_id = :r AND role = 'executor'"),
                               {'r': run})
    path = w.url.removeprefix('sqlite:///')
    managed = config(w.context, w.ports, supervisor=False)
    app = create_app(w.url, tmp_path / 'ui', managed=managed)
    with AnonymousClient(app, base_url=LOCAL) as anonymous:
        assert anonymous.get(MAP + '/projects').status_code == 401
        assert anonymous.get(MAP + '/activity').status_code == 401
    with client(w.url, tmp_path, managed) as http:
        marks = table_marks(path)
        ordinary = snapshot(http, w.project, run, invocation)
        assert http.get(MAP + '/projects', headers={'Host': 'foreign.invalid'}).status_code == 403
        assert http.get(MAP + '/projects', headers={'Origin': 'https://foreign.invalid'}).status_code == 403
        assert http.get(MAP + '/projects', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert http.post(MAP + '/projects', headers=CSRF).status_code == 405  # no mutation route exists
        # Every alias of the project reads the same scope; identifiers of another project answer like missing ones.
        for alias in ('synthetic', f'run:{run}'):
            assert get(http, f'/projects/{alias}/phases')['scope'] == ordinary['phases']['scope']
        for route in (f'/projects/{foreign}/runs/{run}/steps', f'/projects/{foreign}/invocations/{invocation}',
                      f'/projects/{foreign}/invocations/{invocation}/steps', f'/projects/{foreign}/phases/P001/tasks',
                      f'/projects/{w.project}/runs/unknown/steps', f'/projects/{w.project}/phases/P404/tasks',
                      f'/projects/{w.project}/phases/P001/tasks/P001-T404/runs', '/projects/unknown/phases'):
            refused = http.get(MAP + route)
            assert refused.status_code == 404 and refused.json()['detail']['code'] == 'map_not_found', route
        assert get(http, f'/projects/{foreign}/phases')['items'] == []
        assert http.get(MAP + f'/projects/{w.project}/invocations/{invocation}/related',
                        params={'group': 'native'}).status_code == 422
        assert http.get(MAP + '/projects', params={'limit': 101}).status_code == 422
        assert http.get(MAP + f'/projects/{w.project}/phases/P001/tasks', params={'limit': 301}).status_code == 422

        # Pages over a stable version are complete and disjoint; cursors are bound to their scope.
        one, count, _ = pages(http, f'/projects/{w.project}/phases', limit=1)
        assert count == 2 and [p['code'] for p in one] == ['P001', 'P002'] and one == ordinary['phases']['items']
        cursor = get(http, f'/projects/{w.project}/phases', limit=1)['next_cursor']
        for route, params in ((f'/projects/{w.project}/phases/P001/tasks', {}), ('/projects', {}),
                              (f'/projects/{foreign}/phases', {}),
                              (f'/projects/{w.project}/invocations/{invocation}/steps', {})):
            refused = http.get(MAP + route, params={'cursor': cursor, **params})
            assert refused.status_code == 422 and refused.json()['detail']['code'] == 'cursor_invalid', route
        body, check = cursor[3:].rsplit('.', 1)
        for forged in ('garbage', 'c1.' + body + '.' + '0' * 16, 'c1.' + wm._encode({'s': 'x', 'v': 'y', 'k': [1]}),
                       cursor[:-1]):
            assert http.get(MAP + f'/projects/{w.project}/phases', params={'cursor': forged}).status_code == 422
        # A change supersedes the version: the old cursor is stale and the snapshot reload recovers.
        assert table_marks(path) == marks  # nothing above wrote
        w.phases.raise_question(w.phase_id, w.get(w.phase_id)['version'], text='Synthetic owner question.')
        stale = http.get(MAP + f'/projects/{w.project}/phases', params={'cursor': cursor, 'limit': 1})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'cursor_stale'
        poll = get(http, '/activity', scope=[ordinary['phases']['scope'], ordinary['trace']['scope']])
        changed = {s['scope']: s['version'] for s in poll['scopes']}
        assert changed[ordinary['phases']['scope']] != ordinary['phases']['version']
        assert changed[ordinary['trace']['scope']] == ordinary['trace']['version']  # a sealed trace never changes
        recovered, count, _ = pages(http, f'/projects/{w.project}/phases', limit=1)
        assert count == 2 and recovered[0]['status']['code'] == 'BLOCKED'
        bad = get(http, '/activity', scope=['s1.' + wm._encode(['phases', foreign + 'x']), 'not-a-scope'][:1])
        assert bad['scopes'][0]['version'] is None and bad['scopes'][0]['error'] == 'not_found'
        assert http.get(MAP + '/activity', params={'scope': 'not-a-scope'}).status_code == 422
        assert http.get(MAP + '/activity', params={'scope': [ordinary['phases']['scope']] * 11}).status_code == 422
        current = snapshot(http, w.project, run, invocation)

    create_backup(path, tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    w.context.root.rename(tmp_path / 'checkout-gone')  # archive reads need no checkout
    restored = tmp_path / 'restored/state.sqlite3'
    before = sha256(restored.read_bytes()).hexdigest()
    archive = create_app(f'sqlite:///{restored}', managed=ManagedConfig(supervisor=False))
    with TestClient(archive, base_url=LOCAL) as http:
        assert archive.state.runtime.projects == {}
        archived = snapshot(http, w.project, run, invocation)
        assert all(page['read_only_archive'] for page in archived.values())
        assert strip(archived) == strip(current)
        assert archived['projects']['items'][0]['configuration'] is None
        assert archived['projects']['items'][0]['configuration_source'] == 'absent'
        poll = get(http, '/activity', scope=[archived['phases']['scope']])
        assert poll['read_only_archive'] and not poll['polling']['enabled']
        assert poll['scopes'][0]['version'] == archived['phases']['version']
        assert http.post(MAP + '/projects', headers=CSRF).status_code in (405, 409)
    assert sha256(restored.read_bytes()).hexdigest() == before


ROOT = __import__('pathlib').Path(__file__).resolve().parents[2] / 'src/my_harness'


def assigned(module, receivers, constructors=(), calls=(), names=()):
    """String constants the module writes as a status: `<receiver>.status = ...` (literals, conditionals, dict values
    and defaults, tuple assignments), `status=` keywords of the named row constructors, and the given positional
    argument of the named calls. Read from the real source, not from a copy of the mapping."""
    import ast
    tree = ast.parse((ROOT / module).read_text())
    found = set()

    def constants(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
        elif isinstance(node, ast.IfExp):
            constants(node.body), constants(node.orelse)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'get':
            constants(node.func.value)
            for arg in node.args[1:]:
                constants(arg)
        elif isinstance(node, ast.Dict):
            for value in node.values:
                constants(value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                pairs = (zip(target.elts, node.value.elts) if isinstance(target, ast.Tuple)
                         and isinstance(node.value, ast.Tuple) else [(target, node.value)])
                for left, right in pairs:
                    if (isinstance(left, ast.Attribute) and left.attr == 'status'
                            and isinstance(left.value, ast.Name) and left.value.id in receivers):
                        constants(right)
                    if isinstance(left, ast.Name) and left.id in names:  # a local later passed as the status
                        constants(right)
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', None)
            if name in constructors:
                for keyword in node.keywords:
                    if keyword.arg == 'status':
                        constants(keyword.value)
            if name in calls and len(node.args) > calls[name]:
                constants(node.args[calls[name]])
    return found


def constraint(table, column):
    import re
    from my_harness.storage.models import Base
    for item in Base.metadata.tables[table].constraints:
        sql = str(getattr(item, 'sqltext', ''))
        if sql.startswith(f'{column} IN ') or sql.startswith(f'status IN ') and column == 'status':
            return set(re.findall(r"'([A-Za-z_]+)'", sql))
    raise AssertionError((table, column))


def unmapped(entity, values):
    return sorted(v for v in values if wm.status(entity, v)['class'] == 'unknown')


def vocabularies():
    """Every persisted status vocabulary the map classifies, from constants, check constraints and written values."""
    import re
    from my_harness.core.engine.knowledge import STATUSES
    from my_harness.core.engine.observation import STREAM_ENDS, SUPERVISOR_STOPS
    from my_harness.core.engine.phases import VERDICTS
    from my_harness.storage.models import GRAPH_THREAD_STATUSES, OPERATION_STATUSES
    from my_harness.storage.phases import CHECK_STATUS
    from my_harness.storage.retention import TERMINAL_ATTEMPTS
    managed = (ROOT / 'storage/managed.py').read_text()
    history = {v.upper() for group in re.findall(r'history\.status (?:not )?in \{([^}]*)\}', managed)
               for v in re.findall(r'"([a-z_]+)"', group)}
    run = set().union(*(assigned(m, ('run',), ('Run', 'ManagedRunRow')) for m in (
        'storage/managed.py', 'storage/phases.py', 'storage/structured_phases.py', 'storage/chat.py',
        'storage/planning.py', 'storage/bootstrap.py', 'storage/project_import.py', 'storage/document_export.py',
        'storage/retired_work.py', 'storage/transition.py'))) | history
    phase_ops = set().union(*(assigned(m, ('op', 'task_op', 'interrupted', 'operation'), ('Operation',),
                                       {'abort': 3})
                              for m in ('storage/phases.py', 'storage/structured_phases.py', 'storage/closure.py')))
    phases = set().union(*(assigned(m, ('phase',), ('Phase', 'PhaseRow'))
                           for m in ('storage/phases.py', 'storage/structured_phases.py', 'storage/closure.py')))
    # Plan and check verdicts become the operation status (`op.status = outcome['verdict']`).
    phase_ops |= (set(VERDICTS) | {'NOT_READY'} | (phases & {'CLOSED', 'ABANDONED'})
                  | assigned('services/phase_lifecycle.py', (), (), {'result': 0}))
    phases |= set(CHECK_STATUS.values())
    attempts = ({v.upper() for v in (*STREAM_ENDS, *SUPERVISOR_STOPS)} | set(TERMINAL_ATTEMPTS)
                | {'COMPLETED', 'INTERRUPTED'} | assigned('storage/managed.py', (), ('AttemptRow',)))
    return {
        'run': run, 'phase': phases, 'phase_operation': phase_ops,
        'attempt': attempts,
        'process': assigned('storage/managed.py', ('row',), ('Process',)) & {'PENDING', 'RUNNING', 'STOPPED', 'UNCERTAIN'},
        'termination': {*STREAM_ENDS.values(), *SUPERVISOR_STOPS.values(), 'interrupted', 'pending'},
        'launch': constraint('usage_invocations', 'launch'),
        'identity': {*STATUSES['phase'], *STATUSES['task'], 'replaced'},
        'workflow_operation': set(OPERATION_STATUSES),
        'graph_thread': set(GRAPH_THREAD_STATUSES),
        'autonomous_run': constraint('autonomous_runs', 'status'),
        # Persisted values plus the effective EXPIRED the permission view derives (`effective_status`).
        'permission': assigned('storage/permissions.py', ('row', 'old'), ('Permission',)) | {'EXPIRED'},
        'judge_ruling': assigned('services/judge.py', (), (), {'_ruling': 2}, names=('status',)),
        'commit': assigned('storage/managed.py', ('row', 'commit'), ('Commit',)) & {'INTENT', 'COMMITTED', 'INVALIDATED'}
                  | {'INTENT', 'COMMITTED', 'INVALIDATED'},
    }


def test_every_persisted_status_vocabulary_has_a_class_and_unmapped_values_stay_unknown(world, tmp_path):
    found = vocabularies()
    # The extraction reads real writers: each vocabulary is non-trivial and contains values the writers emit.
    assert {'COMMITTED', 'ACCEPTANCE_READY', 'REVISION_LIMIT', 'EXECUTING', 'REFUSED'} <= found['run']
    assert {'READY_TO_CLOSE', 'NEEDS_RECONCILIATION', 'BLOCKED', 'CLOSING'} <= found['phase']
    assert {'QUEUED', 'INTENT', 'PROPOSED', 'STALE', 'READY', 'REVISE'} <= found['phase_operation']
    assert {'REPETITIVE', 'TIMEOUT', 'CANCELLED', 'ACTIVE'} <= found['attempt']
    assert {'PENDING', 'GRANTED', 'DENIED', 'CONSUMED', 'DENIED_CONSUMED', 'SUPERSEDED'} <= found['permission']
    assert {'ESCALATED', 'FAILED', 'UNCERTAIN', 'VALIDATED'} <= found['judge_ruling']
    assert {'PENDING', 'RUNNING', 'STOPPED', 'UNCERTAIN'} == found['process']
    assert {entity: unmapped(entity, values) for entity, values in found.items()} == {e: [] for e in found}
    # The check detects a value without a mapping; such a value renders as `unknown` with its raw code.
    assert unmapped('run', found['run'] | {'MYSTERY'}) == ['MYSTERY']
    assert wm.status('run', 'MYSTERY') == {'code': 'MYSTERY', 'class': 'unknown'}

    # Values actually written by the world's real flows, read back from SQLite, are all mapped.
    engine = world.repository.engine
    tables = {'run': 'SELECT DISTINCT status FROM managed_runs', 'phase': 'SELECT DISTINCT status FROM managed_phases',
              'phase_operation': 'SELECT DISTINCT status FROM phase_operations',
              'attempt': 'SELECT DISTINCT status FROM managed_attempts',
              'commit': 'SELECT DISTINCT status FROM managed_commits',
              'launch': 'SELECT DISTINCT launch FROM usage_invocations',
              'workflow_operation': 'SELECT DISTINCT status FROM workflow_operations',
              'graph_thread': 'SELECT DISTINCT status FROM graph_threads'}
    with engine.connect() as db:
        written = {entity: set(db.scalars(text(sql)).all()) for entity, sql in tables.items()}
    assert written['run'] and written['phase_operation'] and written['commit']
    assert {entity: unmapped(entity, values) for entity, values in written.items()} == {e: [] for e in written}

    # An unmapped persisted value reaches the API as `unknown` with its raw code, never a guessed class.
    with engine.begin() as db:
        db.execute(text("UPDATE managed_runs SET status = 'MYSTERY', version = version + 1 WHERE purpose = 'task'"))
    with client(world.url, tmp_path, config(world.context, world.ports, supervisor=False)) as http:
        [node] = get(http, f'/projects/{world.project}/phases/P001/tasks')['items']
        assert node['status'] == {'code': 'MYSTERY', 'class': 'unknown'}


def test_trace_states_source_records_retention_and_lazy_pages(tmp_path, context, repository, migrated_database,  # noqa: F811
                                                              monkeypatch):
    from my_harness.storage import observed_steps as storage
    from my_harness.storage.operation_journal import record_event
    from my_harness.storage.retention import apply_retention, preview_retention
    from sqlalchemy.orm import Session
    from test_observed_steps import CLAUDE, OVERSIZE, finish, invocation, scripted, settle
    from test_trace_observation import probe_adapter
    url, database = migrated_database[0], migrated_database[0].removeprefix('sqlite:///')
    port = scripted(tmp_path, OVERSIZE + CLAUDE[1:])
    job, claim, big, _ = settle(repository, context, port, 'executor')
    finish(repository, job, claim)
    ObservedStepProjector(repository.engine).run_pending()
    def settled(adapter, role):
        job, claim, request, _ = settle(repository, context, adapter, role)
        finish(repository, job, claim)  # releases the checkout for the next synthetic run; projects nothing
        return request
    pending = settled(scripted(tmp_path, CLAUDE), 'executor')
    failed = settled(scripted(tmp_path, CLAUDE), 'reviewer')
    with Session(repository.engine) as session, session.begin():
        record_event(session, kind=storage.FAILED, dedupe_key=storage.failed_key(invocation(failed)), source='derived',
                     payload={'reason': 'integrity_conflict'}, invocation_id=invocation(failed))
    monkeypatch.setattr(storage, 'mark_pending', lambda *args, **kwargs: None)  # a settlement from before T019
    earlier = settled(probe_adapter(tmp_path, 'success', usage=True), 'planner')  # D296 budget: no third executor
    monkeypatch.undo()
    with client(url, tmp_path, config(context, supervisor=False)) as http:
        states = {name: get(http, f'/projects/synthetic/invocations/{ident}')['steps']
                  for name, ident in (('sealed', invocation(big)), ('pending', invocation(pending)),
                                      ('failed', invocation(failed)), ('earlier', invocation(earlier)))}
        assert {k: v['state'] for k, v in states.items()} == {
            'sealed': 'sealed', 'pending': 'pending', 'failed': 'integrity_failed', 'earlier': 'not_projected'}
        assert states['earlier']['reason'] == 'settled_before_observed_steps'
        assert states['earlier']['observation']['payload']['format'] == 'trace-observation-1'  # counters kept
        head = get(http, f'/projects/synthetic/invocations/{invocation(earlier)}')
        assert head['evidence']['attempt_logs'].endswith(f'/attempts/{earlier.id}/logs')
        for request in (pending, failed, earlier):  # no partial projection and no backfill: no steps at all
            page = get(http, f'/projects/synthetic/invocations/{invocation(request)}/steps')
            assert page['items'] == [] and page['next_cursor'] is None

        whole, count, _ = pages(http, f'/projects/synthetic/invocations/{invocation(big)}/steps', limit=3)
        assert count > 2 and [s['seq'] for s in whole] == list(range(len(whole)))  # lazy pages: no loss, no duplicate
        refs = [r for s in whole for r in s['source_records']]
        oversize = [r for r in refs if r['oversize']]
        assert oversize and all(r['availability'] == 'available' for r in refs)
        assert oversize[0]['log']['path'] == f'/api/managed/runs/{job.run_id}/attempts/{big.id}/logs'
        assert oversize[0]['log']['size'] > 16384 and len(oversize[0]['log']['sha256']) == 64
        target = refs[0]
        event = http.get(target['event']['path'], params=target['event']['query']).json()['items']
        assert [(e['sequence'], e['kind']) for e in event] == [(target['sequence'], 'agent_event')]
        assert 'original' not in json.dumps(whole) and 'synthetic private thought' not in json.dumps(whole)

        options = dict(artifact_roots=[port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
        shown = preview_retention(database, **options)
        apply_retention(database, **options, preview_sha256=shown['preview_sha256'], reason='Synthetic retention',
                        confirmed=True, writers_stopped=True)
        after, _, last = pages(http, f'/projects/synthetic/invocations/{invocation(big)}/steps', limit=200)
        refs = [r for s in after for r in s['source_records']]
        assert {r['availability'] for r in refs if r['oversize']} == {'unavailable_after_retention'}
        assert {r['availability'] for r in refs if not r['oversize']} == {'available'}
        assert [{k: v for k, v in s.items() if k != 'source_records'} for s in after] == [
            {k: v for k, v in s.items() if k != 'source_records'} for s in whole]  # steps survive retention
        assert last['version'] == get(http, f'/projects/synthetic/invocations/{invocation(big)}/steps')['version']

        # Preparation steps and configuration assistance are not map elements: their lane is labelled excluded.
        with closing(sqlite3.connect(database)) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute("INSERT INTO usage_invocations (id, source_kind, source_id, preparation_id, preparation_step_id, "
                       "root, purpose, role, versions, launch, started_at, recorded_at, updated_at) VALUES "
                       "('preparation_step:s1', 'preparation_step', 's1', 'p1', 's1', ?, 'preparation', 'executor', '{}', "
                       "'observed', 't', 't', 't')", (str(context.root),))
            db.commit()
        excluded = get(http, '/projects/synthetic/invocations/preparation_step:s1')
        assert excluded['steps']['state'] == 'lane_excluded'
        assert excluded['steps']['reason'] == 'steps_not_projected_for_lane'
        assert excluded['owner']['lane'] == 'preparation_step' and excluded['evidence'] is None


# Realistic-size budgets (T018 §12, D309) -----------------------------------------------------------------------------

TOTALS = {'projects': 25, 'phases': 40, 'tasks': 80, 'runs': 30, 'invocations': 40, 'steps': 5000, 'inbox': 300}


def deep_world(tmp_path, database, engine):
    """One deep path with per-level maxima; siblings at each level are leaves (T018 §12, Q19). Rows are written as
    their writers persist them; statuses cycle through each level's vocabulary, and telemetry is partly absent."""
    from test_knowledge import OWNER, phase, task
    root = str(tmp_path / 'deep')
    knowledge = KnowledgeRepository(engine)
    project = knowledge.project(root)
    draft = knowledge.open_draft(project, None)
    phases = [knowledge.put(draft, 'phase', f'P{n:03d}', {**phase(f'Objective {n}.'),
                            **({'status': 'withdrawn'} if n == 40 else {})}) for n in range(1, 41)]
    for n in range(1, TOTALS['tasks'] + 1):
        item = knowledge.put(draft, 'task', f'P001-T{n:03d}', task(f'Task {n}'))
        knowledge.link(draft, 'part_of', item, phases[0], position=n - 1)
        if n > 1:
            knowledge.link(draft, 'depends_on', item, previous)
        previous = item
    knowledge.adopt(draft, None, origin='owner_confirmed', actor=OWNER)
    runs_codes = list(wm._TABLE['run'])
    statuses = [code for cls in wm._TABLE['run'].values() for code in cls]
    at = lambda n: f'2026-11-05T10:{n // 60 % 60:02d}:{n % 60:02d}.{n:06d}+00:00'  # noqa: E731
    with closing(sqlite3.connect(database)) as db:
        def run(ident, root_, phase_, task_, status, n, purpose='task'):
            db.execute("""INSERT INTO managed_runs (id, root, task_id, phase_id, context_json, versions_json,
                history_json, status, stage, revisions, revision_limit, version, created_at, updated_at, purpose)
                VALUES (?, ?, ?, ?, '{}', '{}', '{}', ?, 'finished', 0, 2, 3, ?, ?, ?)""",
                       (ident, root_, task_, phase_, status, at(n), at(n), purpose))
            db.execute("""INSERT INTO run_projections (run_id, projection, history_sha256, history_status, attempts,
                executor_attempts, cycle_count, stop_count) VALUES (?, 'run-projection-1', ?, 'stopped', 1, 1, 0, 0)""",
                       (ident, '0' * 64))
        for n in range(1, TOTALS['projects']):  # leaf siblings: one run each
            run(f'leaf-{n}', str(tmp_path / f'leaf-{n:02d}'), 'P001', 'P001-T001', statuses[n % len(statuses)], n)
        for n in range(1, 41):
            status = 'ACTIVE' if n == 1 else 'CLOSED' if n < 30 else 'ABANDONED' if n < 35 else None
            if status is None:
                continue  # identities only (pending, and the withdrawn P040)
            tasks = [f'P001-T{t:03d}' for t in range(1, 81)] if n == 1 else []
            db.execute("""INSERT INTO managed_phases (id, root, code, definition, definition_sha256, documents, status,
                version, created_at, updated_at, definition_number) VALUES (?, ?, ?, ?, ?, '{}', ?, 1, ?, ?, 1)""",
                       (f'phase-{n}', root, f'P{n:03d}', json.dumps({'code': f'P{n:03d}', 'tasks': tasks,
                        'objective': f'Objective {n}.', 'exit_criteria': []}), '0' * 64, status, at(n), at(n)))
        for kind, status in (('plan', 'ADOPTED'), ('check', 'REVISE'), ('check', 'QUEUED')):
            db.execute("""INSERT INTO phase_operations (id, phase_id, kind, run_id, status, previous_status, request,
                created_at) VALUES (?, 'phase-1', ?, NULL, ?, 'ACTIVE', '{}', ?)""", (str(uuid.uuid4()), kind, status,
                                                                                    at(len(kind) + len(status))))
        for t in range(1, TOTALS['tasks'] + 1):  # every task of the deep phase has a latest run
            run(f'task-{t}', root, 'P001', f'P001-T{t:03d}', statuses[t % len(statuses)], 100 + t)
        for r in range(1, TOTALS['runs']):  # the deep task's earlier runs; its latest is `task-1`
            run(f'deep-{r}', root, 'P001', 'P001-T001', statuses[r % len(statuses)], r)
        db.execute("UPDATE managed_runs SET created_at = ? WHERE id = 'task-1'", (at(999),))
        db.execute("""INSERT INTO managed_jobs (idempotency_key, run_id, request_json, status, created_at)
            VALUES ('deep', 'task-1', '{"action": "start"}', 'FINISHED', ?)""", (at(1),))
        job = db.execute("SELECT id FROM managed_jobs WHERE idempotency_key = 'deep'").fetchone()[0]
        roles = ['planner'] + ['executor', 'reviewer'] * 19 + ['judge']
        for number, role in enumerate(roles, start=1):
            attempt = f'attempt-{number}'
            db.execute("""INSERT INTO managed_attempts (id, run_id, number, request_json, versions_json, status,
                result_json, started_at, finished_at) VALUES (?, 'task-1', ?, ?, '{}', ?, '{}', ?, ?)""",
                       (attempt, number, json.dumps({'role': role}), list(wm.STATUS['attempt'])[number % 9],
                        at(number), at(number + 1)))
            if number % 2:  # half the processes are absent: missing telemetry stays absent
                db.execute("""INSERT INTO managed_processes (id, attempt_id, job_id, spec, status, capture)
                    VALUES (?, ?, ?, '{"provider": "claude"}', 'STOPPED', ?)""",
                           (attempt, attempt, job, json.dumps({'status': 'complete', 'group_state': 'dead',
                                                               'wall_duration_seconds': 1.5 + number})))
            db.execute("""INSERT INTO usage_invocations (id, source_kind, source_id, attempt_id, run_id, root,
                phase_code, task_id, purpose, role, agent, requested_model, requested_effort, versions, launch,
                started_at, finished_at, recorded_at, updated_at) VALUES (?, 'managed_attempt', ?, ?, 'task-1', ?,
                'P001', 'P001-T001', 'task', ?, ?, 'synthetic-model', 'medium', '{}', 'observed', ?, ?, ?, ?)""",
                       (f'managed_attempt:{attempt}', attempt, attempt, root, role,
                        'executor' if role == 'executor' else 'judge' if role == 'judge' else 'reviewer',
                        at(number), at(number + 1), at(number), at(number)))
        deep = 'managed_attempt:attempt-2'
        rows = []
        for seq in range(TOTALS['steps']):
            payload = {'format': 'observed-step-1', 'seq': seq, 'kind': 'tool_call' if seq % 3 else 'turn',
                       'parent_seq': seq - seq % 3 if seq % 3 else None, 'call_id': f'call-{seq}', 'tool': 'Read',
                       'outcome': 'completed', 'source_record': [{'run_id': 'task-1', 'attempt_id': 'attempt-2',
                                                                 'sequence': seq + 1, 'record': seq + 1,
                                                                 'oversize': seq % 500 == 0}]}
            rows.append((str(uuid.uuid4()), f'step:{deep}:{seq}', root, deep, 'invocation.step', 'measured',
                         json.dumps(payload), '0' * 64, at(seq)))
        rows.append((str(uuid.uuid4()), f'steps:{deep}', root, deep, 'invocation.steps_sealed', 'measured',
                     json.dumps({'format': 'observed-step-1', 'steps': TOTALS['steps']}), '0' * 64, at(1)))
        db.executemany("""INSERT INTO trace_events (event_id, dedupe_key, root, invocation_id, kind, source, payload,
            payload_sha256, truncated, redactions, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)""", rows)
        for q in range(TOTALS['inbox'] // 2):  # open owner questions of the active phase
            db.execute("""INSERT INTO phase_questions (id, phase_id, text, source, status, version, created_at)
                VALUES (?, 'phase-1', ?, '{"kind": "owner"}', 'OPEN', 1, ?)""", (f'q-{q}', f'Private {SECRET}', at(q)))
            db.execute("""INSERT INTO phase_events (phase_id, sequence, kind, recorded_at, payload)
                VALUES ('phase-1', ?, 'question_raised', ?, ?)""", (q + 2, at(q), json.dumps({'id': f'q-{q}'})))
        for p in range(TOTALS['inbox'] // 2):  # pending run permissions raised by the deep run's attempts
            ident, attempt = f'perm-{p}', f'attempt-{p % 40 + 1}'
            db.execute("""INSERT INTO permission_requests (id, run_id, version, status, request, fingerprint,
                expires_at, created_at) VALUES (?, 'task-1', 1, 'PENDING', ?, ?, '2100-01-01T00:00:00+00:00', ?)""",
                       (ident, json.dumps({'source_attempt_id': attempt, 'operation': 'network'}), '0' * 64, at(p)))
            db.execute("""INSERT INTO managed_events (run_id, sequence, kind, recorded_at, payload)
                VALUES ('task-1', ?, 'permission_requested', ?, ?)""", (100 + p, at(p), json.dumps({'id': ident})))
        db.commit()
    return project, root, deep


PARALLEL = int(__import__('os').environ.get('PYTEST_XDIST_WORKER_COUNT', '1')) > 1


def test_realistic_size_pages_meet_the_poll_and_trace_budgets(tmp_path, migrated_database, record_property):
    """Sizes, totals, statuses and lossless paging of the §12 fixture; runs in every suite."""
    measure_realistic_size(tmp_path, migrated_database, record_property, latency=False)


@pytest.mark.skipif(PARALLEL, reason='D309 latency is measured on the development machine without other test workers; '
                                     'run serially: scripts/check tests/product/test_work_map.py -- -n 0')
def test_realistic_size_pages_meet_the_latency_budget_when_measured_serially(tmp_path, migrated_database,
                                                                             record_property):
    measure_realistic_size(tmp_path, migrated_database, record_property, latency=True)


def measure_realistic_size(tmp_path, migrated_database, record_property, *, latency):
    import statistics
    import time
    from my_harness.storage.database import make_engine
    database = migrated_database[0].removeprefix('sqlite:///')
    engine = make_engine(migrated_database[0])
    try:
        project, root, deep = deep_world(tmp_path, database, engine)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(database)) as db:
        counted = {'projects': len({r[0] for r in db.execute('SELECT root FROM managed_runs')}),
                   'phases': 40, 'tasks': db.execute("SELECT count(*) FROM managed_runs WHERE root = ? AND phase_id = 'P001'"
                                                    " AND task_id != 'P001-T001'", (root,)).fetchone()[0] + 1,
                   'runs': db.execute("SELECT count(*) FROM managed_runs WHERE task_id = 'P001-T001' AND root = ?",
                                      (root,)).fetchone()[0],
                   'invocations': db.execute("SELECT count(*) FROM usage_invocations WHERE run_id = 'task-1'").fetchone()[0],
                   'steps': db.execute("SELECT count(*) FROM trace_events WHERE invocation_id = ? AND kind = "
                                       "'invocation.step'", (deep,)).fetchone()[0],
                   'inbox': 300}
    assert counted == TOTALS
    archive = create_app(migrated_database[0], managed=ManagedConfig(supervisor=False))
    timings = {}
    with TestClient(archive, base_url=LOCAL) as http:
        routes = {'L0 projects': ('/projects', {}), 'L1 phases': (f'/projects/{project}/phases', {}),
                  'L2 tasks': (f'/projects/{project}/phases/P001/tasks', {}),
                  'runs': (f'/projects/{project}/phases/P001/tasks/P001-T001/runs', {}),
                  'L3 steps': (f'/projects/{project}/runs/task-1/steps', {}),
                  'L4 header': (f'/projects/{project}/invocations/{deep}', {}),
                  'L4 related': (f'/projects/{project}/invocations/{deep}/related', {'group': 'permissions'})}
        first = {name: get(http, path, **params) for name, (path, params) in routes.items()}
        assert len(first['L0 projects']['items']) == 25 and len(first['L1 phases']['items']) == 40
        assert len(first['L2 tasks']['items']) == 80 and len(first['L2 tasks']['edges']) == 79
        assert len(first['runs']['items']) == 30 and len(first['L3 steps']['items']) == 40
        assert first['L0 projects']['items'][0]['bubbles']['total'] == 300 or any(
            p['bubbles']['total'] == 300 for p in first['L0 projects']['items'])
        assert {n['status']['class'] for n in first['L2 tasks']['items']} >= {'done', 'progress', 'waiting', 'failed',
                                                                              'inactive'}
        assert {p['status']['class'] for p in first['L1 phases']['items']} >= {'done', 'progress', 'pending',
                                                                                'inactive'}
        assert SECRET not in json.dumps(first)
        # Small pages over a stable version: the concatenation equals the single page, without loss or duplicates.
        for name, key, size, expected_pages in (('L0 projects', 'id', 7, 4), ('L1 phases', 'code', 7, 6),
                                                ('L2 tasks', 'code', 7, 12), ('runs', 'run_id', 7, 5),
                                                ('L3 steps', 'key', 7, 6)):
            path, params = routes[name]
            paged, count, _ = pages(http, path, limit=size, **params)
            assert [i[key] for i in paged] == [i[key] for i in first[name]['items']] and count == expected_pages, name
        for name, (path, params) in routes.items():
            samples = []
            for _ in range(20):
                started = time.perf_counter()
                get(http, path, **params)
                samples.append((time.perf_counter() - started) * 1000)
            timings[name] = statistics.quantiles(samples, n=20)[18]
        trace, count, samples, cursor = [], 0, [], None
        while True:
            started = time.perf_counter()
            page = get(http, f'/projects/{project}/invocations/{deep}/steps', limit=200,
                       **({'cursor': cursor} if cursor else {}))
            samples.append((time.perf_counter() - started) * 1000)
            trace += page['items']
            count += 1
            cursor = page['next_cursor']
            if cursor is None:
                break
        timings['L4 trace pages'] = statistics.quantiles(samples, n=20)[18]
        assert count == 25 and [s['seq'] for s in trace] == list(range(TOTALS['steps']))
        assert sum(1 for s in trace for r in s['source_records'] if r['oversize']) == 10
        poll = http.get(MAP + '/activity', params={'scope': [first[n]['scope'] for n in routes]})
        assert poll.status_code == 200 and not poll.json()['active']
        samples = []
        for _ in range(20):
            started = time.perf_counter()
            http.get(MAP + '/activity', params={'scope': [first[n]['scope'] for n in routes]})
            samples.append((time.perf_counter() - started) * 1000)
        timings['activity'] = statistics.quantiles(samples, n=20)[18]
    record_property('work_map_p95_ms', {k: round(v, 1) for k, v in timings.items()})
    record_property('work_map_idle_poll_bytes', len(poll.content))
    print('WORK_MAP_BUDGET', json.dumps({'p95_ms': {k: round(v, 1) for k, v in timings.items()},
                                         'idle_poll_bytes': len(poll.content), 'totals': TOTALS}))
    assert len(poll.content) <= 8 * 1024, len(poll.content)
    if latency:
        assert all(value <= 150 for value in timings.values()), timings


LARGE = ('managed_runs', 'managed_attempts', 'managed_events', 'trace_events', 'usage_invocations',
         'managed_processes', 'attempt_metrics', 'phase_events', 'knowledge_revision_links', 'knowledge_revision_members')


def test_map_reads_use_indexed_bounded_queries_and_never_select_histories(tmp_path, migrated_database):
    from sqlalchemy import event
    database = migrated_database[0].removeprefix('sqlite:///')
    from my_harness.storage.database import make_engine
    engine = make_engine(migrated_database[0])
    try:
        project, root, deep = deep_world(tmp_path, database, engine)
    finally:
        engine.dispose()
    app = create_app(migrated_database[0], managed=ManagedConfig(supervisor=False))
    captured = []
    with TestClient(app, base_url=LOCAL) as http:
        event.listen(app.state.runtime.engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, parameters, context, many: captured.append((statement, parameters)))
        scopes = []
        for path, params in (('/projects', {}), (f'/projects/{project}/phases', {}),
                             (f'/projects/{project}/phases/P001/tasks', {}),
                             (f'/projects/{project}/phases/P001/tasks/P001-T001/runs', {}),
                             (f'/projects/{project}/runs/task-1/steps', {}),
                             (f'/projects/{project}/invocations/{deep}', {}),
                             (f'/projects/{project}/invocations/{deep}/steps', {}),
                             (f'/projects/{project}/invocations/{deep}/related', {'group': 'records'}),
                             (f'/projects/{project}/invocations/{deep}/related', {'group': 'permissions'})):
            scopes.append(get(http, path, **params)['scope'])
        get(http, '/activity', scope=scopes)
    own = [(s, p) for s, p in captured if not s.lstrip().startswith('WITH facts(') and 'EXPLAIN' not in s
           and not s.lstrip().upper().startswith('PRAGMA')]
    assert own and all('history_json' not in s for s, _ in captured)
    offenders, plans = {}, 0
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as db:
        for statement, parameters in own:
            aliases = {alias: table for table, alias in re.findall(r'(?:FROM|JOIN)\s+(\w+)\s+(?:AS\s+)?(\w+)', statement)}
            for row in db.execute('EXPLAIN QUERY PLAN ' + statement, parameters):
                plans += 1
                full = re.match(r'SCAN (\w+)$', row[3])  # a full table scan (index scans name their index)
                table = aliases.get(full.group(1), full.group(1)) if full else None
                if table in LARGE:
                    offenders.setdefault(table, set()).add(statement.strip().split('\n')[0][:80])
    assert plans > len(own) and offenders == {}, offenders
    # A circle's latest invocation in an element is a seek per role in time order: no sort of its history.
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as db:
        circles = [(s, p) for s, p in own if 'FROM usage_invocations' in s and 'ORDER BY started_at DESC' in s]
        assert circles
        for statement, parameters in circles:
            plan = list(db.execute('EXPLAIN QUERY PLAN ' + statement, parameters))
            seeks = [row for row in plan if 'usage_invocations' in row[3]
                     and 'sqlite_autoindex_usage_invocations_1 (id=?)' not in row[3]]
            assert seeks and all('SEARCH' in r[3] and 'ix_usage_invocations_circle_' in r[3] for r in seeks), plan
            # The only sorts merge the one-row branch results; none sits in a branch beside its seek.
            assert not {r[1] for r in plan if 'TEMP B-TREE' in r[3]} & {r[1] for r in seeks}, plan


def test_0041_round_trip_adds_and_drops_only_the_map_indexes(world, migrated_database, tmp_path):
    from alembic import command
    from sqlalchemy import inspect
    url, alembic = migrated_database
    engine = world.repository.engine
    names = {'ix_managed_runs_scope': 'managed_runs', 'ix_managed_attempts_open': 'managed_attempts',
             'ix_phase_operations_phase': 'phase_operations',
             'ix_usage_invocations_circle_project': 'usage_invocations',
             'ix_usage_invocations_circle_root': 'usage_invocations',
             'ix_usage_invocations_circle_phase': 'usage_invocations',
             'ix_usage_invocations_circle_task': 'usage_invocations'}

    def present():
        engine.dispose()
        return {name: name in {i['name'] for i in inspect(engine).get_indexes(table)} for name, table in names.items()}
    before = table_marks(url.removeprefix('sqlite:///'))
    with client(url, tmp_path, config(world.context, world.ports, supervisor=False)) as http:
        expected = get(http, f'/projects/{world.project}/phases/P001/tasks')['items']
    command.downgrade(alembic, '0040_observed_step_reads')
    assert present() == dict.fromkeys(names, False)
    assert table_marks(url.removeprefix('sqlite:///')) == before  # index only: rows untouched
    command.upgrade(alembic, 'head')
    command.check(alembic)
    assert present() == dict.fromkeys(names, True)
    with client(url, tmp_path, config(world.context, world.ports, supervisor=False)) as http:
        assert get(http, f'/projects/{world.project}/phases/P001/tasks')['items'] == expected


# Review corrections (2026-11-05) ------------------------------------------------------------------------------------

def scope_of(value):
    return 's1.' + wm._encode(value)


def test_malformed_scopes_and_cursors_are_contract_errors_never_500(world, tmp_path):
    """Finding 6: types and structure are validated before use; malformed input is a 422, never a 500."""
    w = world
    with client(w.url, tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        phases = get(http, f'/projects/{w.project}/phases')
        malformed = [scope_of([[]]), scope_of({}), scope_of([1]), scope_of([None]), scope_of(['phases']),
                     scope_of(['phases', w.project, 'extra']), scope_of(['projects', 'x']), scope_of(['unknown']),
                     scope_of([['phases'], w.project]), scope_of([{'level': 'phases'}]), scope_of('phases'),
                     scope_of(['tasks', w.project]), scope_of(['related', w.project, 'x']), scope_of([]),
                     's1.!!!', 's1.', 'phases', 's2.' + wm._encode(['projects'])]
        for value in malformed:
            refused = http.get(MAP + '/activity', params={'scope': value})
            assert refused.status_code == 422 and refused.json()['detail']['code'] == 'scope_invalid', value
        # Well formed but foreign or unknown: reported per scope without revealing anything.
        known = get(http, '/activity', scope=[scope_of(['phases', 'unknown']), scope_of(['related', w.project,
                                                                                          'missing', 'records']),
                                               phases['scope']])
        assert [s['error'] for s in known['scopes']] == ['not_found', 'not_found', None]
        body = {'s': phases['scope'], 'v': phases['version'], 'k': [['P001']]}
        forged = [wm.cursor(phases['scope'], phases['version'], [['P001']]),
                  wm.cursor(phases['scope'], phases['version'], [{'code': 'P001'}]),
                  wm.cursor(phases['scope'], phases['version'], [1]),
                  wm.cursor(phases['scope'], phases['version'], ['P001', 'P002']),
                  'c1.' + wm._encode({**body, 's': ['x']}) + '.' + wm._digest({**body, 's': ['x']})[:16],
                  'c1.' + wm._encode([1, 2]) + '.' + wm._digest([1, 2])[:16], 'c1.a.b.c', 'c1..']
        for value in forged:
            refused = http.get(MAP + f'/projects/{w.project}/phases', params={'cursor': value})
            assert refused.status_code == 422 and refused.json()['detail']['code'] == 'cursor_invalid', value
        for route in ('/projects', f'/projects/{w.project}/phases/P001/tasks',
                      f'/projects/{w.project}/runs/unknown/steps'):
            assert http.get(MAP + route, params={'cursor': forged[0]}).status_code in (404, 422)


def grow(database, root, *, projects=60, runs=300, attempts=40, tasks=50, permissions=100, phases=30):
    """More history around the §12 deep path, outside the first pages: other projects, earlier runs of the deep
    task, later attempts of the deep run, run-only tasks, permission requests of the deep invocation and phases."""
    at = '2026-11-04T09:00:00.000000+00:00'
    with closing(sqlite3.connect(database)) as db:
        def run(ident, root_, task, status='COMMITTED', created=at):
            db.execute("""INSERT INTO managed_runs (id, root, task_id, phase_id, context_json, versions_json,
                history_json, status, stage, revisions, revision_limit, version, created_at, updated_at, purpose)
                VALUES (?, ?, ?, 'P001', '{}', '{}', '{}', ?, 'finished', 0, 2, 1, ?, ?, 'task')""",
                       (ident, root_, task, status, created, created))
        for n in range(projects):
            run(f'grow-project-{n}', f'{os.path.dirname(root)}/zz-grow-{n:03d}', 'P001-T001')  # after the fixture
        for n in range(runs):
            run(f'grow-run-{n}', root, 'P001-T001', created=f'2026-11-01T00:00:{n % 60:02d}.{n:06d}+00:00')
        for n in range(tasks):
            run(f'grow-task-{n}', root, f'P001-T{500 + n:03d}', status='STOPPED')
        for n in range(41, 41 + attempts):
            db.execute("""INSERT INTO managed_attempts (id, run_id, number, request_json, versions_json, status,
                result_json, started_at) VALUES (?, 'task-1', ?, '{"role": "reviewer"}', '{}', 'COMPLETED', '{}', ?)""",
                       (f'grow-attempt-{n}', n, at))
        for n in range(permissions):
            db.execute("""INSERT INTO permission_requests (id, run_id, version, status, request, fingerprint,
                expires_at, created_at) VALUES (?, 'task-1', 1, 'DENIED', ?, ?, '2100-01-01T00:00:00+00:00', ?)""",
                       (f'grow-perm-{n}', json.dumps({'source_attempt_id': 'attempt-2'}), '0' * 64,
                        f'2026-11-05T11:{n // 60:02d}:{n % 60:02d}.000000+00:00'))
        for n in range(phases):
            db.execute("""INSERT INTO managed_phases (id, root, code, definition, definition_sha256, documents, status,
                version, created_at, updated_at, definition_number) VALUES (?, ?, ?, '{"tasks": []}', ?, '{}',
                'CLOSED', 1, ?, ?, 1)""", (f'grow-phase-{n}', root, f'P{100 + n:03d}', '0' * 64, at, at))
        db.commit()


def test_pages_read_and_enrich_only_their_rows_however_long_the_history(tmp_path, migrated_database, monkeypatch):
    """Finding 1: keyset pages select only their rows and enrich only their items; more history does not change
    what the first page of any level reads, and every level still pages without loss or duplicates."""
    from collections import Counter
    from my_harness.storage import work_map as storage
    from my_harness.storage.database import make_engine
    from my_harness.storage.observed_steps import ObservedSteps
    database = migrated_database[0].removeprefix('sqlite:///')
    engine = make_engine(migrated_database[0])
    project, root, deep = deep_world(tmp_path, database, engine)
    counts = Counter()
    rows, state, step, card = storage._rows, ObservedSteps.state, storage.WorkMap._invocation_step, \
        storage.WorkMap._project_card

    def counted(name, original, size=None):
        def wrapper(*args, **kwargs):
            result = original(*args, **kwargs)
            counts[name] += len(result) if size else 1
            return result
        return wrapper
    monkeypatch.setattr(storage, '_rows', counted('rows', rows, size=True))
    monkeypatch.setattr(ObservedSteps, 'state', counted('step_states', state))
    monkeypatch.setattr(storage.WorkMap, '_invocation_step', counted('invocation_details', step))
    monkeypatch.setattr(storage.WorkMap, '_project_card', counted('project_cards', card))
    from sqlalchemy import event
    event.listen(engine, 'before_cursor_execute', lambda *a: counts.update(['statements']))
    reader = storage.WorkMap(engine)
    reads = {'projects': lambda c=None: reader.projects(cursor=c, limit=5),
             'phases': lambda c=None: reader.phases(project, cursor=c, limit=5),
             'tasks': lambda c=None: reader.tasks(project, 'P001', cursor=c, limit=5),
             'runs': lambda c=None: reader.runs(project, 'P001', 'P001-T001', cursor=c, limit=5),
             'steps': lambda c=None: reader.steps(project, 'task-1', cursor=c, limit=5),
             'permissions': lambda c=None: reader.related(project, deep, 'permissions', cursor=c, limit=3)}

    def first_pages():
        measured = {}
        for name, read in reads.items():
            counts.clear()
            page = read()
            measured[name] = (dict(counts), [i.get('id') or i.get('code') or i.get('run_id') or i.get('key')
                                             for i in page['items']])
        return measured
    before = first_pages()
    assert before['steps'][0]['invocation_details'] == 5 and before['steps'][0]['step_states'] == 5
    assert before['projects'][0]['project_cards'] == 5
    for name in reads:  # the deep invocation raised 4 of the fixture's permission requests: pages of 3
        assert len(before[name][1]) == (3 if name == 'permissions' else 5), name
    grow(database, root)
    after = first_pages()
    # The same first page, with the same rows materialized, the same detail queries and the same statements,
    # although the history around it grew (other projects, runs, attempts, tasks, permission requests, phases).
    assert {n: after[n][1] for n in reads} == {n: before[n][1] for n in reads}
    assert {n: after[n][0] for n in reads} == {n: before[n][0] for n in reads}

    def walk(read, key, size):
        seen, cursor, pages_ = [], None, 0
        while True:
            page = read(cursor)
            seen += [item[key] for item in page['items']]
            pages_ += 1
            cursor = page['next_cursor']
            if cursor is None:
                return seen, pages_
    monkeypatch.undo()
    reader = storage.WorkMap(engine)
    everything, _ = walk(lambda c: reader.projects(cursor=c, limit=100), 'id', 100)
    projects, _ = walk(lambda c: reader.projects(cursor=c, limit=7), 'id', 7)
    assert len(projects) == len(set(projects)) == len(everything) == 85 and projects == everything
    tasks, _ = walk(lambda c: reader.tasks(project, 'P001', cursor=c, limit=9), 'code', 9)
    assert len(tasks) == len(set(tasks)) == 130
    assert tasks[:80] == [f'P001-T{n:03d}' for n in range(1, 81)] and tasks[80:] == [
        f'P001-T{500 + n:03d}' for n in range(50)]  # plan order, then run-only tasks by code
    steps, _ = walk(lambda c: reader.steps(project, 'task-1', cursor=c, limit=7), 'key', 7)
    assert len(steps) == len(set(steps)) == len(walk(lambda c: reader.steps(project, 'task-1', cursor=c, limit=200),
                                                     'key', 200)[0]) and steps == sorted(steps)
    runs, _ = walk(lambda c: reader.runs(project, 'P001', 'P001-T001', cursor=c, limit=50), 'run_id', 50)
    assert len(runs) == len(set(runs)) == 330
    permissions, _ = walk(lambda c: reader.related(project, deep, 'permissions', cursor=c, limit=13), 'id', 13)
    assert len(permissions) == len(set(permissions)) == 104  # attempt-2 asked 4 of the original 150, plus 100
    phases, _ = walk(lambda c: reader.phases(project, cursor=c, limit=11), 'code', 11)
    assert phases == sorted(phases) and len(phases) == len(set(phases)) == 70
    # The L1 counter is an aggregate over every node of the phase, equal to the L2 nodes it summarizes.
    [p1] = [p for p in reader.phases(project, limit=1)['items']]
    nodes = [n for n in walk(lambda c: reader.tasks(project, 'P001', cursor=c, limit=300), 'status', 300)[0]]
    assert p1['tasks']['total'] == sum(1 for n in nodes if n['class'] != 'inactive')
    engine.dispose()


def test_tokens_follow_every_displayed_source_and_ignore_foreign_changes(tmp_path, context, repository,  # noqa: F811
                                                                          migrated_database):
    """Finding 2: each scope's token changes with the sources its responses show (markers, retention of its own
    stream, configured agents) without bumping a run version, and stays put for changes elsewhere."""
    from my_harness.storage.retention import apply_retention, preview_retention
    from my_harness.storage.work_map import WorkMap
    from test_managed_api import PLAN, VERSIONS, make_context
    from test_observed_steps import CLAUDE, OVERSIZE, finish, invocation, scripted, settle
    url, database = migrated_database[0], migrated_database[0].removeprefix('sqlite:///')
    (tmp_path / 'a').mkdir(), (tmp_path / 'b').mkdir()  # separate artifact roots: retention of one stream only
    sealed_port, pending_port = scripted(tmp_path / 'a', OVERSIZE + CLAUDE[1:]), scripted(tmp_path / 'b', CLAUDE)

    def settled(port, role):
        job, claim, request, _ = settle(repository, context, port, role)
        finish(repository, job, claim)
        return job.run_id, request
    sealed_run, sealed = settled(sealed_port, 'executor')
    ObservedStepProjector(repository.engine).run_pending()
    pending_run, pending = settled(pending_port, 'reviewer')

    def run_version(run_id):
        with repository.engine.connect() as db:
            return db.scalar(text('SELECT version FROM managed_runs WHERE id = :id'), {'id': run_id})
    managed = config(context, supervisor=False)
    with client(url, tmp_path, managed) as http:
        steps = get(http, f'/projects/synthetic/runs/{pending_run}/steps')
        head = get(http, f'/projects/synthetic/invocations/{invocation(pending)}')
        trace = get(http, f'/projects/synthetic/invocations/{invocation(sealed)}/steps', limit=2)
        other = get(http, f'/projects/synthetic/invocations/{invocation(pending)}/steps')
        phases = get(http, '/projects/synthetic/phases')
        scopes = [steps['scope'], head['scope'], trace['scope'], other['scope'], phases['scope']]
        assert steps['items'][0]['steps']['state'] == 'pending' and head['steps']['state'] == 'pending'
        before = run_version(pending_run)

        # pending → sealed by the real projector: L3 and the L4 header change; the run's version does not.
        ObservedStepProjector(repository.engine).run_pending()
        assert run_version(pending_run) == before
        poll = {s['scope']: s['version'] for s in get(http, '/activity', scope=scopes)['scopes']}
        assert poll[steps['scope']] != steps['version'] and poll[head['scope']] != head['version']
        assert poll[trace['scope']] == trace['version']  # another invocation's seal never supersedes this trace
        reloaded = get(http, f'/projects/synthetic/runs/{pending_run}/steps')
        assert reloaded['version'] == poll[steps['scope']] and reloaded['items'][0]['steps']['state'] == 'sealed'
        stale = http.get(MAP + f'/projects/synthetic/invocations/{invocation(pending)}/steps',
                         params={'cursor': wm.cursor(other['scope'], other['version'], [1])})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'cursor_stale'  # its own seal

        # Retention of the sealed attempt's stdout changes its source-record availability: its trace token moves,
        # the old cursor is stale, the reloaded pages say so; the other invocation's trace token stays.
        other = get(http, f'/projects/synthetic/invocations/{invocation(pending)}/steps')
        options = dict(artifact_roots=[sealed_port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
        shown = preview_retention(database, **options)
        apply_retention(database, **options, preview_sha256=shown['preview_sha256'], reason='Synthetic retention',
                        confirmed=True, writers_stopped=True)
        poll = {s['scope']: s['version'] for s in get(http, '/activity', scope=[trace['scope'], other['scope']])['scopes']}
        assert poll[trace['scope']] != trace['version'] and poll[other['scope']] == other['version']
        stale = http.get(MAP + f'/projects/synthetic/invocations/{invocation(sealed)}/steps',
                         params={'cursor': trace['next_cursor']})
        assert stale.status_code == 409
        whole, _, last = pages(http, f'/projects/synthetic/invocations/{invocation(sealed)}/steps', limit=2)
        assert last['version'] == poll[trace['scope']]
        assert {r['availability'] for s in whole for r in s['source_records'] if r['oversize']} == {
            'unavailable_after_retention'}

        # Activity in another project does not supersede this project's phases or traces; it does move L0.
        projects = get(http, '/projects')
        phases = get(http, '/projects/synthetic/phases')
        (tmp_path / 'elsewhere').mkdir()
        __import__('subprocess').run(['git', 'init', '--quiet', str(tmp_path / 'elsewhere')], check=True)
        elsewhere = make_context(tmp_path / 'elsewhere')
        repository.submit(elsewhere, 'P009-T001', 'P009', PLAN, VERSIONS, key='elsewhere')
        poll = {s['scope']: s['version'] for s in get(http, '/activity', scope=[
            projects['scope'], phases['scope'], trace['scope']])['scopes']}
        assert poll[phases['scope']] == phases['version'] and poll[projects['scope']] != projects['version']
        assert poll[trace['scope']] == get(http, f'/projects/synthetic/invocations/{invocation(sealed)}/steps')['version']

    # Configured agents shown at L0: a different model for the same roots is a different version.
    roots = {'synthetic': str(context.root)}
    first = WorkMap(repository.engine, roots, {str(context.root): {'reviewer': {'model': 'synthetic-a'}}}).projects()
    second = WorkMap(repository.engine, roots, {str(context.root): {'reviewer': {'model': 'synthetic-b'}}}).projects()
    assert first['version'] != second['version']
    card = lambda page: next(i for i in page['items'] if i['registered_project_id'] == 'synthetic')  # noqa: E731
    assert card(first)['configuration'] != card(second)['configuration']
    assert card(first)['configuration'] == {'reviewer': {'model': 'synthetic-a'}}
    phase_scope = WorkMap(repository.engine, roots).phases('synthetic')['scope']
    versions = {model: WorkMap(repository.engine, roots, {str(context.root): {'reviewer': {'model': model}}})
                .activity([first['scope'], phase_scope])['scopes'] for model in ('synthetic-a', 'synthetic-b')}
    assert versions['synthetic-a'][0]['version'] == first['version'] != versions['synthetic-b'][0]['version']
    assert versions['synthetic-a'][1]['version'] != versions['synthetic-b'][1]['version']  # J/circles read it too


def test_a_rejected_acceptance_is_projected_as_rejected_not_accepted(git_repo, migrated_database, tmp_path):
    """Finding 3: the projected acceptance decision distinguishes absent, rejected and eligible; a deterministic
    rejection (a failing validation command) is `rejected` with its reasons, and nothing is committed."""
    from my_harness.core.engine.validation import CommandResult
    from test_engine import PHASE_ID, TASK_ID
    from test_junit import managed_run
    context, repository, _supervisor, job, _agents = managed_run(git_repo, migrated_database, result=CommandResult(1))
    with repository.engine.connect() as db:
        projected = json.loads(db.scalar(text('SELECT acceptance_json FROM run_projections WHERE run_id = :r'),
                                         {'r': job.run_id}))
    assert projected['eligible'] is False and projected['reasons']  # the run projection T020 reads
    with client(migrated_database[0], tmp_path, config(context, supervisor=False)) as http:
        project = f'run:{job.run_id}'
        [node] = [n for n in get(http, f'/projects/{project}/phases/{PHASE_ID}/tasks')['items'] if n['code'] == TASK_ID]
        acceptance = node['latest']['acceptance']
        assert acceptance['state'] == 'rejected' and acceptance['eligible'] is False
        assert acceptance['reasons'] == [r[:199] + '…' if len(r) > 200 else r for r in projected['reasons']][:20]
        assert node['latest']['commit'] is None and node['status'] == {'code': 'STOPPED', 'class': 'inactive'}
        [run] = get(http, f'/projects/{project}/phases/{PHASE_ID}/tasks/{TASK_ID}/runs')['items']
        assert run['acceptance'] == acceptance and run['commit'] is None
    from my_harness.storage.work_map import acceptance as project_acceptance
    assert project_acceptance(None)['state'] == 'absent' and project_acceptance(None)['source'] == 'absent'
    assert project_acceptance(json.dumps({'eligible': True, 'reasons': []}))['state'] == 'eligible'
    assert project_acceptance('{"eligible": "yes"}')['state'] == 'unknown'


def test_standing_permission_validity_follows_t010_ancestry_and_matches_the_inbox(world, tmp_path):
    """Finding 4: a request whose ancestry expired or ended can no longer be answered; a historical grant is kept
    apart from the authority it confers now (expired or ended grants). Same canonical rule as T010 and T017."""
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    from my_harness.services.permission_lifecycle import PermissionLifecycle
    from my_harness.storage.models import PermissionRecordRow
    w = world
    engine = w.repository.engine
    with engine.connect() as db:
        run = db.scalar(text("SELECT id FROM managed_runs WHERE purpose = 'task'"))
        attempt = db.scalar(text("SELECT a.id FROM managed_attempts a JOIN usage_invocations i ON i.source_id = a.id "
                                 "WHERE a.run_id = :r AND i.role = 'executor'"), {'r': run})
    lifecycle = PermissionLifecycle(engine)
    ids = {}
    with Session(engine) as session, session.begin():
        def add(name, kind, **payload):
            ids[name] = lifecycle.append(session, w.project, kind, payload, f'map-{name}').id
            return ids[name]
        add('open', 'authorization', expires_at='2100-01-01T00:00:00.000000+00:00', grantee='executor')
        add('old', 'authorization', expires_at='2000-01-01T00:00:00.000000+00:00', grantee='executor')
        add('ended', 'authorization', grantee='executor')
        add('end-ancestor', 'end', record_id=ids['ended'])
        for name, parent in (('pending', 'open'), ('lapsed', 'old'), ('cut', 'ended'), ('granted', 'open'),
                             ('granted-expired', 'open'), ('granted-revoked', 'open')):
            add(name, 'request', source_attempt_id=attempt, parent=ids[parent], grantee='executor')
        add('grant', 'grant', request_id=ids['granted'], parent=ids['open'])
        add('grant-expired', 'grant', request_id=ids['granted-expired'], parent=ids['open'],
            expires_at='2001-01-01T00:00:00.000000+00:00')
        add('grant-revoked', 'grant', request_id=ids['granted-revoked'], parent=ids['open'])
        add('revocation', 'end', record_id=ids['grant-revoked'])
    with Session(engine) as session:
        canonical = {name: lifecycle.active(session, session.get(PermissionRecordRow, ids[name]))
                     for name in ('pending', 'lapsed', 'cut', 'grant', 'grant-expired', 'grant-revoked')}
    assert canonical == {'pending': True, 'lapsed': False, 'cut': False, 'grant': True, 'grant-expired': False,
                         'grant-revoked': False}
    invocation = f'managed_attempt:{attempt}'
    with client(w.url, tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        page = get(http, f'/projects/{w.project}/invocations/{invocation}/related', group='permissions')
        items = {i['id']: i for i in page['items'] if i['source'] == 'standing_permission'}
        view = {name: (items[ids[name]]['status']['code'], items[ids[name]]['status'].get('lapse'),
                       items[ids[name]]['response'], items[ids[name]]['authority'], items[ids[name]]['answerable'])
                for name in ('pending', 'lapsed', 'cut', 'granted', 'granted-expired', 'granted-revoked')}
        assert view == {'pending': ('PENDING', None, None, None, True),
                        'lapsed': ('EXPIRED', 'expired', None, None, False),
                        'cut': ('REVOKED', 'ended', None, None, False),
                        'granted': ('GRANTED', None, 'grant', 'effective', False),
                        'granted-expired': ('GRANTED', None, 'grant', 'expired', False),
                        'granted-revoked': ('GRANTED', None, 'grant', 'ended', False)}
        assert items[ids['pending']]['status']['class'] == 'waiting'
        assert {items[ids[n]]['status']['class'] for n in ('lapsed', 'cut')} == {'inactive'}
        # T017 parity: exactly the answerable request is an unresolved inbox item.
        inbox = {i['request_id']: i for i in http.get('/api/managed/inbox', params={
            'project': w.project, 'kind': 'permission', 'limit': 100}).json()['items']}
        assert {name for name in view if not inbox[ids[name]]['resolved']} == {'pending'}
        # Time alone changes validity: the related token moves when the open ancestor expires.
        scope, version = page['scope'], page['version']
        http.app.state.runtime.repository.clock = lambda: datetime(2101, 1, 1, tzinfo=timezone.utc)
        [moved] = get(http, '/activity', scope=[scope])['scopes']
        assert moved['version'] != version
        later = {i['id']: i for i in get(http, f'/projects/{w.project}/invocations/{invocation}/related',
                                            group='permissions')['items']}
        assert later[ids['pending']]['status']['code'] == 'EXPIRED' and not later[ids['pending']]['answerable']
        assert later[ids['granted']]['authority'] == 'expired'
        inbox = {i['request_id']: i for i in http.get('/api/managed/inbox', params={
            'project': w.project, 'kind': 'permission', 'limit': 100}).json()['items']}
        assert inbox[ids['pending']]['resolved']


def test_other_lanes_judge_history_circle_targets_and_waiting(world, tmp_path):
    """Finding 5: active preparation and project-scoped configuration assistance appear from their own ledgers
    (no managed attempt is manufactured; their steps stay lane-excluded); a global assistance stays explicitly
    unscoped; J appears where a judge actually ran; each circle names its latest invocation, which opens L4; a
    circle can wait on the owner with nothing running."""
    w = world
    engine = w.repository.engine
    root = str(w.context.root)
    with engine.connect() as db:
        task_run = db.scalar(text("SELECT id FROM managed_runs WHERE purpose = 'task'"))
        executor = db.scalar(text("SELECT i.id FROM usage_invocations i WHERE i.run_id = :r AND i.role = 'executor'"),
                             {'r': task_run})
    with engine.connect() as db:
        before = db.scalar(text('SELECT version FROM managed_runs WHERE id = :r'), {'r': task_run})
    managed = config(w.context, w.ports, supervisor=False)
    with client(w.url, tmp_path, managed) as http:
        card = next(i for i in get(http, '/projects')['items'] if i['id'] == w.project)
        circles = {c['circle']: c for c in card['circles']}
        assert 'J' not in circles  # no judge profile and no judge has run here
        assert circles['E']['latest_invocation']['invocation_id'] == executor and not circles['E']['inert']
        assert circles['H']['waiting'] and not circles['H']['active'] and circles['H']['bubbles'] == 1
        phases = get(http, f'/projects/{w.project}/phases')['items']
        p2 = {c['circle']: c for c in phases[1]['circles']}
        assert p2['R']['inert'] and p2['R']['latest_invocation'] is None and 'J' not in p2

        # A judge invocation that ran (settled) on the task: J is shown from that history, everywhere it ran.
        judge = inflight(engine, task_run, role='judge')
        with engine.begin() as db:
            db.execute(text("UPDATE managed_attempts SET result_json = '{}', status = 'COMPLETED' WHERE id = :a"),
                       {'a': judge})
            db.execute(text("UPDATE managed_processes SET status = 'STOPPED' WHERE id = :a"), {'a': judge})
        for path in ('/projects', f'/projects/{w.project}/phases', f'/projects/{w.project}/phases/P001/tasks'):
            node = get(http, path)['items'][0]
            j = {c['circle']: c for c in node['circles']}['J']
            assert j['shown'] == 'judge_history' and j['latest_invocation']['invocation_id'] == f'inv-{judge}', path
        target = get(http, f'/projects/{w.project}/invocations/inv-{judge}')
        assert target['invocation']['role'] == 'judge' and target['owner']['task'] == 'P001-T001'
        assert 'J' not in {c['circle'] for c in get(http, f'/projects/{w.project}/phases')['items'][1]['circles']}
        # A judge profile shows J without history (configured agents, ordinary mode only).
        from my_harness.storage.work_map import WorkMap
        profiled = WorkMap(engine, {'synthetic': root}, {root: {'judge': {'model': 'synthetic-judge'}}})
        p2 = {c['circle']: c for c in profiled.phases(w.project)['items'][1]['circles']}
        assert p2['J']['shown'] == 'judge_profile' and p2['J']['inert']

        # Preparation and configuration assistance in progress, written as their own journals persist them.
        with closing(sqlite3.connect(w.url.removeprefix('sqlite:///'))) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute("""INSERT INTO registered_projects (id, version, status, root, row, row_sha256, trust,
                created_at, updated_at) VALUES ('synthetic-registry', 1, 'ACTIVE', ?, '{}', ?, '{}', ?, ?)""",
                       (root, '0' * 64, NOW, NOW))
            db.execute("""INSERT INTO project_preparation_operations (id, project_id, root, idempotency_key,
                request_sha256, version, status, reserved, plan, plan_sha256, created_at, updated_at) VALUES
                ('prep-1', 'synthetic-registry', ?, 'prep-key', ?, 1, 'RUNNING', 1, '{}', ?, ?, ?)""",
                       (root, '0' * 64, '0' * 64, NOW, NOW))
            for step, number, kind in (('step-exec', 1, 'executor'), ('step-cmd', 2, 'command')):
                db.execute("""INSERT INTO project_preparation_steps (id, operation_id, number, spec, status)
                    VALUES (?, 'prep-1', ?, ?, 'STARTED')""", (step, number, json.dumps({'kind': kind})))
                db.execute("""INSERT INTO managed_processes (id, preparation_id, spec, status)
                    VALUES (?, 'prep-1', '{}', 'RUNNING')""", (step,))
            db.execute("""INSERT INTO usage_invocations (id, source_kind, source_id, preparation_id, preparation_step_id,
                root, project_id, purpose, role, agent, versions, launch, started_at, recorded_at, updated_at) VALUES
                ('preparation_step:step-exec', 'preparation_step', 'step-exec', 'prep-1', 'step-exec', ?,
                 'synthetic-registry', 'preparation', 'executor', 'executor', '{}', 'pending', ?, ?, ?)""",
                       (root, NOW, NOW, NOW))
            db.execute("""INSERT INTO registered_projects (id, version, status, root, row, row_sha256, trust,
                created_at, updated_at) VALUES ('foreign-registry', 1, 'ACTIVE', ?, '{}', ?, '{}', ?, ?)""",
                       (root + '-foreign', '0' * 64, NOW, NOW))
            for ident, scope in (('assist-1', 'synthetic-registry'), ('assist-2', None),
                                 ('assist-3', 'foreign-registry')):
                db.execute("""INSERT INTO configuration_operations (id, format, kind, status, idempotency_key,
                    request_sha256, payload, created_at, updated_at) VALUES (?, 'synthetic', 'ASSIST', 'INTENDED', ?,
                    ?, '{"process": {"status": "RUNNING"}}', ?, ?)""", (ident, ident, '0' * 64, NOW, NOW))
                db.execute("""INSERT INTO usage_invocations (id, source_kind, source_id, operation_id, project_id,
                    purpose, role, agent, versions, launch, started_at, recorded_at, updated_at) VALUES
                    (?, 'configuration_assistance', ?, ?, ?, 'configuration_assistance', 'configuration', 'reviewer',
                     '{}', 'pending', ?, ?, ?)""", (f'configuration_assistance:{ident}', ident, ident, scope, '2090-01-01' if ident == 'assist-1' else '2091-01-01', NOW, NOW))
            db.commit()
        card = next(i for i in get(http, '/projects')['items'] if i['id'] == w.project)
        lanes = {a['source_kind']: a for a in card['active_invocations']}
        assert lanes['preparation_step']['circle'] == 'E' and lanes['preparation_step']['attempt_id'] is None
        assert lanes['preparation_step']['lane'] == 'preparation' and lanes['preparation_step']['run_id'] is None
        assert lanes['configuration_assistance']['circle'] == 'R'
        assert lanes['configuration_assistance']['invocation_id'] == 'configuration_assistance:assist-1'
        lit = {c['circle']: c for c in card['circles']}
        assert lit['E']['active'] and lit['R']['active'] and lit['H']['active']
        assert lit['R']['latest_invocation']['invocation_id'] == 'configuration_assistance:assist-1'
        assert [h['reason'] for h in lit['H']['harness']] == ['preparation_command']
        assert card['status']['class'] == 'waiting'  # the owner wait still outranks the work in progress
        poll = get(http, '/activity')
        assert {a['source_kind'] for a in poll['active_invocations']} == {'preparation_step',
                                                                          'configuration_assistance'}
        assert [u['invocation_id'] for u in poll['unscoped_invocations']] == ['configuration_assistance:assist-2']
        assert poll['unscoped_invocations'][0]['reason'] == 'global_scope'
        for ident, lane in (('preparation_step:step-exec', 'preparation_step'),
                            ('configuration_assistance:assist-1', 'configuration_assistance')):
            head = get(http, f'/projects/{w.project}/invocations/{ident}')
            assert head['steps']['state'] == 'lane_excluded' and head['owner']['lane'] == lane
            assert head['invocation']['process'] and head['step'] is None and head['evidence'] is None
            assert get(http, f'/projects/{w.project}/invocations/{ident}/steps')['state'] == 'lane_excluded'
        for foreign in ('assist-2', 'assist-3'):
            assert http.get(MAP + f'/projects/{w.project}/invocations/configuration_assistance:{foreign}').status_code == 404
        with engine.begin() as db:
            db.execute(text("UPDATE configuration_operations SET status = 'APPLIED', payload = '{}' WHERE kind = 'ASSIST'"))
        settled = next(i for i in get(http, '/projects')['items'] if i['id'] == w.project)
        r = next(c for c in settled['circles'] if c['circle'] == 'R')
        assert not r['active'] and r['latest_invocation']['invocation_id'] == 'configuration_assistance:assist-1'
        head = get(http, f'/projects/{w.project}/invocations/configuration_assistance:assist-1')
        assert head['owner']['lane'] == 'configuration_assistance' and head['steps']['state'] == 'lane_excluded'
        with engine.connect() as db:
            foreign = WorkMap(engine)._latest(db, root + '-foreign')
            assert foreign['R']['invocation_id'] == 'configuration_assistance:assist-3'
        with engine.connect() as db:
            assert db.scalar(text('SELECT count(*) FROM managed_attempts WHERE run_id IS NULL')) == 0
            assert db.scalar(text('SELECT version FROM managed_runs WHERE id = :r'), {'r': task_run}) == before


@pytest.mark.parametrize('grant_parent', [False, True])
def test_grant_alone_expiring_refreshes_permissions_and_invalidates_cursor(world, tmp_path, grant_parent):
    """Time is a displayed dependency even when only the answer grant (or its own parent) expires."""
    from datetime import datetime, timezone
    from sqlalchemy.orm import Session
    from my_harness.services.permission_lifecycle import PermissionLifecycle
    w = world
    with w.repository.engine.connect() as db:
        attempt, invocation, run = db.execute(text("""SELECT i.attempt_id, i.id, i.run_id FROM usage_invocations i
            JOIN managed_runs r ON r.id = i.run_id WHERE r.purpose = 'task' AND i.role = 'executor' LIMIT 1""")).one()
        version = db.scalar(text('SELECT version FROM managed_runs WHERE id = :r'), {'r': run})
    lifecycle = PermissionLifecycle(w.repository.engine)
    with Session(w.repository.engine) as session, session.begin():
        def add(kind, payload, key):
            return lifecycle.append(session, w.project, kind, payload, key).id
        permanent = add('authorization', {'grantee': 'executor'}, 'permanent')
        request = add('request', {'parent': permanent, 'source_attempt_id': attempt}, 'grant-clock-request')
        add('grant', {'parent': permanent, 'request_id': request,
                      **({'expires_at': '2026-11-05T11:00:00.000000+00:00'} if not grant_parent else {})}, 'grant-clock-answer')
        timed = add('authorization', {'expires_at': '2026-11-05T11:00:00.000000+00:00'} if grant_parent else {}, 'grant-parent')
        other = add('request', {'parent': permanent, 'source_attempt_id': attempt}, 'grant-parent-request')
        add('grant', {'parent': timed, 'request_id': other}, 'grant-parent-answer')
    marks = table_marks(w.url.removeprefix('sqlite:///'))
    with client(w.url, tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        repository = http.app.state.runtime.repository
        repository.clock = lambda: datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
        path = f'/projects/{w.project}/invocations/{invocation}/related'
        page = get(http, path, group='permissions', limit=1)
        before = {i['id']: i for i in pages(http, path, group='permissions', limit=1)[0]}
        assert page['next_cursor']
        assert {before[r]['authority'] for r in (request, other)} == {'effective'}
        assert get(http, '/activity', scope=[page['scope']])['scopes'][0]['version'] == page['version']
        repository.clock = lambda: datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        after = get(http, path, group='permissions', limit=1)
        later = {i['id']: i for i in pages(http, path, group='permissions', limit=1)[0]}
        assert later[request]['authority'] == ('effective' if grant_parent else 'expired')
        assert later[other]['authority'] == ('expired' if grant_parent else 'effective')
        assert all(later[r]['response'] == 'grant' and later[r]['status']['code'] == 'GRANTED'
                   for r in (request, other))
        assert after['version'] != page['version']
        assert get(http, '/activity', scope=[page['scope']])['scopes'][0]['version'] == after['version']
        stale = get(http, path, status=409, group='permissions', cursor=page['next_cursor'], limit=1)
        assert 'cursor_stale' in str(stale)
    with w.repository.engine.connect() as db:
        assert db.scalar(text('SELECT version FROM managed_runs WHERE id = :r'), {'r': run}) == version
    assert table_marks(w.url.removeprefix('sqlite:///')) == marks


def test_l2_middle_final_and_group_transitions_materialize_only_page(tmp_path, migrated_database, monkeypatch):
    from my_harness.storage import work_map as storage
    from my_harness.storage.database import make_engine
    from test_knowledge import OWNER, task
    engine = make_engine(migrated_database[0])
    project, root, _ = deep_world(tmp_path, migrated_database[0].removeprefix('sqlite:///'), engine)
    reader = storage.WorkMap(engine)
    original = reader._identity_tasks
    latest = reader._latest
    detail_calls = []
    def detail(*args, **kwargs):
        detail_calls.append((args[2:], kwargs))
        return latest(*args, **kwargs)
    monkeypatch.setattr(reader, '_latest', detail)
    calls = []
    def measured(*args, **kwargs):
        rows = original(*args, **kwargs)
        calls.append((len(rows), kwargs.get('keys_only', False)))
        return rows
    monkeypatch.setattr(reader, '_identity_tasks', measured)
    # Exact reproduced tail: 79, then one. No unbounded inspector read at exhaustion.
    cursor = reader.tasks(project, 'P001', limit=79)['next_cursor']
    calls.clear()
    assert len(reader.tasks(project, 'P001', cursor=cursor, limit=1)['items']) == 1
    assert all(n <= 2 for n, _ in calls), calls
    knowledge = KnowledgeRepository(engine)
    base = knowledge.head(project).id
    draft = knowledge.open_draft(project, base)
    with engine.connect() as db:
        phase = db.scalar(text("SELECT id FROM knowledge_items WHERE project_id = :p AND code = 'P001'"), {'p': project})
    for n in range(100, 140):
        item = knowledge.put(draft, 'task', f'P001-T{n:03d}', task('Large off-page inspector ' * 50))
        knowledge.link(draft, 'part_of', item, phase, position=n - 20)
    knowledge.adopt(draft, base, origin='owner_confirmed', actor=OWNER)
    def middle_and_tail():
        measured = []
        for offset in (3, 78, 80, 118):
            cursor = reader.tasks(project, 'P001', limit=offset)['next_cursor']
            calls.clear()
            detail_calls.clear()
            page = reader.tasks(project, 'P001', cursor=cursor, limit=1)
            measured.append(([i['code'] for i in page['items']], list(calls), len(detail_calls)))
        return measured
    before_growth = middle_and_tail()
    grow(migrated_database[0].removeprefix('sqlite:///'), root)
    assert middle_and_tail() == before_growth
    expected = [f'P001-T{n:03d}' for n in range(1, 81)] + [f'P001-T{n:03d}' for n in range(100, 140)] + [
        f'P001-T{n:03d}' for n in range(500, 550)]
    for size in (1, 7, 79):
        seen, cursor = [], None
        while True:
            calls.clear()
            detail_calls.clear()
            page = reader.tasks(project, 'P001', cursor=cursor, limit=size)
            assert len(detail_calls) == len(page['items'])
            assert all(n <= size + 1 for n, _ in calls), calls
            assert sum(n for n, keys in calls if not keys) <= size, calls
            seen += [i['code'] for i in page['items']]
            cursor = page['next_cursor']
            if cursor is None:
                break
        assert seen == expected and len(seen) == len(set(seen))
    engine.dispose()


@pytest.mark.parametrize('task_chat', [False, True])
def test_chat_circle_targets_follow_conversation_owner_active_and_settled(world, tmp_path, task_chat):
    w = world
    engine = w.repository.engine
    with engine.connect() as db:
        task = db.scalar(text("SELECT id FROM managed_runs WHERE purpose = 'task' LIMIT 1"))
    run = chat_run(engine, str(w.context.root), None if task_chat else w.phase_id)
    if task_chat:
        with engine.begin() as db:
            db.execute(text("UPDATE chat_conversations SET task_run_id = :task WHERE id = "
                            "(SELECT conversation_id FROM chat_turns WHERE run_id = :run)"),
                       {'task': task, 'run': run})
    foreign_run = chat_run(engine, str(w.context.root) + '-foreign', None)
    foreign = inflight(engine, foreign_run, role='chat', at='2099-01-01')
    first = inflight(engine, run, role='chat', at='2080-01-01')
    latest = inflight(engine, run, role='chat', at='2081-01-01')
    with client(w.url, tmp_path, config(w.context, w.ports, supervisor=False)) as http:
        for settled in (False, True):
            if settled:
                with engine.begin() as db:
                    db.execute(text("UPDATE managed_attempts SET result_json = '{}', status = 'COMPLETED' "
                                    "WHERE id IN (:a, :b)"), {'a': first, 'b': latest})
                    db.execute(text("UPDATE managed_processes SET status = 'STOPPED' WHERE id IN (:a, :b)"),
                               {'a': first, 'b': latest})
            paths = ['/projects', f'/projects/{w.project}/phases']
            if task_chat:
                paths.append(f'/projects/{w.project}/phases/P001/tasks')
            for path in paths:
                node = get(http, path)['items'][0]
                circle = next(c for c in node['circles'] if c['circle'] == 'R')
                assert circle['latest_invocation']['invocation_id'] == f'inv-{latest}'
                assert circle['latest_invocation']['started_at'] == '2081-01-01'
                assert circle['active'] is not settled
            head = get(http, f'/projects/{w.project}/invocations/inv-{latest}')
            assert head['owner']['phase'] == 'P001'
            assert head['owner']['task'] == ('P001-T001' if task_chat else None)
            p2 = get(http, f'/projects/{w.project}/phases')['items'][1]
            assert all(c['latest_invocation'] is None for c in p2['circles'])
            activity = get(http, '/activity')['active_invocations']
            mine = [i for i in activity if i['invocation_id'] == f'inv-{latest}']
            assert bool(mine) is not settled
            if mine:
                assert mine[0]['scope']['phase'] == 'P001'
                assert mine[0]['scope']['task'] == ('P001-T001' if task_chat else None)
            assert http.get(MAP + f'/projects/{w.project}/invocations/inv-{foreign}').status_code == 404


def test_retired_registry_preserves_settled_assistance_history_and_archive(tmp_path, migrated_database):
    """Retirement disables operations, without erasing persisted assistance ownership or read scopes."""
    from my_harness.storage.database import make_engine
    engine = make_engine(migrated_database[0])
    root = tmp_path / 'historical-checkout'
    root.mkdir()
    knowledge = KnowledgeRepository(engine)
    project = knowledge.project(str(root))
    foreign = knowledge.project(str(tmp_path / 'foreign-checkout'))
    with engine.begin() as db:
        for ident, checkout in (('historical-registry', str(root)), ('foreign-registry', str(tmp_path / 'foreign-checkout'))):
            db.execute(text("""INSERT INTO registered_projects (id, version, status, root, row, row_sha256, trust,
                created_at, updated_at) VALUES (:id, 1, 'ACTIVE', :root, '{}', :sha, '{}', :at, :at)"""),
                       {'id': ident, 'root': checkout, 'sha': '0' * 64, 'at': NOW})
        for ident, owner in (('settled', 'historical-registry'), ('foreign', 'foreign-registry'), ('global', None)):
            db.execute(text("""INSERT INTO configuration_operations (id, format, kind, status, idempotency_key,
                request_sha256, payload, created_at, updated_at) VALUES (:id, 'configuration-operation-1', 'ASSIST', 'APPLIED',
                :id, :sha, '{"owner_closed": true}', :at, :at)"""), {'id': ident, 'sha': '0' * 64, 'at': NOW})
            db.execute(text("""INSERT INTO usage_invocations (id, source_kind, source_id, operation_id, project_id,
                purpose, role, agent, versions, launch, started_at, finished_at, recorded_at, updated_at) VALUES
                (:inv, 'configuration_assistance', :id, :id, :owner, 'configuration_assistance', 'configuration',
                'reviewer', '{}', 'observed', :at, :at, :at, :at)"""),
                       {'id': ident, 'inv': f'configuration_assistance:{ident}', 'owner': owner, 'at': NOW})
        payload = json.dumps({'format': 'synthetic', 'channel': 'configuration'})
        db.execute(text("""INSERT INTO trace_events (event_id, dedupe_key, root, invocation_id, kind, source, payload,
            payload_sha256, truncated, redactions, recorded_at) VALUES ('historical-receipt', 'historical-receipt',
            NULL, 'configuration_assistance:settled', 'knowledge.receipt', 'measured', :payload, :sha, 0, 0, :at)"""),
                   {'payload': payload, 'sha': sha256(payload.encode()).hexdigest(), 'at': NOW})
        assert db.scalar(text("SELECT count(*) FROM configuration_operations WHERE status = 'INTENDED'")) == 0
        immutable = db.execute(text('SELECT * FROM usage_invocations ORDER BY id')).all()
    database = migrated_database[0].removeprefix('sqlite:///')
    invocation = 'configuration_assistance:settled'
    path = f'/projects/{project}/invocations/{invocation}'

    def read(http, *, archive=False):
        card = next(i for i in get(http, '/projects')['items'] if i['id'] == project)
        circle = next(c for c in card['circles'] if c['circle'] == 'R')
        assert circle['latest_invocation']['invocation_id'] == invocation and not circle['active']
        assert card['active_invocations'] == []
        head = get(http, path)
        steps = get(http, path + '/steps')
        records = get(http, path + '/related', group='records')
        permissions = get(http, path + '/related', group='permissions')
        assert head['owner']['lane'] == 'configuration_assistance'
        assert head['steps']['state'] == steps['state'] == 'lane_excluded'
        assert [i['event_id'] for i in records['items']] == ['historical-receipt']
        assert permissions['items'] == []
        responses = [head, steps, records, permissions]
        poll = get(http, '/activity', scope=[p['scope'] for p in responses])
        assert all(p['read_only_archive'] is archive for p in responses)
        assert poll['read_only_archive'] is archive and poll['polling']['enabled'] is not archive
        assert [(s['scope'], s['version']) for s in poll['scopes']] == [(p['scope'], p['version']) for p in responses]
        for rejected in (f'/projects/{foreign}/invocations/{invocation}',
                         f'/projects/{project}/invocations/configuration_assistance:foreign',
                         f'/projects/{project}/invocations/configuration_assistance:global'):
            for suffix, params in (('', {}), ('/steps', {}), ('/related', {'group': 'records'}),
                                   ('/related', {'group': 'permissions'})):
                assert get(http, rejected + suffix, status=404, **params)['detail']['code'] == 'map_not_found'
            bad_scope = wm.scope('invocation', rejected.split('/')[2], rejected.split('/')[-1])
            assert get(http, '/activity', scope=[bad_scope])['scopes'][0]['error'] == 'not_found'
        return responses, circle['latest_invocation']

    with TestClient(create_app(migrated_database[0], managed=ManagedConfig(supervisor=False)), base_url=LOCAL) as http:
        before = read(http)
        with engine.begin() as db:
            db.execute(text("UPDATE registered_projects SET status = 'RETIRED', version = version + 1 "
                            "WHERE id = 'historical-registry'"))
        after = read(http)
        assert strip(after[0]) == strip(before[0]) and after[1] == before[1]
        assert [(p['scope'], p['version']) for p in after[0]] == [(p['scope'], p['version']) for p in before[0]]
        assert http.app.state.runtime.projects == {}  # history never composes the checkout
    with engine.connect() as db:
        assert db.execute(text('SELECT * FROM usage_invocations ORDER BY id')).all() == immutable
        assert db.scalar(text("SELECT status FROM registered_projects WHERE id = 'historical-registry'")) == 'RETIRED'
    create_backup(database, tmp_path / 'history-backup', writers_stopped=True)
    restore_backup(tmp_path / 'history-backup', tmp_path / 'history-restored')
    root.rename(tmp_path / 'checkout-removed')
    restored = tmp_path / 'history-restored/state.sqlite3'
    digest = sha256(restored.read_bytes()).hexdigest()
    app = create_app(f'sqlite:///{restored}', managed=ManagedConfig(supervisor=False))
    with TestClient(app, base_url=LOCAL) as http:
        assert app.state.runtime.projects == {}
        archived = read(http, archive=True)
        assert strip(archived[0]) == strip(before[0]) and archived[1] == before[1]
        with app.state.runtime.engine.connect() as db:
            assert db.scalar(text('PRAGMA query_only')) == 1
    assert sha256(restored.read_bytes()).hexdigest() == digest
    engine.dispose()
