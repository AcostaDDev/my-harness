"""H6.4 (D072 §9): SQLite authority of the per-attempt metrics and their aggregates.

Each resolved attempt leaves a row in `attempt_metrics` in the same transaction that records its
result (`source='capture'`). Attempts before 0014 are backfilled with an explicit and
idempotent operation (`source='backfill'`) from `result_json` and, if its root is authorized, the sealed stdout
verified by size and SHA-256. Rows are not rewritten: H5.3 retention does not affect them.

Aggregates sum each field separately: `SUM` of only nulls is null and each sum carries the number of
attempts that contribute to it. Reported turns are not mixed with derived ones and no quota is deduced.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from my_harness.core.engine.metrics import CATALOG, TOKENS, attempt_metrics, replay
from my_harness.storage import run_projection
from my_harness.storage.models import (
    AttemptMetricRow as Metric, AttemptModelMetricRow as ModelMetric, ManagedAttemptRow as AttemptRow,
    ManagedCommitRow as Commit, ManagedEventRow as Event, ManagedProcessRow as Process, ManagedRunRow as Run,
    RunProjectionCycleRow as Cycle, RunProjectionRow as Projection, RunProjectionStopRow as Stop,
)
from my_harness.i18n import tr

# Raw `input_tokens` is not aggregated: Claude excludes the cache and Codex includes it. Its normalized form is.
SUMMED = ('uncached_input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens',
          'total_tokens')
# Conversations that are not work of a phase: they do not enter its SUMMARY (H6.4/H6.5).
CONVERSATIONS = ('chat', 'definition', 'phase_planning', 'project_import', 'onboarding')
DIMENSIONS = {'role': Metric.role, 'provider': Metric.provider, 'requested_model': Metric.requested_model,
              'requested_effort': Metric.requested_effort, 'day': Metric.day, 'phase': Metric.phase_code,
              'task': Metric.task_id, 'status': Metric.status, 'purpose': Metric.purpose, 'root': Metric.root}
# `key`: by descending key (most recent days first), for the UI time series (H6.2 E6).
ORDERS = ('attempts', 'tokens', 'key')
VALIDATION_DIMENSIONS = ('phase', 'task', 'root')
STOP_LIMIT = 20


# --- materialization ---------------------------------------------------------------------------


def executor_round(roles, number) -> int:
    """Executions of the run up to attempt `number` (1-based), including its own."""
    return sum(1 for role in roles[:number] if role == 'executor')


def record(session, run, attempt, *, executor_round, recorded_at, source='capture', stream=None, diagnostics=()):
    """Row of an already resolved attempt, in the caller's transaction. Never replaces an existing row."""
    if attempt.result_json is None or session.get(Metric, attempt.id) is not None:
        return False
    process = session.get(Process, attempt.id)
    request = json.loads(attempt.request_json)
    values = attempt_metrics(request=request, result=json.loads(attempt.result_json), status=attempt.status,
                             spec=process.spec if process is not None else None, executor_round=executor_round,
                             stream=stream)
    models = values.pop('models')
    notes = list(diagnostics) + ([] if process is not None else ['no_process'])
    session.add(Metric(attempt_id=attempt.id, run_id=run.id, number=attempt.number, root=run.root,
                       phase_code=run.phase_id, task_id=run.task_id, purpose=run.purpose, role=request['role'],
                       started_at=attempt.started_at, finished_at=attempt.finished_at, day=attempt.started_at[:10],
                       source=source, catalog=CATALOG, diagnostics=notes, recorded_at=recorded_at, **values))
    session.flush()  # The per-model rows reference the attempt row (foreign keys enabled).
    for item in models:
        session.add(ModelMetric(attempt_id=attempt.id, **item))
    return True


# --- explicit backfill -------------------------------------------------------------------------


def _retired(session) -> set[str]:
    """Streams with an authorized or pending purge (H5.3): not read even if the file is still there."""
    rows = session.scalars(select(Event.payload).where(Event.kind.in_(('log_retention_intent', 'log_retention_removed'))))
    return {payload.get('source') for payload in rows if isinstance(payload, dict)}


def _stream(spec, capture, roots, retired):
    """Verified reread of the sealed stdout, or the reason it is not used."""
    from my_harness.storage.backup import BackupError, _read
    if not isinstance(spec, dict) or spec.get('provider') not in ('codex', 'claude'):
        return None, ['stream_not_applicable']
    artifact = ((capture or {}).get('artifacts') or {}).get('stdout') if isinstance(capture, dict) else None
    if not isinstance(artifact, dict) or not isinstance(artifact.get('path'), str):
        return None, ['stream_unsealed']
    path = Path(artifact['path'])
    if artifact['path'] in retired:
        return None, ['stream_retired']
    if not roots or not path.is_absolute() or not any(path.is_relative_to(root) for root in roots):
        return None, ['stream_outside_authorized_roots']
    try:
        data = _read(path)
    except FileNotFoundError:
        return None, ['stream_missing']
    except (OSError, BackupError) as exc:
        return None, [f'stream_unreadable: {type(exc).__name__}']
    if len(data) != artifact.get('size') or hashlib.sha256(data).hexdigest() != artifact.get('sha256'):
        return None, ['stream_hash_mismatch']
    return replay(spec['provider'], data), ['stream_verified']


def backfill(engine, *, artifact_roots=(), clock=None) -> dict:
    """Idempotent backfill of resolved attempts without metrics. Reads disk outside the transactions."""
    roots = []
    for value in artifact_roots:
        root = Path(value)
        if not root.is_absolute() or not root.is_dir() or root.resolve() != root:
            raise ValueError(tr('metrics.roots'))
        roots.append(root)
    clock = clock or (lambda: datetime.now(timezone.utc))

    def now():
        return clock().astimezone(timezone.utc).isoformat(timespec='microseconds')
    with Session(engine) as session:
        if session.execute(text('PRAGMA user_version')).scalar():
            raise ValueError(tr('metrics.restored'))
        pending = session.scalars(select(AttemptRow.id).outerjoin(Metric, Metric.attempt_id == AttemptRow.id)
                                  .where(AttemptRow.result_json.is_not(None), Metric.attempt_id.is_(None))
                                  .order_by(AttemptRow.run_id, AttemptRow.number)).all()
    report = {'inserted': 0, 'already_present': 0, 'streams': {}}
    for attempt_id in pending:
        with Session(engine) as session:
            process = session.get(Process, attempt_id)
            stream, notes = _stream(process.spec if process else None, process.capture if process else None,
                                    roots, _retired(session))
        with Session(engine) as session, session.begin():
            session.execute(text('UPDATE managed_runs SET version = version WHERE 0'))  # SQLite lock first
            attempt = session.get(AttemptRow, attempt_id)
            run = session.get(Run, attempt.run_id)
            roles = [json.loads(value)['role'] for value in session.scalars(
                select(AttemptRow.request_json).where(AttemptRow.run_id == run.id).order_by(AttemptRow.number))]
            inserted = record(session, run, attempt, executor_round=executor_round(roles, attempt.number),
                              recorded_at=now(), source='backfill', stream=stream, diagnostics=notes)
        report['inserted' if inserted else 'already_present'] += 1
        for note in notes:
            report['streams'][note] = report['streams'].get(note, 0) + 1
    report['streams'] = dict(sorted(report['streams'].items()))
    return report


# --- queries -----------------------------------------------------------------------------------


def _scope(query, model, scope):
    for key, column in (('root', model.root), ('phase', model.phase_code if model is Metric else model.phase_id),
                        ('task', model.task_id)):
        if scope.get(key) is not None:
            query = query.where(column == scope[key])
    return query


def _sums():
    columns = []
    for name in SUMMED + ('tool_calls', 'permission_denials', 'wall_ms', 'duration_ms', 'api_duration_ms'):
        columns += [func.sum(getattr(Metric, name)).label(name), func.count(getattr(Metric, name)).label(f'{name}__n')]
    columns += [func.sum(Metric.cost_usd).label('cost_usd'), func.count(Metric.cost_usd).label('cost_usd__n')]
    for provenance, label in (('reported', 'turns_reported'), ('derived', 'turns_derived')):
        # By the recorded provenance of each row, never by the provider: they are never mixed.
        value = case((func.json_extract(Metric.provenance, '$.turns') == provenance, Metric.turns), else_=None)
        columns += [func.sum(value).label(label), func.count(value).label(f'{label}__n')]
    for basis in ('terminal', 'messages'):
        columns.append(func.sum(case((Metric.accounting == basis, 1), else_=0)).label(f'accounting_{basis}'))
    columns.append(func.count(Metric.attempt_id).label('attempts'))
    return columns


def _consumption(row) -> dict:
    data = row._mapping
    measured = lambda name: {'sum': data[name], 'attempts': data[f'{name}__n']}
    attempts = data['attempts'] or 0
    terminal, messages = data['accounting_terminal'] or 0, data['accounting_messages'] or 0
    return {'attempts': attempts,
            'accounting': {'terminal': terminal, 'messages': messages, 'absent': attempts - terminal - messages},
            'tokens': {name: measured(name) for name in SUMMED},
            'cost_usd': {**measured('cost_usd'), 'basis': 'api_equivalent_reported'},
            'turns_reported': measured('turns_reported'), 'turns_derived': measured('turns_derived'),
            'tool_calls': measured('tool_calls'), 'permission_denials': measured('permission_denials'),
            'attempt_wall_ms': measured('wall_ms'), 'reported_duration_ms': measured('duration_ms'),
            'api_duration_ms': measured('api_duration_ms')}


def attempt_view(row: Metric, models) -> dict:
    keys = ('attempt_id', 'run_id', 'number', 'root', 'phase_code', 'task_id', 'purpose', 'role', 'provider',
            'adapter_version', 'cli_version', 'requested_model', 'requested_effort', 'reported_models',
            'reported_effort', 'status', 'error', 'verdict', 'executor_round', 'accounting', 'input_semantics',
            *TOKENS, 'uncached_input_tokens', 'total_tokens', 'turns', 'tool_calls', 'tools', 'permission_denials',
            'wall_ms', 'duration_ms', 'api_duration_ms', 'cost_usd', 'started_at', 'finished_at', 'day', 'source',
            'normalization', 'catalog', 'provenance', 'diagnostics', 'recorded_at')
    return {**{key: getattr(row, key) for key in keys},
            'models': [{key: getattr(item, key) for key in ('model', *TOKENS, 'cost_usd')} for item in models]}


def _seconds(start, end):
    if not start or not end:
        return None
    return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3)


class MetricsViews:
    """Paginated reads; no writes. `scope`: {'root', 'phase', 'task'}, each key optional."""

    def __init__(self, engine):
        self.engine = engine

    def attempts(self, scope, offset, limit, run_id=None):
        with Session(self.engine) as session:
            query = _scope(select(Metric), Metric, scope)
            if run_id is not None:
                query = query.where(Metric.run_id == run_id)
            rows = session.scalars(query.order_by(Metric.started_at, Metric.run_id, Metric.number)
                                   .offset(offset).limit(limit + 1)).all()
            items = [attempt_view(row, session.scalars(select(ModelMetric).where(ModelMetric.attempt_id == row.attempt_id)
                                                       .order_by(ModelMetric.model)).all()) for row in rows[:limit]]
            return {'items': items, 'offset': offset, 'next_offset': offset + limit if len(rows) > limit else None}

    def groups(self, scope, dimension, offset, limit, *, role=None, order='attempts'):
        if dimension not in DIMENSIONS and dimension != 'reported_model':
            raise ValueError(tr('metrics.dimension', dimension=dimension))
        if order not in ORDERS:
            raise ValueError(tr('metrics.order', order=order))
        with Session(self.engine) as session:
            if dimension == 'reported_model':
                return self._model_groups(session, scope, offset, limit, role, order)
            key = DIMENSIONS[dimension]
            query = _scope(select(key.label('key'), *_sums()), Metric, scope)
            if role is not None:
                query = query.where(Metric.role == role)
            ranking = (key if order == 'key' else func.count(Metric.attempt_id) if order == 'attempts'
                       else func.coalesce(func.sum(Metric.total_tokens), -1))
            rows = session.execute(query.group_by(key).order_by(ranking.desc(), key)
                                   .offset(offset).limit(limit + 1)).all()
            items = [{'key': row.key, **_consumption(row)} for row in rows[:limit]]
            return {'dimension': dimension, 'order': order, 'role': role, 'items': items, 'offset': offset,
                    'next_offset': offset + limit if len(rows) > limit else None}

    def _model_groups(self, session, scope, offset, limit, role, order):
        """Consumption per reported model (Claude `modelUsage`); Codex reports neither model nor breakdown."""
        columns = [ModelMetric.model.label('key'), func.count(ModelMetric.attempt_id).label('attempts')]
        for name in TOKENS + ('cost_usd',):
            columns += [func.sum(getattr(ModelMetric, name)).label(name),
                        func.count(getattr(ModelMetric, name)).label(f'{name}__n')]
        query = _scope(select(*columns).join(Metric, Metric.attempt_id == ModelMetric.attempt_id), Metric, scope)
        if role is not None:
            query = query.where(Metric.role == role)
        ranking = (ModelMetric.model if order == 'key' else func.count(ModelMetric.attempt_id) if order == 'attempts'
                   else func.coalesce(func.sum(ModelMetric.output_tokens), -1))
        rows = session.execute(query.group_by(ModelMetric.model).order_by(ranking.desc(), ModelMetric.model)
                               .offset(offset).limit(limit + 1)).all()
        items = [{'key': row.key, 'attempts': row.attempts,
                  'tokens': {name: {'sum': row._mapping[name], 'attempts': row._mapping[f'{name}__n']} for name in TOKENS},
                  'cost_usd': {'sum': row.cost_usd, 'attempts': row.cost_usd__n, 'basis': 'api_equivalent_reported'}}
                 for row in rows[:limit]]
        return {'dimension': 'reported_model', 'order': order, 'role': role, 'items': items, 'offset': offset,
                'next_offset': offset + limit if len(rows) > limit else None}

    # --- tasks -------------------------------------------------------------------------------

    def _task_keys(self, session, scope):
        query = _scope(select(Run.root, Run.phase_id, Run.task_id).where(Run.purpose == 'task'), Run, scope)
        return query.group_by(Run.root, Run.phase_id, Run.task_id).order_by(Run.root, Run.phase_id, Run.task_id)

    def _task(self, session, root, phase, task) -> dict:
        runs = session.execute(select(Run.id, Run.status, Run.created_at).where(
            Run.root == root, Run.phase_id == phase, Run.task_id == task, Run.purpose == 'task')
            .order_by(Run.created_at, Run.id)).all()
        ids = [run.id for run in runs]
        run_projection.require(session, ids)
        metrics = session.scalars(select(Metric).where(Metric.run_id.in_(ids))
                                  .order_by(Metric.started_at, Metric.number)).all()
        consumption = _consumption(session.execute(select(*_sums()).where(Metric.run_id.in_(ids))).one())
        agents, by_role = {}, {}
        for row in metrics:
            key = (row.role, row.provider, row.requested_model, row.requested_effort)
            agents[key] = agents.get(key, 0) + 1
            by_role[row.role] = by_role.get(row.role, 0) + 1
        # P010-T011: `run-projection-1` projection, in the order of the runs and of their cycles and stops.
        executions = session.scalar(select(func.coalesce(func.sum(Projection.executor_attempts), 0))
                                    .where(Projection.run_id.in_(ids)))
        ordered = (Run.created_at, Run.id)
        first = session.scalar(select(Cycle.verdict).join(Run, Run.id == Cycle.run_id)
                               .where(Cycle.run_id.in_(ids), func.coalesce(Cycle.verdict, '') != '')
                               .order_by(*ordered, Cycle.number).limit(1))
        latest = select(Cycle.run_id, Cycle.number).join(Run, Run.id == Cycle.run_id).where(Cycle.run_id.in_(ids)) \
            .order_by(*(column.desc() for column in ordered), Cycle.number.desc()).limit(1)
        tests = [counts for counts, _ in run_projection.cycle_tests(session, latest).values()]
        stops = session.execute(select(Stop.stage, Stop.reason).join(Run, Run.id == Stop.run_id)
                                .where(Stop.run_id.in_(ids)).order_by(*ordered, Stop.ordinal)).all()
        accepted = [row.finished_at for row in metrics if row.role == 'reviewer' and row.verdict == 'ACCEPT']
        committed = session.scalar(select(Commit.finished_at).where(Commit.run_id.in_(ids), Commit.status == 'COMMITTED')
                                   .order_by(Commit.finished_at).limit(1))
        started = runs[0].created_at if runs else None
        return {'root': root, 'phase_code': phase, 'task_id': task, 'runs': len(runs),
                'status': runs[-1].status if runs else None,
                'agents': [{'role': r, 'provider': p, 'requested_model': m, 'requested_effort': e, 'attempts': n}
                           for (r, p, m, e), n in sorted(agents.items(), key=lambda kv: tuple(str(v) for v in kv[0]))],
                'attempts_by_role': dict(sorted(by_role.items())),
                'executions': executions, 'corrections': max(0, executions - 1) if executions else None,
                'first_verdict': first,
                'accepted_first_time': (first == 'ACCEPT') if first else None,
                'started_at': started, 'accepted_at': accepted[-1] if accepted else None, 'committed_at': committed,
                'seconds_to_accept': _seconds(started, accepted[-1] if accepted else None),
                'seconds_to_commit': _seconds(started, committed),
                'tests': tests[0] if tests else None,
                'stops': [{'stage': stop.stage, 'reason': stop.reason} for stop in stops],
                'consumption': consumption}

    def tasks(self, scope, offset, limit):
        with Session(self.engine) as session:
            keys = session.execute(self._task_keys(session, scope).offset(offset).limit(limit + 1)).all()
            items = [self._task(session, *key) for key in keys[:limit]]
            return {'items': items, 'offset': offset, 'next_offset': offset + limit if len(keys) > limit else None}

    def validations(self, scope, dimension, offset, limit):
        """Evolution of the tests (H6.2 E6): each validation cycle of the tasks in scope, grouped by phase,
        task or root, with the descending key.

        Cycles do not store their time (`source_attempt_id` only exists with JUnit reports), so they are not
        grouped by day: the date would be inferred. The phase is the axis of the evolution. P010-T011: counts per
        cycle from the projection, without decoding histories."""
        if dimension not in VALIDATION_DIMENSIONS:
            raise ValueError(tr('metrics.dimension', dimension=dimension))
        key = {'phase': Run.phase_id, 'task': Run.task_id, 'root': Run.root}[dimension]
        groups = {}
        with Session(self.engine) as session:
            runs = _scope(select(Run.id).where(Run.purpose == 'task'), Run, scope)
            run_projection.require(session, runs)
            cycles = select(Cycle.run_id, Cycle.number).where(Cycle.run_id.in_(runs))
            tests = run_projection.cycle_tests(session, cycles)
            for run_id, number, group_key in session.execute(
                    select(Cycle.run_id, Cycle.number, key).join(Run, Run.id == Cycle.run_id)
                    .where(Cycle.run_id.in_(runs)).order_by(Run.created_at, Run.id, Cycle.number)):
                counts, all_passed = tests[(run_id, number)]
                group = groups.setdefault(group_key, {'key': group_key, 'validations': 0, 'passed': 0, 'failed': 0,
                                                      'commands_passed': 0, 'commands_failed': 0, 'cases': None,
                                                      'validations_with_cases': 0})
                group['validations'] += 1
                group['passed' if all_passed else 'failed'] += 1
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
        """Scope totals, task quality, tests of their last validation and stops by reason."""
        with Session(self.engine) as session:
            consumption = _consumption(session.execute(_scope(select(*_sums()), Metric, scope)).one())
            pending = session.scalar(_scope(
                select(func.count(AttemptRow.id)).join(Run, Run.id == AttemptRow.run_id)
                .outerjoin(Metric, Metric.attempt_id == AttemptRow.id)
                .where(AttemptRow.result_json.is_not(None), Metric.attempt_id.is_(None)), Run, scope))
            tasks = [self._task(session, *key) for key in session.execute(self._task_keys(session, scope)).all()]
            run_projection.require(session, _scope(select(Run.id), Run, scope))
            count = func.count().label('count')
            grouped = _scope(select(Run.purpose, Stop.stage, Stop.reason, count).join(Run, Run.id == Stop.run_id),
                             Run, scope).group_by(Run.purpose, Stop.stage, Stop.reason)
            distinct = session.scalar(select(func.count()).select_from(grouped.subquery()))
            ranked = session.execute(grouped.order_by(count.desc(), Run.purpose, Stop.stage, Stop.reason)
                                     .limit(STOP_LIMIT)).all()
        reviewed = [task for task in tasks if task['accepted_first_time'] is not None]
        tests = {'tasks_with_validation': 0, 'commands_passed': 0, 'commands_failed': 0,
                 'cases': None}
        for task in tasks:
            if task['tests'] is None:
                continue
            tests['tasks_with_validation'] += 1
            tests['commands_passed'] += task['tests']['commands_passed']
            tests['commands_failed'] += task['tests']['commands_failed']
            if task['tests']['cases'] is not None:
                tests['cases'] = tests['cases'] or {'passed': 0, 'failed': 0, 'error': 0, 'skipped': 0}
                for key, value in task['tests']['cases'].items():
                    tests['cases'][key] += value
        durations = [task['seconds_to_commit'] for task in tasks if task['seconds_to_commit'] is not None]
        corrections = [task['corrections'] for task in tasks if task['corrections'] is not None]
        return {'scope': scope, 'catalog': CATALOG, 'consumption': consumption, 'attempts_without_metrics': pending,
                'tasks': {'count': len(tasks), 'reviewed': len(reviewed),
                          'accepted_first_time': sum(1 for task in reviewed if task['accepted_first_time']),
                          'committed': sum(1 for task in tasks if task['committed_at']),
                          'corrections': {'sum': sum(corrections), 'tasks': len(corrections)} if corrections else None,
                          'seconds_to_commit': {'sum': round(sum(durations), 3), 'tasks': len(durations),
                                                'max': max(durations)} if durations else None},
                'tests': tests,
                'stops': {'distinct': distinct, 'items': [
                    {'purpose': purpose, 'stage': stage, 'reason': reason, 'count': n}
                    for purpose, stage, reason, n in ranked]}}


def phase_consumption(session, root, code) -> dict:
    """D072: tokens and turns of the phase for its SUMMARY. Excludes the chat and the definition and
    planning conversations (H6.5): they are not work of the phase."""
    query = select(*_sums()).where(Metric.root == root, Metric.phase_code == code, Metric.purpose.notin_(CONVERSATIONS))
    by_task = {}
    for row in session.execute(select(Metric.task_id, *_sums()).where(
            Metric.root == root, Metric.phase_code == code, Metric.purpose == 'task')
            .group_by(Metric.task_id).order_by(Metric.task_id)).all():
        by_task[row.task_id] = _brief(_consumption(row))
    by_role = {row.role: _brief(_consumption(row)) for row in session.execute(
        select(Metric.role, *_sums()).where(Metric.root == root, Metric.phase_code == code,
                                            Metric.purpose.notin_(CONVERSATIONS))
        .group_by(Metric.role).order_by(Metric.role)).all()}
    return {'total': _brief(_consumption(session.execute(query).one())), 'by_role': by_role, 'by_task': by_task}


def _brief(consumption) -> dict:
    """What the SUMMARY archives: sums with their number of attempts; null different from zero."""
    tokens = consumption['tokens']
    return {'attempts': consumption['attempts'], 'accounting': consumption['accounting'],
            **{name: tokens[name] for name in SUMMED if name != 'reasoning_tokens'},
            'turns_reported': consumption['turns_reported'], 'turns_derived': consumption['turns_derived'],
            'cost_usd': consumption['cost_usd']}
