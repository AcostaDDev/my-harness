"""P002-T020 (D304, D306, D311): pure parts of the work-map read projections. No I/O.

Status classes (T018 §5.1–5.2) with an explicit `unknown` fallback, actor circles (§5.3), bubble attribution over
T017 items, and the opaque scope, version and keyset cursor tokens (§7). A token is never authority: it only names
a read scope and a position; every query that consumes one is still filtered by the project root.
"""
import base64
import binascii
import hashlib
import json

FORMAT = 'work-map-1'
CLASSES = ('done', 'progress', 'waiting', 'failed', 'pending', 'inactive', 'unknown')
# Counter and field sources, as everywhere in the trace (T006): absence is a source, never a zero.
SOURCES = ('supplied', 'reported', 'derived', 'measured', 'absent')
# Page caps per level (D306). Every route clamps to these; nothing larger is ever read for one page.
LIMITS = {'projects': 100, 'phases': 200, 'tasks': 300, 'runs': 50, 'steps': 200, 'trace': 200, 'related': 200}
POLLING = {'active_interval_ms': 2000, 'idle_interval_ms': 10000, 'pause_when_hidden': True}
MAX_SCOPES = 10

# T018 §5.2; one table per persisted entity. Values absent here are `unknown` and keep their raw code.
_TABLE = {
    'run': {
        'done': ('COMMITTED', 'COMPLETED', 'DONE'),
        'progress': ('QUEUED', 'ACTIVE', 'PLANNING', 'PREPARING', 'EXECUTING', 'REVIEWING', 'VALIDATING',
                     'COMMITTING', 'ANSWERING', 'DISCOVERING', 'CHECKING', 'INTENT'),
        'waiting': ('ACCEPTANCE_READY',),
        'failed': ('BLOCKED', 'REVISION_LIMIT', 'RECOVERY_REQUIRED', 'INTERRUPTED', 'FAILED', 'ABORTED', 'REFUSED'),
        'inactive': ('STOPPED',),
    },
    # Stored attempt status (upper-cased result). An attempt without a result is `ACTIVE` until it settles.
    'attempt': {
        'done': ('COMPLETE', 'COMPLETED'),
        'progress': ('ACTIVE',),
        # D311: REPETITIVE is the stored output-guard stop of the CLI adapter (`repetitive`), absent from T018 §5.2.
        'failed': ('PARTIAL', 'INVALID', 'FAILED', 'TIMEOUT', 'TIMED_OUT', 'INTERRUPTED', 'REFUSED', 'REPETITIVE'),
        'inactive': ('CANCELLED',),
    },
    # Process of an attempt that has no result yet: rays only for PENDING/RUNNING (§5.3).
    'process': {
        'progress': ('PENDING', 'RUNNING'),
        'failed': ('UNCERTAIN', 'STOPPED'),
    },
    # `trace-observation-1` termination classes.
    'termination': {
        'done': ('completed',),
        'progress': ('pending',),
        'failed': ('failed', 'partial', 'invalid_stream', 'timeout', 'output_guard', 'interrupted', 'refused'),
        'inactive': ('cancelled',),
    },
    'launch': {
        'done': ('observed',),
        'progress': ('pending',),
        'failed': ('unknown_execution',),
        'inactive': ('not_invoked',),
    },
    'phase': {
        'done': ('CLOSED',),
        'progress': ('ACTIVE', 'CHECKING', 'CLOSING'),
        'waiting': ('READY_TO_CLOSE', 'NEEDS_RECONCILIATION'),
        'failed': ('BLOCKED',),
        'inactive': ('ABANDONED',),
    },
    # D311: phase operations (plan, check, close and the recorded kinds). A negative check verdict is a failed
    # slot with its raw code; a proposed plan or a stale closure waits for the owner.
    'phase_operation': {
        'done': ('READY', 'CLOSED', 'ADOPTED', 'RECORDED', 'CONSUMED'),
        'progress': ('QUEUED', 'INTENT'),
        'waiting': ('PROPOSED', 'STALE'),
        'failed': ('BLOCKED', 'REVISE', 'NOT_READY', 'INTERRUPTED', 'FAILED', 'REFUSED'),
        'inactive': ('ABANDONED', 'CANCELLED'),
    },
    'identity': {
        'pending': ('planned',),
        'inactive': ('withdrawn', 'replaced'),
    },
    'workflow_operation': {
        'done': ('COMPLETED',),
        'progress': ('INTENDED',),
        'failed': ('FAILED', 'UNCERTAIN'),
        'inactive': ('ABANDONED',),
    },
    'graph_thread': {
        'done': ('COMPLETED',),
        'progress': ('RUNNING',),
        'waiting': ('WAITING',),
        'failed': ('QUARANTINED', 'RECOVERY_REQUIRED', 'FAILED'),
        'inactive': ('CANCELLED', 'REVOKED'),
    },
    'autonomous_run': {
        'done': ('COMPLETED',),
        'progress': ('RUNNING',),
        'waiting': ('WAITING_FOR_OWNER', 'PAUSED', 'LIMIT_REACHED'),
        'failed': ('FAILED', 'RECOVERY_REQUIRED'),
        'inactive': ('REVOKED',),
    },
    'permission': {
        'done': ('GRANTED', 'CONSUMED'),
        'waiting': ('PENDING',),
        # D311: DENIED_CONSUMED (an applied denial) is persisted by the legacy run permissions, absent from T018.
        'inactive': ('DENIED', 'DENIED_CONSUMED', 'EXPIRED', 'REVOKED', 'SUPERSEDED'),
    },
    'judge_ruling': {
        'done': ('VALIDATED',),
        'waiting': ('ESCALATED',),
        'failed': ('FAILED', 'UNCERTAIN'),
    },
    'commit': {
        'done': ('COMMITTED',),
        'progress': ('INTENT',),
        'inactive': ('INVALIDATED',),
    },
    # Harness validate / format steps (derived from the run projection and the run's stops).
    'harness_step': {
        'done': ('passed',),
        'progress': ('running',),
        'failed': ('failed', 'unreadable'),
        'inactive': ('not_configured', 'not_recorded'),
    },
}
STATUS = {entity: {code: cls for cls, codes in table.items() for code in codes} for entity, table in _TABLE.items()}


def status(entity: str, code) -> dict:
    """`{code, class}`; a value without a mapping is `unknown` and keeps its raw code (never a guessed class)."""
    return {'code': code, 'class': STATUS[entity].get(code, 'unknown') if code is not None else 'unknown'}


def circle(role, roles) -> str | None:
    """R/E/J for agent roles through `roles` (the CLI role → agent table); preparation steps belong to E. Unknown
    roles stay unattributed."""
    if role == 'preparation':
        return 'E'
    return {'reviewer': 'R', 'executor': 'E', 'judge': 'J'}.get(roles.get(role))


# §5.3: the T017 topic decides the circle; permissions follow the attempt that asked.
BUBBLE_CIRCLES = {'task_gap': 'R', 'autonomous_question': 'R', 'phase_question': 'R', 'judge_escalation': 'J',
                  'phase_ready': 'H', 'limit_reached': 'H', 'recovery_required': 'H', 'failed': 'H'}


def bubble_circle(topic: str, role, roles) -> tuple[str, bool]:
    """(circle, attributed). An origin that cannot be resolved attaches to H, labelled as not attributed."""
    if topic in ('run_permission', 'standing_permission'):
        found = circle(role, roles)
        return (found, True) if found else ('H', False)
    found = BUBBLE_CIRCLES.get(topic)
    return (found, True) if found else ('H', False)


def counter(value, source: str, *, reason=None, **extra) -> dict:
    """A counter keeps its value and source; missing evidence is `absent` with a reason, never zero (INV-09)."""
    if value is None:
        return {'value': None, 'source': 'absent', 'reason': reason or 'not_observed', **extra}
    return {'value': value, 'source': source, 'reason': None, **extra}


class TokenError(ValueError):
    """A malformed scope or cursor, or one bound to another level, project or scope (`args[0]`: which)."""


class StaleCursor(Exception):
    """A cursor of a superseded version (`409 cursor_stale`): the client reloads the snapshot."""


_ALPHABET = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_')


def _encode(value) -> str:
    raw = json.dumps(value, separators=(',', ':'), sort_keys=True, ensure_ascii=True).encode('ascii')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode(text: str):
    if not isinstance(text, str) or not 1 <= len(text) <= 2048:
        raise TokenError('token')
    if any(c not in _ALPHABET for c in text):
        raise TokenError('token')
    try:
        raw = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
        return json.loads(raw.decode('ascii'))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise TokenError('token') from None


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, separators=(',', ':'), sort_keys=True).encode()).hexdigest()


def scope(level: str, *parts: str) -> str:
    """Opaque id of one read scope, echoed by the activity poll; `parts` start with the project key."""
    if level not in ARITY or len(parts) != ARITY[level] or not all(isinstance(p, str) for p in parts):
        raise TokenError('scope')
    return 's1.' + _encode([level, *parts])


# Arity of each scope: the project key plus the level's own arguments (`projects` has none).
ARITY = {'projects': 0, 'phases': 1, 'tasks': 2, 'runs': 3, 'steps': 2, 'invocation': 2, 'trace': 2, 'related': 3}


def read_scope(value) -> tuple[str, list[str]]:
    """Types and structure are checked before any value is used: a list of non-empty strings, a known level and
    that level's arity. Anything else is a `TokenError('scope')` (422), never an exception of the reader."""
    if not isinstance(value, str) or not value.startswith('s1.'):
        raise TokenError('scope')
    try:
        data = _decode(value[3:])
    except TokenError:
        raise TokenError('scope') from None
    if (not isinstance(data, list) or not data
            or not all(isinstance(p, str) and 0 < len(p) <= 200 for p in data)
            or data[0] not in ARITY or len(data) - 1 != ARITY[data[0]]):
        raise TokenError('scope')
    return data[0], data[1:]


def version(watermarks) -> str:
    """Version token of one scope: a digest of its source watermarks (insert-only sequences and row versions)."""
    return 'v1.' + _digest(watermarks)[:32]


def cursor(scope_id: str, version_token: str, key: list) -> str:
    body = {'s': scope_id, 'v': version_token, 'k': key}
    return 'c1.' + _encode(body) + '.' + _digest(body)[:16]


def read_cursor(value: str | None, scope_id: str, version_token: str, shape: tuple) -> list | None:
    """Keyset position of `value` within `scope_id`. `shape` lists the expected key types. Malformed, tampered or
    foreign cursors raise `TokenError`; a cursor of an older version of the same scope raises `StaleCursor`."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith('c1.') or value.count('.') != 2:
        raise TokenError('cursor')
    _, encoded, check = value.split('.')
    try:
        body = _decode(encoded)
    except TokenError:
        raise TokenError('cursor') from None
    if (not isinstance(body, dict) or set(body) != {'s', 'v', 'k'} or not isinstance(body['s'], str)
            or not isinstance(body['v'], str) or not isinstance(body['k'], list) or len(body['k']) != len(shape)
            or not all(type(item) is kind for item, kind in zip(body['k'], shape))
            or _digest(body)[:16] != check):
        raise TokenError('cursor')
    if body['s'] != scope_id:
        raise TokenError('cursor')
    if body['v'] != version_token:
        raise StaleCursor()
    return body['k']
