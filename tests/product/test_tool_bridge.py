"""T008: real broker/services/SQLite/MCP subprocesses, fake clients and permissions only. No providers."""
from dataclasses import replace
import json
import os
from pathlib import Path
import select
import subprocess
import sys
from threading import Event, Thread
import time
from uuid import uuid4

import pytest
from sqlalchemy import event, select as sqlselect, text
from sqlalchemy.orm import Session as SQLSession

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter, argv_for
from my_harness.adapters.cli_compatibility import guard_contract
from my_harness.adapters.processes import identity
from my_harness.adapters.tool_bridge_transport import BridgeSession
from my_harness.core.engine import tool_bridge as core
from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot, freeze
from my_harness.core.engine.domain_catalogue import CATALOGUE, Catalogue, Entry, digest
from my_harness.core.engine.prompts import builtin_catalog
from my_harness.services.domain_operations import DomainOperations, DomainRefusal
from my_harness.services.managed import _Journal
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.services.tool_bridge import BridgeFactory, Broker, InvocationResolver
from my_harness.storage.frozen_context import ReceiptSink, ContextRepository
from my_harness.storage.models import ManagedAttemptRow, TraceEventRow, UsageInvocationRow
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.operation_journal import InvocationOperation, OperationJournal, command_sink
from test_domain_operations import TablePermissions, seed, put, requirement
from test_frozen_context import world, adopt  # noqa: F401
from test_managed import PLAN, VERSIONS, context, repository  # noqa: F401
from test_operation_journal import thread, record_result

CLIENT = str(Path(__file__).with_name('tool_bridge_client.py'))


def setup(world, repository, context, tmp_path, client='codex', mode='normal', role='reviewer', refs=None, environment=()):
    version = {'codex': '0.165.0', 'claude': '2.1.312'}[client]
    cell = core.Qualification(client, version, role, 'T008-fake-client', provenance='simulated')
    env = (('ITEM_ID', world['ids']['R001']), ('BRIDGE_PID', str(tmp_path / 'bridge.pid')),
           ('BRIDGE_RESULT', str(tmp_path / 'result.json')), *environment)
    config = CLIConfig(client, (sys.executable, '-I', CLIENT, client, version, mode), version, env, 6)
    adapter = CLIProcessAdapter({'reviewer': config, 'executor': config}, tmp_path / 'captures')
    permissions = TablePermissions(repository.engine)
    permissions.allow(*(e.id for e in CATALOGUE if e.kind == 'query'), 'knowledge.draft.open',
                      product=('knowledge.propose:task',))
    resolver = InvocationResolver()
    ops = DomainOperations(repository.engine, resolver=resolver, permissions=permissions,
                           delivery=ReceiptSink('tool_result'), audit_sinks=(command_sink,))
    adapter.bind_tool_bridges(BridgeFactory(ops, qualifications=(cell,)))
    snapshot = world['contexts'].prepare_for(context, [world['ids']['R001']], client=client)
    prompt, snap = world['contexts'].render(world['project'], snapshot, builtin_catalog(), 'review-task',
                                          {'INPUT_JSON': '{}'}, context)
    request = AgentRequest(str(uuid4()), role, Selection('synthetic-model', 'medium', 'test'), prompt,
                           None, context_snapshot(context), prompt_snapshot_json=snap)
    refs = refs or [e.ref for e in CATALOGUE.scoped('agent', role, frozenset(CATALOGUE.current(e.id).ref for e in CATALOGUE))]
    request = core.policy(request, refs, cell)
    thread(repository.engine)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, {**VERSIONS, **adapter.frozen_versions()},
                            key=str(uuid4()))
    claim = repository.claim(lease_seconds=120)
    repository.register_owner(claim, identity())
    request = repository.agent_started(claim, repository.get_run(job.run_id).history, request,
                                       InvocationOperation('thread-1', 'tools'))
    adapter.bind_process_journal(_Journal(repository, claim, Event()))
    with SQLSession(repository.engine) as session:
        caller = resolver.resolve(session, request.id)
    return adapter, request, Broker(ops, caller), permissions, job, claim


def rpc(process, method, params, rid=1):
    process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params}) + '\n')
    process.stdin.flush()
    assert select.select([process.stdout], [], [], 5)[0], 'stdio response timeout'
    response = json.loads(process.stdout.readline())
    assert response['id'] == rid
    return response


def relay(session, *, parent=False):
    command = [session.config['command'], *session.config['args']]
    if parent:
        command = [sys.executable, '-c',
            'import subprocess,sys; p=subprocess.Popen(sys.argv[1:], start_new_session=True); p.wait()', *command]
    return subprocess.Popen(command,
                            env={**os.environ, **session.config['env']}, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)


def invoke(broker, operation='knowledge.lookup', arguments=None, key='invoke', **changes):
    entry = CATALOGUE.current(operation)
    args = {'id': operation, 'version': entry.version, 'schema_sha256': entry.schema_sha256,
            'arguments': arguments or {}, 'key': key, **changes}
    return broker.call('invoke_tool', args)


@pytest.mark.parametrize('client', ['codex', 'claude'])
@pytest.mark.parametrize('mode', ['normal', 'orphan', 'auth', 'quota'])
@pytest.mark.parametrize('role', ['reviewer', 'executor'])
def test_adapter_stdio_domain_journey_and_no_fallback(world, repository, context, tmp_path, client, mode, role):
    adapter, request, broker, permissions, job, claim = setup(world, repository, context, tmp_path, client, mode, role)
    result = adapter.invoke(context, request)
    assert (result.status == 'complete') == (mode in ('normal', 'orphan')), result.error
    value = json.loads((tmp_path / 'result.json').read_text())
    assert value['ok'] and 'Sign in' in freeze(value)
    with SQLSession(repository.engine) as session:
        events = session.scalars(sqlselect(TraceEventRow).order_by(TraceEventRow.id)).all()
        kinds = [e.kind for e in events]
        assert kinds.count('broker.called') == 3
        assert kinds.count('tool.discovered') == 2
        assert kinds.count('tool.called') == kinds.count('tool.result') == 1
        assert kinds.count('bridge.registered') == kinds.count('bridge.disconnected') == 1
        assert kinds.count('bridge.ready') == 1
        assert session.query(UsageInvocationRow).count() == 1
    deliveries = ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)
    assert {d['channel'] for d in deliveries} == {'initial_context', 'tool_result'}
    assert len(deliveries) == 4
    metadata = json.loads(result.metadata_json)
    assert metadata['group_state'] == 'dead'
    if client == 'codex':
        assert not metadata['observed'].get('model')
        assert metadata['observed'].get('usage') is None
    repository.close_owner(claim)


def test_scope_schema_closed_envelopes_replay_and_revocation(world, repository, context, tmp_path):
    allowed = [CATALOGUE.current(n).ref for n in ('knowledge.head', 'knowledge.lookup', 'knowledge.draft.open')]
    _, request, broker, permissions, *_ = setup(world, repository, context, tmp_path, refs=allowed)
    page = broker.call('search_tools', {'key': 'page', 'limit': 1})
    assert page['ok'] and len(page['result']['items']) == 1
    cursor = page['result']['page']['next_cursor']
    assert broker.call('search_tools', {'key': 'page2', 'limit': 1, 'cursor': cursor})['ok']
    assert not broker.call('search_tools', {'key': 'changed', 'query': 'changed', 'cursor': cursor})['ok']
    all_items = broker.call('search_tools', {'key': 'all'})['result']['items']
    assert {e['id'] for e in all_items} == {e[0] for e in allowed}
    for name in ('knowledge.adopt', 'knowledge.projects', 'knowledge.get', 'sql', 'python'):
        assert not broker.call('describe_tool', {'id': name, 'version': 1, 'key': name})['ok']
        assert not invoke(broker, arguments={}, id=name)['ok']
    for changes in ({'version': 999}, {'schema_sha256': '0' * 64}, {'caller': 'owner'},
                    {'arguments': {'item_id': world['ids']['R001'], 'project_id': world['project']}},
                    {'arguments': {'item_id': world['ids']['R001'], 'revision': 999}}, {'key': ''}):
        assert not invoke(broker, **changes)['ok']
    args = {'item_id': world['ids']['R001']}
    first = invoke(broker, arguments=args, key='read')
    assert first['ok']
    replay = invoke(broker, arguments=args, key='read')
    assert replay['ok'] and replay['replayed'] and replay['result'] == first['result']
    assert not invoke(broker, arguments={'item_id': world['ids']['T001']}, key='read')['ok']
    assert len(ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)) == 5
    permissions.revoke(CATALOGUE.current('knowledge.lookup').tool_target)
    assert not invoke(broker, arguments=args, key='read')['ok']
    # Discovery still discloses the frozen scope, not a grant.
    assert broker.call('search_tools', {'key': 'after-revoke'})['ok']
    forged = Broker(broker.operations, replace(broker.caller, knowledge_project_id='foreign'))
    assert not forged.call('search_tools', {'key': 'forgery'})['ok']


def test_additional_client_conformance_and_protocol_refusals(world, repository, context, tmp_path):
    _, request, broker, *_ = setup(world, repository, context, tmp_path)
    session = BridgeSession(broker, tmp_path)
    process = relay(session)
    try:
        assert rpc(process, 'server/discover', {})['error']['code'] == -32601
        assert rpc(process, 'initialize', {'protocolVersion': '2024-11-05',
                   'clientInfo': {'name': 'synthetic-third-client', 'version': '1'}, 'capabilities': {}})['result']
        assert len(rpc(process, 'tools/list', {})['result']['tools']) == 3
        result = rpc(process, 'tools/call', {'name': 'search_tools', 'arguments': {'key': 'third', 'query': 'lookup'}})
        assert json.loads(result['result']['content'][0]['text'])['ok']
        entry = json.loads(result['result']['content'][0]['text'])['result']['items'][0]
        described = rpc(process, 'tools/call', {'name': 'describe_tool', 'arguments': {
            'id': entry['id'], 'version': entry['version'], 'key': 'third-schema'}})
        assert json.loads(described['result']['content'][0]['text'])['result']['schema_sha256'] == entry['schema_sha256']
        arguments = {'item_id': world['ids']['R001']}
        invoked = rpc(process, 'tools/call', {'name': 'invoke_tool', 'arguments': {
            'id': entry['id'], 'version': entry['version'], 'schema_sha256': entry['schema_sha256'],
            'arguments': arguments, 'key': 'third-call'}})
        assert json.loads(invoked['result']['content'][0]['text'])['ok']
        assert rpc(process, 'tools/call', {'name': 'invoke_tool', 'arguments': {'caller': 'owner'}})['result']['isError']
        for malformed in (None, [], '', 1):
            assert rpc(process, 'tools/call', {'name': 'invoke_tool', 'arguments': malformed})['result']['isError']
        assert rpc(process, 'initialize', {'protocolVersion': 'future'})['error']
        process.stdin.write('{"jsonrpc":"2.0","id":1,"id":2}\n')
        process.stdin.flush()
        assert json.loads(process.stdout.readline())['error']
        process.stdin.close()
        assert process.wait(timeout=3) == 0
    finally:
        process.kill() if process.poll() is None else None
        process.wait(timeout=3)
        session.close()


@pytest.mark.parametrize('missing', core.MC)
def test_each_required_capability_is_mandatory(missing):
    cell = core.Qualification('codex', '0.165.0', 'reviewer', 'missing',
                              capabilities=tuple(c for c in core.MC if c != missing), provenance='simulated')
    with pytest.raises(ValueError, match=missing):
        cell.admit('codex', '0.165.0', 'reviewer')
    for args in [('opencode', '0.165.0', 'reviewer'), ('codex', '0.166.0', 'reviewer'),
                 ('codex', '0.165.0', 'executor')]:
        with pytest.raises(ValueError):
            core.qualification(core.NATIVE, *args)


def test_product_permissions_deny_and_caller_changes_are_rejected(world, repository, context, tmp_path):
    _, request, broker, *_ = setup(world, repository, context, tmp_path)
    ops = ManagedRuntime(repository.engine).tool_bridges().operations
    assert invoke(Broker(ops, broker.caller), arguments={'item_id': world['ids']['R001']})['error']['code'] == 'capability_unavailable'
    for changes in ({'invocation_id': 'forged'}, {'attempt_id': str(uuid4())}, {'operation_key': 'foreign'},
                    {'thread_id': 'foreign'}, {'root': '/foreign'}, {'frozen_revision_id': 'foreign'},
                    {'role': 'executor'}, {'tool_policy': frozenset(e.ref for e in CATALOGUE)}):
        forged = Broker(broker.operations, replace(broker.caller, **changes))
        assert not forged.call('search_tools', {'key': 'forged'})['ok']


def test_measure_serialized_context_is_reproducible():
    entries = [Entry(f'synthetic.tool.{i:03}', 1, 'query', ('agent',), ('reviewer',),
                     {'type': 'object', 'additionalProperties': False, 'properties': {
                         'query': {'type': 'string', 'maxLength': 200, 'description': 'Synthetic field. ' * 30}}},
                     {'type': 'object', 'additionalProperties': True}, summary='Synthetic operation. ' * 10)
               for i in range(200)]
    result = core.measure(entries, entries[:5])
    assert result == core.measure(entries, entries[:5])
    assert result['initial_surface_bytes'] + result['descriptors_bytes'] + result['selected_schemas_bytes'] < result['full_catalogue_bytes']
    assert result['logical_exchanges'] == 3


@pytest.mark.parametrize('client', ['codex', 'claude'])
@pytest.mark.parametrize('role', ['reviewer', 'executor'])
def test_independent_guard_rejects_extra_servers_tools_and_approval_bypass(
        world, repository, context, tmp_path, client, role):
    adapter, request, broker, *_ = setup(world, repository, context, tmp_path, client, role=role)
    session = BridgeSession(broker, tmp_path)
    try:
        config = adapter.agents[role]
        argv = argv_for(config, context, request, bridge=session.config)
        access = 'write' if role == 'executor' else 'read'
        assert guard_contract(client, argv, context.root, access, bridge=session.config)
        assert not guard_contract(client, argv, context.root, access)
        for poisoned in ({**session.config, 'command': '/untrusted/command'},
                         {**session.config, 'args': ['-c', 'arbitrary_code']},
                         {**session.config, 'args': ['-m', 'my_harness.adapters.tool_bridge_stdio']},
                         {**session.config, 'env': {**session.config['env'], 'PYTHONPATH': '/untrusted'}}):
            poisoned_argv = argv_for(config, context, request, bridge=poisoned)
            assert not guard_contract(client, poisoned_argv, context.root, access, bridge=poisoned)
        if client == 'codex':
            changed = (*argv, '-c', 'mcp_servers.foreign.command="unsafe"')
            assert not guard_contract(client, changed, context.root, access, bridge=session.config)
            changed = tuple(x.replace('default_tools_approval_mode="approve"', 'default_tools_approval_mode="auto"') for x in argv)
            assert not guard_contract(client, changed, context.root, access, bridge=session.config)
        else:
            changed = list(argv)
            pos = changed.index('--allowedTools') + 1
            changed[pos] += ',mcp__foreign__sql'
            assert not guard_contract(client, changed, context.root, access, bridge=session.config)
            changed = list(argv)
            pos = changed.index('--mcp-config') + 1
            changed[pos] = freeze({'mcpServers': {'harness': session.config, 'foreign': {'command': 'unsafe'}}})
            assert not guard_contract(client, changed, context.root, access, bridge=session.config)
    finally:
        session.close(require_available=False)  # guard-only setup intentionally launches no relay


def test_mutation_reentry_deduplicates_effect_and_receipt_then_rechecks_authority(world, repository, context, tmp_path):
    _, request, broker, permissions, *_ = setup(world, repository, context, tmp_path)
    args = {'expected_revision_id': broker.caller.frozen_revision_id}
    a = invoke(broker, 'knowledge.draft.open', args, 'open')
    assert a['ok'], a
    b = invoke(broker, 'knowledge.draft.open', args, 'open')
    assert b['ok'] and b['replayed'] and b['result'] == a['result']
    assert len(ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)) == 1
    assert not invoke(broker, 'knowledge.draft.open', {'expected_revision_id': None}, 'open')['ok']
    permissions.revoke(CATALOGUE.current('knowledge.draft.open').tool_target)
    assert not invoke(broker, 'knowledge.draft.open', args, 'open')['ok']
    with repository.engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM domain_commands WHERE principal='agent' AND outcome='ACCEPTED'")).scalar() == 1


def test_receipt_failure_returns_no_unrecorded_content_and_replay_has_no_duplicate_receipts(
        world, repository, context, tmp_path):
    _, request, broker, *_ = setup(world, repository, context, tmp_path)
    def fail(connection, cursor, statement, *rest):
        if statement.startswith('INSERT INTO knowledge_deliveries'):
            raise RuntimeError('synthetic receipt failure')
    event.listen(repository.engine, 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError):
            broker.call('search_tools', {'key': 'receipt'})
        with pytest.raises(RuntimeError):
            invoke(broker, arguments={'item_id': world['ids']['R001']}, key='receipt-query')
    finally:
        event.remove(repository.engine, 'before_cursor_execute', fail)
    assert not ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)
    a = broker.call('describe_tool', {'id': 'knowledge.lookup', 'version': CATALOGUE.current('knowledge.lookup').version, 'key': 'schema'})
    b = broker.call('describe_tool', {'id': 'knowledge.lookup', 'version': CATALOGUE.current('knowledge.lookup').version, 'key': 'schema'})
    assert a == b
    assert len(ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)) == 1


@pytest.mark.parametrize('client', ['codex', 'claude'])
def test_cancel_mid_call_stops_detached_bridge_even_with_exit_zero_and_never_relaunches(
        world, repository, context, tmp_path, client):
    adapter, request, broker, _, job, claim = setup(world, repository, context, tmp_path, client, 'cancel')
    entered, release = Event(), Event()
    original = broker.operations.handlers['knowledge.lookup']
    def delayed(call):
        entered.set()
        assert release.wait(4)
        return original(call)
    broker.operations.handlers['knowledge.lookup'] = delayed
    results, errors = [], []
    def run():
        try:
            results.append(adapter.invoke(context, request))
        except BaseException as error:
            errors.append(error)
    worker = Thread(target=run)
    worker.start()
    try:
        assert entered.wait(5)
        assert adapter.cancel(request.id).requested
        time.sleep(0.1)
        release.set()
        worker.join(timeout=6)
        assert not worker.is_alive() and not errors, errors
        result = results[0]
        assert result.status == 'cancelled' and result.exit_code == 0
        saved = repository.processes(job.id)[0]['spec']['tool_bridge']
        assert saved['identity']['pid'] == int((tmp_path / 'bridge.pid').read_text())
        assert saved['state'] == 'dead'
        # The attempt outcome was never committed. Recovery cannot interpret exit 0 as completed inference.
        with repository.engine.begin() as connection:
            connection.execute(text("UPDATE managed_jobs SET lease_until='2000-01-01' WHERE id=:id"), {'id': job.id})
        recovered = OperationJournal(repository.engine).recover('thread-1', writer_stopped=True)
        assert recovered[0]['status'] == 'UNCERTAIN'
        assert not invoke(broker, arguments={'item_id': world['ids']['R001']}, key='new')['ok']
    finally:
        release.set()
        worker.join(timeout=6)
        adapter.close()


@pytest.mark.parametrize('boundary', ['eof', 'supervisor', 'parent'])
def test_relay_loss_terminates_during_domain_call(world, repository, context, tmp_path, boundary):
    _, request, broker, *_ = setup(world, repository, context, tmp_path)
    entered, release = Event(), Event()
    original = broker.operations.handlers['knowledge.lookup']
    def delayed(call):
        entered.set()
        assert release.wait(4)
        return original(call)
    broker.operations.handlers['knowledge.lookup'] = delayed
    session = BridgeSession(broker, tmp_path)
    process = relay(session, parent=boundary == 'parent')
    try:
        rpc(process, 'initialize', {'protocolVersion': '2025-06-18'})
        entry = CATALOGUE.current('knowledge.lookup')
        process.stdin.write(freeze({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'invoke_tool', 'arguments': {'id': entry.id, 'version': entry.version,
                'schema_sha256': entry.schema_sha256, 'arguments': {'item_id': world['ids']['R001']}, 'key': 'inflight'}}}) + '\n')
        process.stdin.flush()
        assert entered.wait(4)
        if boundary == 'eof':
            process.stdin.close()
        elif boundary == 'supervisor':
            session.stopped.set()
            session.connection.shutdown(2)
        else:
            assert session.process['parent'] == process.pid
            process.kill()
        assert process.wait(timeout=2) in (0, -9)
    finally:
        release.set()
        process.kill() if process.poll() is None else None
        process.wait(timeout=3)
        session.close()


def test_frozen_revision_cross_project_and_lost_authority(world, repository, context, tmp_path):
    _, request, broker, permissions, *_ = setup(world, repository, context, tmp_path)
    other, _ = seed(world['ops'], '/synthetic/other-project')
    args = {'item_id': other['R001']}
    a = invoke(broker, arguments=args, key='foreign')
    b = invoke(broker, arguments={'item_id': 'nonexistent'}, key='missing')
    assert a['error'] == b['error'] == {'code': 'not_found'}
    writer = world['writer']
    draft, sha = writer.open(world['revision']['revision_id'])
    writer.apply(draft, sha, [put('requirement', 'R001', requirement('Changed after invocation freeze.'))])
    later = adopt(world['ops'], world['owner'], draft, world['revision']['revision_id'])
    result = invoke(broker, 'knowledge.head', key='head')
    assert result['result']['revision']['id'] == broker.caller.frozen_revision_id != later['revision_id']
    permissions.drop('current', 'project', CATALOGUE.current('knowledge.head').tool_target)
    assert not invoke(broker, 'knowledge.head', key='head')['ok']


def test_backup_and_archive_preserve_tool_evidence_without_execution_or_writes(
        world, repository, context, tmp_path, migrated_database):
    import shutil
    adapter, request, broker, _, job, claim = setup(world, repository, context, tmp_path)
    result = adapter.invoke(context, request)
    record_result(repository, claim, job, request, result)
    repository.close_owner(claim)
    live = ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)
    create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True,
                  artifact_roots=(tmp_path / 'captures',))
    restore_backup(tmp_path / 'backup', tmp_path / 'archive')
    archive = make_engine('sqlite:///' + str(tmp_path / 'archive/state.sqlite3'))
    shutil.rmtree(context.root)
    statements = []
    event.listen(archive, 'before_cursor_execute', lambda conn, cursor, statement, *args: statements.append(statement))
    try:
        assert ContextRepository(archive).deliveries(world['project'], broker.caller.invocation_id) == live
        kinds = [e['kind'] for e in OperationJournal(archive).events(str(context.root), 'thread-1')['items']]
        assert 'tool.discovered' in kinds and 'tool.result' in kinds and 'bridge.stopped' in kinds
        assert not any(s.lstrip().upper().startswith(('INSERT', 'DELETE', 'UPDATE', 'CREATE')) for s in statements)
        refused = Broker(ManagedRuntime(archive).tool_bridges().operations, broker.caller).call('search_tools', {'key': 'archive'})
        assert refused['error']['code'] == 'query_only'
    finally:
        archive.dispose()


def test_trace_commit_serializes_with_concurrent_process_journal_write(world, repository, context, tmp_path):
    """Reproduce the WAL snapshot-upgrade race from the parallel general check without probabilistic retries."""
    _, request, broker, _, job, _ = setup(world, repository, context, tmp_path)
    started, finished = Event(), Event()
    errors, workers = [], []
    triggered = False
    def writer():
        try:
            with repository.engine.begin() as connection:
                started.set()
                connection.execute(text('UPDATE managed_runs SET stage=stage WHERE id=:id'), {'id': job.run_id})
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()
    def race(connection, cursor, statement, *args):
        nonlocal triggered
        if not triggered and statement.startswith('SELECT trace_events.'):
            triggered = True
            worker = Thread(target=writer)
            workers.append(worker)
            worker.start()
            assert started.wait(2)
            # Without the journal write lock, this commits between the context read and event INSERT,
            # and SQLite refuses that INSERT with SQLITE_BUSY_SNAPSHOT instead of waiting.
            finished.wait(0.1)
    event.listen(repository.engine, 'before_cursor_execute', race)
    try:
        with SQLSession(repository.engine) as session, session.begin():
            broker.event(session, 'bridge.race', 'synthetic-race', {'synthetic': True})
    finally:
        event.remove(repository.engine, 'before_cursor_execute', race)
        for worker in workers:
            worker.join(timeout=3)
    assert triggered and finished.is_set() and not errors


def test_changed_surface_or_qualification_blocks_before_spawn(world, repository, context, tmp_path):
    from my_harness.core.engine.journal import JournalError
    adapter, request, broker, *_ = setup(world, repository, context, tmp_path)
    snapshot = json.loads(request.prompt_snapshot_json)
    snapshot['scoped_tools']['surface_sha256'] = '0' * 64
    with pytest.raises(JournalError):
        adapter.invoke(context, replace(request, prompt_snapshot_json=freeze(snapshot)))
    assert not (tmp_path / 'bridge.pid').exists()
    assert not (tmp_path / 'result.json').exists()


@pytest.mark.parametrize('client', ['codex', 'claude'])
def test_stdio_refusal_stays_typed_while_native_process_events_are_written(world, repository, context, tmp_path, client):
    adapter, request, broker, permissions, job, claim = setup(world, repository, context, tmp_path, client)
    permissions.revoke(CATALOGUE.current('knowledge.lookup').tool_target)
    result = adapter.invoke(context, request)
    response = json.loads((tmp_path / 'result.json').read_text())
    assert response == {'ok': False, 'error': {'code': 'capability_denied'}}
    deliveries = ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)
    assert len(deliveries) == 3  # initial context, discovery and schema; no refused knowledge read
    with SQLSession(repository.engine) as session:
        refused = session.scalar(sqlselect(TraceEventRow).where(TraceEventRow.kind == 'domain.command_refused'))
        assert refused.invocation_id == broker.caller.invocation_id
    assert result.status == 'complete'  # synthetic final answer; never relabels the logical refusal
    repository.close_owner(claim)


@pytest.mark.parametrize('client', ['codex', 'claude'])
@pytest.mark.parametrize('shadow', ['package', 'module', 'stdlib', 'pythonpath', 'pythonhome'])
def test_relay_imports_are_isolated_from_checkout_and_inherited_python_environment(
        world, repository, context, tmp_path, client, shadow):
    sentinel = tmp_path / 'project-code-executed.txt'  # deliberately outside the managed checkout
    attack = f'from pathlib import Path\nPath({str(sentinel)!r}).write_text("untrusted code executed")\n'
    environment = ()
    if shadow == 'package':
        package = context.root / 'my_harness'
        package.mkdir()
        (package / '__init__.py').write_text(attack)
    elif shadow == 'module':
        (context.root / 'my_harness.py').write_text(attack)
    elif shadow == 'stdlib':
        (context.root / 'json.py').write_text(attack)
        (context.root / 'sitecustomize.py').write_text(attack)
    elif shadow == 'pythonpath':
        poisoned = tmp_path / 'poisoned-python-path'
        (poisoned / 'my_harness').mkdir(parents=True)
        (poisoned / 'my_harness/__init__.py').write_text(attack)
        (poisoned / 'sitecustomize.py').write_text(attack)
        environment = (('BRIDGE_PYTHONPATH', str(poisoned)),)
    else:
        (context.root / 'sitecustomize.py').write_text(attack)
        environment = (('BRIDGE_PYTHONHOME', str(context.root)),
                       ('BRIDGE_PYTHONSTARTUP', str(context.root / 'sitecustomize.py')))
    adapter, request, broker, _, job, claim = setup(world, repository, context, tmp_path, client,
                                                   environment=environment)
    result = adapter.invoke(context, request)
    assert not sentinel.exists(), 'The project executed code during trusted relay startup'
    assert result.status == 'complete', result.error
    assert json.loads((tmp_path / 'result.json').read_text())['ok']
    assert repository.processes(job.id)[0]['spec']['tool_bridge']['ready']['surface_sha256'] == core.SURFACE_SHA256
    repository.close_owner(claim)


@pytest.mark.parametrize('client', ['codex', 'claude'])
@pytest.mark.parametrize('mode', ['no-bridge', 'startup-failure', 'registered-no-init', 'available-no-calls'])
def test_bridge_availability_is_required_but_logical_calls_are_optional(
        world, repository, context, tmp_path, client, mode):
    adapter, request, broker, _, job, claim = setup(world, repository, context, tmp_path, client, mode)
    result = adapter.invoke(context, request)
    available = mode == 'available-no-calls'
    assert result.status == ('complete' if available else 'failed')
    assert (result.payload_json is not None) == available
    assert result.exit_code == 0 and result.terminal_observed
    saved = repository.processes(job.id)[0]
    assert saved['capture']['status'] == result.status
    assert saved['capture']['tool_bridge']['available'] == available
    if available:
        assert saved['spec']['tool_bridge']['ready']['protocol'] == '2024-11-05'
    else:
        assert saved['capture']['diagnostic_code'] == 'bridge_unavailable'
        if mode == 'registered-no-init':
            assert saved['spec']['tool_bridge']['state'] == 'dead'
            assert 'ready' not in saved['spec']['tool_bridge']
        else:
            assert saved['spec'].get('tool_bridge') is None
        assert 'launch_permitted' not in saved['capture']  # the CLI really ran; do not invent no-inference evidence
    with SQLSession(repository.engine) as session:
        kinds = session.scalars(sqlselect(TraceEventRow.kind)).all()
        assert kinds.count('bridge.ready') == int(available)
        assert 'broker.called' not in kinds and 'tool.called' not in kinds
    assert len(ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)) == 1
    record_result(repository, claim, job, request, result)
    with SQLSession(repository.engine) as session:
        invocations = session.scalars(sqlselect(UsageInvocationRow)).all()
        assert len(invocations) == 1 and invocations[0].launch != 'not_invoked'
    repository.close_owner(claim)


def test_closing_without_availability_cannot_establish_completion(world, repository, context, tmp_path):
    _, _, broker, *_ = setup(world, repository, context, tmp_path)
    session = BridgeSession(broker, tmp_path)
    with pytest.raises(RuntimeError, match='availability'):
        session.close()
    assert session.closed and not session.available.is_set()


def test_peer_eof_then_service_settlement_then_supervisor_close_is_an_expected_disconnect(
        world, repository, context, tmp_path):
    """Deterministic review ordering: the peer is already gone when sendall attempts the service response."""
    _, request, broker, *_ = setup(world, repository, context, tmp_path)
    entered, release = Event(), Event()
    original = broker.operations.handlers['knowledge.lookup']
    def delayed(call):
        entered.set()
        assert release.wait(5)
        return original(call)
    broker.operations.handlers['knowledge.lookup'] = delayed
    session = BridgeSession(broker, tmp_path)
    process = relay(session)
    try:
        rpc(process, 'initialize', {'protocolVersion': '2024-11-05'})
        entry = CATALOGUE.current('knowledge.lookup')
        process.stdin.write(freeze({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'invoke_tool', 'arguments': {'id': entry.id, 'version': entry.version,
                'schema_sha256': entry.schema_sha256, 'arguments': {'item_id': world['ids']['R001']},
                'key': 'review-eof'}}}) + '\n')
        process.stdin.flush()
        assert entered.wait(5)
        process.stdin.close()
        assert process.wait(timeout=3) == 0
        assert not session.stopped.is_set()
        release.set()
        session.thread.join(timeout=5)
        assert not session.thread.is_alive() and not session.stopped.is_set()
        assert session.error is None and session.response_lost
        session.close()
        deliveries = ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)
        assert len(deliveries) == 1  # committed at the domain service boundary, no client delivery claim
        with SQLSession(repository.engine) as db:
            disconnected = db.scalar(sqlselect(TraceEventRow).where(TraceEventRow.kind == 'bridge.disconnected'))
            assert disconnected.payload['reason'] == 'peer_closed'
            assert disconnected.payload['response_lost'] and disconnected.payload['error'] is None
        # Missing native outcome still reconciles as uncertain, despite the settled deterministic query.
        assert OperationJournal(repository.engine).recover('thread-1', writer_stopped=True, at='2100-01-01')[0]['status'] == 'UNCERTAIN'
    finally:
        release.set()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        session.close()


@pytest.mark.parametrize('failure_type', [RuntimeError, BrokenPipeError])
def test_cancellation_does_not_suppress_a_real_receipt_failure(world, repository, context, tmp_path, monkeypatch, failure_type):
    _, request, broker, *_ = setup(world, repository, context, tmp_path)
    entered, release = Event(), Event()
    original = broker.operations.handlers['knowledge.lookup']
    def delayed(call):
        entered.set()
        assert release.wait(5)
        return original(call)
    def fail(*args):
        raise failure_type('synthetic receipt persistence failure')
    broker.operations.handlers['knowledge.lookup'] = delayed
    monkeypatch.setattr(broker.operations.delivery, 'record', fail)
    session = BridgeSession(broker, tmp_path)
    process = relay(session)
    try:
        rpc(process, 'initialize', {'protocolVersion': '2024-11-05'})
        entry = CATALOGUE.current('knowledge.lookup')
        process.stdin.write(freeze({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {
            'name': 'invoke_tool', 'arguments': {'id': entry.id, 'version': entry.version,
                'schema_sha256': entry.schema_sha256, 'arguments': {'item_id': world['ids']['R001']}, 'key': 'fail'}}}) + '\n')
        process.stdin.flush()
        assert entered.wait(5)
        process.stdin.close()
        assert process.wait(timeout=3) == 0
        session.stopped.set()
        release.set()
        session.thread.join(timeout=5)
        assert not session.thread.is_alive()
        assert session.error == failure_type.__name__
        assert not ContextRepository(repository.engine).deliveries(world['project'], broker.caller.invocation_id)
    finally:
        release.set()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=3)
        with pytest.raises(RuntimeError, match='transport failed'):
            session.close()
