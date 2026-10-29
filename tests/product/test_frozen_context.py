"""T007: real context, command, journal, fenced invocation and backup implementations.

Synthetic accepted knowledge, temporary Git/SQLite, test-only caller/permission doubles and a fake CLI.
No providers, network, installed state or product graphs. TM01/TM14/TM15 and FL08 crash/rollback boundaries.
"""
from dataclasses import replace
from hashlib import sha256
import json
from threading import Event
from uuid import uuid4
import subprocess

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session as SQLSession

from my_harness.adapters.processes import identity
from my_harness.core.engine import frozen_context as core
from my_harness.core.engine import knowledge
from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot, freeze
from my_harness.core.engine.prompts import builtin_catalog, render_attempt
from my_harness.services.domain_operations import Caller, DomainOperations, owner_reader, owner_writer
from my_harness.services.managed import _Journal
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage import frozen_context as storage
from my_harness.storage.backup import create_backup, restore_backup, verify_bundle, BackupError
from my_harness.storage.database import make_engine
from my_harness.storage.frozen_context import ContextRepository, ReceiptSink
from my_harness.storage.operation_journal import InvocationOperation, OperationJournal
from test_domain_operations import (Session, TablePermissions, TrustingResolver, put, requirement, run, seed,
                                    section, refused)
from test_managed import PLAN, VERSIONS, context, repository  # noqa: F401
from test_operation_journal import thread, rows, record_result
from test_trace_observation import probe_adapter


def adopt(ops, owner, draft, revision):
    preview = run(ops, owner, 'knowledge.adoption.preview', {'draft_id': draft}).result
    return run(ops, owner, 'knowledge.adopt', {'draft_id': draft, 'expected_revision_id': revision,
        'preview_sha256': preview['preview_sha256'], 'reason': 'Synthetic adoption.'}, str(uuid4())).result


def capture(data, name='synthetic-profile', version='1', provenance='synthetic capture'):
    return dict(id=name, version=version, data=data, sha256=core.digest(data), provenance=provenance)


@pytest.fixture
def world(repository, context):
    ops = DomainOperations(repository.engine)
    root = str(context.root)
    ids, first = seed(ops, root)
    owner = owner_writer(root)
    writer = Session(ops, owner, 'instructions')
    draft, sha = writer.open(first['revision_id'])
    sha, items = writer.apply(draft, sha, [
        put('section', 'rules', section('Rules', '# Rules\nCanonical agents. {{DO_NOT_EVALUATE}}'),
            document='instructions', root_position=0),
        put('section', 'child', section('Child', 'Child rules.'), document='instructions'),
        put('section', 'claude', section('Claude', 'Claude only.', 'claude'), document='instructions', root_position=1),
        put('section', 'gemini', section('Gemini', 'Gemini only.', 'gemini'), document='instructions', root_position=2)])
    writer.apply(draft, sha, [{'op': 'link', 'kind': 'part_of', 'source_item_id': items[1],
                             'target_item_id': items[0], 'position': 0}])
    revision = adopt(ops, owner, draft, first['revision_id'])
    project = run(ops, owner, 'knowledge.head', {}).result['knowledge_project_id']
    contexts = ManagedRuntime(repository.engine).frozen_contexts()
    blob = subprocess.run(['git', '-C', root, 'hash-object', 'app/main.txt'], check=True,
                           capture_output=True, text=True).stdout.strip()
    snapshot = contexts.prepare(root, [ids['R001'], ids['T001']], client='codex',
                                profile=core.profile_capture(context),
                                code=[capture('baseline', 'git:app/main.txt', blob, 'synthetic Git blob')])
    return dict(ops=ops, owner=owner, ids=ids, revision=revision, project=project, contexts=contexts,
                snapshot=snapshot, writer=writer)


def start(world, repository, context, *, adapter=None, snapshot=None, key='first'):
    engine = repository.engine
    with SQLSession(engine) as session:
        from my_harness.storage.models import GraphThreadRow
        exists = session.get(GraphThreadRow, 'thread-1')
    if exists is None:
        thread(engine)
    versions = {**VERSIONS, **(adapter.frozen_versions() if adapter else {})}
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, versions, key=str(uuid4()))
    claim = repository.claim(lease_seconds=120)
    repository.register_owner(claim, identity())
    prompt, prompt_snapshot = world['contexts'].render(world['project'], snapshot or world['snapshot'],
        builtin_catalog(), 'review-task', {'INPUT_JSON': '{}'}, context)
    request = AgentRequest(str(uuid4()), 'reviewer', Selection('synthetic-model', 'medium', 'test'), prompt,
                           None, context_snapshot(context), prompt_snapshot_json=prompt_snapshot)
    request = repository.agent_started(claim, repository.get_run(job.run_id).history, request,
                                        InvocationOperation('thread-1', key))
    if adapter:
        adapter.bind_process_journal(_Journal(repository, claim, Event()))
    return job, claim, request


def queries(world, repository, request, *, channel='query_result', permissions=None):
    permissions = permissions or TablePermissions(repository.engine)
    permissions.allow('knowledge.head', 'knowledge.list', 'knowledge.get', 'knowledge.lookup', 'knowledge.search')
    sid = json.loads(request.prompt_snapshot_json)['canonical_context']['id']
    revision = world['contexts'].snapshot(world['project'], sid)['data']['revision_id']
    caller = Caller('agent', 'broker', knowledge_project_id=world['project'], role='reviewer',
        invocation_id='managed_attempt:' + request.id, attempt_id=request.id, thread_id='thread-1',
        frozen_revision_id=revision, tool_policy=frozenset(e.ref for e in world['ops'].catalogue))
    ops = DomainOperations(repository.engine, resolver=TrustingResolver(), permissions=permissions,
                           delivery=ReceiptSink(channel))
    return ops, caller, permissions


@pytest.mark.parametrize('client,expected', [('codex', []), ('claude', ['# Claude\nClaude only.']), ('gemini', ['# Gemini\nGemini only.'])])
def test_deterministic_context_exact_sources_instruction_order_and_targets(world, context, client, expected):
    contexts, project = world['contexts'], world['project']
    args = dict(client=client, profile=core.profile_capture(context))
    a = contexts.prepare(str(context.root), [world['ids']['T001'], world['ids']['R001']], **args)
    b = contexts.prepare(str(context.root), [world['ids']['R001'], world['ids']['T001']], **args)
    one, two = contexts.snapshot(project, a), contexts.snapshot(project, b)
    assert one['data'] == two['data'] and one['sha256'] == two['sha256']
    instructions = [e for e in one['data']['entries'] if e['purpose'] == 'instructions']
    assert [e['data'] for e in instructions] == ['# Rules\n# Rules\nCanonical agents. {{DO_NOT_EVALUATE}}', '## Child\nChild rules.', *expected]
    for e in one['data']['entries']:
        assert e['digest'] == sha256(e['data'].encode()).hexdigest()
    assert {e['authority'] for e in one['data']['entries']} == {'canonical', 'capture'}
    prompt, snapshot = contexts.render(project, a, builtin_catalog(), 'review-task', {'INPUT_JSON': '{}'}, context)
    assert one['data']['instructions'] in prompt and '{{DO_NOT_EVALUATE}}' in prompt
    assert json.loads(snapshot)['canonical_context']['sha256'] == one['sha256']
    # Definition templates have no historical instructions slot; the explicit canonical path adds them.
    text, _ = contexts.render(project, a, builtin_catalog(), 'define-project',
                             {'CONTEXT_JSON': '{}', 'MESSAGE': 'Synthetic'}, context)
    assert one['data']['instructions'] in text


def test_new_path_has_no_checkout_fallback_and_legacy_render_is_unchanged(world, context):
    catalog = builtin_catalog()
    context = replace(context, documents='v2')
    (context.root / 'AGENTS.md').write_text('Legacy only.')
    legacy, old_snapshot = render_attempt(catalog, 'review-task', {'INPUT_JSON': '{}'}, context)
    assert 'Legacy only.' in legacy and 'canonical_context' not in json.loads(old_snapshot)
    (context.root / 'AGENTS.md').unlink()
    with pytest.raises(Exception):
        render_attempt(catalog, 'review-task', {'INPUT_JSON': '{}'}, context)
    prompt, snap = world['contexts'].render(world['project'], world['snapshot'], catalog,
                                           'review-task', {'INPUT_JSON': '{}'}, context)
    assert 'Canonical agents.' in prompt and json.loads(old_snapshot)['rendered'] == legacy
    assert 'path' not in json.loads(snap)['project_instructions']
    assert world['contexts'].snapshot(world['project'], world['snapshot'])['data']['revision_id'] == world['revision']['revision_id']


def test_fenced_intent_is_not_delivery_then_real_fake_cli_observation_is_deduplicated(world, context, repository, tmp_path, migrated_database):
    adapter = probe_adapter(tmp_path, 'success')
    job, claim, request = start(world, repository, context, adapter=adapter)
    invocation = 'managed_attempt:' + request.id
    assert world['contexts'].deliveries(world['project'], invocation) == []
    result = adapter.invoke(context, request)
    assert result.status == 'complete'
    record_result(repository, claim, job, request, result)
    deliveries = world['contexts'].deliveries(world['project'], invocation)
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d['channel'] == 'initial_context'
    assert d['payload']['exposures'] == world['contexts'].snapshot(world['project'], world['snapshot'])['data']['entries']
    with SQLSession(repository.engine) as session, session.begin():
        storage.observe(session, request.id, core.digest(request.prompt))
    assert world['contexts'].deliveries(world['project'], invocation) == deliveries
    events = OperationJournal(repository.engine).events(str(context.root), 'thread-1')['items']
    assert any(e['kind'] == 'context.intended' for e in events)
    assert sum(e['kind'] == 'knowledge.receipt' for e in events) == len(d['receipts'])
    assert 'Canonical agents.' not in freeze(events) and core.profile_capture(context)['data'] not in freeze(events)


def test_freezing_search_lookup_and_failure_receipts_never_reveal_new_revision(world, context, repository):
    job, claim, request = start(world, repository, context)
    ops, caller, permissions = queries(world, repository, request)
    old = run(ops, caller, 'knowledge.lookup', {'item_id': world['ids']['R001'], 'exposure': 'excerpt',
                                             'start': 3, 'length': 17}, 'lookup').body()
    w = world['writer']
    draft, sha = w.open(world['revision']['revision_id'])
    _, (new_id, _) = w.apply(draft, sha, [put('requirement', 'R002', requirement('SECRET_NEW_REVISION')),
        put('requirement', 'R001', requirement('CHANGED_NEW_REVISION'))])
    later = adopt(world['ops'], world['owner'], draft, world['revision']['revision_id'])
    responses = [run(ops, caller, 'knowledge.head', {}, 'head').body(),
        run(ops, caller, 'knowledge.search', {'query': 'NEW_REVISION'}, 'search').body(),
        run(ops, caller, 'knowledge.list', {}, 'list').body(),
        run(ops, caller, 'knowledge.get', {'item_id': world['ids']['R001']}, 'get').body()]
    for n in (later['number'], 999999):
        e = refused('revision_outside_context', lambda: run(ops, caller, 'knowledge.search',
                    {'query': 'sign', 'revision': n}, 'bad-' + str(n)))
        responses.append({'code': e.code, 'params': e.params})
    for item in (new_id, 'missing-item'):
        e = refused('not_found', lambda: run(ops, caller, 'knowledge.lookup', {'item_id': item}, 'missing-' + item))
        responses.append({'code': e.code, 'params': e.params})
    serialized = freeze(responses)
    assert all(secret not in serialized for secret in ('NEW_REVISION', later['revision_id'], later['revision_sha256'], new_id))
    assert run(ops, caller, 'knowledge.lookup', {'item_id': world['ids']['R001'], 'exposure': 'excerpt',
                                              'start': 3, 'length': 17}, 'lookup').body() == old
    receipts = world['contexts'].deliveries(world['project'], caller.invocation_id)
    for d in receipts:
        for r in d['receipts']:
            e = d['payload']['exposures'][r['index']]
            assert r['revision_id'] == world['revision']['revision_id']
            if r['failure'] is None:
                assert r['digest'] == core.digest(e['data'])
            else:
                assert 'digest' not in r
    assert any(r['exposure'] == 'excerpt' and r['digest'] != r['source_sha256']
               for d in receipts for r in d['receipts'] if 'source_sha256' in r)
    snapshot = world['contexts'].prepare(str(context.root), [], client='codex', profile=core.profile_capture(context))
    # A second native attempt is a new explicit boundary, even inside the same managed run.
    prompt, snap = world['contexts'].render(world['project'], snapshot, builtin_catalog(), 'review-task', {'INPUT_JSON': '{}'}, context)
    from my_harness.core.engine.contracts import AgentResult
    record_result(repository, claim, job, request, AgentResult('{}', True, 0, status='complete'))
    next_request = replace(request, id=str(uuid4()), prompt=prompt, prompt_snapshot_json=snap, permission_snapshot_json=None)
    repository.agent_started(claim, repository.get_run(job.run_id).history, next_request,
                              InvocationOperation('thread-1', 'second'))
    next_ops, next_caller, _ = queries(world, repository, next_request, permissions=permissions)
    assert run(next_ops, next_caller, 'knowledge.head', {}, 'head-new').result['revision']['id'] == later['revision_id']
    assert run(next_ops, next_caller, 'knowledge.search', {'query': 'SECRET_NEW_REVISION'}, 'search-new').result['page']['total'] == 1


def test_query_reentry_receipt_transaction_rollback_and_tool_channel(world, context, repository, migrated_database, monkeypatch):
    _, _, request = start(world, repository, context)
    ops, caller, _ = queries(world, repository, request, channel='tool_result')
    args = {'item_id': world['ids']['R001'], 'exposure': 'metadata'}
    first = run(ops, caller, 'knowledge.lookup', args, 'same').body()
    before = rows(migrated_database[0], 'trace_events')
    assert run(ops, caller, 'knowledge.lookup', args, 'same').body() == first
    assert rows(migrated_database[0], 'trace_events') == before
    refused('idempotency_conflict', lambda: run(ops, caller, 'knowledge.lookup', {**args, 'exposure': 'full'}, 'same'))
    refused('delivery_key_required', lambda: run(ops, caller, 'knowledge.head', {}))
    previous = world['contexts'].deliveries(world['project'], caller.invocation_id)
    original = storage.record_envelope

    def broken(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('Synthetic receipt persistence failure after event write.')
    monkeypatch.setattr(storage, 'record_envelope', broken)
    with pytest.raises(RuntimeError):
        run(ops, caller, 'knowledge.lookup', args, 'rollback')
    assert world['contexts'].deliveries(world['project'], caller.invocation_id) == previous
    monkeypatch.setattr(storage, 'record_envelope', original)
    result = run(ops, caller, 'knowledge.lookup', args, 'rollback').body()
    assert result == first
    deliveries = world['contexts'].deliveries(world['project'], caller.invocation_id)
    assert len(deliveries) == 2 and all(d['channel'] == 'tool_result' for d in deliveries)


def test_commit_failure_returns_no_content_and_rolls_back_receipts(world, context, repository, migrated_database, monkeypatch):
    _, _, request = start(world, repository, context)
    ops, caller, _ = queries(world, repository, request)
    real_record = ops.delivery.record

    def mark(session, *args):
        real_record(session, *args)
        session.info['synthetic_commit_failure'] = True

    def fail_commit(session):
        if session.info.get('synthetic_commit_failure'):
            raise RuntimeError('Synthetic commit failure.')

    monkeypatch.setattr(ops.delivery, 'record', mark)
    event.listen(SQLSession, 'before_commit', fail_commit)
    before = rows(migrated_database[0], 'trace_events')
    try:
        with pytest.raises(RuntimeError, match='commit failure'):
            run(ops, caller, 'knowledge.head', {}, 'commit-failure')
    finally:
        event.remove(SQLSession, 'before_commit', fail_commit)
    assert world['contexts'].deliveries(world['project'], caller.invocation_id) == []
    assert rows(migrated_database[0], 'trace_events') == before
    monkeypatch.setattr(ops.delivery, 'record', real_record)
    assert run(ops, caller, 'knowledge.head', {}, 'commit-failure').result['revision']['id'] == caller.frozen_revision_id


def test_failed_query_replays_failure_without_rewriting_receipts(world, context, repository, migrated_database):
    _, _, request = start(world, repository, context)
    ops, caller, _ = queries(world, repository, request)
    for _ in range(2):
        refused('not_found', lambda: run(ops, caller, 'knowledge.lookup', {'item_id': 'missing'}, 'missing'))
    deliveries = world['contexts'].deliveries(world['project'], caller.invocation_id)
    assert len(deliveries) == 1 and deliveries[0]['payload']['failure'] == 'not_found'
    assert len(rows(migrated_database[0], 'trace_events', "WHERE kind = 'knowledge.receipt'")) == 1
    assert 'digest' not in deliveries[0]['receipts'][0]


def test_large_search_is_bounded_paged_truncated_and_project_isolated(world, context, repository):
    writer = world['writer']
    draft, sha = writer.open(world['revision']['revision_id'])
    # Realistic volume, with one large Unicode section and small members spread over many pages.
    for start_at in range(0, 1200, 200):
        sha, _ = writer.apply(draft, sha, [put('requirement', f'R{i + 2:04}', requirement(f'Needle {i}.'))
                                            for i in range(start_at, start_at + 200)])
    sha, (section_id,) = writer.apply(draft, sha, [put('section', 'large', section('Large', '🦊λ\n' * 16000),
                                                       document='architecture', root_position=1)])
    later = adopt(world['ops'], world['owner'], draft, world['revision']['revision_id'])
    snapshot = world['contexts'].prepare(str(context.root), [], client='codex', profile=core.profile_capture(context))
    _, _, request = start(world, repository, context, snapshot=snapshot)
    ops, caller, _ = queries(world, repository, request)
    other, _ = seed(world['ops'], '/synthetic/foreign')
    missing = refused('not_found', lambda: run(ops, caller, 'knowledge.lookup', {'item_id': 'missing'}, 'm'))
    foreign = refused('not_found', lambda: run(ops, caller, 'knowledge.lookup', {'item_id': other['R001']}, 'f'))
    assert (missing.code, missing.params) == (foreign.code, foreign.params)
    ids, cursor, pages = [], None, 0
    while True:
        args = {'query': 'needle', 'limit': 50, 'max_bytes': 32768}
        if cursor:
            args['cursor'] = cursor
        result = run(ops, caller, 'knowledge.search', args, 'page-' + str(pages)).result
        assert len(result['exposures']) <= 50 and len(freeze(result).encode()) <= core.MAX_RESULT
        assert result['page']['total'] == 1200 and result['revision']['id'] == later['revision_id']
        ids += [e['identity']['item_id'] for e in result['exposures']]
        pages += 1
        cursor = result['page'].get('next_cursor')
        if cursor is None:
            break
        if pages == 1:
            refused('cursor_invalid', lambda: run(ops, caller, 'knowledge.search',
                {'query': 'sign', 'cursor': cursor, 'limit': 50, 'max_bytes': 32768}, 'wrong-cursor'))
    assert len(ids) == len(set(ids)) == 1200 and pages >= 24
    result = run(ops, caller, 'knowledge.lookup', {'item_id': section_id, 'exposure': 'full', 'max_bytes': 1024}, 'large').result
    e = result['exposures'][0]
    assert e['exposure'] == 'excerpt' and e['truncated'] and len(e['data'].encode()) <= 1024
    assert e['digest'] == core.digest(e['data']) != e['identity']['content_sha256']
    # Sections are stable entities, and the next range reconstructs the canonical content exactly.
    parts, start_at = [], 0
    while True:
        result = run(ops, caller, 'knowledge.lookup', {'item_id': section_id, 'exposure': 'excerpt',
            'start': start_at, 'length': 32768, 'max_bytes': 32768}, 'range-' + str(start_at)).result
        e = result['exposures'][0]
        parts.append(e['data'])
        start_at = e['range']['end']
        if start_at == e['range']['total']:
            break
    assert json.loads(''.join(parts))['body'] == '🦊λ\n' * 16000


def test_prelaunch_crash_and_failed_observation_never_claim_initial_delivery(world, context, repository, migrated_database, monkeypatch):
    _, _, request = start(world, repository, context)
    invocation = 'managed_attempt:' + request.id
    assert world['contexts'].deliveries(world['project'], invocation) == []
    assert len(rows(migrated_database[0], 'invocation_contexts')) == 1
    assert not rows(migrated_database[0], 'knowledge_deliveries')
    # Reopened storage after a crash sees intent only. Recovery never starts another inference.
    reopened = make_engine(migrated_database[0])
    assert ContextRepository(reopened).deliveries(world['project'], invocation) == []
    assert not OperationJournal(reopened).recover('thread-1')
    reopened.dispose()
    original = storage.record_envelope
    monkeypatch.setattr(storage, 'record_envelope', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('disk failure')))
    with pytest.raises(RuntimeError), SQLSession(repository.engine) as session, session.begin():
        storage.observe(session, request.id, core.digest(request.prompt))
    assert world['contexts'].deliveries(world['project'], invocation) == []
    monkeypatch.setattr(storage, 'record_envelope', original)


def test_canonical_start_failure_rolls_back_attempt_boundary_and_invocation(world, context, repository, migrated_database, monkeypatch):
    def broken(*args):
        raise RuntimeError('Synthetic seal failure.')
    monkeypatch.setattr(storage, 'seal', broken)
    with pytest.raises(RuntimeError):
        start(world, repository, context)
    url = migrated_database[0]
    for table in ('managed_attempts', 'usage_invocations', 'workflow_operations', 'invocation_contexts', 'knowledge_deliveries'):
        assert rows(url, table) == []
    assert world['contexts'].snapshot(world['project'], world['snapshot'])  # prepared selection survives


def test_restored_readonly_evidence_without_checkout_or_writes(world, context, repository, migrated_database, tmp_path):
    job, claim, request = start(world, repository, context)
    ops, caller, _ = queries(world, repository, request)
    run(ops, caller, 'knowledge.lookup', {'item_id': world['ids']['R001'], 'exposure': 'excerpt', 'length': 20}, 'excerpt')
    with SQLSession(repository.engine) as session, session.begin():
        storage.observe(session, request.id, core.digest(request.prompt))
    live = world['contexts'].deliveries(world['project'], caller.invocation_id)
    from my_harness.core.engine.contracts import AgentResult
    record_result(repository, claim, job, request, AgentResult('{}', True, 0, status='complete'))
    repository.close_owner(claim)
    create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'archive')
    import shutil
    shutil.rmtree(context.root)
    archive = make_engine('sqlite:///' + str(tmp_path / 'archive/state.sqlite3'))
    statements = []
    event.listen(archive, 'before_cursor_execute', lambda conn, cursor, statement, *args: statements.append(statement))
    archived = ManagedRuntime(archive).frozen_contexts()
    assert archived.snapshot(world['project'], world['snapshot']) == world['contexts'].snapshot(world['project'], world['snapshot'])
    assert archived.deliveries(world['project'], caller.invocation_id) == live
    exact = archived.invocation(world['project'], caller.invocation_id)
    assert exact['prompt'] == request.prompt and exact['prompt_sha256'] == core.digest(request.prompt)
    assert exact['prompt_snapshot'] == json.loads(request.prompt_snapshot_json)
    assert all(s.lstrip().upper().startswith(('SELECT', 'PRAGMA')) for s in statements)
    with pytest.raises(ValueError):
        archived.prepare(str(context.root), [], client='codex', profile=core.profile_capture(context))
    with pytest.raises(ValueError):
        archived.deliveries('foreign-project', caller.invocation_id)
    archive.dispose()


def test_bounds_missing_instructions_and_foreign_snapshot_are_refused(world, context, repository):
    contexts = world['contexts']
    with pytest.raises(ValueError):
        contexts.prepare(str(context.root), [], client='codex', profile=capture('x' * core.MAX_CONTEXT))
    with pytest.raises(ValueError):
        contexts.prepare(str(context.root), ['foreign'], client='codex', profile=core.profile_capture(context))
    with pytest.raises(ValueError):
        contexts.snapshot('other-project', world['snapshot'])
    # A generated file cannot fill a missing canonical instruction document at revision 1.
    (context.root / 'AGENTS.md').write_text('Generated fallback must never be used.')
    with pytest.raises(ValueError):
        contexts.prepare(str(context.root), [], revision=1, client='codex', profile=core.profile_capture(context))


def test_insert_only_evidence_and_backup_digest_verification(world, context, repository, migrated_database, tmp_path):
    _, _, request = start(world, repository, context)
    with SQLSession(repository.engine) as session, session.begin():
        storage.observe(session, request.id, core.digest(request.prompt))
    from sqlalchemy.exc import IntegrityError
    for table in ('context_snapshots', 'invocation_contexts', 'knowledge_deliveries'):
        for mutation in (f'DELETE FROM {table}', f'UPDATE {table} SET created_at = created_at',
                         f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}'):
            with pytest.raises(IntegrityError), repository.engine.begin() as connection:
                connection.execute(text(mutation))
    # A forged insert cannot be rescued by a self-consistent trace digest; backup verifies stored exposure bytes.
    with repository.engine.begin() as connection:
        connection.execute(text('DROP TRIGGER knowledge_deliveries_no_update'))
        connection.execute(text("UPDATE knowledge_deliveries SET payload = '{}'"))
        import importlib
        migration = importlib.import_module('my_harness.migrations.versions.0033_frozen_context')
        connection.execute(text(migration.TRIGGERS['knowledge_deliveries_no_update']))
    with pytest.raises(BackupError):
        create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'bad', writers_stopped=True)


def test_known_prelaunch_refusal_records_failures_without_delivery(world, context, repository):
    _, claim, request = start(world, repository, context)
    repository.process_intent(claim, request.id, {'launch_permitted': False})
    repository.process_update(claim, request.id, 'process_finished', {'status': 'refused', 'group_state': 'dead'})
    deliveries = world['contexts'].deliveries(world['project'], 'managed_attempt:' + request.id)
    assert len(deliveries) == 1 and deliveries[0]['payload']['failure'] == 'launch_refused'
    assert all(r['failure'] == 'launch_refused' and 'digest' not in r for r in deliveries[0]['receipts'])
    assert all(e['data'] == '' for e in deliveries[0]['payload']['exposures'])


def test_adapter_receipt_failure_does_not_return_success_or_leave_a_receipt(world, context, repository, tmp_path, monkeypatch):
    adapter = probe_adapter(tmp_path, 'success')
    _, _, request = start(world, repository, context, adapter=adapter)
    def broken(*args, **kwargs):
        raise RuntimeError('Synthetic initial receipt failure.')
    monkeypatch.setattr(storage, 'record_envelope', broken)
    result = adapter.invoke(context, request)
    assert result.status != 'complete'
    assert world['contexts'].deliveries(world['project'], 'managed_attempt:' + request.id) == []


def test_context_preparation_failure_events_and_canonical_render_bounds(world, context, repository):
    with pytest.raises(ValueError):
        world['contexts'].prepare(str(context.root), ['missing'], client='codex', profile=core.profile_capture(context))
    events = rows(str(repository.engine.url), 'trace_events', "WHERE kind = 'context.preparation_failed'")
    assert len(events) == 1 and json.loads(events[0]['payload']) == {'failure': 'entity_missing'}
    with pytest.raises(ValueError):
        world['contexts'].render(world['project'], world['snapshot'], builtin_catalog(), 'review-task',
                                  {'INPUT_JSON': 'x' * core.MAX_PROMPT}, context)


def test_old_invocation_cannot_read_a_later_adoption_through_its_own_draft(world, context, repository):
    _, _, request = start(world, repository, context)
    ops, caller, permissions = queries(world, repository, request)
    permissions.allow('knowledge.draft.open', 'knowledge.draft.apply', 'knowledge.draft.get',
                      product=['knowledge.propose:section:architecture'])
    writer = Session(ops, caller, 'proposal')
    draft, sha = writer.open(world['revision']['revision_id'])
    writer.apply(draft, sha, [put('section', 'overview', section('Overview', 'Invocation proposal.'),
                                 document='architecture', root_position=0, provenance='inferred')])
    run(ops, caller, 'knowledge.draft.get', {'draft_id': draft}, 'proposal-before')
    receipts = world['contexts'].deliveries(world['project'], caller.invocation_id)
    assert all(r['authority'] != 'canonical' for d in receipts for r in d['receipts'])
    later = adopt(world['ops'], world['owner'], draft, world['revision']['revision_id'])
    refusal = refused('not_found', lambda: run(ops, caller, 'knowledge.draft.get', {'draft_id': draft}, 'proposal-after'))
    assert not refusal.params
    assert later['revision_id'] not in freeze(run(ops, caller, 'knowledge.head', {}, 'still-old').body())


def test_retired_instructions_and_extreme_serialized_result_bounds(world, context, repository):
    draft, sha = world['writer'].open(world['revision']['revision_id'])
    retired = {**section('Old rule', 'Retired must stay historical.'), 'status': 'retired'}
    world['writer'].apply(draft, sha, [
        put('section', 'retired', retired, document='instructions', root_position=3),
        put('section', 'escapes', section('Escapes', '\\"' * 30000), document='architecture', root_position=1)])
    adopt(world['ops'], world['owner'], draft, world['revision']['revision_id'])
    snapshot = world['contexts'].prepare(str(context.root), [], client='codex', profile=core.profile_capture(context))
    assert 'Retired must stay historical.' not in world['contexts'].snapshot(world['project'], snapshot)['data']['instructions']
    reader = owner_reader(world['project'])
    result = run(world['ops'], reader, 'knowledge.search', {'query': 'Escapes', 'exposure': 'full', 'max_bytes': 32768}).result
    assert result['exposures'] and len(freeze(result).encode()) <= core.MAX_RESULT
    assert result['exposures'][0]['truncated']


@pytest.mark.parametrize('field,value', [('frozen_revision_id', 'missing'), ('attempt_id', 'other'),
                                        ('thread_id', 'other'), ('role', 'executor')])
def test_receipt_sink_checks_the_persisted_boundary_in_addition_to_the_resolver(world, context, repository, field, value):
    _, _, request = start(world, repository, context)
    ops, caller, _ = queries(world, repository, request)
    refused('caller_unavailable', lambda: run(ops, replace(caller, **{field: value}), 'knowledge.head', {}, 'forged'))
    assert world['contexts'].deliveries(world['project'], caller.invocation_id) == []


def test_real_profile_and_instruction_client_are_enforced_before_launch(world, context, repository, tmp_path):
    from my_harness.core.engine.journal import JournalError
    other = replace(context, profile=replace(context.profile, executor_instructions='Different profile.'))
    with pytest.raises(ValueError):
        world['contexts'].render(world['project'], world['snapshot'], builtin_catalog(), 'review-task',
                                  {'INPUT_JSON': '{}'}, other)
    snapshot = world['contexts'].prepare_for(context, [], client='claude')
    adapter = probe_adapter(tmp_path, 'success')  # reviewer uses Codex in this fixture
    _, _, request = start(world, repository, context, adapter=adapter, snapshot=snapshot)
    with pytest.raises(JournalError, match='instruction target'):
        adapter.invoke(context, request)
    assert not (tmp_path / 'launches.jsonl').exists()
    deliveries = world['contexts'].deliveries(world['project'], 'managed_attempt:' + request.id)
    assert len(deliveries) == 1 and deliveries[0]['payload']['failure'] == 'launch_refused'


def adopt_staged_instructions(world, agents_text, wrappers=None):
    staged = knowledge.stage_instructions(agents_text, wrappers)
    draft, sha = world['writer'].open(world['revision']['revision_id'])
    changes = [put('section', 'review-' + s['code'], section(s['title'], s['body'], s['target']),
                   document='instructions', root_position=3 + s['position'] if s['parent'] is None else None)
               for s in staged['sections']]
    sha, ids = world['writer'].apply(draft, sha, changes)
    by_code = {s['code']: item for s, item in zip(staged['sections'], ids)}
    links = [{'op': 'link', 'kind': 'part_of', 'source_item_id': by_code[s['code']],
              'target_item_id': by_code[s['parent']], 'position': s['position']}
             for s in staged['sections'] if s['parent'] is not None]
    if links:
        world['writer'].apply(draft, sha, links)
    adopt(world['ops'], world['owner'], draft, world['revision']['revision_id'])
    return staged, by_code


@pytest.mark.parametrize('client', ['codex', 'claude', 'gemini'])
def test_staged_instruction_headings_structure_and_exact_delivered_bytes(world, context, repository, client):
    rules = ('Synthetic preamble.\n\n# Never publish without approval\n\n'
             '## Commands allowed only in disposable projects\n\n'
             '### Checks\nRun the synthetic check.\n')
    wrappers = {'claude': '@AGENTS.md\n# Claude approval required\n',
                'gemini': '@AGENTS.md\n# Gemini approval required\n'}
    staged, by_code = adopt_staged_instructions(world, rules, wrappers)
    sid = world['contexts'].prepare_for(context, [], client=client)
    snapshot = world['contexts'].snapshot(world['project'], sid)
    prompt, _ = world['contexts'].render(world['project'], sid, builtin_catalog(), 'review-task',
                                        {'INPUT_JSON': '{}'}, context)
    expected = ('Synthetic preamble.\n\n\n\n# Never publish without approval\n\n\n\n'
                '## Commands allowed only in disposable projects\n\n\n\n### Checks\nRun the synthetic check.\n')
    assert expected in prompt
    assert ('Claude approval required' in prompt) == (client == 'claude')
    assert ('Gemini approval required' in prompt) == (client == 'gemini')
    assert '@AGENTS.md' not in snapshot['data']['instructions']
    entries = {e['identity']['item_id']: e for e in snapshot['data']['entries'] if e['purpose'] == 'instructions'}
    for s in staged['sections']:
        if s['target'] not in ('agents', client):
            assert by_code[s['code']] not in entries
            continue
        e = entries[by_code[s['code']]]
        assert s['title'] in e['data'] and s['body'] in e['data']
        assert e['data'] in prompt and e['digest'] == core.digest(e['data'])
    _, _, request = start(world, repository, context, snapshot=sid)
    with SQLSession(repository.engine) as session, session.begin():
        storage.observe(session, request.id, core.digest(request.prompt))
    [delivery] = world['contexts'].deliveries(world['project'], 'managed_attempt:' + request.id)
    for receipt in delivery['receipts']:
        exposure = delivery['payload']['exposures'][receipt['index']]
        assert exposure['data'] in request.prompt and receipt['digest'] == core.digest(exposure['data'])
    # Re-reading the original immutable selection does not replace its exposures after adoption.
    assert snapshot == world['contexts'].snapshot(world['project'], sid)


def test_client_target_refusal_closes_and_survives_backup_and_query_only_restore(world, context, repository,
                                                                                 migrated_database, tmp_path):
    from my_harness.core.engine.contracts import AgentResult
    from my_harness.core.engine.journal import JournalError
    sid = world['contexts'].prepare_for(context, [], client='claude')
    adapter = probe_adapter(tmp_path, 'success')
    job, claim, request = start(world, repository, context, adapter=adapter, snapshot=sid)
    with pytest.raises(JournalError, match='instruction target'):
        adapter.invoke(context, request)
    record_result(repository, claim, job, request, AgentResult(None, False, None, error='Synthetic refusal', status='failed'))
    repository.close_owner(claim)
    invocation = 'managed_attempt:' + request.id
    evidence = world['contexts'].deliveries(world['project'], invocation)
    assert len(evidence) == 1 and all(r['failure'] == 'launch_refused' and 'digest' not in r
                                      for r in evidence[0]['receipts'])
    [process] = repository.processes(job.id)
    assert process['identity'] is None and process['spec']['launch_permitted'] is False
    assert 'artifacts' not in process['spec'] and 'prompt_path' not in process['spec']
    assert not (tmp_path / 'launches.jsonl').exists() and not (tmp_path / 'captures').exists()
    [ledger] = rows(migrated_database[0], 'usage_invocations')
    assert ledger['launch'] == 'not_invoked'
    create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    import shutil
    shutil.rmtree(context.root)
    engine = make_engine('sqlite:///' + str(tmp_path / 'restored/state.sqlite3'))
    with engine.connect() as connection:
        assert connection.scalar(text('PRAGMA query_only')) == 1
    contexts = ContextRepository(engine)
    assert contexts.deliveries(world['project'], invocation) == evidence
    assert contexts.invocation(world['project'], invocation)['prompt'] == request.prompt
    trace = OperationJournal(engine).events(str(context.root), 'thread-1')['items']
    assert [e for e in trace if e['kind'] == 'knowledge.receipt']
    assert not any('digest' in e['payload'] for e in trace if e['kind'] == 'knowledge.receipt')
    engine.dispose()


def test_executable_identity_change_before_go_records_known_failure_without_execution(world, context, repository,
                                                                                      tmp_path, monkeypatch, migrated_database):
    import my_harness.adapters.cli_agents as cli
    from my_harness.core.engine.journal import JournalError
    adapter = probe_adapter(tmp_path, 'success')
    job, claim, request = start(world, repository, context, adapter=adapter)
    real_identity = cli.launch_identity

    def changed(config):
        launch, _digest = real_identity(config)
        return launch, '0' * 64

    monkeypatch.setattr(cli, 'launch_identity', changed)
    with pytest.raises(JournalError, match='launch files changed'):
        adapter.invoke(context, request)
    assert not (tmp_path / 'launches.jsonl').exists()
    [process] = repository.processes(job.id)
    assert process['identity'] is not None and process['capture']['diagnostic_code'] == 'identity_changed'
    assert process['capture']['launch_permitted'] is False and process['capture']['launch_boundary'] == 'before_go'
    [delivery] = world['contexts'].deliveries(world['project'], 'managed_attempt:' + request.id)
    assert delivery['payload']['failure'] == 'launch_refused'
    assert all(r['failure'] == 'launch_refused' and 'digest' not in r for r in delivery['receipts'])
    from my_harness.core.engine.contracts import AgentResult
    record_result(repository, claim, job, request, AgentResult(None, False, None, error='Synthetic refusal', status='failed'))
    repository.close_owner(claim)
    create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True,
                  artifact_roots=(tmp_path / 'captures',))
    manifest = verify_bundle(tmp_path / 'backup')
    assert len(manifest['files']) == 1 and manifest['files'][0]['source'] == process['spec']['prompt_path']
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = make_engine('sqlite:///' + str(tmp_path / 'restored/state.sqlite3'))
    assert ContextRepository(restored).deliveries(world['project'], 'managed_attempt:' + request.id) == [delivery]
    restored.dispose()


@pytest.mark.parametrize('status', ['cancelled', 'partial', 'refused'])
def test_stop_or_refusal_without_positive_boundary_does_not_claim_nondelivery(world, context, repository, status):
    _, claim, request = start(world, repository, context)
    repository.process_intent(claim, request.id, {'provider': 'codex'})
    # Even a refusal diagnostic is not the adapter's explicit proof that GO was never released.
    repository.process_update(claim, request.id, 'process_finished',
        {'status': status, 'group_state': 'dead', 'diagnostic_code': 'identity_changed'})
    assert world['contexts'].deliveries(world['project'], 'managed_attempt:' + request.id) == []
    assert OperationJournal(repository.engine).operations(str(context.root), 'thread-1')['items'][0]['status'] == 'INTENDED'


@pytest.mark.parametrize('corruption', ['missing_artifacts', 'before_spawn', 'before_go'])
def test_backup_does_not_exempt_launched_process_artifacts(world, context, repository, tmp_path,
                                                          migrated_database, corruption):
    from my_harness.storage.models import ManagedProcessRow
    adapter = probe_adapter(tmp_path, 'success')
    job, claim, request = start(world, repository, context, adapter=adapter)
    result = adapter.invoke(context, request)
    assert result.status == 'complete'
    record_result(repository, claim, job, request, result)
    repository.close_owner(claim)
    with SQLSession(repository.engine) as session, session.begin():
        row = session.get(ManagedProcessRow, request.id)
        capture = dict(row.capture)
        capture.pop('artifacts')
        if corruption != 'missing_artifacts':
            capture.update(status='refused', launch_permitted=False, launch_boundary=corruption)
            if corruption == 'before_spawn':
                row.spec = {**row.spec, 'launch_permitted': False}
        row.capture = capture
    with pytest.raises(BackupError):
        create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'bad-backup', writers_stopped=True,
                      artifact_roots=(tmp_path / 'captures',))


def test_historical_body_only_context_stays_readable_without_rewriting_or_new_launch(world, context, repository,
                                                                                    migrated_database, tmp_path):
    from my_harness.storage.knowledge import KnowledgeSession
    from my_harness.storage.models import ContextSnapshotRow
    legacy_id = str(uuid4())
    with SQLSession(repository.engine) as session, session.begin():
        revision = KnowledgeSession(session).revision(world['project'], world['revision']['number'])
        data = core.assemble(revision, [], client='codex', profile=core.profile_capture(context), code=(),
                             context_format=core.LEGACY_FORMAT)
        assert data['format'] == 'frozen-context-1'
        assert data['instructions'] == '# Rules\nCanonical agents. {{DO_NOT_EVALUATE}}\n\nChild rules.'
        payload = freeze(data)
        session.add(ContextSnapshotRow(id=legacy_id, project_id=world['project'], revision_id=revision.id,
                                      sha256=core.digest(payload), payload=payload, created_at='2026-10-29T00:00:00Z'))
    before = world['contexts'].snapshot(world['project'], legacy_id)
    with pytest.raises(ValueError):
        world['contexts'].render(world['project'], legacy_id, builtin_catalog(), 'review-task', {'INPUT_JSON': '{}'}, context)
    assert world['contexts'].snapshot(world['project'], legacy_id) == before
    create_backup(migrated_database[0].removeprefix('sqlite:///'), tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = make_engine('sqlite:///' + str(tmp_path / 'restored/state.sqlite3'))
    assert ContextRepository(restored).snapshot(world['project'], legacy_id) == before
    restored.dispose()
