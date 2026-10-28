"""P001-T003 (D257/D259): explicit, previewed accounting operations. No GET/startup/migration/restore effect.

Reference import, accounting backfill and repricing each require an exact preview digest and an idempotency key.
Backfill and repricing build a named cohort in bounded transactions; an interrupted build resumes from its
cursor and stays BUILDING (never full coverage) until it closes. Neither operation launches a client, reads a
stream, edits a native source, rewrites `metrics-1` or changes an earlier valuation. `metrics-backfill` is separate.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from my_harness.core.engine.metric_references import ReferenceError, canonical, digest, load_bundle
from my_harness.storage import accounting
from my_harness.storage.models import (
    AttemptMetricRow as Metric, ConfigurationOperationRow as Operation, ManagedAttemptRow as Attempt,
    ManagedProcessRow as Process, ManagedRunRow as Run, MetricsReferenceRow as Reference,
    ProjectPreparationOperationRow as Preparation, UsageCaptureRow as Capture, UsageInvocationRow as Invocation,
    UsageValuationRow as Valuation, ValuationCohortMemberRow as Member, ValuationCohortRow as Cohort,
)

MAX_BUNDLE_BYTES = 1024 * 1024
MAX_MEMBERS = 10000
BATCH = 200
LEGACY = 'legacy-metrics-1'


class OperationRefused(ValueError):
    def __init__(self, code, **detail):
        super().__init__(code if not detail else f'{code}: {json.dumps(detail, sort_keys=True)}')
        self.code, self.detail = code, detail


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _writable(session):
    from my_harness.storage.backup import RESTORED_USER_VERSION
    if session.execute(text('PRAGMA user_version')).scalar() == RESTORED_USER_VERSION:
        raise OperationRefused('restored_read_only')


def _write(engine):
    session = Session(engine)
    session.begin()
    _writable(session)
    session.execute(text('UPDATE managed_runs SET version = version WHERE 0'))  # SQLite write lock first
    return session


def _sealed(preview):
    return {**preview, 'sha256': digest(preview)}


# --- references ---------------------------------------------------------------------------------


def reference_preview(engine, raw):
    """Validate a bounded canonical metrics-reference-1 bundle; saving a file alone activates nothing."""
    if type(raw) is not bytes or len(raw) > MAX_BUNDLE_BYTES:
        raise OperationRefused('reference_bundle_size')
    try:
        bundle = load_bundle(raw)
    except ReferenceError as exc:
        raise OperationRefused('reference_bundle_invalid', reason=exc.reason) from None
    with Session(engine) as session:
        _writable(session)
        new, existing, conflicts = 0, 0, []
        rows = [(bundle.id, canonical(bundle.envelope()).decode('utf-8'))]
        rows += [(ref.id, ref.content.decode('utf-8')) for ref in bundle.references]
        for identifier, content in rows:
            row = session.get(Reference, identifier)
            if row is None:
                new += 1
            elif row.content == content:
                existing += 1
            else:
                conflicts.append(identifier)
    return _sealed({'operation': 'reference-import', 'bundle': bundle.id, 'raw_sha256': sha256(raw).hexdigest(),
                    'references': len(bundle.references), 'new_rows': new, 'existing_rows': existing,
                    'conflicts': conflicts})


def reference_import(engine, raw, *, preview_sha256):
    preview = reference_preview(engine, raw)
    if preview['sha256'] != preview_sha256:
        raise OperationRefused('stale_accounting_preview')
    if preview['conflicts']:
        raise OperationRefused('reference_conflict', ids=preview['conflicts'])
    session = _write(engine)
    try:
        inserted = accounting.store_bundle(session, load_bundle(raw), source='import', now=_now())
        session.commit()
    finally:
        session.close()
    return {**preview, 'inserted_rows': inserted}


# --- cohorts ------------------------------------------------------------------------------------


def _cohort_report(session, cohort):
    rows = session.execute(select(Member.reason, Valuation.status, func.count()).outerjoin(
        Valuation, Valuation.id == Member.valuation_id).where(Member.cohort_id == cohort.id)
        .group_by(Member.reason, Valuation.status)).all()
    statuses, gaps = {}, {}
    for reason, status, count in rows:
        if reason is not None:
            gaps[reason] = gaps.get(reason, 0) + count
        else:
            statuses[status] = statuses.get(status, 0) + count
    return {'cohort': cohort.id, 'name': cohort.name, 'kind': cohort.kind, 'status': cohort.status,
            'expected': cohort.expected, 'built': cohort.built, 'valuations': dict(sorted(statuses.items())),
            'unpriced': dict(sorted(gaps.items())), 'selection_digest': cohort.selection_digest,
            'scenario_digest': cohort.scenario_digest}


def _replay(engine, *, key, kind, preview_sha256):
    """An existing cohort for this key resumes/returns from its frozen selection, never from a new preview."""
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise OperationRefused('idempotency_key')
    with Session(engine) as session:
        cohort = session.scalar(select(Cohort).where(Cohort.idempotency_key == key))
        if cohort is None:
            return None
        if cohort.request_sha256 != digest({'kind': kind, 'preview': preview_sha256}):
            raise OperationRefused('idempotency_key_reused')
        return {'name': cohort.name, 'sha256': preview_sha256}


def _confirm(engine, preview, *, key, kind, build):
    if not isinstance(key, str) or not 1 <= len(key) <= 200:
        raise OperationRefused('idempotency_key')
    request = digest({'kind': kind, 'preview': preview['sha256']})
    session = _write(engine)
    try:
        cohort = session.scalar(select(Cohort).where(Cohort.idempotency_key == key))
        if cohort is None:
            if session.scalar(select(Cohort.id).where(Cohort.name == preview['name'])):
                raise OperationRefused('cohort_name_exists')
            references = (preview.get('scenario') or {}).get('profile', {}).get('references')
            if references is not None and accounting.bundle(session, references, now=_now()) is None:
                raise OperationRefused('reference_missing')
            cohort = Cohort(id=str(uuid4()), name=preview['name'], kind=kind, idempotency_key=key,
                            request_sha256=request, selection=preview['selection'],
                            selection_digest=preview['selection_digest'], scenario=preview.get('scenario'),
                            scenario_digest=preview.get('scenario_digest'),
                            reference_set_digest=(preview.get('scenario') or {}).get('profile', {}).get('references'),
                            status='BUILDING', expected=len(preview['selection']['members']), built=0,
                            created_at=_now())
            session.add(cohort)
        elif cohort.request_sha256 != request:
            raise OperationRefused('idempotency_key_reused')
        identifier = cohort.id
        session.commit()
    finally:
        session.close()
    while True:
        session = _write(engine)
        try:
            cohort = session.get(Cohort, identifier)
            if cohort.status == 'CLOSED':
                return _cohort_report(session, cohort)
            members = cohort.selection['members']
            batch = members[cohort.built:cohort.built + BATCH]
            now = _now()
            for member in batch:
                build(session, cohort, member, now)
            cohort.built += len(batch)
            cohort.cursor = batch[-1][0] if batch else cohort.cursor
            if cohort.built == cohort.expected:
                cohort.status, cohort.closed_at = 'CLOSED', now
                cohort.report = _cohort_report(session, cohort)
            session.commit()
        finally:
            session.close()


def _member(session, cohort, invocation_id, basis, valuation=None, reason=None, now=None):
    if session.get(Member, (cohort.id, invocation_id, basis)) is None:
        session.add(Member(cohort_id=cohort.id, invocation_id=invocation_id, basis=basis,
                           valuation_id=valuation.id if valuation is not None else None,
                           reason=None if valuation is not None else reason, recorded_at=now))


# --- accounting backfill ------------------------------------------------------------------------


def _backfill_members(session):
    members = []
    attempts = session.scalars(select(Attempt.id).outerjoin(Invocation, Invocation.attempt_id == Attempt.id)
                               .where(Attempt.result_json.is_not(None), Invocation.id.is_(None)).order_by(Attempt.id))
    members += [['managed_attempt', value] for value in attempts]
    processes = session.scalars(select(Process).outerjoin(Invocation, Invocation.preparation_step_id == Process.id)
                                .where(Process.preparation_id.is_not(None), Process.capture.is_not(None),
                                       Invocation.id.is_(None)).order_by(Process.id))
    members += [['preparation_step', row.id] for row in processes if row.spec.get('adapter_version') != 'preparation-commands-1']
    operations = session.scalars(select(Operation).outerjoin(Invocation, Invocation.operation_id == Operation.id)
                                 .where(Operation.kind == 'ASSIST', Operation.status == 'APPLIED', Invocation.id.is_(None))
                                 .order_by(Operation.id))
    members += [['configuration_assistance', row.id] for row in operations if row.payload.get('attempt_id')]
    return members


def backfill_preview(engine, *, name):
    """Settled native sources without an invocation row; bounded, frozen membership."""
    _name(name)
    with Session(engine) as session:
        _writable(session)
        members = _backfill_members(session)
    if len(members) > MAX_MEMBERS:
        raise OperationRefused('accounting_selection_too_large', limit=MAX_MEMBERS, found=len(members))
    selection = {'format': 'accounting-backfill-1', 'members': members}
    return _sealed({'operation': 'accounting-backfill', 'name': name, 'selection': selection,
                    'selection_digest': digest(selection), 'expected': len(members)})


def _legacy_capture(session, invocation, attempt_id, now):
    """Only a metrics-1 row survives: limited provenance, no invented TTL/model/profile/effective date."""
    row = session.get(Metric, attempt_id)
    if row is None:
        return None
    fields = ('provider', 'adapter_version', 'cli_version', 'requested_model', 'requested_effort', 'reported_models',
              'reported_effort', 'accounting', 'input_semantics', 'input_tokens', 'cache_read_tokens',
              'cache_write_tokens', 'output_tokens', 'reasoning_tokens', 'status', 'normalization', 'catalog', 'source')
    document = {'format': LEGACY, 'metric': {key: getattr(row, key) for key in fields},
                'cost_usd': None if row.cost_usd is None else {'value': repr(row.cost_usd), 'representation': 'legacy_float'},
                'reasons': ['legacy_evidence']}
    return accounting.append_capture(session, invocation, document, source='backfill', now=now)


def _backfill_member(session, cohort, member, now):
    kind, source_id = member
    invocation = session.get(Invocation, accounting.key(kind, source_id))
    if invocation is None:
        if kind == 'managed_attempt':
            attempt = session.get(Attempt, source_id)
            run = session.get(Run, attempt.run_id)
            invocation = accounting.intend_attempt(session, run, attempt)
            if session.get(Process, attempt.id) is not None:
                accounting.settle_attempt(session, run, attempt, source='backfill')
            else:
                invocation.launch, invocation.outcome = 'unknown_execution', attempt.status
                invocation.finished_at, invocation.updated_at = attempt.finished_at, now
                _legacy_capture(session, invocation, attempt.id, now)
        elif kind == 'preparation_step':
            process = session.get(Process, source_id)
            operation = session.get(Preparation, process.preparation_id)
            started = (process.capture or {}).get('started_at') or operation.created_at
            invocation = accounting.intend_preparation(session, operation, process.id, process.spec, started)
            accounting.settle_process(session, kind, source_id, {'spec': process.spec, 'status': process.status,
                                      'identity': process.identity, 'capture': process.capture},
                                      outcome=(process.capture or {}).get('status'), now=now,
                                      finished_at=operation.updated_at, source='backfill')
        else:
            operation = session.get(Operation, source_id)
            payload = operation.payload
            invocation = accounting.intend_assistance(session, operation, payload['preview'], payload['attempt_id'],
                                                      operation.created_at)
            accounting.settle_process(session, kind, source_id, payload.get('process'), outcome=operation.status,
                                      now=now, finished_at=operation.updated_at, source='backfill')
    profile = (invocation.binding or {}).get('profile')
    basis = profile['basis'] if profile else 'unknown'
    valuation = session.scalar(select(Valuation).where(Valuation.invocation_id == invocation.id,
                                                       Valuation.origin == 'backfill').order_by(Valuation.recorded_at))
    reason = None
    if valuation is None:
        captured = session.scalar(select(Capture).where(Capture.invocation_id == invocation.id).order_by(Capture.id.desc()))
        reason = ('not_invoked' if invocation.launch == 'not_invoked' else 'capture_unavailable' if captured is None
                  else 'legacy_evidence' if captured.version == LEGACY
                  else (invocation.binding or {}).get('reason') or 'billing_profile_unknown')
    _member(session, cohort, invocation.id, basis, valuation, reason, now)


def backfill(engine, *, name, preview_sha256, key):
    replay = _replay(engine, key=key, kind='backfill', preview_sha256=preview_sha256)
    if replay is not None:
        return _confirm(engine, replay, key=key, kind='backfill', build=_backfill_member)
    preview = backfill_preview(engine, name=name)
    if preview['sha256'] != preview_sha256:
        raise OperationRefused('stale_accounting_preview')
    return _confirm(engine, preview, key=key, kind='backfill', build=_backfill_member)


# --- repricing ----------------------------------------------------------------------------------


def _name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120 or name != name.strip():
        raise OperationRefused('cohort_name')


def _profile(profile):
    from my_harness.services.configuration import billing_profiles
    try:
        billing_profiles({'profiles': {'scenario': profile}}, {})
    except ValueError:
        raise OperationRefused('repricing_profile_invalid') from None
    return {**{k: profile[k] for k in ('provider', 'platform', 'product', 'scheme', 'unit', 'basis', 'references')},
            'conditions': {k: {'value': v['value'], 'provenance': 'asserted', 'source': v['source']}
                           for k, v in sorted(profile.get('conditions', {}).items())}}


FILTERS = ('source_kinds', 'started_from', 'started_before', 'root', 'purpose', 'cohort')


def reprice_preview(engine, *, name, profile, retrospective, filters=None):
    """Explicit scenario over a bounded frozen selection; never claims a current tariff was effective then."""
    _name(name)
    if type(retrospective) is not bool:
        raise OperationRefused('repricing_retrospective_required')
    filters = dict(filters or {})
    if set(filters) - set(FILTERS):
        raise OperationRefused('repricing_filter')
    profile = _profile(profile)
    scenario = {'format': 'repricing-scenario-1', 'profile': profile, 'retrospective': retrospective,
                'at': 'invocation_started_at'}
    with Session(engine) as session:
        _writable(session)
        query = select(Invocation).where(Invocation.launch != 'not_invoked').order_by(Invocation.id)
        if filters.get('source_kinds'):
            query = query.where(Invocation.source_kind.in_(list(filters['source_kinds'])))
        for field, column in (('root', Invocation.root), ('purpose', Invocation.purpose)):
            if filters.get(field) is not None:
                query = query.where(column == filters[field])
        if filters.get('started_from'):
            query = query.where(Invocation.started_at >= filters['started_from'])
        if filters.get('started_before'):
            query = query.where(Invocation.started_at < filters['started_before'])
        if filters.get('cohort'):
            query = query.join(Member, Member.invocation_id == Invocation.id).where(Member.cohort_id == filters['cohort'])
        members = []
        for invocation in session.scalars(query):
            capture = session.scalar(select(Capture).where(Capture.invocation_id == invocation.id)
                                     .order_by(Capture.id.desc()).limit(1))
            provider = ((capture.document.get('client') or {}).get('provider')
                        if capture is not None and isinstance(capture.document, dict) else None)
            if capture is not None and capture.version == LEGACY:
                provider = (capture.document.get('metric') or {}).get('provider')
            if provider not in (None, profile['provider']):
                continue
            members.append([invocation.id, capture.id if capture is not None else None])
            if len(members) > MAX_MEMBERS:
                raise OperationRefused('accounting_selection_too_large', limit=MAX_MEMBERS)
        if not accounting.available(session, profile['references']):
            raise OperationRefused('reference_missing')
    selection = {'format': 'accounting-repricing-1', 'filters': filters, 'members': members}
    return _sealed({'operation': 'accounting-repricing', 'name': name, 'selection': selection,
                    'selection_digest': digest(selection), 'scenario': scenario, 'scenario_digest': digest(scenario),
                    'expected': len(members)})


def _reprice_member(session, cohort, member, now):
    invocation_id, capture_id = member
    invocation = session.get(Invocation, invocation_id)
    profile, retrospective = cohort.scenario['profile'], cohort.scenario['retrospective']
    capture = session.get(Capture, capture_id) if capture_id is not None else None
    valuation, reason = None, None
    if capture is None:
        reason = 'capture_unavailable'
    elif capture.version == LEGACY or capture.evidence is None:
        reason = 'legacy_evidence' if capture.version == LEGACY else 'usage_missing'
    else:
        original = session.scalar(select(Valuation.id).where(Valuation.invocation_id == invocation.id,
            Valuation.origin == 'admission', Valuation.basis == profile['basis']))
        valuation = accounting.value(session, invocation, capture, profile=profile, origin='repricing', now=now,
                                     scenario=accounting.scenario_for(profile, accounting.utc(invocation.started_at),
                                                                      retrospective=retrospective),
                                     supersedes=original)
        reason = None if valuation is not None else 'reference_missing'
    _member(session, cohort, invocation.id, profile['basis'], valuation, reason, now)


def reprice(engine, *, name, profile, retrospective, filters=None, preview_sha256, key):
    replay = _replay(engine, key=key, kind='repricing', preview_sha256=preview_sha256)
    if replay is not None:
        return _confirm(engine, replay, key=key, kind='repricing', build=_reprice_member)
    preview = reprice_preview(engine, name=name, profile=profile, retrospective=retrospective, filters=filters)
    if preview['sha256'] != preview_sha256:
        raise OperationRefused('stale_accounting_preview')
    return _confirm(engine, preview, key=key, kind='repricing', build=_reprice_member)
