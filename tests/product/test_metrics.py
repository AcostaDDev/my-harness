"""H6.4: per-attempt metrics and aggregates with synthetic streams, temporary Git/SQLite; no providers.

The streams imitate the shape characterized in D071 (docs/archive/phase-007/H6.4_METRICS.md) with made-up values.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys

from alembic import command
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.adapters.engine_fake import ScriptedCommandRunner, SyntheticWorkspace
from my_harness.cli import main
from my_harness.core.engine.documents import render_summary
from my_harness.core.engine.metrics import StreamMetrics, attempt_metrics, replay
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.metrics import MetricsViews, backfill
from my_harness.storage.models import AttemptMetricRow, AttemptModelMetricRow, ManagedAttemptRow
from my_harness.storage.retention import apply_retention, preview_retention
from test_backup import db_path, dump_rows
from test_cli_agents import PROBE, wait_until
from test_managed import PLAN, VERSIONS, Clock, SyntheticCrash, context, edit, repository, review, submit, worker  # noqa: F401
from test_managed_api import VERSIONS as VERSIONS_API, client
from test_phases import World, checkout  # noqa: F401

GLOBAL = {'root': None, 'phase': None, 'task': None}
VOLATILE = ('source', 'recorded_at', 'diagnostics')


def usage_adapter(tmp_path, mode='flow', timeout=5):
    env = (('PROBE_EXPLICIT', 'selected'), ('PROBE_RECORD', str(tmp_path / 'launches.jsonl')),
           ('PROBE_CHILD', str(tmp_path / 'child.pid')), ('PROBE_USAGE', '1'))
    return CLIProcessAdapter([CLIConfig(provider, (sys.executable, PROBE, provider, mode), version, env, timeout)
                              for provider, version in (('codex', '0.163.0'), ('claude', '2.1.304'))],
                             tmp_path / 'captures')


def flow(tmp_path, context, repository, mode='flow', key='metrics', planning='agent'):
    """Codex planner and reviewer, Claude executor, through the real adapter and the synthetic probe."""
    ctx = replace(context, policy=replace(context.policy, planning_mode=planning))
    port = usage_adapter(tmp_path, mode)
    job = repository.submit(ctx, 'P001-T001', 'P001', PLAN, {**VERSIONS, **port.frozen_versions()}, key=key)

    def factory(frozen, versions):
        return port, ScriptedCommandRunner([]), SyntheticWorkspace(frozen, ('app/main.txt',))
    return port, job, LocalSupervisor(repository, factory)


def metric_rows(repository, run_id=None):
    with Session(repository.engine) as session:
        query = select(AttemptMetricRow).order_by(AttemptMetricRow.run_id, AttemptMetricRow.number)
        if run_id is not None:
            query = query.where(AttemptMetricRow.run_id == run_id)
        return [{c.name: getattr(row, c.name) for c in AttemptMetricRow.__table__.columns}
                for row in session.scalars(query)]


def model_rows(repository):
    with Session(repository.engine) as session:
        return [(row.attempt_id, row.model, row.input_tokens, row.cache_read_tokens, row.cache_write_tokens,
                 row.output_tokens, row.reasoning_tokens, row.cost_usd)
                for row in session.scalars(select(AttemptModelMetricRow).order_by(AttemptModelMetricRow.attempt_id,
                                                                                  AttemptModelMetricRow.model))]


def stable(rows):
    return [{k: v for k, v in row.items() if k not in VOLATILE} for row in rows]


def clear_metrics(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute('DELETE FROM attempt_model_metrics')
        db.execute('DELETE FROM attempt_metrics')
        db.commit()


def as_terminal_1(path):
    """Exact shape of the results sealed before 0014 (cli-9): no turns, API duration or counters."""
    with closing(sqlite3.connect(path)) as db:
        for attempt_id, raw in db.execute('SELECT id, result_json FROM managed_attempts').fetchall():
            result = json.loads(raw)
            if result.get('metadata_json'):
                meta = json.loads(result['metadata_json'])
                meta.pop('normalization'), meta.pop('stream_metrics')
                for key in ('num_turns', 'duration_api_ms'):
                    meta['observed'].pop(key, None)
                result['metadata_json'] = json.dumps(meta, sort_keys=True, separators=(',', ':'))
                db.execute('UPDATE managed_attempts SET result_json=? WHERE id=?', (json.dumps(result), attempt_id))
        db.commit()


# --- pure catalog -------------------------------------------------------------------------------


CLAUDE_STREAM = [
    {'type': 'system', 'subtype': 'init', 'model': 'm-a'},
    {'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'usage': {
        'input_tokens': 2, 'cache_read_input_tokens': 10, 'cache_creation_input_tokens': 5, 'output_tokens': 1}}}},
    {'type': 'assistant', 'message': {'id': 'm1', 'model': 'm-a', 'usage': {'output_tokens': 1},
                                      'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Read'}]}},
    {'type': 'assistant', 'message': {'id': 'm1', 'model': 'm-a', 'usage': {'output_tokens': 1},
                                      'content': [{'type': 'tool_use', 'id': 't1', 'name': 'Read'}]}},
    # message_delta: cumulative usage of the message; here only output, input follows message_start.
    {'type': 'stream_event', 'event': {'type': 'message_delta', 'usage': {'output_tokens': 20}}},
    {'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed', 'utilization': 0.9}},
    {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 9871},
    {'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'usage': {
        'input_tokens': 1, 'cache_read_input_tokens': 15, 'cache_creation_input_tokens': 0, 'output_tokens': 1}}}},
]
CLAUDE_RESULT = {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 2, 'duration_ms': 50,
                 'duration_api_ms': 40, 'total_cost_usd': 0.5, 'permission_denials': [{'tool_name': 'Bash'}],
                 'usage': {'input_tokens': 3, 'cache_read_input_tokens': 25, 'cache_creation_input_tokens': 5,
                           'output_tokens': 30, 'output_tokens_details': {'thinking_tokens': 4}},
                 'modelUsage': {'m-a': {'inputTokens': 2, 'outputTokens': 20, 'cacheReadInputTokens': 10,
                                        'cacheCreationInputTokens': 5, 'thinkingTokens': 4, 'costUSD': 0.4},
                                'm-b': {'inputTokens': 1, 'outputTokens': 10, 'cacheReadInputTokens': 15,
                                        'cacheCreationInputTokens': 0, 'costUSD': 0.1}}}


def sealed(provider, events, *, terminal=True, wall=1.5):
    """Metadata as the adapter seals it (terminal-2) for a given stream."""
    metrics = StreamMetrics(provider)
    observed = {}
    for event in events:
        is_terminal = terminal and event is events[-1]
        if is_terminal:
            observed.update({k: event[k] for k in ('usage', 'modelUsage', 'duration_ms', 'total_cost_usd',
                                                    'permission_denials', 'num_turns', 'duration_api_ms') if k in event})
        if isinstance(event.get('message'), dict) and 'model' in event['message']:
            observed.setdefault('message_models', [])
            if event['message']['model'] not in observed['message_models']:
                observed['message_models'].append(event['message']['model'])
        metrics.event(event, terminal=is_terminal)
    meta = {'observed': observed, 'wall_duration_seconds': wall, 'normalization': 'terminal-2',
            'stream_metrics': metrics.summary()}
    return {'payload_json': None, 'metadata_json': json.dumps(meta)}


def compute(provider, result, role='executor', status='COMPLETE', **kwargs):
    return attempt_metrics(request={'role': role, 'selection': {'model': 'req', 'effort': 'low'}}, result=result,
                           status=status, spec={'provider': provider, 'adapter_version': 'cli-9', 'cli_version': 'x'},
                           executor_round=1, **kwargs)


def test_claude_terminal_total_wins_over_incremental_messages_and_models_are_listed():
    row = compute('claude', sealed('claude', CLAUDE_STREAM + [CLAUDE_RESULT]))
    assert (row['accounting'], row['input_semantics']) == ('terminal', 'excludes_cache')
    # Terminal totals: neither per-message usage nor `assistant` snapshots are added on top.
    assert (row['input_tokens'], row['cache_read_tokens'], row['cache_write_tokens'], row['output_tokens'],
            row['reasoning_tokens']) == (3, 25, 5, 30, 4)
    assert (row['uncached_input_tokens'], row['total_tokens']) == (3, 63)
    assert row['models'] == [
        {'model': 'm-a', 'input_tokens': 2, 'cache_read_tokens': 10, 'cache_write_tokens': 5, 'output_tokens': 20,
         'reasoning_tokens': 4, 'cost_usd': 0.4},
        {'model': 'm-b', 'input_tokens': 1, 'cache_read_tokens': 15, 'cache_write_tokens': 0, 'output_tokens': 10,
         'reasoning_tokens': None, 'cost_usd': 0.1}]
    assert row['reported_models'] == ['m-a', 'm-b'] and row['reported_effort'] is None
    assert (row['turns'], row['provenance']['turns']) == (2, 'reported')
    assert (row['tools'], row['tool_calls']) == ({'Read': 1}, 1)  # the same repeated tool_use counts once
    assert (row['permission_denials'], row['duration_ms'], row['api_duration_ms'], row['cost_usd'], row['wall_ms']) \
        == (1, 50, 40, 0.5, 1500)
    assert row['provenance']['wall_ms'] == 'measured' and row['provenance']['cost_usd'] == 'reported'
    assert row['provenance']['total_tokens'] == 'derived' and row['provenance']['requested_model'] == 'requested'
    # Nothing from rate_limit_event or the estimated reasoning count: no quota is inferred.
    assert not any(word in json.dumps(row) for word in ('rate_limit', 'utilization', 'quota', '9871'))


def test_claude_without_terminal_derives_partial_usage_from_message_deltas():
    row = compute('claude', sealed('claude', CLAUDE_STREAM, terminal=False), status='CANCELLED')
    assert row['accounting'] == 'messages' and row['provenance']['input_tokens'] == 'derived'
    # m1: input from message_start and cumulative output from message_delta; m2 without delta: its initial snapshot.
    assert (row['input_tokens'], row['cache_read_tokens'], row['cache_write_tokens'], row['output_tokens']) \
        == (3, 25, 5, 21)
    assert row['reasoning_tokens'] is None and row['provenance']['reasoning_tokens'] == 'absent'
    assert (row['turns'], row['cost_usd'], row['duration_ms']) == (None, None, None)
    assert row['reported_models'] == ['m-a'] and row['status'] == 'CANCELLED'


def test_codex_cumulative_terminal_derived_turns_and_absent_fields():
    events = [{'type': 'item.completed', 'item': {'id': 'i0', 'type': 'command_execution'}},
              {'type': 'item.completed', 'item': {'id': 'i0', 'type': 'command_execution'}},
              {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{}'}},
              {'type': 'item.completed', 'item': {'id': 'i1', 'type': 'mcp_tool_call'}},
              {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 60,
                                                    'cache_write_input_tokens': 0, 'output_tokens': 9,
                                                    'reasoning_output_tokens': 4}}]
    row = compute('codex', sealed('codex', events), role='planner')
    assert (row['accounting'], row['input_semantics']) == ('terminal', 'includes_cache_read')
    assert (row['input_tokens'], row['uncached_input_tokens'], row['total_tokens']) == (100, 40, 109)
    assert (row['turns'], row['provenance']['turns']) == (3, 'derived')
    assert (row['tools'], row['tool_calls']) == ({'command_execution': 1, 'mcp_tool_call': 1}, 2)
    for field in ('cost_usd', 'duration_ms', 'api_duration_ms', 'permission_denials', 'reported_models', 'models'):
        assert row['provenance'][field] == 'absent'
    assert row['cost_usd'] is None and row['models'] == []
    # Non-zero cache write: uncertified semantics, total absent instead of guessed.
    events[-1]['usage']['cache_write_input_tokens'] = 7
    assert compute('codex', sealed('codex', events))['total_tokens'] is None


@pytest.mark.parametrize('value', [None, -1, '5', 1.5, True])
def test_malformed_or_null_counts_are_absence_never_zero(value):
    result = dict(CLAUDE_RESULT, usage={'input_tokens': value, 'cache_read_input_tokens': 0,
                                        'cache_creation_input_tokens': 0, 'output_tokens': 1}, num_turns=value)
    row = compute('claude', sealed('claude', [result]))
    assert row['input_tokens'] is None and row['provenance']['input_tokens'] == 'absent'
    assert row['total_tokens'] is None and row['turns'] is None
    assert row['cache_read_tokens'] == 0 and row['provenance']['cache_read_tokens'] == 'reported'


def test_historical_results_without_metadata_stay_readable_with_absent_values():
    for result in ({'payload_json': '{"result": "x"}'}, None):
        row = attempt_metrics(request={'role': 'executor', 'selection': {'model': 'm', 'effort': 'e'}}, result=result,
                              status='COMPLETED', spec=None, executor_round=1)
        assert row['provider'] is None and row['normalization'] is None and row['accounting'] is None
        assert all(row[name] is None for name in ('input_tokens', 'total_tokens', 'turns', 'wall_ms', 'tools'))
        assert set(row['provenance'].values()) == {'requested', 'absent'}


def test_replay_of_a_terminal_1_capture_adds_only_what_the_seal_lacked():
    raw = b''.join(json.dumps(event).encode() + b'\n' for event in CLAUDE_STREAM + [CLAUDE_RESULT])
    stream = replay('claude', raw + b'{"type":"res')  # partial tail ignored as in the capture
    old = json.loads(sealed('claude', CLAUDE_STREAM + [CLAUDE_RESULT])['metadata_json'])
    old.pop('normalization'), old.pop('stream_metrics'), old['observed'].pop('num_turns')
    old['observed']['usage'] = {**old['observed']['usage'], 'output_tokens': 31}  # the seal prevails
    row = compute('claude', {'metadata_json': json.dumps(old)}, stream=stream)
    assert (row['turns'], row['tools'], row['output_tokens'], row['normalization']) == (2, {'Read': 1}, 31, 'terminal-1')
    without = compute('claude', {'metadata_json': json.dumps(old)})
    assert (without['turns'], without['tools'], without['api_duration_ms']) == (None, None, 40)


# --- capture in the result transaction ------------------------------------------------------------


def test_cli_flow_materializes_one_row_per_attempt_from_the_sealed_capture(tmp_path, context, repository):
    port, job, supervisor = flow(tmp_path, context, repository)
    assert supervisor.run_once().status == 'DONE'
    assert repository.get_run(job.run_id).status == 'ACCEPTANCE_READY'
    rows = metric_rows(repository)
    with Session(repository.engine) as session:
        attempts = session.scalars(select(ManagedAttemptRow).order_by(ManagedAttemptRow.number)).all()
        assert [row['attempt_id'] for row in rows] == [a.id for a in attempts]
        assert [row['recorded_at'] for row in rows] == [a.finished_at for a in attempts]
    planner, executor, reviewer = rows
    assert [r['role'] for r in rows] == ['planner', 'executor', 'reviewer']
    assert [r['executor_round'] for r in rows] == [0, 1, 1]
    assert {r['source'] for r in rows} == {'capture'} and {r['normalization'] for r in rows} == {'terminal-2'}
    assert (planner['provider'], planner['adapter_version'], planner['cli_version']) == ('codex', 'cli-14', '0.163.0')
    assert (planner['total_tokens'], planner['uncached_input_tokens'], planner['turns'], planner['tools']) \
        == (1050, 400, 3, {'command_execution': 1, 'file_change': 1})
    assert (executor['provider'], executor['total_tokens'], executor['output_tokens'], executor['turns']) \
        == ('claude', 776, 70, 2)
    assert executor['reported_models'] == ['claude-synthetic-a', 'claude-synthetic-b']
    assert (executor['tools'], executor['permission_denials'], executor['cost_usd']) == ({'Read': 1}, 0, 0.0125)
    assert reviewer['verdict'] == 'ACCEPT' and planner['verdict'] is None
    assert [m[1:] for m in model_rows(repository)] == [
        ('claude-synthetic-a', 3, 100, 400, 30, 12, 0.01), ('claude-synthetic-b', 3, 200, 0, 40, 0, 0.0025)]
    summary = MetricsViews(repository.engine).summary(GLOBAL)['consumption']
    assert summary['tokens']['total_tokens'] == {'sum': 2876, 'attempts': 3}
    # Raw input (Codex includes the cache, Claude does not) is not aggregated; uncached input is.
    assert 'input_tokens' not in summary['tokens']
    assert summary['tokens']['uncached_input_tokens'] == {'sum': 806, 'attempts': 3}
    assert summary['turns_reported'] == {'sum': 2, 'attempts': 1}
    assert summary['turns_derived'] == {'sum': 6, 'attempts': 2}
    assert summary['cost_usd']['sum'] == 0.0125 and summary['accounting'] == {'terminal': 3, 'messages': 0, 'absent': 0}


def test_cancelled_failed_and_double_terminal_attempts_are_counted_once(tmp_path, context, repository):
    port, job, supervisor = flow(tmp_path / 'hang', context, repository, mode='hang', planning='deterministic')
    with ThreadPoolExecutor() as pool:
        future = pool.submit(supervisor.run_once)
        wait_until(lambda: any(e['kind'] == 'stream_bytes' and e['payload']['size']
                               for e in repository.events(job.run_id)) and len(metric_rows(repository)) == 0
                   and _stream_has(port, 'message_start', 2))
        assert port.cancel(repository.processes(job.id)[0]['attempt_id']).requested
        assert future.result(timeout=10).status == 'DONE'
    [cancelled] = metric_rows(repository, job.run_id)
    assert (cancelled['status'], cancelled['accounting'], cancelled['provenance']['output_tokens']) \
        == ('CANCELLED', 'messages', 'derived')
    assert (cancelled['input_tokens'], cancelled['cache_read_tokens'], cancelled['output_tokens'],
            cancelled['total_tokens'], cancelled['turns']) == (6, 300, 31, 737, None)

    _, failed_job, failed = flow(tmp_path / 'error', context, repository, mode='error', key='error',
                                 planning='deterministic')
    failed.run_once()
    [executor] = metric_rows(repository, failed_job.run_id)
    assert (executor['status'], executor['accounting'], executor['total_tokens']) == ('FAILED', 'terminal', 776)

    _, double_job, double = flow(tmp_path / 'double', context, repository, mode='double_terminal', key='double',
                                 planning='deterministic')
    double.run_once()
    [invalid] = metric_rows(repository, double_job.run_id)
    # Two terminals: invalid status and the total of only one, never the sum of both.
    assert (invalid['status'], invalid['total_tokens'], invalid['turns']) == ('INVALID', 776, 2)


def _stream_has(port, kind, count):
    files = list(port.artifact_root.glob('*/stdout.bin'))
    return bool(files) and files[0].read_text(errors='replace').count(f'"{kind}"') >= count


def test_codex_failure_reports_no_usage_as_absent_not_zero(tmp_path, context, repository):
    port = usage_adapter(tmp_path, 'error')
    from test_cli_agents import setup_invocation
    job, claim, request = setup_invocation(repository, context, port, role='reviewer')
    result = port.invoke(context, request)
    assert result.status == 'failed'
    history = repository.get_run(job.run_id).history
    from my_harness.core.engine.contracts import Attempt
    repository.checkpoint(claim, replace(history, attempts=(Attempt(request, result),)), 'reviewer')
    [row] = metric_rows(repository)
    assert (row['provider'], row['status'], row['accounting'], row['total_tokens']) == ('codex', 'FAILED', None, None)
    assert row['provenance']['input_tokens'] == 'absent' and row['turns'] == 3  # items actually observed


def test_metrics_and_result_commit_atomically(context, repository, monkeypatch):
    job = submit(repository, context)
    supervisor, _, _, _ = worker(repository, context, [edit(), review()])

    def broken(*args, **kwargs):
        raise RuntimeError('synthetic metrics failure')
    monkeypatch.setattr('my_harness.storage.managed.record_metrics', broken)
    with pytest.raises(RuntimeError, match='synthetic metrics failure'):
        supervisor.run_once()
    with Session(repository.engine) as session:
        # The result was not recorded without its metrics row: same transaction.
        assert session.scalars(select(ManagedAttemptRow.result_json).where(ManagedAttemptRow.run_id == job.run_id)).all() == [None]
    assert metric_rows(repository) == []


def test_interrupted_attempts_get_rows_when_the_stopped_writer_is_confirmed(context, repository):
    clock = Clock()
    repository.clock = clock
    job = submit(repository, context)

    def crash(context, request):
        raise SyntheticCrash()
    supervisor, _, _, _ = worker(repository, context, [crash])
    with pytest.raises(SyntheticCrash):
        supervisor.run_once()
    assert metric_rows(repository) == []
    clock.now += timedelta(seconds=31)
    assert repository.recover_expired() == [job.id]
    record = repository.get_run(job.run_id)
    repository.confirm_stopped(job.id, owner_token=repository.get_job(job.id).owner_token,
                               expected_version=record.version, reason='Synthetic owner joined')
    [row] = metric_rows(repository)
    assert (row['status'], row['role'], row['executor_round'], row['provider']) == ('INTERRUPTED', 'executor', 1, None)
    assert row['error'].startswith('Interrupted invocation') and row['diagnostics'] == ['no_process']
    assert row['total_tokens'] is None and row['day'] == '2026-10-11'


# --- explicit backfill -------------------------------------------------------------------------


def test_backfill_from_result_json_reproduces_capture_and_is_idempotent(tmp_path, context, repository,
                                                                         migrated_database):
    port, job, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    captured, models = metric_rows(repository), model_rows(repository)
    path = db_path(migrated_database)
    clear_metrics(path)
    assert MetricsViews(repository.engine).summary(GLOBAL)['attempts_without_metrics'] == 3
    report = backfill(repository.engine)
    assert report == {'inserted': 3, 'already_present': 0, 'streams': {'stream_outside_authorized_roots': 3}}
    filled = metric_rows(repository)
    assert stable(filled) == stable(captured) and model_rows(repository) == models
    assert {row['source'] for row in filled} == {'backfill'}
    assert backfill(repository.engine, artifact_roots=[port.artifact_root]) == {
        'inserted': 0, 'already_present': 0, 'streams': {}}
    assert metric_rows(repository) == filled
    assert MetricsViews(repository.engine).summary(GLOBAL)['attempts_without_metrics'] == 0


def test_backfill_of_old_captures_reads_only_verified_streams(tmp_path, context, repository, migrated_database):
    port, job, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    captured = metric_rows(repository)
    path = db_path(migrated_database)
    as_terminal_1(path)
    clear_metrics(path)
    backfill(repository.engine)
    blind = metric_rows(repository)
    assert [row['normalization'] for row in blind] == ['terminal-1'] * 3
    assert [row['total_tokens'] for row in blind] == [row['total_tokens'] for row in captured]
    assert [row['turns'] for row in blind] == [None, None, None] and blind[1]['api_duration_ms'] is None
    clear_metrics(path)
    tampered = Path(json.loads(json.loads(_result(path, 3))['metadata_json'])['artifacts']['stdout']['path'])
    tampered.write_bytes(tampered.read_bytes() + b'\n')
    report = backfill(repository.engine, artifact_roots=[port.artifact_root])
    assert report['streams'] == {'stream_hash_mismatch': 1, 'stream_verified': 2}
    verified = metric_rows(repository)
    assert [row['turns'] for row in verified] == [3, 2, None]
    assert [row['tools'] for row in verified[:2]] == [captured[0]['tools'], captured[1]['tools']]
    assert verified[1]['api_duration_ms'] == 800 and verified[1]['provenance']['turns'] == 'reported'
    assert verified[2]['diagnostics'] == ['stream_hash_mismatch'] and verified[2]['total_tokens'] == 1050
    # What was read from a verified stream would not be rebuilt if that stream is retired: the downgrade refuses.
    config = migrated_database[1]
    with pytest.raises(RuntimeError, match='Stream-derived'):
        command.downgrade(config, '0013_bootstrap')
    command.check(config)


def _result(path, number):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT result_json FROM managed_attempts WHERE number=?', (number,)).fetchone()[0]


def test_retention_keeps_metrics_and_retired_streams_are_never_read(tmp_path, context, repository, migrated_database):
    port, job, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    path = db_path(migrated_database)
    before = dump_rows(path)
    options = dict(artifact_roots=[port.artifact_root], before='2100-01-01T00:00:00Z', min_bytes=1)
    shown = preview_retention(path, **options)
    assert shown['items'] and all(item['eligible'] for item in shown['items'])
    apply_retention(path, **options, preview_sha256=shown['preview_sha256'], reason='Synthetic retention',
                    confirmed=True, writers_stopped=True)
    after = dump_rows(path)
    assert after['attempt_metrics'] == before['attempt_metrics'] and after['attempt_model_metrics'] \
        == before['attempt_model_metrics']
    assert not any(Path(item['source']).exists() for item in shown['items'])
    as_terminal_1(path)
    clear_metrics(path)
    report = backfill(repository.engine, artifact_roots=[port.artifact_root])
    assert report['streams'] == {'stream_retired': 3}
    assert [row['turns'] for row in metric_rows(repository)] == [None, None, None]


def test_cli_backfill_requires_an_explicit_existing_database(tmp_path, context, repository, migrated_database,
                                                             capsys):
    port, job, supervisor = flow(tmp_path, context, repository)
    supervisor.run_once()
    path = db_path(migrated_database)
    clear_metrics(path)
    assert main(['metrics-backfill', '--database', str(path), '--artifact-root', str(port.artifact_root)]) == 0
    assert json.loads(capsys.readouterr().out) == {'inserted': 3, 'already_present': 0,
                                                   'streams': {'stream_verified': 3}}
    assert main(['metrics-backfill', '--database', 'relative.sqlite3']) == 1
    assert main(['metrics-backfill', '--database', str(tmp_path / 'missing.sqlite3')]) == 1
    assert not (tmp_path / 'missing.sqlite3').exists()


def test_downgrade_without_stream_derived_rows_round_trips(tmp_path, context, repository, migrated_database):
    flow(tmp_path, context, repository)[2].run_once()
    config = migrated_database[1]
    command.downgrade(config, '0013_bootstrap')
    command.upgrade(config, 'head')
    command.check(config)
    assert backfill(repository.engine)['inserted'] == 3  # derived: the backfill rebuilds them


# --- aggregates ---------------------------------------------------------------------------------


@pytest.fixture
def world(repository, checkout):  # noqa: F811
    return World(repository, checkout)


def revise():
    data = {'task_id': 'P001-T001', 'verdict': 'REVISE', 'findings': [], 'blocking_questions': [],
            'scope_grants': [], 'next_prompt': 'Correct synthetic content',
            'executor_selection': {'model': 'synthetic-executor', 'effort': 'medium', 'reason': 'Explicit correction'}}
    return data


def test_task_quality_tests_and_stops_without_reported_usage(world):
    from test_managed_api import PLAN as TASK_PLAN, review as accept
    from test_phases import PLAN_2

    def change(text):
        def call(context, request):
            context.path('app/main.txt').write_text(text, encoding='utf-8')
            return {'result': 'synthetic'}
        return call

    def failure(context, request):
        raise RuntimeError('synthetic executor failure')

    def committed(task, plan, *responses, retry=()):
        world.script(*responses)
        job = world.repository.submit(world.context, task, 'P001', plan, VERSIONS_API, key=world.key())
        world.run()
        record = world.repository.get_run(job.run_id)
        if retry:
            assert record.history.status == 'stopped'
            world.repository.resume(job.run_id, key=world.key(), expected_version=record.version, retry_executor=True)
            world.script(*retry)
            world.run()
            record = world.repository.get_run(job.run_id)
        assert record.status == 'ACCEPTANCE_READY', (record.history.stops, world.ports.roles())
        world.repository.submit_commit(job.run_id, key=world.key(), expected_version=record.version)
        world.run()

    committed('P001-T001', TASK_PLAN, change('first\n'), revise(), change('second\n'), accept())
    committed('P001-T002', PLAN_2, failure, retry=(change('third\n'), {**accept(), 'task_id': 'P001-T002'}))
    views = MetricsViews(world.repository.engine)
    root = str(world.context.root)
    summary = views.summary({'root': root, 'phase': 'P001', 'task': None})
    assert {k: v for k, v in summary['tasks'].items() if k != 'seconds_to_commit'} == {
        'count': 2, 'reviewed': 2, 'accepted_first_time': 1, 'committed': 2, 'corrections': {'sum': 2, 'tasks': 2}}
    assert summary['tasks']['seconds_to_commit']['tasks'] == 2
    assert summary['tests'] == {'tasks_with_validation': 2, 'commands_passed': 2, 'commands_failed': 0, 'cases': None}
    assert summary['stops'] == {'distinct': 1, 'items': [{'purpose': 'task', 'stage': 'executor',
                                                          'reason': 'RuntimeError: synthetic executor failure',
                                                          'count': 1}]}
    # Fake agents: the attempts count, their tokens are absence (null), never zero.
    consumption = summary['consumption']
    assert consumption['attempts'] == 7 and consumption['accounting'] == {'terminal': 0, 'messages': 0, 'absent': 7}
    assert consumption['tokens']['total_tokens'] == {'sum': None, 'attempts': 0}
    assert consumption['attempt_wall_ms'] == {'sum': None, 'attempts': 0}
    scope = {'root': root, 'phase': None, 'task': None}
    first, = views.tasks(scope, 0, 1)['items']
    later = views.tasks(scope, 1, 1)
    second, = later['items']
    assert later['next_offset'] is None
    assert (first['task_id'], first['executions'], first['corrections'], first['first_verdict'],
            first['accepted_first_time'], first['runs']) == ('P001-T001', 2, 1, 'REVISE', False, 1)
    assert first['attempts_by_role'] == {'executor': 2, 'reviewer': 2} and first['stops'] == []
    assert first['seconds_to_accept'] is not None and first['committed_at'] is not None
    assert first['tests'] == {'commands_passed': 1, 'commands_failed': 0, 'cases': None}
    assert (second['task_id'], second['accepted_first_time'], second['corrections']) == ('P001-T002', True, 1)
    assert second['stops'] == [{'stage': 'executor', 'reason': 'RuntimeError: synthetic executor failure'}]
    with Session(world.repository.engine) as session:
        failed = session.scalar(select(AttemptMetricRow).where(AttemptMetricRow.task_id == 'P001-T002',
                                                               AttemptMetricRow.number == 1))
        assert failed.error == 'RuntimeError: synthetic executor failure' and failed.total_tokens is None
    assert views.summary({'root': root, 'phase': 'P001', 'task': 'P001-T002'})['tasks']['count'] == 1


def test_validation_evolution_counts_every_cycle_by_phase_task_and_root(world):
    """H6.2 E6: OK/KO of each validation cycle (revalidations too), by phase, task or root."""
    from my_harness.core.engine.validation import CommandResult
    from test_managed_api import PLAN as TASK_PLAN, review as accept
    from test_phases import PLAN_2

    def change(text):
        def call(context, request):
            context.path('app/main.txt').write_text(text, encoding='utf-8')
            return {'result': 'synthetic'}
        return call

    world.ports.runner.responses.extend([CommandResult(1, stderr='synthetic failure'), CommandResult(0), CommandResult(0)])
    for task, plan, responses in (('P001-T001', TASK_PLAN, (change('first\n'), revise(), change('second\n'), accept())),
                                  ('P001-T002', PLAN_2, (change('third\n'), {**accept(), 'task_id': 'P001-T002'}))):
        world.script(*responses)
        world.repository.submit(world.context, task, 'P001', plan, VERSIONS_API, key=world.key())
        world.run()
    views = MetricsViews(world.repository.engine)
    root = str(world.context.root)
    scope = {'root': root, 'phase': None, 'task': None}
    by_task = views.validations(scope, 'task', 0, 1)
    assert [(i['key'], i['passed'], i['failed']) for i in by_task['items']] == [('P001-T002', 1, 0)]
    assert views.validations(scope, 'task', 1, 1)['items'][0]['key'] == 'P001-T001'
    by_phase, = views.validations(scope, 'phase', 0, 30)['items']
    assert by_phase == {'key': 'P001', 'validations': 3, 'passed': 2, 'failed': 1, 'commands_passed': 2,
                        'commands_failed': 1, 'cases': None, 'validations_with_cases': 0}
    task, = views.validations({**scope, 'phase': 'P001', 'task': 'P001-T001'}, 'root', 0, 30)['items']
    assert (task['key'], task['validations'], task['passed'], task['failed']) == (root, 2, 1, 1)
    # The last validation of each task (summary) versus the full evolution (all validations).
    assert views.summary(scope)['tests']['commands_failed'] == 0
    assert views.validations(GLOBAL, 'phase', 1, 30) == {'dimension': 'phase', 'items': [], 'offset': 1,
                                                         'next_offset': None}
    with pytest.raises(ValueError):
        views.validations(GLOBAL, 'day', 0, 30)
    # Order by descending key in the consumption groups too (per-day series of the UI).
    assert [item['key'] for item in views.groups(scope, 'task', 0, 10, order='key')['items']] == ['P001-T002', 'P001-T001']


def test_groups_favorites_and_reported_models_paginate_without_double_counting(tmp_path, context, repository):
    flow(tmp_path / 'a', context, repository, key='a')[2].run_once()
    flow(tmp_path / 'b', context, repository, key='b', planning='deterministic')[2].run_once()
    views = MetricsViews(repository.engine)
    rows = metric_rows(repository)
    total = views.summary(GLOBAL)['consumption']['tokens']['total_tokens']
    assert total == {'sum': sum(row['total_tokens'] for row in rows), 'attempts': len(rows)}
    for dimension in ('role', 'provider', 'requested_model', 'day', 'task'):
        items, offset = [], 0
        while offset is not None:
            page = views.groups(GLOBAL, dimension, offset, 1)
            items += page['items']
            offset = page['next_offset']
        assert sum(item['tokens']['total_tokens']['sum'] for item in items) == total['sum']
        assert sum(item['attempts'] for item in items) == len(rows)
    by_role = views.groups(GLOBAL, 'role', 0, 10, order='tokens')['items']
    assert [item['key'] for item in by_role] == ['reviewer', 'executor', 'planner']  # 2100, 1552, 1050
    favorites = views.groups(GLOBAL, 'requested_model', 0, 10, role='executor')['items']
    assert [(item['key'], item['attempts']) for item in favorites] == [('synthetic-executor', 2)]
    models = views.groups(GLOBAL, 'reported_model', 0, 1)
    assert models['items'][0]['key'] == 'claude-synthetic-a' and models['next_offset'] == 1
    assert models['items'][0]['tokens']['output_tokens'] == {'sum': 60, 'attempts': 2}
    with pytest.raises(ValueError):
        views.groups(GLOBAL, 'quota', 0, 10)


def test_http_metrics_are_read_only_paginated_and_scoped(tmp_path, context, repository):
    flow(tmp_path, context, repository)[2].run_once()
    configuration = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),))
    with client(str(repository.engine.url), tmp_path, configuration) as http:
        summary = http.get('/api/managed/metrics/summary', params={'project_id': 'synthetic'})
        assert summary.status_code == 200, summary.text
        assert summary.json()['consumption']['tokens']['total_tokens'] == {'sum': 2876, 'attempts': 3}
        assert http.get('/api/managed/metrics/summary').json()['consumption'] == summary.json()['consumption']
        page = http.get('/api/managed/metrics/attempts', params={'project_id': 'synthetic', 'limit': 2}).json()
        assert [item['role'] for item in page['items']] == ['planner', 'executor'] and page['next_offset'] == 2
        assert page['items'][1]['models'][0]['model'] == 'claude-synthetic-a'
        assert page['items'][1]['provenance']['turns'] == 'reported'
        groups = http.get('/api/managed/metrics/groups', params={'dimension': 'provider', 'order': 'tokens'}).json()
        assert [(item['key'], item['attempts']) for item in groups['items']] == [('codex', 2), ('claude', 1)]
        models = http.get('/api/managed/metrics/models', params={'role': 'executor'}).json()
        assert [item['key'] for item in models['items']] == ['claude-synthetic-a', 'claude-synthetic-b']
        tasks = http.get('/api/managed/metrics/tasks', params={'project_id': 'synthetic', 'phase': 'P001'}).json()
        assert tasks['items'][0]['agents'][0] == {'role': 'executor', 'provider': 'claude',
                                                  'requested_model': 'synthetic-executor',
                                                  'requested_effort': 'medium', 'attempts': 1}
        assert http.get('/api/managed/metrics/summary', params={'phase': 'P001'}).status_code == 422
        assert http.get('/api/managed/metrics/summary', params={'project_id': 'other'}).status_code == 404
        assert http.get('/api/managed/metrics/groups', params={'dimension': 'quota'}).status_code == 422
        assert http.post('/api/managed/metrics/summary').status_code == 405
        days = http.get('/api/managed/metrics/groups', params={'dimension': 'day', 'order': 'key', 'project_id': 'synthetic'})
        assert days.status_code == 200 and days.json()['order'] == 'key'
        evolution = http.get('/api/managed/metrics/validations', params={'project_id': 'synthetic', 'dimension': 'phase'})
        assert evolution.status_code == 200, evolution.text
        assert [(item['key'], item['validations']) for item in evolution.json()['items']] == [('P001', 1)]
        assert http.get('/api/managed/metrics/validations', params={'dimension': 'day'}).status_code == 422
        assert http.get('/api/managed/metrics/validations', params={'phase': 'P001'}).status_code == 422


# --- phase SUMMARY -----------------------------------------------------------------------------


SUMMARY = {'phase': {'code': 'P001', 'status': 'CLOSED', 'objective': 'o', 'exit_criteria': ['c'], 'tag': 'p001',
                     'definition_number': 1, 'title': 'Fase'},
           'tasks': [{'task_id': 'P001-T001', 'status': 'COMMITTED', 'verdict': 'ACCEPT',
                      'attempts': {'executor': 1}, 'revisions': 0, 'commit': 'abc', 'tests': None}],
           'extra_tasks': [], 'questions': [], 'definitions': []}


def brief(total, attempts, reported=None, derived=None, cost=None):
    measure = lambda value, n: {'sum': value, 'attempts': n if value is not None else 0}
    return {'attempts': attempts, 'accounting': {'terminal': attempts, 'messages': 0, 'absent': 0},
            **{name: measure(total, attempts) for name in ('uncached_input_tokens', 'cache_read_tokens',
                                                           'cache_write_tokens', 'output_tokens', 'total_tokens')},
            'turns_reported': measure(reported, 1), 'turns_derived': measure(derived, 1),
            'cost_usd': {'sum': cost, 'attempts': 1 if cost is not None else 0, 'basis': 'api_equivalent_reported'}}


def test_summary_render_adds_tokens_and_turns_only_for_new_snapshots():
    old = render_summary(SUMMARY)
    assert '## Consumo' not in old and '| Tarea | Estado | Revisión | Intentos por rol | Correcciones | Commit | Tests |\n' in old
    consumption = {'total': brief(776, 2, 2, 3, 0.0125), 'by_role': {'executor': brief(776, 1, 2, None, 0.0125),
                                                                    'reviewer': brief(None, 1)},
                   'by_task': {'P001-T001': brief(776, 2, 2, 3)}}
    new = render_summary({**SUMMARY, 'consumption': consumption})
    assert '| Tests | Tokens | Turnos |' in new
    assert '| 776 | 2 reportados · 3 derivados |' in new
    assert '| reviewer | 1 | — | — | — | — | — | — | — |' in new  # absence, not zero
    assert '| total | 2 | 776 | 776 | 776 | 776 | 776 | 2 reportados · 3 derivados | 0.0125 |' in new
    assert render_summary({**SUMMARY, 'consumption': consumption}) == new


def closed_v2(repository, tmp_path):
    from test_documents import V2World, v2_files
    from test_managed_api import git, make_context
    root = tmp_path / 'v2'
    for path, text in v2_files().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'v2 baseline')
    v2 = V2World(repository, replace(make_context(root), documents='v2'))
    pid = v2.create_v2()
    v2.accept()
    v2.close_ready(pid)
    return v2, pid


def test_phase_transition_summary_includes_consumption(repository, tmp_path, _legacy_close):  # noqa: F811
    from test_documents import queue_transition
    v2, pid = closed_v2(repository, tmp_path)
    with closing(sqlite3.connect(repository.engine.url.database)) as db:
        # Reported usage injected into the executor's row; fake agents report no usage.
        db.execute("UPDATE attempt_metrics SET total_tokens=500, uncached_input_tokens=10, output_tokens=90, "
                   "cache_read_tokens=300, cache_write_tokens=100, turns=4, provider='claude', accounting='terminal', "
                   "provenance=json_set(provenance, '$.turns', 'reported') WHERE role='executor'")
        db.commit()
    queue_transition(v2, pid)
    v2.run()
    summary = (v2.context.root / 'docs/archive/phase-001/SUMMARY.md').read_text()
    assert '| P001-T001 | COMMITTED | ACCEPT | executor 1, reviewer 1 |' in summary
    assert '| 500 (1/2 intentos) | 4 reportados |' in summary
    assert '| phase | 1 | — | — | — | — | — | — | — |' in summary
    assert '| total | 3 | 10 (1/3) | 300 (1/3) | 100 (1/3) | 90 (1/3) | 500 (1/3) | 4 reportados | — |' in summary


def test_transition_reviewed_before_metrics_runs_exactly_as_reviewed(repository, tmp_path, _legacy_close):  # noqa: F811
    from my_harness.storage.models import PhaseOperationRow
    from test_documents import queue_transition
    v2, pid = closed_v2(repository, tmp_path)
    job = queue_transition(v2, pid)
    with Session(repository.engine) as session, session.begin():
        op = session.scalar(select(PhaseOperationRow).where(PhaseOperationRow.run_id == job.run_id))
        stored = json.loads(json.dumps(op.request))
        stored['preview']['snapshot']['summary'].pop('consumption')  # shape frozen before 0014
        op.request = stored
    v2.run()
    assert repository.get_run(job.run_id).status == 'COMMITTED'
    assert (v2.context.root / 'docs/archive/phase-001/SUMMARY.md').exists()
