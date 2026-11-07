"""P002-T019 (D305, D310): durable observed steps of every settled managed attempt, and their bounded reads.

Settlement (the transaction that stores an attempt's result, or `confirm_stopped`) records one
`invocation.steps_pending` trace event; nothing is parsed under that writer lock. The projector then reads the sealed
evidence outside any write transaction (`agent_event` rows in run order, the parser's diagnostics, `stream_bytes`
chunks and, for records over 16 KiB, the stdout bytes verified against the sealed capture's digest and size, every
chunk digest and the record's own digest), derives `observed-step-1` steps (`core/engine/observed_steps.py`) and
writes them in bounded writer transactions as `invocation.step` events, sealing with `invocation.steps_sealed` last.

Under the writer lock, every write first checks that no terminal marker (sealed or failed) exists, and the seal
checks that the persisted step keys are exactly the derived sequence (a longer earlier write is a divergence too).
Dedupe keys make an identical replay converge; a different payload or set is an integrity failure, recorded once as
`invocation.steps_failed` and never overwritten. A crash restarts from `seq` 0. A stop request is honoured between
batches and before the seal: the marker stays pending and the next pass converges. Retention keeps an attempt's
streams while it is not sealed.

Reads are keyset pages of at most 200 steps per invocation, from SQLite only: they serve restored `query_only`
archives without checkout, registry or writes. Attempts settled before T019 have no pending marker and are not
backfilled: their reads say so and carry the persisted `trace-observation-1` counters (or the pure evaluation from
the sealed capture, labelled `derived`) and the run evidence link. Preparation and configuration-assistance
invocations are excluded lanes.
"""
from contextlib import ExitStack, contextmanager
import errno
import hashlib
import json
import logging
import os
from threading import Lock

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.adapters.streams import strict_json
from my_harness.core.engine import observed_steps as core
from my_harness.core.engine.observation import observe, termination
from my_harness.i18n import tr
from my_harness.storage.backup import MAX_FILE_BYTES, BackupError, opened, unchanged
from my_harness.storage.models import (
    ManagedAttemptRow, ManagedEventRow, ManagedProcessRow, ManagedRunRow, TraceEventRow as Event,
    UsageInvocationRow, WorkflowOperationRow as Operation,
)
from my_harness.storage.operation_journal import JournalConflict, now, record_event

logger = logging.getLogger(__name__)

PENDING, STEP, SEALED, FAILED = ('invocation.steps_pending', 'invocation.step', 'invocation.steps_sealed',
                                 'invocation.steps_failed')
SESSION_KEY = 'observed_steps_pending'
EXCLUDED_LANES = ('preparation_step', 'configuration_assistance')
STREAM_KINDS = ('agent_event', 'stream_diagnostic', 'stream_bytes')
BROKER_KINDS = ('broker.called', 'broker.result', 'tool.called', 'tool.result', 'tool.discovered')
MAX_PAGE = 200
BATCH = 250
READ_BLOCK = 65536
MAX_RECORD = 4 * 1024 * 1024 + 1  # the parser's bound on one JSONL record, plus its newline


def pending_key(invocation_id: str) -> str:
    return f'steps_pending:{invocation_id}'


def sealed_key(invocation_id: str) -> str:
    return f'steps:{invocation_id}'


def failed_key(invocation_id: str) -> str:
    return f'steps_failed:{invocation_id}'


def step_key(invocation_id: str, seq: int) -> str:
    return f'step:{invocation_id}:{seq}'


# Settlement ----------------------------------------------------------------------------------------------------------

def mark_pending(session, run: ManagedRunRow, attempt: ManagedAttemptRow, *, at: str) -> Event | None:
    """Inside the settlement transaction: the attempt's projection is owed. Attempts without a ledger row (before
    P001-T003) have no invocation to project and keep today's evidence only."""
    invocation = session.scalar(select(UsageInvocationRow).where(
        UsageInvocationRow.source_kind == 'managed_attempt', UsageInvocationRow.source_id == attempt.id))
    if invocation is None:
        return None
    process = session.get(ManagedProcessRow, attempt.id)
    payload = {'format': core.FORMAT, 'attempt_id': attempt.id, 'run_id': run.id, 'purpose': run.purpose,
               'role': json.loads(attempt.request_json).get('role'),
               'client': (process.spec or {}).get('provider') if process is not None else None}
    row = record_event(session, kind=PENDING, dedupe_key=pending_key(invocation.id), payload=payload,
                       source='derived', root=run.root, invocation_id=invocation.id, at=at)
    session.info.setdefault(SESSION_KEY, []).append(invocation.id)
    return row


def unsealed_attempt(db, attempt_id: str) -> bool:
    """Retention guard over a raw sqlite3 connection: the attempt owes a projection that is not sealed yet."""
    return db.execute(
        "SELECT 1 FROM usage_invocations u JOIN trace_events p ON p.dedupe_key = 'steps_pending:' || u.id "
        "WHERE u.source_kind = 'managed_attempt' AND u.source_id = ? AND NOT EXISTS "
        "(SELECT 1 FROM trace_events s WHERE s.dedupe_key = 'steps:' || u.id)", (attempt_id,)).fetchone() is not None


# Evidence ------------------------------------------------------------------------------------------------------------

class Unavailable:
    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return f'Unavailable({self.code!r})'


class _Failed(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class StdoutRanges:
    """Oversize record bytes from the sealed stdout (D305, T018 §6.3), one record in memory at a time.

    Before any range is trusted, the whole file is read once through the repository's no-follow opening, bounded by
    the sealed capture's size: every `stream_bytes` chunk digest, then the capture's digest and size. Without a sealed
    capture artifact there is no such proof and every range is unavailable. Each range is then read at its offset
    from the same descriptor and checked against its own digest; the file must not change meanwhile."""

    def __init__(self, artifact, chunks):
        self.artifact, self.chunks = artifact, chunks
        self.stack = ExitStack()
        self.state = None  # None (not verified yet), 'verified' or an unavailability code
        self.fd = self.before = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stack.close()

    def _verify(self):
        artifact = self.artifact
        if not (isinstance(artifact, dict) and isinstance(artifact.get('path'), str)
                and type(artifact.get('size')) is int and isinstance(artifact.get('sha256'), str)):
            raise _Failed('capture_absent')
        size = artifact['size']
        try:
            fd, before = self.stack.enter_context(opened(artifact['path'], MAX_FILE_BYTES))
        except FileNotFoundError:
            raise _Failed('stdout_missing') from None
        except BackupError:
            raise _Failed('stdout_unsafe') from None  # a link in the path, a special file or over the bound
        except OSError as error:
            raise _Failed('stdout_unsafe' if error.errno in (errno.ELOOP, errno.ENOTDIR) else
                          'stdout_unreadable') from None
        if before.st_size != size:
            raise _Failed('stdout_digest_mismatch')
        whole, expected = hashlib.sha256(), 0
        for offset, length, sha256 in self.chunks:
            if offset != expected or type(length) is not int or length <= 0 or expected + length > size:
                raise _Failed('chunks_incomplete')
            digest, left = hashlib.sha256(), length
            while left:
                block = os.read(fd, min(READ_BLOCK, left))
                if not block:
                    raise _Failed('stdout_digest_mismatch')
                digest.update(block)
                whole.update(block)
                left -= len(block)
            if digest.hexdigest() != sha256:
                raise _Failed('chunk_digest_mismatch')
            expected += length
        if expected != size:
            raise _Failed('chunks_incomplete')
        if os.read(fd, 1) or whole.hexdigest() != artifact['sha256']:
            raise _Failed('stdout_digest_mismatch')
        if not unchanged(before, os.fstat(fd)):
            raise _Failed('stdout_changed')
        self.fd, self.before = fd, before

    def read(self, reference):
        """Exact verified record bytes, bounded before reading or allocating the range."""
        offset, size, sha256 = (reference.get(k) for k in ('offset', 'size', 'sha256'))
        if type(offset) is not int or type(size) is not int or offset < 0 or size <= 0 or not isinstance(sha256, str):
            return Unavailable('reference_invalid')
        if size > MAX_RECORD:
            return Unavailable('record_too_large')
        if self.state is None:
            try:
                self._verify()
                self.state = 'verified'
            except _Failed as failure:
                self.state = failure.code
        if self.state != 'verified':
            return Unavailable(self.state)
        if offset + size > self.artifact['size']:
            return Unavailable('chunks_incomplete')
        parts, read = [], 0
        while read < size:
            block = os.pread(self.fd, size - read, offset + read)
            if not block:
                return Unavailable('stdout_digest_mismatch')
            parts.append(block)
            read += len(block)
        data = b''.join(parts)
        if not unchanged(self.before, os.fstat(self.fd)):
            return Unavailable('stdout_changed')
        if hashlib.sha256(data).hexdigest() != sha256:
            return Unavailable('record_digest_mismatch')
        return data

    def get(self, reference):
        data = self.read(reference)
        if isinstance(data, Unavailable):
            return data
        try:
            event = strict_json(data.rstrip(b'\n').decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return Unavailable('record_invalid')
        if not isinstance(event, dict) or not isinstance(event.get('type'), str):
            return Unavailable('record_invalid')
        return event


def oversize_records(artifact, chunks, references):
    """Every reference resolved at once (tests and tools); the projector resolves them one at a time instead."""
    with StdoutRanges(artifact, chunks) as ranges:
        return {seq: ranges.get(reference) for seq, reference in references.items()}


def _brokers(session, invocation_id):
    """Broker calls of the invocation with their result, logical and discovery event ids, in one ordered pass.

    A discovery event is linked only to the single broker call open when it was recorded, and only if that call has
    exactly one; calls that overlapped a discovery with others open get none."""
    rows = session.scalars(select(Event).where(Event.invocation_id == invocation_id, Event.kind.in_(BROKER_KINDS))
                           .order_by(Event.id)).all()
    by_key = {row.dedupe_key: row for row in rows}
    calls, open_calls, discoveries, ambiguous = {}, set(), {}, set()
    for row in rows:
        call_id = row.payload.get('call_id') if isinstance(row.payload, dict) else None
        if row.kind == 'broker.called' and isinstance(call_id, str):
            calls[call_id] = row
            open_calls.add(call_id)
        elif row.kind == 'broker.result' and isinstance(call_id, str):
            open_calls.discard(call_id)
        elif row.kind == 'tool.discovered':
            if len(open_calls) == 1:
                [owner] = open_calls
                discoveries.setdefault(owner, []).append(row.event_id)
            else:
                ambiguous |= open_calls
    result = []
    for call_id, row in calls.items():
        found = discoveries.get(call_id, ())
        result.append({
            'broker': row.payload.get('broker'), 'arguments_sha256': row.payload.get('arguments_sha256'),
            'call_event_id': row.event_id,
            'result_event_id': getattr(by_key.get(f'broker:result:{call_id}'), 'event_id', None),
            'logical_call_event_id': getattr(by_key.get(f'logical:call:{call_id}'), 'event_id', None),
            'logical_result_event_id': getattr(by_key.get(f'logical:result:{call_id}'), 'event_id', None),
            'discovery_event_id': found[0] if len(found) == 1 and call_id not in ambiguous else None})
    return result


# Projector -----------------------------------------------------------------------------------------------------------

class ObservedStepProjector:
    """Deterministic, idempotent and recoverable projection of pending attempts (one at a time per process; other
    processes are excluded by the terminal and set checks made under the SQLite writer lock)."""

    def __init__(self, engine, *, batch: int = BATCH):
        self.engine = engine
        self.batch = batch
        self._lock = Lock()

    @contextmanager
    def _write(self):
        with Session(self.engine) as session, session.begin():
            if session.execute(text('PRAGMA query_only')).scalar():
                raise PermissionError(tr('journal.read_only'))
            session.execute(text('UPDATE workflow_operations SET status = status WHERE 0'))  # write lock first
            yield session

    def _page(self, limit, after):
        with Session(self.engine) as session:
            return [tuple(row) for row in session.execute(text(
                "SELECT p.id, p.invocation_id FROM trace_events p WHERE p.kind = :kind AND p.id > :after "
                "AND NOT EXISTS (SELECT 1 FROM trace_events s WHERE s.dedupe_key IN "
                "('steps:' || p.invocation_id, 'steps_failed:' || p.invocation_id)) ORDER BY p.id LIMIT :limit"),
                {'kind': PENDING, 'after': int(after), 'limit': int(limit)})]

    def pending(self, limit: int = 100) -> list[str]:
        """Invocations whose projection is owed: a pending marker without a sealed or failed one, oldest first."""
        return [invocation_id for _id, invocation_id in self._page(limit, 0)]

    def _safe(self, invocation_id, stop=None):
        try:
            return self.project(invocation_id, stop=stop)
        except Exception:  # left pending: retention keeps its streams and the next pass retries it
            logger.exception('Observed-step projection of %s stays pending.', invocation_id)
            return {'invocation_id': invocation_id, 'state': 'pending'}

    def run_pending(self, limit: int = 100, *, stop=None) -> list[dict]:
        """The recovery pass: every owed invocation once, in marker order, page by page past failures; `stop` is
        checked before each invocation and, inside a projection, before each batch and the seal."""
        results, after = [], 0
        while True:
            page = self._page(limit, after)
            if not page:
                return results
            for marker_id, invocation_id in page:
                if stop is not None and stop():
                    return results
                results.append(self._safe(invocation_id, stop))
                if results[-1].get('stopped'):
                    return results
                after = marker_id

    def project_many(self, invocation_ids) -> list[dict]:
        """The ordinary path after a settlement commits; errors leave the projection pending for recovery."""
        return [self._safe(invocation_id) for invocation_id in invocation_ids]

    def _inputs(self, invocation_id):
        with Session(self.engine) as session:
            marker = session.scalar(select(Event).where(Event.dedupe_key == pending_key(invocation_id)))
            if marker is None:
                return None
            done = self._terminal(session, invocation_id)
            if done is not None:
                return {'done': done}
            invocation = session.get(UsageInvocationRow, invocation_id)
            if invocation is None or invocation.attempt_id is None:
                raise LookupError(tr('observed_steps.invocation_unknown'))
            attempt = session.get(ManagedAttemptRow, invocation.attempt_id)
            run = session.get(ManagedRunRow, attempt.run_id)
            process = session.get(ManagedProcessRow, attempt.id)
            operation = session.scalar(select(Operation).where(Operation.attempt_id == attempt.id))
            spec = process.spec if process is not None else None
            capture = process.capture if process is not None and isinstance(process.capture, dict) else None
            ended = termination(spec, process.status if process is not None else None, capture)['class']
            artifact = (capture or {}).get('artifacts', {}).get('stdout') if capture else None
            chunks = []
            query = select(ManagedEventRow.payload).where(ManagedEventRow.run_id == run.id,
                                                          ManagedEventRow.kind == 'stream_bytes')
            for payload in session.execute(query.order_by(ManagedEventRow.sequence)).scalars().yield_per(1000):
                if payload.get('attempt_id') == attempt.id and payload.get('stream') == 'stdout':
                    chunks.append((payload.get('offset'), payload.get('size'), payload.get('sha256')))
            deriver = core.Deriver(client=(spec or {}).get('provider'), run_id=run.id, attempt_id=attempt.id,
                                   termination=ended, brokers=_brokers(session, invocation_id))
            oversize = unavailable = 0
            index, at = 0, None
            query = select(ManagedEventRow).where(ManagedEventRow.run_id == run.id,
                                                  ManagedEventRow.kind.in_(STREAM_KINDS))
            with StdoutRanges(artifact, chunks) as ranges:
                for row in session.execute(query.order_by(ManagedEventRow.sequence)).scalars().yield_per(500):
                    payload = row.payload
                    if payload.get('attempt_id') != attempt.id:
                        continue
                    if row.kind == 'stream_bytes':
                        if payload.get('stream') == 'stdout':
                            at = row.recorded_at  # receipt of the chunk that carries the following newlines
                        continue
                    item = {'index': index, 'sequence': row.sequence, 'record': payload.get('record'), 'at': at}
                    index += 1
                    if row.kind == 'stream_diagnostic':
                        item['diagnostic'] = payload.get('code')
                    elif 'original' in payload:
                        item['event'] = payload['original']
                    else:
                        oversize += 1
                        item['oversize'] = True
                        reference = payload.get('original_reference')
                        resolved = (ranges.get(reference) if isinstance(reference, dict)
                                    else Unavailable('reference_invalid'))
                        if isinstance(resolved, dict):
                            item['event'] = resolved
                        else:
                            unavailable += 1
                            reference = reference if isinstance(reference, dict) else {}
                            item['unavailable'] = {'code': resolved.code, 'size': reference.get('size'),
                                                   'sha256': reference.get('sha256'), 'type': payload.get('type')}
                    deriver.feed(item)
            steps, summary = deriver.derive()
            summary.update({'client_version': (spec or {}).get('cli_version'),
                            'stdout': ({'size': artifact.get('size'), 'sha256': artifact.get('sha256')}
                                       if isinstance(artifact, dict) else None),
                            'oversize_records': oversize, 'oversize_unavailable': unavailable})
            links = {'root': run.root, 'thread_id': operation.thread_id if operation else None,
                     'operation_id': operation.id if operation else None, 'invocation_id': invocation_id}
            return {'steps': steps, 'summary': summary, 'links': links}

    @staticmethod
    def _terminal(session, invocation_id):
        return session.scalar(select(Event.kind).where(Event.dedupe_key.in_(
            (sealed_key(invocation_id), failed_key(invocation_id)))).order_by(Event.id).limit(1))

    @staticmethod
    def _settled(invocation_id, kind):
        return {'invocation_id': invocation_id, 'state': 'sealed' if kind == SEALED else 'integrity_failed',
                'written': 0}

    def _fail(self, session, invocation_id, links, at, code, **detail):
        record_event(session, kind=FAILED, dedupe_key=failed_key(invocation_id), source='derived',
                     payload={'format': core.FORMAT, 'derivation': core.DERIVATION, 'code': code, **detail},
                     at=at, **links)
        logger.error('Observed steps of %s diverge from the recorded ones (%s); nothing is overwritten.',
                     invocation_id, code)
        return {'invocation_id': invocation_id, 'state': 'integrity_failed', 'written': 0}

    def project(self, invocation_id: str, *, stop=None) -> dict:
        """`stop` (a callable) interrupts between batches and before the seal: nothing more is written, the marker
        stays pending and a later pass replays the written batches as no-ops and converges."""
        def stopped():
            if stop is not None and stop():
                logger.info('Observed-step projection of %s stopped; it stays pending.', invocation_id)
                return True
            return False

        with self._lock:
            inputs = self._inputs(invocation_id)
            if inputs is None:
                return {'invocation_id': invocation_id, 'state': 'not_pending'}
            if 'done' in inputs:
                return self._settled(invocation_id, inputs['done'])
            steps, summary, links = inputs['steps'], inputs['summary'], inputs['links']
            keys = [step_key(invocation_id, step['seq']) for step in steps]
            at = now()
            interrupted = {'invocation_id': invocation_id, 'state': 'pending', 'stopped': True}
            try:
                for start in range(0, len(steps), self.batch):
                    if stopped():
                        return interrupted
                    with self._write() as session:
                        done = self._terminal(session, invocation_id)
                        if done is not None:  # another projector finished first: its terminal marker stands
                            return self._settled(invocation_id, done)
                        for key, step in zip(keys[start:start + self.batch], steps[start:start + self.batch]):
                            record_event(session, kind=STEP, dedupe_key=key, payload=step, source='measured',
                                         at=at, **links)
                if stopped():
                    return interrupted
                with self._write() as session:
                    done = self._terminal(session, invocation_id)
                    if done is not None:
                        return self._settled(invocation_id, done)
                    persisted = set(session.scalars(select(Event.dedupe_key).where(
                        Event.invocation_id == invocation_id, Event.kind == STEP)))
                    if persisted != set(keys):  # e.g. more steps left by an earlier, longer derivation
                        return self._fail(session, invocation_id, links, at, 'integrity_step_set',
                                          persisted=len(persisted), derived=len(keys),
                                          extra=len(persisted - set(keys)))
                    record_event(session, kind=SEALED, dedupe_key=sealed_key(invocation_id), payload=summary,
                                 source='measured', at=at, **links)
            except JournalConflict as conflict:
                with self._write() as session:
                    done = self._terminal(session, invocation_id)
                    if done is not None:
                        return self._settled(invocation_id, done)
                    return self._fail(session, invocation_id, links, at, 'integrity_conflict',
                                      detail=str(conflict)[:500])
            return {'invocation_id': invocation_id, 'state': 'sealed', 'written': len(steps)}


# Reads ---------------------------------------------------------------------------------------------------------------

class ObservedSteps:
    """Read-only, bounded and per invocation; works on restored `query_only` copies (no checkout, registry or
    writes). `root`, when given, scopes the read: another project's invocation is unknown, never revealed."""

    def __init__(self, engine):
        self.engine = engine

    def _state(self, session, invocation_id, root):
        invocation = session.get(UsageInvocationRow, invocation_id)
        if invocation is None or (root is not None and invocation.root != root):
            raise LookupError(tr('observed_steps.invocation_unknown'))
        head = {'invocation_id': invocation_id, 'lane': invocation.source_kind, 'role': invocation.role,
                'agent': invocation.agent}
        if invocation.source_kind in EXCLUDED_LANES:
            return {**head, 'state': 'lane_excluded', 'reason': 'steps_not_projected_for_lane'}, None
        attempt = session.get(ManagedAttemptRow, invocation.attempt_id)
        head['evidence'] = {'run_id': attempt.run_id, 'attempt_id': attempt.id}
        if attempt.result_json is None:
            return {**head, 'state': 'not_settled'}, None
        markers = {row.kind: row for row in session.scalars(select(Event).where(Event.dedupe_key.in_((
            pending_key(invocation_id), sealed_key(invocation_id), failed_key(invocation_id)))))}
        if FAILED in markers:
            return {**head, 'state': 'integrity_failed', 'failure': markers[FAILED].payload}, None
        if SEALED in markers:
            return {**head, 'state': 'sealed', 'summary': markers[SEALED].payload}, markers[SEALED]
        if PENDING in markers:
            return {**head, 'state': 'pending'}, None
        return {**head, 'state': 'not_projected', 'reason': 'settled_before_observed_steps',
                'observation': self._observation(session, invocation_id, attempt)}, None

    @staticmethod
    def _observation(session, invocation_id, attempt):
        """No backfill (Q2): the persisted T006 counters, else the pure evaluation of the sealed capture."""
        row = session.scalar(select(Event).where(Event.dedupe_key == f'observation:{invocation_id}'))
        if row is not None:
            return {'source': 'trace', 'persisted': True, 'payload': row.payload}
        process = session.get(ManagedProcessRow, attempt.id)
        payload = observe(spec=process.spec if process else None, process_status=process.status if process else None,
                          capture=process.capture if process else None,
                          identity_present=bool(process is not None and process.identity),
                          attempt_number=attempt.number)
        return {'source': 'derived', 'persisted': False, 'payload': payload}

    def state(self, invocation_id: str, *, root: str | None = None) -> dict:
        with Session(self.engine) as session:
            return self._state(session, invocation_id, root)[0]

    def page(self, invocation_id: str, *, root: str | None = None, after: int | None = None,
             limit: int = MAX_PAGE) -> dict:
        """Steps of a sealed projection in `seq` order, keyset by the step event's position (`after`)."""
        if after is not None and (type(after) is not int or after < 0):
            raise ValueError(tr('observed_steps.cursor_invalid'))
        limit = max(1, min(int(limit), MAX_PAGE))
        with Session(self.engine) as session:
            head, sealed = self._state(session, invocation_id, root)
            if sealed is None:
                return {**head, 'items': [], 'next_after': None}
            query = select(Event).where(Event.invocation_id == invocation_id, Event.kind == STEP,
                                        Event.id < sealed.id)
            if after is not None:
                query = query.where(Event.id > after)
            rows = session.scalars(query.order_by(Event.id).limit(limit + 1)).all()
            items = [{'cursor': row.id, 'event_id': row.event_id, 'truncated': row.truncated,
                      'redactions': row.redactions, **row.payload} for row in rows[:limit]]
        return {**head, 'items': items, 'next_after': items[-1]['cursor'] if len(rows) > limit else None}
