"""P002-T006 (D287): operation journal, correlated trace events, invocation linkage and conservative recovery.

Temporary SQLite migrated to head, synthetic graphs and knowledge, fake CLIs (`cli_process_probe.py`) through the
real adapter and supervisor journal; no installed agent, provider, network or real project. Threats: TM12 (replay
and crash without duplicated effects or inference), TM14 (ordered, deduplicated, source-labelled events; no double
counting), TM15 (bounded queries and payloads), TM17 (sanitized payloads, project isolation).
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import subprocess
import sys
import time
from threading import Event as ThreadEvent
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from my_harness.adapters.processes import identity
from my_harness.core.engine.contracts import AgentRequest, Attempt, Selection, context_snapshot
from my_harness.orchestration import (
    GraphDefinition, GraphRegistry, GraphRunner, JournalPort, OperationUncertain, operation_key, run_operation,
    wait_for,
)
from my_harness.services.managed import _Journal
from my_harness.services.managed_runtime import ManagedConfig, ManagedRuntime
from my_harness.storage import operation_journal as journal_module
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.graph_continuations import GraphContinuationRepository
from my_harness.storage.managed import OwnershipLost
from my_harness.storage.models import GraphThreadRow
from my_harness.storage.operation_journal import (
    InvocationOperation, JournalConflict, OperationJournal, record_envelope, record_event,
)
from test_cli_agents import wait_until
from test_domain_operations import ROOT, OWNER, refused, run, seed
from test_managed import PLAN, VERSIONS, context, repository  # noqa: F401  (fixtures)
from test_trace_observation import probe_adapter

OTHER_ROOT = '/synthetic/other'
TRACE_TABLES = ('workflow_operations', 'trace_events', 'trace_artifacts')


def rows(url, table, where=''):
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(f'SELECT * FROM {table} {where} ORDER BY 1')]


def thread(engine, thread_id='thread-1'):
    GraphContinuationRepository(engine).create(thread_id, 'synthetic', '1', 'f' * 64)
    return thread_id


@pytest.fixture
def world(migrated_database):
    url = migrated_database[0]
    engine = make_engine(url)
    yield url, engine, OperationJournal(engine)
    engine.dispose()


# Port, re-entry and uncertain operations (TM12) ----------------------------------------------------------------------

class State(TypedDict, total=False):
    ref: str
    state: str
    answer: str


def effect_graph(journal, root, effects):
    def act(state, config):
        port = JournalPort(journal, config['configurable']['thread_id'], root)
        record = run_operation(port, config, 'publish', 'sealed_effect', {'ref': state['ref']},
                               lambda: effects.append(state['ref']) or {'published': state['ref']})
        return {'state': record.state, 'answer': wait_for('owner_decision', {'ref': state['ref']})}

    def build():
        builder = StateGraph(State)
        builder.add_node('act', act)
        builder.add_edge(START, 'act')
        builder.add_edge('act', END)
        return builder
    return GraphDefinition('synthetic-effect', '1', build)


def test_a_resumed_node_reconciles_its_completed_operation_without_a_second_effect(world):
    url, engine, journal = world
    effects = []
    graphs = GraphRunner(engine, GraphRegistry([effect_graph(journal, ROOT, effects)]))
    assert graphs.start('synthetic-effect', 'thread-1', {'ref': 'rev-1'}).status == 'WAITING'
    done = graphs.resume('thread-1', 'approved')
    assert done.status == 'COMPLETED', done.detail
    assert done.values['state'] == 'COMPLETED' and effects == ['rev-1']
    [operation] = rows(url, 'workflow_operations')
    assert (operation['kind'], operation['status'], operation['root']) == ('sealed_effect', 'COMPLETED', ROOT)
    assert json.loads(operation['result']) == {'published': 'rev-1'}
    kinds = [event['kind'] for event in rows(url, 'trace_events')]
    assert kinds == ['operation.intended', 'operation.completed']
    assert journal.projection(operation['id']) == 'COMPLETED'


CRASH = '''
import os, sys
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from my_harness.orchestration import GraphDefinition, GraphRegistry, GraphRunner, JournalPort, run_operation
from my_harness.storage.database import make_engine
from my_harness.storage.operation_journal import OperationJournal


class State(TypedDict, total=False):
    ref: str
    state: str


def definition(journal, root, effect):
    def act(state, config):
        port = JournalPort(journal, config['configurable']['thread_id'], root)
        return {'state': run_operation(port, config, 'publish', 'sealed_effect', {'ref': state['ref']}, effect).state}

    def build():
        builder = StateGraph(State)
        builder.add_node('act', act)
        builder.add_edge(START, 'act')
        builder.add_edge('act', END)
        return builder
    return GraphDefinition('synthetic-crash', '1', build)


if __name__ == '__main__':
    url, root = sys.argv[1:]
    engine = make_engine(url)
    GraphRunner(engine, GraphRegistry([definition(OperationJournal(engine), root, lambda: os._exit(23))])).start(
        'synthetic-crash', 'thread-crash', {'ref': 'rev-1'})
'''


def test_a_crash_after_the_seal_stops_the_thread_and_is_never_reissued(world, tmp_path, monkeypatch):
    url, engine, journal = world
    module = tmp_path / 'crash_graph.py'
    module.write_text(CRASH)
    child = subprocess.run((sys.executable, str(module), url, ROOT), capture_output=True, text=True, timeout=60)
    assert child.returncode == 23, child.stderr  # sealed and committed, then the process died inside the effect
    [operation] = rows(url, 'workflow_operations')
    assert operation['status'] == 'INTENDED'
    assert journal.recover('thread-crash') == []  # RUNNING without confirmation: a live segment may still finish
    monkeypatch.syspath_prepend(str(tmp_path))
    from crash_graph import definition
    effects = []
    graphs = GraphRunner(engine, GraphRegistry([definition(journal, ROOT, lambda: effects.append(1) or {})]))
    recovered = graphs.recover('thread-crash', writer_stopped=True)
    assert (recovered.status, recovered.reason) == ('RECOVERY_REQUIRED', 'operation_uncertain') and effects == []
    [changed] = journal.recover('thread-crash')
    assert changed['status'] == 'UNCERTAIN'
    port = JournalPort(journal, 'thread-crash', ROOT)
    with pytest.raises(ValueError):
        journal.abandon(changed['operation_id'], reason=' ', actor={'principal': 'owner'})
    abandoned = journal.abandon(changed['operation_id'], reason='Owner checked: nothing published.',
                                actor={'principal': 'owner'})
    assert abandoned['status'] == 'ABANDONED'
    with pytest.raises(JournalConflict):
        journal.abandon(changed['operation_id'], reason='Again.', actor={'principal': 'owner'})
    assert port.seal(changed['key'], 'sealed_effect', {'ref': 'rev-1'}).state == 'ABANDONED'
    with pytest.raises(JournalConflict):
        port.seal(changed['key'], 'sealed_effect', {'ref': 'other'})  # same key, other references
    assert effects == []
    events = rows(url, 'trace_events')
    assert [e['kind'] for e in events] == ['operation.intended', 'operation.uncertain', 'operation.abandoned']
    assert [e['parent_event_id'] for e in events[1:]] == [e['event_id'] for e in events[:-1]]
    assert journal.projection(changed['operation_id']) == 'ABANDONED'
    # A sealed key without outcome in a fresh thread: run_operation stops instead of performing the effect.
    thread(engine, 'thread-2')
    other = JournalPort(journal, 'thread-2', ROOT)
    config = {'configurable': {'thread_id': 'thread-2'}, 'metadata': {}}
    other.seal(operation_key(config, 'x', {}), 'sealed_effect', {})
    with pytest.raises(OperationUncertain):
        run_operation(other, config, 'x', 'sealed_effect', {}, lambda: effects.append(2) or {})
    assert effects == []


def test_checkpoint_writes_wait_for_concurrent_journal_writes(world):
    """Node threads write the journal while LangGraph's executor writes checkpoints: no write fails on the lock."""
    import threading
    from my_harness.orchestration.saver import HarnessCheckpointSaver
    url, engine, journal = world
    thread(engine, 't')
    saver, errors = HarnessCheckpointSaver(engine), []
    config = {'configurable': {'thread_id': 't', 'checkpoint_ns': '', 'checkpoint_id': 'c0'}}

    def checkpoints():
        for number in range(200):
            try:
                saver.put_writes(config, [('x', number)], f'task-{number}')
            except Exception as error:  # noqa: BLE001
                errors.append(repr(error))
    worker = threading.Thread(target=checkpoints)
    worker.start()
    for number in range(200):
        journal.seal('t', ROOT, f'op-{number}', 'sealed_effect', {})
    worker.join()
    assert errors == [] and len(rows(url, 'graph_checkpoint_writes')) == 200


# Events: ordered, deduplicated, immutable, bounded (TM14, TM15, TM17) -------------------------------------------------

def test_events_are_ordered_deduplicated_immutable_and_sanitized(world):
    url, engine, journal = world
    thread(engine)
    with Session(engine) as session, session.begin():
        first = record_event(session, kind='synthetic.one', dedupe_key='k1', payload={'n': 1}, root=ROOT,
                             thread_id='thread-1')
        again = record_event(session, kind='synthetic.one', dedupe_key='k1', payload={'n': 1}, root=ROOT,
                             thread_id='thread-1')
        second = record_event(session, kind='synthetic.two', dedupe_key='k2', root=ROOT, thread_id='thread-1',
                              payload={'env': {'TOKEN': 'x'}, 'note': 'sk-ant-' + 'A' * 30, 'items': list(range(150))})
        assert again.id == first.id and second.id > first.id
        with pytest.raises(JournalConflict):
            record_event(session, kind='synthetic.one', dedupe_key='k1', payload={'n': 2}, root=ROOT,
                         thread_id='thread-1')
    [one, two] = rows(url, 'trace_events')
    payload = json.loads(two['payload'])
    assert payload['env'] == {'redacted': 'sensitive_key'} and 'sk-ant-' not in two['payload']
    assert two['truncated'] == 1 and two['redactions'] == 2 and one['source'] == 'derived'
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        for statement in ("UPDATE trace_events SET kind = 'x'", 'DELETE FROM trace_events',
                          'INSERT OR REPLACE INTO trace_events SELECT * FROM trace_events LIMIT 1'):
            with pytest.raises(sqlite3.DatabaseError, match='immutable'):
                db.execute(statement)


def test_envelopes_are_validated_before_they_become_events(world):
    url, engine, journal = world
    thread(engine)
    envelope = {'format': 'knowledge-delivery-1', 'invocation_id': 'managed_attempt:x', 'channel': 'initial_context',
                'entity_type': 'decision', 'stable_id': 'item-1', 'revision_id': 'rev-1', 'exposure': 'full',
                'digest': 'a' * 64, 'page': {'truncated': False}, 'failure': None}
    with Session(engine) as session, session.begin():
        with pytest.raises(JournalConflict):
            record_envelope(session, 'knowledge.read', envelope, dedupe_key='d0', invocation_id='managed_attempt:x')
        with pytest.raises(ValueError):
            record_envelope(session, 'knowledge.delivered', {**envelope, 'comprehended': True}, dedupe_key='d1',
                            invocation_id='managed_attempt:x')
    assert rows(url, 'trace_events') == []


# Domain command outcomes and their events (T005 audit sink) -----------------------------------------------------------

DOMAIN = '''
from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from my_harness.orchestration import GraphDefinition, domain_command


class State(TypedDict, total=False):
    expected: str
    draft: str
    replayed: bool


def definition(ops, root):
    def open_draft(state, config):
        outcome = domain_command(config, ops, root, 'knowledge.draft.open', {'expected_revision_id': state['expected']})
        return {'draft': outcome['draft_id'], 'replayed': outcome['replayed']}

    def build():
        builder = StateGraph(State)
        builder.add_node('open_draft', open_draft)
        builder.add_edge(START, 'open_draft')
        builder.add_edge('open_draft', END)
        return builder
    return GraphDefinition('synthetic-domain-trace', '1', build)
'''


def test_command_outcomes_and_refusals_carry_their_events_in_their_own_transactions(world, tmp_path, monkeypatch):
    url, engine, journal = world
    ops = ManagedRuntime(engine).domain_operations()
    ids, first = seed(ops)
    accepted = [e for e in rows(url, 'trace_events') if e['kind'] == 'domain.command_accepted']
    commands = rows(url, 'domain_commands', "WHERE outcome = 'ACCEPTED'")
    assert sorted(e['command_id'] for e in accepted) == sorted(c['command_id'] for c in commands)
    assert {e['root'] for e in accepted} == {ROOT} and {e['source'] for e in accepted} == {'supplied'}
    refused('stale_revision', lambda: run(ops, OWNER, 'knowledge.draft.open', {'expected_revision_id': None}, 'stale'))
    [refusal] = [e for e in rows(url, 'trace_events') if e['kind'] == 'domain.command_refused']
    assert json.loads(refusal['payload'])['refusal_code'] == 'stale_revision'
    module = tmp_path / 'domain_trace_graph.py'
    module.write_text(DOMAIN)
    monkeypatch.syspath_prepend(str(tmp_path))
    from domain_trace_graph import definition
    graphs = GraphRunner(engine, GraphRegistry([definition(ops, ROOT)]))
    assert graphs.start('synthetic-domain-trace', 'thread-1', {'expected': first['revision_id']}).status == 'COMPLETED'
    [operation] = rows(url, 'workflow_operations')
    [command] = rows(url, 'domain_commands', "WHERE channel = 'graph'")
    assert (operation['kind'], operation['status'], operation['command_id']) == (
        'domain_command', 'COMPLETED', command['command_id'])
    assert operation['key'] == json.loads(command['caller'])['operation_key']
    trace = journal.events(ROOT, 'thread-1')['items']
    assert [e['kind'] for e in trace] == ['operation.completed'] and trace[0]['command_id'] == command['command_id']

    def failing(session, row):
        raise RuntimeError('synthetic sink failure')
    from my_harness.services.domain_operations import DomainOperations
    from my_harness.storage.operation_journal import command_sink
    broken = DomainOperations(engine, audit_sinks=(command_sink, failing))
    before = {table: rows(url, table) for table in (*TRACE_TABLES, 'domain_commands', 'knowledge_revisions')}
    with pytest.raises(RuntimeError):
        run(broken, OWNER, 'knowledge.draft.open', {'expected_revision_id': first['revision_id']}, 'rolled-back')
    with pytest.raises(RuntimeError):  # a refusal whose event cannot be written is never reported as a refusal
        run(broken, OWNER, 'knowledge.draft.open', {'expected_revision_id': None}, 'unrecorded')
    assert {table: rows(url, table) for table in before} == before


# Agent invocations: fenced seal, ledger link, settlement and recovery (TM12, TM14) ----------------------------------

def started(repository, context, adapter=None, *, key='op-invocation', lease_seconds=30, role='planner'):
    if not thread_exists(repository.engine, 'thread-1'):
        thread(repository.engine)
    versions = {**VERSIONS, **(adapter.frozen_versions() if adapter else {})}
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, versions, key=str(uuid4()))
    claim = repository.claim(lease_seconds=lease_seconds)
    repository.register_owner(claim, identity())
    request = AgentRequest(str(uuid4()), role, Selection('synthetic-model', 'medium', 'test'),
                           'Return a synthetic JSON object', None, context_snapshot(context))
    spec = InvocationOperation('thread-1', key, {'task': 'P001-T001'}, origin={'kind': 'managed_job', 'id': 'job-synthetic'})
    request = repository.agent_started(claim, repository.get_run(job.run_id).history, request, spec)
    if adapter is not None:
        adapter.bind_process_journal(_Journal(repository, claim, ThreadEvent()))
    return job, claim, request


def thread_exists(engine, thread_id):
    with Session(engine) as session:
        return session.get(GraphThreadRow, thread_id) is not None


def record_result(repository, claim, job, request, result):
    history = repository.get_run(job.run_id).history
    repository.checkpoint(claim, replace(history, attempts=history.attempts + (Attempt(request, result),)),
                          'planner')


def operation_of(url, attempt_id):
    [row] = rows(url, 'workflow_operations', f"WHERE attempt_id = '{attempt_id}'")
    return row


def test_an_invocation_is_sealed_with_its_attempt_and_ledger_and_settles_once(tmp_path, context, repository,
                                                                               migrated_database):
    url = migrated_database[0]
    port = probe_adapter(tmp_path, 'success', usage=True)
    job, claim, request = started(repository, context, port)
    sealed = operation_of(url, request.id)
    [invocation] = rows(url, 'usage_invocations', f"WHERE attempt_id = '{request.id}'")
    assert sealed['status'] == 'INTENDED' and sealed['invocation_id'] == invocation['id'] == f'managed_attempt:{request.id}'
    assert (sealed['job_id'], sealed['owner_token']) == (job.id, claim.owner_token) and invocation['launch'] == 'pending'
    assert json.loads(sealed['refs']) == {'role': 'planner', 'task': 'P001-T001'}
    result = port.invoke(context, request)
    record_result(repository, claim, job, request, result)
    repository.checkpoint(claim, repository.get_run(job.run_id).history, 'planner')  # nothing settles twice
    settled = operation_of(url, request.id)
    assert settled['status'] == 'COMPLETED' and json.loads(settled['result']) == {'attempt_status': 'complete'}
    assert len(rows(url, 'usage_invocations')) == 1 and len(rows(url, 'usage_captures')) == 1
    events = OperationJournal(repository.engine).events(sealed['root'], 'thread-1')['items']
    assert [e['kind'] for e in events] == ['operation.intended', 'invocation.observed', 'operation.completed']
    observed = events[1]['payload']
    assert observed['format'] == 'trace-observation-1' and observed['termination']['class'] == 'completed'
    assert observed['counters']['harness_attempt']['value'] == 1 and observed['counters']['native_turns']['value'] == 1
    assert 'input_tokens' not in json.dumps(observed)  # amounts stay in the ledger, never copied into the trace
    assert events[1]['invocation_id'] == invocation['id'] and events[2]['parent_event_id'] == events[1]['event_id']
    again = AgentRequest(str(uuid4()), 'planner', Selection('synthetic-model', 'medium', 'test'),
                         'Return a synthetic JSON object', None, context_snapshot(context))
    with pytest.raises(JournalConflict):  # the same key never seals a second launch
        repository.agent_started(claim, repository.get_run(job.run_id).history, again,
                                 InvocationOperation('thread-1', 'op-invocation', {'task': 'P001-T001'}))
    assert len(rows(url, 'managed_attempts')) == len(rows(url, 'usage_invocations')) == 1


def test_a_supervisor_cancellation_with_exit_zero_settles_as_failed_cancelled(tmp_path, context, repository,
                                                                              migrated_database):
    url = migrated_database[0]
    port = probe_adapter(tmp_path, 'term_exit0')
    job, claim, request = started(repository, context, port)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(port.invoke, context, request)
        wait_until(lambda: any(e['kind'] == 'agent_event' for e in repository.events(job.run_id)))
        assert port.cancel(request.id).requested
        result = future.result(timeout=5)
    assert result.exit_code == 0 and result.status == 'cancelled'
    record_result(repository, claim, job, request, result)
    settled = operation_of(url, request.id)
    assert settled['status'] == 'FAILED' and json.loads(settled['error'])['code'] == 'cancelled'
    observed = [e for e in rows(url, 'trace_events') if e['kind'] == 'invocation.observed'][0]
    payload = json.loads(observed['payload'])
    assert payload['termination']['class'] == 'cancelled' and payload['usage']['view'] is None


def test_joint_rollback_leaves_no_attempt_ledger_or_operation(context, repository, migrated_database, monkeypatch):
    url = migrated_database[0]

    def broken(*args, **kwargs):
        raise RuntimeError('synthetic failure while sealing')
    monkeypatch.setattr(journal_module, '_transition_event', broken)
    with pytest.raises(RuntimeError):
        started(repository, context)
    assert rows(url, 'managed_attempts') == rows(url, 'usage_invocations') == rows(url, 'workflow_operations') == []


def test_expired_lease_and_stale_writer_leave_the_invocation_uncertain_until_confirmed_stopped(
        context, repository, migrated_database):
    url = migrated_database[0]
    journal = OperationJournal(repository.engine)
    job, claim, request = started(repository, context, lease_seconds=0.2)
    assert journal.recover('thread-1', writer_stopped=True) == []  # a live fenced owner may still record the result
    time.sleep(0.3)
    [changed] = journal.recover('thread-1')  # the lease expired: no proof of a stopped writer, nor of an outcome
    assert changed['status'] == 'UNCERTAIN'
    history = repository.get_run(job.run_id).history
    with pytest.raises(OwnershipLost):  # the stale writer cannot settle anything any more
        repository.checkpoint(claim, history, 'planner')
    assert operation_of(url, request.id)['status'] == 'UNCERTAIN'
    assert rows(url, 'managed_attempts')[0]['result_json'] is None
    assert repository.recover_expired() == [job.id]
    repository.close_owner(claim)
    record = repository.get_run(job.run_id)
    repository.confirm_stopped(job.id, owner_token=claim.owner_token, expected_version=record.version,
                               reason='Synthetic owner checked the writer stopped')
    settled = operation_of(url, request.id)
    assert settled['status'] == 'FAILED' and json.loads(settled['error'])['code'] == 'interrupted_outcome_unknown'
    [invocation] = rows(url, 'usage_invocations')
    assert invocation['launch'] == 'unknown_execution' and len(rows(url, 'usage_captures')) == 0
    port = JournalPort(journal, 'thread-1', settled['root'])
    assert port.seal(settled['key'], 'agent_invocation', {'role': 'planner', 'task': 'P001-T001'}).state == 'FAILED'
    assert [e['kind'] for e in journal.events(settled['root'], 'thread-1')['items']] == [
        'operation.intended', 'operation.uncertain', 'invocation.observed', 'operation.failed']


# Queries: bounded, isolated, read-only and available on restored archives (TM15, TM17) ---------------------------

def test_trace_queries_are_bounded_and_isolated_by_project(world):
    url, engine, journal = world
    thread(engine, 'thread-a')
    thread(engine, 'thread-b')
    a = JournalPort(journal, 'thread-a', ROOT)
    for number in range(130):
        record = a.seal(f'op-{number:03}', 'sealed_effect', {'n': str(number)})
        a.complete(record.key, {'n': number})
    JournalPort(journal, 'thread-b', OTHER_ROOT).seal('op-b', 'sealed_effect', {})
    with pytest.raises(JournalConflict):
        JournalPort(journal, 'thread-a', OTHER_ROOT).seal('op-moved', 'sealed_effect', {})
    page = journal.events(ROOT, 'thread-a', limit=500)
    assert len(page['items']) == 200 and page['next_after'] == page['items'][-1]['sequence']
    rest = journal.events(ROOT, 'thread-a', after=page['next_after'], limit=500)
    assert len(rest['items']) == 60 and rest['next_after'] is None
    sequences = [e['sequence'] for e in page['items'] + rest['items']]
    assert sequences == sorted(sequences) and len(set(sequences)) == 260
    operations = journal.operations(ROOT, 'thread-a', limit=500)
    assert len(operations['items']) == 130 and operations['next_offset'] is None
    assert journal.operations(ROOT, 'thread-a', limit=100)['next_offset'] == 100
    for root, thread_id in ((OTHER_ROOT, 'thread-a'), (ROOT, 'thread-b'), (ROOT, 'absent')):
        with pytest.raises(LookupError):
            journal.events(root, thread_id)
    for item in operations['items']:
        assert journal.projection(item['operation_id']) == item['status']


def test_restored_archives_serve_traces_without_writes_or_checkout(migrated_database, tmp_path):
    from fastapi.testclient import TestClient as AnonymousClient
    from session_client import TestClient
    from my_harness.api.app import create_app
    from test_knowledge_api import H, journey
    from test_managed_api import LOCAL, config, make_context
    url = migrated_database[0]
    checkout = tmp_path / 'checkout'
    checkout.mkdir()
    app = create_app(url, tmp_path / 'ui', managed=config(make_context(checkout)))
    with TestClient(app, base_url=LOCAL) as http:
        project, _draft, _head = journey(http)
        [root] = [row['root'] for row in rows(url, 'knowledge_projects') if row['id'] == project]
        engine = make_engine(url)
        journal = OperationJournal(engine)
        thread(engine, 'thread-1')
        port = JournalPort(journal, 'thread-1', root)
        port.complete(port.seal('op-1', 'sealed_effect', {'ref': 'r'}).key, {'note': 'synthetic'})
        offloaded = ('synthetic output line\n' * 80) + 'Bearer ' + 'z' * 24  # masked, then stored with its event
        with Session(engine) as session, session.begin():
            record_event(session, kind='synthetic.output', dedupe_key='output-1', payload={'output': offloaded},
                         root=root, thread_id='thread-1')
        [sha256] = [row['sha256'] for row in rows(url, 'trace_artifacts')]
        thread(engine, 'thread-other')
        JournalPort(journal, 'thread-other', OTHER_ROOT).seal('op-2', 'sealed_effect', {})
        engine.dispose()
        base = f'/api/managed/knowledge/projects/{project}/traces/thread-1'
        paths = ('', '/operations', '/events', f'/artifacts/{sha256}')
        live = {path: http.get(base + path).json() for path in paths}
        assert live[f'/artifacts/{sha256}']['content'].startswith('synthetic output line')
        assert 'Bearer zzzz' not in live[f'/artifacts/{sha256}']['content']
        assert live['']['status'] == 'RUNNING' and len(live['/operations']['items']) == 1
        assert 'Bearer zzzz' not in json.dumps(live['/events'])
        assert http.get(f'/api/managed/knowledge/projects/{project}/traces/thread-other').status_code == 404
        assert http.get(base + '/events?limit=101').status_code == 422
    with AnonymousClient(app, base_url=LOCAL) as anonymous:
        assert anonymous.get(base).status_code == 401
    create_backup(url.removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = f"sqlite:///{tmp_path / 'restored/state.sqlite3'}"
    before = {table: rows(restored, table) for table in TRACE_TABLES}
    assert before == {table: rows(url, table) for table in TRACE_TABLES}
    archive = create_app(restored, tmp_path / 'ui', managed=ManagedConfig(supervisor=True))
    with TestClient(archive, base_url=LOCAL) as http:
        assert {path: http.get(base + path).json() for path in paths} == live
        other = http.get(f'/api/managed/knowledge/projects/{project}/traces/thread-other/artifacts/{sha256}')
        assert other.status_code == 404
        absent = http.get('/api/managed/knowledge/projects/absent/traces/thread-1')
        assert absent.status_code == 404 and absent.json()['detail']['code'] == 'trace_unknown'
        assert http.post(base + '/events', headers=H).status_code in (405, 409)
    archived = OperationJournal(make_engine(restored))
    for write in (lambda: JournalPort(archived, 'thread-1', root).seal('op-3', 'sealed_effect', {}),
                  lambda: archived.recover('thread-1', writer_stopped=True)):
        with pytest.raises(PermissionError):
            write()
    assert {table: rows(restored, table) for table in TRACE_TABLES} == before


# Review findings of 2026-10-29 (regressions) -------------------------------------------------------------------------

def test_generic_completion_cannot_fabricate_an_invocation_success(context, repository, migrated_database):
    """Finding 1: an expired-lease invocation without result stays as its native evidence says."""
    url = migrated_database[0]
    journal = OperationJournal(repository.engine)
    job, claim, request = started(repository, context, lease_seconds=0.2)
    time.sleep(0.3)
    sealed = operation_of(url, request.id)
    port = JournalPort(journal, 'thread-1', sealed['root'])
    for attempt in (lambda: journal.complete('thread-1', sealed['root'], sealed['key'], {'ok': True}),
                    lambda: port.complete(sealed['key'], {'ok': True}),
                    lambda: port.seal('op-forged', 'agent_invocation', {'role': 'planner'}),
                    lambda: port.seal('op-command', 'domain_command', {'operation': 'x@1'}),
                    lambda: run_operation(port, {'configurable': {'thread_id': 'thread-1'}, 'metadata': {}}, 'x',
                                          'agent_invocation', {}, lambda: {'ok': True})):
        with pytest.raises(JournalConflict):
            attempt()
    after = operation_of(url, request.id)
    assert after['status'] == 'INTENDED' and after['result'] is None
    assert rows(url, 'usage_invocations')[0]['launch'] == 'pending'
    assert rows(url, 'managed_attempts')[0]['result_json'] is None
    assert [e['kind'] for e in rows(url, 'trace_events')] == ['operation.intended']
    assert len(rows(url, 'workflow_operations')) == 1
    # The evidence path still decides: the lease expired, so recovery says UNCERTAIN, never COMPLETED.
    assert journal.recover('thread-1')[0]['status'] == 'UNCERTAIN'


class Echo(TypedDict, total=False):
    ref: str
    text: str
    answer: str


def echo_graph(journal, root, effects, size):
    def act(state, config):
        port = JournalPort(journal, config['configurable']['thread_id'], root)
        record = run_operation(port, config, 'render', 'sealed_effect', {'ref': state['ref']},
                               lambda: effects.append(1) or {'text': 'r' * size, 'items': list(range(80))})
        return {'text': record.result['text'], 'answer': wait_for('owner_decision', {'ref': state['ref']})}

    def build():
        builder = StateGraph(Echo)
        builder.add_node('act', act)
        builder.add_edge(START, 'act')
        builder.add_edge('act', END)
        return builder
    return GraphDefinition('synthetic-echo', '1', build)


def test_results_within_the_contract_are_kept_for_the_replay(world):
    """Finding 2: a 2013-byte result with a string over 1 KiB is what the replay continues from."""
    url, engine, journal = world
    effects = []
    graphs = GraphRunner(engine, GraphRegistry([echo_graph(journal, ROOT, effects, 1680)]))
    assert graphs.start('synthetic-echo', 'thread-1', {'ref': 'rev-1'}).status == 'WAITING'
    [operation] = rows(url, 'workflow_operations')
    stored = json.loads(operation['result'])
    assert len(json.dumps(stored).encode()) == 2013 and stored['text'] == 'r' * 1680
    done = graphs.resume('thread-1', 'approved')
    assert done.status == 'COMPLETED', done.detail
    assert done.values['text'] == 'r' * 1680 and effects == [1]  # same result on replay, effect once
    thread(engine, 'thread-2')
    port = JournalPort(journal, 'thread-2', ROOT)
    too_large = port.seal('op-large', 'sealed_effect', {})
    for result in ({'text': 'x' * 17000}, {'note': 'sk-ant-' + 'A' * 30}, {'api_key': 'v'}, {'n': float('nan')}):
        with pytest.raises(JournalConflict):
            port.complete(too_large.key, result)
    assert port.seal('op-large', 'sealed_effect', {}).state == 'INTENDED'  # refused, never completed with a digest
    largest = port.seal('op-limit', 'sealed_effect', {})
    kept = port.complete(largest.key, {'text': 'y' * 16000})
    assert kept.result == {'text': 'y' * 16000}


def test_another_root_cannot_replay_read_reconcile_or_complete(world, context, repository, migrated_database):
    """Finding 3: the project root is checked on every port path."""
    url, engine, journal = world
    thread(engine, 'thread-a')
    mine, other = JournalPort(journal, 'thread-a', '/synthetic/a'), JournalPort(journal, 'thread-a', '/synthetic/b')
    sealed = mine.seal('op-1', 'sealed_effect', {'ref': 'r'})
    for attempt in (lambda: other.seal('op-1', 'sealed_effect', {'ref': 'r'}),
                    lambda: other.complete('op-1', {'stolen': True}),
                    lambda: journal.complete('thread-a', '/synthetic/b', 'op-1', {'stolen': True})):
        with pytest.raises(JournalConflict):
            attempt()
    assert mine.complete(sealed.key, {'value': 'mine'}).result == {'value': 'mine'}
    with pytest.raises(JournalConflict):  # a completed result cannot be read from another root either
        other.seal('op-1', 'sealed_effect', {'ref': 'r'})
    assert mine.seal('op-1', 'sealed_effect', {'ref': 'r'}).result == {'value': 'mine'}  # legitimate replay
    # An invocation settled natively cannot be reconciled through another root's port.
    job, claim, request = started(repository, context)
    invocation = operation_of(url, request.id)
    history = repository.get_run(job.run_id).history
    from my_harness.core.engine.contracts import AgentResult
    repository.checkpoint(claim, replace(history, attempts=history.attempts + (
        Attempt(request, AgentResult('{}', True, 0, status='complete')),)), 'planner')
    with pytest.raises(JournalConflict):
        JournalPort(journal, 'thread-1', OTHER_ROOT).seal(invocation['key'], 'agent_invocation',
                                                         {'role': 'planner', 'task': 'P001-T001'})
    assert JournalPort(journal, 'thread-1', invocation['root']).seal(
        invocation['key'], 'agent_invocation', {'role': 'planner', 'task': 'P001-T001'}).state == 'COMPLETED'


def discovery(invocation_id, count=50):
    return {'format': 'tool-discovery-1', 'invocation_id': invocation_id, 'action': 'search',
            'catalogue_sha256': 'a' * 64, 'query_sha256': 'b' * 64, 'query_length': 24,
            'results': [{'id': f'knowledge.{"synthetic_descriptor_" * 7}{n:02}', 'version': n + 1,
                         'schema_sha256': f'{n:02x}' * 32} for n in range(count)],
            'page': {'truncated': False}}


def test_offloaded_event_content_is_stored_verified_and_survives_restart_and_restore(context, repository, tmp_path,
                                                                                     migrated_database):
    """Finding 4: a valid 50-descriptor discovery envelope can be reconstructed from what was stored."""
    url = migrated_database[0]
    engine, journal = repository.engine, OperationJournal(repository.engine)
    _job, claim, request = started(repository, context)
    sealed = operation_of(url, request.id)
    ROOT = sealed['root']  # noqa: N806  (the invocation's project root)
    envelope = discovery(sealed['invocation_id'])
    assert 13000 < len(json.dumps(envelope)) < 15000  # about 14 KB
    with Session(engine) as session, session.begin():
        record_envelope(session, 'tool.discovered', envelope, dedupe_key='discovery-1',
                        invocation_id=envelope['invocation_id'], root=ROOT, thread_id='thread-1')
    [event] = [e for e in journal.events(ROOT, 'thread-1')['items'] if e['kind'] == 'tool.discovered']
    reference = event['payload']['artifact']
    assert event['payload']['truncated'] == 'payload' and event['truncated'] is True
    assert json.loads(journal.artifact(ROOT, 'thread-1', reference['sha256'])['content']) == envelope
    restarted = OperationJournal(make_engine(url))  # a new engine: nothing comes from memory
    assert json.loads(restarted.artifact(ROOT, 'thread-1', reference['sha256'])['content']) == envelope
    with pytest.raises(LookupError):
        restarted.artifact(OTHER_ROOT, 'thread-1', reference['sha256'])
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        for statement in ("UPDATE trace_artifacts SET content = x'00'", 'DELETE FROM trace_artifacts'):
            with pytest.raises(sqlite3.DatabaseError, match='immutable'):
                db.execute(statement)
    restarted.engine.dispose()
    repository.close_owner(claim)  # the synthetic writer stops before the copy
    engine.dispose()
    create_backup(url.removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = OperationJournal(make_engine(f"sqlite:///{tmp_path / 'restored/state.sqlite3'}"))
    assert json.loads(restored.artifact(ROOT, 'thread-1', reference['sha256'])['content']) == envelope
    # Every reference in every event has its bytes; a forged reference is refused at write time.
    from my_harness.core.engine.trace_payload import artifact_references
    stored = {(row['event_id'], row['sha256']) for row in rows(url, 'trace_artifacts')}
    for row in rows(url, 'trace_events'):
        for item in artifact_references(json.loads(row['payload'])):
            assert (row['event_id'], item['sha256']) in stored
    engine = make_engine(url)
    with Session(engine) as session, session.begin():
        with pytest.raises(JournalConflict):
            record_event(session, kind='synthetic.forged', dedupe_key='forged', root=ROOT, thread_id='thread-1',
                         payload={'x': {'artifact': {'sha256': 'c' * 64, 'size': 1, 'media': 'text/plain'}}})
        with pytest.raises(JournalConflict):  # more than 1 MiB offloaded is refused, not truncated
            record_event(session, kind='synthetic.huge', dedupe_key='huge', root=ROOT, thread_id='thread-1',
                         payload={f'k{n}': f'{n}' + 'z' * 20000 for n in range(60)})
    assert not [e for e in rows(url, 'trace_events') if e['dedupe_key'] in ('forged', 'huge')]


def test_refs_and_origin_are_bounded_and_refused_before_any_write(world):
    """Finding 5: references and origin are validated, never coerced, and refusals write nothing."""
    url, engine, journal = world
    thread(engine)
    port = JournalPort(journal, 'thread-1', ROOT)
    for refs in ({'blob': 'x' * 36000}, {'api_key': 'value'}, {'ref': 'sk-ant-' + 'A' * 30}, {'n': 1},
                 {'Upper': 'x'}, {'ref': 'line\nbreak'}, {'ref': ''}, {f'k{n}': 'v' for n in range(33)}):
        with pytest.raises(JournalConflict):
            port.seal('op-x', 'sealed_effect', refs)
    for origin in ({'kind': 'managed_job', 'id': 'job-1', 'api_key': 'x'}, {'kind': 'prompt', 'id': 'x'},
                   {'kind': 'managed_job'}, {'kind': 'managed_job', 'id': 'has space'}, 'job-1'):
        with pytest.raises(JournalConflict):
            JournalPort(journal, 'thread-1', ROOT, origin=origin).seal('op-y', 'sealed_effect', {})
        with pytest.raises(JournalConflict):
            InvocationOperation('thread-1', 'op-z', {}, origin=origin)
    with pytest.raises(JournalConflict):
        InvocationOperation('thread-1', 'op-z', {'prompt': 'Write the code'})
    assert rows(url, 'workflow_operations') == [] and rows(url, 'trace_events') == []
    limit = {f'k{n:02}': 'v' * 200 for n in range(32)}
    origin = {'kind': 'managed_job', 'id': 'job-1'}
    JournalPort(journal, 'thread-1', ROOT, origin=origin).seal('op-ok', 'sealed_effect', limit)
    [item] = journal.operations(ROOT, 'thread-1')['items']
    assert item['refs'] == limit and item['origin'] == origin


def test_references_inside_an_offloaded_payload_are_checked_on_write_and_in_backups(world, tmp_path):
    """A payload over 8 KiB is stored as one JSON artifact; the references inside it must have their bytes too."""
    import hashlib
    from my_harness.storage.backup import BackupError
    url, engine, journal = world
    thread(engine)
    JournalPort(journal, 'thread-1', ROOT).seal('op-1', 'sealed_effect', {})
    forged = {'artifact': {'sha256': 'c' * 64, 'size': 10, 'media': 'text/plain; charset=utf-8'}}
    filler = {f'k{n:02}': 'f' * 900 for n in range(12)}  # over 8 KiB without any string over 1 KiB
    with Session(engine) as session, session.begin():
        with pytest.raises(JournalConflict):
            record_event(session, kind='synthetic.forged', dedupe_key='forged-nested', root=ROOT,
                         thread_id='thread-1', payload={'nested': forged, **filler})
    assert not [e for e in rows(url, 'trace_events') if e['dedupe_key'] == 'forged-nested']
    # Legitimate nesting: a string over 1 KiB is offloaded first, then the whole payload references it.
    long_text = 'synthetic long line\n' * 120
    with Session(engine) as session, session.begin():
        stored = record_event(session, kind='synthetic.nested', dedupe_key='nested', root=ROOT,
                              thread_id='thread-1', payload={'long': long_text, **filler}).payload
    outer = stored['artifact']
    assert outer['media'] == 'application/json' and stored['truncated'] == 'payload'
    inner = json.loads(journal.artifact(ROOT, 'thread-1', outer['sha256'])['content'])['long']['artifact']
    assert journal.artifact(ROOT, 'thread-1', inner['sha256'])['content'] == long_text
    engine.dispose()
    create_backup(url.removeprefix('sqlite:///'), tmp_path / 'good', writers_stopped=True)  # legitimate: verified
    # A forged reference written around the journal (inserts are not blocked by triggers) fails backup verification.
    content = json.dumps({'nested': forged, **filler}).encode()
    sha256 = hashlib.sha256(content).hexdigest()
    payload = json.dumps({'artifact': {'sha256': sha256, 'size': len(content), 'media': 'application/json'},
                          'truncated': 'payload'})
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        db.execute("INSERT INTO trace_events (event_id, dedupe_key, root, thread_id, kind, source, payload, "
                   "payload_sha256, truncated, redactions, recorded_at) VALUES ('forged-event', 'forged-raw', ?, "
                   "'thread-1', 'synthetic.forged', 'derived', ?, ?, 1, 0, '2026-10-29T00:00:00+00:00')",
                   (ROOT, payload, 'd' * 64))
        db.execute('INSERT INTO trace_artifacts (event_id, sha256, size, media, content) VALUES (?, ?, ?, ?, ?)',
                   ('forged-event', sha256, len(content), 'application/json', content))
        db.commit()
    with pytest.raises(BackupError, match='c' * 64):  # the missing nested reference, nothing else
        create_backup(url.removeprefix('sqlite:///'), tmp_path / 'forged', writers_stopped=True)
