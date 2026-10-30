"""P002-T006 (D287): production operation journal behind `OperationPort`, and correlated trace events.

One `workflow_operations` row per deterministic key inside a graph thread; the thread's first operation fixes its
project root. Every status change is a compare-and-set that writes its `trace_events` row in the same transaction,
so the status column is a projection the events rebuild. Events are ordered by id, deduplicated by key (an identical
replay is a no-op, a different payload is refused) and insert-only.

Kinds: `domain_command` (written COMPLETED inside the command's transaction through the T005 audit sink),
`agent_invocation` (sealed in the fenced attempt start with the ledger intent, settled with the fenced attempt result)
and `sealed_effect` (the generic `run_operation` effect, without a native journal to reconcile against). Later tasks
add their kinds with reconcilers. Only `sealed_effect` is sealed and completed through the generic port; the other
kinds settle from their native outcome. Recovery classifies by evidence: a native outcome reconciles; otherwise the
operation becomes UNCERTAIN, never COMPLETED. An expired lease proves nothing and nothing is reissued.

Every read, replay, reconciliation and completion through the port checks the operation's project root. `refs` are
bounded string references and `origin` the `{kind, id}` reference of the request; both are validated before anything
is written and never coerced. Operation results are kept verbatim within 16 KiB (they are what a replayed node
continues from), so credentials and secret-looking values are refused, not masked. Event payloads are bounded by
`trace-payload-1`; what they offload is stored in `trace_artifacts` with the event and read back by digest.
"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import re
from typing import Mapping
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.core.engine.observation import observe
from my_harness.core.engine import trace_envelopes
from my_harness.core.engine.trace_payload import SECRET_VALUES, SENSITIVE_KEY, bound, contained_references
from my_harness.i18n import tr
from my_harness.storage.models import (
    DomainCommandRow, GraphThreadRow, KnowledgeProjectRow, ManagedAttemptRow, ManagedJobRow, ManagedProcessRow,
    TraceArtifactRow as Artifact, TraceEventRow as Event, WorkflowOperationRow as Operation,
)

KINDS = ('domain_command', 'agent_invocation', 'sealed_effect')
GENERIC_KINDS = ('sealed_effect',)  # sealed and completed through the port; the others settle natively
TERMINAL = ('COMPLETED', 'FAILED', 'ABANDONED')
ORIGIN_KINDS = ('domain_command', 'managed_job', 'phase_authorization', 'autonomous_authorization', 'inbox_action',
                'chat_turn')
MAX_RESULT = 16384
MAX_DEPTH = 16
MAX_REFS = 32
MAX_REF_VALUE = 200
MAX_EVENT_ARTIFACTS = 1024 * 1024  # offloaded bytes per event
REF_KEY = re.compile(r'[a-z][a-z0-9_]{0,63}')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}')
MAX_PAGE = 200
ENVELOPES = {'knowledge.delivered': trace_envelopes.knowledge_delivery,
             'knowledge.receipt': trace_envelopes.knowledge_receipt,
             'tool.discovered': trace_envelopes.tool_discovery}


def now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


class JournalConflict(ValueError):
    pass


def _secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_VALUES)


def validated_refs(refs) -> dict:
    """Bounded string references, unchanged: at most 32 lowercase keys and printable values of 200 characters,
    no credential names or secret-looking values. Anything else is refused, never coerced or truncated."""
    if not isinstance(refs, Mapping) or len(refs) > MAX_REFS:
        raise JournalConflict(tr('journal.refs_invalid', where='$'))
    for key, value in refs.items():
        if not isinstance(key, str) or not REF_KEY.fullmatch(key) or SENSITIVE_KEY.match(key):
            raise JournalConflict(tr('journal.refs_invalid', where=str(key)[:64]))
        if (not isinstance(value, str) or not value or len(value) > MAX_REF_VALUE or not value.isprintable()
                or _secret(value)):
            raise JournalConflict(tr('journal.refs_invalid', where=key))
    return dict(sorted(refs.items()))


def validated_origin(origin) -> dict | None:
    """The request reference `{kind, id}` of D287, or none."""
    if origin is None:
        return None
    if (not isinstance(origin, Mapping) or set(origin) != {'kind', 'id'} or origin['kind'] not in ORIGIN_KINDS
            or not isinstance(origin['id'], str) or not IDENTIFIER.fullmatch(origin['id']) or _secret(origin['id'])):
        raise JournalConflict(tr('journal.origin_invalid'))
    return {'kind': origin['kind'], 'id': origin['id']}


def validated_result(value, where: str = 'result') -> dict:
    """An operation result or error kept verbatim: a JSON object of primitives within 16 KiB and 16 levels,
    without credential keys or secret-looking strings (refused, since masking would change what a replay reads)."""
    def check(item, depth):
        if depth > MAX_DEPTH:
            raise JournalConflict(tr('journal.result_invalid', where=where))
        if isinstance(item, Mapping):
            for key, inner in item.items():
                if not isinstance(key, str) or SENSITIVE_KEY.match(key) or _secret(key):
                    raise JournalConflict(tr('journal.result_invalid', where=where))
                check(inner, depth + 1)
        elif isinstance(item, (list, tuple)):
            for inner in item:
                check(inner, depth + 1)
        elif isinstance(item, str):
            if _secret(item):
                raise JournalConflict(tr('journal.result_invalid', where=where))
        elif item is not None and not isinstance(item, (bool, int, float)):
            raise JournalConflict(tr('journal.result_invalid', where=where))
    if not isinstance(value, Mapping):
        raise JournalConflict(tr('journal.result_invalid', where=where))
    check(value, 0)
    try:
        text_value = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)
    except (TypeError, ValueError):
        raise JournalConflict(tr('journal.result_invalid', where=where)) from None
    if len(text_value.encode('utf-8')) > MAX_RESULT:
        raise JournalConflict(tr('journal.result_invalid', where=where))
    return json.loads(text_value)


@dataclass(frozen=True)
class InvocationOperation:
    """What a graph node supplies to `agent_started` for the invocation it seals (D287); validated on creation."""
    thread_id: str
    key: str
    refs: Mapping = field(default_factory=dict)
    origin: Mapping | None = None
    parent_operation_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self):
        validated_refs(self.refs)
        validated_origin(self.origin)


# Events --------------------------------------------------------------------------------------------------------------

def record_event(session, *, kind: str, dedupe_key: str, payload: Mapping, source: str = 'derived', root=None,
                 thread_id=None, operation_id=None, invocation_id=None, command_id=None, parent_event_id=None,
                 causation_id=None, at: str | None = None) -> Event:
    """Appends one event in the caller's transaction; the same key with the same content returns the first row."""
    clean = bound(dict(payload))
    if sum(len(data) for _reference, data in clean.artifacts) > MAX_EVENT_ARTIFACTS:
        raise JournalConflict(tr('journal.event_too_large', key=dedupe_key))
    offloaded = {reference['sha256']: (reference['media'], data) for reference, data in clean.artifacts}
    if any(reference.get('sha256') not in offloaded
           for reference in contained_references(clean.payload, offloaded)):
        # A supplied value shaped like a reference would point at bytes nobody stored.
        raise JournalConflict(tr('journal.event_conflict', key=dedupe_key))
    links = {'root': root, 'thread_id': thread_id, 'operation_id': operation_id, 'invocation_id': invocation_id,
             'command_id': command_id, 'parent_event_id': parent_event_id, 'causation_id': causation_id,
             'kind': kind, 'source': source}
    digest = _sha256({'payload': clean.payload, **links})
    existing = session.scalar(select(Event).where(Event.dedupe_key == dedupe_key))
    if existing is not None:
        if existing.payload_sha256 != digest:
            raise JournalConflict(tr('journal.event_conflict', key=dedupe_key))
        return existing
    row = Event(event_id=str(uuid4()), dedupe_key=dedupe_key, payload=clean.payload, payload_sha256=digest,
                truncated=clean.truncated, redactions=clean.redactions, recorded_at=at or now(), **links)
    session.add(row)
    session.flush()
    stored = set()
    for reference, data in clean.artifacts:  # masked bytes the payload references, kept with the event
        if reference['sha256'] not in stored:
            stored.add(reference['sha256'])
            session.add(Artifact(event_id=row.event_id, sha256=reference['sha256'], size=reference['size'],
                                 media=reference['media'], content=data))
    session.flush()
    return row


def record_envelope(session, kind: str, envelope: Mapping, *, dedupe_key: str, invocation_id: str, root=None,
                    thread_id=None, operation_id=None, causation_id=None) -> Event:
    """T007/T008 entry: a validated knowledge-delivery or discovery envelope as an event of its invocation."""
    validate = ENVELOPES.get(kind)
    if validate is None:
        raise JournalConflict(tr('journal.kind_unknown', kind=kind))
    validate(dict(envelope))
    if envelope['invocation_id'] != invocation_id:
        raise JournalConflict(tr('journal.event_conflict', key=dedupe_key))
    return record_event(session, kind=kind, dedupe_key=dedupe_key, payload=envelope, source='supplied', root=root,
                        thread_id=thread_id, operation_id=operation_id, invocation_id=invocation_id,
                        causation_id=causation_id)


def _last_event(session, operation_id: str) -> str | None:
    return session.scalar(select(Event.event_id).where(Event.operation_id == operation_id)
                          .order_by(Event.id.desc()).limit(1))


def _transition_event(session, row: Operation, status: str, payload: Mapping, *, at: str, source='derived'):
    return record_event(session, kind=f'operation.{status.lower()}', dedupe_key=f'operation:{row.id}:{status}',
                        payload={'status': status, 'kind': row.kind, 'key': row.key, **payload}, source=source,
                        root=row.root, thread_id=row.thread_id, operation_id=row.id,
                        invocation_id=row.invocation_id, command_id=row.command_id,
                        parent_event_id=_last_event(session, row.id),
                        causation_id=row.causation_event_id if status == 'INTENDED' else None, at=at)


# Operations ----------------------------------------------------------------------------------------------------------

def _check_scope(session, thread_id: str, root: str) -> None:
    if session.get(GraphThreadRow, thread_id) is None:
        raise LookupError(tr('orchestration.thread_unknown', thread=thread_id))
    other = session.scalar(select(Operation.root).where(Operation.thread_id == thread_id, Operation.root != root)
                           .limit(1))
    if other is not None:
        raise JournalConflict(tr('journal.thread_scope', thread=thread_id))


def _insert(session, *, thread_id, key, kind, root, refs, status, at, origin=None, parent_operation_id=None,
            causation_event_id=None, **links) -> Operation:
    if kind not in KINDS:
        raise JournalConflict(tr('journal.kind_unknown', kind=kind))
    refs, origin = validated_refs(refs), validated_origin(origin)
    _check_scope(session, thread_id, root)
    row = Operation(id=str(uuid4()), thread_id=thread_id, key=key, root=root, kind=kind,
                    parent_operation_id=parent_operation_id, causation_event_id=causation_event_id,
                    origin=origin, refs=refs,
                    request_sha256=_sha256({'kind': kind, 'refs': refs}), status=status, created_at=at,
                    updated_at=at, **links)
    session.add(row)
    session.flush()
    return row


def _scoped(session, thread_id: str, key: str, root: str) -> Operation | None:
    """The operation under `key`, only for its own project root: another root cannot read, reconcile or change it."""
    row = session.scalar(select(Operation).where(Operation.thread_id == thread_id, Operation.key == key))
    if row is not None and row.root != root:
        raise JournalConflict(tr('journal.thread_scope', thread=thread_id))
    return row


def _existing(session, thread_id: str, key: str, kind: str, refs: Mapping, root: str) -> Operation | None:
    row = _scoped(session, thread_id, key, root)
    if row is not None and (row.kind != kind or row.request_sha256 != _sha256({'kind': kind,
                                                                               'refs': validated_refs(refs)})):
        raise JournalConflict(tr('journal.operation_conflict', operation=key, thread=thread_id))
    return row


def transition(session, row: Operation, expected: tuple, status: str, *, result=None, error=None, at=None,
               payload: Mapping | None = None) -> Operation:
    """Compare-and-set from one of `expected` to `status`, with its event in the same transaction."""
    if row.status not in expected:
        raise JournalConflict(tr('journal.operation_state', operation=row.id, status=row.status,
                                 expected=', '.join(expected)))
    at = at or now()
    row.status, row.updated_at = status, at
    if result is not None:
        row.result = validated_result(result)
    if error is not None:
        row.error = validated_result(error, 'error')
    session.flush()
    _transition_event(session, row, status, {**({'error': row.error} if error is not None else {}),
                                             **(payload or {})}, at=at)
    return row


# Domain commands (T005 audit sink) -----------------------------------------------------------------------------------

def command_sink(session, command: DomainCommandRow) -> None:
    """Called by `DomainOperations` in the session of an accepted outcome or of a recorded refusal."""
    project = session.get(KnowledgeProjectRow, command.knowledge_project_id) if command.knowledge_project_id else None
    root = project.root if project is not None else None
    caller = command.caller or {}
    thread_id, key = caller.get('thread_id'), caller.get('operation_key')
    graph = command.principal == 'harness' and command.channel == 'graph' and thread_id and key
    payload = {'operation': command.operation_id, 'version': command.operation_version,
               'principal': command.principal, 'channel': command.channel, 'outcome': command.outcome,
               'refusal_code': command.refusal_code, 'draft_id': command.draft_id, 'revision_id': command.revision_id}
    if command.outcome != 'ACCEPTED' or not graph:
        # T008: agent commands retain their domain identity while linking to the parent native invocation.
        # Refused forged callers do not get to attach an event to an unrelated project's operation.
        invocation = session.scalar(select(Operation).where(Operation.invocation_id == caller.get('invocation_id'),
            Operation.root == root)) if command.principal == 'agent' and caller.get('invocation_id') else None
        record_event(session, kind=f'domain.command_{command.outcome.lower()}',
                     dedupe_key=f'command:{command.command_id}', payload={**payload, 'operation_key': key},
                     source='supplied', root=root,
                     thread_id=invocation.thread_id if invocation else (
                         thread_id if graph and session.get(GraphThreadRow, thread_id) else None),
                     operation_id=invocation.id if invocation else None,
                     invocation_id=invocation.invocation_id if invocation else None,
                     command_id=command.command_id, at=command.recorded_at)
        return
    if root is None:
        raise JournalConflict(tr('journal.thread_scope', thread=thread_id))
    refs = {'operation': f'{command.operation_id}@{command.operation_version}'}
    row = _existing(session, thread_id, key, 'domain_command', refs, root)
    if row is not None:  # a replay returns the stored outcome before reaching the sink; a second row is refused
        raise JournalConflict(tr('journal.operation_conflict', operation=key, thread=thread_id))
    row = _insert(session, thread_id=thread_id, key=key, kind='domain_command', root=root, refs=refs,
                  status='COMPLETED', at=command.recorded_at, command_id=command.command_id,
                  result={'command_id': command.command_id})
    _transition_event(session, row, 'COMPLETED', payload, at=command.recorded_at, source='supplied')


# Agent invocations (fenced managed writes) ---------------------------------------------------------------------------

def seal_invocation(session, spec: InvocationOperation, *, root: str, job: ManagedJobRow, attempt: ManagedAttemptRow,
                    invocation_id: str, at: str) -> Operation:
    """Inside `agent_started`'s fenced transaction, with the attempt row and the ledger intent, before launch."""
    refs = {**spec.refs, 'role': json.loads(attempt.request_json)['role']}
    if _existing(session, spec.thread_id, spec.key, 'agent_invocation', refs, root) is not None:
        raise JournalConflict(tr('journal.invocation_exists', operation=spec.key))
    row = _insert(session, thread_id=spec.thread_id, key=spec.key, kind='agent_invocation', root=root, refs=refs,
                  status='INTENDED', at=at, origin=spec.origin, parent_operation_id=spec.parent_operation_id,
                  causation_event_id=spec.causation_event_id, job_id=job.id, owner_token=job.owner_token,
                  attempt_id=attempt.id, invocation_id=invocation_id)
    _transition_event(session, row, 'INTENDED', {'attempt_number': attempt.number}, at=at, source='supplied')
    return row


def _attempt_outcome(attempt: ManagedAttemptRow):
    """Native outcome of a settled attempt: (status, result, error), or None while it has no result."""
    if attempt.result_json is None:
        return None
    status = (attempt.status or '').upper()
    if status in ('COMPLETE', 'COMPLETED'):
        return 'COMPLETED', {'attempt_status': status.lower()}, None
    code = 'interrupted_outcome_unknown' if status == 'INTERRUPTED' else (status.lower() or 'failed')
    return 'FAILED', None, {'code': code, 'attempt_id': attempt.id}


def settle_attempt(session, attempt: ManagedAttemptRow, *, revision_round: int | None, at: str) -> Operation | None:
    """Reconciles the attempt's operation in the transaction that stores its result; 0.1.9 attempts have none."""
    row = session.scalar(select(Operation).where(Operation.attempt_id == attempt.id))
    if row is None or row.status in TERMINAL:
        return row
    outcome = _attempt_outcome(attempt)
    if outcome is None:
        return row
    status, result, error = outcome
    process = session.get(ManagedProcessRow, attempt.id)
    observation = observe(spec=process.spec if process else None, process_status=process.status if process else None,
                          capture=process.capture if process else None,
                          identity_present=bool(process is not None and process.identity),
                          attempt_number=attempt.number, revision_round=revision_round)
    record_event(session, kind='invocation.observed', dedupe_key=f'observation:{row.invocation_id}',
                 payload=observation, root=row.root, thread_id=row.thread_id, operation_id=row.id,
                 invocation_id=row.invocation_id, at=at)
    return transition(session, row, ('INTENDED', 'UNCERTAIN'), status, result=result, error=error, at=at,
                      payload={'termination': observation['termination']['class']})


def _lease_live(job: ManagedJobRow | None, at: str) -> bool:
    return bool(job is not None and job.status == 'ACTIVE' and job.lease_until and job.lease_until > at)


# Journal: port operations, recovery and queries ----------------------------------------------------------------------

def _plain(row: Operation, created: bool) -> dict:
    return {'key': row.key, 'kind': row.kind, 'state': row.status, 'created': created,
            'result': dict(row.result or {}), 'operation_id': row.id}


class OperationJournal:
    def __init__(self, engine):
        self.engine = engine

    def _write(self):
        session = Session(self.engine)
        transaction = session.begin()
        if session.execute(text('PRAGMA query_only')).scalar():
            transaction.rollback()
            session.close()
            raise PermissionError(tr('journal.read_only'))
        session.execute(text('UPDATE workflow_operations SET status = status WHERE 0'))  # write lock first
        return _Unit(session, transaction)

    def seal(self, thread_id: str, root: str, key: str, kind: str, refs: Mapping, *,
             origin: Mapping | None = None) -> dict:
        """`OperationPort.seal` for one thread (orchestration's `JournalPort`): the existing record, reconciled
        first when its native source has an outcome, or a new INTENDED operation committed before the effect."""
        at = now()
        refs, origin = validated_refs(refs), validated_origin(origin)  # before anything is written
        with self._write() as session:
            row = _existing(session, thread_id, key, kind, refs, root)
            if row is not None:
                if row.kind == 'agent_invocation' and row.status in ('INTENDED', 'UNCERTAIN'):
                    settle_attempt(session, session.get(ManagedAttemptRow, row.attempt_id), revision_round=None, at=at)
                return _plain(row, False)
            if kind not in GENERIC_KINDS:  # invocations and commands are sealed by their own fenced writes
                raise JournalConflict(tr('journal.kind_not_generic', kind=kind))
            row = _insert(session, thread_id=thread_id, key=key, kind=kind, root=root, refs=refs, status='INTENDED',
                          at=at, origin=origin)
            _transition_event(session, row, 'INTENDED', {}, at=at, source='supplied')
            return _plain(row, True)

    def complete(self, thread_id: str, root: str, key: str, result: Mapping) -> dict:
        """`OperationPort.complete` for a generic sealed effect of this project; an invocation or a command never
        completes here (their outcome is the fenced native result, or a reconciliation from persisted evidence)."""
        at = now()
        result = validated_result(result)
        with self._write() as session:
            row = _scoped(session, thread_id, key, root)
            if row is None:
                raise LookupError(tr('journal.operation_unknown', operation=key))
            if row.kind not in GENERIC_KINDS:
                raise JournalConflict(tr('journal.kind_not_generic', kind=row.kind))
            transition(session, row, ('INTENDED',), 'COMPLETED', result=result, at=at)
            return _plain(row, False)

    def recover(self, thread_id: str, *, writer_stopped: bool = False, at: str | None = None) -> list[dict]:
        """Classifies the thread's non-terminal operations by evidence; never completes from a status or a lease."""
        at = at or now()
        changed = []
        with self._write() as session:
            thread = session.get(GraphThreadRow, thread_id)
            if thread is None:
                raise LookupError(tr('orchestration.thread_unknown', thread=thread_id))
            rows = session.scalars(select(Operation).where(Operation.thread_id == thread_id,
                                                           Operation.status == 'INTENDED')
                                   .order_by(Operation.created_at, Operation.id)).all()
            for row in rows:
                if row.kind == 'agent_invocation':
                    attempt = session.get(ManagedAttemptRow, row.attempt_id)
                    if _attempt_outcome(attempt) is not None:
                        settle_attempt(session, attempt, revision_round=None, at=at)
                    elif _lease_live(session.get(ManagedJobRow, row.job_id), at):
                        continue  # its fenced owner may still record the result
                    else:
                        transition(session, row, ('INTENDED',), 'UNCERTAIN', at=at,
                                   error={'code': 'no_native_outcome', 'attempt_id': row.attempt_id})
                elif thread.status != 'RUNNING' or writer_stopped:
                    transition(session, row, ('INTENDED',), 'UNCERTAIN', at=at, error={'code': 'no_recorded_outcome'})
                else:
                    continue  # a live segment may still complete it
                changed.append({'operation_id': row.id, 'key': row.key, 'status': row.status})
        return changed

    def abandon(self, operation_id: str, *, reason: str, actor: Mapping, at: str | None = None) -> dict:
        """Owner decision on an UNCERTAIN operation: no effect is claimed and nothing is reissued under its key."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('journal.reason_required'))
        with self._write() as session:
            row = session.get(Operation, operation_id)
            if row is None:
                raise LookupError(tr('journal.operation_unknown', operation=operation_id))
            transition(session, row, ('UNCERTAIN',), 'ABANDONED', at=at, error={'code': 'owner_abandoned'},
                       payload={'reason': reason.strip()[:1000], 'actor': dict(actor)})
            return {'operation_id': row.id, 'status': row.status}

    # Queries: bounded, scoped to one project root, read-only (they also serve restored query-only copies) -----------

    def _thread(self, session, root: str, thread_id: str) -> GraphThreadRow:
        thread = session.get(GraphThreadRow, thread_id)
        owned = session.scalar(select(Operation.id).where(Operation.thread_id == thread_id, Operation.root == root)
                               .limit(1))
        if thread is None or owned is None:
            raise LookupError(tr('journal.trace_unknown'))
        return thread

    def thread(self, root: str, thread_id: str) -> dict:
        with Session(self.engine) as session:
            row = self._thread(session, root, thread_id)
            return {'thread_id': row.id, 'graph_id': row.graph_id, 'graph_version': row.graph_version,
                    'status': row.status, 'segments': row.segments, 'reason': row.reason,
                    'created_at': row.created_at, 'updated_at': row.updated_at}

    def operations(self, root: str, thread_id: str, *, offset: int = 0, limit: int = 100) -> dict:
        limit = max(1, min(int(limit), MAX_PAGE))
        with Session(self.engine) as session:
            self._thread(session, root, thread_id)
            rows = session.scalars(select(Operation).where(Operation.thread_id == thread_id, Operation.root == root)
                                   .order_by(Operation.created_at, Operation.id).offset(offset).limit(limit + 1)).all()
            items = [{'operation_id': r.id, 'key': r.key, 'kind': r.kind, 'status': r.status,
                      'parent_operation_id': r.parent_operation_id, 'causation_event_id': r.causation_event_id,
                      'origin': r.origin, 'refs': r.refs, 'command_id': r.command_id, 'attempt_id': r.attempt_id,
                      'invocation_id': r.invocation_id, 'result': r.result, 'error': r.error,
                      'created_at': r.created_at, 'updated_at': r.updated_at} for r in rows[:limit]]
        return {'items': items, 'next_offset': offset + limit if len(rows) > limit else None}

    def events(self, root: str, thread_id: str, *, after: int = 0, limit: int = 100,
               operation_id: str | None = None) -> dict:
        limit = max(1, min(int(limit), MAX_PAGE))
        with Session(self.engine) as session:
            self._thread(session, root, thread_id)
            query = select(Event).where(Event.thread_id == thread_id, Event.root == root, Event.id > after)
            if operation_id is not None:
                query = query.where(Event.operation_id == operation_id)
            rows = session.scalars(query.order_by(Event.id).limit(limit + 1)).all()
            items = [{'sequence': r.id, 'event_id': r.event_id, 'kind': r.kind, 'source': r.source,
                      'operation_id': r.operation_id, 'invocation_id': r.invocation_id, 'command_id': r.command_id,
                      'parent_event_id': r.parent_event_id, 'causation_id': r.causation_id, 'payload': r.payload,
                      'truncated': r.truncated, 'redactions': r.redactions, 'recorded_at': r.recorded_at}
                     for r in rows[:limit]]
        return {'items': items, 'next_after': items[-1]['sequence'] if len(rows) > limit else None}

    def artifact(self, root: str, thread_id: str, sha256: str) -> dict:
        """Offloaded content of an event of this project's thread, verified against its digest and size."""
        with Session(self.engine) as session:
            self._thread(session, root, thread_id)
            row = session.scalar(select(Artifact).join(Event, Event.event_id == Artifact.event_id).where(
                Artifact.sha256 == sha256, Event.thread_id == thread_id, Event.root == root).limit(1))
            if row is None:
                raise LookupError(tr('journal.trace_unknown'))
            if hashlib.sha256(row.content).hexdigest() != row.sha256 or len(row.content) != row.size:
                raise JournalConflict(tr('journal.artifact_corrupt', sha256=sha256))
            return {'sha256': row.sha256, 'size': row.size, 'media': row.media,
                    'content': row.content.decode('utf-8')}

    def projection(self, operation_id: str) -> str | None:
        """Status rebuilt from the operation's transition events alone (FL14: projections are rebuildable)."""
        with Session(self.engine) as session:
            kinds = session.scalars(select(Event.kind).where(Event.operation_id == operation_id,
                                                             Event.kind.like('operation.%')).order_by(Event.id)).all()
        return kinds[-1].removeprefix('operation.').upper() if kinds else None


class _Unit:
    def __init__(self, session, transaction):
        self.session, self.transaction = session, transaction

    def __enter__(self):
        return self.session

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.transaction.commit()
            else:
                self.transaction.rollback()
        finally:
            self.session.close()
