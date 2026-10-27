"""P010-T003 (D142): run views over the `run-projection-1` projection, without decoding histories.

Temporary SQLite, synthetic histories of formats 1–8 and a large history; fake engine and agents. The
views are compared with a copy of the previous implementation, which decoded the whole history.
"""

import base64
from contextlib import closing
from dataclasses import asdict, replace
import hashlib
import json
import sqlite3
import time

from alembic import command
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from my_harness.adapters.engine_fake import ScriptedAgentAdapter
from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine import serialization
from my_harness.core.engine.acceptance import AcceptanceDecision
from my_harness.core.engine.context import Command
from my_harness.core.engine.contracts import (
    AgentRequest, AgentResult, Attempt, OperationalStop, RunHistory, Selection, freeze,
)
from my_harness.core.engine.evidence import ContentEvidence, PathPolicyResult
from my_harness.core.engine.junit import JUnitReport, TestCase as JUnitCase
from my_harness.core.engine.review import ReviewCycle
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.core.engine.validation import CommandResult, ValidationEntry, ValidationReport, validation_payload
from my_harness.services.managed import LocalSupervisor
from my_harness.storage import managed_views, run_projection
from my_harness.storage.backup import BackupError, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.managed_views import SQLiteManagedViews, diff_page
from my_harness.storage.models import ManagedRunRow as Run
from test_backup import backup, db_path, reseal_database
from test_engine import PHASE_ID, PLAN, TASK_ID, edit, review
from test_git import IDENTITY, VERSIONS, make_context, repo as git_repo  # noqa: F401  (fixture)
from test_junit import ReportRunner, configured, simple_xml


# --- previous implementation (base bfbd006), only as a reference for results --------------------------------

def legacy_history(history_json):
    history = load_history(history_json)
    acceptance = history.acceptance
    return {
        'status': history.status, 'task': run_projection.loads(history.task_json),
        'stop': {'stage': history.stop.stage, 'reason': history.stop.reason} if history.stop else None,
        'stops': [{'stage': stop.stage, 'reason': stop.reason} for stop in history.stops],
        'attempts': len(history.attempts),
        'cycles': [{'number': cycle.number, 'verdict': cycle.verdict, 'fingerprint': cycle.evidence.fingerprint,
                    'changed_paths': list(cycle.evidence.changed_paths),
                    **run_projection.diff_summary(cycle.evidence.diff),
                    'provenance': run_projection.loads(cycle.evidence.provenance_json),
                    'validation': {**validation_payload(cycle.validation, include_cases=False),
                                   'evidence': run_projection.evidence_view(
                                       validation_payload(cycle.validation, include_cases=False)['evidence'])},
                    'review': run_projection.loads(cycle.review_json),
                    'formatting': run_projection.loads(cycle.formatting_json)}
                   for cycle in history.cycles],
        'acceptance': None if acceptance is None else {
            'eligible': acceptance.eligible, 'reasons': list(acceptance.reasons),
            'base_revision': acceptance.evidence.base_revision, 'fingerprint': acceptance.evidence.fingerprint,
            'changed_paths': list(acceptance.evidence.changed_paths)},
    }


def legacy_actions(history_json, *, revision_limit, purpose='task', status='STOPPED'):
    """Previous detail actions without job, lock or commit (the other data does not depend on the history)."""
    history, actions = load_history(history_json), []
    if history.task_json is not None and history.status in ('stopped', 'blocked', 'revision_limit'):
        actions.append('revalidate')
        executions = sum(a.request.role == 'executor' for a in history.attempts)
        if json.loads(history.task_json)['allowed_paths'] and (not executions or history.revisions < revision_limit):
            actions.append('retry_executor')
    if history.acceptance and history.acceptance.eligible:
        actions.append('commit')
    if purpose == 'task' and status in ('STOPPED', 'BLOCKED', 'REVISION_LIMIT', 'INTERRUPTED'):
        actions.append('permissions')
    return actions


def legacy_cases(history_json, cycle, entry, report, offset, limit):
    validation = load_history(history_json).cycles[cycle].validation
    command_entry = validation.entries[entry]
    imported = command_entry.reports[report]
    summary = validation_payload(validation, include_cases=False)['entries'][entry]['reports'][report]
    return {'report': summary, 'run_id': validation.run_id, 'source_attempt_id': validation.source_attempt_id,
            'command_id': command_entry.command_id,
            'evidence': run_projection.evidence_view(asdict(validation.evidence)),
            'items': [asdict(case) for case in imported.cases[offset:offset + limit]], 'offset': offset,
            'next_offset': offset + limit if offset + limit < len(imported.cases) else None}


def legacy_diff(history_json, cycle, offset, limit):
    diff = load_history(history_json).cycles[cycle].evidence.diff
    summary = run_projection.diff_summary(diff)
    return {'sha256': summary['diff_sha256'], 'size_bytes': summary['diff_bytes'], **diff_page(diff, offset, limit)}


def plain(value):
    return json.loads(json.dumps(value))


# --- synthetic histories -------------------------------------------------------------------------------------

FEATURES = {1: set(), 2: {'cli'}, 3: {'cli', 'provenance'}, 4: {'prompts'}, 5: {'prompts', 'permissions'},
            6: {'reports'}, 7: {'reports', 'capture'}, 8: {'formatting', 'reports'}}
TASK = freeze({'task_id': 'T1', 'phase_id': 'P1', 'allowed_paths': ['app/**'], 'forbidden_paths': [],
               'title': 'Sintética', 'additional_notes': 'nota'})


def junit(n, cases):
    xml = f'<testsuite name="S" tests="{cases}"/>'.encode()
    return JUnitReport('.local/junit.xml', 'Declared synthetic selection', 'complete', ('aviso',),
                       hashlib.sha256(xml).hexdigest(), len(xml), base64.b64encode(xml).decode(), 'created',
                       tuple(JUnitCase(f'id-{n}-{i}', None, f'case {i} ñ', 'Clase', ('S', None),
                                      'failed' if i % 7 == 0 else 'passed', 0.25 * i, None, None, None)
                             for i in range(cases)))


def synthetic(run_id, fmt, *, cycles=3, cases=5, diff=None, stops=2, status='stopped', eligible=False):
    features = FEATURES[fmt]
    selection = Selection('model-a', 'high', 'motivo')
    attempts, items = [], []
    for n in range(cycles):
        for role in ('executor', 'reviewer'):
            request = AgentRequest(f'{run_id}-{n}-{role}', role, selection, f'prompt {n}', TASK, '{}',
                                   prompt_snapshot_json=freeze({'n': n}) if 'prompts' in features else None,
                                   permission_snapshot_json=freeze({'grants': []}) if 'permissions' in features else None)
            attempts.append(Attempt(request, AgentResult('{"ok":true}', True, 0, 'raw',
                                                         status='complete' if 'cli' in features else None)))
        evidence = ContentEvidence('base', f'fp-{n}', ('app/a.txt', 'app/ñ.txt'),
                                   diff if diff is not None and n == cycles - 1 else f'+línea {n} ñ €\n-old\n',
                                   freeze({'tree': f't{n}'}) if 'provenance' in features else None)
        reports = (junit(n, cases), junit(n + 100, 0)) if 'reports' in features else ()
        result = CommandResult(1 if n == 0 else 0, f'out {n}', 'err', 1.5,
                               capture_json=freeze({'group_state': 'dead', 'streams': {
                                   'stdout': {'complete': True}, 'stderr': {'complete': True}}})
                               if 'capture' in features else None)
        entries = (ValidationEntry(Command(('npm', 'test')), 'npm test', result, 'cmd' if reports else None, reports),
                   ValidationEntry(None, 'rm -rf x', CommandResult(None, error='outside policy')))
        validation = ValidationReport(evidence, entries, run_id if reports else None,
                                      f'{run_id}-{n}-executor' if reports else None)
        verdict = 'ACCEPT' if n == cycles - 1 else 'REVISE'
        items.append(ReviewCycle(n, evidence, PathPolicyResult(()), validation,
                                 None if n == cycles - 1 and status == 'reviewing' else freeze({'verdict': verdict}),
                                 None, '[]', freeze({'paths': ['app/a.txt']}) if 'formatting' in features else None))
    halts = tuple(OperationalStop('validation', f'parada {n}') for n in range(stops))
    acceptance = AcceptanceDecision(eligible, () if eligible else ('stale',), items[-1].evidence) if items else None
    history = RunHistory(run_id, '{}', TASK, tuple(attempts), tuple(items), (), status, halts[-1] if halts else None,
                         halts, acceptance, freeze({'catalog': 1}) if 'prompts' in features else None)
    text = dump_history(history)
    assert json.loads(text)['format'] == fmt and load_history(text) == history
    return text


def insert_run(db, run_id, history_json, *, created_at='2026-10-22T00:00:00', revision_limit=3, status='STOPPED'):
    db.execute("INSERT INTO managed_runs(id,root,task_id,phase_id,context_json,versions_json,history_json,status,stage,"
               "revisions,revision_limit,version,created_at,updated_at,purpose) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (run_id, '/synthetic', 'T1', 'P1', '{}', freeze({'engine': 'x'}), history_json, status, 'stop',
                0, revision_limit, 1, created_at, created_at, 'task'))


class Probe:
    """Emitted SQL and history decodings during a view read."""

    def __init__(self, engine, monkeypatch):
        self.statements, self.decoded = [], 0
        original = serialization.load_history

        def counted(snapshot):
            self.decoded += 1
            return original(snapshot)
        for module in (serialization, run_projection):
            monkeypatch.setattr(module, 'load_history', counted)
        event.listen(engine, 'before_cursor_execute',
                     lambda conn, cursor, statement, params, context, many: self.statements.append((statement, params)))

    def reset(self):
        self.statements.clear()
        self.decoded = 0

    def clean(self):
        return self.decoded == 0 and not any('history_json' in statement for statement, _ in self.statements)


def assert_equivalent(views, history_json, run_id, *, revision_limit=3):
    detail = views.run(run_id)
    legacy = legacy_history(history_json)
    cycles = legacy.pop('cycles')
    assert plain(detail['history']) == plain({**legacy, 'cycle_count': len(cycles),
                                              'latest_cycle': cycles[-1] if cycles else None})
    assert detail['actions'] == legacy_actions(history_json, revision_limit=revision_limit, status=detail['status'])
    for limit in (1, 2, 100):
        offset, collected = 0, []
        while offset is not None:
            page = views.cycles(run_id, offset, limit)
            collected += page['items']
            offset = page['next_offset']
        assert plain(collected) == plain(cycles)
    for number, cycle in enumerate(load_history(history_json).cycles):
        for limit in (3, 7, 4096):
            offset = 0
            while offset is not None:
                page = views.cycle_diff(run_id, number, offset, limit)
                assert page == {'run_id': run_id, 'cycle': number, **legacy_diff(history_json, number, offset, limit)}
                offset = page['next_offset']
        for e, entry in enumerate(cycle.validation.entries):
            for r, imported in enumerate(entry.reports):
                for offset, limit in ((0, 2), (2, 2), (4, 50), (len(imported.cases), 5), (len(imported.cases) + 9, 5)):
                    assert plain(views.test_cases(run_id, number, e, r, offset, limit)) == plain(
                        legacy_cases(history_json, number, e, r, offset, limit))
                assert views.test_original(run_id, number, e, r) == (
                    base64.b64decode(imported.original_base64), imported.sha256)


def test_migration_backfills_formats_1_to_8_with_previous_results(migrated_database, monkeypatch):
    url, config = migrated_database
    command.downgrade(config, '0022_project_preparation')
    histories = {f'run-f{fmt}': synthetic(f'run-f{fmt}', fmt) for fmt in FEATURES}
    histories['run-empty'] = dump_history(RunHistory('run-empty', '{}'))
    histories['run-ready'] = synthetic('run-ready', 8, status='acceptance_ready', eligible=True, stops=0)
    histories['run-reviewing'] = synthetic('run-reviewing', 6, status='reviewing', stops=1)
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        for run_id, text in histories.items():
            insert_run(db, run_id, text)
        db.commit()
    command.upgrade(config, 'head')
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        # The migration does not rewrite histories: identical bytes.
        assert dict(db.execute('SELECT id, history_json FROM managed_runs')) == histories
        for run_id, text in histories.items():
            run_projection.verify(db, run_id, text)
    engine = make_engine(url)
    probe = Probe(engine, monkeypatch)
    views = SQLiteManagedViews(engine)
    for run_id, text in histories.items():
        probe.reset()
        assert_equivalent(views, text, run_id)
        assert probe.clean(), run_id
    detail = views.run('run-empty')
    assert detail['history']['cycle_count'] == 0 and detail['history']['latest_cycle'] is None
    assert views.cycles('run-empty', 0, 10) == {'items': [], 'offset': 0, 'next_offset': None}
    with pytest.raises(LookupError, match='review cycle'):
        views.cycle_diff('run-f1', 3, 0, 10)
    with pytest.raises(LookupError, match='JUnit report'):
        views.test_cases('run-f1', 0, 0, 0, 0, 10)  # format 1: no reports
    with pytest.raises(LookupError, match='Unknown managed run'):
        views.cycles('unknown', 0, 10)
    engine.dispose()
    # The downgrade only drops derived tables; the histories stay intact.
    command.downgrade(config, '0022_project_preparation')
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        assert dict(db.execute('SELECT id, history_json FROM managed_runs')) == histories
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'run_projection%'").fetchall()
    command.upgrade(config, 'head')


def test_large_history_reads_are_bounded_and_equivalent(migrated_database, monkeypatch):
    url, _ = migrated_database
    body = ''.join(f'+línea {n:06d} con ñ y € {"x" * 40}\n' for n in range(64_000))  # ~4 MiB
    text = synthetic('run-large', 8, cycles=40, cases=2000, diff=body, stops=30)
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        insert_run(db, 'run-large', text)
        db.commit()
    engine = make_engine(url)
    with Session(engine) as session, session.begin():
        run_projection.create(session, 'run-large', text, load_history(text))
    probe = Probe(engine, monkeypatch)
    views = SQLiteManagedViews(engine)
    started = time.perf_counter()
    detail = views.run('run-large')
    elapsed = time.perf_counter() - started
    assert probe.clean() and len(text) > 20 * 1024 * 1024
    assert detail['history']['cycle_count'] == 40 and len(json.dumps(detail)) < 64 * 1024
    probe.reset()
    page = views.cycles('run-large', 10, 10)
    assert [c['number'] for c in page['items']] == list(range(10, 20)) and page['next_offset'] == 20
    assert probe.clean()
    # Diff: a 64 KiB page in the middle of 4 MiB reads at most two chunks of the diff table.
    probe.reset()
    middle = views.cycle_diff('run-large', 39, 0, 64 * 1024)['next_offset']
    for _ in range(30):
        middle = views.cycle_diff('run-large', 39, middle, 64 * 1024)['next_offset']
    probe.reset()
    page = views.cycle_diff('run-large', 39, middle, 64 * 1024)
    chunks = [params for statement, params in probe.statements if 'run_projection_diff_chunks' in statement]
    assert probe.clean() and len(chunks) == 1
    first, last = (value for value in chunks[0][2:4])
    assert last - first <= 1 and page == {'run_id': 'run-large', 'cycle': 39,
                                          **legacy_diff(text, 39, middle, 64 * 1024)}
    # JUnit: a page of cases reads only its rows.
    probe.reset()
    cases = views.test_cases('run-large', 39, 0, 0, 1950, 100)
    assert probe.clean() and len(cases['items']) == 50 and cases['next_offset'] is None
    assert plain(cases) == plain(legacy_cases(text, 39, 0, 0, 1950, 100))
    probe.reset()
    started_legacy = time.perf_counter()
    legacy = legacy_history(text)
    elapsed_legacy = time.perf_counter() - started_legacy
    assert plain(detail['history']['latest_cycle']) == plain(legacy['cycles'][-1])
    print(f'detalle proyección {elapsed * 1000:.1f} ms; detalle anterior {elapsed_legacy * 1000:.1f} ms; '
          f'historial {len(text) / 1024 / 1024:.1f} MiB')
    engine.dispose()


def two_cycle_run(git_repo, migrated_database):  # noqa: F811
    context = configured(make_context(git_repo))
    repository = SQLiteManagedRepository(make_engine(migrated_database[0]))
    workspace = GitWorkspace(IDENTITY)
    agents = ScriptedAgentAdapter([edit(), review('REVISE'), edit('second'), review()])
    supervisor = LocalSupervisor(repository, lambda *_: (agents, ReportRunner(simple_xml(12)), workspace),
                                 commit_factory=lambda *_: workspace)
    job = repository.submit(context, TASK_ID, PHASE_ID, PLAN, VERSIONS, key='projection-start')
    assert supervisor.run_once().status == 'DONE'
    return repository, job


def test_writers_keep_the_projection_consistent_and_roll_back_with_the_history(git_repo, migrated_database,  # noqa: F811
                                                                               monkeypatch):
    repository, job = two_cycle_run(git_repo, migrated_database)
    record = repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY' and len(record.history.cycles) == 2
    views = SQLiteManagedViews(repository.engine)
    with Session(repository.engine) as session:
        text = session.scalar(select(Run.history_json).where(Run.id == job.run_id))
    assert_equivalent(views, text, job.run_id, revision_limit=record.history.revisions + 3)
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        run_projection.verify(db, job.run_id, text)
    # Failure after writing the projection and before committing: neither history nor projection change.
    original = run_projection.advance

    def interrupted(*args):
        original(*args)
        raise RuntimeError('simulated crash')
    monkeypatch.setattr(run_projection, 'advance', interrupted)
    with pytest.raises(RuntimeError, match='crash'):
        with repository._write() as session:
            repository._history(session, session.get(Run, job.run_id), replace(record.history, status='blocked'))
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        assert db.execute('SELECT history_json FROM managed_runs WHERE id=?', (job.run_id,)).fetchone()[0] == text
        run_projection.verify(db, job.run_id, text)
    assert views.run(job.run_id)['history']['status'] == 'acceptance_ready'
    # A rewrite rejected by the authority does not touch the projection either.
    monkeypatch.setattr(run_projection, 'advance', original)
    with pytest.raises(Conflict):
        with repository._write() as session:
            repository._history(session, session.get(Run, job.run_id), replace(record.history, cycles=()))
    with closing(sqlite3.connect(db_path(migrated_database))) as db:
        run_projection.verify(db, job.run_id, text)
    repository.engine.dispose()


@pytest.mark.parametrize('damage', ['changed', 'missing', 'orphan'])
def test_backup_rejects_a_projection_that_differs_from_the_history(git_repo, migrated_database, tmp_path,  # noqa: F811
                                                                   damage):
    repository, job = two_cycle_run(git_repo, migrated_database)
    repository.engine.dispose()
    bundle = backup(migrated_database, tmp_path)  # the live database is consistent
    with closing(sqlite3.connect(bundle / 'state.sqlite3')) as db:
        if damage == 'changed':
            db.execute("UPDATE run_projection_cycles SET verdict='BLOCKED' WHERE number=0")
        elif damage == 'missing':
            db.execute('DELETE FROM run_projection_cases WHERE ordinal=3')
        else:
            db.execute("INSERT INTO run_projection_stops VALUES(?, 99, 'x', 'y')", (job.run_id,))
        db.commit()
    reseal_database(bundle)
    with pytest.raises(BackupError, match='Projection'):
        restore_backup(bundle, tmp_path / 'restored')
    assert not (tmp_path / 'restored').exists()


def test_lists_and_auxiliary_reads_never_select_the_history(git_repo, migrated_database, monkeypatch):  # noqa: F811
    repository, job = two_cycle_run(git_repo, migrated_database)
    assert not hasattr(managed_views, 'load_history')
    root = SQLiteManagedViews(repository.engine).run(job.run_id)['root']
    probe = Probe(repository.engine, monkeypatch)
    views = SQLiteManagedViews(repository.engine)
    runs = views.runs(root, 0, 30)
    tasks = views.tasks(root, PHASE_ID, [TASK_ID, 'P001-T009'], 0, 30)
    views.jobs(job.run_id, 0, 30), views.attempts(job.run_id, 0, 30), views.events(job.run_id, 0, 100)
    views.exists(job.run_id)
    from my_harness.storage.permissions import PermissionRepository
    PermissionRepository(repository).list(job.run_id)
    assert probe.clean() and probe.statements
    assert [item['id'] for item in runs['items']] == [job.run_id]
    assert [(item['task_id'], item['runs'], item['latest'] and item['latest']['id']) for item in tasks['items']] == [
        (TASK_ID, 1, job.run_id), ('P001-T009', 0, None)]
    # A row read by the views does not load undeclared columns: accessing the history raises.
    with Session(repository.engine) as session:
        row = session.get(Run, job.run_id, options=[managed_views.RUN_COLUMNS])
        with pytest.raises(Exception, match='history_json'):
            row.history_json
    repository.engine.dispose()
