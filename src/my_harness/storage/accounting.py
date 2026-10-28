"""P001-T003 (D254–D257, D259): SQLite authority of the invocation accounting ledger.

Every write runs inside the caller's native-source transaction: managed attempt history, preparation executor
journal or configuration-assistance operation. Intent rows are idempotent by `(source_kind, source_id)`; captures
are append-only and deduplicated by content digest; valuations are immutable rows keyed by their full identity.
Nothing here launches a client, retries inference, settles a process or reads the current configuration.
"""
from datetime import datetime, timezone
from functools import cache

from sqlalchemy import select

from my_harness.core.engine.metric_references import (ReferenceError, canonical, digest, load_bundle,
                                                     load_packaged_bundle)
from my_harness.core.engine.usage_capture import CAPTURE, build, components, evidence
from my_harness.core.engine.valuation import CALCULATOR, NORMALIZATION, calculate, compare_estimate
from my_harness.storage.models import (
    MetricsReferenceRow as Reference, UsageCaptureRow as Capture, UsageComponentRow as Component,
    UsageInvocationRow as Invocation, UsageValuationLineRow as Line, UsageValuationRow as Valuation,
)

SOURCES = ('managed_attempt', 'preparation_step', 'configuration_assistance')
SCENARIO = 'valuation-scenario-1'
PROFILE_FIELDS = ('provider', 'platform', 'product', 'scheme', 'unit', 'basis')


class AccountingConflict(ValueError):
    pass


def key(kind, source_id):
    if kind not in SOURCES or not isinstance(source_id, str) or not source_id:
        raise AccountingConflict('unknown native invocation source')
    return f'{kind}:{source_id}'


def utc(value):
    """Native ISO timestamps → the calculator's explicit UTC form, without changing the instant."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise AccountingConflict('naive native timestamp')
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def agent_of(role):
    from my_harness.adapters.cli_agents import ROLES
    return ROLES.get(role)


def intend(session, *, kind, source_id, purpose, role, selection, versions, now, binding=None, **links):
    """Persist the expected invocation with its native intent. Replays return the existing row unchanged."""
    identifier = key(kind, source_id)
    row = session.get(Invocation, identifier)
    if row is not None:
        return row
    allowed = {'run_id', 'attempt_id', 'preparation_id', 'preparation_step_id', 'operation_id', 'request_id',
               'root', 'project_id', 'phase_code', 'task_id'}
    if set(links) - allowed:
        raise AccountingConflict('unknown invocation link')
    selection = selection or {}
    if binding and binding.get('profile') and not available(session, binding['profile'].get('references')):
        binding = {**binding, 'reason': 'reference_missing'}  # kept unpriced, never a substitute bundle
    row = Invocation(id=identifier, source_kind=kind, source_id=source_id, purpose=purpose, role=role,
                     agent=agent_of(role), requested_model=selection.get('model'),
                     requested_effort=selection.get('effort'),
                     versions={k: versions.get(k) for k in sorted(versions)} if isinstance(versions, dict) else {},
                     binding=binding, binding_sha256=digest(binding) if binding is not None else None,
                     launch='pending', started_at=now, recorded_at=now, updated_at=now, **links)
    session.add(row)
    session.flush()
    return row


def settle(session, invocation, *, spec, status, identity_present, capture, outcome, finished_at, now,
           source='capture'):
    """Advance the lifecycle projection and append the capture/valuation of a settled native source."""
    selection = {'model': invocation.requested_model, 'effort': invocation.requested_effort}
    document = build(spec=spec, status=status, identity_present=identity_present, capture=capture,
                     selection=selection)
    invocation.launch = document['launch']
    invocation.outcome = outcome
    invocation.finished_at = finished_at
    invocation.updated_at = now
    if spec is None:
        # No process evidence at all: the expected row stays visible without a manufactured capture.
        return None
    row = append_capture(session, invocation, document, source=source, now=now)
    if document['launch'] != 'not_invoked':
        # A backfilled invocation never acquires an admission-bound valuation after the fact.
        admission_valuation(session, invocation, row, now=now, origin='admission' if source == 'capture' else 'backfill')
    return row


def append_capture(session, invocation, document, *, source, now):
    sha = digest(document)
    existing = session.scalar(select(Capture).where(Capture.invocation_id == invocation.id,
                                                    Capture.version == document['format'], Capture.digest == sha))
    if existing is not None:
        return existing
    views = components(document) if document['format'] == CAPTURE else []
    selected = evidence(document, views) if document['format'] == CAPTURE else document.get('evidence')
    row = Capture(invocation_id=invocation.id, version=document['format'], digest=sha, document=document,
                  evidence=selected, evidence_digest=digest(selected) if selected is not None else None,
                  source=source, recorded_at=now)
    session.add(row)
    session.flush()
    for view in views:
        session.add(Component(capture_id=row.id, **view))
    session.flush()
    return row


# --- references ---------------------------------------------------------------------------------


def store_bundle(session, bundle, *, source, now):
    """Insert a validated bundle and its documents; equal bytes are idempotent, different bytes conflict."""
    rows = [(bundle.id, 'bundle', canonical(bundle.envelope()).decode('utf-8'), {})]
    for ref in bundle.references:
        document = ref.document()
        rows.append((ref.id, document['kind'], ref.content.decode('utf-8'), document))
    inserted = 0
    for identifier, kind, content, document in rows:
        existing = session.get(Reference, identifier)
        if existing is not None:
            if existing.content != content or existing.kind != kind:
                raise AccountingConflict('reference_conflict')
            continue
        session.add(Reference(id=identifier, kind=kind, format='metrics-reference-1', content=content, source=source,
                              provider=document.get('provider'), product=document.get('product'),
                              model=document.get('model'), observed_at=document.get('observed_at'),
                              recorded_at=now))
        inserted += 1
    session.flush()
    return inserted


@cache
def packaged():
    """The immutable packaged bundle, validated once per process."""
    return load_packaged_bundle()


def bundle(session, identifier, *, now):
    """The exact pinned bundle: packaged bytes or an explicitly imported row. Never a newer substitute."""
    if packaged().id == identifier:
        if session.get(Reference, identifier) is None:
            store_bundle(session, packaged(), source='packaged', now=now)
        return packaged()
    row = session.get(Reference, identifier)
    if row is None or row.kind != 'bundle':
        return None
    try:
        loaded = load_bundle(row.content.encode('utf-8'))
    except ReferenceError:
        return None
    return loaded if loaded.id == identifier else None


def available(session, identifier):
    """Read-only check that `bundle` would succeed, without inserting packaged rows."""
    if packaged().id == identifier:
        return True
    row = session.get(Reference, identifier)
    try:
        return row is not None and row.kind == 'bundle' and load_bundle(row.content.encode('utf-8')).id == identifier
    except ReferenceError:
        return False


# --- valuations ---------------------------------------------------------------------------------


def scenario_for(profile, at, *, retrospective=False):
    return {'format': SCENARIO, 'at': at, 'retrospective': retrospective,
            **{field: profile.get(field) for field in PROFILE_FIELDS},
            'conditions': profile.get('conditions') or {}}


def admission_valuation(session, invocation, capture, *, now, origin='admission'):
    """The original valuation bound at admission; absent binding stays unpriced (billing_profile_unknown)."""
    profile = (invocation.binding or {}).get('profile')
    if not profile:
        return None
    return value(session, invocation, capture, profile=profile,
                 scenario=scenario_for(profile, utc(invocation.started_at)), origin=origin, now=now)


def value(session, invocation, capture, *, profile, scenario, origin, now, supersedes=None):
    selected = bundle(session, profile.get('references'), now=now)
    if selected is None or capture.evidence is None:
        return None
    result = calculate(capture.evidence, scenario, selected)
    identity = {'invocation': invocation.id, 'capture': capture.digest, 'normalization': NORMALIZATION,
                'calculator': CALCULATOR, 'profile': digest(profile), 'references': selected.id,
                'basis': scenario['basis'], 'scenario': result['profile_digest']}
    identifier = digest(identity)
    existing = session.get(Valuation, identifier)
    if existing is not None:
        return existing
    reported = ((capture.document.get('reported_amounts') or {}).get('total_cost_usd')
                if isinstance(capture.document, dict) else None)
    discrepancy = None
    if reported is not None:
        # The client's estimate basis is not established: show both figures, never claim a billing delta.
        comparison = compare_estimate(result, {'amount': reported['value'], 'unit': 'USD', 'basis': None,
                                               'scheme': None, 'legacy_float': reported['representation'] == 'legacy_float'})
        discrepancy = {**comparison, 'reported': reported, 'reported_basis': 'client_estimate_unknown_basis'}
    row = Valuation(id=identifier, invocation_id=invocation.id, capture_id=capture.id, origin=origin,
                    normalization=NORMALIZATION, calculator=CALCULATOR, profile_digest=identity['profile'],
                    reference_set_digest=selected.id, basis=scenario['basis'], scenario_digest=identity['scenario'],
                    evidence_digest=result['evidence_digest'], scenario=scenario, status=result['status'],
                    unit=scenario['unit'], scheme=scenario['scheme'], amount=result['amount'],
                    known_subtotal=result['known_subtotal'], exact_sum=result['exact_sum'],
                    rounding_adjustment=result['rounding_adjustment'], counterfactual=result['counterfactual'],
                    retrospective=result['retrospective'], reasons=result['reasons'], warnings=result['warnings'],
                    selected_components=result['selected_components'], discrepancy=discrepancy,
                    supersedes=supersedes, recorded_at=now)
    session.add(row)
    session.flush()
    for number, line in enumerate(result['lines'], start=1):
        session.add(Line(valuation_id=identifier, number=number, component_key=line['component'],
                         category=line['category'], quantity=line['quantity'], rate=line['rate'],
                         factors=line['factors'], included_adjustments=line['included_adjustments'],
                         tariff_reference=line['tariff_reference'], identity_reference=line['identity_reference'],
                         rate_case=line['rate_case'], exact_amount=line['exact_amount']))
    session.flush()
    return row


# --- native sources -----------------------------------------------------------------------------


def frozen_versions(versions, agent):
    """Client/configuration identities relevant to this invocation; never environment or paths."""
    keep = ('engine', 'agent_adapter', 'local_config', 'project_configuration', 'project_configuration_revision',
            'project_configuration_sha256', 'cli_compatibility_sha256')
    return {k: v for k, v in sorted((versions or {}).items())
            if isinstance(v, (str, type(None))) and (k in keep or agent and k.startswith(f'{agent}_'))}


def intend_attempt(session, run, attempt):
    """Managed attempt: the attempt row is the native intent; the binding is the job's sealed revision."""
    import json
    from my_harness.storage.billing import for_versions
    request = json.loads(attempt.request_json)
    versions = json.loads(run.versions_json)
    agent = agent_of(request['role'])
    selection = request.get('selection') or {}
    return intend(session, kind='managed_attempt', source_id=attempt.id, purpose=run.purpose, role=request['role'],
                  selection=selection, versions=frozen_versions(versions, agent), now=attempt.started_at,
                  binding=for_versions(session, versions, agent), run_id=run.id, attempt_id=attempt.id,
                  request_id=attempt.id, root=run.root, project_id=versions.get('project_registry_id'),
                  phase_code=run.phase_id, task_id=run.task_id)


def settle_attempt(session, run, attempt, *, source='capture'):
    from my_harness.storage.models import ManagedProcessRow as Process
    invocation = session.get(Invocation, key('managed_attempt', attempt.id)) or intend_attempt(session, run, attempt)
    process = session.get(Process, attempt.id)
    return settle(session, invocation, spec=process.spec if process else None,
                  status=process.status if process else None,
                  identity_present=bool(process is not None and process.identity),
                  capture=process.capture if process else None, outcome=attempt.status,
                  finished_at=attempt.finished_at, now=attempt.finished_at or invocation.updated_at, source=source)


def intend_preparation(session, operation, step_id, spec, now):
    """Generic preparation executor step: the journal's executor intent, bound through its confirmed plan."""
    from my_harness.storage.billing import resolve
    data = operation.plan.get('configuration_data') if isinstance(operation.plan, dict) else None
    return intend(session, kind='preparation_step', source_id=step_id, purpose='preparation', role='executor',
                  selection=spec.get('requested') or {}, now=now,
                  versions=frozen_versions(operation.plan.get('agent_versions'), 'executor'),
                  binding=resolve(session, 'executor', project=data) if isinstance(data, dict) else None,
                  preparation_id=operation.id, preparation_step_id=step_id, request_id=step_id,
                  root=operation.root, project_id=operation.project_id)


def intend_assistance(session, row, preview, attempt_id, now):
    """The INTENDED operation is the native intent; its binding is the frozen active source of the preview."""
    from my_harness.storage.billing import resolve
    scope, agent = preview['scope'], 'reviewer' if preview['role'] == 'reviewer' else 'executor'
    reference = {'revision': preview['source']['revision'], 'sha256': preview['source']['sha256']}
    binding = (resolve(session, agent, global_reference=reference) if scope == 'global'
               else resolve(session, agent, project_reference={'scope': scope, **reference}))
    return intend(session, kind='configuration_assistance', source_id=row.id, purpose='configuration_assistance',
                  role='configuration' if agent == 'reviewer' else 'executor', selection=preview['selection'],
                  versions=frozen_versions(preview['versions'], agent), now=now, binding=binding,
                  operation_id=row.id, request_id=attempt_id, project_id=None if scope == 'global' else scope[8:])


def settle_process(session, kind, source_id, process, *, outcome, now, finished_at=None, source='capture'):
    """Preparation/assistance: the native journal's own process record, never a manufactured attempt."""
    invocation = session.get(Invocation, key(kind, source_id))
    if invocation is None:
        return None
    process = process or {}
    return settle(session, invocation, spec=process.get('spec'), status=process.get('status'),
                  identity_present=bool(process.get('identity')), capture=process.get('capture'),
                  outcome=outcome, finished_at=finished_at or now, now=now, source=source)
