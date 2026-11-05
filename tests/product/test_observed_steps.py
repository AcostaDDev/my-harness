"""P002-T019 (D305, D310): durable observed steps from sealed native streams.

Fake CLIs (`cli_process_probe.py`, scripted mode) through the real adapter, supervisor journal and repository on
temporary SQLite; no installed agent, provider or network. Threats: TM12 (crash, replay and recovery), TM14 (honest
steps and gaps), TM15 (bounds, pages, derivation outside settlement), TM17 (masking, no content).
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.core.engine import observed_steps as core
from my_harness.core.engine.domain_catalogue import digest
from my_harness.services.observed_steps import ObservedStepWorker
from my_harness.storage import observed_steps as storage
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.observed_steps import ObservedStepProjector, ObservedSteps
from my_harness.storage.operation_journal import record_event
from my_harness.storage.retention import apply_retention, preview_retention
from test_backup import db_path
from test_cli_agents import PROBE, setup_invocation, wait_until
from test_managed import context, repository  # noqa: F401  (fixtures)
from test_chat import chat  # noqa: F401  (fixture)
from test_operation_journal import record_result, rows, started
from test_phases import checkout, world  # noqa: F401  (fixtures)
from test_trace_observation import probe_adapter

SECRET = 'sk-ant-' + 'A1b2C3d4E5f6G7h8I9j0' * 2


# Fixtures and helpers -----------------------------------------------------------------------------------------------

def scripted(tmp_path, records, *, timeout=5, env=()):
    stream = tmp_path / f'stream-{uuid4()}.json'
    stream.write_text(json.dumps(records))
    environment = (('PROBE_STREAM', str(stream)), *env)
    configs = [CLIConfig(provider, (sys.executable, PROBE, provider, 'scripted'), version, environment, timeout)
               for provider, version in (('codex', '0.163.0'), ('claude', '2.1.304'))]
    return CLIProcessAdapter(configs, tmp_path / 'captures')


def settle(repository, context, port, role, *, operation=False):
    if operation:
        job, claim, request = started(repository, context, port, role=role, key=f'op-{uuid4()}')
    else:
        job, claim, request = setup_invocation(repository, context, port, role)
    result = port.invoke(context, request)
    record_result(repository, claim, job, request, result)
    return job, claim, request, result


def invocation(request):
    return f'managed_attempt:{request.id}'


def steps(repository, request, **kwargs):
    reader, items, after = ObservedSteps(repository.engine), [], None
    while True:
        page = reader.page(invocation(request), after=after, **kwargs)
        items += page['items']
        after = page['next_after']
        if after is None:
            return page, items


def trace_text(url, request):
    events = rows(url, 'trace_events', f"WHERE invocation_id = '{invocation(request)}'")
    artifacts = rows(url, 'trace_artifacts')
    return json.dumps([e['payload'] for e in events]) + json.dumps([str(a['content']) for a in artifacts])


def line(value, sleep=None):
    return {'line': value, **({'sleep': sleep} if sleep else {})}


def assistant(ident, *blocks):
    return {'type': 'assistant', 'message': {'id': ident, 'model': 'claude-synthetic', 'content': list(blocks)}}


def stream_event(kind, **fields):
    return {'type': 'stream_event', 'event': {'type': kind, **fields}}


def tool_use(ident, name, arguments):
    return {'type': 'tool_use', 'id': ident, 'name': name, 'input': arguments}


def tool_result(ident, content, error=False):
    return {'type': 'user', 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': ident, 'content': content, 'is_error': error}]}}


def claude_result(denials=(), **fields):
    return {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': json.dumps({'result': 'ok'}),
            'num_turns': 2, 'permission_denials': list(denials), **fields}


def item(kind, ident, itype, **fields):
    return {'type': kind, 'item': {'id': ident, 'type': itype, **fields}}


CLAUDE = [line({'type': 'system', 'subtype': 'init', 'session_id': 'synthetic'}),
          line(stream_event('message_start', message={'id': 'msg_1'})),
          line(assistant('msg_1', {'type': 'thinking', 'thinking': 'synthetic private thought'})),
          line(assistant('msg_1', tool_use('toolu_1', 'Read', {'file_path': 'app/main.txt'}))),
          line(assistant('msg_1', tool_use('toolu_2', 'Bash', {'command': 'rm -rf build'}))),
          line(assistant('msg_1', tool_use('toolu_2', 'Bash', {'command': 'rm -rf build'}))),  # repeated record
          line(stream_event('message_stop'), sleep=0.06),
          line(tool_result('toolu_1', 'synthetic file body')),
          line(tool_result('toolu_2', 'synthetic refusal', True), sleep=0.03),
          line(stream_event('message_start', message={'id': 'msg_2'})),
          line(assistant('msg_2', tool_use('toolu_3', 'Glob', {'pattern': '*.txt'}))),
          line(tool_result('toolu_3', 'synthetic glob failure', True)),
          line(assistant('msg_3', {'type': 'text', 'text': 'synthetic visible answer'})),
          line(claude_result([{'tool_name': 'Bash', 'tool_use_id': 'toolu_2', 'tool_input': {'command': 'rm'}}]))]

CODEX = [line({'type': 'thread.started', 'thread_id': 'synthetic'}),
         line({'type': 'turn.started'}),
         line(item('item.started', 'item_0', 'command_execution', command='ls app', status='in_progress')),
         line(item('item.started', 'item_1', 'mcp_tool_call', server='harness', tool='search_tools',
                   arguments={'query': 'phase', 'key': 'k-1'}, status='in_progress'), sleep=0.05),
         line(item('item.completed', 'item_0', 'command_execution', command='ls app', status='completed',
                   aggregated_output='synthetic listing', exit_code=0)),
         line(item('item.completed', 'item_1', 'mcp_tool_call', server='harness', tool='search_tools',
                   arguments={'query': 'phase', 'key': 'k-1'}, result={'content': []}, status='completed')),
         line(item('item.started', 'item_2', 'command_execution', command='false', status='in_progress')),
         line(item('item.completed', 'item_2', 'command_execution', command='false', status='failed',
                   aggregated_output='', exit_code=1)),
         line(item('item.completed', 'item_3', 'file_change', changes=[{'path': 'app/x', 'kind': 'add'}],
                   status='completed')),
         line(item('item.completed', 'item_4', 'web_search', query='synthetic', status='declined')),
         line(item('item.completed', 'item_5', 'reasoning', text='synthetic private reasoning')),
         line(item('item.completed', 'item_6', 'agent_message', text=json.dumps({'result': 'ok'}))),
         line({'type': 'turn.completed', 'usage': {'input_tokens': 1}})]


def by_call(items):
    return {step['call_id']: step for step in items if step['kind'] == 'tool_call'}


def check_sources(repository, run_id, attempt_id, step):
    assert len(step['source_record']) <= core.MAX_SOURCES
    for reference in step['source_record']:
        assert set(reference) == {'run_id', 'attempt_id', 'sequence', 'record', 'oversize'}
        assert (reference['run_id'], reference['attempt_id']) == (run_id, attempt_id)
        # Resolvable through the existing run event route's paging (T020 resolves; nothing is copied here).
        [event] = repository.events(run_id, after=reference['sequence'] - 1, limit=1)
        assert event['sequence'] == reference['sequence'] and event['payload']['record'] == reference['record']
        assert event['kind'] == 'agent_event'  # T018 §6.2: native rows only, never a parser diagnostic
        assert reference['oversize'] == ('original_reference' in event['payload'])
    if step.get('reason') in ('invalid_record', 'partial_tail') and 'stream_record' in step:
        assert step['source_record'] == []  # the gap keeps its position and the parser's record number only


# Per-client derivation ----------------------------------------------------------------------------------------------

def test_claude_steps_keep_order_correlation_parallelism_errors_denials_and_sources(tmp_path, context, repository,
                                                                                  migrated_database):
    """TM14: ordinary settlement wakes the projector after its commit; no workflow operation is needed."""
    url = migrated_database[0]
    committed = []

    def notify(ids):  # the ordinary path runs after the settlement transaction committed
        [attempt] = rows(url, 'managed_attempts', f"WHERE id = '{request_holder[0]}'")
        committed.append(attempt['result_json'] is not None)
        return ObservedStepProjector(repository.engine).project_many(ids)
    request_holder = []
    repository.steps_notify = notify
    port = scripted(tmp_path, CLAUDE)
    job, claim, request = setup_invocation(repository, context, port, 'executor')
    request_holder.append(request.id)
    result = port.invoke(context, request)
    record_result(repository, claim, job, request, result)
    assert result.status == 'complete' and committed == [True]
    assert rows(url, 'workflow_operations') == []
    page, items = steps(repository, request)
    assert page['state'] == 'sealed' and page['lane'] == 'managed_attempt' and page['role'] == 'executor'
    assert [(s['seq'], s['kind']) for s in items] == [
        (0, 'turn'), (1, 'reasoning'), (2, 'tool_call'), (3, 'tool_call'), (4, 'turn'), (5, 'tool_call'),
        (6, 'turn'), (7, 'message'), (8, 'message')]
    assert {s['unit'] for s in items if s['kind'] == 'turn'} == {'claude_message'}
    calls = by_call(items)
    assert calls['toolu_1']['outcome'] == 'completed' and calls['toolu_1']['result']['present'] is True
    assert calls['toolu_2']['outcome'] == 'denied'  # permission_denials by tool use id overrides the error result
    assert calls['toolu_3']['outcome'] == 'error'  # is_error without a denial
    assert all(calls[c]['parent_seq'] == 0 for c in ('toolu_1', 'toolu_2')) and calls['toolu_3']['parent_seq'] == 4
    assert calls['toolu_1']['parallel'] and calls['toolu_2']['parallel'] and not calls['toolu_3']['parallel']
    assert items[0]['max_concurrency'] == 2 and items[4]['max_concurrency'] == 1
    assert calls['toolu_2']['source_record_count'] == 4  # two tool_use records, its result and the denial
    assert calls['toolu_1']['timing'] == 'chunk_receipt' and calls['toolu_1']['duration_ms'] >= 40
    assert calls['toolu_1']['tool'] == {'name': 'Read', 'origin': 'native'}
    assert items[1]['reasoning']['present'] and 'text' not in items[1]['reasoning']
    assert items[7]['message']['final'] is False and items[8]['message'] == {**items[8]['message'], 'final': True,
                                                                              'terminal': True}
    assert all(s['outcome'] == 'completed' for s in items if s['kind'] == 'turn')
    summary = page['summary']
    assert summary['coverage'] == 'complete' and summary['client'] == 'claude' and summary['absent'] == []
    assert summary['counts']['tool_call'] == {'completed': 1, 'denied': 1, 'error': 1}
    assert summary['last_record'] == 14 and summary['stdout']['size'] > 0 and summary['max_concurrency'] == 2
    for step in items:
        check_sources(repository, job.run_id, request.id, step)
    # Content stays in the original records only: message, reasoning and result text never enter the trace.
    text = trace_text(url, request)
    for content in ('synthetic private thought', 'synthetic file body', 'synthetic visible answer', 'refusal'):
        assert content not in text
    stored = rows(url, 'trace_events', f"WHERE kind = 'invocation.step'")
    assert {(r['source'], r['thread_id'], r['operation_id']) for r in stored} == {('measured', None, None)}


def test_codex_turns_items_failures_parallelism_and_broker_links_with_an_operation(tmp_path, context, repository,
                                                                                  migrated_database):
    url = migrated_database[0]
    port = scripted(tmp_path, CODEX)
    job, claim, request, result = settle(repository, context, port, 'planner', operation=True)
    assert result.status == 'complete'
    [operation] = rows(url, 'workflow_operations', f"WHERE attempt_id = '{request.id}'")
    # Broker evidence of the native harness call (T008/D289): linked by tool name and argument digest.
    call_id = str(uuid4())
    links = dict(root=operation['root'], thread_id=operation['thread_id'], operation_id=operation['id'],
                 invocation_id=invocation(request))
    with Session(repository.engine) as session, session.begin():
        called = record_event(session, kind='broker.called', dedupe_key=f'broker:call:{call_id}', payload={
            'broker': 'search_tools', 'arguments_sha256': digest({'query': 'phase', 'key': 'k-1'}),
            'call_id': call_id}, **links)
        found = record_event(session, kind='tool.discovered', dedupe_key=f'bridge:discovery:{uuid4()}',
                             payload={'format': 'tool-discovery-1', 'action': 'search'}, **links)
        done = record_event(session, kind='broker.result', dedupe_key=f'broker:result:{call_id}',
                            payload={'call_id': call_id, 'ok': True}, **links)
        ids = called.event_id, found.event_id, done.event_id
    assert [r['state'] for r in ObservedStepProjector(repository.engine).run_pending()] == ['sealed']
    page, items = steps(repository, request)
    assert [s['kind'] for s in items] == ['turn', 'tool_call', 'tool_call', 'tool_call', 'tool_call', 'tool_call',
                                          'reasoning', 'message']
    assert items[0]['unit'] == 'codex_turn' and items[0]['start_observed'] and items[0]['outcome'] == 'completed'
    calls = by_call(items)
    assert calls['item_0']['tool'] == {'name': 'command_execution', 'origin': 'native'}
    assert calls['item_1']['tool']['origin'] == 'harness_broker' and calls['item_1']['tool']['server'] == 'harness'
    assert calls['item_1']['tool']['links'] == {'call_event_id': ids[0], 'discovery_event_id': ids[1],
                                                'result_event_id': ids[2]}
    assert calls['item_0']['parallel'] and calls['item_1']['parallel'] and not calls['item_2']['parallel']
    assert items[0]['max_concurrency'] == 2 and calls['item_1']['duration_ms'] >= 30
    assert calls['item_2']['outcome'] == 'error' and calls['item_3']['outcome'] == 'completed'
    assert 'result' not in calls['item_3']  # a file change reports no result content
    assert calls['item_4']['outcome'] == 'unclassified' and calls['item_4']['status_code'] == 'declined'
    assert items[-1]['message']['final'] is True and items[-2]['reasoning']['present']
    summary = page['summary']
    assert summary['unit'] == 'codex_turn' and summary['coverage'] == 'complete'
    # Codex reports no denials and no per-request turns: absent with a reason, never zero.
    assert summary['absent'] == [{'signal': 'permission_denials', 'reason': 'not_reported_by_client'},
                                 {'signal': 'request_turns', 'reason': 'not_separable_by_client'}]
    assert 'denied' not in json.dumps(summary['counts'])
    stored = rows(url, 'trace_events', "WHERE kind IN ('invocation.step', 'invocation.steps_sealed')")
    assert {(r['thread_id'], r['operation_id']) for r in stored} == {(operation['thread_id'], operation['id'])}
    assert 'synthetic private reasoning' not in trace_text(url, request)
    for step in items:
        check_sources(repository, job.run_id, request.id, step)


@pytest.mark.parametrize('role', ['executor', 'planner', 'reviewer'])
def test_settlement_records_only_the_pending_marker_in_its_transaction(tmp_path, context, repository,
                                                                       migrated_database, role):
    """TM15: settlement stays bounded; parsing happens later, outside the writer transaction."""
    url = migrated_database[0]
    port = probe_adapter(tmp_path, 'success', usage=True)
    job, claim, request, result = settle(repository, context, port, role)
    markers = rows(url, 'trace_events', f"WHERE invocation_id = '{invocation(request)}'")
    assert [m['kind'] for m in markers] == ['invocation.steps_pending']
    assert json.loads(markers[0]['payload'])['attempt_id'] == request.id
    assert ObservedSteps(repository.engine).state(invocation(request))['state'] == 'pending'
    assert [r['state'] for r in ObservedStepProjector(repository.engine).run_pending()] == ['sealed']
    page, items = steps(repository, request)
    assert page['state'] == 'sealed' and items and page['summary']['coverage'] in ('complete', 'partial')
    assert ObservedStepProjector(repository.engine).run_pending() == []  # nothing owed any more


# Gaps: malformed, truncated, unsupported, cancelled, oversize -------------------------------------------------------

def test_malformed_truncated_and_unsupported_records_become_gaps_without_closing_open_work(
        tmp_path, context, repository):
    port = scripted(tmp_path, [
        line(assistant('msg_1', {'type': 'text', 'text': 'partial answer'})),
        {'raw': 'not json at all\n'},
        line({'type': 'future.event', 'opaque': True}),
        line(assistant('msg_1', tool_use('toolu_1', 'Read', {'file_path': 'app/main.txt'}))),
        {'raw': '{"type":"res'}])
    job, claim, request, result = settle(repository, context, port, 'executor')
    assert result.status == 'invalid'
    ObservedStepProjector(repository.engine).run_pending()
    page, items = steps(repository, request)
    assert [(s['kind'], s.get('reason'), s['outcome']) for s in items] == [
        ('turn', None, 'not_observed'), ('message', None, 'completed'),
        ('not_observed', 'invalid_record', 'not_observed'), ('not_observed', 'unsupported_event', 'not_observed'),
        ('tool_call', None, 'not_observed'), ('not_observed', 'partial_tail', 'not_observed')]
    assert items[3]['event_type'] == 'future.event' and items[2]['parent_seq'] == 0
    assert items[2]['source_record'] == [] and items[2]['stream_record'] == 2
    assert items[5]['source_record'] == [] and items[5]['stream_record'] == 5
    assert page['summary']['coverage'] == 'partial'
    assert set(page['summary']['coverage_reasons']) == {'not_observed_steps', 'no_terminal', 'open_turns',
                                                        'open_calls', 'final_answer_absent'}
    assert page['summary']['absent'] == [{'signal': 'permission_denials', 'reason': 'no_terminal'},
                                         {'signal': 'final_answer', 'reason': 'not_observed'}]
    for step in items:
        check_sources(repository, job.run_id, request.id, step)


def test_supervisor_cancellation_leaves_the_turn_and_call_in_flight(tmp_path, context, repository):
    port = probe_adapter(tmp_path, 'term_exit0')
    job, claim, request = setup_invocation(repository, context, port, 'planner')
    with ThreadPoolExecutor() as pool:
        future = pool.submit(port.invoke, context, request)
        wait_until(lambda: any(e['kind'] == 'agent_event' and e['payload'].get('original', {}).get('type')
                               == 'item.started' for e in repository.events(job.run_id)))
        assert port.cancel(request.id).requested
        result = future.result(timeout=5)
    record_result(repository, claim, job, request, result)
    ObservedStepProjector(repository.engine).run_pending()
    page, items = steps(repository, request)
    assert result.exit_code == 0 and page['summary']['termination'] == 'cancelled'
    assert [(s['kind'], s['outcome']) for s in items] == [
        ('turn', 'cancelled_in_flight'), ('tool_call', 'cancelled_in_flight'), ('not_observed', 'not_observed')]
    assert items[2]['reason'] == 'cancelled_in_flight' and items[2]['parent_seq'] == 0
    assert 'finished_at' not in items[1] and items[1]['duration_ms'] is None


def test_confirm_stopped_settles_an_interrupted_attempt_with_its_pending_projection(tmp_path, context, repository,
                                                                                   migrated_database):
    url = migrated_database[0]
    port = scripted(tmp_path, [line(stream_event('message_start', message={'id': 'msg_1'})),
                               line(assistant('msg_1', tool_use('toolu_1', 'Bash', {'command': 'sleep 9'}))),
                               {'hang': True}])
    job, claim, request = started(repository, context, port, role='executor', key='op-stop', lease_seconds=3)
    with ThreadPoolExecutor() as pool:
        future = pool.submit(port.invoke, context, request)
        wait_until(lambda: sum(e['kind'] == 'agent_event' for e in repository.events(job.run_id)) == 2)
        port.cancel(request.id)
        future.result(timeout=5)  # the writer died before recording the result
    expired = []
    wait_until(lambda: expired.extend(repository.recover_expired()) or expired, timeout=10)
    assert expired == [job.id]
    repository.close_owner(claim)
    assert rows(url, 'trace_events', "WHERE kind = 'invocation.steps_pending'") == []
    repository.confirm_stopped(job.id, owner_token=claim.owner_token,
                               expected_version=repository.get_run(job.run_id).version,
                               reason='Synthetic owner checked the writer stopped')
    [attempt] = rows(url, 'managed_attempts')
    assert attempt['status'] == 'INTERRUPTED'
    assert len(rows(url, 'trace_events', "WHERE kind = 'invocation.steps_pending'")) == 1
    ObservedStepProjector(repository.engine).run_pending()
    page, items = steps(repository, request)
    assert [(s['kind'], s['outcome']) for s in items] == [
        ('turn', 'cancelled_in_flight'), ('tool_call', 'cancelled_in_flight'), ('not_observed', 'not_observed')]
    [operation] = rows(url, 'workflow_operations')
    assert operation['status'] == 'FAILED'  # T006 semantics unchanged; steps sit beside it
    assert {r['operation_id'] for r in rows(url, 'trace_events', "WHERE kind = 'invocation.step'")} == {
        operation['id']}


OVERSIZE = [line(stream_event('message_start', message={'id': 'msg_1'})),
            line(assistant('msg_1', tool_use('toolu_big', 'Write', {'file_path': 'app/big.txt',
                                                                  'content': 'x' * 20000}))),
            line(tool_result('toolu_big', 'written')),
            line(claude_result())]


@pytest.mark.parametrize('damage', ['none', 'missing', 'corrupt_range', 'corrupt_elsewhere'])
def test_oversize_records_are_verified_against_the_capture_and_every_chunk(tmp_path, context, repository, damage):
    port = scripted(tmp_path, OVERSIZE)
    job, claim, request, result = settle(repository, context, port, 'executor')
    reference = next(e for e in repository.events(job.run_id, limit=1000) if e['kind'] == 'agent_event'
                     and 'original_reference' in e['payload'])['payload']['original_reference']
    stdout = port.artifact_root / request.id / 'stdout.bin'
    if damage == 'missing':
        stdout.unlink()
    elif damage != 'none':
        data = bytearray(stdout.read_bytes())
        position = reference['offset'] + 100 if damage == 'corrupt_range' else len(data) - 5
        data[position] ^= 1
        stdout.write_bytes(bytes(data))
    ObservedStepProjector(repository.engine).run_pending()
    page, items = steps(repository, request)
    if damage == 'none':
        call = by_call(items)['toolu_big']
        assert call['arguments']['size'] > 16384 and call['outcome'] == 'completed'
        assert len(call['arguments']['summary']) == 256 and call['arguments']['summary_truncated']
        assert call['source_record'][0]['oversize'] is True and page['summary']['oversize_unavailable'] == 0
        return
    gap = next(s for s in items if s['kind'] == 'not_observed')
    assert gap['reason'] == 'oversize_record_unavailable' and gap['source_record'][0]['oversize'] is True
    assert gap['detail'] == {'missing': 'stdout_missing', 'corrupt_range': 'chunk_digest_mismatch',
                             'corrupt_elsewhere': 'chunk_digest_mismatch'}[damage]
    assert (gap['record_size'], gap['record_sha256']) == (reference['size'], reference['sha256'])
    assert gap['event_type'] == 'assistant' and page['summary']['oversize_unavailable'] == 1
    assert page['summary']['unmatched'] == {'results': 1}  # its result is kept, never attached to a guess


def test_oversize_ranges_need_the_sealed_capture_and_a_path_without_links(tmp_path):
    import hashlib
    data = b'{"type":"assistant"}\n' * 3
    chunks = [(0, 30, hashlib.sha256(data[:30]).hexdigest()), (30, len(data) - 30, hashlib.sha256(data[30:]).hexdigest())]
    folder = tmp_path / 'real'
    folder.mkdir()
    path = folder / 'stdout.bin'
    path.write_bytes(data)
    reference = {'offset': 21, 'size': 21, 'sha256': hashlib.sha256(data[21:42]).hexdigest()}
    sealed = {'path': str(path), 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    assert storage.oversize_records(sealed, chunks, {5: reference})[5] == {'type': 'assistant'}
    # Chunk and range digests alone are not the sealed proof (D305, T018 §6.3).
    assert storage.oversize_records(None, chunks, {5: reference})[5].code == 'capture_absent'
    assert storage.oversize_records({**sealed, 'sha256': '0' * 64}, chunks, {5: reference})[5].code == \
        'stdout_digest_mismatch'
    assert storage.oversize_records({**sealed, 'size': len(data) + 1}, chunks, {5: reference})[5].code == \
        'stdout_digest_mismatch'
    assert storage.oversize_records(sealed, chunks[:1], {5: reference})[5].code == 'chunks_incomplete'
    wrong = storage.oversize_records(sealed, chunks, {5: {**reference, 'sha256': '1' * 64}})
    assert wrong[5].code == 'record_digest_mismatch'
    assert storage.oversize_records(sealed, chunks, {5: {**reference, 'size': 10**8}})[5].code == 'record_too_large'
    last = tmp_path / 'link.bin'
    last.symlink_to(path)
    assert storage.oversize_records({**sealed, 'path': str(last)}, chunks, {5: reference})[5].code == 'stdout_unsafe'
    middle = tmp_path / 'linked-folder'
    middle.symlink_to(folder, target_is_directory=True)
    assert storage.oversize_records({**sealed, 'path': str(middle / 'stdout.bin')}, chunks,
                                    {5: reference})[5].code == 'stdout_unsafe'


# Privacy and bounds -------------------------------------------------------------------------------------------------

def test_arguments_are_masked_before_truncation_and_only_digests_are_kept(tmp_path, context, repository,
                                                                          migrated_database):
    url = migrated_database[0]
    command = 'echo ' + 'y' * 230 + ' ' + SECRET + ' done'  # the secret straddles the 256-character cut
    port = scripted(tmp_path, [
        line(assistant('msg_1', tool_use('toolu_1', 'Bash', {'command': command}),
                       tool_use('toolu_2', 'Fetch', {'api_key': 'plain-credential-value', 'url': 'https://x'}))),
        line(tool_result('toolu_1', 'output with ' + SECRET)), line(tool_result('toolu_2', 'ok')),
        line(claude_result())])
    job, claim, request, result = settle(repository, context, port, 'executor')
    ObservedStepProjector(repository.engine).run_pending()
    page, items = steps(repository, request)
    calls = by_call(items)
    first = calls['toolu_1']['arguments']
    assert first['redactions'] == 1 and first['summary_truncated'] and len(first['summary']) == 256
    assert '[REDACTED]'[:5] in first['summary'] and 'sk-ant' not in first['summary']
    second = calls['toolu_2']['arguments']
    assert '"api_key":"[REDACTED]"' in second['summary'] and second['redactions'] == 1
    assert first['size'] == len(json.dumps({'command': command}, separators=(',', ':')).encode())
    text = trace_text(url, request)
    assert SECRET not in text and 'sk-ant-' not in text and 'plain-credential-value' not in text
    assert 'output with' not in text


def test_bounds_cut_at_ten_thousand_events_or_four_mib_with_remaining_counts():
    deriver = core.Deriver(client='claude', run_id='run', attempt_id='attempt')
    for index in range(10_050):
        deriver.feed({'index': index, 'sequence': None, 'record': index + 1, 'at': None,
                      'event': {'type': 'future.event'}})
    kept, summary = deriver.derive()
    assert len(kept) == core.MAX_STEPS and kept[-1]['reason'] == 'step_bound_reached'
    assert kept[-1]['bound'] == 'steps' and kept[-1]['remaining'] == {'not_observed': 51}
    assert summary['bound'] == {'reason': 'steps', 'remaining': {'not_observed': 51}, 'remaining_total': 51}
    assert summary['steps'] == 10_000 and summary['derived_steps'] == 10_050 and summary['coverage'] == 'partial'
    deriver = core.Deriver(client='claude', run_id='r' * 36, attempt_id='a' * 36)
    for index in range(6000):
        deriver.feed({'index': index, 'sequence': index + 1, 'record': index + 1, 'at': '2026-11-04T00:00:00+00:00',
                      'event': assistant(f'msg_{index}', tool_use(f'toolu_{index}', 'T' * 300,
                                                                  {'payload': 'z' * 400}))})
    kept, summary = deriver.derive()
    assert summary['bound']['reason'] == 'bytes' and summary['payload_bytes'] <= core.MAX_BYTES
    assert sum(core._size(step) for step in kept) == summary['payload_bytes']
    assert kept[-1]['remaining_total'] == 12_000 - (len(kept) - 1)
    assert set(kept[-1]['remaining']) == {'turn', 'tool_call'}
    assert all(len(s['tool']['name']) == core.MAX_NAME for s in kept if s['kind'] == 'tool_call')


def test_missing_evidence_and_unsupported_clients_are_explicit():
    nothing = core.Deriver(client='codex', run_id='r', attempt_id='a')
    kept, summary = nothing.derive()
    assert [s['reason'] for s in kept] == ['no_stream'] and summary['coverage'] == 'absent'
    unknown = core.Deriver(client='gemini', run_id='r', attempt_id='a')
    unknown.feed({'index': 0, 'sequence': 3, 'record': 1, 'at': None, 'event': {'type': 'anything'}})
    kept, summary = unknown.derive()
    assert [(s['reason'], s['client']) for s in kept] == [('unsupported_client', 'gemini')]
    assert summary['coverage'] == 'absent'
    absent = core.Deriver(client=None, run_id='r', attempt_id='a')
    assert [s['reason'] for s in absent.derive()[0]] == ['no_stream']


# Recovery, replay and integrity (TM12) ------------------------------------------------------------------------------

def crash_once(monkeypatch, when):
    real, state = storage.record_event, {'calls': 0, 'crashed': False}

    def flaky(session, **kwargs):
        state['calls'] += 1
        if not state['crashed'] and when(kwargs, state['calls']):
            state['crashed'] = True
            raise RuntimeError('synthetic crash during projection')
        return real(session, **kwargs)
    monkeypatch.setattr(storage, 'record_event', flaky)
    return state


def test_a_crash_mid_projection_stays_pending_and_the_recovery_pass_converges(tmp_path, context, repository,
                                                                             migrated_database, monkeypatch):
    url = migrated_database[0]
    port = scripted(tmp_path, CLAUDE)
    job, claim, request, result = settle(repository, context, port, 'executor')
    expected = ObservedStepProjector(repository.engine)._inputs(invocation(request))['steps']
    state = crash_once(monkeypatch, lambda kwargs, calls: calls == 5)
    first = ObservedStepProjector(repository.engine, batch=3)
    assert first.run_pending() == [{'invocation_id': invocation(request), 'state': 'pending'}]
    assert state['crashed'] and len(rows(url, 'trace_events', "WHERE kind = 'invocation.step'")) == 3
    assert ObservedSteps(repository.engine).page(invocation(request))['state'] == 'pending'
    assert ObservedSteps(repository.engine).page(invocation(request))['items'] == []  # never a partial truth
    # A restarted service: the worker's first pass is the recovery path.
    worker = ObservedStepWorker(repository.engine, idle_seconds=0.05)
    worker.start()
    try:
        wait_until(lambda: ObservedSteps(repository.engine).state(invocation(request))['state'] == 'sealed')
    finally:
        worker.stop(timeout=5)
    page, items = steps(repository, request)
    assert [{k: v for k, v in s.items() if k not in ('cursor', 'event_id', 'truncated', 'redactions')}
            for s in items] == expected
    assert len(rows(url, 'trace_events', "WHERE kind = 'invocation.step'")) == len(expected)
    again = ObservedStepProjector(repository.engine).project(invocation(request))
    assert again == {'invocation_id': invocation(request), 'state': 'sealed', 'written': 0}


def test_a_divergent_replay_is_an_integrity_failure_and_nothing_is_overwritten(tmp_path, context, repository,
                                                                              migrated_database, monkeypatch):
    url = migrated_database[0]
    port = scripted(tmp_path, OVERSIZE)
    job, claim, request, result = settle(repository, context, port, 'executor')
    crash_once(monkeypatch, lambda kwargs, calls: kwargs['kind'] == storage.SEALED)
    assert ObservedStepProjector(repository.engine).run_pending()[0]['state'] == 'pending'
    before = rows(url, 'trace_events', "WHERE kind = 'invocation.step'")
    (port.artifact_root / request.id / 'stdout.bin').unlink()  # the oversize record now derives differently
    assert ObservedStepProjector(repository.engine).run_pending()[0]['state'] == 'integrity_failed'
    assert rows(url, 'trace_events', "WHERE kind = 'invocation.step'") == before
    [failure] = rows(url, 'trace_events', "WHERE kind = 'invocation.steps_failed'")
    assert json.loads(failure['payload'])['code'] == 'integrity_conflict'
    state = ObservedSteps(repository.engine).page(invocation(request))
    assert state['state'] == 'integrity_failed' and state['items'] == []
    assert ObservedStepProjector(repository.engine).pending() == []  # reported once, never retried in a loop
    with closing(sqlite3.connect(db_path((url, None)))) as db:
        assert storage.unsealed_attempt(db, request.id)  # retention keeps its evidence


def finish(repository, job, claim):
    from my_harness.core.engine.contracts import stop_history
    repository.close_owner(claim)
    repository.finish(claim, stop_history(repository.get_run(job.run_id).history, 'executor', 'Synthetic stop'))


def test_attempts_settled_before_t019_are_not_backfilled(tmp_path, context, repository, migrated_database,
                                                         monkeypatch):
    url = migrated_database[0]
    monkeypatch.setattr(storage, 'mark_pending', lambda *args, **kwargs: None)  # a 0.1.x-era settlement
    job, claim, plain, _ = settle(repository, context, probe_adapter(tmp_path, 'success', usage=True), 'executor')
    finish(repository, job, claim)
    graphed = settle(repository, context, probe_adapter(tmp_path, 'success'), 'planner', operation=True)[2]
    assert ObservedStepProjector(repository.engine).run_pending() == []
    reader = ObservedSteps(repository.engine)
    for request, source in ((plain, 'derived'), (graphed, 'trace')):
        page = reader.page(invocation(request))
        assert page['state'] == 'not_projected' and page['reason'] == 'settled_before_observed_steps'
        assert page['items'] == [] and page['evidence']['attempt_id'] == request.id
        assert page['observation']['source'] == source
        assert page['observation']['payload']['format'] == 'trace-observation-1'
        assert page['observation']['persisted'] is (source == 'trace')
    assert rows(url, 'trace_events', "WHERE kind LIKE 'invocation.step%'") == []


def test_excluded_lanes_and_foreign_roots_are_explicit(tmp_path, context, repository, migrated_database):
    url = migrated_database[0]
    job, claim, request, result = settle(repository, context, probe_adapter(tmp_path, 'success'), 'executor')
    with closing(sqlite3.connect(db_path((url, None)))) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute("INSERT INTO usage_invocations (id, source_kind, source_id, preparation_id, preparation_step_id, "
                   "purpose, role, versions, launch, started_at, recorded_at, updated_at) VALUES "
                   "('preparation_step:s1', 'preparation_step', 's1', 'p1', 's1', 'preparation', 'executor', '{}', "
                   "'observed', 't', 't', 't')")
        db.commit()
    reader = ObservedSteps(repository.engine)
    assert reader.page('preparation_step:s1')['state'] == 'lane_excluded'
    assert reader.page('preparation_step:s1')['reason'] == 'steps_not_projected_for_lane'
    with pytest.raises(LookupError):
        reader.page(invocation(request), root='/elsewhere')
    with pytest.raises(LookupError):
        reader.page('managed_attempt:unknown')
    with pytest.raises(ValueError):
        reader.page(invocation(request), after=-1)


# Retention, backups and archives ------------------------------------------------------------------------------------

def test_retention_keeps_pending_streams_and_steps_survive_retention_backup_and_query_only_restore(
        tmp_path, context, repository, migrated_database, monkeypatch):
    url = migrated_database[0]
    database = db_path(migrated_database)
    port = scripted(tmp_path, CLAUDE)
    job, claim, request, result = settle(repository, context, port, 'executor')
    finish(repository, job, claim)
    options = dict(artifact_roots=[port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
    pending = preview_retention(database, **options)
    assert [i['eligible'] for i in pending['items']] == [False, False]
    assert all(request.id in str(i['diagnostic']) for i in pending['items'])
    # An archive taken while the projection is pending reads `pending` and cannot write.
    early = tmp_path / 'early-backup'
    create_backup(database, early, artifact_roots=[port.artifact_root], writers_stopped=True)
    restore_backup(early, tmp_path / 'early-restored')
    archive = make_engine(f"sqlite:///{tmp_path / 'early-restored' / 'state.sqlite3'}")
    try:
        assert ObservedSteps(archive).state(invocation(request))['state'] == 'pending'
        assert ObservedStepProjector(archive).run_pending() == [
            {'invocation_id': invocation(request), 'state': 'pending'}]
        with closing(sqlite3.connect(tmp_path / 'early-restored' / 'state.sqlite3')) as db:
            assert db.execute("SELECT count(*) FROM trace_events WHERE kind = 'invocation.step'").fetchone() == (0,)
    finally:
        archive.dispose()
    refused = apply_retention(database, **options, preview_sha256=pending['preview_sha256'],
                              reason='Synthetic explicit retention', confirmed=True, writers_stopped=True)
    assert refused['removed'] == [] and (port.artifact_root / request.id / 'stdout.bin').exists()
    ObservedStepProjector(repository.engine).run_pending()
    _, expected = steps(repository, request)
    shown = preview_retention(database, **options)
    # The scripted client writes no stderr: only stdout is eligible under the policy's size floor.
    assert [(i['stream'], i['eligible']) for i in shown['items']] == [('stdout', True), ('stderr', False)]

    def owed_again(stage):  # revalidation between the durable intent and the effect also applies the guard
        if stage == 'intents_saved':
            monkeypatch.setattr(storage, 'unsealed_attempt', lambda db, attempt_id: True)
    with pytest.raises(ValueError):
        apply_retention(database, **options, preview_sha256=shown['preview_sha256'], reason='Synthetic retention',
                        confirmed=True, writers_stopped=True, hook=owed_again)
    monkeypatch.undo()
    assert (port.artifact_root / request.id / 'stdout.bin').exists()
    shown = preview_retention(database, **options)
    removed = apply_retention(database, **options, preview_sha256=shown['preview_sha256'],
                              reason='Synthetic retention', confirmed=True, writers_stopped=True)
    assert len(removed['removed']) == 1 and not (port.artifact_root / request.id / 'stdout.bin').exists()
    assert steps(repository, request)[1] == expected  # the projection no longer needs the bytes
    bundle = tmp_path / 'backup'
    create_backup(database, bundle, artifact_roots=[port.artifact_root], writers_stopped=True)
    restore_backup(bundle, tmp_path / 'restored')
    archive = make_engine(f"sqlite:///{tmp_path / 'restored' / 'state.sqlite3'}")
    try:
        reader = ObservedSteps(archive)
        page = reader.page(invocation(request), limit=4)
        assert page['state'] == 'sealed' and len(page['items']) == 4 and page['next_after'] is not None
        restored, after = [], None
        while True:
            page = reader.page(invocation(request), after=after, limit=4)
            restored += page['items']
            after = page['next_after']
            if after is None:
                break
        assert restored == expected
        assert ObservedStepProjector(archive).run_pending() == []
    finally:
        archive.dispose()
    assert url


# Keyset pages and the 5,000-step budget (D309) ----------------------------------------------------------------------

def test_keyset_pages_of_a_5000_step_trace_meet_the_150_ms_p95_budget(tmp_path, context, repository,
                                                                      migrated_database, record_property):
    records = []
    for index in range(2500):
        records.append(line(assistant(f'msg_{index}', tool_use(f'toolu_{index}', 'Read', {'file_path': f'f{index}'}))))
        records.append(line(tool_result(f'toolu_{index}', 'ok')))
    records.append(line(claude_result()))
    port = scripted(tmp_path, records, timeout=60)
    job, claim, request, result = settle(repository, context, port, 'executor')
    started_at = time.perf_counter()
    [projected] = ObservedStepProjector(repository.engine).run_pending()
    projection_seconds = time.perf_counter() - started_at
    reader = ObservedSteps(repository.engine)
    summary = reader.state(invocation(request))['summary']
    assert projected['written'] == summary['steps'] == 5001 and summary['bound'] is None
    assert summary['payload_bytes'] <= core.MAX_BYTES
    assert reader.page(invocation(request), limit=10_000)['next_after'] is not None  # clamped to 200
    samples, seqs = [], []
    for _ in range(8):
        after = None
        while True:
            begin = time.perf_counter()
            page = reader.page(invocation(request), after=after)
            samples.append((time.perf_counter() - begin) * 1000)
            assert len(page['items']) <= 200
            seqs += [s['seq'] for s in page['items']]
            after = page['next_after']
            if after is None:
                break
    assert seqs[:5001] == list(range(5001))
    p95 = statistics.quantiles(samples, n=20)[-1]
    record_property('observed_steps_page_p95_ms', round(p95, 2))
    record_property('observed_steps_projection_seconds', round(projection_seconds, 2))
    Path(tmp_path / 'measurement.json').write_text(json.dumps({'p95_ms': p95, 'pages': len(samples)}))
    print(f'observed-steps pages: {len(samples)} samples, p95 {p95:.2f} ms; projection {projection_seconds:.2f} s')
    assert p95 <= 150


# Lanes ----------------------------------------------------------------------------------------------------------------

def test_every_managed_lane_owes_and_seals_its_projection(world, chat):  # noqa: F811
    """Task (executor and reviewer), chat and phase-check lanes all settle through the same repository."""
    from test_chat import answer
    from test_phases import phase_review
    run_id = world.accept_task()
    phase = world.create()
    conversation = chat.create(phase)
    chat.say(conversation, run_ids=[run_id])
    world.script(answer())
    world.run()
    world.check(phase, phase_review())
    engine = world.repository.engine
    assert {r['state'] for r in ObservedStepProjector(engine).run_pending()} == {'sealed'}
    with Session(engine) as session:
        from my_harness.storage.models import ManagedAttemptRow, ManagedRunRow
        attempts = session.execute(
            __import__('sqlalchemy').select(ManagedAttemptRow.id, ManagedRunRow.purpose)
            .join(ManagedRunRow, ManagedRunRow.id == ManagedAttemptRow.run_id)).all()
    reader = ObservedSteps(engine)
    lanes = set()
    for attempt_id, purpose in attempts:
        page = reader.page(f'managed_attempt:{attempt_id}')
        assert page['state'] == 'sealed'
        # Scripted agents launch no process: the gap is explicit, never an invented turn.
        assert [s['reason'] for s in page['items']] == ['no_stream'] and page['summary']['coverage'] == 'absent'
        lanes.add((purpose, page['role']))
    assert {'executor', 'reviewer', 'chat', 'phase'} <= {role for _purpose, role in lanes}
    assert {'task', 'phase_check'} <= {purpose for purpose, _role in lanes}


def test_0040_round_trip_keeps_steps_and_older_downgrades_refuse_while_they_exist(tmp_path, context, repository,
                                                                                 migrated_database):
    from alembic import command
    from sqlalchemy import inspect
    url, config = migrated_database
    job, claim, request, result = settle(repository, context, scripted(tmp_path, CLAUDE), 'executor')
    ObservedStepProjector(repository.engine).run_pending()
    _, expected = steps(repository, request)
    indexes = lambda: {i['name'] for i in inspect(repository.engine).get_indexes('trace_events')}
    command.downgrade(config, '0039_inbox_read_marks')  # index only: rows untouched
    repository.engine.dispose()
    assert 'ix_trace_events_invocation' not in indexes()
    assert len(rows(url, 'trace_events', "WHERE kind = 'invocation.step'")) == len(expected)
    with pytest.raises(RuntimeError, match='Operation journal records'):  # D287: never dropped below 0032
        command.downgrade(config, '0031_domain_commands')
    command.upgrade(config, 'head')
    command.check(config)
    repository.engine.dispose()
    assert 'ix_trace_events_invocation' in indexes() and steps(repository, request)[1] == expected


def test_the_runtime_projects_settled_attempts_in_the_background(tmp_path, migrated_database, checkout, monkeypatch):
    """The composed service: the supervisor settles, the repository hook wakes the `observed-steps` thread."""
    from my_harness.services.managed_runtime import CONFIG_ENV
    from test_managed_api import PLAN as API_PLAN, Ports, client, config, edit, review, settle as settled_run
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    url = migrated_database[0]
    with client(url, tmp_path, config(checkout, Ports([edit, review()]))) as http:
        job = http.post('/api/managed/projects/synthetic/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001',
                        'text': API_PLAN}, headers={'Idempotency-Key': 'start'}).json()
        settled_run(http, job['run_id'])
        attempts = [a['id'] for a in rows(url, 'managed_attempts')]
        assert attempts
        wait_until(lambda: len(rows(url, 'trace_events', "WHERE kind = 'invocation.steps_sealed'")) == len(attempts))
        runtime = http.app.state.runtime
        assert runtime.steps.alive() and runtime.repository.steps_notify == runtime.steps.notify
    assert rows(url, 'trace_events', "WHERE kind = 'invocation.steps_failed'") == []


# Review corrections (2026-11-04) ---------------------------------------------------------------------------------------

PRIVATE = 'SYNTHETIC_TOOL_RESULT_PRIVATE'


def feed(deriver, events):
    for index, event in enumerate(events):
        deriver.feed({'index': index, 'sequence': index + 1, 'record': index + 1,
                      'at': f'2026-11-04T00:00:{index % 60:02d}+00:00', 'event': event})
    return deriver.derive()


def journaled(tmp_path, repository, context, role, provider, records):
    """Records persisted through the repository's own process journal (the adapter's write path), to feed shapes
    the live CLI cannot easily produce together (two terminals); the live capture of a malformed record is
    `test_a_malformed_claude_record_is_journaled_by_the_live_capture_and_later_records_still_derive`."""
    from my_harness.adapters.processes import identity
    from my_harness.core.engine.contracts import AgentResult
    job, claim, request = setup_invocation(repository, context, scripted(tmp_path, []), role)
    repository.process_intent(claim, request.id, {'provider': provider, 'cli_version': 'synthetic',
                                                  'artifacts': str(tmp_path / 'none')})
    repository.process_updates(claim, request.id, [('process_spawned', {**identity(), 'pgid': 1})] + [
        ('agent_event', {'record': n + 1, 'original': record}) for n, record in enumerate(records)])
    repository.process_update(claim, request.id, 'process_finished', {'status': 'invalid', 'group_state': 'dead'})
    record_result(repository, claim, job, request, AgentResult(None, True, 0, error='CLI invalid', status='invalid'))
    return job, claim, request


def test_malformed_claude_shapes_become_gaps_and_later_records_still_derive(tmp_path, context, repository,
                                                                           migrated_database):
    """Finding 1: nested shapes are validated before any step changes; nothing raises, the projection seals."""
    url = migrated_database[0]
    job, claim, request = journaled(tmp_path, repository, context, 'executor', 'claude', [
        {'type': 'assistant', 'message': {'id': 'msg_0', 'content': 1}},
        {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': [], 'content': PRIVATE}]}},
        {'type': 'assistant', 'message': {'id': 'msg_0', 'content': [{'type': 'tool_use', 'id': 7}]}},
        assistant('msg_1', tool_use('toolu_1', 'Read', {'file_path': 'app/main.txt'})),
        tool_result('toolu_1', 'synthetic body'),
        {**claude_result(), 'permission_denials': [{'tool_use_id': ['toolu_1']}]},
        claude_result()])
    assert [r['state'] for r in ObservedStepProjector(repository.engine).run_pending()] == ['sealed']
    page, items = steps(repository, request)
    assert [(s['kind'], s.get('reason')) for s in items] == [
        ('not_observed', 'invalid_record'), ('not_observed', 'invalid_record'), ('not_observed', 'invalid_record'),
        ('turn', None), ('tool_call', None), ('not_observed', 'invalid_record'), ('message', None)]
    assert [s['event_type'] for s in items if s['kind'] == 'not_observed'] == ['assistant', 'user', 'assistant',
                                                                                'result']
    assert by_call(items)['toolu_1']['outcome'] == 'completed' and items[-1]['message']['final'] is True
    assert page['summary']['coverage'] == 'partial' and 'not_observed_steps' in page['summary']['coverage_reasons']
    assert PRIVATE not in trace_text(url, request)
    for step in items:
        check_sources(repository, job.run_id, request.id, step)


def test_malformed_and_unknown_codex_items_keep_no_fields_and_later_records_still_derive(tmp_path, context,
                                                                                        repository,
                                                                                        migrated_database):
    url = migrated_database[0]
    port = scripted(tmp_path, [
        line({'type': 'turn.started'}),
        line(item('item.completed', 'item_0', 'command_execution', command='ls', status=[])),
        line(item('item.started', 'item_1', 'custom_tool', output=PRIVATE, status='in_progress')),
        line(item('item.completed', 'item_1', 'custom_tool', output=PRIVATE, status='completed')),
        line(item('item.completed', 'item_2', 'command_execution', command=['ls'], status='completed')),
        line(item('item.completed', 'item_3', 'file_change', changes=[{'path': 'a', 'diff': PRIVATE}],
                  status='completed')),
        line(item('item.completed', 'item_4', 'command_execution', command='true', status='completed',
                  aggregated_output='', exit_code=0)),
        line(item('item.completed', 'item_5', 'agent_message', text=json.dumps({'result': 'ok'}))),
        line({'type': 'turn.completed'})])
    job, claim, request, result = settle(repository, context, port, 'planner')
    assert [r['state'] for r in ObservedStepProjector(repository.engine).run_pending()] == ['sealed']
    page, items = steps(repository, request)
    assert [(s['kind'], s.get('reason'), s.get('event_type')) for s in items] == [
        ('turn', None, None), ('not_observed', 'invalid_record', 'item.completed'),
        ('not_observed', 'unsupported_event', 'item:custom_tool'), ('not_observed', 'invalid_record', 'item.completed'),
        ('tool_call', None, None), ('tool_call', None, None), ('message', None, None)]
    assert items[2]['source_record_count'] == 2  # one gap for the unknown item's two records
    assert by_call(items)['item_3']['arguments']['summary'] == '[{"kind":null,"path":"a"}]'  # explicit fields only
    assert items[-1]['message']['final'] is True
    text = trace_text(url, request)
    assert PRIVATE not in text and 'custom_tool' in text


def test_a_codex_final_answer_is_bound_to_the_completion_of_its_own_turn():
    """Finding 2: a later turn's completion never makes an earlier message final; coverage shows what is missing."""
    message = item('item.completed', 'item_0', 'agent_message', text='{}')
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [
        {'type': 'turn.started'}, message, {'type': 'turn.started'}, {'type': 'turn.completed'}])
    assert [(s['kind'], s['outcome']) for s in kept] == [('turn', 'not_observed'), ('message', 'completed'),
                                                          ('turn', 'completed')]
    assert kept[1]['message']['final'] is False and kept[1]['parent_seq'] == 0
    assert summary['coverage'] == 'partial'
    assert set(summary['coverage_reasons']) == {'open_turns', 'final_answer_absent'}
    assert {'signal': 'final_answer', 'reason': 'turn_not_completed'} in summary['absent']
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [
        {'type': 'turn.started'}, message, {'type': 'turn.completed'}, {'type': 'turn.started'}])
    assert kept[1]['message']['final'] is True and kept[2]['outcome'] == 'not_observed'
    assert summary['coverage'] == 'partial' and summary['coverage_reasons'] == ['open_turns']
    # A turn end without its start owns nothing: its message is not claimed as the final answer.
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [message, {'type': 'turn.completed'}])
    assert kept[1]['start_observed'] is False and kept[1]['started_at'] is None and not kept[0]['message']['final']
    assert summary['coverage_reasons'] == ['final_answer_absent']
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [
        {'type': 'turn.started'}, message, {'type': 'turn.completed'}])
    assert summary['coverage'] == 'complete' and summary['coverage_reasons'] == []


def test_an_item_seen_only_at_its_end_records_that_end_without_start_or_duration():
    kept, _ = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [
        {'type': 'turn.started'},
        item('item.completed', 'item_0', 'command_execution', command='ls', status='completed', exit_code=0),
        item('item.started', 'item_1', 'command_execution', command='ls', status='in_progress'),
        item('item.completed', 'item_1', 'command_execution', command='ls', status='completed', exit_code=0),
        {'type': 'turn.completed'}])
    only_end, both = kept[1], kept[2]
    assert only_end['started_at'] is None and only_end['finished_at'] == '2026-11-04T00:00:01+00:00'
    assert only_end['duration_ms'] is None and only_end['timing'] == 'chunk_receipt'
    assert both['started_at'] == '2026-11-04T00:00:02+00:00' and both['duration_ms'] == 1000


def test_identical_parallel_broker_calls_are_never_cross_linked():
    arguments = {'query': 'phase', 'key': 'k'}
    call = lambda ident, kind: item(kind, ident, 'mcp_tool_call', server='harness', tool='search_tools',
                                    arguments=arguments, status='in_progress' if kind == 'item.started' else 'completed')
    brokers = [{'broker': 'search_tools', 'arguments_sha256': digest(arguments), 'call_event_id': f'e{n}',
                'result_event_id': f'r{n}'} for n in (1, 2)]
    events = [{'type': 'turn.started'}, call('a', 'item.started'), call('b', 'item.started'),
              call('b', 'item.completed'), call('a', 'item.completed'),
              item('item.completed', 'm', 'agent_message', text='{}'), {'type': 'turn.completed'}]
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a', brokers=brokers), events)
    assert all('links' not in s['tool'] for s in kept if s['kind'] == 'tool_call')
    assert summary['unmatched'] == {'ambiguous_broker_calls': 2, 'broker_events': 2}
    assert {'ambiguous_broker_calls', 'unlinked_broker_events'} <= set(summary['coverage_reasons'])
    single = feed(core.Deriver(client='codex', run_id='r', attempt_id='a', brokers=brokers[:1]),
                  [e for e in events if e.get('item', {}).get('id') != 'b'])[0]
    assert next(s for s in single if s['kind'] == 'tool_call')['tool']['links'] == {
        'call_event_id': 'e1', 'result_event_id': 'r1'}


# Sealing and the thread surface (finding 3) ---------------------------------------------------------------------------

def test_a_shorter_replay_over_more_persisted_steps_is_an_integrity_failure(tmp_path, context, repository,
                                                                           migrated_database, monkeypatch):
    url = migrated_database[0]
    job, claim, request, result = settle(repository, context, scripted(tmp_path, CLAUDE), 'executor')
    expected = ObservedStepProjector(repository.engine)._inputs(invocation(request))['steps']
    crash_once(monkeypatch, lambda kwargs, calls: kwargs['kind'] == storage.SEALED)
    assert ObservedStepProjector(repository.engine).run_pending()[0]['state'] == 'pending'
    first = rows(url, 'trace_events', "WHERE kind = 'invocation.step'")[0]
    with Session(repository.engine) as session, session.begin():  # an earlier, longer derivation left one more
        record_event(session, kind=storage.STEP, dedupe_key=storage.step_key(invocation(request), len(expected)),
                     payload={**expected[-1], 'seq': len(expected)}, source='measured', root=first['root'],
                     invocation_id=invocation(request))
    before = rows(url, 'trace_events', "WHERE kind = 'invocation.step'")
    assert ObservedStepProjector(repository.engine).run_pending()[0]['state'] == 'integrity_failed'
    assert rows(url, 'trace_events', "WHERE kind = 'invocation.step'") == before
    assert rows(url, 'trace_events', "WHERE kind = 'invocation.steps_sealed'") == []
    [failure] = rows(url, 'trace_events', "WHERE kind = 'invocation.steps_failed'")
    assert json.loads(failure['payload'])['code'] == 'integrity_step_set'
    assert json.loads(failure['payload'])['extra'] == 1
    assert ObservedSteps(repository.engine).page(invocation(request))['items'] == []


@pytest.mark.parametrize('second', ['identical', 'divergent', 'after_failure'])
def test_two_projectors_never_leave_both_terminal_markers(tmp_path, context, repository, migrated_database, second):
    import threading
    url = migrated_database[0]
    job, claim, request, result = settle(repository, context, scripted(tmp_path, CLAUDE), 'executor')
    target = invocation(request)
    if second == 'after_failure':  # the first projector meets an extra row and fails; the second must not seal
        expected = ObservedStepProjector(repository.engine)._inputs(target)['steps']
        with Session(repository.engine) as session, session.begin():
            record_event(session, kind=storage.STEP, dedupe_key=storage.step_key(target, len(expected)),
                         payload={**expected[-1], 'seq': len(expected)}, source='measured',
                         root=rows(url, 'managed_runs')[0]['root'], invocation_id=target)
    derived, first_done = threading.Barrier(2), threading.Event()
    projectors = [ObservedStepProjector(repository.engine, batch=2), ObservedStepProjector(repository.engine, batch=2)]
    for number, projector in enumerate(projectors):
        real = projector._inputs

        def inputs(invocation_id, real=real, number=number):
            value = real(invocation_id)
            derived.wait(timeout=10)  # both derived before either writes
            if number == 1:
                first_done.wait(timeout=10)
                if second == 'divergent':
                    value['steps'][1] = {**value['steps'][1], 'outcome': 'error'}
            return value
        projector._inputs = inputs
    outcomes = [None, None]

    def run(number):
        outcomes[number] = projectors[number].project(target)['state']
        if number == 0:
            first_done.set()
    threads = [threading.Thread(target=run, args=(n,)) for n in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    terminals = [r['kind'] for r in rows(url, 'trace_events',
                                         "WHERE kind IN ('invocation.steps_sealed', 'invocation.steps_failed')")]
    expected_kind = 'invocation.steps_failed' if second == 'after_failure' else 'invocation.steps_sealed'
    assert terminals == [expected_kind]
    assert outcomes == ['integrity_failed'] * 2 if second == 'after_failure' else outcomes == ['sealed'] * 2


def test_thread_trace_queries_never_serve_step_rows_or_skip_later_rows(tmp_path, context, repository,
                                                                      migrated_database, monkeypatch):
    from my_harness.storage.operation_journal import OperationJournal
    url = migrated_database[0]
    job, claim, request, result = settle(repository, context, scripted(tmp_path, CODEX), 'planner', operation=True)
    [operation] = rows(url, 'workflow_operations', f"WHERE attempt_id = '{request.id}'")
    journal = OperationJournal(repository.engine)

    def walk():
        seen, after = [], 0
        while True:
            page = journal.events(operation['root'], operation['thread_id'], after=after, limit=1)
            seen += page['items']
            if page['next_after'] is None:
                return seen
            after = page['next_after']
    crash_once(monkeypatch, lambda kwargs, calls: calls == 3)
    ObservedStepProjector(repository.engine, batch=2).run_pending()
    assert rows(url, 'trace_events', "WHERE kind = 'invocation.step'")  # a partial projection exists
    partial = walk()
    assert 'invocation.step' not in {e['kind'] for e in partial}
    monkeypatch.undo()
    ObservedStepProjector(repository.engine).run_pending()
    complete = walk()
    assert 'invocation.step' not in {e['kind'] for e in complete}
    assert [e['sequence'] for e in complete] == sorted({e['sequence'] for e in complete})
    assert [e['kind'] for e in complete] == [e['kind'] for e in partial] + ['invocation.steps_sealed']
    assert journal.events(operation['root'], operation['thread_id'], operation_id=operation['id'])['items'][-1][
        'kind'] == 'invocation.steps_sealed'


# Bounds, scale and the worker (finding 4) -----------------------------------------------------------------------------

def sequential_codex(calls):
    events = [{'type': 'turn.started'}]
    for n in range(calls):
        events += [item('item.started', f'c{n}', 'command_execution', command='ls', status='in_progress'),
                   item('item.completed', f'c{n}', 'command_execution', command='ls', status='completed', exit_code=0)]
    return events + [{'type': 'turn.completed'}]


def test_overlap_and_derivation_scale_linearly_with_sequential_calls(record_property):
    timings = {}
    for calls in (2000, 4000, 8000):
        best_overlap = best_derive = None
        for _ in range(2):
            deriver = core.Deriver(client='codex', run_id='r', attempt_id='a')
            for index, event in enumerate(sequential_codex(calls)):
                deriver.feed({'index': index, 'sequence': index + 1, 'record': index + 1, 'at': None, 'event': event})
            began = time.perf_counter()
            deriver._end()
            deriver._parallel()
            overlap = time.perf_counter() - began
            deriver = core.Deriver(client='codex', run_id='r', attempt_id='a')
            began = time.perf_counter()
            feed(deriver, sequential_codex(calls))
            total = time.perf_counter() - began
            best_overlap = overlap if best_overlap is None else min(best_overlap, overlap)
            best_derive = total if best_derive is None else min(best_derive, total)
        timings[calls] = (best_overlap, best_derive)
        record_property(f'overlap_seconds_{calls}', round(best_overlap, 4))
        record_property(f'derive_seconds_{calls}', round(best_derive, 3))
    print('observed-steps derivation scale (calls: overlap s, full derive s):',
          {k: (round(a, 4), round(b, 3)) for k, (a, b) in timings.items()})
    assert timings[8000][0] < 0.2  # the reviewer measured 1.62 s for the pairwise version
    assert timings[8000][0] < 8 * max(timings[2000][0], 0.002)  # linear (×4), not quadratic (×16)
    assert timings[8000][1] < 8 * timings[2000][1]


def test_steps_past_the_bound_are_counted_not_materialized_and_still_absorb_their_results():
    deriver = core.Deriver(client='claude', run_id='r', attempt_id='a')
    events = []
    for n in range(6000):
        events += [assistant(f'msg_{n}', tool_use(f'toolu_{n}', 'Read', {'file_path': 'x' * 2000})),
                   tool_result(f'toolu_{n}', 'ok')]
    for index, event in enumerate(events + [claude_result()]):
        deriver.feed({'index': index, 'sequence': index + 1, 'record': index + 1, 'at': None, 'event': event})
        assert len(deriver.steps) <= core.MAX_STEPS
    kept, summary = deriver.derive()
    assert summary['unmatched'] == {}  # results of omitted calls are theirs, not uncorrelated
    assert summary['derived_steps'] == 12_001 and summary['steps'] == len(kept) <= core.MAX_STEPS
    assert kept[-1]['reason'] == 'step_bound_reached'
    assert kept[-1]['remaining_total'] == 12_001 - (len(kept) - 1)
    assert sum(kept[-1]['remaining'].values()) == kept[-1]['remaining_total']
    assert summary['payload_bytes'] <= core.MAX_BYTES


def test_the_worker_reaches_a_healthy_marker_behind_persistent_failures(tmp_path, context, repository,
                                                                        migrated_database):
    url = migrated_database[0]
    with closing(sqlite3.connect(db_path(migrated_database))) as db:  # twenty older markers that always fail
        db.execute('PRAGMA foreign_keys=OFF')
        db.executemany('INSERT INTO trace_events (event_id, dedupe_key, root, invocation_id, kind, source, payload, '
                       'payload_sha256, truncated, redactions, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       [(str(uuid4()), f'steps_pending:managed_attempt:broken-{n}', '/r', f'managed_attempt:broken-{n}',
                         storage.PENDING, 'derived', '{}', '0' * 64, 0, 0, 't') for n in range(20)])
        db.commit()
    job, claim, request, result = settle(repository, context, scripted(tmp_path, CLAUDE), 'executor')
    projector = ObservedStepProjector(repository.engine)
    assert projector.run_pending(limit=20, stop=lambda: True) == []  # stop is honoured before any work
    worker = ObservedStepWorker(repository.engine, idle_seconds=0.05)
    worker.start()
    try:
        wait_until(lambda: ObservedSteps(repository.engine).state(invocation(request))['state'] == 'sealed')
    finally:
        worker.stop(timeout=5)
    again = projector.run_pending(limit=20)
    assert len(again) == 20 and {r['state'] for r in again} == {'pending'}  # each failure retried, none blocks
    assert invocation(request) not in projector.pending()


# Evidence boundary through the projector (finding 5) -----------------------------------------------------------------

@pytest.mark.parametrize('damage', ['capture_absent', 'linked_folder'])
def test_oversize_ranges_without_sealed_proof_or_behind_a_link_are_unavailable(tmp_path, context, repository,
                                                                               migrated_database, damage):
    url = migrated_database[0]
    port = scripted(tmp_path, OVERSIZE)
    job, claim, request, result = settle(repository, context, port, 'executor')
    if damage == 'capture_absent':
        with closing(sqlite3.connect(db_path(migrated_database))) as db:
            db.execute("UPDATE managed_processes SET capture = json_remove(capture, '$.artifacts') WHERE attempt_id = ?",
                       (request.id,))
            db.commit()
    else:
        folder = port.artifact_root / request.id
        moved = tmp_path / 'moved-attempt'
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
    ObservedStepProjector(repository.engine).run_pending()
    page, items = steps(repository, request)
    gap = next(s for s in items if s['kind'] == 'not_observed')
    assert gap['reason'] == 'oversize_record_unavailable'
    assert gap['detail'] == {'capture_absent': 'capture_absent', 'linked_folder': 'stdout_unsafe'}[damage]
    assert gap['source_record'][0]['oversize'] is True
    check_sources(repository, job.run_id, request.id, gap)


def test_reasons_states_and_coverage_codes_have_english_and_spanish_messages():
    from my_harness.i18n import catalog
    keys = ([f'observed_steps.reason.{r}' for r in core.REASONS]
            + [f'observed_steps.coverage.{r}' for r in core.COVERAGE_REASONS]
            + [f'observed_steps.state.{s}' for s in ('sealed', 'pending', 'integrity_failed', 'not_settled',
                                                      'not_projected', 'lane_excluded')]
            + ['retention.steps_pending', 'observed_steps.invocation_unknown', 'observed_steps.cursor_invalid'])
    for language in ('en', 'es'):
        assert [k for k in keys if k not in catalog(language)] == []
    reasons = set()
    for events in ([], [{'type': 'turn.started'}], [{'type': 'turn.completed'}]):
        reasons |= set(feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), events)[1]['coverage_reasons'])
    assert reasons <= set(core.COVERAGE_REASONS)


# Second review corrections (2026-11-05) -------------------------------------------------------------------------------

def test_a_malformed_claude_record_is_journaled_by_the_live_capture_and_later_records_still_derive(
        tmp_path, context, repository, migrated_database):
    """Finding 1: the live capture journals the chunk and its records (no injected rows); `metrics-1` counts nothing
    for the malformed record, the agent result is validated as before and the projector marks it in place."""
    from my_harness.core.engine.metrics import replay
    url = migrated_database[0]
    port = scripted(tmp_path, [
        line({'type': 'system', 'subtype': 'init', 'session_id': 'synthetic'}),
        line({'type': 'assistant', 'message': {'id': 'msg_0', 'content': 1}}),
        line(stream_event('message_start', message={'id': 'msg_1'})),
        line(assistant('msg_1', tool_use('toolu_1', 'Read', {'file_path': 'app/main.txt'}))),
        line(tool_result('toolu_1', 'synthetic body')),
        line(claude_result())])
    job, claim, request, result = settle(repository, context, port, 'executor')
    assert result.status == 'complete' and result.payload_json is not None  # result validation unchanged
    meta = json.loads(result.metadata_json)
    stdout = Path(meta['artifacts']['stdout']['path']).read_bytes()
    assert meta['status'] == 'complete' and meta['stream_metrics']['tools'] == {'Read': 1}
    assert meta['stream_metrics'] == replay('claude', stdout)['summary']  # capture and sealed re-read agree
    journal = [(r['kind'], json.loads(r['payload']))
               for r in rows(url, 'managed_events', f"WHERE run_id = '{job.run_id}'")]
    chunks = [p for k, p in journal if k == 'stream_bytes' and p['stream'] == 'stdout']
    assert sum(c['size'] for c in chunks) == len(stdout) == meta['artifacts']['stdout']['size']
    records = {p['record']: p for k, p in journal if k == 'agent_event'}
    assert sorted(records) == [1, 2, 3, 4, 5, 6] and records[2]['original']['message']['content'] == 1
    assert not (port.artifact_root / request.id / 'capture.json').exists()  # no interrupted capture
    assert [r['state'] for r in ObservedStepProjector(repository.engine).run_pending()] == ['sealed']
    page, items = steps(repository, request)
    assert [(s['kind'], s.get('reason')) for s in items] == [
        ('not_observed', 'invalid_record'), ('turn', None), ('tool_call', None), ('message', None)]
    gap = items[0]
    assert gap['event_type'] == 'assistant' and [r['record'] for r in gap['source_record']] == [2]
    assert by_call(items)['toolu_1']['outcome'] == 'completed' and items[-1]['message']['final'] is True
    assert page['summary']['coverage_reasons'] == ['not_observed_steps'] and page['summary']['last_record'] == 6
    for step in items:
        check_sources(repository, job.run_id, request.id, step)


def test_an_in_progress_file_change_without_changes_derives_and_takes_them_from_its_completion(
        tmp_path, context, repository, migrated_database):
    """Finding 2a: `changes: null` while in progress is valid; the projection seals instead of staying pending."""
    port = scripted(tmp_path, [
        line({'type': 'turn.started'}),
        line(item('item.started', 'item_0', 'file_change', changes=None, status='in_progress')),
        line(item('item.updated', 'item_0', 'file_change', changes=None, status='in_progress')),
        line(item('item.completed', 'item_0', 'file_change', changes=[{'path': 'app/x', 'kind': 'add'}],
                  status='completed')),
        line(item('item.completed', 'item_1', 'agent_message', text=json.dumps({'result': 'ok'}))),
        line({'type': 'turn.completed'})])
    job, claim, request, result = settle(repository, context, port, 'planner')
    assert [r['state'] for r in ObservedStepProjector(repository.engine).run_pending()] == ['sealed']
    page, items = steps(repository, request)
    assert [s['kind'] for s in items] == ['turn', 'tool_call', 'message']
    call = by_call(items)['item_0']
    assert call['outcome'] == 'completed' and call['source_record_count'] == 3
    assert call['arguments']['summary'] == '[{"kind":"add","path":"app/x"}]'  # observed at its completion
    assert call['started_at'] is not None and call['duration_ms'] is not None
    assert page['summary']['coverage'] == 'complete' and page['summary']['unmatched'] == {}


def test_a_codex_final_message_without_text_is_an_explicit_absent_final_answer():
    """Finding 2b: a completed turn whose last message has no text has no final answer, and says so."""
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [
        {'type': 'turn.started'}, item('item.completed', 'item_0', 'agent_message'), {'type': 'turn.completed'}])
    assert kept[1]['message'] == {'present': False, 'final': False}
    assert summary['coverage'] == 'partial' and summary['coverage_reasons'] == ['final_answer_absent']
    assert {'signal': 'final_answer', 'reason': 'message_text_absent'} in summary['absent']


def test_an_mcp_call_first_seen_updating_has_no_start_and_takes_its_fields_from_its_completion():
    """Finding 2c: no `item.started` → start and duration absent; server, tool and arguments first observed at the
    completion are incorporated (so the harness call is still attributed to its broker call)."""
    arguments = {'query': 'phase'}
    broker = {'broker': 'search_tools', 'arguments_sha256': digest(arguments), 'call_event_id': 'e1'}
    events = [{'type': 'turn.started'},
              item('item.updated', 'item_0', 'mcp_tool_call', status='in_progress'),
              item('item.completed', 'item_0', 'mcp_tool_call', server='harness', tool='search_tools',
                   arguments=arguments, result={'content': []}, status='completed'),
              item('item.completed', 'item_1', 'agent_message', text='{}'), {'type': 'turn.completed'}]
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a', brokers=[broker]), events)
    call = kept[1]
    assert call['tool'] == {'name': 'search_tools', 'server': 'harness', 'origin': 'harness_broker',
                            'links': {'call_event_id': 'e1'}}
    assert call['arguments']['sha256'] == digest(arguments) and call['arguments']['summary'] == '{"query":"phase"}'
    assert call['started_at'] is None and call['duration_ms'] is None
    assert call['finished_at'] == '2026-11-04T00:00:02+00:00' and call['timing'] == 'chunk_receipt'
    assert call['source_record_count'] == 2 and summary['coverage'] == 'complete'
    # Never completed: nothing invented either way.
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), events[:2])
    assert (kept[1]['outcome'], kept[1]['started_at'], kept[1].get('finished_at'), kept[1]['timing']) == (
        'not_observed', None, None, 'absent')
    assert kept[1]['tool'] == {'name': None, 'server': None, 'origin': None}
    # A field already observed is never replaced by a later record.
    kept, _ = feed(core.Deriver(client='codex', run_id='r', attempt_id='a'), [
        {'type': 'turn.started'},
        item('item.started', 'item_0', 'mcp_tool_call', server='other', tool='t', arguments={'a': 1},
             status='in_progress'),
        item('item.completed', 'item_0', 'mcp_tool_call', server='harness', tool='u', arguments={'a': 2},
             status='completed')])
    assert kept[1]['tool'] == {'name': 't', 'server': 'other', 'origin': 'other_mcp'}
    assert kept[1]['arguments']['summary'] == '{"a":1}'


def test_a_broker_link_needs_a_unique_native_call_across_the_whole_invocation(monkeypatch):
    """Finding 3: an identical harness call past the step bound makes the visible one ambiguous: no link, a reason."""
    monkeypatch.setattr(core, 'MAX_STEPS', 6)
    arguments = {'query': 'phase'}
    broker = {'broker': 'search_tools', 'arguments_sha256': digest(arguments), 'call_event_id': 'e1'}

    def call(ident, value):
        return [item(kind, ident, 'mcp_tool_call', server='harness', tool='search_tools', arguments=value,
                     status='in_progress' if kind == 'item.started' else 'completed')
                for kind in ('item.started', 'item.completed')]

    def events(late):
        return ([{'type': 'turn.started'}] + call('a', arguments)
                + [item('item.completed', f'r{n}', 'reasoning', text='synthetic') for n in range(6)]
                + call('b', late) + [item('item.completed', 'm', 'agent_message', text='{}'),
                                     {'type': 'turn.completed'}])
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a', brokers=[broker]),
                         events(arguments))
    visible = by_call(kept)
    assert list(visible) == ['a'] and kept[-1]['reason'] == 'step_bound_reached'  # `b` is past the bound
    assert 'links' not in visible['a']['tool'] and visible['a']['tool']['link_absent'] == 'ambiguous_broker_calls'
    assert summary['unmatched'] == {'ambiguous_broker_calls': 2, 'broker_events': 1}
    assert {'ambiguous_broker_calls', 'unlinked_broker_events'} <= set(summary['coverage_reasons'])
    # The same invocation with a different late call: the visible call is unique and linked.
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a', brokers=[broker]),
                         events({'query': 'other'}))
    assert by_call(kept)['a']['tool']['links'] == {'call_event_id': 'e1'} and summary['unmatched'] == {}
    # A single call past the bound owns its broker call: neither ambiguous nor linked to a visible step.
    late = {'broker': 'search_tools', 'arguments_sha256': digest({'query': 'other'}), 'call_event_id': 'e2'}
    kept, summary = feed(core.Deriver(client='codex', run_id='r', attempt_id='a', brokers=[broker, late]),
                         events({'query': 'other'}))
    assert by_call(kept)['a']['tool']['links'] == {'call_event_id': 'e1'} and summary['unmatched'] == {}


def test_a_stop_between_batches_leaves_the_projection_pending_and_the_next_start_converges(
        tmp_path, context, repository, migrated_database):
    """Finding 4: the service's stop reaches a projection in progress, between batches and before the seal."""
    url = migrated_database[0]
    job, claim, request, result = settle(repository, context, scripted(tmp_path, CLAUDE), 'executor')
    expected = ObservedStepProjector(repository.engine)._inputs(invocation(request))['steps']
    assert len(expected) == 9

    def written(kind=storage.STEP):
        return len(rows(url, 'trace_events', f"WHERE kind = '{kind}'"))
    worker = ObservedStepWorker(repository.engine, idle_seconds=0.05)
    worker.projector.batch = 3
    real = worker.projector._write

    @contextmanager
    def write_then_stop():
        with real() as session:
            yield session
        worker.stopping.set()  # the runtime stops right after the first batch committed
    worker.projector._write = write_then_stop
    worker.start()
    worker.thread.join(5)
    assert not worker.alive()
    assert written() == 3 and written(storage.SEALED) == written(storage.FAILED) == 0
    assert ObservedSteps(repository.engine).state(invocation(request))['state'] == 'pending'
    assert ObservedStepProjector(repository.engine).pending() == [invocation(request)]
    # The check before the seal: every batch written, the seal withheld.
    checks = []
    stopped = ObservedStepProjector(repository.engine, batch=3).run_pending(
        stop=lambda: checks.append(1) or len(checks) > 4)  # before the invocation and each of 3 batches
    assert stopped == [{'invocation_id': invocation(request), 'state': 'pending', 'stopped': True}]
    assert written() == 9 and written(storage.SEALED) == 0
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        assert storage.unsealed_attempt(db, request.id)  # retention still keeps its streams
    # The next start converges: written batches replay as no-ops, the seal is written once.
    again = ObservedStepWorker(repository.engine, idle_seconds=0.05)
    again.start()
    try:
        wait_until(lambda: ObservedSteps(repository.engine).state(invocation(request))['state'] == 'sealed')
    finally:
        again.stop(timeout=5)
    page, items = steps(repository, request)
    assert [{k: v for k, v in s.items() if k not in ('cursor', 'event_id', 'truncated', 'redactions')}
            for s in items] == expected
    assert written() == 9 and written(storage.SEALED) == 1 and written(storage.FAILED) == 0


def test_an_unexpected_capture_failure_still_journals_the_chunk_already_written(tmp_path, context, repository,
                                                                                migrated_database, monkeypatch):
    """Finding 1 (boundary): bytes written and fsynced before an unforeseen parser failure keep their chunk and the
    records read from it in the journal; the attempt is still interrupted and the failure is not masked."""
    from my_harness.adapters import streams
    url = migrated_database[0]
    real = streams.StreamMetrics.event

    def broken(self, event, *, terminal=False):
        if event.get('type') == 'assistant':
            raise TypeError('synthetic counter failure')
        return real(self, event, terminal=terminal)
    monkeypatch.setattr(streams.StreamMetrics, 'event', broken)
    port = scripted(tmp_path, [line({'type': 'system', 'subtype': 'init', 'session_id': 'synthetic'}, sleep=0.1),
                               line(assistant('msg_1', {'type': 'text', 'text': 'synthetic'})), line(claude_result())])
    job, claim, request = setup_invocation(repository, context, port, 'executor')
    with pytest.raises(TypeError, match='synthetic counter failure'):
        port.invoke(context, request)
    stdout = (port.artifact_root / request.id / 'stdout.bin').read_bytes()
    journal = [(r['kind'], json.loads(r['payload']))
               for r in rows(url, 'managed_events', f"WHERE run_id = '{job.run_id}'")]
    chunks = [p for k, p in journal if k == 'stream_bytes' and p['stream'] == 'stdout']
    assert sum(c['size'] for c in chunks) == len(stdout) > 0
    assert 2 in {p['record'] for k, p in journal if k == 'agent_event'}  # the record whose counters failed
    capture = json.loads((port.artifact_root / request.id / 'capture.json').read_text())
    assert capture['status'] == 'interrupted' and capture['interruption'] == 'TypeError'
