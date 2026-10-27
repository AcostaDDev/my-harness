"""OT007/D252: temporary SQLite, synthetic streams and owned fake CLI groups only."""
from contextlib import contextmanager
from dataclasses import replace
import json
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from my_harness.adapters.engine_fake import ScriptedCommandRunner, SyntheticWorkspace
from my_harness.adapters.processes import liveness
from my_harness.core.engine.journal import JournalError
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.managed import Conflict, OwnershipLost
from my_harness.storage.models import ManagedAttemptRow, ManagedProcessRow
from sqlalchemy.orm import Session
from test_cli_agents import adapter, setup_invocation
from test_managed import PLAN, VERSIONS, context, repository


def managed(repository, context, port, lease=1.5):
    job = repository.submit(context, 'P001-T001', 'P001', PLAN,
                            {**VERSIONS, **port.frozen_versions()}, key='lease')
    return job, LocalSupervisor(repository, lambda *_: (
        port, ScriptedCommandRunner([]), SyntheticWorkspace(context, ('app/main.txt',))), lease_seconds=lease)


def test_stream_survives_real_sqlite_busy_during_one_renewal(tmp_path, context, repository, monkeypatch):
    import sqlite3
    port = adapter(tmp_path, 'flow', timeout=15)
    port.agents['executor'] = replace(port.agents['executor'], environment=
        port.agents['executor'].environment + (('PROBE_STREAM_SECONDS', '4.5'),))
    job, supervisor = managed(repository, context, port, lease=3)
    original, calls = repository.heartbeat, []

    def transient(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            # An independent SQLite writer makes the first renewal fail with a real busy error.
            with sqlite3.connect(repository.engine.url.database, timeout=5) as blocker:
                blocker.execute('BEGIN IMMEDIATE')
                try:
                    with repository.engine.connect() as connection:
                        connection.exec_driver_sql('PRAGMA busy_timeout=1')
                        connection.execute(text('UPDATE managed_runs SET version = version WHERE 0'))
                finally:
                    blocker.rollback()
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, 'heartbeat', transient)
    assert supervisor.run_once().status == 'DONE'
    assert len(calls) >= 3
    history = repository.get_run(job.run_id).history
    assert history.status == 'acceptance_ready' and len(history.attempts) == 2
    closed = next(e for e in repository.events(job.run_id, after=repository.get_run(job.run_id).version - 3)
                  if e['kind'] == 'process_owner_closed')
    assert closed['payload']['heartbeat'] == {'failures': 1, 'last_error': 'OperationalError', 'lost': False}
    assert len((tmp_path / 'launches.jsonl').read_text().splitlines()) == 2


def test_permanent_renewal_failure_stops_cli_and_preserves_partial_evidence(tmp_path, context, repository, monkeypatch):
    port = adapter(tmp_path, 'slow_stream', timeout=30)
    job, supervisor = managed(repository, context, port)

    def broken(*args, **kwargs):
        raise OperationalError('UPDATE', {}, Exception('database is locked'))

    monkeypatch.setattr(repository, 'heartbeat', broken)
    started = time.monotonic()
    with pytest.raises(JournalError, match='renewal.*OperationalError'):
        supervisor.run_once()
    assert time.monotonic() - started < 15
    assert repository.get_job(job.id).status == 'RECOVERY_REQUIRED'
    assert repository.claim() is None
    process, = repository.processes(job.id)
    capture = process['capture']
    assert process['status'] == 'STOPPED' and liveness(process['identity'], group=True) == 'dead'
    assert capture['status'] == 'interrupted' and capture['settled_by'] == 'closing_owner'
    assert capture['group_state'] == capture['reported_group_state'] == 'dead'
    assert capture['final_usage_observed'] is False and capture['artifacts']['stdout']['size'] > 0
    with Session(repository.engine) as session:
        assert session.get(ManagedAttemptRow, process['attempt_id']).result_json is None
    events = repository.events(job.run_id, limit=1000)
    closed = next(e for e in events if e['kind'] == 'process_owner_closed')
    assert closed['payload']['heartbeat']['last_error'] == 'OperationalError'
    assert closed['payload']['heartbeat']['lost'] is True
    interrupted = next(e for e in events if e['kind'] == 'process_interrupted')
    assert interrupted['sequence'] < closed['sequence'] and interrupted['payload']['partial_capture'] is True
    run = repository.get_run(job.run_id)
    repository.confirm_stopped(job.id, owner_token=repository.get_job(job.id).owner_token,
                               expected_version=run.version, reason='Synthetic group independently observed dead')
    assert repository.get_job(job.id).status == 'INTERRUPTED'
    assert repository.get_run(job.run_id).history.attempts[0].result.error.startswith('Interrupted invocation')
    assert repository.processes(job.id)[0]['capture'] == capture
    assert len((tmp_path / 'launches.jsonl').read_text().splitlines()) == 1


def test_sustained_stream_batches_transactions_and_preserves_event_bytes(tmp_path, context, repository, monkeypatch):
    port = adapter(tmp_path, 'long_text')
    job, claim, request = setup_invocation(repository, context, port)
    original, batches = repository.process_updates, []

    def counted(claim, attempt, items):
        batches.append(list(items))
        return original(claim, attempt, items)

    monkeypatch.setattr(repository, 'process_updates', counted)
    result = port.invoke(context, request)
    assert result.status == 'complete'
    # Compare every parsed record with the independent original JSONL, including order and sequences.
    from pathlib import Path
    raw = (Path(repository.processes(job.id)[0]['spec']['artifacts']) / 'stdout.bin').read_bytes()
    from my_harness.adapters.streams import AgentStream
    expected = []
    parser = AgentStream('claude', lambda kind, payload: expected.append((kind, payload)))
    parser.feed(raw)
    parser.finish(0)
    events, after = [], 0
    while page := repository.events(job.run_id, after=after, limit=1000):
        events.extend(page)
        after = page[-1]['sequence']
    actual = [(e['kind'], {k: v for k, v in e['payload'].items()
                           if k not in ('job_id', 'attempt_id', 'status', 'stage', 'revisions')})
              for e in events if e['kind'] == 'agent_event']
    assert actual == [(kind, payload) for kind, payload in expected if kind == 'agent_event']
    assert len(actual) == 1501 and len(batches) < len(actual) / 10
    assert [e['sequence'] for e in events] == list(range(1, events[-1]['sequence'] + 1))
    repository.close_owner(claim)


def test_chunk_is_one_transaction_and_rolls_back_on_invalid_spawn(tmp_path, context, repository, monkeypatch):
    port = adapter(tmp_path)
    job, claim, request = setup_invocation(repository, context, port)
    repository.process_intent(claim, request.id, {'synthetic': True})
    original, transactions = repository._write, []

    @contextmanager
    def counted():
        transactions.append(True)
        with original() as session:
            yield session

    monkeypatch.setattr(repository, '_write', counted)
    before = repository.events(job.run_id)
    with pytest.raises(Conflict, match='identity'):
        repository.process_updates(claim, request.id, [
            ('stream_bytes', {'stream': 'stdout', 'offset': 0, 'size': 3}),
            ('process_spawned', {'host': 'synthetic'}),
            ('process_spawned', {'host': 'foreign'})])
    assert len(transactions) == 1 and repository.events(job.run_id) == before
    assert repository.processes(job.id)[0]['identity'] is None


@pytest.mark.parametrize('state', ['dead', 'alive', 'unknown'])
@pytest.mark.parametrize('partial', [None, {'status': 'interrupted', 'group_state': 'dead'}, ['invalid'], 'bad json'])
def test_closing_owner_uses_liveness_without_completing_attempt(
        tmp_path, context, repository, monkeypatch, state, partial):
    port = adapter(tmp_path)
    job, claim, request = setup_invocation(repository, context, port)
    artifacts = tmp_path / 'partial'
    artifacts.mkdir()
    if partial is not None:
        (artifacts / 'capture.json').write_text(partial if isinstance(partial, str) else json.dumps(partial))
    repository.process_intent(claim, request.id, {'artifacts': str(artifacts)})
    repository.process_update(claim, request.id, 'process_spawned', {'host': 'synthetic', 'pid': 42, 'pgid': 42})
    from my_harness.adapters import processes
    monkeypatch.setattr(processes, 'liveness', lambda *_, **__: state)
    repository.quarantine(claim, 'Synthetic lease loss')
    with pytest.raises(OwnershipLost):
        repository.close_owner(replace(claim, owner_token='foreign'))
    assert repository.processes(job.id)[0]['capture'] is None
    repository.close_owner(claim)
    process, = repository.processes(job.id)
    assert process['status'] == ('STOPPED' if state == 'dead' else 'UNCERTAIN')
    assert process['capture']['group_state'] == state
    assert process['capture']['status'] == 'interrupted'
    with Session(repository.engine) as session:
        assert session.get(ManagedAttemptRow, request.id).result_json is None
    if state != 'dead':
        with pytest.raises(Conflict):
            repository.confirm_stopped(job.id, owner_token=claim.owner_token,
                expected_version=repository.get_run(job.run_id).version, reason='Expiry is not proof of death')
    assert repository.claim() is None


def test_close_owner_never_replaces_a_stored_capture(tmp_path, context, repository):
    port = adapter(tmp_path)
    job, claim, request = setup_invocation(repository, context, port)
    result = port.invoke(context, request)
    with repository._write() as session:
        session.get(ManagedProcessRow, request.id).status = 'RUNNING'
    before = repository.processes(job.id)
    repository.close_owner(claim)
    assert repository.processes(job.id) == before
    assert json.loads(result.metadata_json) == before[0]['capture']


def test_output_guard_is_already_visible_in_managed_attempt_evidence(tmp_path, context, repository):
    port = adapter(tmp_path, 'repetitive', timeout=15)
    job, supervisor = managed(repository, context, port, lease=10)
    assert supervisor.run_once().status == 'DONE'
    history = repository.get_run(job.run_id).history
    assert history.status == 'stopped' and len(history.attempts) == 1
    attempt = history.attempts[0]
    assert attempt.result.status == 'repetitive'
    capture = repository.processes(job.id)[0]['capture']
    assert capture['output_guard']['policy'] == 'output-guard-1'
    assert capture['output_guard']['code'] == 'repetitive_output'
    assert capture['final_usage_observed'] is False and 'CLI repetitive' in str(history.stop)
