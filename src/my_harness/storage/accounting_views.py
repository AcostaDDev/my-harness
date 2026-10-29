"""P001-T004 (D257, T001 §8, D262): bounded read-only queries over the invocation accounting ledger.

One row per native invocation, joined with its latest capture and the valuation(s) chosen by one explicit
selection policy: the original admission-bound valuation (default) or the membership of one named cohort. Nothing
here prices, backfills, launches a client, rewrites a row or decodes a run history; reads work on a restored
query-only archive. Amounts are decimal strings summed exactly; only identical unit/platform/product/scheme/basis
buckets are added. Missing is never zero, an invocation enters a total once, and a known subtotal is never labelled
as a full amount while any expected invocation in scope is unpriced, incomplete or its cohort is still building.
"""
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import json

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from my_harness.i18n import tr
from my_harness.storage.models import (
    MetricsReferenceRow as Reference, UsageCaptureRow as Capture, UsageComponentRow as Component,
    UsageInvocationRow as Invocation, UsageValuationLineRow as Line, UsageValuationRow as Valuation,
    ValuationCohortMemberRow as Member, ValuationCohortRow as Cohort,
)

FORMAT = 'accounting-aggregate-1'
QUANTUM = Decimal('0.000000000001')
CONVERSATIONS = ('chat', 'definition', 'phase_planning', 'project_import', 'onboarding')
PHASE_PURPOSES = ('phase_check', 'phase_close', 'phase_transition')
WORK = ('task_first_pass', 'task_rework', 'phase', 'conversation', 'setup', 'other')
TASK_WORK = ('task_first_pass', 'task_rework')
# T001 §8: phase work excludes conversations, preparation and configuration assistance unless asked for.
PHASE_WORK = ('task_first_pass', 'task_rework', 'phase', 'other')
TOKENS = ('uncached_input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'cache_write_5m_tokens',
          'cache_write_1h_tokens', 'output_tokens', 'reasoning_tokens')
BUCKET = ('unit', 'platform', 'product', 'scheme', 'basis', 'counterfactual', 'retrospective')
DIMENSIONS = {'provider': 'provider', 'effective_model': 'effective_model', 'requested_model': 'requested_model',
              'role': 'role', 'purpose': 'purpose', 'work': 'work', 'source_kind': 'source_kind', 'root': 'root',
              'phase': 'phase_code', 'task': 'task_id', 'day': 'day', 'outcome': 'outcome', 'launch': 'launch'}
ORDERS = ('invocations', 'key')
FILTERS = ('root', 'phase', 'task', 'provider', 'role', 'purpose', 'source_kind', 'outcome', 'launch',
           'requested_model', 'effective_model', 'effective_model_kind', 'work', 'started_from', 'started_before')
EQUAL = {'root': 'root', 'phase': 'phase_code', 'task': 'task_id', 'provider': 'provider', 'role': 'role',
         'purpose': 'purpose', 'source_kind': 'source_kind', 'outcome': 'outcome', 'launch': 'launch',
         'requested_model': 'requested_model', 'effective_model': 'effective_model',
         'effective_model_kind': 'effective_model_kind'}
LEGACY = 'legacy-metrics-1'

# Reported model of every selected component: one name, several (`mixed`) or not established (`unknown`).
_MODELS = "FROM json_each(c.evidence, '$.components') e"
_MODEL = "json_extract(e.value, '$.reported_model')"
BASE = f"""
SELECT i.id AS id, i.source_kind, i.source_id, i.run_id, i.attempt_id, i.preparation_id, i.preparation_step_id,
       i.operation_id, i.request_id, i.root, i.project_id, i.phase_code, i.task_id, i.purpose, i.role, i.agent,
       COALESCE(json_extract(i.versions, '$.' || i.agent || '_provider'), json_extract(c.document, '$.client.provider'),
                json_extract(c.document, '$.metric.provider')) AS provider,
       i.requested_model, i.requested_effort, i.launch, i.outcome, i.started_at, i.finished_at,
       substr(i.started_at, 1, 10) AS day,
       json_extract(i.binding, '$.profile.basis') AS binding_basis, json_extract(i.binding, '$.reason') AS binding_reason,
       c.id AS capture_id, c.version AS capture_version, c.source AS capture_source, c.recorded_at AS capture_recorded_at,
       c.evidence AS evidence, json_extract(c.document, '$.timing.wall_ms') AS wall_ms,
       (SELECT CASE WHEN COUNT(DISTINCT {_MODEL}) > 1 THEN 'mixed'
                    WHEN COUNT(*) > 0 AND COUNT({_MODEL}) = COUNT(*) THEN 'reported' ELSE 'unknown' END
        {_MODELS}) AS effective_model_kind,
       (SELECT CASE WHEN COUNT(DISTINCT {_MODEL}) = 1 AND COUNT({_MODEL}) = COUNT(*) THEN MAX({_MODEL}) END
        {_MODELS}) AS effective_model,
       CASE WHEN i.source_kind != 'managed_attempt' THEN 'setup'
            WHEN i.purpose IN {CONVERSATIONS} THEN 'conversation'
            WHEN i.purpose IN {PHASE_PURPOSES} THEN 'phase'
            WHEN i.purpose != 'task' THEN 'other'
            WHEN EXISTS (SELECT 1 FROM managed_runs r2 WHERE r2.purpose = 'task' AND r2.root = r.root
                         AND r2.phase_id = r.phase_id AND r2.task_id = r.task_id
                         AND (r2.created_at < r.created_at OR (r2.created_at = r.created_at AND r2.id < r.id)))
                 THEN 'task_rework'
            WHEN (SELECT COUNT(*) FROM managed_attempts a2 WHERE a2.run_id = a.run_id AND a2.number <= a.number
                  AND json_extract(a2.request_json, '$.role') = 'executor') > 1 THEN 'task_rework'
            ELSE 'task_first_pass' END AS work
FROM usage_invocations i
LEFT JOIN usage_captures c ON c.id = (SELECT MAX(c2.id) FROM usage_captures c2 WHERE c2.invocation_id = i.id)
LEFT JOIN managed_attempts a ON a.id = i.attempt_id
LEFT JOIN managed_runs r ON r.id = i.run_id
"""
VALUATION = """v.id AS valuation_id, v.origin AS valuation_origin, v.status AS valuation_status, v.unit,
       json_extract(v.scenario, '$.platform') AS platform, json_extract(v.scenario, '$.product') AS product,
       v.scheme, v.basis, v.counterfactual, v.retrospective, v.amount, v.known_subtotal,
       v.reasons AS valuation_reasons, v.warnings AS valuation_warnings,
       json_extract(v.discrepancy, '$.status') AS discrepancy"""


class Selection:
    """Original admission-bound valuations, or the frozen membership of one named cohort (D257)."""

    def __init__(self, session, cohort=None):
        self.cohort = None
        if cohort is not None:
            self.cohort = session.get(Cohort, cohort) or session.scalar(select(Cohort).where(Cohort.name == cohort))
            if self.cohort is None:
                raise LookupError(tr('accounting.cohort_unknown'))

    @property
    def closed(self):
        return self.cohort is None or self.cohort.status == 'CLOSED'

    def view(self):
        if self.cohort is None:
            return {'policy': 'admission', 'cohort': None, 'complete': True}
        return {'policy': 'cohort', 'cohort': cohort_view(self.cohort), 'complete': self.closed}

    def join(self):
        if self.cohort is None:
            return ("LEFT JOIN usage_valuations v ON v.id = (SELECT v2.id FROM usage_valuations v2 WHERE "
                    "v2.invocation_id = b.id AND v2.origin = 'admission' ORDER BY v2.recorded_at, v2.id LIMIT 1)",
                    "1 AS member, NULL AS member_reason")
        return ("LEFT JOIN valuation_cohort_members m ON m.cohort_id = :cohort AND m.invocation_id = b.id "
                "LEFT JOIN usage_valuations v ON v.id = m.valuation_id",
                "m.cohort_id IS NOT NULL AS member, m.reason AS member_reason")


def cohort_view(row):
    return {'id': row.id, 'name': row.name, 'kind': row.kind, 'status': row.status, 'expected': row.expected,
            'built': row.built, 'selection_digest': row.selection_digest, 'scenario_digest': row.scenario_digest,
            'reference_set_digest': row.reference_set_digest,
            'basis': ((row.scenario or {}).get('profile') or {}).get('basis'),
            'retrospective': (row.scenario or {}).get('retrospective'),
            'created_at': row.created_at, 'closed_at': row.closed_at}


def _filtered(filters, params):
    """Filters over the computed invocation columns; unknown keys are refused, never ignored."""
    if set(filters) - set(FILTERS):
        raise ValueError(tr('accounting.filter', filter=', '.join(sorted(set(filters) - set(FILTERS)))))
    clauses, binds = [], []
    for name, column in EQUAL.items():
        if filters.get(name) is not None:
            clauses.append(f'b.{column} = :{name}')
            params[name] = filters[name]
    if filters.get('work'):
        clauses.append('b.work IN :work')
        params['work'] = list(filters['work'])
        binds.append(bindparam('work', expanding=True))
    for name, operator in (('started_from', '>='), ('started_before', '<')):
        if filters.get(name) is not None:
            clauses.append(f'b.started_at {operator} :{name}')
            params[name] = filters[name]
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    return f'SELECT b.* FROM ({BASE}) b {where}', binds


def scope(filters):
    """Effective filters: a phase without an explicit work selection names the phase-work default."""
    filters = {key: value for key, value in filters.items() if value is not None}
    if filters.get('phase') is not None and not filters.get('work'):
        filters['work'] = list(PHASE_WORK)
    if filters.get('work'):
        if set(filters['work']) - set(WORK):
            raise ValueError(tr('accounting.filter', filter='work'))
        filters['work'] = sorted(set(filters['work']), key=WORK.index)
    return filters


def _rows(session, filters, selection):
    params = {}
    query, binds = _filtered(filters, params)
    join, member = selection.join()
    if selection.cohort is not None:
        params['cohort'] = selection.cohort.id
    statement = text(f'SELECT b.*, {member}, {VALUATION} FROM ({query}) b {join} ORDER BY b.id, v.id')
    return session.execute(statement.bindparams(*binds), params).mappings()


def _invocations(session, filters, selection):
    """(invocation, [valuation rows]) in id order; a cohort can hold one member per basis."""
    current, valuations = None, []
    for row in _rows(session, filters, selection):
        if current is not None and row['id'] != current['id']:
            yield current, valuations
            valuations = []
        current = row
        if row['valuation_id'] is not None:
            valuations.append(row)
    if current is not None:
        yield current, valuations


# --- per-invocation interpretation -------------------------------------------------------------


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def quantities(evidence):
    """Disjoint selected components → summed categories; one unknown component leaves that category unknown."""
    components = (evidence or {}).get('components') or []
    result = {}
    for name in TOKENS:
        values = []
        for item in components:
            if name == 'uncached_input_tokens':
                raw, read = item.get('input_tokens'), item.get('cache_read_tokens')
                # usage-accounting-1: Claude input excludes the cache; legacy Codex input includes cache reads.
                value = (raw if item.get('semantics') == 'claude-cli-1'
                         else raw - read if item.get('semantics') == 'codex-cli-1' and None not in (raw, read) else None)
            else:
                value = item.get({'cache_write_5m_tokens': 'write_5m', 'cache_write_1h_tokens': 'write_1h'}.get(name, name))
            values.append(value if type(value) is int and value >= 0 else None)
        result[name] = sum(values) if values and None not in values else None
    return result


def usage_view(row):
    evidence = _json(row['evidence'])
    coverage = (evidence or {}).get('coverage') or 'absent'
    return {'coverage': coverage if row['launch'] != 'not_invoked' else None,
            'partition': (evidence or {}).get('partition'), 'delegation': (evidence or {}).get('delegation'),
            'charges_complete': (evidence or {}).get('charges_complete'),
            'reasons': (evidence or {}).get('reasons') or (['legacy_evidence'] if row['capture_version'] == LEGACY else []),
            'tokens': quantities(evidence)}


def unpriced_reason(row):
    """Why an expected invocation has no selected valuation; never a substitute price."""
    if row['member_reason']:
        return row['member_reason']
    if row['capture_id'] is None:
        return 'capture_unavailable'
    if row['capture_version'] == LEGACY:
        return 'legacy_evidence'
    if row['binding_basis'] is None:
        return row['binding_reason'] or 'billing_profile_unknown'
    return 'reference_missing'


def _sum(values):
    with localcontext() as context:
        context.prec = 200
        total = Decimal(0)
        for value in values:
            total += Decimal(value)
    return format(total, 'f')


def _divide(value, count):
    if value is None or not count:
        return None
    with localcontext() as context:
        context.prec = 200
        return format((Decimal(value) / count).quantize(QUANTUM, rounding=ROUND_HALF_EVEN), 'f')


class Totals:
    """Coverage, token sums, ratios and compatible amount buckets of one scope or group."""

    def __init__(self, closed=True, policy='admission'):
        self.closed, self.policy = closed, policy
        self.invocations = self.expected = self.captured = self.outside = 0
        self.launch, self.usage, self.priced, self.unpriced = Counter(), Counter(), Counter(), Counter()
        self.tokens = {name: [0, 0, 0] for name in TOKENS}
        self.cache, self.wall = [0, 0, 0], [0, 0, 0]
        self.buckets = {}

    def add(self, row, valuations):
        if not row['member']:
            self.outside += 1  # in the filter scope, outside the selected cohort: not counted, only shown
            return
        self.invocations += 1
        self.launch[row['launch']] += 1
        if row['launch'] == 'not_invoked':
            return  # positive evidence that inference never began: excluded from spend denominators
        self.expected += 1
        self.captured += row['capture_id'] is not None
        usage = usage_view(row)
        self.usage[usage['coverage']] += 1
        tokens = usage['tokens']
        for name, value in tokens.items():
            if value is not None:
                self.tokens[name][0] += value
                self.tokens[name][1] += 1
                self.tokens[name][2] += usage['coverage'] != 'complete'
        if usage['coverage'] == 'complete':
            parts = (tokens['uncached_input_tokens'], tokens['cache_read_tokens'], tokens['cache_write_tokens'])
            if None not in parts:
                self.cache[0] += parts[1]
                self.cache[1] += sum(parts)
                self.cache[2] += 1
            wall = row['wall_ms']
            if tokens['output_tokens'] is not None and type(wall) is int and wall > 0:
                self.wall[0] += tokens['output_tokens']
                self.wall[1] += wall
                self.wall[2] += 1
        if not valuations:
            self.priced['unpriced'] += 1
            self.unpriced[unpriced_reason(row)] += 1
            return
        statuses = {item['valuation_status'] for item in valuations}
        self.priced[next(s for s in ('unsupported', 'incomplete', 'complete') if s in statuses)] += 1
        for item in valuations:
            key = tuple(bool(item[k]) if k in ('counterfactual', 'retrospective') else item[k] for k in BUCKET)
            bucket = self.buckets.setdefault(key, {'counts': Counter(), 'complete': [], 'known': [],
                                                   'reasons': Counter(), 'discrepancies': Counter()})
            bucket['counts'][item['valuation_status']] += 1
            if item['valuation_status'] == 'complete':
                bucket['complete'].append(item['amount'])
                bucket['known'].append(item['amount'])
            elif item['known_subtotal'] is not None:
                bucket['known'].append(item['known_subtotal'])
            bucket['reasons'].update(_json(item['valuation_reasons']) or [])
            if item['discrepancy']:
                bucket['discrepancies'][item['discrepancy']] += 1

    def full(self):
        """Every expected invocation has a selected complete valuation and the selection is closed."""
        return self.closed and self.priced['unpriced'] == 0 and self.priced['complete'] == self.expected

    def amounts(self):
        scope_complete = self.closed and self.priced['unpriced'] == 0
        result = []
        for key, bucket in sorted(self.buckets.items(), key=lambda item: tuple(str(v) for v in item[0])):
            counts = bucket['counts']
            complete = scope_complete and counts['incomplete'] == 0 and counts['unsupported'] == 0
            result.append({**dict(zip(BUCKET, key)), 'invocations': sum(counts.values()),
                           'complete': counts['complete'], 'incomplete': counts['incomplete'],
                           'unsupported': counts['unsupported'], 'denominator': self.expected,
                           'amount': _sum(bucket['complete']) if complete else None,
                           'known_subtotal': _sum(bucket['known']) if bucket['known'] else None,
                           'reasons': dict(sorted(bucket['reasons'].items())),
                           'discrepancies': dict(sorted(bucket['discrepancies'].items()))})
        return result

    def view(self):
        cache = self.cache
        wall = self.wall
        return {
            'coverage': {'invocations': self.invocations, 'expected': self.expected,
                         'launch': {name: self.launch[name] for name in ('pending', 'not_invoked', 'observed',
                                                                         'unknown_execution')},
                         'captured': self.captured,
                         'usage': {name: self.usage[name] for name in ('complete', 'partial', 'absent')},
                         'valuation': {name: self.priced[name] for name in ('complete', 'incomplete', 'unsupported',
                                                                            'unpriced')},
                         'unpriced_reasons': dict(sorted(self.unpriced.items())),
                         'outside_selection': self.outside if self.policy == 'cohort' else None,
                         'full_scope_priced': self.full()},
            'tokens': {name: {'sum': values[0] if values[1] else None, 'invocations': values[1], 'partial': values[2]}
                       for name, values in self.tokens.items()},
            'cache_hit': {'cache_read_tokens': cache[0], 'input_tokens': cache[1], 'invocations': cache[2],
                          'excluded': self.expected - cache[2], 'ratio': cache[0] / cache[1] if cache[1] else None},
            'wall_throughput': {'output_tokens': wall[0], 'wall_ms': wall[1], 'invocations': wall[2],
                                'excluded': self.expected - wall[2],
                                'output_tokens_per_wall_second': wall[0] * 1000 / wall[1] if wall[1] else None},
            'amounts': self.amounts(),
        }


# --- views -------------------------------------------------------------------------------------


def _valuation_brief(row):
    return {'id': row.id, 'origin': row.origin, 'status': row.status, 'unit': row.unit,
            'platform': (row.scenario or {}).get('platform'), 'product': (row.scenario or {}).get('product'),
            'scheme': row.scheme, 'basis': row.basis, 'counterfactual': row.counterfactual,
            'retrospective': row.retrospective, 'amount': row.amount, 'known_subtotal': row.known_subtotal,
            'reasons': row.reasons, 'warnings': row.warnings,
            'discrepancy': (row.discrepancy or {}).get('status') if row.discrepancy else None}


def bundle_view(bundle, source, recorded_at):
    """D263: what a billing profile can pin from one bundle; tariff schemes carry their bases and conditions."""
    documents = [ref.document() for ref in bundle.references]
    schemes = {}
    for document in documents:
        if document['kind'] != 'tariff':
            continue
        identity = tuple(document[key] for key in ('provider', 'platform', 'product', 'scheme', 'unit'))
        item = schemes.setdefault(identity, {'bases': set(), 'conditions': {}, 'models': set()})
        item['bases'].update(document['bases'])
        item['models'].add(document['model'])
        for name in document['required_conditions']:
            item['conditions'].setdefault(name, set())
        for case in document['cases']:
            for name, value in case['conditions'].items():
                item['conditions'].setdefault(name, set()).add(str(value))
    observed = sorted(document['observed_at'] for document in documents)
    unknown = {document['effective_period_unknown'] for document in documents}
    return {'id': bundle.id, 'source': source, 'recorded_at': recorded_at, 'available': True,
            'references': len(documents), 'providers': sorted({document['provider'] for document in documents}),
            'models': sorted({document['model'] for document in documents}),
            'observed_from': observed[0] if observed else None, 'observed_to': observed[-1] if observed else None,
            'effective_period': 'unknown' if unknown == {True} else 'known' if unknown == {False} else 'mixed',
            'schemes': [{**dict(zip(('provider', 'platform', 'product', 'scheme', 'unit'), identity)),
                         'bases': sorted(item['bases']), 'models': sorted(item['models']),
                         'conditions': {name: sorted(values) for name, values in sorted(item['conditions'].items())}}
                        for identity, item in sorted(schemes.items())]}


def _page(items, offset, limit):
    return {'items': items[:limit], 'offset': offset, 'next_offset': offset + limit if len(items) > limit else None}


class AccountingViews:
    """Read-only accounting queries; `filters` keys from FILTERS (root/phase/task come from the API scope)."""

    def __init__(self, engine):
        self.engine = engine

    def summary(self, filters, cohort=None):
        filters = scope(filters)
        with Session(self.engine) as session:
            selection = Selection(session, cohort)
            totals = Totals(selection.closed, selection.view()['policy'])
            for row, valuations in _invocations(session, filters, selection):
                totals.add(row, valuations)
            return {'format': FORMAT, 'filters': filters, 'selection': selection.view(), **totals.view()}

    def groups(self, filters, dimension, offset, limit, *, cohort=None, order='invocations'):
        if dimension not in DIMENSIONS:
            raise ValueError(tr('metrics.dimension', dimension=dimension))
        if order not in ORDERS:
            raise ValueError(tr('metrics.order', order=order))
        filters = scope(filters)
        column = DIMENSIONS[dimension]
        with Session(self.engine) as session:
            selection = Selection(session, cohort)
            policy, groups = selection.view()['policy'], {}
            for row, valuations in _invocations(session, filters, selection):
                # Phases and tasks are only unique within their project root (and phase).
                context = ((row['root'],) if dimension == 'phase' else
                           (row['root'], row['phase_code']) if dimension == 'task' else ())
                kind = row['effective_model_kind'] if dimension == 'effective_model' else (
                    'value' if row[column] is not None else 'unknown')
                key = (kind, row[column], *context)
                if key not in groups:
                    groups[key] = Totals(selection.closed, policy)
                groups[key].add(row, valuations)
            ranked = sorted(groups.items(), key=lambda item: (str(item[0][1]) if item[0][1] is not None else '',
                                                              item[0][0], *(str(v) for v in item[0][2:])), reverse=True)
            if order == 'invocations':
                ranked.sort(key=lambda item: item[1].invocations, reverse=True)  # stable: key order within a count
            items = [{'key': key[1], 'key_kind': key[0],
                      'root': key[2] if len(key) > 2 else None, 'phase_code': key[3] if len(key) > 3 else None,
                      **totals.view()} for key, totals in ranked[offset:offset + limit + 1]]
            return {'format': FORMAT, 'dimension': dimension, 'order': order, 'filters': filters,
                    'selection': selection.view(), **_page(items, offset, limit)}

    def tasks(self, filters, cohort=None):
        """T001 §8: task spend over every attempted task invocation (revisions, reviews and retries included),
        per compatible bucket, against attempted and verified-COMMITTED tasks. Exact indicators only for a
        fully priced scope with known acceptance; otherwise the known subtotals stay partial."""
        filters = scope(filters)
        filters = {**filters, 'work': [item for item in filters.get('work') or TASK_WORK if item in TASK_WORK]}
        with Session(self.engine) as session:
            selection = Selection(session, cohort)
            policy = selection.view()['policy']
            commits = self._commits(session, filters.get('root'))
            everything, committed = Totals(selection.closed, policy), Totals(selection.closed, policy)
            attempted, accepted, unknown = set(), set(), set()
            # An explicit work filter without task work selects no task invocation (never every invocation).
            rows = _invocations(session, filters, selection) if filters['work'] else ()
            for row, valuations in rows:
                everything.add(row, valuations)
                task = (row['root'], row['phase_code'], row['task_id'])
                if row['member'] and row['launch'] != 'not_invoked':
                    attempted.add(task)
                state = commits.get(task)
                if state == 'COMMITTED':
                    accepted.add(task)
                    committed.add(row, valuations)
                elif state == 'INTENT':
                    unknown.add(task)
            accepted &= attempted
            unknown &= attempted
            known = not unknown
            indicators = []
            totals, linked = everything.view()['amounts'], {tuple(b[k] for k in BUCKET): b
                                                            for b in committed.view()['amounts']}
            for bucket in totals:
                other = linked.get(tuple(bucket[k] for k in BUCKET)) or {}
                total, work_amount = bucket['amount'], other.get('amount')
                indicators.append({**{k: bucket[k] for k in BUCKET},
                                   'total': {'amount': total, 'known_subtotal': bucket['known_subtotal']},
                                   'committed_work': {'amount': work_amount,
                                                      'known_subtotal': other.get('known_subtotal')},
                                   'per_committed_task': _divide(total, len(accepted)) if known else None,
                                   'per_attempted_task': _divide(total, len(attempted)),
                                   'committed_work_per_committed_task':
                                       _divide(work_amount, len(accepted)) if known else None})
            return {'format': FORMAT, 'filters': filters, 'selection': selection.view(),
                    'tasks': {'attempted': len(attempted), 'committed': len(accepted),
                              'acceptance_unknown': len(unknown),
                              'not_committed': len(attempted) - len(accepted) - len(unknown)},
                    'coverage': everything.view()['coverage'], 'committed_coverage': committed.view()['coverage'],
                    'indicators': indicators}

    @staticmethod
    def _commits(session, root):
        """Per task: COMMITTED if any run committed, INTENT if only an unresolved commit exists."""
        query = ("SELECT r.root, r.phase_id, r.task_id, MAX(c.status = 'COMMITTED') AS committed, "
                 "MAX(c.status = 'INTENT') AS intent FROM managed_commits c JOIN managed_runs r ON r.id = c.run_id "
                 "WHERE r.purpose = 'task'" + (' AND r.root = :root' if root is not None else '') +
                 ' GROUP BY r.root, r.phase_id, r.task_id')
        rows = session.execute(text(query), {'root': root} if root is not None else {}).all()
        return {(row.root, row.phase_id, row.task_id): 'COMMITTED' if row.committed else 'INTENT' if row.intent
                else None for row in rows}

    # --- details -----------------------------------------------------------------------------

    def invocations(self, filters, offset, limit, cohort=None):
        filters = scope(filters)
        with Session(self.engine) as session:
            selection = Selection(session, cohort)
            params = {}
            query, binds = _filtered(filters, params)
            statement = text(f'{query} ORDER BY b.started_at, b.id LIMIT :limit OFFSET :offset').bindparams(*binds)
            rows = session.execute(statement, {**params, 'limit': limit + 1, 'offset': offset}).mappings().all()
            items = [self._item(session, row, selection) for row in rows[:limit]]
            return {'format': FORMAT, 'filters': filters, 'selection': selection.view(), 'items': items,
                    'offset': offset, 'next_offset': offset + limit if len(rows) > limit else None}

    def _item(self, session, row, selection):
        if selection.cohort is None:
            chosen = session.scalars(select(Valuation).where(Valuation.invocation_id == row['id'],
                                                             Valuation.origin == 'admission')
                                     .order_by(Valuation.recorded_at, Valuation.id).limit(1)).all()
            member = {'member': 1, 'member_reason': None}
        else:
            members = session.scalars(select(Member).where(Member.cohort_id == selection.cohort.id,
                                                           Member.invocation_id == row['id'])
                                      .order_by(Member.basis)).all()
            chosen = [session.get(Valuation, m.valuation_id) for m in members if m.valuation_id is not None]
            reasons = [m.reason for m in members if m.reason is not None]
            member = {'member': 1 if members else 0, 'member_reason': reasons[0] if reasons else None}
        context = {**row, **member}
        expected = member['member'] and row['launch'] != 'not_invoked'
        keys = ('id', 'source_kind', 'source_id', 'run_id', 'attempt_id', 'preparation_id', 'preparation_step_id',
                'operation_id', 'request_id', 'root', 'project_id', 'phase_code', 'task_id', 'purpose', 'work', 'role',
                'agent', 'provider', 'requested_model', 'requested_effort', 'effective_model', 'effective_model_kind',
                'launch', 'outcome', 'started_at', 'finished_at', 'wall_ms')
        return {**{key: row[key] for key in keys},
                'capture': None if row['capture_id'] is None else {
                    'id': row['capture_id'], 'version': row['capture_version'], 'source': row['capture_source'],
                    'recorded_at': row['capture_recorded_at']},
                'usage': usage_view(row), 'in_selection': bool(member['member']),
                'valuations': [_valuation_brief(item) for item in chosen],
                'unpriced_reason': unpriced_reason(context) if expected and not chosen else None}

    def invocation(self, invocation_id, cohort=None):
        with Session(self.engine) as session:
            selection = Selection(session, cohort)
            row = session.execute(text(f'SELECT b.* FROM ({BASE}) b WHERE b.id = :id'), {'id': invocation_id}) \
                .mappings().one_or_none()
            if row is None:
                raise LookupError(tr('accounting.invocation_unknown'))
            invocation = session.get(Invocation, invocation_id)
            capture = session.get(Capture, row['capture_id']) if row['capture_id'] is not None else None
            parts = [] if capture is None else session.scalars(
                select(Component).where(Component.capture_id == capture.id).order_by(Component.key)).all()
            keys = ('key', 'grain', 'parent_key', 'inclusion', 'reported_model', 'model_source', 'semantics',
                    'coverage', 'input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'write_5m', 'write_1h',
                    'output_tokens', 'reasoning_tokens', 'reasons')
            count = session.scalar(select(func.count(Capture.id)).where(Capture.invocation_id == invocation_id))
            return {**self._item(session, row, selection), 'selection': selection.view(),
                    'versions': invocation.versions, 'binding': invocation.binding,
                    'binding_sha256': invocation.binding_sha256, 'captures': count,
                    'capture_document': None if capture is None else {
                        'digest': capture.digest, 'document': capture.document, 'evidence': capture.evidence,
                        'evidence_digest': capture.evidence_digest},
                    'components': [{key: getattr(part, key) for key in keys} for part in parts]}

    def valuations(self, invocation_id, offset, limit):
        """Every immutable valuation of one invocation, oldest first, with its lines and reference identity."""
        with Session(self.engine) as session:
            if session.get(Invocation, invocation_id) is None:
                raise LookupError(tr('accounting.invocation_unknown'))
            rows = session.scalars(select(Valuation).where(Valuation.invocation_id == invocation_id)
                                   .order_by(Valuation.recorded_at, Valuation.id).offset(offset).limit(limit + 1)).all()
            items = []
            for row in rows[:limit]:
                lines = session.scalars(select(Line).where(Line.valuation_id == row.id).order_by(Line.number)).all()
                references = {ref for line in lines for ref in (line.tariff_reference, line.identity_reference) if ref}
                cohorts = session.execute(select(Cohort.id, Cohort.name).join(Member, Member.cohort_id == Cohort.id)
                                          .where(Member.valuation_id == row.id).order_by(Cohort.name)).all()
                items.append({**_valuation_brief(row), 'capture_id': row.capture_id,
                              'normalization': row.normalization, 'calculator': row.calculator,
                              'profile_digest': row.profile_digest, 'reference_set_digest': row.reference_set_digest,
                              'scenario_digest': row.scenario_digest, 'evidence_digest': row.evidence_digest,
                              'scenario': row.scenario, 'exact_sum': row.exact_sum,
                              'rounding_adjustment': row.rounding_adjustment,
                              'selected_components': row.selected_components,
                              'discrepancy_detail': row.discrepancy, 'supersedes': row.supersedes,
                              'recorded_at': row.recorded_at,
                              'cohorts': [{'id': ident, 'name': name} for ident, name in cohorts],
                              'lines': [{'number': line.number, 'component_key': line.component_key,
                                         'category': line.category, 'quantity': line.quantity, 'rate': line.rate,
                                         'factors': line.factors, 'included_adjustments': line.included_adjustments,
                                         'tariff_reference': line.tariff_reference,
                                         'identity_reference': line.identity_reference, 'rate_case': line.rate_case,
                                         'exact_amount': line.exact_amount} for line in lines],
                              'references': [self._reference(session.get(Reference, ident))
                                             for ident in sorted(references)]})
            return {'items': items, 'offset': offset,
                    'next_offset': offset + limit if len(rows) > limit else None}

    @staticmethod
    def _reference(row):
        return {'id': row.id, 'kind': row.kind, 'format': row.format, 'source': row.source, 'provider': row.provider,
                'product': row.product, 'model': row.model, 'observed_at': row.observed_at}

    def references(self, offset, limit):
        """D263: the packaged bundle first, then imported bundles, newest first. Reads never insert rows."""
        from my_harness.core.engine.metric_references import ReferenceError, load_bundle
        from my_harness.storage.accounting import packaged
        bundle = packaged()
        with Session(self.engine) as session:
            stored = session.get(Reference, bundle.id)
            items = [] if offset else [bundle_view(bundle, 'packaged', stored.recorded_at if stored else None)]
            rows = session.scalars(select(Reference).where(Reference.kind == 'bundle', Reference.id != bundle.id)
                                   .order_by(Reference.recorded_at.desc(), Reference.id)
                                   .offset(max(offset - 1, 0)).limit(limit + 1 - len(items))).all()
        for row in rows:
            try:
                loaded = load_bundle(row.content.encode('utf-8'))
                if loaded.id != row.id:
                    raise ReferenceError('reference_conflict', 'bundle digest mismatch')
                items.append(bundle_view(loaded, row.source, row.recorded_at))
            except ReferenceError:
                # A damaged row stays visible as unavailable instead of disappearing from the list.
                items.append({'id': row.id, 'source': row.source, 'recorded_at': row.recorded_at, 'available': False,
                              'references': 0, 'providers': [], 'models': [], 'observed_from': None,
                              'observed_to': None, 'effective_period': 'unknown', 'schemes': []})
        return _page(items, offset, limit)

    def cohorts(self, offset, limit):
        with Session(self.engine) as session:
            rows = session.scalars(select(Cohort).order_by(Cohort.created_at.desc(), Cohort.id)
                                   .offset(offset).limit(limit + 1)).all()
            return {'items': [cohort_view(row) for row in rows[:limit]], 'offset': offset,
                    'next_offset': offset + limit if len(rows) > limit else None}
