"""H3.3/H3.4: SQLite authority of phases, serialized with the managed queue.

Disk reads (documents) happen outside a transaction and are compared by
hash; checks and closures are jobs under the checkout lock. Batch and closure
authorizations are distinct, explicit and audited rows: neither implies the other, and
H3.2 permission grants play no part. No history is rewritten.

H3.4 (D033): a batch may explicitly authorize chaining tasks and confirming
the commit of each eligible acceptance; the supervisor drives it step by step with deterministic
keys and stops at the first blocker. Definitions are amended as
new versions, the phase can be abandoned and reconciliation with an agent is a
normal task with a deterministic contract limited to the phase documents.
"""

from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import context_snapshot, freeze
from my_harness.core.engine.document_text import work_language, words
from my_harness.core.engine.phases import CHECK_STATUS, TAG_KINDS, digest, document_hashes, phase_definition
from my_harness.core.engine.serialization import load_history, restore_context
from my_harness.storage.managed import Conflict, _job
from my_harness.storage.models import (
    ManagedCommitRow as Commit, ManagedJobRow as Job, ManagedRunRow as Run, PhaseAuthorizationRow as Authorization,
    PhaseDefinitionRow as Definition, PhaseEventRow as PhaseEvent, PhaseOperationRow as Operation,
    PhaseQuestionRow as Question, PhaseRow as Phase,
)
from my_harness.storage.permissions import actor
from my_harness.i18n import tr

PENDING = ('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED')
CHECKABLE = ('ACTIVE', 'NEEDS_RECONCILIATION', 'READY_TO_CLOSE', 'BLOCKED')
RECONCILABLE = CHECKABLE
# Amend or abandon: never with a check/closure in progress or on a terminal phase.
AMENDABLE = CHECKABLE
TERMINAL = ('CLOSED', 'ABANDONED')
# Task run that ended without a confirmable acceptance: it does not block another reconciliation task.
FAILED_RUN = ('STOPPED', 'BLOCKED', 'REVISION_LIMIT', 'INTERRUPTED', 'REFUSED')
# Parts of an unattended batch scope that are not projected (large or internal content).
HIDDEN_SCOPE = ('text', 'context_json', 'versions_json')


def _event(managed, session, phase, kind, payload):
    phase.version += 1
    phase.updated_at = managed._now()
    session.add(PhaseEvent(phase_id=phase.id, sequence=phase.version, kind=kind, recorded_at=phase.updated_at,
                           payload={**payload, 'status': phase.status}))


def _questions(session, phase_id):
    return session.scalars(select(Question).where(Question.phase_id == phase_id)
                           .order_by(Question.created_at, Question.id)).all()


def _open(rows):
    return [row for row in rows if row.status == 'OPEN']


def committed_tasks(session, phase):
    """Last COMMITTED acceptance of each declared task, only task runs of this checkout and phase."""
    result = {}
    for task in phase.definition['tasks']:
        row = session.execute(select(Commit.run_id, Commit.commit_sha).join(Run, Run.id == Commit.run_id).where(
            Run.root == phase.root, Run.phase_id == phase.code, Run.task_id == task, Run.purpose == 'task',
            Commit.status == 'COMMITTED').order_by(Commit.finished_at.desc(), Commit.operation_id).limit(1)).first()
        result[task] = None if row is None else {'run_id': row.run_id, 'commit': row.commit_sha}
    return result


def _decision_proposals(session, tasks):
    """D088 point 2 (P008-T003): reviewer ADR proposals in the last review of each COMMITTED task,
    to consolidate them in the reconciliation. They never write DECISIONS by themselves."""
    result = {}
    for task, item in tasks.items():
        if item is None:
            continue
        cycles = load_history(session.get(Run, item['run_id']).history_json).cycles
        review = json.loads(cycles[-1].review_json) if cycles and cycles[-1].review_json else {}
        if review.get('decision_proposals'):
            result[task] = review['decision_proposals']
    return result


def authority(session, phase):
    """Parts of the READY binding that live in SQLite."""
    rows = _questions(session, phase.id)
    sha = digest([[q.id, q.status, q.text, q.answer['text'] if q.answer else None] for q in rows])
    return {'definition_sha256': phase.definition_sha256, 'tasks': committed_tasks(session, phase),
            'questions_sha256': sha}, rows


def stale_reasons(parts, bound):
    return [tr('phases.part_changed_ready', part=key) for key in sorted(parts) if parts[key] != bound.get(key)]


def _latest(session, phase_id, kind):
    return session.scalar(select(Operation).where(Operation.phase_id == phase_id, Operation.kind == kind)
                          .order_by(Operation.created_at.desc(), Operation.id.desc()).limit(1))


def _ready(session, phase):
    """Current READY: the last check, while the phase stays in READY_TO_CLOSE/CLOSING."""
    if phase.status not in ('READY_TO_CLOSE', 'CLOSING'):
        return None
    check = _latest(session, phase.id, 'check')
    return check if check is not None and check.status == 'READY' else None


def question_view(row):
    return {key: getattr(row, key) for key in ('id', 'text', 'source', 'status', 'answer', 'version', 'created_at')}


def operation_view(row):
    return {key: getattr(row, key) for key in ('id', 'kind', 'run_id', 'status', 'previous_status', 'request',
                                                 'result', 'created_at', 'finished_at')}


def authorization_view(row, now, tasks=None):
    data = {key: getattr(row, key) for key in ('id', 'kind', 'status', 'scope', 'fingerprint', 'actor', 'reason',
                                                 'expires_at', 'created_at', 'closed', 'version')}
    data['scope'] = {key: value for key, value in row.scope.items() if key not in HIDDEN_SCOPE}
    effective = row.status
    if row.status == 'ACTIVE' and row.expires_at <= now:
        effective = 'EXPIRED'
    elif row.status == 'ACTIVE' and row.kind == 'batch' and tasks is not None and all(
            tasks.get(task) is not None for task in row.scope['tasks']):
        effective = 'COMPLETE'
    return {**data, 'effective_status': effective}


def definition_view(row):
    return {key: getattr(row, key) for key in ('number', 'definition', 'definition_sha256', 'documents', 'origin',
                                                 'reason', 'actor', 'created_at')}


CONFIRMED_DOCUMENT_KINDS = ('document_edit', 'document_export')


def _closure(session, phase):
    """Operation that ended the phase (closure or abandonment); None if open or closed without a recorded operation."""
    if phase.status not in TERMINAL:
        return None
    return session.scalar(select(Operation).where(
        Operation.phase_id == phase.id, Operation.kind == 'close', Operation.status == phase.status)
        .order_by(Operation.created_at.desc(), Operation.id.desc()).limit(1))


def closure_files(session, phase) -> dict[str, str | None]:
    """Hashes the unified closure wrote into the phase archive (D088)."""
    op = _closure(session, phase)
    shown = (op.request.get('preview') or {}) if op is not None else {}
    archive = shown.get('archive')
    return {} if not archive else {doc['path']: doc['after_sha256'] for doc in shown['documents']
                                    if doc['path'].startswith(archive + '/')}


def expected_documents(session, phase) -> dict[str, str | None]:
    """P010-T005: adopted base plus what the closure and the confirmed edits after it wrote.

    Presentation only: does not change `phase.documents`, the READY or what a check verifies."""
    expected = dict(phase.documents)
    op = _closure(session, phase)
    if op is None or not op.request.get('preview'):
        return expected
    for doc in op.request['preview']['documents']:
        if doc['path'] in expected:
            expected[doc['path']] = doc['after_sha256']
    later = session.scalars(select(Operation).where(
        Operation.phase_id == phase.id, Operation.kind.in_(CONFIRMED_DOCUMENT_KINDS), Operation.status == 'COMMITTED',
        Operation.created_at > op.created_at).order_by(Operation.created_at, Operation.id)).all()
    for row in later:
        for doc in row.request['preview']['documents']:
            if doc['path'] in expected and expected[doc['path']] == doc['before_sha256']:
                expected[doc['path']] = doc['after_sha256']
    return expected


def closure_view(session, phase, current_documents, archive_documents, successor):
    """Historical evidence of a finished phase and classification of its live documents and its archive.

    `renewed`: expected differences from the adopted base (closure and later confirmed edits).
    `changed`: live documents that do not match what is expected, only without a successor (with one, they are its).
    `archive_altered`: archive files whose content on disk is no longer what the closure wrote."""
    op = _closure(session, phase)
    if op is None:
        return None
    result, request = op.result or {}, op.request
    # Closures before D088 have no sealed preview: they show check and base, without an archive.
    check = session.get(Operation, request['check_operation_id']) if request.get('check_operation_id') else None
    review = (check.result or {}).get('result') if check is not None else None
    auth = session.get(Authorization, request['authorization_id']) if request.get('authorization_id') else None
    bound = request.get('binding') or {}
    expected = expected_documents(session, phase)
    files = closure_files(session, phase)
    return {
        'operation_id': op.id, 'status': op.status, 'finished_at': op.finished_at,
        'actor': auth.actor if auth else None, 'reason': auth.reason if auth else None,
        'commit': result.get('commit'), 'tag': result.get('tag'), 'archive': result.get('archive'),
        'check': None if check is None else {
            'operation_id': check.id, 'verdict': check.status, 'finished_at': check.finished_at,
            'summary': (review or {}).get('summary'),
            'exit_criteria_results': (review or {}).get('exit_criteria_results') or []},
        'binding': {'head': bound.get('head'), 'binding_sha256': request.get('binding_sha256'),
                    'documents': bound.get('documents')},
        'documents': expected,
        'renewed': sorted(path for path, value in expected.items() if phase.documents.get(path) != value),
        'changed': (None if current_documents is None or successor is not None
                    else sorted(path for path, value in current_documents.items() if expected.get(path) != value)),
        'archive_files': sorted(files),
        'archive_altered': (None if archive_documents is None
                            else sorted(path for path, value in files.items() if archive_documents.get(path) != value)),
    }


def _invalidate_batches(managed, session, phase, reason):
    """An amendment or an abandonment invalidates the current batches; finished ones are kept."""
    rows = session.scalars(select(Authorization).where(Authorization.phase_id == phase.id,
                           Authorization.kind == 'batch', Authorization.status == 'ACTIVE')).all()
    for row in rows:
        row.status, row.version = 'INVALIDATED', row.version + 1
        row.closed = {'at': managed._now(), 'actor': actor(), 'reason': reason}
    return [row.id for row in rows]


def _open_reconcile_task(session, phase):
    """Reconciliation task in progress, pending commit or adoption (one at a time)."""
    op = _latest(session, phase.id, 'reconcile_task')
    if op is None or op.status != 'QUEUED':
        return None
    return None if session.get(Run, op.run_id).status in FAILED_RUN else op


def _operation(session, run):
    op = session.scalar(select(Operation).where(Operation.run_id == run.id))
    if op is None:
        raise Conflict('Phase run without its phase operation')
    return op, session.get(Phase, op.phase_id)


def _invalidate(managed, session, phase, op, status, reason):
    auth = session.get(Authorization, op.request['authorization_id'])
    if auth.status == 'ACTIVE':
        auth.status, auth.version = status, auth.version + 1
        auth.closed = {'at': managed._now(), 'operation_id': op.id, 'reason': reason}


def settle(managed, session, run, outcome):
    """Check/closure result, atomic with the end of the job (called from `finish`)."""
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        raise Conflict('Phase operation already settled')
    now = managed._now()
    parts, rows = authority(session, phase)
    if op.kind == 'check':
        outcome = dict(outcome)
        if outcome['verdict'] == 'READY' and stale_reasons(parts, outcome['binding']):
            outcome.update(verdict='NOT_READY', binding=None, binding_sha256=None,
                           reasons=[tr('phases.authority_changed_check',
                                       reasons=', '.join(stale_reasons(parts, outcome['binding'])))])
        attempt = load_history(run.history_json).attempts
        for text in outcome['questions']:
            session.add(Question(id=str(uuid4()), phase_id=phase.id, text=text.strip(), status='OPEN', answer=None,
                                 version=1, created_at=now, source={
                                     'kind': 'phase_check', 'operation_id': op.id, 'run_id': run.id,
                                     'attempt_id': attempt[-1].request.id if attempt else None}))
        session.flush()
        op.status, op.result, op.finished_at = outcome['verdict'], outcome, now
        phase.status = CHECK_STATUS.get(outcome['verdict'], op.previous_status)
        if _open(_questions(session, phase.id)):
            phase.status = 'BLOCKED'
        _event(managed, session, phase, 'phase_checked', {'operation_id': op.id, 'run_id': run.id,
               'verdict': outcome['verdict'], 'reasons': outcome['reasons'],
               'binding_sha256': outcome['binding_sha256'], 'questions': outcome['questions']})
        return
    op.result, op.finished_at = outcome, now
    if outcome['status'] in ('CLOSED', 'ABANDONED'):
        # Questions and commits are excluded during CLOSING; a change here requires manual recovery.
        changed = stale_reasons(parts, op.request['binding'])
        if changed or (outcome['status'] == 'CLOSED' and _open(rows)):
            raise Conflict(tr('phases.phase_authority_changed_during'))
        auth = session.get(Authorization, op.request['authorization_id'])
        auth.status, auth.version = 'CONSUMED', auth.version + 1
        auth.closed = {'at': now, 'operation_id': op.id, 'reason': tr('phases.closed_reason')}
        terminal = outcome['status']
        if op.request.get('preview'):
            from my_harness.storage.closure import adopt
            outcome = adopt(managed, session, run, op, phase, outcome)
            op.result = outcome
        op.status, phase.status = terminal, terminal
        _event(managed, session, phase, 'phase_abandoned' if terminal == 'ABANDONED' else 'phase_closed', {
               'operation_id': op.id, 'run_id': run.id,
               'tag': outcome['tag'], 'binding_sha256': outcome['binding_sha256'],
               **({'archive': outcome['archive'], 'commit': outcome['commit']} if outcome.get('archive') else {})})
    elif outcome['status'] == 'STALE':
        _invalidate(managed, session, phase, op, 'INVALIDATED', tr('phases.ready_evidence_stale'))
        op.status, phase.status = 'STALE', 'NEEDS_RECONCILIATION'
        _event(managed, session, phase, 'ready_invalidated', {'operation_id': op.id, 'reasons': outcome['reasons']})
    else:
        _invalidate(managed, session, phase, op, 'INVALIDATED', '; '.join(outcome['reasons']))
        op.status, phase.status = outcome['status'], op.previous_status
        _event(managed, session, phase, 'phase_close_failed', {'operation_id': op.id, 'status': outcome['status'],
               'reasons': outcome['reasons']})


def abort(managed, session, run, status, reason):
    """Refused job or writer confirmed stopped: no effects repeated; the tag is left to reconcile."""
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        return
    intent = op.request.get('tag_intent')
    op.result = {'reason': reason, **({'tag_effect': 'uncertain', 'tag_intent': intent} if intent else {})}
    op.status, op.finished_at = status, managed._now()
    if op.kind == 'close':
        _invalidate(managed, session, phase, op, 'INVALIDATED',
                    tr('phases.close_ended', status=status.lower(), reason=reason))
    phase.status = 'BLOCKED' if _open(_questions(session, phase.id)) else op.previous_status
    _event(managed, session, phase, 'phase_operation_aborted', {
        'operation_id': op.id, 'kind': op.kind, 'status': status, 'reason': reason, 'tag_intent': intent})


def record_tag_intent(managed, session, run, intent):
    op, phase = _operation(session, run)
    if op.kind != 'close' or op.status not in ('QUEUED', 'INTENT') or intent['operation_id'] != op.id:
        raise Conflict('Tag intent requires its queued close operation')
    op.request = {**op.request, 'tag_intent': intent}
    op.status = 'INTENT'
    _event(managed, session, phase, 'phase_tag_intent', {'operation_id': op.id, **intent})


def record_intent(managed, session, run, intent):
    from my_harness.storage.documents import record_operation_intent
    record_operation_intent(managed, session, run, intent, 'close', lambda session, phase: phase.status == 'CLOSING')


def insert_phase(managed, session, root, definition, documents, source=None):
    """Shared insertion: normal creation and bootstrap adoption in the job's transaction."""
    now = managed._now()
    phase = Phase(id=str(uuid4()), root=root, code=definition['code'], definition=definition,
                  definition_sha256=digest(definition), documents=documents, status='ACTIVE', version=0,
                  created_at=now, updated_at=now, definition_number=1)
    session.add(phase)
    session.flush()
    session.add(Definition(id=str(uuid4()), phase_id=phase.id, number=1, definition=definition,
                           definition_sha256=phase.definition_sha256, documents=documents, origin='created',
                           reason=None, actor=actor(), created_at=now))
    _event(managed, session, phase, 'phase_created', {
        'definition_sha256': phase.definition_sha256, 'documents': documents, 'actor': actor(),
        **({'source': source} if source else {})})
    return phase.id


class PhaseRepository:
    def __init__(self, managed):
        self.managed = managed

    def _phase(self, session, phase_id, expected, context=None, *, resume_close=False):
        phase = session.get(Phase, phase_id)
        if phase is None:
            raise LookupError(tr('phases.unknown_managed_phase'))
        if context is not None and str(context.root) != phase.root:
            raise LookupError(tr('phases.phase_belongs_another_checkout'))
        if type(expected) is not int or phase.version != expected:
            raise Conflict(tr('phases.phase_changed_reload_before'))
        from my_harness.storage.documents import unresolved
        if unresolved(session, phase.root) and not resume_close:
            raise Conflict(tr('managed.document_intent_awaits_reconciliation'))
        return phase

    @staticmethod
    def _root_pending(session, root):
        return session.scalar(select(Job.id).join(Run, Run.id == Job.run_id).where(
            Run.root == root, Job.status.in_(PENDING))) is not None

    @staticmethod
    def _closure_pending(session, root):
        return (PhaseRepository._root_pending(session, root) or session.scalar(select(Run.id).where(
            Run.root == root, Run.purpose == 'task', Run.status == 'ACCEPTANCE_READY')) is not None)

    # --- reads ------------------------------------------------------------------------

    def list(self, root):
        with Session(self.managed.engine) as session:
            rows = session.scalars(select(Phase).where(Phase.root == root).order_by(Phase.created_at, Phase.id)).all()
            return [{key: getattr(row, key) for key in ('id', 'code', 'status', 'version', 'created_at', 'updated_at')}
                    | {'objective': row.definition['objective']} for row in rows]

    def by_code(self, root, code):
        """Id of the phase with that code in the checkout; the code is unique per root."""
        with Session(self.managed.engine) as session:
            phase_id = session.scalar(select(Phase.id).where(Phase.root == root, Phase.code == code))
        if phase_id is None:
            raise LookupError(tr('phases.unknown_managed_phase'))
        return phase_id

    def definition(self, phase_id):
        with Session(self.managed.engine) as session:
            phase = session.get(Phase, phase_id)
            if phase is None:
                raise LookupError(tr('phases.unknown_managed_phase'))
            return phase.root, phase.definition

    def closure_files(self, phase_id):
        """Paths of the archive written by the closure, so the API reads them from disk before `get`."""
        with Session(self.managed.engine) as session:
            phase = session.get(Phase, phase_id)
            if phase is None:
                raise LookupError(tr('phases.unknown_managed_phase'))
            return sorted(closure_files(session, phase))

    def get(self, phase_id, current_documents=None, archive_documents=None):
        """Projection with actions computed by the server; `current_documents` and `archive_documents` (hashes
        of the `closure_files` files) are disk reads."""
        now = self.managed._now()
        with Session(self.managed.engine) as session:
            phase = session.get(Phase, phase_id)
            if phase is None:
                raise LookupError(tr('phases.unknown_managed_phase'))
            parts, rows = authority(session, phase)
            open_questions = _open(rows)
            auths = session.scalars(select(Authorization).where(Authorization.phase_id == phase.id)
                                    .order_by(Authorization.created_at, Authorization.id)).all()
            auth_views = [authorization_view(row, now, parts['tasks']) for row in auths]
            ops = session.scalars(select(Operation).where(Operation.phase_id == phase.id)
                                  .order_by(Operation.created_at, Operation.id)).all()
            op_views = []
            for op in ops:
                view = operation_view(op)
                if op.kind == 'reconcile_task' and op.status == 'QUEUED':
                    view['status'] = session.get(Run, op.run_id).status  # live state of the normal run
                op_views.append(view)
            definitions = session.scalars(select(Definition).where(Definition.phase_id == phase.id)
                                          .order_by(Definition.number)).all()
            ready = _ready(session, phase)
            ready_view = None if ready is None else {
                'operation_id': ready.id, 'binding': ready.result['binding'],
                'binding_sha256': ready.result['binding_sha256'],
                'stale_reasons': stale_reasons(parts, ready.result['binding'])}
            drift = None
            if current_documents is not None:
                drift = sorted(path for path, value in current_documents.items() if phase.documents.get(path) != value)
                if ready_view is not None and current_documents != ready.result['binding']['documents']:
                    ready_view['stale_reasons'].append(tr('phases.documents_changed_ready_view'))
            pending = self._root_pending(session, phase.root)
            active_batch = [a for a in auth_views if a['kind'] == 'batch' and a['effective_status'] == 'ACTIVE']
            reconcile_task = _open_reconcile_task(session, phase)
            actions = []
            if not open_questions and phase.status in CHECKABLE:
                actions.append('check')
            if phase.status in RECONCILABLE and not pending:
                actions.append('reconcile')
                if reconcile_task is None:
                    actions.append('reconcile_task')
            if (phase.status == 'READY_TO_CLOSE' and ready_view and not ready_view['stale_reasons']
                    and not open_questions):
                actions.append('close')
            if phase.status not in ('CLOSED', 'CLOSING', 'ABANDONED'):
                actions.append('question')
            if phase.status == 'ACTIVE' and not open_questions:
                if not active_batch:
                    actions.append('authorize_batch')
                elif not active_batch[0]['scope'].get('chain_commits'):
                    actions.append('batch_next')  # manual H3.3 batch; the supervisor drives the unattended one
            if phase.status in AMENDABLE and not pending:
                actions += ['amend', 'abandon']
            from my_harness.storage.documents import unresolved
            if unresolved(session, phase.root):
                actions = []
                from my_harness.storage.documents import pending as interrupted_document
                interrupted = interrupted_document(session, phase, 'close')
                if interrupted is not None and not pending:
                    actions = ['abandon' if interrupted.request.get('terminal') == 'ABANDONED' else 'close']
            # Same order as `latest_phase`: creation and then id.
            successor = session.scalar(select(Phase.code).where(Phase.root == phase.root, or_(
                Phase.created_at > phase.created_at, and_(Phase.created_at == phase.created_at, Phase.id > phase.id)))
                .order_by(Phase.created_at, Phase.id).limit(1))
            closure = closure_view(session, phase, current_documents, archive_documents, successor)
            return {
                'id': phase.id, 'root': phase.root, 'code': phase.code, 'definition': phase.definition,
                'definition_sha256': phase.definition_sha256, 'definition_number': phase.definition_number,
                'definitions': [definition_view(row) for row in definitions],
                'status': phase.status, 'version': phase.version,
                'created_at': phase.created_at, 'updated_at': phase.updated_at,
                'documents': {'baseline': phase.documents, 'current': current_documents, 'drift': drift,
                              'current_sha256': digest(current_documents) if current_documents is not None else None},
                'tasks': parts['tasks'], 'questions': [question_view(q) for q in rows],
                'operations': op_views, 'authorizations': auth_views,
                'ready': ready_view, 'closure': closure, 'actions': actions, 'successor': successor}

    def events(self, phase_id, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError(tr('phases.invalid_phase_event_page'))
        with Session(self.managed.engine) as session:
            if session.get(Phase, phase_id) is None:
                raise LookupError(tr('phases.unknown_managed_phase'))
            rows = session.scalars(select(PhaseEvent).where(PhaseEvent.phase_id == phase_id, PhaseEvent.sequence > after)
                                   .order_by(PhaseEvent.sequence).limit(limit + 1)).all()
            items = [{'id': r.id, 'sequence': r.sequence, 'kind': r.kind, 'recorded_at': r.recorded_at,
                      'payload': r.payload} for r in rows[:limit]]
            return {'items': items, 'cursor': items[-1]['sequence'] if items else after, 'has_more': len(rows) > limit}

    def snapshot(self, run_id):
        """Read for the phase job; `settle` checks the authority again in its transaction."""
        with Session(self.managed.engine) as session:
            run = session.get(Run, run_id)
            op, phase = _operation(session, run)
            parts, rows = authority(session, phase)
            evidence = {}
            for task, item in parts['tasks'].items():
                review = None
                if item is not None:
                    cycles = load_history(session.get(Run, item['run_id']).history_json).cycles
                    review = cycles[-1].review_json if cycles else None
                evidence[task] = None if item is None else {**item, 'review_json': review}
            result = {'operation_id': op.id, 'kind': op.kind, 'definition': phase.definition,
                      'definition_sha256': phase.definition_sha256, 'documents': phase.documents,
                      'tasks': parts['tasks'], 'questions_sha256': parts['questions_sha256'],
                      'open_questions': [q.text for q in rows if q.status == 'OPEN'],
                      'answered_questions': [{'question': q.text, 'answer': q.answer['text']}
                                             for q in rows if q.status == 'ANSWERED'],
                      'task_evidence': evidence}
            if op.kind == 'close':
                auth = session.get(Authorization, op.request['authorization_id'])
                result['ready'] = {'binding': op.request['binding'], 'binding_sha256': op.request['binding_sha256']}
                result['tag_kind'] = op.request.get('tag_kind', 'lightweight')
                previous = session.scalars(select(Operation).where(
                    Operation.phase_id == phase.id, Operation.kind == 'close', Operation.id != op.id)
                    .order_by(Operation.created_at.desc(), Operation.id.desc())).all()
                result['previous_tag_intent'] = next((row.result['tag_intent'] for row in previous if row.result
                                                      and row.result.get('tag_effect') == 'uncertain'), None)
                result['authorization'] = {'id': auth.id, 'status': auth.status, 'expires_at': auth.expires_at,
                                           'usable': auth.status == 'ACTIVE' and auth.expires_at > self.managed._now()}
                if op.request.get('preview'):
                    result['closure'] = {**op.request, 'operation_id': op.id}
                    result['terminal'] = op.request.get('terminal', 'CLOSED')
                    result['tag_intent'] = op.request.get('tag_intent')
            return result

    # --- definition and documents --------------------------------------------------------

    def create(self, context, data):
        definition = phase_definition(context, data)
        documents = document_hashes(context, definition['documents'])
        with self.managed._write() as session:
            root = str(context.root)
            from my_harness.storage.documents import unresolved
            from my_harness.storage.bootstrap import unresolved as bootstrap_unresolved
            from my_harness.storage.project_import import unresolved as import_unresolved
            if (self._root_pending(session, root) or unresolved(session, root)
                    or bootstrap_unresolved(session, root) or import_unresolved(session, root)):
                raise Conflict(tr('phases.checkout_has_unfinished_work'))
            if session.scalar(select(Phase.id).where(Phase.root == root, Phase.code == definition['code'])):
                raise Conflict(tr('phases.phase_code_already_exists'))
            if session.scalar(select(Phase.id).where(Phase.root == root, Phase.status.notin_(TERMINAL))):
                raise Conflict(tr('phases.close_abandon_open_phase'))
            return insert_phase(self.managed, session, root, definition, documents)

    def reconcile(self, context, phase_id, expected, *, documents_sha256, reason):
        """Explicit adoption of changed documents (proposal by hash), never a silent merge."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('phases.explicit_reconciliation_reason_required'))
        root, definition = self.definition(phase_id)
        if root != str(context.root):
            raise LookupError(tr('phases.phase_belongs_another_checkout'))
        current = document_hashes(context, definition['documents'])
        if digest(current) != documents_sha256:
            raise Conflict(tr('phases.documents_changed_since_they'))
        with self.managed._write() as session:
            phase = self._phase(session, phase_id, expected, context)
            if phase.status not in RECONCILABLE:
                raise Conflict(tr('phases.reconciliation_requires_phase_without'))
            if self._root_pending(session, phase.root):
                raise Conflict(tr('phases.checkout_has_unfinished_jobs'))
            before = phase.documents
            now = self.managed._now()
            source = None
            task_op = _open_reconcile_task(session, phase)
            if task_op is not None:
                # H3.4: the base is adopted after the exact-content commit of the reconciliation task.
                commit = session.scalar(select(Commit).where(Commit.run_id == task_op.run_id,
                                                             Commit.status == 'COMMITTED'))
                if commit is None:
                    raise Conflict(tr('phases.reconciliation_task_reviewed_committed'))
                source = {'operation_id': task_op.id, 'run_id': task_op.run_id, 'commit': commit.commit_sha}
            op = Operation(id=str(uuid4()), phase_id=phase.id, kind='reconcile', run_id=None, status='RECORDED',
                           previous_status=phase.status, created_at=now, finished_at=now,
                           request={'actor': actor(), 'reason': reason, 'documents_sha256': documents_sha256},
                           result={'before': before, 'after': current, 'source': source,
                                   'changed': sorted(p for p in current if before.get(p) != current[p])})
            session.add(op)
            if task_op is not None:
                task_op.status, task_op.finished_at = 'ADOPTED', now
                task_op.result = {'adopted_by': op.id, 'commit': source['commit'], 'documents_sha256': documents_sha256}
            phase.documents = current
            if phase.status in ('NEEDS_RECONCILIATION', 'READY_TO_CLOSE'):
                phase.status = 'ACTIVE'
            _event(self.managed, session, phase, 'documents_reconciled', {
                'operation_id': op.id, 'changed': op.result['changed'], 'reason': reason, 'actor': op.request['actor']})

    # --- blocking questions ------------------------------------------------------------

    def raise_question(self, phase_id, expected, *, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError(tr('phases.explicit_question_text_required'))
        with self.managed._write() as session:
            phase = self._phase(session, phase_id, expected)
            if phase.status in ('CLOSED', 'CLOSING', 'ABANDONED'):
                raise Conflict(tr('phases.closed_closing_abandoned_phase'))
            row = Question(id=str(uuid4()), phase_id=phase.id, text=text.strip(), status='OPEN', answer=None,
                           version=1, created_at=self.managed._now(), source={'kind': 'human', 'actor': actor()})
            session.add(row)
            if phase.status in ('ACTIVE', 'NEEDS_RECONCILIATION', 'READY_TO_CLOSE'):
                phase.status = 'BLOCKED'
            _event(self.managed, session, phase, 'question_raised', question_view(row))

    def answer(self, phase_id, question_id, expected, *, expected_question_version, answer):
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(tr('phases.explicit_answer_required'))
        with self.managed._write() as session:
            phase = self._phase(session, phase_id, expected)
            row = session.get(Question, question_id)
            if row is None or row.phase_id != phase.id:
                raise LookupError(tr('phases.unknown_phase_question'))
            if phase.status in ('CLOSED', 'CLOSING', 'ABANDONED'):
                raise Conflict(tr('phases.closed_closing_abandoned_phase_2'))
            if row.status != 'OPEN' or row.version != expected_question_version:
                raise Conflict(tr('phases.question_changed_already_answered'))
            row.status, row.version = 'ANSWERED', row.version + 1
            row.answer = {'text': answer.strip(), 'actor': actor(), 'answered_at': self.managed._now()}
            session.flush()
            if phase.status == 'BLOCKED' and not _open(_questions(session, phase.id)):
                phase.status = 'ACTIVE'
            _event(self.managed, session, phase, 'question_answered', question_view(row))

    # --- operations by job -------------------------------------------------------------

    def submit_check(self, context, phase_id, expected, *, key, versions):
        request = freeze({'action': 'phase_check', 'phase_id': phase_id, 'expected_version': expected})
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            phase = self._phase(session, phase_id, expected, context)
            if phase.status not in CHECKABLE:
                raise Conflict(tr('phases.phase_check_requires_phase'))
            if _open(_questions(session, phase.id)):
                raise Conflict(tr('phases.pending_blocking_questions_answered'))
            job = self.managed._queue_new_run(session, assessment, context, versions, f'{phase.code}-CHECK',
                                              phase.code, key, request, purpose='phase_check')
            op = Operation(id=str(uuid4()), phase_id=phase.id, kind='check', run_id=job.run_id, status='QUEUED',
                           previous_status=phase.status, request={'job_id': job.id, 'actor': actor()},
                           created_at=self.managed._now())
            session.add(op)
            phase.status = 'CHECKING'
            _event(self.managed, session, phase, 'phase_check_queued',
                   {'operation_id': op.id, 'run_id': job.run_id, 'job_id': job.id})
            return job

    def submit_close(self, context, phase_id, expected, *, key, versions, binding_sha256, reason, ttl_seconds,
                     tag_kind='lightweight', git=None, terminal='CLOSED'):
        """Closure authorization bound to the shown READY + closure job, in one transaction.

        `tag_kind` is fixed by the project on the server (H3.4) and stays frozen in the authorization."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('phases.explicit_close_reason_required'))
        if tag_kind not in TAG_KINDS:
            raise ValueError(tr('phases.unknown_tag_kind'))
        if terminal not in TERMINAL:
            raise ValueError(tr('phases.closure_closed_abandoned'))
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError(tr('phases.validity_between_1_second'))
        request = freeze({'action': 'phase_close', 'phase_id': phase_id, 'expected_version': expected,
                          'binding_sha256': binding_sha256, 'reason': reason, 'ttl_seconds': ttl_seconds,
                          **({'terminal': terminal} if terminal != 'CLOSED' else {})})
        from my_harness.storage.documents import pending, unresolved, _resume_job
        from my_harness.storage.transition import snapshot as archive_snapshot
        from my_harness.storage.closure import prepare
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            phase = self._phase(session, phase_id, expected, context, resume_close=True)
            interrupted = pending(session, phase, 'close')
            frozen = None
            if interrupted is None:
                if terminal == 'CLOSED' and (phase.status != 'READY_TO_CLOSE' or _ready(session, phase) is None):
                    raise Conflict(tr('phases.ready_close_phase_current'))
                if terminal == 'ABANDONED' and phase.status not in AMENDABLE:
                    raise Conflict(tr('phases.phase_without_operations_progress'))
                if self._closure_pending(session, phase.root) or unresolved(session, phase.root):
                    raise Conflict(tr('phases.checkout_has_unfinished_work_2'))
                frozen = archive_snapshot(session, phase)
                frozen['phase'] = {**frozen['phase'], 'status': terminal}
                frozen['summary']['phase'] = {**frozen['summary']['phase'], 'status': terminal}
        shown = prepare(context, frozen, git) if frozen is not None else None
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            phase = self._phase(session, phase_id, expected, context, resume_close=True)
            interrupted = pending(session, phase, 'close')
            if interrupted is not None:
                if (interrupted.request.get('terminal', 'CLOSED') != terminal
                        or (terminal == 'CLOSED' and interrupted.request['binding_sha256'] != binding_sha256)):
                    raise Conflict(tr('phases.resume_requires_original_ready'))
                if self._root_pending(session, phase.root):
                    raise Conflict(tr('phases.checkout_has_unfinished_jobs_4'))
                job = _resume_job(self.managed, session, interrupted, context, versions, key, request, assessment,
                                  'phase_close')
                phase.status = 'CLOSING'
                _event(self.managed, session, phase, 'phase_close_resumed', {'operation_id': interrupted.id})
                return job
            ready = _ready(session, phase)
            if terminal == 'ABANDONED' and phase.status not in AMENDABLE:
                raise Conflict(tr('phases.phase_without_operations_progress'))
            if terminal == 'CLOSED' and (phase.status != 'READY_TO_CLOSE' or ready is None):
                raise Conflict(tr('phases.ready_close_phase_current'))
            if terminal == 'CLOSED' and ready.result['binding_sha256'] != binding_sha256:
                raise Conflict(tr('phases.close_authorization_name_current'))
            parts, rows = authority(session, phase)
            if terminal == 'CLOSED' and _open(rows):
                raise Conflict(tr('phases.pending_blocking_questions_prevent'))
            if session.scalar(select(Commit.operation_id).join(Run, Run.id == Commit.run_id).where(
                    Run.root == phase.root, Commit.status == 'INTENT')) is not None:
                raise Conflict(tr('phases.commit_operation_checkout_awaits'))
            if self._closure_pending(session, phase.root) or unresolved(session, phase.root):
                raise Conflict(tr('phases.checkout_has_unfinished_work_2'))
            if terminal == 'ABANDONED':
                bound = {**parts, 'head': shown['head'], 'fingerprint': shown['fingerprint'],
                         'documents': phase.documents}
                binding_sha256 = digest(bound)
                ready = SimpleNamespace(id=None, result={'binding': bound, 'binding_sha256': binding_sha256})
            stale = stale_reasons(parts, ready.result['binding'])
            if terminal == 'CLOSED' and shown is not None:
                stale += [tr('phases.part_changed_ready', part=name) for name in ('head', 'fingerprint')
                          if shown[name] != ready.result['binding'][name]]
            if stale:
                raise Conflict(tr('phases.ready_review_stale', reasons=', '.join(stale)))
            if terminal == 'ABANDONED':
                _invalidate_batches(self.managed, session, phase, tr('phases.abandoned_reason'))
            now = self.managed._now()
            expires = (datetime.fromisoformat(now) + timedelta(seconds=ttl_seconds)).isoformat(timespec='microseconds')
            scope = {'check_operation_id': ready.id, 'binding_sha256': binding_sha256, 'tag': phase.definition['tag'],
                     'tag_kind': tag_kind}
            auth = Authorization(id=str(uuid4()), phase_id=phase.id, kind='close', status='ACTIVE', scope=scope,
                                 fingerprint=digest({'phase_id': phase.id, 'scope': scope, 'expires_at': expires}),
                                 actor=actor(), reason=reason.strip(), expires_at=expires, created_at=now,
                                 closed=None, version=1)
            session.add(auth)
            job = self.managed._queue_new_run(session, assessment, context, versions, f'{phase.code}-CLOSE',
                                              phase.code, key, request, purpose='phase_close')
            op = Operation(id=str(uuid4()), phase_id=phase.id, kind='close', run_id=job.run_id, status='QUEUED',
                           previous_status=phase.status, created_at=now, request={
                               'job_id': job.id, 'authorization_id': auth.id, 'check_operation_id': ready.id,
                               'binding': ready.result['binding'], 'binding_sha256': binding_sha256,
                               'tag_kind': tag_kind, 'preview': shown, 'terminal': terminal})
            session.add(op)
            phase.status = 'CLOSING'
            _event(self.managed, session, phase, 'close_authorized', authorization_view(auth, now))
            _event(self.managed, session, phase, 'phase_close_queued',
                   {'operation_id': op.id, 'run_id': job.run_id, 'job_id': job.id})
            return job

    # --- batch ---------------------------------------------------------------------

    def authorize_batch(self, phase_id, expected, *, tasks, ttl_seconds, reason, chain_commits=False, text=None,
                        context=None, versions=None):
        """`chain_commits` (H3.4, D033): explicit scope «chain tasks and confirm commits», with frozen plan
        text, context and versions; without it, a manual H3.3 batch that only queues via `batch_next`."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('phases.explicit_batch_reason_required'))
        if type(chain_commits) is not bool:
            raise ValueError(tr('phases.explicit_boolean_chain_commits'))
        if chain_commits and (not isinstance(text, str) or not text.strip() or context is None
                              or not isinstance(versions, dict)):
            raise ValueError(tr('phases.unattended_batch_freezes_plan'))
        if not chain_commits and text is not None:
            raise ValueError(tr('phases.unattended_batch_freezes_plan_2'))
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError(tr('phases.validity_between_1_second'))
        if (not isinstance(tasks, list) or not tasks or len(set(tasks)) != len(tasks)
                or not all(isinstance(t, str) for t in tasks)):
            raise ValueError(tr('phases.explicit_distinct_batch_tasks'))
        with self.managed._write() as session:
            phase = self._phase(session, phase_id, expected, context)
            if not set(tasks) <= set(phase.definition['tasks']):
                raise ValueError(tr('phases.batch_tasks_belong_frozen'))
            if phase.status != 'ACTIVE' or _open(_questions(session, phase.id)):
                raise Conflict(tr('phases.batch_authorization_requires_active'))
            now = self.managed._now()
            live = session.scalars(select(Authorization).where(Authorization.phase_id == phase.id,
                                   Authorization.kind == 'batch', Authorization.status == 'ACTIVE')).all()
            if any(row.expires_at > now for row in live):
                raise Conflict(tr('phases.revoke_active_batch_authorization'))
            expires = (datetime.fromisoformat(now) + timedelta(seconds=ttl_seconds)).isoformat(timespec='microseconds')
            scope = {'tasks': tasks}
            if chain_commits:
                scope = {'tasks': tasks, 'chain_commits': True, 'plan_sha256': digest(text), 'text': text,
                         'definition_sha256': phase.definition_sha256, 'context_json': context_snapshot(context),
                         'versions_json': freeze(versions)}
            row = Authorization(id=str(uuid4()), phase_id=phase.id, kind='batch', status='ACTIVE', scope=scope,
                                fingerprint=digest({'phase_id': phase.id, 'scope': scope, 'expires_at': expires}),
                                actor=actor(), reason=reason.strip(), expires_at=expires, created_at=now,
                                closed=None, version=1)
            session.add(row)
            _event(self.managed, session, phase, 'batch_authorized', authorization_view(row, now))
            return row.id

    def revoke(self, phase_id, authorization_id, expected, *, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('phases.explicit_revocation_reason_required'))
        with self.managed._write() as session:
            phase = self._phase(session, phase_id, expected)
            row = session.get(Authorization, authorization_id)
            if row is None or row.phase_id != phase.id:
                raise LookupError(tr('phases.unknown_phase_authorization'))
            if row.kind != 'batch' or row.status != 'ACTIVE':
                raise Conflict(tr('phases.active_batch_authorization_revoked'))
            row.status, row.version = 'REVOKED', row.version + 1
            row.closed = {'at': self.managed._now(), 'actor': actor(), 'reason': reason.strip()}
            _event(self.managed, session, phase, 'batch_revoked', authorization_view(row, self.managed._now()))

    def batch_next(self, context, phase_id, expected, *, key, versions, authorization_id, text):
        """Queues the next authorized task; does not check or close the phase and does not confirm commits."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError(tr('phases.explicit_plan_text_required'))
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            prior = session.scalar(select(Job).where(Job.idempotency_key == key))
            phase = session.get(Phase, phase_id)
            if prior is not None:
                run = session.get(Run, prior.run_id)
                stored = json.loads(prior.request_json)
                if (phase is None or run.root != phase.root or run.phase_id != phase.code
                        or stored.get('text') != text or stored.get('versions_json') != freeze(versions)):
                    raise Conflict(tr('managed.idempotency_key_already_names_2'))
                return _job(prior)
            phase = self._phase(session, phase_id, expected, context)
            auth = session.get(Authorization, authorization_id)
            now = self.managed._now()
            if (auth is None or auth.phase_id != phase.id or auth.kind != 'batch' or auth.status != 'ACTIVE'
                    or auth.expires_at <= now):
                raise Conflict(tr('phases.current_batch_authorization_phase'))
            if auth.scope.get('chain_commits'):
                raise Conflict(tr('phases.unattended_batch_advanced_supervisor'))
            if phase.status != 'ACTIVE' or _open(_questions(session, phase.id)):
                raise Conflict(tr('phases.batch_advances_active_phase'))
            if self._root_pending(session, phase.root):
                raise Conflict(tr('phases.checkout_has_unfinished_jobs_2'))
            done = committed_tasks(session, phase)
            task = None
            for candidate in auth.scope['tasks']:
                if done[candidate] is not None:
                    continue
                if session.scalar(select(Run.id).where(Run.root == phase.root, Run.phase_id == phase.code,
                                                       Run.task_id == candidate, Run.purpose == 'task')):
                    raise Conflict(tr('phases.task_has_run_without', candidate=candidate))
                task = candidate
                break
            if task is None:
                raise Conflict(tr('phases.every_authorized_task_already'))
            request = freeze({'action': 'start', 'context_json': context_snapshot(context),
                              'versions_json': freeze(versions), 'task_id': task, 'phase_id': phase.code, 'text': text})
            job = self.managed._queue_new_run(session, assessment, context, versions, task, phase.code, key, request)
            _event(self.managed, session, phase, 'batch_task_queued', {
                'authorization_id': auth.id, 'task_id': task, 'run_id': job.run_id, 'job_id': job.id})
            return job

    # --- H3.4: amendment, abandonment and reconciliation with an agent --------------------

    def amend(self, context, phase_id, expected, *, data, reason):
        """New version of the definition; the previous one is kept. Invalidates READY and current batches.

        The code does not change (it identifies the runs). New documents are adopted with their current hash,
        recorded in the amendment audit; existing ones keep their adopted base."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('phases.explicit_amendment_reason_required'))
        root, current = self.definition(phase_id)
        if root != str(context.root):
            raise LookupError(tr('phases.phase_belongs_another_checkout'))
        if not isinstance(data, dict) or 'code' in data:
            raise ValueError(tr('phases.amendment_keeps_phase_code'))
        definition = phase_definition(context, {**data, 'code': current['code']})
        observed = document_hashes(context, definition['documents'])
        sha = digest(definition)
        with self.managed._write() as session:
            phase = self._phase(session, phase_id, expected, context)
            if phase.status not in AMENDABLE:
                raise Conflict(tr('phases.amendment_requires_phase_without'))
            if self._root_pending(session, phase.root):
                raise Conflict(tr('phases.checkout_has_unfinished_jobs_3'))
            if sha == phase.definition_sha256:
                raise Conflict(tr('phases.amendment_does_not_change'))
            now = self.managed._now()
            added = [path for path in definition['documents'] if path not in phase.documents]
            documents = {path: phase.documents[path] if path in phase.documents else observed[path]
                         for path in definition['documents']}
            number = phase.definition_number + 1
            session.add(Definition(id=str(uuid4()), phase_id=phase.id, number=number, definition=definition,
                                   definition_sha256=sha, documents=documents, origin='amended',
                                   reason=reason.strip(), actor=actor(), created_at=now))
            invalidated = _invalidate_batches(self.managed, session, phase, tr('phases.amended_reason', number=number))
            op = Operation(id=str(uuid4()), phase_id=phase.id, kind='amend', run_id=None, status='RECORDED',
                           previous_status=phase.status, created_at=now, finished_at=now,
                           request={'actor': actor(), 'reason': reason.strip(), 'definition_sha256': sha,
                                    'previous_sha256': phase.definition_sha256},
                           result={'previous_number': phase.definition_number, 'number': number,
                                   'added_documents': added,
                                   'removed_documents': [p for p in phase.documents if p not in documents],
                                   'invalidated_authorizations': invalidated,
                                   'ready_invalidated': phase.status == 'READY_TO_CLOSE'})
            session.add(op)
            phase.definition, phase.definition_sha256, phase.definition_number = definition, sha, number
            phase.documents = documents
            if phase.status == 'READY_TO_CLOSE':
                phase.status = 'ACTIVE'  # READY never survives another definition
            _event(self.managed, session, phase, 'definition_amended', {
                'operation_id': op.id, 'number': number, 'definition_sha256': sha, 'reason': reason.strip(),
                'invalidated_authorizations': invalidated, 'actor': op.request['actor']})

    def abandon(self, phase_id, expected, *, reason, context, git, key, versions):
        """Confirmed abandonment: the same reconcilable archive as the closure, without tag or READY."""
        return self.submit_close(context, phase_id, expected, reason=reason, git=git, key=key, versions=versions,
                                 binding_sha256=None, ttl_seconds=3600, terminal='ABANDONED')

    def submit_reconcile_task(self, context, phase_id, expected, *, key, versions):
        """Normal task with a deterministic contract (`reconcile-phase` template) limited to the documents.

        It is executed, reviewed and confirmed through the task flow; then the base is adopted by hash."""
        from my_harness.core.engine.contracts import task_contract
        from my_harness.core.engine.prompts import digest as text_digest, render
        from my_harness.storage.prompts import PromptRepository
        template = PromptRepository(self.managed.engine).catalog(context)['reconcile-phase']
        marker = {'kind': 'reconcile_task', 'phase_id': phase_id, 'expected_version': expected}
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            prior = session.scalar(select(Job).where(Job.idempotency_key == key))
            if prior is not None:
                if json.loads(prior.request_json).get('phase_operation') != marker:
                    raise Conflict(tr('managed.idempotency_key_already_names_2'))
                return _job(prior)
            phase = self._phase(session, phase_id, expected, context)
            if phase.status not in RECONCILABLE:
                raise Conflict(tr('phases.reconciliation_requires_phase_without'))
            if self._root_pending(session, phase.root):
                raise Conflict(tr('phases.checkout_has_unfinished_jobs'))
            if _open_reconcile_task(session, phase) is not None:
                raise Conflict(tr('phases.reconciliation_task_phase_progress'))
            documents = phase.definition['documents']
            protected = context.profile.protected_paths
            number = 1 + len(session.scalars(select(Operation.id).where(
                Operation.phase_id == phase.id, Operation.kind == 'reconcile_task')).all())
            task_id = f'{phase.code}-RECONCILE-{number}'
            from my_harness.core.engine.documents import BUDGETS, executor_protected, layout
            target = layout(context)
            allowed = list(documents)
            if target is not None:
                allowed = list(dict.fromkeys(list(documents) + list(target.product_documents)
                                             + [f'{folder}/**' for folder in target.folders]))
            # P008-T003: in v2 the harness documents are governed by the documentary contract, not the profile.
            if any(executor_protected(context, task_id, path) for path in allowed):
                raise Conflict(tr('phases.phase_document_protected_profile'))
            tasks = committed_tasks(session, phase)
            check = _latest(session, phase.id, 'check')
            evidence = {'phase': phase.definition, 'definition_sha256': phase.definition_sha256,
                        'baseline_documents': phase.documents, 'tasks': tasks,
                        'latest_check': None if check is None else {
                            'operation_id': check.id, 'status': check.status,
                            'reasons': (check.result or {}).get('reasons'), 'review': (check.result or {}).get('result')}}
            proposals = _decision_proposals(session, tasks)
            if proposals:
                evidence['decision_proposals'] = proposals  # D088 point 2: proposals to consolidate
            instructions = render(template, {'PHASE_ID': phase.code, 'REVIEW_JSON': freeze(evidence)})
            required = (check.result or {}).get('reasons', []) if check is not None and check.status == 'REVISE' else []
            policy = context.policy
            constraints = ['Documentation only: no code, tests, plans state, commits or tags.']
            if target is not None:
                # D072: reconciliation compacts STATE and updates the product and decision documents;
                # the managed blocks (also the DECISIONS index, D088) and the archive still belong to the harness.
                # D169: the headings and the status label follow the project's work language.
                w = words(work_language(context))
                constraints += [
                    'Never edit inside my-harness managed blocks; My Harness regenerates them at commit.',
                    f'Rewrite the "{w["baseline_label"]}" section of {target.state} as a compact description of what '
                    f'exists and works, by area, within {BUDGETS["base"]} bytes, linking archived summaries.',
                    f'Summarize the phase in the "{w["active_label"]}" section of {target.state} and note what the next '
                    'session must know.',
                    f'Record durable decisions as new "## DNNN — title" sections of {target.decisions}, each with '
                    f'a first "{w["status_label"]}" line and the next free number; supersede, never delete or renumber.']
                if proposals:
                    constraints.append('Consolidate the reviewer decision_proposals of the evidence into '
                                       f'{target.decisions} when they describe accepted reality; never invent or '
                                       'adopt rejected ones.')
            contract = task_contract(context, {
                'task_id': task_id, 'phase_id': phase.code, 'title': f'Reconcile phase {phase.code} documents',
                'objective': f'Make the phase {phase.code} documents describe accepted reality.',
                'business_context': '', 'allowed_paths': allowed,
                'forbidden_paths': list(dict.fromkeys(path for path in protected
                                                      if target is None or path not in target.harness_owned)),
                'acceptance_criteria': [f'Only these {"phase " if target is None else ""}documents change: {", ".join(allowed)}.',
                                        *[f'Required by the phase review: {item}' for item in required],
                                        'Unresolved product decisions are recorded as questions, not invented.'],
                'implementation_constraints': constraints,
                'validation_commands': [], 'documentation_refs': list(documents), 'deliverables': list(documents),
                'risk_notes': [], 'executor_prompt': instructions,
                'executor_selection': {'model': policy.executor_models[0], 'effort': policy.executor_efforts[0],
                                       'reason': 'First explicit executor selection of the policy (deterministic contract)'},
                'contract_source': f'reconcile-phase template {template.id} (deterministic, no agent planner)',
                'prompt_template': {'name': template.name, 'id': template.id, 'sha256': template.sha256,
                                    'rendered_sha256': text_digest(instructions)},
            }, task_id, phase.code)
            request = freeze({'action': 'start', 'context_json': context_snapshot(context),
                              'versions_json': freeze(versions), 'task_id': task_id, 'phase_id': phase.code,
                              'text': f'Deterministic reconcile-phase contract for {phase.code}',
                              'contract_json': contract, 'phase_operation': marker})
            job = self.managed._queue_new_run(session, assessment, context, versions, task_id, phase.code, key, request)
            op = Operation(id=str(uuid4()), phase_id=phase.id, kind='reconcile_task', run_id=job.run_id,
                           status='QUEUED', previous_status=phase.status, created_at=self.managed._now(),
                           request={'job_id': job.id, 'actor': actor(), 'task_id': task_id,
                                    'contract_sha256': text_digest(contract), 'allowed_paths': allowed,
                                    'template': {'id': template.id, 'sha256': template.sha256}})
            session.add(op)
            _event(self.managed, session, phase, 'reconcile_task_queued', {
                'operation_id': op.id, 'run_id': job.run_id, 'job_id': job.id, 'task_id': task_id})
            return job


# --- H3.4: unattended batch driver -----------------------------------------------------------


def _batch_stop(managed, session, phase, auth, status, reason):
    auth.status, auth.version = status, auth.version + 1
    auth.closed = {'at': managed._now(), 'reason': reason, 'by': 'batch_driver'}
    _event(managed, session, phase, 'batch_stopped', {'authorization_id': auth.id, 'status': status, 'reason': reason})


def _batch_step(managed, session, auth_id, context, assessment):
    """A step derived from the state: queues a task or a commit, waits, ends or stops."""
    auth = session.get(Authorization, auth_id)
    if auth is None or auth.status != 'ACTIVE':
        return
    phase, scope = session.get(Phase, auth.phase_id), auth.scope

    def stop(status, reason):
        _batch_stop(managed, session, phase, auth, status, reason)
    if auth.expires_at <= managed._now():
        return stop('EXPIRED', tr('phases.batch_authorization_expired_nothing'))
    if phase.definition_sha256 != scope['definition_sha256']:
        return stop('INVALIDATED', tr('phases.phase_definition_changed_since'))
    if _open(_questions(session, phase.id)):
        return stop('STOPPED', tr('phases.pending_blocking_questions'))
    if phase.status != 'ACTIVE':
        return stop('STOPPED', tr('phases.phase_batch_never_checks', status=phase.status))
    states = session.scalars(select(Job.status).join(Run, Run.id == Job.run_id).where(
        Run.root == phase.root, Job.status.in_(PENDING))).all()
    if 'RECOVERY_REQUIRED' in states:
        return stop('STOPPED', tr('phases.job_checkout_requires_explicit'))
    if states:
        return  # one writing action at a time: wait for it to finish
    done = committed_tasks(session, phase)
    for task in scope['tasks']:
        if done.get(task) is not None:
            continue
        start_key = f'batch:{auth.id}:start:{task}'
        start = session.scalar(select(Job).where(Job.idempotency_key == start_key))
        if start is None:
            if session.scalar(select(Run.id).where(Run.root == phase.root, Run.phase_id == phase.code,
                                                   Run.task_id == task, Run.purpose == 'task')):
                return stop('STOPPED', tr('phases.task_has_run_outside', task=task))
            request = freeze({'action': 'start', 'context_json': scope['context_json'],
                              'versions_json': scope['versions_json'], 'task_id': task, 'phase_id': phase.code,
                              'text': scope['text']})
            job = managed._queue_new_run(session, assessment, context, json.loads(scope['versions_json']), task,
                                         phase.code, start_key, request)
            _event(managed, session, phase, 'batch_task_queued', {
                'authorization_id': auth.id, 'task_id': task, 'run_id': job.run_id, 'job_id': job.id,
                'unattended': True})
            return
        run = session.get(Run, start.run_id)
        commit_key = f'batch:{auth.id}:commit:{run.id}'
        if session.scalar(select(Job.id).where(Job.idempotency_key == commit_key)) is None:
            history = load_history(run.history_json)
            if history.status == 'acceptance_ready' and history.acceptance is not None and history.acceptance.eligible:
                request = freeze({'action': 'commit', 'run_id': run.id, 'expected_version': run.version,
                                  'mechanical': []})
                job = managed._queue_commit(session, run, commit_key, request, (), assessment)
                _event(managed, session, phase, 'batch_commit_queued', {
                    'authorization_id': auth.id, 'task_id': task, 'run_id': run.id, 'job_id': job.id})
                return
            detail = history.stop.reason if history.stop else history.status
            return stop('STOPPED', tr('phases.task_stopped_without_eligible', task=task, status=run.status,
                                      detail=detail))
        return stop('STOPPED', tr('phases.commit_task_did_not', task=task, status=run.status))
    auth.status, auth.version = 'COMPLETED', auth.version + 1
    auth.closed = {'at': managed._now(), 'reason': tr('phases.batch_completed_reason'),
                   'by': 'batch_driver'}
    _event(managed, session, phase, 'batch_completed', {'authorization_id': auth.id})


def advance_batches(managed):
    """Called by the supervisor before claiming. Idempotent: deterministic keys per batch and step."""
    with Session(managed.engine) as session:
        live = [row.id for row in session.scalars(select(Authorization).where(
            Authorization.kind == 'batch', Authorization.status == 'ACTIVE')
            .order_by(Authorization.created_at, Authorization.id)) if row.scope.get('chain_commits')]
        contexts = {auth_id: session.get(Authorization, auth_id).scope['context_json'] for auth_id in live}
    for auth_id in live:
        try:
            context = restore_context(contexts[auth_id])
            assessment = managed.guard.assess(context.root)  # disk read outside the transaction
            with managed._write() as session:
                _batch_step(managed, session, auth_id, context, assessment)
        except (ValueError, LookupError, OSError) as exc:  # Conflict derives from ValueError
            with managed._write() as session:
                auth = session.get(Authorization, auth_id)
                if auth.status == 'ACTIVE':
                    _batch_stop(managed, session, session.get(Phase, auth.phase_id), auth, 'STOPPED',
                                f'{type(exc).__name__}: {exc}')
