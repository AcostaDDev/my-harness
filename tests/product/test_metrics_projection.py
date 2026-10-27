"""P010-T011 (D142): metrics and export preview over `run-projection-1`, without decoding histories.

Temporary SQLite, synthetic histories of formats 1–8 and a large scope; fake engine and agents. The views are
compared with a copy of the previous implementation (base 389a3b1), which decoded every history.
"""

from contextlib import closing
from dataclasses import asdict
import json
import sqlite3
import time

from alembic import command
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine import serialization
from my_harness.core.engine.acceptance import AcceptanceDecision
from my_harness.core.engine.context import Command
from my_harness.core.engine.contracts import AgentRequest, AgentResult, Attempt, RunHistory, Selection, freeze
from my_harness.core.engine.documents import validation_counts
from my_harness.core.engine.evidence import ContentEvidence, PathPolicyResult
from my_harness.core.engine.junit import JUnitReport, TestCase as JUnitCase
from my_harness.core.engine.review import ReviewCycle
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.core.engine.validation import CommandResult, ValidationEntry, ValidationReport
from my_harness.storage import document_export, documents, run_projection
from my_harness.storage.database import make_engine
from my_harness.storage.document_export import DocumentExportRepository
from my_harness.storage.metrics import STOP_LIMIT, MetricsViews, _scope
from my_harness.storage.models import (
    ManagedCommitRow as Commit, ManagedRunRow as Run, AttemptMetricRow as Metric,
)
from test_backup import db_path
from test_documents import v2, v2checkout  # noqa: F401  (fixtures)
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import VERSIONS
from test_phases import checkout, world  # noqa: F401  (fixtures)
from test_run_projection import FEATURES, TASK, synthetic


# --- previous implementation (base 389a3b1), only as a reference for results --------------------------------

class LegacyMetricsViews(MetricsViews):
    """`_task`, `validations` and the stops of `summary` as they decoded the histories."""

    def _task(self, session, root, phase, task) -> dict:
        from my_harness.storage.metrics import _consumption, _seconds, _sums
        runs = session.scalars(select(Run).where(Run.root == root, Run.phase_id == phase, Run.task_id == task,
                                                 Run.purpose == 'task').order_by(Run.created_at, Run.id)).all()
        ids = [run.id for run in runs]
        metrics = session.scalars(select(Metric).where(Metric.run_id.in_(ids))
                                  .order_by(Metric.started_at, Metric.number)).all()
        consumption = _consumption(session.execute(select(*_sums()).where(Metric.run_id.in_(ids))).one())
        agents, by_role = {}, {}
        for row in metrics:
            key = (row.role, row.provider, row.requested_model, row.requested_effort)
            agents[key] = agents.get(key, 0) + 1
            by_role[row.role] = by_role.get(row.role, 0) + 1
        histories = [load_history(run.history_json) for run in runs]
        executions = sum(1 for history in histories for a in history.attempts if a.request.role == 'executor')
        verdicts = [cycle.verdict for history in histories for cycle in history.cycles if cycle.verdict]
        accepted = [row.finished_at for row in metrics if row.role == 'reviewer' and row.verdict == 'ACCEPT']
        committed = session.scalar(select(Commit.finished_at).where(Commit.run_id.in_(ids), Commit.status == 'COMMITTED')
                                   .order_by(Commit.finished_at).limit(1))
        latest = next((h.cycles[-1] for h in reversed(histories) if h.cycles), None)
        started = runs[0].created_at if runs else None
        return {'root': root, 'phase_code': phase, 'task_id': task, 'runs': len(runs),
                'status': runs[-1].status if runs else None,
                'agents': [{'role': r, 'provider': p, 'requested_model': m, 'requested_effort': e, 'attempts': n}
                           for (r, p, m, e), n in sorted(agents.items(), key=lambda kv: tuple(str(v) for v in kv[0]))],
                'attempts_by_role': dict(sorted(by_role.items())),
                'executions': executions, 'corrections': max(0, executions - 1) if executions else None,
                'first_verdict': verdicts[0] if verdicts else None,
                'accepted_first_time': (verdicts[0] == 'ACCEPT') if verdicts else None,
                'started_at': started, 'accepted_at': accepted[-1] if accepted else None, 'committed_at': committed,
                'seconds_to_accept': _seconds(started, accepted[-1] if accepted else None),
                'seconds_to_commit': _seconds(started, committed),
                'tests': validation_counts(latest.validation) if latest is not None else None,
                'stops': [{'stage': stop.stage, 'reason': stop.reason} for h in histories for stop in h.stops],
                'consumption': consumption}

    def validations(self, scope, dimension, offset, limit):
        groups = {}
        with Session(self.engine) as session:
            for run in session.scalars(_scope(select(Run).where(Run.purpose == 'task'), Run, scope)):
                key = {'phase': run.phase_id, 'task': run.task_id, 'root': run.root}[dimension]
                for cycle in load_history(run.history_json).cycles:
                    if cycle.validation is None:
                        continue
                    group = groups.setdefault(key, {'key': key, 'validations': 0, 'passed': 0, 'failed': 0,
                                                    'commands_passed': 0, 'commands_failed': 0, 'cases': None,
                                                    'validations_with_cases': 0})
                    counts = validation_counts(cycle.validation)
                    group['validations'] += 1
                    group['passed' if cycle.validation.all_passed else 'failed'] += 1
                    group['commands_passed'] += counts['commands_passed']
                    group['commands_failed'] += counts['commands_failed']
                    if counts['cases'] is not None:
                        group['validations_with_cases'] += 1
                        group['cases'] = group['cases'] or {'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0}
                        for name, value in counts['cases'].items():
                            group['cases'][name] += value
        ordered = sorted(groups.values(), key=lambda group: group['key'], reverse=True)
        return {'dimension': dimension, 'items': ordered[offset:offset + limit], 'offset': offset,
                'next_offset': offset + limit if len(ordered) > offset + limit else None}

    def summary(self, scope) -> dict:
        result = super().summary(scope)  # tasks by the previous `_task`; stops recomputed below
        stops = {}
        with Session(self.engine) as session:
            for run in session.scalars(_scope(select(Run), Run, scope)):
                for stop in load_history(run.history_json).stops:
                    key = (run.purpose, stop.stage, stop.reason)
                    stops[key] = stops.get(key, 0) + 1
        ranked = sorted(stops.items(), key=lambda kv: (-kv[1], kv[0]))
        return {**result, 'stops': {'distinct': len(ranked), 'items': [
            {'purpose': purpose, 'stage': stage, 'reason': reason, 'count': n}
            for (purpose, stage, reason), n in ranked[:STOP_LIMIT]]}}


# --- synthetic histories -------------------------------------------------------------------------------------

def edge(run_id):
    """Edge validations: non-integer codes, live capture, timeout, partial reports, no cases or missing ones,
    freshness without changes and case results outside the catalog; executors with and without summary."""
    selection = Selection('model-b', 'low', 'motivo')
    capture = lambda state: freeze({'group_state': state, 'streams': {  # noqa: E731
        'stdout': {'complete': True}, 'stderr': {'complete': True}}})

    def report(status, freshness, results):
        return JUnitReport('.local/r.xml', 'Declared', status, (), None, None, None, freshness,
                           tuple(JUnitCase(f'c{i}', None, f'c{i}', 'K', ('S',), value, None, None, None, None)
                                 for i, value in enumerate(results)))
    entries = (
        ValidationEntry(Command(('npm', 'test')), 'npm test', CommandResult(0, capture_json=capture('alive')), 'a',
                        (report('partial', 'unchanged', ('failed', 'passed', 'skipped')),
                         report('missing', 'created', ('failed',)),
                         report('complete', 'changed', ('error', 'flaky', 'passed')))),
        ValidationEntry(Command(('npm', 'lint')), 'npm lint', CommandResult(0, error=''), 'b',
                        (report('complete', 'created', ()),)),
        ValidationEntry(Command(('npm', 'x')), 'npm x', CommandResult(0, timed_out=True)),
        ValidationEntry(Command(('npm', 'y')), 'npm y', CommandResult(0, capture_json=capture('dead'))),
        ValidationEntry(Command(('npm', 'z')), 'npm z', CommandResult(0, capture_json='{no json')),
        ValidationEntry(Command(('npm', 'b')), 'npm b', CommandResult(False)),  # JSON false is not code 0
        ValidationEntry(Command(('npm', 'f')), 'npm f', CommandResult(0.0)),
    )
    clean = (ValidationEntry(Command(('npm', 'test')), 'npm test', CommandResult(0), 'c',
                             (report('complete', 'unchanged', ('failed', 'passed')),)),)
    cycles, attempts = [], []
    for n, (items, verdict) in enumerate(((entries, None), (clean, 'ACCEPT'), ((), 'REVISE'))):
        evidence = ContentEvidence('base', f'fp-{n}', ('app/a.txt',), f'+{n}\n')
        cycles.append(ReviewCycle(n, evidence, PathPolicyResult(()), ValidationReport(evidence, items, run_id, None),
                                  freeze({'summary': 'sin veredicto'}) if verdict is None else freeze({'verdict': verdict}),
                                  None))
    for n, (role, payload) in enumerate((('planner', None), ('executor', '{"result":"hecho ñ"}'),
                                         ('reviewer', '{"verdict":"REVISE"}'), ('executor', '{"result": 7}'),
                                         ('executor', None), ('reviewer', '{"verdict":"ACCEPT"}'))):
        attempts.append(Attempt(AgentRequest(f'{run_id}-{n}', role, selection, 'p', TASK, '{}'),
                                AgentResult(payload, True, 0, 'raw')))
    history = RunHistory(run_id, '{}', TASK, tuple(attempts), tuple(cycles), (), 'stopped', None, (),
                         AcceptanceDecision(True, (), cycles[-1].evidence))
    text = dump_history(history)
    assert load_history(text) == history
    return text


def insert(db, run_id, text, *, root='/synthetic', phase='P1', task='T1', purpose='task', created_at, pending=False):
    db.execute("INSERT INTO managed_runs(id,root,task_id,phase_id,context_json,versions_json,history_json,status,stage,"
               "revisions,revision_limit,version,created_at,updated_at,purpose) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (run_id, root, task, phase, '{}', freeze({'engine': 'x'}), text, 'STOPPED', 'stop', 0, 3, 1,
                created_at, created_at, purpose))
    # Each history attempt has its row with the same request and result (`_history` requires it); an attempt
    # in progress has a row without result and is not in the history yet.
    history = load_history(text)
    for number, attempt in enumerate(history.attempts, start=1):
        db.execute('INSERT INTO managed_attempts(id,run_id,number,request_json,versions_json,status,result_json,'
                   'started_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   (attempt.request.id, run_id, number, freeze(asdict(attempt.request)), '{}', 'COMPLETED',
                    freeze(asdict(attempt.result)), created_at, created_at))
    if pending:
        request = AgentRequest(f'{run_id}-pending', 'executor', Selection('m', 'high', 'r'), 'p', TASK, '{}')
        db.execute('INSERT INTO managed_attempts(id,run_id,number,request_json,versions_json,status,started_at) '
                   'VALUES(?,?,?,?,?,?,?)', (request.id, run_id, len(history.attempts) + 1,
                                              freeze(asdict(request)), '{}', 'ACTIVE', created_at))


def corpus():
    """Runs of several roots, phases, tasks and purposes; tasks with several runs and a last run without cycles."""
    runs = [(f'run-f{fmt}', synthetic(f'run-f{fmt}', fmt, status='reviewing' if fmt == 6 else 'stopped'),
             {'task': 'T1' if fmt <= 4 else 'T2'}) for fmt in FEATURES]
    runs += [('run-edge', edge('run-edge'), {'phase': 'P2', 'task': 'T3', 'pending': True}),
             ('run-empty', dump_history(RunHistory('run-empty', '{}')), {'task': 'T2'}),
             ('run-other', synthetic('run-other', 8, cycles=2, stops=3), {'root': '/other', 'phase': 'P9', 'task': 'T1'}),
             ('run-chat', synthetic('run-chat', 2, cycles=1, stops=4), {'purpose': 'chat', 'task': 'CHAT'})]
    return [(run_id, text, {**options, 'created_at': f'2026-10-22T00:00:{n:02d}'})
            for n, (run_id, text, options) in enumerate(runs)]


class Probe:
    """Emitted SQL and history decodings during a view read."""

    def __init__(self, engine, monkeypatch):
        from sqlalchemy import event
        self.statements, self.decoded = [], 0
        original = serialization.load_history

        def counted(snapshot):
            self.decoded += 1
            return original(snapshot)
        for module in (serialization, run_projection, documents, document_export):
            monkeypatch.setattr(module, 'load_history', counted)
        event.listen(engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, params, context, many: self.statements.append(statement))

    def reset(self):
        self.statements.clear()
        self.decoded = 0

    def clean(self):
        return self.decoded == 0 and not any('history_json' in statement for statement in self.statements)


SCOPES = [{'root': None, 'phase': None, 'task': None}, {'root': '/synthetic', 'phase': None, 'task': None},
          {'root': '/synthetic', 'phase': 'P1', 'task': None}, {'root': '/synthetic', 'phase': 'P1', 'task': 'T2'},
          {'root': '/synthetic', 'phase': 'P2', 'task': 'T3'}, {'root': '/nada', 'phase': None, 'task': None}]


def pages(read, limit):
    offset, items = 0, []
    while offset is not None:
        page = read(offset, limit)
        items += page['items']
        offset = page['next_offset']
    return items


def assert_metrics_equivalent(engine, probe):
    views, legacy = MetricsViews(engine), LegacyMetricsViews(engine)
    for scope in SCOPES:
        probe.reset()
        assert views.summary(scope) == legacy.summary(scope), scope
        for limit in (1, 2, 50):
            probe.reset()
            current = pages(lambda offset, size: views.tasks(scope, offset, size), limit)
            assert probe.clean()
            assert current == pages(lambda offset, size: legacy.tasks(scope, offset, size), limit)
            for dimension in ('phase', 'task', 'root'):
                probe.reset()
                current = pages(lambda offset, size: views.validations(scope, dimension, offset, size), limit)
                assert probe.clean()
                assert current == pages(lambda offset, size: legacy.validations(scope, dimension, offset, size), limit)
    probe.reset()
    views.summary(SCOPES[0])
    assert probe.clean()


def test_metrics_and_preview_facts_match_the_previous_implementation_on_formats_1_to_8(migrated_database, monkeypatch):
    url, config = migrated_database
    command.downgrade(config, '0022_project_preparation')
    runs = corpus()
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        for run_id, text, options in runs:
            insert(db, run_id, text, **options)
        db.commit()
    command.upgrade(config, 'head')  # migration 0023 backfills the projection of the previous runs
    engine = make_engine(url)
    probe = Probe(engine, monkeypatch)
    assert_metrics_equivalent(engine, probe)
    # Edge cases accredited in the reference: the result is not trivial.
    edge_task = MetricsViews(engine).tasks(SCOPES[4], 0, 10)['items'][0]
    assert edge_task['first_verdict'] == 'ACCEPT' and edge_task['executions'] == 3
    assert edge_task['tests'] == {'commands_passed': 0, 'commands_failed': 0, 'cases': None}
    edge_validations = MetricsViews(engine).validations(SCOPES[4], 'task', 0, 10)['items'][0]
    assert edge_validations == {'key': 'T3', 'validations': 3, 'passed': 2, 'failed': 1, 'commands_passed': 3,
                                'commands_failed': 5, 'cases': {'passed': 3, 'failed': 2, 'error': 2, 'skipped': 1},
                                'validations_with_cases': 2}
    # Export preview: same facts per task and same acceptance as from the history.
    with Session(engine) as session:
        for run_id, text, _ in runs:
            probe.reset()
            projected = documents._projected_facts(session, run_id)
            accepted = document_export._acceptance(session, run_id, True)
            assert probe.clean(), run_id
            assert projected == documents._history_facts(session, run_id), run_id
            assert accepted == document_export._acceptance(session, run_id, False), run_id
        attempts, summary, verdict, tests = documents._projected_facts(session, 'run-edge')
        assert attempts == {'planner': 1, 'executor': 3, 'reviewer': 2} and list(attempts) == [
            'planner', 'executor', 'reviewer']
        assert summary is None and verdict == 'REVISE' and tests == validation_counts(
            load_history(edge('run-edge')).cycles[-1].validation)
    engine.dispose()


def test_views_refuse_a_run_without_projection(migrated_database):
    url, _ = migrated_database
    engine = make_engine(url)
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        insert(db, 'run-x', synthetic('run-x', 8), created_at='2026-10-22T00:00:00')
        db.commit()
    with pytest.raises(RuntimeError, match='without projection'):
        MetricsViews(engine).summary(SCOPES[0])
    with pytest.raises(RuntimeError, match='without projection'):
        MetricsViews(engine).validations(SCOPES[0], 'task', 0, 10)
    with Session(engine) as session, pytest.raises(RuntimeError, match='without projection'):
        documents._projected_facts(session, 'run-x')
    engine.dispose()


def test_large_scope_is_read_without_histories_and_matches(migrated_database, monkeypatch):
    url, _ = migrated_database
    body = ''.join(f'+línea {n:06d} con ñ y € {"x" * 40}\n' for n in range(64_000))  # ~4 MiB
    large = synthetic('run-large', 8, cycles=40, cases=2000, diff=body, stops=30)
    runs = [('run-large', large, {'task': 'T00'})]
    runs += [(f'run-{n:02d}', synthetic(f'run-{n:02d}', 8, cycles=4, cases=200, stops=2),
              {'task': f'T{n % 30:02d}', 'phase': f'P{n % 3}'}) for n in range(60)]
    engine = make_engine(url)
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        for n, (run_id, text, options) in enumerate(runs):
            insert(db, run_id, text, created_at=f'2026-10-22T00:{n // 60:02d}:{n % 60:02d}', **options)
        db.commit()
    with Session(engine) as session, session.begin():
        for run_id, text, _ in runs:
            run_projection.create(session, run_id, text, load_history(text))
    total = sum(len(text) for _, text, _ in runs)
    assert total > 30 * 1024 * 1024
    views, legacy = MetricsViews(engine), LegacyMetricsViews(engine)
    probe = Probe(engine, monkeypatch)
    measures = {}
    for name, read in (('summary', lambda v: v.summary(SCOPES[0])), ('tasks', lambda v: v.tasks(SCOPES[0], 0, 20)),
                       ('validations', lambda v: v.validations(SCOPES[0], 'phase', 0, 20))):
        probe.reset()
        started = time.perf_counter()
        current = read(views)
        elapsed = time.perf_counter() - started
        assert probe.clean(), name
        started = time.perf_counter()
        assert current == read(legacy), name
        measures[name] = (elapsed, time.perf_counter() - started)
    with Session(engine) as session:
        probe.reset()
        started = time.perf_counter()
        facts = documents._projected_facts(session, 'run-large')
        elapsed = time.perf_counter() - started
        assert probe.clean()
        started = time.perf_counter()
        assert facts == documents._history_facts(session, 'run-large')
        measures['preview_task'] = (elapsed, time.perf_counter() - started)
    print('; '.join(f'{name} {new * 1000:.1f} ms (anterior {old * 1000:.1f} ms)' for name, (new, old) in measures.items())
          + f'; historiales {total / 1024 / 1024:.1f} MiB')
    engine.dispose()


# --- export preview with the real engine ----------------------------------------------------------------------

def test_d036_export_preview_reads_the_projection_and_the_confirmed_export_commits(world, monkeypatch):  # noqa: F811
    from test_document_export import queue, shown
    world.accept_task()
    pid = world.create()
    probe = Probe(world.repository.engine, monkeypatch)
    view = shown(world, pid)
    assert probe.clean() and probe.statements
    assert view['snapshot']['tasks']['P001-T001']['acceptance'] is True
    job = queue(world, pid, view)  # the submission recomputes from the history and requires the same snapshot
    assert probe.decoded > 0
    world.run()
    assert world.repository.get_run(job.run_id).status == 'COMMITTED'


def test_v2_export_preview_reads_the_projection_and_matches_the_history(v2, monkeypatch):  # noqa: F811
    v2.accept()
    pid = v2.create_v2()
    exporter = DocumentExportRepository(v2.repository)
    writer = v2.ports.writer(v2.context, VERSIONS)
    probe = Probe(v2.repository.engine, monkeypatch)
    view = exporter.preview(v2.context, pid, writer)
    assert probe.clean() and view['snapshot']['layout'] == 'v2'
    task = view['snapshot']['state']['tasks'][0]
    assert task['summary'].startswith('Implementado P001-T001') and task['attempts'] == {'executor': 1, 'reviewer': 1}
    assert task['verdict'] == 'ACCEPT' and task['tests'] is not None
    with Session(v2.repository.engine) as session:
        phase = session.get(documents.Phase, pid)
        assert view['snapshot'] == document_export.snapshot(session, phase, v2.context)  # from the history
    job = exporter.submit(v2.context, pid, view['expected_version'], key='v2-export', versions=VERSIONS,
                          preview_sha256=view['preview_sha256'], reason='Export v2 blocks', confirmed=True, git=writer)
    v2.run()
    assert v2.repository.get_run(job.run_id).status == 'COMMITTED'


def test_export_preview_refuses_a_projection_that_differs_from_the_history(v2):  # noqa: F811
    from my_harness.storage.managed import Conflict
    run_id = v2.accept()
    pid = v2.create_v2()
    exporter = DocumentExportRepository(v2.repository)
    writer = v2.ports.writer(v2.context, VERSIONS)
    with Session(v2.repository.engine) as session, session.begin():
        session.execute(run_projection.TABLES['run_projection_cycles'][0].update()
                        .where(run_projection.TABLES['run_projection_cycles'][0].c.run_id == run_id)
                        .values(verdict='REVISE'))
    view = exporter.preview(v2.context, pid, writer)
    assert view['snapshot']['state']['tasks'][0]['verdict'] == 'REVISE'
    # The preview is not authority: the confirmed submission checks it against the history and enqueues nothing.
    with pytest.raises(Conflict, match='authority changed'):
        exporter.submit(v2.context, pid, view['expected_version'], key='v2-export', versions=VERSIONS,
                        preview_sha256=view['preview_sha256'], reason='Export v2 blocks', confirmed=True, git=writer)
