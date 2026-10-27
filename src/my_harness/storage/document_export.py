"""Documentary export over existing phase operations and jobs; SQLite is the authority."""
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.commit import CommitIntent
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.document_export import preview as build_preview
from my_harness.core.engine.phases import document_hashes
from my_harness.storage import run_projection
from my_harness.storage.managed import Conflict, _job
from my_harness.storage.models import ManagedJobRow as Job, ManagedRunRow as Run, RunProjectionRow as Projection
from my_harness.storage.models import PhaseOperationRow as Operation, PhaseRow as Phase
from my_harness.storage.permissions import actor
from my_harness.storage.phases import (
    PhaseRepository, _event, _latest, _open, _operation, _questions, committed_tasks,
)
from my_harness.core.engine.serialization import load_history
from my_harness.i18n import tr


def _acceptance(session, run_id, projected):
    if projected:
        run_projection.require(session, [run_id])
        accepted = session.scalar(select(Projection.acceptance_json).where(Projection.run_id == run_id))
        return json.loads(accepted)['eligible'] if accepted is not None else None
    history = load_history(session.scalar(select(Run.history_json).where(Run.id == run_id)))
    return history.acceptance.eligible if history.acceptance else None


def snapshot(session, phase, context=None, *, projected=False):
    """D036 shape (JSON) or, with the D072 layout, the readable projection of the managed blocks.

    `projected`: only the preview reads the `run-projection-1` projection (P010-T011). The submission, the job request
    and the intent recompute from the history and require the same result that was reviewed."""
    from my_harness.core.engine.documents import layout
    if context is not None and layout(context) is not None:
        from my_harness.storage.documents import phases_snapshot, state_snapshot
        return {'layout': 'v2', 'state': state_snapshot(session, phase, projected=projected),
                'phases': phases_snapshot(session, phase.root)}
    tasks = {}
    committed = committed_tasks(session, phase)
    for task in sorted(phase.definition['tasks']):
        run = session.execute(select(Run.id, Run.status).where(
            Run.root == phase.root, Run.phase_id == phase.code, Run.task_id == task, Run.purpose == 'task')
            .order_by(Run.created_at.desc(), Run.id).limit(1)).first()
        tasks[task] = {'run_id': run.id if run else None, 'status': run.status if run else None,
                       'acceptance': _acceptance(session, run.id, projected) if run else None,
                       'commit': committed[task]['commit'] if committed[task] else None,
                       'committed_run_id': committed[task]['run_id'] if committed[task] else None}
    check = _latest(session, phase.id, 'check')
    from my_harness.storage.models import PhaseAuthorizationRow as Authorization
    batches = session.scalars(select(Authorization).where(Authorization.phase_id == phase.id,
                              Authorization.kind == 'batch').order_by(Authorization.created_at, Authorization.id)).all()
    return {'phase': {'id': phase.id, 'code': phase.code, 'status': phase.status,
                      'definition_sha256': phase.definition_sha256}, 'tasks': tasks,
            'open_questions': [{'id': q.id, 'text': q.text} for q in _open(_questions(session, phase.id))],
            'latest_check': None if check is None else {'id': check.id, 'status': check.status, 'result': check.result},
            'batches': [{'id': a.id, 'status': a.status, 'tasks': a.scope['tasks'], 'expires_at': a.expires_at,
                         'closed': a.closed} for a in batches]}


def _phase(session, context, phase_id, expected=None):
    phase = session.get(Phase, phase_id)
    if phase is None or phase.root != str(context.root):
        raise LookupError(tr('export.unknown_phase_checkout'))
    if expected is not None and (type(expected) is not int or phase.version != expected):
        raise Conflict(tr('export.phase_changed_reload_before'))
    latest = session.scalar(select(Phase.id).where(Phase.root == phase.root)
                            .order_by(Phase.created_at.desc(), Phase.id.desc()).limit(1))
    if latest != phase.id:
        raise Conflict(tr('export.latest_phase_checkout_export'))
    if PhaseRepository._root_pending(session, phase.root) or phase.status in ('CHECKING', 'CLOSING'):
        raise Conflict(tr('export.checkout_has_unfinished_jobs'))
    from my_harness.storage.models import PhaseAuthorizationRow as Authorization
    if session.scalar(select(Authorization.id).where(Authorization.phase_id == phase.id,
                      Authorization.kind == 'batch', Authorization.status == 'ACTIVE')):
        raise Conflict(tr('export.revoke_active_batch_before'))
    return phase


def _pending(session, phase):
    rows = session.scalars(select(Operation).where(Operation.phase_id == phase.id, Operation.kind == 'document_export',
                          Operation.status == 'INTERRUPTED', Operation.finished_at.is_not(None))
                          .order_by(Operation.created_at.desc(), Operation.id)).all()
    return next((op for op in rows if op.request.get('commit_intent')), None)


def unresolved(session, root):
    """An uncertain intent keeps its authority until reconciliation; includes the D072 operations."""
    from my_harness.storage.documents import unresolved as documents_unresolved
    return documents_unresolved(session, root)


class DocumentExportRepository:
    def __init__(self, managed):
        self.managed = managed

    def preview(self, context, phase_id, git):
        with Session(self.managed.engine) as session:
            phase = _phase(session, context, phase_id)
            pending = _pending(session, phase)
            if pending is not None and pending.request.get('commit_intent'):
                return {**pending.request['preview'], 'expected_version': phase.version, 'resume_operation_id': pending.id}
            state, baseline = snapshot(session, phase, context, projected=True), dict(phase.documents)
            version = phase.version
        try:
            shown = build_preview(context, state, baseline, git)
        except (ValueError, OSError, UnicodeError) as exc:
            raise Conflict(str(exc)) from exc
        return {**shown, 'expected_version': version, 'resume_operation_id': None}

    def submit(self, context, phase_id, expected, *, key, versions, preview_sha256, reason, confirmed, git,
               resume_operation_id=None):
        if confirmed is not True or not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('export.explicit_confirmation_exact_diff'))
        marker = freeze({'action': 'document_export', 'phase_id': phase_id, 'expected_version': expected,
                         'preview_sha256': preview_sha256, 'reason': reason, 'confirmed': confirmed,
                         'resume_operation_id': resume_operation_id})
        # Idempotency before rereading disk: the confirmed submission is still the same after the effect.
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
        try:
            shown = self.preview(context, phase_id, git)
        except Conflict:
            # Another identical submission may confirm between the first read and the preview.
            with Session(self.managed.engine) as session:
                existing = self.managed._existing(session, key, marker)
                if existing:
                    return _job(existing)
            raise
        if shown['preview_sha256'] != preview_sha256 or shown['resume_operation_id'] != resume_operation_id:
            raise Conflict(tr('export.preview_changed_review_exact'))
        if not shown['mechanical']:
            raise Conflict(tr('export.mechanical_blocks_already_match'))
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
            phase = _phase(session, context, phase_id, expected)
            if shown['expected_version'] != expected:
                raise Conflict(tr('export.phase_changed_since_preview'))
            if resume_operation_id is not None:
                op = _pending(session, phase)
                if op is None or op.id != resume_operation_id or not op.request.get('commit_intent'):
                    raise Conflict(tr('export.exact_interrupted_export_intent'))
                run = session.get(Run, op.run_id)
                from my_harness.core.engine.contracts import context_snapshot
                if run.context_json != context_snapshot(context) or run.versions_json != freeze(versions):
                    raise Conflict(tr('export.frozen_export_context_versions'))
                job = Job(idempotency_key=key, run_id=run.id, request_json=marker, status='QUEUED',
                          created_at=self.managed._now(), activation_id=self.managed._admit(session, assessment),
                          language_context=self.managed._language(session, run.id))
                session.add(job)
                session.flush()
                run.status, run.stage = 'QUEUED', 'document_export'
                self.managed._event(session, run, 'job_queued', {'job_id': job.id, 'action': 'document_export'})
                job = _job(job)
                op.status, op.finished_at = 'QUEUED', None
            else:
                if snapshot(session, phase, context) != shown['snapshot'] or phase.documents != shown['baseline']:
                    raise Conflict(tr('export.sqlite_authority_changed_after_2'))
                job = self.managed._queue_new_run(session, assessment, context, versions, f'{phase.code}-EXPORT',
                                                  phase.code, key, marker, purpose='document_export')
                saved = {k: v for k, v in shown.items() if k not in ('expected_version', 'resume_operation_id')}
                op = Operation(id=str(uuid4()), phase_id=phase.id, kind='document_export', run_id=job.run_id,
                               status='QUEUED', previous_status=phase.status,
                               request={'preview': saved, 'actor': actor(), 'reason': reason},
                               created_at=self.managed._now())
                session.add(op)
            _event(self.managed, session, phase, 'document_export_queued', {
                'operation_id': op.id, 'run_id': job.run_id, 'job_id': job.id, 'preview_sha256': preview_sha256,
                'actor': actor(), 'reason': reason})
            return job

    def request(self, run_id):
        with Session(self.managed.engine) as session:
            run = session.get(Run, run_id)
            op, phase = _operation(session, run)
            if op.kind != 'document_export' or op.status != 'QUEUED':
                raise Conflict('Export requires its queued operation')
            # Before the first effect, all SQLite authority must still match the approved snapshot.
            from my_harness.core.engine.serialization import restore_context
            frozen = restore_context(run.context_json)
            if not op.request.get('commit_intent') and snapshot(session, phase, frozen) != op.request['preview']['snapshot']:
                raise Conflict(tr('export.sqlite_authority_changed_after'))
            return {**op.request, 'operation_id': op.id}


def record_intent(managed, session, run, intent):
    op, phase = _operation(session, run)
    shown = op.request['preview']
    from my_harness.core.engine.serialization import restore_context
    if (op.kind != 'document_export' or op.status != 'QUEUED' or intent.operation_id != op.id
            or intent.run_id != run.id or snapshot(session, phase, restore_context(run.context_json)) != shown['snapshot']):
        raise Conflict('Export intent must match its exact reviewed SQLite snapshot')
    op.request = {**op.request, 'commit_intent': intent.to_json()}
    op.status = 'INTENT'
    _event(managed, session, phase, 'document_export_intent', {
        'operation_id': op.id, 'expected_commit': intent.expected_commit, 'expected_tree': intent.expected_tree})


def settle(managed, session, run, outcome):
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        raise Conflict('Export operation already settled')
    if outcome['status'] == 'COMMITTED':
        intent = CommitIntent.from_json(op.request['commit_intent'])
        if outcome['commit'] != intent.expected_commit or outcome['tree'] != intent.expected_tree:
            raise Conflict('Export result differs from its sealed intent')
        from my_harness.core.engine.serialization import restore_context
        context = restore_context(run.context_json)
        observed = document_hashes(context, phase.definition['documents'])
        expected = {**op.request['preview']['baseline'], **{
            d['path']: d['after_sha256'] for d in op.request['preview']['documents']}}
        if observed != expected or phase.documents != op.request['preview']['baseline']:
            raise Conflict(tr('export.documents_changed_after_export'))
        phase.documents = observed
        # READY keeps its historical evaluation; its hashes/HEAD no longer certify the closure.
        # The next closure gate observes the drift and invalidates it, as in H3.3.
        run.status, run.stage = 'COMMITTED', 'committed'
    op.status, op.result, op.finished_at = outcome['status'], outcome, managed._now()
    _event(managed, session, phase, 'documents_exported' if outcome['status'] == 'COMMITTED' else 'document_export_invalidated',
           {'operation_id': op.id, **outcome, 'documents': phase.documents})


def abort(managed, session, run, status, reason):
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        return
    op.status, op.result, op.finished_at = status, {'reason': reason}, managed._now()
    _event(managed, session, phase, 'document_export_aborted', {'operation_id': op.id, 'status': status, 'reason': reason})
