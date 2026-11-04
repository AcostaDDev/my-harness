"""P002-T016 (D276, D299): SQLite authority of autonomous roadmap runs.

Every mutation runs inside the managed writer transaction (`SQLiteManagedRepository._write`), so it serializes with
manual jobs, batches and phase operations of the same database. Authorization revisions, delegated children, bound
consumption and events are insert-only (triggers); the run row and owner questions change by compare-and-set on
their version. Nothing here launches a process or calls a model.
"""
from uuid import uuid4

from decimal import Decimal

from sqlalchemy import func, select

from my_harness.core.engine import autonomy
from my_harness.storage.models import (
    AutonomousAuthorizationRow as Authorization, AutonomousChildRow as Child,
    AutonomousConsumptionRow as Consumption, AutonomousEventRow as Event, AutonomousQuestionRow as Question,
    AutonomousRunRow as Run, KnowledgeProjectRow, PhaseAuthorizationRow, PhaseRow,
)

refuse = autonomy.AutonomyRefusal


def project_id(session, root):
    return session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == str(root)))


def active_run(session, root):
    return session.scalar(select(Run).where(Run.root == str(root), Run.status.notin_(autonomy.TERMINAL)))


def active_batches(session, root):
    """Manual batch authorizations still able to chain work on this root (excluded while a run is active)."""
    return list(session.scalars(select(PhaseAuthorizationRow.id).join(
        PhaseRow, PhaseRow.id == PhaseAuthorizationRow.phase_id).where(
        PhaseRow.root == str(root), PhaseAuthorizationRow.kind == 'batch', PhaseAuthorizationRow.status == 'ACTIVE')))


def authorization(session, ident):
    row = session.get(Authorization, ident)
    if row is None:
        raise LookupError(ident)
    return row


def latest(session, lineage_id):
    return session.scalar(select(Authorization).where(Authorization.lineage_id == lineage_id)
                          .order_by(Authorization.number.desc()).limit(1))


def event(session, run, kind, payload, *, refs=None, dedupe=None, now):
    """Deduplicated event with references T017 can derive an item from (project, phase, task, operation...)."""
    key = dedupe or f'{run.id}:{run.version}:{kind}'
    existing = session.scalar(select(Event).where(Event.dedupe_key == key))
    if existing is not None:
        return existing
    row = Event(run_id=run.id, root=run.root, kind=kind, dedupe_key=key,
                refs={'run_id': run.id, 'authorization_id': run.authorization_id, **(refs or {})},
                payload=dict(payload), created_at=now)
    session.add(row)
    session.flush()
    return row


def seal(session, *, root, project, lineage_id, previous, key, request_sha256, preview, actor, reason, policy,
         permission_record_id, now):
    """One owner-confirmed authorization revision; the same idempotency key with the same request returns it."""
    existing = session.scalar(select(Authorization).where(Authorization.idempotency_key == key))
    if existing is not None:
        if existing.request_sha256 != request_sha256:
            raise refuse('idempotency_conflict')
        return existing, False
    number = 1 if previous is None else previous.number + 1
    row = Authorization(id=preview_id(key), root=str(root), project_id=project, lineage_id=lineage_id, number=number,
                        previous_id=previous.id if previous else None, idempotency_key=key,
                        request_sha256=request_sha256, preview=dict(preview), preview_sha256=preview['preview_sha256'],
                        origin='owner_confirmed', policy=dict(policy), permission_record_id=permission_record_id,
                        actor=dict(actor), reason=reason, created_at=now)
    session.add(row)
    session.flush()
    return row, True


def preview_id(key):
    """Deterministic authorization identity of one confirmation request, so the T010 parent can name it first."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'my-harness:autonomous-authorization:' + key))


def create_run(session, *, root, authorization_row, now):
    if active_run(session, root) is not None:
        raise refuse('autonomous_run_active')
    run = Run(id=str(uuid4()), root=str(root), lineage_id=authorization_row.lineage_id,
              authorization_id=authorization_row.id, thread_id=f'roadmap-{authorization_row.lineage_id}',
              status='RUNNING', reason='authorized', detail={'graph_started': False}, version=1,
              created_at=now, updated_at=now)
    session.add(run)
    session.flush()
    event(session, run, 'run_started', {'authorization_number': authorization_row.number,
                                        'preview_sha256': authorization_row.preview_sha256},
          dedupe=f'{run.id}:started', now=now)
    return run


def run_by_id(session, run_id):
    run = session.get(Run, run_id)
    if run is None:
        raise LookupError(run_id)
    return run


def move(session, run, expected, target, *, reason, detail=None, now, refs=None, expected_version=None):
    """Compare-and-set state change with its event in the same transaction (FL02 guard table)."""
    if expected_version is not None and run.version != expected_version:
        raise refuse('run_version_stale')
    if run.status not in expected:
        raise refuse('run_state', status=run.status)
    if target != run.status:
        autonomy.transition(run.status, target)
    previous = run.status
    run.status, run.reason = target, reason
    run.detail = {**(run.detail or {}), **(detail or {}), 'previous_status': previous}
    run.version += 1
    run.updated_at = now
    event(session, run, 'run_' + target.lower(), {'from': previous, 'reason': reason, 'detail': detail or {}},
          refs=refs, now=now)
    return run


def child(session, run, *, kind, key, subject, rule, now, ruling_id=None, permission_record_id=None):
    """A concrete `owner_delegated` child under the run's current authorization revision; idempotent by key."""
    existing = session.scalar(select(Child).where(Child.operation_key == key))
    if existing is not None:
        if existing.run_id != run.id or existing.kind != kind or existing.subject != subject:
            raise refuse('child_conflict')
        return existing
    row = Child(id=str(uuid4()), run_id=run.id, authorization_id=run.authorization_id, kind=kind, operation_key=key,
                subject=dict(subject), preview_sha256=autonomy.digest(subject), rule=rule, ruling_id=ruling_id,
                permission_record_id=permission_record_id, origin='owner_delegated', created_at=now)
    session.add(row)
    session.flush()
    event(session, run, 'child_sealed', {'child_id': row.id, 'kind': kind, 'rule': rule,
                                         'preview_sha256': row.preview_sha256},
          refs={k: v for k, v in subject.items() if k in ('phase', 'task', 'operation_id')},
          dedupe=f'child:{row.id}', now=now)
    return row


def children(session, run_id):
    return list(session.scalars(select(Child).where(Child.run_id == run_id).order_by(Child.created_at, Child.id)))


def consumed(session, root, bound, identities):
    identities = [identities] if isinstance(identities, str) else list(identities)
    return session.scalar(select(func.count()).select_from(Consumption).where(
        Consumption.root == str(root), Consumption.bound == bound, Consumption.identity.in_(identities))) or 0


def consume(session, run, *, bound, identity, key, evidence, now):
    """Records one unit; never deleted, so a resume, new revision, phase change, rename or split cannot refill it."""
    existing = session.scalar(select(Consumption).where(Consumption.consumption_key == key))
    if existing is not None:
        return existing
    row = Consumption(id=str(uuid4()), root=run.root, bound=bound, identity=identity, consumption_key=key,
                      run_id=run.id, authorization_id=run.authorization_id, evidence=dict(evidence), created_at=now)
    session.add(row)
    session.flush()
    return row


def ask(session, run, *, kind, subject, binding, now):
    """Durable owner question; the same subject under the same authorization revision is asked once."""
    key = autonomy.digest({'kind': kind, 'subject': subject, 'authorization_id': run.authorization_id})
    existing = session.scalar(select(Question).where(Question.run_id == run.id, Question.dedupe_key == key))
    if existing is not None:
        return existing
    row = Question(id=str(uuid4()), run_id=run.id, dedupe_key=key, kind=kind, subject=dict(subject),
                   binding=dict(binding), status='OPEN', version=1, created_at=now, updated_at=now)
    session.add(row)
    session.flush()
    event(session, run, 'question_opened', {'question_id': row.id, 'kind': kind},
          refs={'question_id': row.id, **{k: v for k, v in subject.items() if k in ('phase', 'task')}},
          dedupe=f'question:{row.id}', now=now)
    return row


def open_questions(session, run_id):
    return list(session.scalars(select(Question).where(Question.run_id == run_id, Question.status == 'OPEN')
                                .order_by(Question.created_at, Question.id)))


def questions(session, run_id):
    return list(session.scalars(select(Question).where(Question.run_id == run_id)
                                .order_by(Question.created_at, Question.id)))


def events(session, run_id, after=0, limit=100):
    return list(session.scalars(select(Event).where(Event.run_id == run_id, Event.id > after)
                                .order_by(Event.id).limit(limit)))


def view(run, current, *, questions_rows=(), children_rows=(), consumption=None):
    return {'id': run.id, 'root': run.root, 'status': run.status, 'reason': run.reason, 'detail': run.detail or {},
            'version': run.version, 'thread_id': run.thread_id, 'created_at': run.created_at,
            'updated_at': run.updated_at,
            'authorization': {'id': current.id, 'number': current.number, 'lineage_id': current.lineage_id,
                              'preview_sha256': current.preview_sha256, 'origin': current.origin,
                              'policy': current.policy, 'bounds': current.preview['bounds'],
                              'caps': current.preview['caps'], 'delegation': current.preview['delegation'],
                              'scope': current.preview['scope']['phases'],
                              'acknowledgement': current.preview['acknowledgement']},
            'questions': [question_view(q) for q in questions_rows],
            'children': [{'id': c.id, 'kind': c.kind, 'rule': c.rule, 'origin': c.origin,
                          'preview_sha256': c.preview_sha256, 'subject': c.subject, 'ruling_id': c.ruling_id,
                          'permission_record_id': c.permission_record_id, 'authorization_id': c.authorization_id}
                         for c in children_rows],
            'consumption': consumption or {}}


def question_view(row):
    return {'id': row.id, 'kind': row.kind, 'status': row.status, 'version': row.version, 'subject': row.subject,
            'binding': row.binding, 'answer': row.answer, 'created_at': row.created_at}


# --- G12 readiness gap records (sealed reports and owner answers) -----------------------------------------------

def gap_report(session, root, revision_id, readiness_version):
    """The sealed reviewer report of this frozen revision and classifier version, if any (reused, never regenerated)."""
    from my_harness.storage.models import AutonomousReviewRow as Gap
    return session.scalar(select(Gap).where(Gap.root == str(root), Gap.kind == 'report',
                                            Gap.record_key == f'report:{root}:{revision_id}:{readiness_version}'))


def seal_gap_report(session, *, root, project, revision, readiness_version, payload, now):
    from my_harness.storage.models import AutonomousReviewRow as Gap
    existing = gap_report(session, root, revision['id'], readiness_version)
    if existing is not None:
        return existing
    row = Gap(id=str(uuid4()), root=str(root), project_id=project, kind='report',
              record_key=f'report:{root}:{revision["id"]}:{readiness_version}', revision_id=revision['id'],
              revision_sha256=revision['sha256'], gap_sha256=None, payload=dict(payload),
              sha256=autonomy.digest(payload), origin='harness_deterministic', actor={'principal': 'harness'},
              created_at=now)
    session.add(row)
    session.flush()
    return row


def gap_answers(session, root, revision_id):
    """Current owner answers: only records bound to this exact frozen revision count."""
    from my_harness.storage.models import AutonomousReviewRow as Gap
    return list(session.scalars(select(Gap).where(Gap.root == str(root), Gap.kind == 'answer',
                                                  Gap.revision_id == revision_id).order_by(Gap.created_at, Gap.id)))


def answer_gap(session, *, root, project, revision, gap_sha256, text, key, actor, now):
    from my_harness.storage.models import AutonomousReviewRow as Gap
    payload = {'text': text, 'gap_sha256': gap_sha256, 'revision_id': revision['id']}
    existing = session.scalar(select(Gap).where(Gap.record_key == 'answer:' + key))
    if existing is not None:
        if existing.payload != payload or existing.root != str(root):
            raise refuse('idempotency_conflict')
        return existing
    row = Gap(id=str(uuid4()), root=str(root), project_id=project, kind='answer', record_key='answer:' + key,
              revision_id=revision['id'], revision_sha256=revision['sha256'], gap_sha256=gap_sha256,
              payload=payload, sha256=autonomy.digest(payload), origin='owner_confirmed', actor=dict(actor),
              created_at=now)
    session.add(row)
    session.flush()
    return row


ADOPTION_BINDING = ('preview_sha256', 'draft_id', 'coverage', 'revision_id', 'expected_version')


def verify_child(session, permissions, child_id, *, kind, root, phase=None, binding=None, adoption=None):
    """Effect-boundary check of a delegated effect (D299/D300), inside the effect's own writer transaction.

    The child must exist with this kind and an untampered subject, belong to a live run of this root under the
    lineage's latest authorization revision with an active T010 parent, and name this phase (in the sealed scope)
    and, for closure, this exact READY binding. A plan, reviewer output or ruling alone never passes."""
    child = session.get(Child, child_id) if isinstance(child_id, str) else None
    if child is None or child.kind != kind or child.origin != 'owner_delegated' \
            or child.preview_sha256 != autonomy.digest(child.subject):
        raise refuse('delegated_child_missing')
    run = session.get(Run, child.run_id)
    if run is None or run.root != str(root) or run.status in (*autonomy.TERMINAL, 'RECOVERY_REQUIRED'):
        raise refuse('delegated_run_inactive')
    auth = session.get(Authorization, run.authorization_id)
    if child.authorization_id != auth.id or latest(session, run.lineage_id).id != auth.id:
        raise refuse('delegated_child_stale')
    parent = permissions.get(session, auth.project_id, auth.permission_record_id, 'authorization')
    if not permissions.active(session, parent):
        raise refuse('delegated_authority_revoked')
    if phase is None or child.subject.get('phase') != phase or phase not in auth.preview['scope']['phases']:
        raise refuse('delegated_scope')
    if binding is not None and child.subject.get('binding_sha256') != binding:
        raise refuse('delegated_binding_stale')
    if kind == 'plan_adoption':
        # The child was sealed for one proposal, its staged draft, the exact preview and the accepted revision.
        if adoption is None or any(child.subject.get(k) != adoption.get(k) for k in ADOPTION_BINDING):
            raise refuse('delegated_adoption_mismatch')
    return {'origin': 'owner_delegated', 'child_id': child.id, 'authorization_id': auth.id, 'run_id': run.id,
            'rule': child.rule, 'ruling_id': child.ruling_id, 'parent': auth.permission_record_id,
            **({'proposal_operation_id': child.subject.get('proposal_operation_id'),
                'proposal_sha256': child.subject.get('proposal_sha256')} if kind == 'plan_adoption' else {})}


# --- observed usage and per-inference admission (D276 caps) -------------------------------------------------------

def delegated_runs(session, children):
    """Managed runs created by delegated effects: each job's idempotency key is its child's operation key."""
    from my_harness.storage.models import ManagedJobRow as Job
    keys = [c['operation_key'] for c in children if c.get('operation_key')]
    runs = {c['run_id'] for c in children if c.get('run_id')}
    if keys:
        runs |= set(session.scalars(select(Job.run_id).where(Job.idempotency_key.in_(keys))))
    return sorted(runs)


TOKEN_PARTS = ('uncached_input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens')


def observed_usage(session, runs, basis=None):
    """Attributable usage already in the ledger (no new projection): invocation count; observed tokens from the
    selected capture of each invocation (None when any is unknown); valuation on `basis` as `known`, `unknown` or
    `incompatible` (only valuations on another basis)."""
    from my_harness.storage.accounting_views import quantities
    from my_harness.storage.models import (UsageCaptureRow as Capture, UsageInvocationRow as Invocation,
                                           UsageValuationRow as Valuation)
    rows = list(session.scalars(select(Invocation).where(Invocation.run_id.in_(runs),
                                                         Invocation.launch != 'not_invoked'))) if runs else []
    tokens = 0
    for row in rows:
        capture = session.scalar(select(Capture).where(Capture.invocation_id == row.id)
                                 .order_by(Capture.id.desc()).limit(1))
        parts = [quantities(capture.evidence).get(k) for k in TOKEN_PARTS] if capture is not None else [None]
        if None in parts:
            tokens = None
            break
        tokens += sum(parts)
    valuation = None
    if basis:
        total, status = Decimal(0), 'known'
        for row in rows:
            values = list(session.scalars(select(Valuation).where(Valuation.invocation_id == row.id)
                                          .order_by(Valuation.id)))
            matching = [v for v in values if v.basis == basis and v.status == 'complete' and v.amount is not None]
            if matching:
                total += Decimal(matching[-1].amount)
                continue
            status = 'incompatible' if values and all(v.basis != basis for v in values) else 'unknown'
            break
        valuation = {'status': status, 'basis': basis, 'amount': str(total) if status == 'known' else None}
    return {'invocations': len(rows), 'tokens': tokens, 'valuation': valuation}


def admission_check(session, managed, managed_run):
    """Inside the attempt-start transaction: the stop for a new delegated inference, or None (manual runs).

    Authority (the child under the lineage's latest authorization and an active T010 parent), a RUNNING autonomous
    run (a pause holds new inferences; revocation or recovery ends them) and the caps over the ledger are all read
    in this transaction. `kind` separates authority and state refusals from cap limits."""
    from my_harness.services.permission_lifecycle import PermissionLifecycle
    from my_harness.storage.models import ManagedJobRow as Job
    keys = list(session.scalars(select(Job.idempotency_key).where(Job.run_id == managed_run.id)))
    child = session.scalar(select(Child).where(Child.operation_key.in_(keys))) if keys else None
    if child is None:
        return None
    run = session.get(Run, child.run_id)
    auth = authorization(session, run.authorization_id)
    permissions = getattr(managed, 'permission_lifecycle', None) or PermissionLifecycle(managed.engine)
    parent = permissions.get(session, auth.project_id, auth.permission_record_id, 'authorization')
    if run.status in (*autonomy.TERMINAL, 'RECOVERY_REQUIRED'):
        return {'kind': 'authority', 'reason': 'authority_inactive', 'run_status': run.status}
    if child.authorization_id != auth.id or latest(session, run.lineage_id).id != auth.id:
        return {'kind': 'authority', 'reason': 'delegated_child_stale'}
    if not permissions.active(session, parent):
        return {'kind': 'authority', 'reason': 'delegated_authority_revoked'}
    if run.status != 'RUNNING':
        return {'kind': 'state', 'reason': 'run_not_running', 'run_status': run.status}
    caps = auth.preview['caps']
    runs = delegated_runs(session, [{**c.subject, 'operation_key': c.operation_key} for c in children(session, run.id)])
    usage = observed_usage(session, runs, (caps.get('valuation') or {}).get('basis'))
    stop = autonomy.cap_stop(caps, usage, managed._now())
    return {'kind': 'cap', **stop} if stop else None


def admission_refusal(session, run_id):
    """The cap or authority stop recorded for a delegated managed run, if its inference was refused."""
    from my_harness.storage.models import ManagedEventRow
    payload = session.scalar(select(ManagedEventRow.payload).where(
        ManagedEventRow.run_id == run_id, ManagedEventRow.kind == 'autonomy_admission_refused')
        .order_by(ManagedEventRow.sequence.desc()).limit(1)) if run_id else None
    return payload['stop'] if payload else None



# --- effect-boundary checks inside T014's own transactions (P002-T016 review) -----------------------------------

def admission_child(session, managed_run_id):
    """The `task_admission` child whose operation key queued this managed run (its first job), or None."""
    from my_harness.storage.models import ManagedJobRow as Job
    keys = list(session.scalars(select(Job.idempotency_key).where(Job.run_id == managed_run_id)))
    return session.scalar(select(Child).where(Child.operation_key.in_(keys), Child.kind == 'task_admission')) \
        if keys else None


def _frozen_contract_sha256(session, managed_run_id):
    """Digest of the contract T014 froze for a delegated run (`task_delegated` evidence), or None."""
    import json
    from my_harness.storage.models import ManagedEventRow
    binding = session.scalar(select(ManagedEventRow.payload).where(
        ManagedEventRow.run_id == managed_run_id, ManagedEventRow.kind == 'task_delegated'))
    return autonomy.digest(json.loads(binding['contract_json'])) if binding else None


def verify_task_admission(session, permissions, child_id, *, root, phase, task, request, identity):
    """Inside T014's queue transaction, before a run or job exists: the sealed admission child for this phase and
    task under live authority, the task-child permission it names, the digest of the exact contract T014 will freeze
    and the contract identity computed from the accepted knowledge read in this same transaction."""
    import json
    provenance = verify_child(session, permissions, child_id, kind='task_admission', root=root, phase=phase)
    child = session.get(Child, child_id)
    if (child.subject.get('task') != task or request.get('task_id') != task or request.get('phase_id') != phase
            or request.get('delegated_authorization') != child.permission_record_id):
        raise refuse('delegated_scope')
    contract = request.get('contract_json')
    if contract is None or autonomy.digest(json.loads(contract)) != child.subject.get('contract_sha256'):
        raise refuse('task_contract_mismatch')
    if identity is None or child.subject.get('version_sha256') != identity:
        raise refuse('task_contract_stale', expected=child.subject.get('version_sha256'), current=identity)
    return provenance


def verify_task_commit(session, permissions, child_id, *, root, phase, task, managed_run, identity):
    """Inside T014's commit-queue transaction: the sealed commit child under live authority, an acceptance produced
    by a run this same autonomous run admitted for this phase and task, with its frozen contract, active task-child
    authority, and the contract identity of the accepted knowledge read in this transaction."""
    verify_child(session, permissions, child_id, kind='task_commit', root=root, phase=phase)
    commit = session.get(Child, child_id)
    admission = admission_child(session, managed_run.id)
    if (admission is None or admission.run_id != commit.run_id or admission.subject.get('task') != task
            or admission.subject.get('phase') != phase or managed_run.task_id != task
            or managed_run.phase_id != phase or commit.subject.get('run_id') != managed_run.id
            or _frozen_contract_sha256(session, managed_run.id) != admission.subject.get('contract_sha256')):
        raise refuse('acceptance_not_delegated')
    if identity is None or admission.subject.get('version_sha256') != identity \
            or commit.subject.get('version_sha256') != identity:
        raise refuse('acceptance_identity_stale', expected=admission.subject.get('version_sha256'), current=identity)
    if permissions.delegated_inactive(session, managed_run.id):
        raise refuse('delegated_authority_revoked')
    return admission


def held_review(session, managed_run):
    """Persisted evidence that a non-RUNNING autonomous run (an owner pause) held the reviewer of a delegated task
    run after its executor finished: the run STOPPED at the reviewer by a `state` admission refusal of its latest
    job, every attempt settled, and the executor's content evidence frozen in the last review cycle without a
    review. None for every other stop."""
    from my_harness.core.engine.serialization import load_history
    from my_harness.storage.models import ManagedEventRow, ManagedJobRow as Job
    if managed_run is None or managed_run.purpose != 'task' or managed_run.status != 'STOPPED':
        return None
    refusal = session.scalar(select(ManagedEventRow).where(
        ManagedEventRow.run_id == managed_run.id, ManagedEventRow.kind == 'autonomy_admission_refused')
        .order_by(ManagedEventRow.sequence.desc()).limit(1))
    job = session.scalar(select(Job).where(Job.run_id == managed_run.id).order_by(Job.id.desc()).limit(1))
    if (refusal is None or job is None or job.status != 'DONE' or refusal.payload.get('job_id') != job.id
            or refusal.payload.get('role') != 'reviewer' or (refusal.payload.get('stop') or {}).get('kind') != 'state'):
        return None
    history = load_history(managed_run.history_json)
    if (history.status != 'stopped' or history.stop is None or history.stop.stage != 'reviewer'
            or not history.cycles or history.cycles[-1].review_json is not None or history.task_json is None
            or not history.attempts or history.attempts[-1].request.role != 'executor'):
        return None
    evidence = history.cycles[-1].evidence
    return {'run_id': managed_run.id, 'version': managed_run.version, 'job_id': job.id,
            'refusal_event_id': refusal.id, 'cycle': history.cycles[-1].number,
            'evidence': {'base_revision': evidence.base_revision, 'fingerprint': evidence.fingerprint,
                         'changed_paths': list(evidence.changed_paths)}}


def verify_held_review(session, permissions, managed_run, *, root, held, identity, checkout, running=False):
    """Before the explicit continuation of a held review (and again inside T014's resume transaction, `running`):
    the same held evidence, a run admitted by the active autonomous run of this root under its latest authorization
    with a live parent and task-child authority, the frozen contract the child sealed, the current contract
    identity, a settled writer and a checkout whose evidence is exactly the executor's work under review."""
    from my_harness.storage.models import ManagedJobRow as Job
    current = held_review(session, managed_run)
    if current is None or held is None or any(current[k] != held.get(k) for k in
                                              ('run_id', 'version', 'job_id', 'refusal_event_id', 'evidence')):
        raise refuse('held_review_stale')
    admission = admission_child(session, managed_run.id)
    if admission is None:
        raise refuse('held_review_not_delegated')
    verify_child(session, permissions, admission.id, kind='task_admission', root=root,
                 phase=admission.subject.get('phase'))
    run, active = session.get(Run, admission.run_id), active_run(session, root)
    if active is None or active.id != run.id or (running and run.status != 'RUNNING') \
            or admission.subject.get('task') != managed_run.task_id \
            or admission.subject.get('phase') != managed_run.phase_id:
        raise refuse('held_review_not_delegated')
    if _frozen_contract_sha256(session, managed_run.id) != admission.subject.get('contract_sha256'):
        raise refuse('task_contract_mismatch')
    if identity is None or admission.subject.get('version_sha256') != identity:
        raise refuse('task_contract_stale', expected=admission.subject.get('version_sha256'), current=identity)
    if permissions.delegated_inactive(session, managed_run.id):
        raise refuse('delegated_authority_revoked')
    if session.scalar(select(Job.id).where(Job.run_id == managed_run.id,
                                           Job.status.in_(('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED')))) is not None:
        raise refuse('writer_not_settled')
    expected = held['evidence']
    if checkout is None or any(checkout.get(k) != expected[k] for k in ('base_revision', 'fingerprint', 'changed_paths')):
        raise refuse('held_review_checkout_mismatch')
    return admission


def continuation_refused(managed_run):
    """True when T014's bound continuation of a held review stopped because its effective capture was not the
    executor evidence it was authorized for (stop stage `continuation`); the files are left for the owner."""
    from my_harness.core.engine.serialization import load_history
    if managed_run is None or managed_run.status != 'STOPPED':
        return False
    history = load_history(managed_run.history_json)
    return history.stop is not None and history.stop.stage == 'continuation'
