"""P002-T020 (D304, D306, D309, D311): bounded, read-only work-map and trace projections for L0–L4 and the poll.

Projections in FL14's sense: rebuilt from persisted rows on every read, never authority, never written. Each read
opens one plain connection and scopes every query by the project's checkout root. Pages are keyset pages over stable
keys (checkout root, phase code, plan position and task code, attempt number, creation time and id, trace event id):
only the page's rows are selected and only they are enriched; counters over a whole scope are SQL aggregates. No
`history_json`, no full run history, no checkout, registry composition or provider. The same reads serve restored
`query_only` archives. Status classes, circles and tokens come from `core/engine/work_map.py`; observed steps from
T019's `ObservedSteps`; unresolved owner items from T017's `FACTS` projection, whose resolution rules are reused, not
reimplemented; standing-permission validity from T010's `PermissionLifecycle.active`.
"""
from datetime import datetime
import json
import os

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import ROLES
from my_harness.core.engine import work_map as wm
from my_harness.core.engine.observation import observe
from my_harness.services.permission_lifecycle import PermissionLifecycle
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.inbox import FACTS, Inbox, PROJECTS
from my_harness.storage.models import PermissionRecordRow, RunProjectionCycleRow as Cycle
from my_harness.storage.observed_steps import FAILED, PENDING, SEALED, ObservedSteps
from my_harness.storage.operation_journal import now
from my_harness.storage.retention import REMOVED
from my_harness.storage.run_projection import cycle_tests

TERMINAL_PHASES = ('CLOSED', 'ABANDONED')
TERMINAL_AUTONOMOUS = ('REVOKED', 'COMPLETED')
PHASE_SLOTS = ('plan', 'check', 'close')
PHASE_PURPOSES = ('phase_check', 'phase_close', 'phase_transition')
MAX_TEXT = 2000
MAX_LIST = 20
TAIL = 999_999  # attempt-number slot of the run's tail (cycles without their executor attempt, commits)
# Roles behind each circle (`cli_agents.ROLES`; preparation steps belong to E).
CIRCLE_ROLES = {name: tuple(sorted(role for role in ROLES if wm.circle(role, ROLES) == name)) +
                (('preparation',) if name == 'E' else ()) for name in ('R', 'E', 'J')}
# Trace kinds of one invocation that change what L3, L4 or its related records show.
MARKERS = (PENDING, SEALED, FAILED, 'invocation.observed')
# L4 related records: trace kinds of one invocation and the payload fields the map may carry. They are identities,
# codes and digests only (T007, T008, T009 envelopes and the bridge's own events); free text never crosses (TM17).
RELATED = {
    'knowledge.delivered': ('receipt', ('format', 'channel', 'entity_type', 'stable_id', 'revision_id', 'exposure',
                                        'failure', 'digest', 'sections', 'page')),
    'knowledge.receipt': ('receipt', ('format', 'channel', 'entity_type', 'stable_id', 'revision_id', 'exposure',
                                      'failure', 'digest', 'delivery_id', 'index', 'source_sha256', 'range',
                                      'version', 'authority', 'page')),
    'tool.discovered': ('discovery', ('format', 'action', 'catalogue_sha256', 'query_sha256', 'query_length',
                                      'results', 'page', 'id', 'version', 'outcome', 'schema_sha256')),
    'broker.called': ('broker', ('broker', 'arguments_sha256', 'call_id')),
    'broker.result': ('broker', ('call_id', 'broker', 'ok', 'operation', 'result_sha256', 'error')),
    'tool.called': ('tool', ('id', 'version', 'schema_sha256', 'key_sha256')),
    'tool.result': ('tool', ('id', 'ok', 'error', 'result_sha256', 'replayed', 'command_id')),
    'judge.requested': ('ruling', ('request_id', 'duty', 'evidence_sha256')),
    'judge.ruled': ('ruling', ('request_id', 'ruling_id', 'status', 'continuation')),
    'context.intended': ('context', ('snapshot_id', 'sha256', 'revision_id')),
    'invocation.observed': ('observation', ('format', 'provider', 'launch', 'termination', 'counters', 'usage',
                                            'reported_model', 'native_session', 'missing')),
}
GROUPS = ('records', 'permissions')


def _codes(entity, cls):
    return json.dumps(sorted(code for code, value in wm.STATUS[entity].items() if value == cls))


# A skip scan over an index: each step seeks the next distinct value, so a page of n distinct values costs n seeks
# however many rows each value has.
SKIP = """
WITH RECURSIVE k(v) AS (
    SELECT (SELECT min({column}) FROM {table} WHERE {where} AND {column} > :after)
    UNION ALL
    SELECT (SELECT min({column}) FROM {table} WHERE {where} AND {column} > k.v) FROM k WHERE k.v IS NOT NULL
    LIMIT :limit)
SELECT v FROM k WHERE v IS NOT NULL
"""

# Whole-database watermarks for L0: the latest insert-only sequences (every run, phase and autonomous change appends
# its event) and the small mutable tables, each one indexed seek or small table.
GLOBAL = """
SELECT (SELECT max(id) FROM managed_events) AS events, (SELECT max(id) FROM phase_events) AS phase_events,
       (SELECT max(id) FROM trace_events) AS trace, (SELECT max(id) FROM autonomous_events) AS autonomous_events,
       (SELECT count(*) || ':' || coalesce(sum(version), 0) FROM autonomous_runs) AS autonomous,
       (SELECT max(rowid) FROM permission_records) AS permissions,
       (SELECT count(*) FROM knowledge_revisions WHERE status = 'ACCEPTED') AS revisions,
       (SELECT max(rowid) FROM knowledge_projects) AS knowledge,
       (SELECT count(*) || ':' || coalesce(sum(version), 0) FROM registered_projects) AS registry,
       (SELECT count(*) || ':' || coalesce(sum(version), 0) FROM project_preparation_operations WHERE reserved = 1)
           AS preparation,
       (SELECT group_concat(id || '@' || status || '@' || updated_at) FROM configuration_operations
         WHERE kind = 'ASSIST' AND status = 'INTENDED') AS assistance
"""

# Per-root watermarks: row counts and version sums (every run, phase and autonomous event increments its row's
# version) and the latest insert-only sequences of the root.
WATERMARKS = """
SELECT (SELECT count(*) || ':' || coalesce(sum(r.version), 0) FROM managed_runs r WHERE r.root = :root) AS runs,
       (SELECT count(*) || ':' || coalesce(sum(p.version), 0) FROM managed_phases p WHERE p.root = :root) AS phases,
       (SELECT count(*) || ':' || coalesce(sum(a.version), 0) FROM autonomous_runs a WHERE a.root = :root) AS autonomous,
       (SELECT max(t.id) FROM trace_events t WHERE t.root = :root) AS trace,
       (SELECT max(v.number) FROM knowledge_projects k JOIN knowledge_revisions v ON v.project_id = k.id
         AND v.status = 'ACCEPTED' WHERE k.root = :root) AS revision,
       (SELECT max(x.sequence) FROM knowledge_projects k JOIN permission_records x ON x.project_id = k.id
         WHERE k.root = :root) AS permissions,
       (SELECT group_concat(g.id || '@' || g.version) FROM registered_projects g
         WHERE g.root = :root AND g.status = 'ACTIVE') AS registry
"""

# Attempts started without a result whose process is PENDING or RUNNING (§5.3), through the partial index of open
# attempts. Chat turns carry their conversation's scope (phase or task run).
ACTIVE = """
SELECT 'managed_attempt' AS source_kind, a.id AS attempt_id, a.run_id, a.number, a.started_at, r.root, r.purpose,
       r.phase_id, r.task_id, p.status AS process, i.id AS invocation_id, i.agent,
       COALESCE(i.role, json_extract(a.request_json, '$.role')) AS role,
       cp.code AS chat_phase, c.task_run_id AS chat_run, ct.task_id AS chat_task, ct.phase_id AS chat_task_phase
FROM managed_attempts a
JOIN managed_runs r ON r.id = a.run_id
JOIN managed_processes p ON p.attempt_id = a.id
LEFT JOIN usage_invocations i ON i.source_kind = 'managed_attempt' AND i.source_id = a.id
LEFT JOIN chat_turns t ON t.run_id = r.id AND r.purpose = 'chat'
LEFT JOIN chat_conversations c ON c.id = t.conversation_id
LEFT JOIN managed_phases cp ON cp.id = c.phase_id AND cp.root = r.root
LEFT JOIN managed_runs ct ON ct.id = c.task_run_id AND ct.root = r.root
WHERE a.result_json IS NULL AND p.status IN ('PENDING', 'RUNNING')
  AND (:root IS NULL OR r.root = :root)
ORDER BY a.started_at, a.id
"""

# Project preparation in progress (a reserved operation): executor steps are E invocations with their own ledger
# rows (no managed attempt is manufactured); command steps are deterministic Harness work.
PREPARATION = """
SELECT o.root, o.id AS operation_id, s.id AS step_id, s.number, json_extract(s.spec, '$.kind') AS kind,
       p.status AS process, i.id AS invocation_id, i.role, i.agent, i.started_at
FROM project_preparation_operations o  -- CROSS JOIN fixes the order: reserved operations first (partial index)
CROSS JOIN project_preparation_steps s ON s.operation_id = o.id
CROSS JOIN managed_processes p ON p.id = s.id AND p.preparation_id = o.id
LEFT JOIN usage_invocations i ON i.source_kind = 'preparation_step' AND i.source_id = s.id
WHERE o.reserved = 1 AND p.status IN ('PENDING', 'RUNNING') AND (:root IS NULL OR o.root = :root)
ORDER BY s.number
"""

# Configuration assistance in progress. Only a project-scoped one is attributable (its ledger row names the
# registered project); a global one has no project and is reported as unscoped.
ASSISTANCE = """
SELECT o.id AS operation_id, json_extract(o.payload, '$.process.status') AS process, i.id AS invocation_id, i.role,
       i.agent, i.started_at, i.project_id, g.root
FROM configuration_operations o
LEFT JOIN usage_invocations i ON i.source_kind = 'configuration_assistance' AND i.source_id = o.id
LEFT JOIN registered_projects g ON g.id = i.project_id AND g.status = 'ACTIVE'
WHERE o.kind = 'ASSIST' AND o.status = 'INTENDED'
  AND json_extract(o.payload, '$.process.status') IN ('PENDING', 'RUNNING')
ORDER BY i.started_at, o.id
"""

# Deterministic Harness work: an active job holding the checkout in a deterministic stage, or a running
# autonomous supervisor.
HARNESS = """
SELECT r.root, r.id AS run_id, r.phase_id, r.task_id, r.stage AS stage, r.status AS status, 'stage' AS reason
FROM checkout_locks l JOIN managed_jobs j ON j.id = l.job_id JOIN managed_runs r ON r.id = j.run_id
WHERE j.status = 'ACTIVE' AND (r.stage IN ('validation', 'commit', 'formatter') OR r.status IN ('VALIDATING', 'COMMITTING'))
UNION ALL
SELECT a.root, NULL, NULL, NULL, NULL, a.status, 'autonomous_supervisor' FROM autonomous_runs a WHERE a.status = 'RUNNING'
"""

# Latest task run per (phase, task) of the given phases and tasks, with the run count; window over the scope index.
LATEST = """
SELECT * FROM (
    SELECT id, phase_id, task_id, status, stage, revisions, revision_limit, created_at, updated_at, version,
           row_number() OVER (PARTITION BY phase_id, task_id ORDER BY created_at DESC, id) AS rn,
           count(*) OVER (PARTITION BY phase_id, task_id) AS runs
    FROM managed_runs WHERE root = :root AND purpose = 'task' AND phase_id IN (SELECT value FROM json_each(:phases))
      AND (:tasks IS NULL OR task_id IN (SELECT value FROM json_each(:tasks)))
) WHERE rn = 1
"""

# Task nodes of the page's phases, counted in SQL: the plan, the accepted identities of the phase and the run-only
# tasks. Totals exclude inactive nodes (replaced, withdrawn without a run, latest run inactive).
TASK_COUNTS = """
WITH page(code) AS (SELECT value FROM json_each(:phases)),
plan(phase, task) AS (SELECT p.code, j.value FROM managed_phases p JOIN page ON page.code = p.code,
                      json_each(p.definition, '$.tasks') j WHERE p.root = :root),
ident(phase, task, status) AS (
    SELECT ph.code, t.code, json_extract(v.content, '$.status') FROM knowledge_revision_links l
    JOIN knowledge_items ph ON ph.id = l.target_item_id AND ph.kind = 'phase' JOIN page ON page.code = ph.code
    JOIN knowledge_items t ON t.id = l.source_item_id AND t.kind = 'task'
    JOIN knowledge_revision_members m ON m.revision_id = l.revision_id AND m.item_id = t.id
    JOIN knowledge_item_versions v ON v.id = m.version_id
    WHERE l.revision_id = :rev AND l.kind = 'part_of'),
latest(phase, task, status) AS (
    SELECT phase_id, task_id, status FROM (
        SELECT phase_id, task_id, status, row_number() OVER (PARTITION BY phase_id, task_id
                                                             ORDER BY created_at DESC, id) AS rn
        FROM managed_runs WHERE root = :root AND purpose = 'task' AND phase_id IN (SELECT code FROM page))
    WHERE rn = 1),
replaced(task) AS (SELECT t.code FROM knowledge_revision_links l JOIN knowledge_items t ON t.id = l.target_item_id
                   WHERE l.revision_id = :rev AND l.kind = 'replaces'),
nodes(phase, task) AS (SELECT phase, task FROM plan UNION SELECT phase, task FROM ident
                       UNION SELECT phase, task FROM latest)
SELECT n.phase, count(*) AS nodes,
       sum(CASE WHEN n.task IN (SELECT task FROM replaced) THEN 0
                WHEN r.status IS NOT NULL THEN r.status NOT IN (SELECT value FROM json_each(:inactive_runs))
                WHEN i.status IS NOT NULL THEN i.status NOT IN (SELECT value FROM json_each(:inactive_identity))
                ELSE 1 END) AS total,
       sum(CASE WHEN n.task NOT IN (SELECT task FROM replaced) AND r.status = 'COMMITTED' THEN 1 ELSE 0 END)
           AS committed
FROM nodes n LEFT JOIN latest r ON r.phase = n.phase AND r.task = n.task
LEFT JOIN ident i ON i.phase = n.phase AND i.task = n.task
GROUP BY n.phase
"""

# Phases of one root, counted in SQL: instances, accepted identities and run-only codes.
PHASE_COUNTS = """
WITH inst(code, status) AS (SELECT code, status FROM managed_phases WHERE root = :root),
ident(code, status) AS (
    SELECT i.code, json_extract(v.content, '$.status') FROM knowledge_revision_members m
    JOIN knowledge_items i ON i.id = m.item_id AND i.kind = 'phase' JOIN knowledge_item_versions v ON v.id = m.version_id
    WHERE m.revision_id = :rev),
runs(code) AS (SELECT DISTINCT phase_id FROM managed_runs WHERE root = :root AND purpose = 'task'),
codes(code) AS (SELECT code FROM inst UNION SELECT code FROM ident UNION SELECT code FROM runs)
SELECT count(*) AS nodes,
       sum(CASE WHEN inst.status IS NOT NULL THEN inst.status NOT IN (SELECT value FROM json_each(:inactive_phase))
                WHEN ident.status IS NOT NULL THEN ident.status NOT IN (SELECT value FROM json_each(:inactive_identity))
                ELSE 1 END) AS total,
       coalesce(sum(inst.status = 'CLOSED'), 0) AS closed
FROM codes LEFT JOIN inst ON inst.code = codes.code LEFT JOIN ident ON ident.code = codes.code
"""

# Permission requests an attempt raised: legacy run requests (with the existing view's effective EXPIRED) and T010
# request records, keyset by (created_at, id). T010 validity is computed afterwards, for the page rows only.
PERMISSIONS = """
SELECT * FROM (
    SELECT 'run_permission' AS source, p.id,
           CASE WHEN p.expires_at <= :now AND p.status IN ('PENDING', 'GRANTED', 'DENIED') THEN 'EXPIRED'
                ELSE p.status END AS status,
           p.created_at, p.expires_at, NULL AS project_id
    FROM permission_requests p WHERE p.run_id = :run
      AND json_extract(p.request, '$.source_attempt_id') = :attempt
    UNION ALL
    SELECT 'standing_permission', x.id, NULL, x.created_at, json_extract(x.payload, '$.expires_at'), x.project_id
    FROM permission_records x JOIN knowledge_projects k ON k.id = x.project_id AND k.root = :root
    WHERE x.kind = 'request' AND json_extract(x.payload, '$.source_attempt_id') = :attempt)
WHERE :created IS NULL OR created_at > :created OR (created_at = :created AND id > :id)
ORDER BY created_at, id LIMIT :limit
"""

# Aggregate of the same requests for the version token: counts, versions, the latest T010 record and how many
# legacy requests or T010 ancestries have expired by now (time changes validity without a write).
PERMISSION_MARKS = """
WITH RECURSIVE requests(id, payload, project_id) AS (
    SELECT x.id, x.payload, x.project_id FROM permission_records x
    JOIN knowledge_projects k ON k.id = x.project_id AND k.root = :root
    WHERE x.kind = 'request' AND json_extract(x.payload, '$.source_attempt_id') = :attempt),
chain(request, id, payload) AS (
    SELECT id, id, payload FROM requests
    UNION
    SELECT r.id, g.id, g.payload FROM requests r JOIN permission_records g
      ON g.project_id = r.project_id AND g.kind = 'grant' AND json_extract(g.payload, '$.request_id') = r.id
    UNION
    SELECT chain.request, parent.id, parent.payload FROM permission_records parent JOIN chain
      ON parent.id = json_extract(chain.payload, '$.parent'))
SELECT (SELECT count(*) || ':' || coalesce(sum(version), 0) || ':' || coalesce(sum(expires_at <= :now), 0)
        FROM permission_requests WHERE run_id = :run AND json_extract(request, '$.source_attempt_id') = :attempt)
           AS legacy,
       (SELECT count(*) FROM requests) AS requests,
       (SELECT max(x.sequence) FROM permission_records x JOIN knowledge_projects k ON k.id = x.project_id
         AND k.root = :root) AS sequence,
       (SELECT count(*) FROM chain WHERE json_extract(payload, '$.expires_at') <= :now) AS expired
"""


class MapNotFound(LookupError):
    """Unknown or foreign project, phase, task, run or invocation: answered alike, never revealed (TM18)."""


def _rows(db, sql, **params):
    return [dict(row) for row in db.execute(text(sql), params).mappings()]


def _json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _text(value, *, source='supplied', reason='no_accepted_identity'):
    """A bounded knowledge text with its source; absent (with a reason) when the record has none."""
    if not isinstance(value, str):
        return {'value': None, 'source': 'absent', 'reason': reason, 'truncated': False}
    truncated = len(value) > MAX_TEXT
    return {'value': value[:MAX_TEXT - 1] + '…' if truncated else value, 'source': source, 'reason': None,
            'truncated': truncated}


def _short(value):
    if not isinstance(value, str):
        return value
    return value if len(value) <= MAX_TEXT else value[:MAX_TEXT - 1] + '…'


def _bounded(value, depth=0):
    """Allowlisted payload fields keep scalars (strings bounded) and small structures of the same."""
    if isinstance(value, str):
        return value if len(value) <= 200 else value[:199] + '…'
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= 4:
        return None
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:MAX_LIST]]
    if isinstance(value, dict):
        return {str(k)[:64]: _bounded(v, depth + 1) for k, v in list(value.items())[:MAX_LIST]}
    return None


def _ms(start, end):
    try:
        delta = datetime.fromisoformat(end.replace('Z', '+00:00')) - datetime.fromisoformat(start.replace('Z', '+00:00'))
    except (AttributeError, ValueError, TypeError):
        return None
    value = round(delta.total_seconds() * 1000)
    return value if value >= 0 else None


def acceptance(raw) -> dict:
    """The run projection's acceptance decision: absent (never evaluated), rejected (`eligible = false`, with its
    deterministic reasons) or eligible. Eligibility is not a commit; the commit is reported separately."""
    data = _json(raw)
    if data is None:
        return {'state': 'absent', 'eligible': None, 'reasons': [], 'source': 'absent', 'reason': 'not_evaluated'}
    if not isinstance(data, dict) or not isinstance(data.get('eligible'), bool):
        return {'state': 'unknown', 'eligible': None, 'reasons': [], 'source': 'derived', 'reason': 'unreadable'}
    reasons = [_bounded(r) for r in data.get('reasons') or [] if isinstance(r, str)][:MAX_LIST]
    return {'state': 'eligible' if data['eligible'] else 'rejected', 'eligible': data['eligible'],
            'reasons': reasons, 'source': 'derived', 'reason': None}


class WorkMap:
    def __init__(self, engine, projects=None, configuration=None, clock=now):
        self.engine = engine
        self.registered = dict(projects or {})  # registered UI ids → checkout roots (ordinary mode only)
        self.configuration = dict(configuration or {})  # root → configured agents (`agents_view`), never in archives
        self.clock = clock

    # --- identity and isolation -------------------------------------------------------------------------------

    @staticmethod
    def _archive(db) -> bool:
        return db.scalar(text('PRAGMA user_version')) == RESTORED_USER_VERSION

    def _identities(self, db, roots):
        configured = {root: ident for ident, root in self.registered.items()}
        roots = sorted(roots)
        found = {row['root']: row for row in _rows(db, PROJECTS, roots=json.dumps(roots))}
        registry = {row['root']: row['id'] for row in _rows(db, """
            SELECT root, id FROM registered_projects WHERE status = 'ACTIVE'
              AND root IN (SELECT value FROM json_each(:roots))""", roots=json.dumps(roots))}
        result = []
        for root in roots:
            row = found.get(root) or {}
            registered = configured.get(root)
            key = row.get('project_id') or registered
            if key is None:
                continue
            name, source = ((registered, 'registered') if registered else (registry[root], 'registry')
                            if root in registry else (os.path.basename(root.rstrip('/')) or key, 'root_basename'))
            result.append({'root': root, 'key': key, 'name': name, 'name_source': source,
                           'knowledge_project_id': row.get('knowledge_id'), 'registered_project_id': registered})
        return result

    def _project(self, db, project: str) -> dict:
        try:
            root = Inbox(self.engine, self.registered)._root(db, project)
        except LookupError:
            raise MapNotFound(project) from None
        [identity] = self._identities(db, [root]) or [None]
        if identity is None:
            raise MapNotFound(project)
        return identity

    @staticmethod
    def _head(identity):
        return {k: identity[k] for k in ('key', 'name', 'knowledge_project_id', 'registered_project_id')}

    @staticmethod
    def _skip(db, table, column, where, after, limit, **params):
        return [row[0] for row in db.execute(text(SKIP.format(table=table, column=column, where=where)),
                                             {'after': after, 'limit': limit, **params})]

    def _configured(self, root=None):
        """Digest input of the configuration the responses show (every root, or one)."""
        if root is None:
            return json.dumps(self.configuration, sort_keys=True, default=str)
        return json.dumps(self.configuration.get(root), sort_keys=True, default=str)

    # --- shared sources ---------------------------------------------------------------------------------------

    def _active(self, db, root=None) -> list[dict]:
        """Every active invocation attributable to a project: managed attempts (chat included), preparation
        executor steps and project-scoped configuration assistance, each from its own ledger."""
        result = []
        for row in _rows(db, ACTIVE, root=root):
            chat = row['purpose'] == 'chat'
            scope = ({'phase': row['chat_task_phase'] or row['chat_phase'], 'task': row['chat_task'],
                      'run_id': row['chat_run']} if chat else
                     {'phase': row['phase_id'], 'task': row['task_id'] if row['purpose'] == 'task' else None,
                      'run_id': row['run_id']})
            result.append({'root': row['root'], 'source_kind': 'managed_attempt',
                           'invocation_id': row['invocation_id'], 'attempt_id': row['attempt_id'],
                           'run_id': row['run_id'], 'number': row['number'], 'role': row['role'],
                           'circle': wm.circle(row['role'], ROLES), 'agent': row['agent'], 'lane': row['purpose'],
                           'chat': chat, 'scope': scope, 'process': row['process'], 'started_at': row['started_at']})
        for row in _rows(db, PREPARATION, root=root):
            if row['kind'] != 'executor':
                continue  # preparation commands are deterministic Harness work (`_harness`)
            result.append({'root': row['root'], 'source_kind': 'preparation_step',
                           'invocation_id': row['invocation_id'], 'attempt_id': None, 'run_id': None,
                           'number': row['number'], 'role': 'preparation', 'circle': 'E', 'agent': row['agent'],
                           'lane': 'preparation', 'chat': False, 'scope': {'phase': None, 'task': None, 'run_id': None},
                           'process': row['process'], 'started_at': row['started_at']})
        for row in _rows(db, ASSISTANCE):
            if row['root'] is None or (root is not None and row['root'] != root):
                continue  # a global assistance has no project scope (`activity.unscoped_invocations`)
            result.append({'root': row['root'], 'source_kind': 'configuration_assistance',
                           'invocation_id': row['invocation_id'], 'attempt_id': None, 'run_id': None, 'number': None,
                           'role': row['role'], 'circle': wm.circle(row['role'], ROLES), 'agent': row['agent'],
                           'lane': 'configuration_assistance', 'chat': False,
                           'scope': {'phase': None, 'task': None, 'run_id': None}, 'process': row['process'],
                           'started_at': row['started_at']})
        return result

    def _unscoped(self, db) -> list[dict]:
        return [{'invocation_id': row['invocation_id'], 'operation_id': row['operation_id'], 'role': row['role'],
                 'lane': 'configuration_assistance', 'process': row['process'], 'reason': 'global_scope'}
                for row in _rows(db, ASSISTANCE) if row['root'] is None]

    def _harness(self, db, root=None) -> dict:
        found = {}
        for row in _rows(db, HARNESS):
            if root is None or row['root'] == root:
                found.setdefault(row['root'], []).append(
                    {'reason': row['reason'], 'run_id': row['run_id'], 'phase': row['phase_id'],
                     'task': row['task_id'], 'stage': row['stage'], 'status': row['status']})
        for row in _rows(db, PREPARATION, root=root):
            if row['kind'] != 'executor':
                found.setdefault(row['root'], []).append(
                    {'reason': 'preparation_command', 'run_id': None, 'phase': None, 'task': None,
                     'stage': row['kind'], 'status': row['process']})
        return found

    def _bubbles(self, db, root=None) -> list[dict]:
        """Unresolved, non-notification T017 items (deduplicated by T017), each attributed to one circle."""
        rows = _rows(db, FACTS + """
            SELECT id, kind, topic, root, phase_id, task_id, run_id, evidence_id FROM items
            WHERE NOT resolved AND kind != 'notification' ORDER BY id""", root=root, now=self.clock())
        attempts = [row['evidence_id'] for row in rows if row['topic'] in ('run_permission', 'standing_permission')
                    and row['evidence_id']]
        roles = {row['id']: row['role'] for row in _rows(db, """
            SELECT a.id, COALESCE(i.role, json_extract(a.request_json, '$.role')) AS role FROM managed_attempts a
            LEFT JOIN usage_invocations i ON i.source_kind = 'managed_attempt' AND i.source_id = a.id
            WHERE a.id IN (SELECT value FROM json_each(:ids))""", ids=json.dumps(attempts))} if attempts else {}
        result = []
        for row in rows:
            role = roles.get(row['evidence_id'])
            circle, attributed = wm.bubble_circle(row['topic'], role, ROLES)
            if row['topic'] == 'phase_question' and row['run_id'] is None:
                circle, attributed = 'H', False  # raised outside a check: no agent origin to attach to
            result.append({'id': row['id'], 'kind': row['kind'], 'topic': row['topic'], 'circle': circle,
                           'attributed': attributed, 'root': row['root'], 'phase': row['phase_id'],
                           'task': row['task_id'], 'run_id': row['run_id'], 'attempt_id': row['evidence_id']
                           if row['topic'] in ('run_permission', 'standing_permission') else None})
        return result

    @staticmethod
    def _bubble_view(items, *, identities=False):
        view = {'total': len(items), 'source': 'derived', 'by_kind': {}, 'by_circle': {}, 'unattributed': 0}
        for item in items:
            view['by_kind'][item['kind']] = view['by_kind'].get(item['kind'], 0) + 1
            view['by_circle'][item['circle']] = view['by_circle'].get(item['circle'], 0) + 1
            view['unattributed'] += not item['attributed']
        if identities:
            view['items'] = [{k: item[k] for k in ('id', 'kind', 'topic', 'circle', 'attributed')}
                             for item in items[:MAX_LIST]]
            view['items_truncated'] = len(items) > MAX_LIST
        return view

    @staticmethod
    def _active_view(item):
        return {k: item[k] for k in ('source_kind', 'invocation_id', 'attempt_id', 'run_id', 'number', 'role',
                                     'circle', 'agent', 'lane', 'chat', 'scope', 'process', 'started_at')}

    def _latest(self, db, root, phase=None, task=None):
        """The most recent persisted invocation of each circle within an element (project, phase or task): the
        circle's navigation target to L4. Ordered candidate branches per role and effective owner."""
        found = {}
        for name, roles in CIRCLE_ROLES.items():
            branches, params = [], {'root': root, 'phase': phase, 'task': task}
            for n, role in enumerate(roles):
                params[f'role{n}'] = role
                conditions = [f"root = :root AND role = :role{n} AND purpose != 'chat' "
                              + ('AND phase_code = :phase ' if phase is not None else '')
                              + ('AND task_id = :task ' if task is not None else '')]
                # A chat run keeps CHAT identifiers; the conversation owns its effective scope.
                conditions.append(f"""root = :root AND role = :role{n} AND purpose = 'chat'
                    AND EXISTS (SELECT 1 FROM chat_turns t JOIN chat_conversations c
                      ON c.id = t.conversation_id AND c.root = :root
                      LEFT JOIN managed_phases p ON p.id = c.phase_id AND p.root = c.root
                      LEFT JOIN managed_runs r ON r.id = c.task_run_id AND r.root = c.root
                      WHERE t.run_id = usage_invocations.run_id
                        AND (:phase IS NULL OR coalesce(r.phase_id, p.code) = :phase)
                        AND (:task IS NULL OR r.task_id = :task))""")
                for condition in conditions:
                    branches.append(f"""SELECT * FROM (SELECT id, role, source_kind, started_at FROM usage_invocations
                        WHERE {condition} ORDER BY started_at DESC, id DESC LIMIT 1)""")
                if phase is None and task is None:
                    # Historical ownership survives logical retirement; operation admission is separate.
                    # One ordered seek per registered project, including settled assistance operations.
                    branches.append(f"""SELECT i.id, i.role, i.source_kind, i.started_at FROM registered_projects g
                        JOIN usage_invocations i ON i.id = (SELECT id FROM usage_invocations
                          WHERE project_id = g.id AND role = :role{n} AND source_kind = 'configuration_assistance'
                          ORDER BY started_at DESC, id DESC LIMIT 1)
                        JOIN configuration_operations o ON o.id = i.source_id AND o.kind = 'ASSIST'
                        WHERE g.root = :root""")
            rows = _rows(db, 'SELECT * FROM (' + ' UNION ALL '.join(branches)
                         + ') ORDER BY started_at DESC, id DESC LIMIT 1', **params)
            found[name] = ({'invocation_id': rows[0]['id'], 'role': rows[0]['role'], 'lane': rows[0]['source_kind'],
                            'started_at': rows[0]['started_at']} if rows else None)
        return found

    def _circles(self, db, root, active, harness, *, bubbles=(), phase=None, task=None):
        """R, E and H always; J with a judge profile or where a judge actually ran (honest history). Each circle
        carries its latest invocation in the element (inert without one), its bubbles and whether it waits."""
        configured = self.configuration.get(root) or {}
        latest = self._latest(db, root, phase, task)
        result = []
        for name in ('R', 'E', 'J', 'H'):
            mine = [a for a in active if a['circle'] == name]
            marks = [b for b in bubbles if b['circle'] == name]
            shown = ('always' if name != 'J' else 'judge_profile' if configured.get('judge')
                     else 'judge_history' if latest['J'] or mine or marks else None)
            if shown is None:
                continue
            target = latest.get(name)
            result.append({'circle': name, 'shown': shown,
                           'active': bool(harness) if name == 'H' else bool(mine),
                           'active_invocations': len(mine) if name != 'H' else 0,
                           'chat': any(a['chat'] for a in mine), 'harness': harness if name == 'H' else [],
                           'bubbles': len(marks), 'waiting': bool(marks),
                           'latest_invocation': target, 'inert': target is None and not mine})
        return result

    def _knowledge(self, db, project_id):
        if project_id is None:
            return None
        row = db.execute(text("""SELECT id, number, project_id FROM knowledge_revisions WHERE project_id = :p
            AND status = 'ACCEPTED' ORDER BY number DESC LIMIT 1"""), {'p': project_id}).mappings().first()
        return dict(row) if row else None

    def _root_version(self, db, identity, *, bubbles=None, active=None, harness=None) -> str:
        root = identity['root']
        bubbles = self._bubbles(db, root) if bubbles is None else bubbles
        active = self._active(db, root) if active is None else active
        harness = self._harness(db, root).get(root, []) if harness is None else harness
        marks = _rows(db, WATERMARKS, root=root)[0]
        return wm.version({'root': marks, 'bubbles': [b['id'] for b in bubbles],
                           'active': [[a['source_kind'], a['attempt_id'] or a['invocation_id'], a['process']]
                                      for a in active],
                           'harness': harness, 'configured': self._configured(root)})

    # --- L0: projects -----------------------------------------------------------------------------------------

    def _page_roots(self, db, after, limit):
        """The next `limit` checkout roots after `after`, by skip scans and indexed ranges of each source."""
        found = set(self._skip(db, 'managed_runs', 'root', '1', after, limit))
        found |= set(self._skip(db, 'managed_phases', 'root', '1', after, limit))
        found |= set(db.scalars(text("SELECT root FROM knowledge_projects WHERE root > :a ORDER BY root LIMIT :n"),
                                {'a': after, 'n': limit}))
        found |= set(db.scalars(text("""SELECT root FROM registered_projects WHERE status = 'ACTIVE' AND root > :a
            ORDER BY root LIMIT :n"""), {'a': after, 'n': limit}))
        found |= {root for root in self.registered.values() if root > after}
        return sorted(found)[:limit]

    def _projects_version(self, db, bubbles, active, harness):
        return wm.version({'global': _rows(db, GLOBAL)[0], 'registered': sorted(self.registered.items()),
                           'bubbles': [b['id'] for b in bubbles],
                           'active': [[a['source_kind'], a['attempt_id'] or a['invocation_id'], a['process']]
                                      for a in active],
                           'harness': json.dumps(harness, sort_keys=True), 'configured': self._configured()})

    def projects(self, *, cursor=None, limit=wm.LIMITS['projects']) -> dict:
        limit = max(1, min(int(limit), wm.LIMITS['projects']))
        with self.engine.connect() as db:
            bubbles, active, harness = self._bubbles(db), self._active(db), self._harness(db)
            scope = wm.scope('projects')
            version = self._projects_version(db, bubbles, active, harness)
            after = wm.read_cursor(cursor, scope, version, (str,))
            start = ''
            if after is not None:
                try:
                    start = self._project(db, after[0])['root']
                except MapNotFound:
                    raise wm.TokenError('cursor') from None
            roots = self._page_roots(db, start, limit + 1)
            identities = self._identities(db, roots[:limit])
            items = [self._project_card(db, p, [b for b in bubbles if b['root'] == p['root']],
                                        [a for a in active if a['root'] == p['root']], harness.get(p['root'], []))
                     for p in identities]
            return {'format': wm.FORMAT, 'level': 'projects', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'items': items,
                    'next_cursor': wm.cursor(scope, version, [identities[-1]['key']])
                    if len(roots) > limit and identities else None}

    def _replaced(self, db, revision, tasks=None):
        if revision is None:
            return set()
        return set(db.scalars(text("""SELECT t.code FROM knowledge_revision_links l
            JOIN knowledge_items t ON t.id = l.target_item_id WHERE l.revision_id = :rev AND l.kind = 'replaces'
              AND (:tasks IS NULL OR t.code IN (SELECT value FROM json_each(:tasks)))"""),
            {'rev': revision['id'], 'tasks': None if tasks is None else json.dumps(tasks)}))

    def _project_card(self, db, identity, bubbles, active, harness):
        root = identity['root']
        revision = self._knowledge(db, identity['knowledge_project_id'])
        counts = _rows(db, PHASE_COUNTS, root=root, rev=revision['id'] if revision else None,
                       inactive_phase=_codes('phase', 'inactive'), inactive_identity=_codes('identity', 'inactive'))[0]
        autonomous = db.execute(text("""
            SELECT r.id, r.status, r.reason, r.created_at, r.updated_at, json_extract(a.policy, '$.bounds') AS bounds
            FROM autonomous_runs r LEFT JOIN autonomous_authorizations a ON a.id = r.authorization_id
            WHERE r.root = :root ORDER BY r.created_at DESC, r.id DESC LIMIT 1"""), {'root': root}).mappings().first()
        open_row = db.execute(text("""SELECT code, status FROM managed_phases WHERE root = :root
            AND status NOT IN ('CLOSED', 'ABANDONED')"""), {'root': root}).mappings().first()
        open_phase = None
        failed_tasks, waiting_tasks = [], []
        if open_row is not None:
            [open_phase] = self._phase_nodes(db, root, revision, [open_row['code']])
            replaced = self._replaced(db, revision)
            flagged = json.loads(_codes('run', 'failed')) + json.loads(_codes('run', 'waiting'))
            for row in _rows(db, LATEST + " AND status IN (SELECT value FROM json_each(:flagged))", root=root,
                             phases=json.dumps([open_row['code']]), tasks=None, flagged=json.dumps(flagged)):
                if row['task_id'] in replaced:
                    continue
                cls = wm.status('run', row['status'])['class']
                (failed_tasks if cls == 'failed' else waiting_tasks).append((row['task_id'], row['status']))
        auto_status = wm.status('autonomous_run', autonomous['status']) if autonomous else None
        errors = []
        if auto_status and auto_status['class'] == 'failed':
            errors.append({'kind': 'autonomous_run', 'id': autonomous['id'], 'status': auto_status})
        if open_phase and open_phase['status']['class'] == 'failed':
            errors.append({'kind': 'phase', 'id': open_phase['code'], 'status': open_phase['status']})
        errors += [{'kind': 'task', 'id': task, 'status': wm.status('run', code)} for task, code in sorted(failed_tasks)]
        total, closed = counts['total'] or 0, counts['closed'] or 0
        if errors:
            cls = 'failed'
        elif bubbles or waiting_tasks or (auto_status and auto_status['class'] == 'waiting') or (
                open_phase and open_phase['status']['class'] == 'waiting'):
            cls = 'waiting'
        elif active or harness:
            cls = 'progress'
        elif total and closed == total:
            cls = 'done'
        else:
            cls = 'pending'
        configured = self.configuration.get(root)
        last = db.scalar(text("""SELECT max(at) FROM (
            SELECT max(updated_at) AS at FROM managed_runs WHERE root = :root
            UNION ALL SELECT max(updated_at) FROM managed_phases WHERE root = :root
            UNION ALL SELECT max(updated_at) FROM autonomous_runs WHERE root = :root)"""), {'root': root})
        return {
            'id': identity['key'], 'name': identity['name'], 'name_source': identity['name_source'],
            'knowledge_project_id': identity['knowledge_project_id'],
            'registered_project_id': identity['registered_project_id'],
            'status': {'code': None, 'class': cls, 'source': 'derived'},
            'mode': {'kind': 'autonomous' if autonomous and autonomous['status'] not in TERMINAL_AUTONOMOUS
                     else 'manual',
                     'autonomous_run': {'id': autonomous['id'], 'status': auto_status, 'reason': autonomous['reason'],
                                        'bounds': _bounded(_json(autonomous['bounds'])),
                                        'updated_at': autonomous['updated_at']} if autonomous else None},
            'active_phase': {'code': open_phase['code'], 'title': open_phase['title'],
                             'status': open_phase['status']} if open_phase else None,
            'phases': wm.counter(closed if counts['nodes'] else None, 'derived', reason='no_phases',
                                 total=total if counts['nodes'] else None, meaning='phases closed / total'),
            'circles': self._circles(db, root, active, harness, bubbles=bubbles),
            'active_invocations': [self._active_view(a) for a in active],
            'last_activity': wm.counter(last, 'derived', reason='no_activity'),
            'errors': errors[:MAX_LIST],
            'bubbles': self._bubble_view(bubbles),
            'configuration': configured,
            'configuration_source': 'supplied' if configured is not None else 'absent',
        }

    # --- L1: phases -------------------------------------------------------------------------------------------

    def _page_phases(self, db, root, revision, after, limit):
        """The next phase codes after `after`: instances (root, code), accepted identities (by code) and run-only
        codes (skip scan), each bounded to the page."""
        found = set(db.scalars(text("""SELECT code FROM managed_phases WHERE root = :root AND code > :a
            ORDER BY code LIMIT :n"""), {'root': root, 'a': after, 'n': limit}))
        if revision is not None:
            found |= set(db.scalars(text("""SELECT i.code FROM knowledge_items i
                JOIN knowledge_revision_members m ON m.revision_id = :rev AND m.item_id = i.id
                WHERE i.project_id = :p AND i.kind = 'phase' AND i.document IS NULL AND i.code > :a
                ORDER BY i.code LIMIT :n"""), {'rev': revision['id'], 'p': revision['project_id'], 'a': after,
                                               'n': limit}))
        found |= set(self._skip(db, 'managed_runs', 'phase_id', "root = :root AND purpose = 'task'", after, limit,
                                root=root))
        return sorted(found)[:limit]

    def _phase_nodes(self, db, root, revision, codes):
        """Roadmap identities (accepted revision) merged with operational instances and run-only codes, for the
        given codes only."""
        codes = sorted(set(codes))
        instances = {row['code']: row for row in _rows(db, """
            SELECT id, code, status, version, created_at, updated_at,
                   json_extract(definition, '$.tasks') AS tasks, json_extract(definition, '$.tag') AS tag,
                   substr(json_extract(definition, '$.objective'), 1, :max) AS objective,
                   json_array_length(definition, '$.exit_criteria') AS criteria,
                   json_extract(definition, '$.knowledge.coverage') AS coverage
            FROM managed_phases WHERE root = :root AND code IN (SELECT value FROM json_each(:codes))""",
            root=root, max=MAX_TEXT + 1, codes=json.dumps(codes))}
        identities = {}
        if revision is not None:
            for row in _rows(db, """
                SELECT i.id, i.code, json_extract(v.content, '$.status') AS status,
                       json_extract(v.content, '$.title') AS title, json_extract(v.content, '$.tag') AS tag,
                       substr(json_extract(v.content, '$.objective'), 1, :max) AS objective,
                       (SELECT count(*) FROM knowledge_revision_links c WHERE c.revision_id = m.revision_id
                         AND c.kind = 'criterion_of' AND c.target_item_id = i.id) AS criteria
                FROM knowledge_items i JOIN knowledge_revision_members m ON m.revision_id = :rev AND m.item_id = i.id
                JOIN knowledge_item_versions v ON v.id = m.version_id
                WHERE i.project_id = :p AND i.kind = 'phase' AND i.document IS NULL
                  AND i.code IN (SELECT value FROM json_each(:codes))""",
                    rev=revision['id'], p=revision['project_id'], max=MAX_TEXT + 1, codes=json.dumps(codes)):
                identities[row['code']] = row
        with_runs = set(db.scalars(text("""SELECT DISTINCT phase_id FROM managed_runs WHERE root = :root
            AND purpose = 'task' AND phase_id IN (SELECT value FROM json_each(:codes))"""),
            {'root': root, 'codes': json.dumps(codes)}))
        nodes = []
        for code in codes:
            instance, identity = instances.get(code), identities.get(code)
            if instance is None and identity is None and code not in with_runs:
                continue
            if instance:
                state = wm.status('phase', instance['status'])
            elif identity:
                state = wm.status('identity', identity['status'])
            else:
                state = {'code': None, 'class': 'unknown', 'reason': 'no_phase_record'}
            coverage = _json(instance['coverage']) if instance else None
            nodes.append({
                'code': code, 'title': identity['title'] if identity else None,
                'origin': 'roadmap' if identity else 'instance' if instance else 'runs',
                'identity': {'item_id': identity['id'], 'status': wm.status('identity', identity['status'])}
                if identity else None,
                'instance': {'id': instance['id'], 'status': instance['status'], 'version': instance['version'],
                             'created_at': instance['created_at'], 'updated_at': instance['updated_at']}
                if instance else None,
                'status': state,
                'objective': _short((identity or {}).get('objective') or (instance or {}).get('objective')),
                'tag': (identity or {}).get('tag') if identity else (instance or {}).get('tag'),
                'criteria': wm.counter(identity['criteria'] if identity else instance['criteria'] if instance else None,
                                       'derived', reason='no_criteria',
                                       covered=len(coverage) if isinstance(coverage, dict) else None),
                'plan': [t for t in (_json(instance['tasks']) or []) if isinstance(t, str)] if instance else [],
            })
        return nodes

    def _slots(self, db, root, instance_ids, knowledge_project):
        """Latest plan, check and close operation per phase instance, with the actors that actually took part."""
        if not instance_ids:
            return {}
        ops = _rows(db, """
            SELECT o.id, o.phase_id, o.kind, o.run_id, o.status, o.created_at, o.finished_at,
                   (SELECT count(*) FROM phase_operations y WHERE y.phase_id = o.phase_id AND y.kind = o.kind) AS history
            FROM phase_operations o WHERE o.phase_id IN (SELECT value FROM json_each(:ids)) AND o.kind IN ('plan', 'check', 'close')
              AND o.id = (SELECT x.id FROM phase_operations x WHERE x.phase_id = o.phase_id AND x.kind = o.kind
                          ORDER BY x.created_at DESC, x.id DESC LIMIT 1)""", ids=json.dumps(instance_ids))
        runs = [op['run_id'] for op in ops if op['run_id']]
        actors = {}
        for row in _rows(db, """
            SELECT a.run_id, a.number, a.status, a.result_json IS NULL AS open, i.id AS invocation_id,
                   COALESCE(i.role, json_extract(a.request_json, '$.role')) AS role
            FROM managed_attempts a JOIN managed_runs r ON r.id = a.run_id AND r.root = :root
            LEFT JOIN usage_invocations i ON i.source_kind = 'managed_attempt' AND i.source_id = a.id
            WHERE a.run_id IN (SELECT value FROM json_each(:runs)) ORDER BY a.run_id, a.number""",
                runs=json.dumps(runs), root=root):
            actors.setdefault(row['run_id'], {})[wm.circle(row['role'], ROLES) or 'R'] = (
                wm.status('attempt', 'ACTIVE' if row['open'] else row['status']), row['invocation_id'])
        harness = set(db.scalars(text("""
            SELECT run_id FROM managed_commits WHERE run_id IN (SELECT value FROM json_each(:runs))
            UNION SELECT run_id FROM run_projection_cycles WHERE run_id IN (SELECT value FROM json_each(:runs))"""),
            {'runs': json.dumps(runs)}).all())
        judged = {}
        checks = [op['id'] for op in ops if op['kind'] == 'check']
        if checks and knowledge_project:
            for row in _rows(db, """
                SELECT json_extract(j.payload, '$.evidence.check_operation_id') AS op, u.status, ji.invocation_id
                FROM judge_requests j JOIN judge_invocations ji ON ji.request_id = j.id
                LEFT JOIN judge_rulings u ON u.request_id = j.id
                WHERE j.project_id = :p AND json_extract(j.payload, '$.evidence.check_operation_id')
                      IN (SELECT value FROM json_each(:ops))""", p=knowledge_project, ops=json.dumps(checks)):
                judged[row['op']] = (wm.status('judge_ruling', row['status']), row['invocation_id'])
        result = {}
        for op in ops:
            taken = [{'circle': name, 'status': value[0], 'invocation_id': value[1]}
                     for name, value in sorted(actors.get(op['run_id'], {}).items())]
            if op['id'] in judged and not any(a['circle'] == 'J' for a in taken):
                taken.append({'circle': 'J', 'status': judged[op['id']][0], 'invocation_id': judged[op['id']][1]})
            if op['run_id'] in harness:
                taken.append({'circle': 'H', 'status': None, 'invocation_id': None})
            result.setdefault(op['phase_id'], {})[op['kind']] = {
                'operation_id': op['id'], 'run_id': op['run_id'], 'status': wm.status('phase_operation', op['status']),
                'created_at': op['created_at'], 'finished_at': op['finished_at'], 'history': op['history'],
                'actors': taken}
        return result

    def phases(self, project: str, *, cursor=None, limit=wm.LIMITS['phases']) -> dict:
        limit = max(1, min(int(limit), wm.LIMITS['phases']))
        with self.engine.connect() as db:
            identity = self._project(db, project)
            root = identity['root']
            bubbles, active = self._bubbles(db, root), self._active(db, root)
            harness = self._harness(db, root).get(root, [])
            scope = wm.scope('phases', identity['key'])
            version = self._root_version(db, identity, bubbles=bubbles, active=active, harness=harness)
            after = wm.read_cursor(cursor, scope, version, (str,))
            revision = self._knowledge(db, identity['knowledge_project_id'])
            codes = self._page_phases(db, root, revision, after[0] if after else '', limit + 1)
            shown = self._phase_nodes(db, root, revision, codes[:limit])
            page_codes = [n['code'] for n in shown]
            counts = {row['phase']: row for row in _rows(
                db, TASK_COUNTS, root=root, rev=revision['id'] if revision else None, phases=json.dumps(page_codes),
                inactive_runs=_codes('run', 'inactive'), inactive_identity=_codes('identity', 'inactive'))}
            replaced = self._replaced(db, revision)
            failed = {}
            for row in _rows(db, LATEST + " AND status IN (SELECT value FROM json_each(:failed))", root=root,
                             phases=json.dumps(page_codes), tasks=None, failed=_codes('run', 'failed')):
                if row['task_id'] not in replaced:
                    failed.setdefault(row['phase_id'], []).append(
                        {'kind': 'task', 'id': row['task_id'], 'status': wm.status('run', row['status'])})
            slots = self._slots(db, root, [n['instance']['id'] for n in shown if n['instance']],
                                identity['knowledge_project_id'])
            items = []
            for node in shown:
                tally = counts.get(node['code'])
                mine = [a for a in active if a['scope']['phase'] == node['code']]
                marks = [b for b in bubbles if b['phase'] == node['code']]
                check = (slots.get(node['instance']['id'], {}).get('check') if node['instance'] else None)
                errors = sorted(failed.get(node['code'], []), key=lambda e: e['id'])
                if node['status']['class'] == 'failed':
                    errors.insert(0, {'kind': 'phase', 'id': node['code'], 'status': node['status']})
                is_open = node['instance'] is not None and node['instance']['status'] not in TERMINAL_PHASES
                items.append({**{k: node[k] for k in ('code', 'title', 'origin', 'identity', 'instance', 'status',
                                                      'objective', 'tag', 'criteria')},
                              'slots': {kind: slots.get(node['instance']['id'], {}).get(kind) if node['instance']
                                        else None for kind in PHASE_SLOTS},
                              'ready': bool(node['instance'] and node['instance']['status'] in ('READY_TO_CLOSE', 'CLOSING')
                                            and check and check['status']['code'] == 'READY'),
                              'last_check': check,
                              'tasks': wm.counter(tally['committed'] if tally else None, 'derived', reason='no_tasks',
                                                  total=tally['total'] if tally else None,
                                                  meaning='tasks committed / total'),
                              'active': is_open,
                              'circles': self._circles(db, root, mine, harness if is_open else [], bubbles=marks,
                                                       phase=node['code']),
                              'active_invocations': [self._active_view(a) for a in mine],
                              'errors': errors[:MAX_LIST], 'bubbles': self._bubble_view(marks, identities=True)})
            # Roadmap order: consecutive codes of the page, its predecessor (the cursor) and its successor.
            sequence = ([after[0]] if after else []) + page_codes + codes[limit:limit + 1]
            edges = [{'kind': 'roadmap_order', 'source': a, 'target': b} for a, b in zip(sequence, sequence[1:])]
            return {'format': wm.FORMAT, 'level': 'phases', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'project': self._head(identity), 'items': items,
                    'edges': edges,
                    'next_cursor': wm.cursor(scope, version, [page_codes[-1]]) if len(codes) > limit and page_codes
                    else None}

    # --- L2: tasks and the run selector -----------------------------------------------------------------------

    def _phase(self, db, identity, code):
        """One phase node, by bounded lookups of that code only."""
        revision = self._knowledge(db, identity['knowledge_project_id'])
        nodes = self._phase_nodes(db, identity['root'], revision, [code])
        if not nodes:
            raise MapNotFound(code)
        return revision, nodes[0]

    def _identity_tasks(self, db, revision, phase, *, after=None, codes=None, exclude=(), limit=None, keys_only=False):
        """Accepted task identities of the phase (`part_of`), by code, with inspector texts only for detail reads."""
        if revision is None:
            return []
        columns = 't.code' if keys_only else """t.code, t.id, json_extract(v.content, '$.status') AS status,
                   json_extract(v.content, '$.title') AS title,
                   substr(json_extract(v.content, '$.problem'), 1, :max) AS problem,
                   substr(json_extract(v.content, '$.expected_result'), 1, :max) AS expected_result"""
        details = '' if keys_only else """
            JOIN knowledge_revision_members m ON m.revision_id = l.revision_id AND m.item_id = t.id
            JOIN knowledge_item_versions v ON v.id = m.version_id"""
        return _rows(db, f"""
            SELECT {columns}
            FROM knowledge_revision_links l
            JOIN knowledge_items ph ON ph.id = l.target_item_id AND ph.kind = 'phase' AND ph.code = :phase
            JOIN knowledge_items t ON t.id = l.source_item_id AND t.kind = 'task'
            {details}
            WHERE l.revision_id = :rev AND l.kind = 'part_of'
              AND (:after IS NULL OR t.code > :after)
              AND (:codes IS NULL OR t.code IN (SELECT value FROM json_each(:codes)))
              AND t.code NOT IN (SELECT value FROM json_each(:exclude))
            ORDER BY t.code {'LIMIT :limit' if limit else ''}""", rev=revision['id'], phase=phase, after=after,
                     codes=None if codes is None else json.dumps(codes), exclude=json.dumps(list(exclude)),
                     max=MAX_TEXT + 1, limit=limit)

    def _page_tasks(self, db, root, revision, phase, after, limit):
        """The page's task codes in node order: plan position, then accepted identities of the phase not in the
        plan (by code), then run-only tasks (skip scan, by code). Returns [(group, key, code)]."""
        plan = list(dict.fromkeys(phase['plan']))
        group, position = (after[0], after[1]) if after else (0, -1)
        page = []
        if group == 0:
            page += [(0, i, code) for i, code in enumerate(plan) if i > position][:limit]
        if len(page) < limit and group <= 1:
            start = after[2] if after and group == 1 else None
            page += [(1, 0, row['code']) for row in self._identity_tasks(
                db, revision, phase['code'], after=start, exclude=plan, limit=limit - len(page), keys_only=True)]
        if len(page) < limit:
            start = after[2] if after and group == 2 else ''
            # Exclude within SQL: no identity rows or inspector texts cross the page boundary.
            where = """root = :root AND purpose = 'task' AND phase_id = :phase
                AND task_id NOT IN (SELECT value FROM json_each(:plan))
                AND NOT EXISTS (
                    SELECT 1 FROM knowledge_revision_links l
                    JOIN knowledge_items ph ON ph.id = l.target_item_id AND ph.kind = 'phase' AND ph.code = :phase
                    JOIN knowledge_items t ON t.id = l.source_item_id AND t.kind = 'task'
                    WHERE l.revision_id = :rev AND l.kind = 'part_of' AND t.code = managed_runs.task_id)"""
            page += [(2, 0, code) for code in self._skip(
                db, 'managed_runs', 'task_id', where, start, limit - len(page), root=root, phase=phase['code'],
                plan=json.dumps(plan), rev=revision['id'] if revision else None)]
        return page

    def tasks(self, project: str, code: str, *, cursor=None, limit=wm.LIMITS['tasks']) -> dict:
        limit = max(1, min(int(limit), wm.LIMITS['tasks']))
        with self.engine.connect() as db:
            identity = self._project(db, project)
            root = identity['root']
            revision, phase = self._phase(db, identity, code)
            bubbles, active = self._bubbles(db, root), self._active(db, root)
            harness = self._harness(db, root).get(root, [])
            scope = wm.scope('tasks', identity['key'], code)
            version = self._root_version(db, identity, bubbles=bubbles, active=active, harness=harness)
            after = wm.read_cursor(cursor, scope, version, (int, int, str))
            if after is not None and after[0] not in (0, 1, 2):
                raise wm.TokenError('cursor')
            keys = self._page_tasks(db, root, revision, phase, after, limit + 1)
            shown = keys[:limit]
            codes = [k[2] for k in shown]
            details = {row['code']: row for row in self._identity_tasks(db, revision, code, codes=codes)}
            latest = {row['task_id']: row for row in _rows(db, LATEST, root=root, phases=json.dumps([code]),
                                                           tasks=json.dumps(codes))}
            run_ids = [row['id'] for row in latest.values()]
            projections = {row['run_id']: row for row in _rows(db, """
                SELECT run_id, executor_attempts, attempts, cycle_count, acceptance_json, stop_stage
                FROM run_projections WHERE run_id IN (SELECT value FROM json_each(:ids))""", ids=json.dumps(run_ids))}
            commits = {row['run_id']: row for row in _rows(db, """
                SELECT run_id, status, commit_sha, finished_at FROM managed_commits c
                WHERE run_id IN (SELECT value FROM json_each(:ids)) AND operation_id = (
                    SELECT x.operation_id FROM managed_commits x WHERE x.run_id = c.run_id
                    ORDER BY x.created_at DESC, x.operation_id DESC LIMIT 1)""", ids=json.dumps(run_ids))}
            links = {'depends_on': [], 'replaces': []}
            if revision is not None:
                for row in _rows(db, """
                    SELECT l.kind, s.code AS source, t.code AS target FROM knowledge_revision_links l
                    JOIN knowledge_items s ON s.id = l.source_item_id JOIN knowledge_items t ON t.id = l.target_item_id
                    WHERE l.revision_id = :rev AND l.kind IN ('depends_on', 'replaces')
                      AND (s.code IN (SELECT value FROM json_each(:codes))
                           OR t.code IN (SELECT value FROM json_each(:codes)))""", rev=revision['id'],
                                 codes=json.dumps(codes)):
                    links[row['kind']].append((row['source'], row['target']))
            replaced = {t for _s, t in links['replaces']}
            items = []
            for group, _position, task in shown:
                identity_row = details.get(task)
                run = latest.get(task)
                if task in replaced:
                    state = {**wm.status('identity', 'replaced'), 'run_status': run['status'] if run else None}
                elif run is not None:
                    state = wm.status('run', run['status'])
                elif identity_row is not None:
                    state = wm.status('identity', identity_row['status'])
                else:
                    state = {'code': None, 'class': 'pending', 'reason': 'planned_without_run'}
                mine = [a for a in active if a['scope']['task'] == task and a['scope']['phase'] == code]
                marks = [b for b in bubbles if b['phase'] == code and b['task'] == task]
                lit = [h for h in harness if h['task'] == task and h['phase'] == code]
                view = None
                if run:
                    projection = projections.get(run['id'], {})
                    commit = commits.get(run['id'])
                    view = {'run_id': run['id'], 'status': wm.status('run', run['status']), 'stage': run['stage'],
                            'revisions': run['revisions'], 'created_at': run['created_at'],
                            'updated_at': run['updated_at'],
                            'attempts': wm.counter(projection.get('executor_attempts'), 'derived',
                                                   reason='no_projection', revision_limit=run['revision_limit'],
                                                   revision_limit_source='supplied',
                                                   meaning='executor attempts of the latest run / revision limit'),
                            'cycles': projection.get('cycle_count'),
                            'acceptance': acceptance(projection.get('acceptance_json')),
                            'commit': {'status': wm.status('commit', commit['status']), 'commit': commit['commit_sha'],
                                       'finished_at': commit['finished_at']} if commit else None}
                items.append({'code': task, 'title': identity_row['title'] if identity_row else None,
                              'in_plan': group == 0,
                              'identity': {'item_id': identity_row['id'],
                                           'status': wm.status('identity', identity_row['status'])}
                              if identity_row else None,
                              'problem': _text(identity_row['problem'] if identity_row else None),
                              'expected_result': _text(identity_row['expected_result'] if identity_row else None),
                              'status': state, 'runs': run['runs'] if run else 0, 'latest': view,
                              'replaces': sorted(t for s, t in links['replaces'] if s == task),
                              'replaced_by': sorted(s for s, t in links['replaces'] if t == task),
                              'depends_on': sorted(t for s, t in links['depends_on'] if s == task),
                              'circles': self._circles(db, root, mine, lit, bubbles=marks, phase=code, task=task),
                              'active_invocations': [self._active_view(a) for a in mine],
                              'errors': [{'kind': 'run', 'id': run['id'], 'status': state}]
                              if run and state['class'] == 'failed' else [],
                              'bubbles': self._bubble_view(marks, identities=True)})
            shown_codes = set(codes)
            targets = {t for kind in links.values() for _s, t in kind} - shown_codes
            in_phase = {t for t in targets if self._task_exists(db, root, revision, phase, t)}
            edges = [{'kind': kind, 'source': s, 'target': t, 'target_in_phase': t in shown_codes or t in in_phase}
                     for kind in ('depends_on', 'replaces') for s, t in links[kind] if s in shown_codes]
            edges += [{'kind': 'replaces', 'source': s, 'target': t, 'target_in_phase': True}
                      for s, t in links['replaces'] if t in shown_codes and s not in shown_codes]
            last = shown[-1] if shown else None
            return {'format': wm.FORMAT, 'level': 'tasks', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'project': self._head(identity),
                    'phase': {k: phase[k] for k in ('code', 'title', 'status', 'instance')},
                    'items': items, 'edges': edges,
                    'next_cursor': wm.cursor(scope, version, [last[0], last[1], last[2]])
                    if len(keys) > limit and last else None}

    def _task_exists(self, db, root, revision, phase, task):
        """Whether `task` is a node of the phase, by bounded lookups (plan, identity link, a run)."""
        if task in phase['plan']:
            return True
        if self._identity_tasks(db, revision, phase['code'], codes=[task]):
            return True
        return db.scalar(text("""SELECT 1 FROM managed_runs WHERE root = :root AND purpose = 'task'
            AND phase_id = :phase AND task_id = :task LIMIT 1"""), {'root': root, 'phase': phase['code'],
                                                                     'task': task}) is not None

    def _runs_version(self, db, root, code, task):
        row = db.execute(text("""SELECT count(*), coalesce(sum(version), 0) FROM managed_runs
            WHERE root = :root AND purpose = 'task' AND phase_id = :phase AND task_id = :task"""),
            {'root': root, 'phase': code, 'task': task}).one()
        return wm.version({'runs': list(row)})

    def runs(self, project: str, code: str, task: str, *, cursor=None, limit=wm.LIMITS['runs']) -> dict:
        limit = max(1, min(int(limit), wm.LIMITS['runs']))
        with self.engine.connect() as db:
            identity = self._project(db, project)
            root = identity['root']
            revision, phase = self._phase(db, identity, code)
            if not self._task_exists(db, root, revision, phase, task):
                raise MapNotFound(task)
            scope = wm.scope('runs', identity['key'], code, task)
            version = self._runs_version(db, root, code, task)
            after = wm.read_cursor(cursor, scope, version, (str, str))
            rows = _rows(db, """
                SELECT r.id, r.status, r.stage, r.revisions, r.revision_limit, r.created_at, r.updated_at,
                       p.executor_attempts, p.attempts, p.cycle_count, p.acceptance_json,
                       (SELECT c.status FROM managed_commits c WHERE c.run_id = r.id
                        ORDER BY c.created_at DESC, c.operation_id DESC LIMIT 1) AS commit_status
                FROM managed_runs r LEFT JOIN run_projections p ON p.run_id = r.id
                WHERE r.root = :root AND r.purpose = 'task' AND r.phase_id = :phase AND r.task_id = :task
                  AND (:created IS NULL OR r.created_at < :created OR (r.created_at = :created AND r.id > :id))
                ORDER BY r.created_at DESC, r.id LIMIT :limit""", root=root, phase=code, task=task,
                created=after[0] if after else None, id=after[1] if after else None, limit=limit + 1)
            items = [{'run_id': r['id'], 'status': wm.status('run', r['status']), 'stage': r['stage'],
                      'revisions': r['revisions'], 'revision_limit': r['revision_limit'],
                      'attempts': wm.counter(r['attempts'], 'derived', reason='no_projection',
                                             executor=r['executor_attempts']),
                      'cycles': r['cycle_count'], 'acceptance': acceptance(r['acceptance_json']),
                      'commit': wm.status('commit', r['commit_status']) if r['commit_status'] else None,
                      'created_at': r['created_at'], 'updated_at': r['updated_at']} for r in rows[:limit]]
            last = rows[limit - 1] if len(rows) > limit else None
            return {'format': wm.FORMAT, 'level': 'runs', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'project': self._head(identity),
                    'phase': code, 'task': task, 'latest_run_id': items[0]['run_id'] if items and after is None
                    else None, 'items': items,
                    'next_cursor': wm.cursor(scope, version, [last['created_at'], last['id']]) if last else None}

    # --- L3: steps of one run ---------------------------------------------------------------------------------

    def _run(self, db, identity, run_id):
        run = db.execute(text("""SELECT id, root, purpose, phase_id, task_id, status, stage, version, revisions,
            revision_limit, created_at, updated_at FROM managed_runs WHERE id = :id"""), {'id': run_id}).mappings().first()
        if run is None or run['root'] != identity['root']:
            raise MapNotFound(run_id)
        return dict(run)

    ATTEMPTS = """
        SELECT a.id, a.number, a.status, a.result_json IS NULL AS open, a.started_at, a.finished_at,
               COALESCE(i.role, json_extract(a.request_json, '$.role')) AS role,
               i.id AS invocation_id, i.agent, i.requested_model, i.requested_effort, i.launch, i.outcome,
               COALESCE(json_extract(i.versions, '$.' || i.agent || '_provider'),
                        json_extract(p.spec, '$.provider')) AS provider,
               i.purpose, p.status AS process, json_extract(p.capture, '$.wall_duration_seconds') AS wall,
               m.executor_round, m.cli_version, m.adapter_version, m.reported_models, m.reported_effort,
               json_extract(m.provenance, '$.reported_models') AS reported_source
        FROM managed_attempts a
        LEFT JOIN usage_invocations i ON i.source_kind = 'managed_attempt' AND i.source_id = a.id
        LEFT JOIN managed_processes p ON p.attempt_id = a.id
        LEFT JOIN attempt_metrics m ON m.attempt_id = a.id
        WHERE a.run_id = :run {where} ORDER BY a.number {limit}"""

    def _attempts(self, db, run_id, *, after=0, limit=None, number=None):
        where = 'AND a.number = :number' if number is not None else 'AND a.number > :after'
        return _rows(db, self.ATTEMPTS.format(where=where, limit='LIMIT :limit' if limit else ''),
                     run=run_id, after=after, limit=limit, number=number)

    def _ordinals(self, db, run_id, attempts):
        """Per page attempt: the ordinal of its role and its executor round, by aggregates over earlier attempts."""
        if not attempts:
            return
        first = attempts[0]['number']
        before = {row['role']: row['n'] for row in _rows(db, """
            SELECT COALESCE(i.role, json_extract(a.request_json, '$.role')) AS role, count(*) AS n
            FROM managed_attempts a LEFT JOIN usage_invocations i ON i.source_kind = 'managed_attempt'
              AND i.source_id = a.id WHERE a.run_id = :run AND a.number < :first GROUP BY 1""",
                                                            run=run_id, first=first)}
        seen = dict(before)
        for attempt in attempts:
            seen[attempt['role']] = seen.get(attempt['role'], 0) + 1
            attempt['ordinal'] = seen[attempt['role']]
            if attempt['executor_round'] is None:
                attempt['executor_round'] = seen.get('executor', 0)

    def _markers(self, db, invocations):
        """Latest trace event per invocation and kind that alters L3, the L4 header or its related records."""
        return [[r['invocation_id'], r['kind'], r['id']] for r in _rows(db, """
            SELECT invocation_id, kind, max(id) AS id FROM trace_events
            WHERE invocation_id IN (SELECT value FROM json_each(:ids)) AND kind IN (SELECT value FROM json_each(:kinds))
            GROUP BY invocation_id, kind ORDER BY invocation_id, kind""", ids=json.dumps(sorted(invocations)),
            kinds=json.dumps(sorted({*MARKERS, *RELATED})))]

    def _steps_version(self, db, run):
        invocations = list(db.scalars(text("""SELECT i.id FROM managed_attempts a JOIN usage_invocations i
            ON i.source_kind = 'managed_attempt' AND i.source_id = a.id WHERE a.run_id = :run"""), {'run': run['id']}))
        open_ = _rows(db, """SELECT a.id, p.status FROM managed_attempts a LEFT JOIN managed_processes p
            ON p.attempt_id = a.id WHERE a.run_id = :run AND a.result_json IS NULL""", run=run['id'])
        deliveries = _rows(db, """SELECT invocation_id, count(*) AS n FROM knowledge_deliveries
            WHERE invocation_id IN (SELECT value FROM json_each(:ids)) GROUP BY invocation_id ORDER BY 1""",
                           ids=json.dumps(invocations))
        permissions = db.scalar(text("""SELECT max(x.sequence) FROM knowledge_projects k
            JOIN permission_records x ON x.project_id = k.id WHERE k.root = :root"""), {'root': run['root']})
        bubbles = [b['id'] for b in self._bubbles(db, run['root']) if b['run_id'] == run['id']]
        return wm.version({'run': run['version'], 'open': [[r['id'], r['status']] for r in open_],
                           'markers': self._markers(db, invocations),
                           'deliveries': [[r['invocation_id'], r['n']] for r in deliveries],
                           'permissions': permissions, 'bubbles': bubbles})

    def _attempt_status(self, attempt):
        if not attempt['open']:
            return wm.status('attempt', attempt['status'])
        if attempt['process'] is None:
            return {**wm.status('attempt', 'ACTIVE'), 'process': None}
        return {**wm.status('process', attempt['process']), 'process': attempt['process']}

    def _invocation_step(self, db, run, attempt, counts):
        observation = self._observation(db, attempt)
        steps = ObservedSteps(self.engine).state(attempt['invocation_id'], root=run['root']) \
            if attempt['invocation_id'] else {'state': 'not_projected', 'reason': 'no_ledger_row'}
        models = _json(attempt['reported_models'])
        duration = attempt['wall']
        role = attempt['role']
        return {
            'kind': 'invocation', 'invocation_id': attempt['invocation_id'],
            'attempt_id': attempt['id'], 'role': role, 'circle': wm.circle(role, ROLES),
            'label': {'role': role, 'ordinal': attempt['ordinal']},
            'status': self._attempt_status(attempt),
            'active': bool(attempt['open'] and attempt['process'] in ('PENDING', 'RUNNING')),
            'harness_attempt': wm.counter(attempt['number'], 'supplied'),
            'revision_round': wm.counter(attempt['executor_round'], 'derived', reason='no_metrics'),
            'duration_ms': wm.counter(round(duration * 1000) if isinstance(duration, (int, float)) else None,
                                      'measured', reason='no_capture'),
            'started_at': attempt['started_at'], 'finished_at': attempt['finished_at'],
            'identity': {'agent': attempt['agent'], 'client': attempt['provider'],
                         'client_version': attempt['cli_version'],
                         'adapter_version': attempt['adapter_version'],
                         'requested_model': attempt['requested_model'], 'requested_effort': attempt['requested_effort'],
                         'source': 'supplied' if attempt['invocation_id'] else 'absent'},
            'reported_model': wm.counter(models if models else None, 'reported',
                                         reason='not_reported', provenance=_json(attempt['reported_source'])),
            'launch': wm.status('launch', attempt['launch']) if attempt['launch'] else None,
            'termination': observation['payload'].get('termination') if observation else None,
            'observation': {'source': observation['source'], 'persisted': observation['persisted'],
                            'counters': observation['payload'].get('counters'),
                            'usage': observation['payload'].get('usage'),
                            'missing': observation['payload'].get('missing')} if observation else None,
            'records': {name: wm.counter(counts.get((attempt['invocation_id'], name)), 'derived',
                                         reason='no_ledger_row') if attempt['invocation_id']
                        else wm.counter(None, 'derived', reason='no_ledger_row')
                        for name in ('deliveries', 'discovery', 'rulings', 'permission_requests')},
            'steps': {k: steps.get(k) for k in ('state', 'reason') if k in steps},
        }

    def _observation(self, db, attempt):
        """Persisted `trace-observation-1` when present, else the pure evaluation of the sealed capture (no write)."""
        if attempt['invocation_id']:
            row = db.execute(text("SELECT payload FROM trace_events WHERE dedupe_key = :key"),
                             {'key': f"observation:{attempt['invocation_id']}"}).scalar()
            if row is not None:
                return {'source': 'trace', 'persisted': True, 'payload': _json(row) or {}}
        if attempt['open']:
            return None
        process = db.execute(text("SELECT spec, status, capture, identity IS NOT NULL AS identity FROM managed_processes "
                                  "WHERE attempt_id = :id"), {'id': attempt['id']}).mappings().first()
        payload = observe(spec=_json(process['spec']) if process else None,
                          process_status=process['status'] if process else None,
                          capture=_json(process['capture']) if process else None,
                          identity_present=bool(process and process['identity']), attempt_number=attempt['number'],
                          revision_round=attempt['executor_round'])
        return {'source': 'derived', 'persisted': False, 'payload': payload}

    def _record_counts(self, db, run, attempts):
        """Per invocation of the page: deliveries, discovery loads, rulings and permission requests (aggregates)."""
        ids = [a['invocation_id'] for a in attempts if a['invocation_id']]
        counts = {}
        for row in _rows(db, """SELECT invocation_id, count(*) AS n FROM knowledge_deliveries
            WHERE invocation_id IN (SELECT value FROM json_each(:ids)) GROUP BY invocation_id""", ids=json.dumps(ids)):
            counts[(row['invocation_id'], 'deliveries')] = row['n']
        for kind, name in (('tool.discovered', 'discovery'), ('judge.ruled', 'rulings')):
            for row in _rows(db, """SELECT invocation_id, count(*) AS n FROM trace_events
                WHERE invocation_id IN (SELECT value FROM json_each(:ids)) AND kind = :kind GROUP BY invocation_id""",
                    ids=json.dumps(ids), kind=kind):
                counts[(row['invocation_id'], name)] = row['n']
        by_attempt = {a['id']: a['invocation_id'] for a in attempts if a['invocation_id']}
        for row in _rows(db, """
            SELECT attempt, count(*) AS n FROM (
                SELECT json_extract(p.request, '$.source_attempt_id') AS attempt FROM permission_requests p
                WHERE p.run_id = :run
                UNION ALL
                SELECT json_extract(x.payload, '$.source_attempt_id') FROM permission_records x
                JOIN knowledge_projects k ON k.id = x.project_id AND k.root = :root WHERE x.kind = 'request')
            WHERE attempt IN (SELECT value FROM json_each(:attempts)) GROUP BY attempt""",
                         run=run['id'], root=run['root'], attempts=json.dumps(list(by_attempt))):
            counts[(by_attempt[row['attempt']], 'permission_requests')] = row['n']
        for ident in ids:
            for name in ('deliveries', 'discovery', 'rulings', 'permission_requests'):
                counts.setdefault((ident, name), 0)  # these ledgers are complete per invocation: zero is observed
        return counts

    def _cycle_steps(self, db, run, numbers):
        """Format and validate of the given 0-based review cycles, from the run projection and stage events."""
        if not numbers:
            return {}
        cycles = _rows(db, """SELECT number, formatting_json IS NOT NULL AS formatted, verdict,
            json_array_length(validation_json, '$.entries') AS entries FROM run_projection_cycles WHERE run_id = :run
            AND number IN (SELECT value FROM json_each(:numbers)) ORDER BY number""", run=run['id'],
                       numbers=json.dumps(sorted(numbers)))
        passed = {}
        if cycles:
            with Session(bind=db) as session:
                tests = cycle_tests(session, select(Cycle.run_id, Cycle.number).where(
                    Cycle.run_id == run['id'], Cycle.number.in_([c['number'] for c in cycles])))
            passed = {number: value for (_run, number), value in tests.items()}
        result = {}
        for cycle in cycles:
            number = cycle['number']
            # The n-th validation checkpoint opens cycle n; the next checkpoint closes it (format included).
            timing = db.execute(text("""
                SELECT s.recorded_at AS start, (SELECT x.recorded_at FROM managed_events x WHERE x.kind = 'checkpoint'
                       AND x.run_id = s.run_id AND x.sequence > s.sequence ORDER BY x.sequence LIMIT 1) AS finish
                FROM managed_events s WHERE s.kind = 'checkpoint' AND s.run_id = :run
                  AND json_extract(s.payload, '$.stage') = 'validation' ORDER BY s.sequence LIMIT 1 OFFSET :n"""),
                {'run': run['id'], 'n': number}).mappings().first()
            timing = (timing['start'], timing['finish']) if timing and timing['finish'] else None
            counts, all_passed = passed.get(number, (None, None))
            validate = 'not_configured' if not cycle['entries'] else 'passed' if all_passed else 'failed'
            result[number] = [
                {'kind': 'harness', 'stage': 'format', 'cycle': number, 'circle': 'H',
                 'status': wm.status('harness_step', 'passed' if cycle['formatted'] else 'not_recorded'),
                 'duration_ms': wm.counter(None, 'derived', reason='not_measured_separately'),
                 'evidence': {'formatting_recorded': bool(cycle['formatted'])}},
                {'kind': 'harness', 'stage': 'validate', 'cycle': number, 'circle': 'H',
                 'status': wm.status('harness_step', validate),
                 'duration_ms': wm.counter(_ms(*timing) if timing else None, 'derived', reason='no_stage_events',
                                           includes=['format'], timing='stage_events'),
                 'started_at': timing[0] if timing else None, 'finished_at': timing[1] if timing else None,
                 'evidence': {'commands': counts, 'verdict': cycle['verdict']}},
            ]
        return result

    def _tail(self, db, run, executors):
        """Steps after the last attempt: cycles without their executor attempt, a formatter stop or a running
        validation, then every commit record. Bounded by the run's cycles beyond its executor rounds and commits."""
        orphans = list(db.scalars(text("""SELECT number FROM run_projection_cycles WHERE run_id = :run
            AND number >= :n ORDER BY number"""), {'run': run['id'], 'n': executors}))
        tail = [step for steps in self._cycle_steps(db, run, orphans).values() for step in steps]
        cycles = db.scalar(text('SELECT count(*) FROM run_projection_cycles WHERE run_id = :run'), {'run': run['id']})
        stop = db.scalar(text("""SELECT stage FROM run_projection_stops WHERE run_id = :run
            ORDER BY ordinal DESC LIMIT 1"""), {'run': run['id']})
        if stop == 'formatter':
            tail.append({'kind': 'harness', 'stage': 'format', 'cycle': cycles, 'circle': 'H',
                         'status': wm.status('harness_step', 'failed'),
                         'duration_ms': wm.counter(None, 'derived', reason='not_measured_separately'),
                         'evidence': {'stop_stage': 'formatter'}})
        elif run['stage'] == 'validation' and run['status'] == 'VALIDATING':
            tail.append({'kind': 'harness', 'stage': 'validate', 'cycle': cycles, 'circle': 'H',
                         'status': wm.status('harness_step', 'running'),
                         'duration_ms': wm.counter(None, 'derived', reason='in_progress'), 'evidence': {}})
        for commit in _rows(db, """SELECT operation_id, status, commit_sha, created_at, finished_at FROM managed_commits
                WHERE run_id = :run ORDER BY created_at, operation_id""", run=run['id']):
            tail.append({'kind': 'harness', 'stage': 'commit', 'circle': 'H', 'operation_id': commit['operation_id'],
                         'status': wm.status('commit', commit['status']),
                         'duration_ms': wm.counter(_ms(commit['created_at'], commit['finished_at'])
                                                   if commit['finished_at'] else None, 'derived',
                                                   reason='not_finished', timing='commit_record'),
                         'started_at': commit['created_at'], 'finished_at': commit['finished_at'],
                         'evidence': {'commit': commit['commit_sha']}})
        return tail

    def steps(self, project: str, run_id: str, *, cursor=None, limit=wm.LIMITS['steps']) -> dict:
        """Keyset over (attempt number, sub-step): each attempt, then its executor round's format and validate,
        then the tail. Only the page's attempts are read and enriched."""
        limit = max(1, min(int(limit), wm.LIMITS['steps']))
        with self.engine.connect() as db:
            identity = self._project(db, project)
            run = self._run(db, identity, run_id)
            scope = wm.scope('steps', identity['key'], run_id)
            version = self._steps_version(db, run)
            after = wm.read_cursor(cursor, scope, version, (int, int))
            last = tuple(after) if after else (0, 9)
            if last[0] < 0 or (last[0] != TAIL and last[1] not in (0, 1, 2, 9)):
                raise wm.TokenError('cursor')
            bubbles = [b for b in self._bubbles(db, run['root']) if b['run_id'] == run_id]
            pending = []  # (key, kind, payload): keys strictly after the cursor, at most limit + 1
            exhausted = True
            if last[0] != TAIL:
                attempts = self._attempts(db, run_id, after=last[0] - (1 if last[1] < 2 else 0), limit=limit + 1)
                exhausted = len(attempts) <= limit
                self._ordinals(db, run_id, attempts)
                cycles = self._cycle_steps(db, run, [a['executor_round'] - 1 for a in attempts
                                                     if a['role'] == 'executor' and a['executor_round']])
                for attempt in attempts:
                    entries = [((attempt['number'], 0), 'invocation', attempt)]
                    if attempt['role'] == 'executor' and attempt['executor_round']:
                        entries += [((attempt['number'], n), 'harness', step) for n, step in
                                    enumerate(cycles.get(attempt['executor_round'] - 1, []), start=1)]
                    pending += [entry for entry in entries if entry[0] > last]
                    if len(pending) > limit:
                        exhausted = False
                        break
            if exhausted and len(pending) <= limit:
                executors = db.scalar(text("""SELECT count(*) FROM managed_attempts a LEFT JOIN usage_invocations i
                    ON i.source_kind = 'managed_attempt' AND i.source_id = a.id WHERE a.run_id = :run
                    AND COALESCE(i.role, json_extract(a.request_json, '$.role')) = 'executor'"""), {'run': run_id})
                pending += [((TAIL, n), 'harness', step) for n, step in enumerate(self._tail(db, run, executors))
                            if (TAIL, n) > last]
            more = len(pending) > limit or not exhausted  # attempts remain beyond those fetched
            page = pending[:limit]
            enriched = [entry[2] for entry in page if entry[1] == 'invocation']
            counts = self._record_counts(db, run, enriched)
            shown = []
            for key, kind, payload in page:
                if kind == 'invocation':
                    step = self._invocation_step(db, run, payload, counts)
                    step['bubbles'] = self._bubble_view([b for b in bubbles if b['attempt_id'] == payload['id']],
                                                        identities=True)
                else:
                    step = dict(payload)
                step['key'] = f'{key[0]:06d}.{key[1]:04d}'
                shown.append(step)
            next_key = list(page[-1][0]) if page else None
            return {'format': wm.FORMAT, 'level': 'steps', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'project': self._head(identity),
                    'run': {'run_id': run['id'], 'purpose': run['purpose'], 'phase': run['phase_id'],
                            'task': run['task_id'], 'status': wm.status('run', run['status']), 'stage': run['stage'],
                            'revisions': run['revisions'], 'revision_limit': run['revision_limit'],
                            'created_at': run['created_at'], 'updated_at': run['updated_at']},
                    'items': shown, 'bubbles': self._bubble_view(bubbles),
                    'edges': [{'kind': 'step_order', 'source': a['key'], 'target': b['key']}
                              for a, b in zip(shown, shown[1:])],
                    'next_cursor': wm.cursor(scope, version, next_key) if more and next_key else None}

    # --- L4: one invocation -----------------------------------------------------------------------------------

    def _invocation(self, db, identity, invocation_id):
        row = db.execute(text("""
            SELECT i.id, i.source_kind, i.source_id, i.attempt_id, i.run_id, i.root, i.project_id, i.purpose, i.role,
                   i.agent, i.requested_model, i.requested_effort, i.launch, i.outcome, i.started_at, i.finished_at,
                   r.root AS run_root, g.root AS registered_root
            FROM usage_invocations i LEFT JOIN managed_runs r ON r.id = i.run_id
            LEFT JOIN registered_projects g ON g.id = i.project_id
              AND i.source_kind = 'configuration_assistance'
            WHERE i.id = :id"""), {'id': invocation_id}).mappings().first()
        # The run's root for managed attempts, the ledger root for preparation steps and the registered project of a
        # project-scoped configuration assistance (including retired registrations); a global assistance belongs
        # to no project. Historical reads do not admit new operations or compose a project.
        if row is None or (row['run_root'] or row['root'] or row['registered_root']) != identity['root']:
            raise MapNotFound(invocation_id)
        return dict(row)

    def _owner(self, db, identity, invocation):
        """Owning context for navigation from any lane, including those without a `workflow_operation`."""
        if invocation['run_id'] is None:
            return {'lane': invocation['source_kind'], 'phase': None, 'task': None, 'run_id': None,
                    'breadcrumb': [{'level': 'project', 'id': identity['key']},
                                   {'level': 'lane', 'id': invocation['source_kind']},
                                   {'level': 'invocation', 'id': invocation['id'], 'role': invocation['role'],
                                    'ordinal': None}]}
        run = self._run(db, identity, invocation['run_id'])
        operation = db.execute(text("""SELECT id, thread_id, status FROM workflow_operations
            WHERE attempt_id = :a AND root = :root"""), {'a': invocation['attempt_id'], 'root': run['root']}).mappings().first()
        crumb = [{'level': 'project', 'id': identity['key']}]
        owner = {'lane': run['purpose'], 'run_id': run['id'], 'phase': None, 'task': None,
                 'workflow_operation': {'id': operation['id'], 'thread_id': operation['thread_id'],
                                        'status': wm.status('workflow_operation', operation['status'])}
                 if operation else None}
        if run['purpose'] == 'task':
            owner.update(phase=run['phase_id'], task=run['task_id'])
            crumb += [{'level': 'phase', 'id': run['phase_id']}, {'level': 'task', 'id': run['task_id']},
                      {'level': 'run', 'id': run['id']}]
        elif run['purpose'] in PHASE_PURPOSES:
            op = db.execute(text("""SELECT o.id, o.kind, p.code FROM phase_operations o JOIN managed_phases p
                ON p.id = o.phase_id AND p.root = :root WHERE o.run_id = :run LIMIT 1"""),
                {'run': run['id'], 'root': run['root']}).mappings().first()
            owner.update(lane='phase_operation', phase=op['code'] if op else run['phase_id'],
                         phase_operation={'id': op['id'], 'kind': op['kind']} if op else None)
            crumb += [{'level': 'phase', 'id': owner['phase']},
                      {'level': 'phase_operation', 'id': op['kind'] if op else run['purpose']}]
        elif run['purpose'] == 'chat':
            chat = db.execute(text("""SELECT c.id, coalesce(r.phase_id, p.code) AS code, r.task_id, c.task_run_id FROM chat_turns t
                JOIN chat_conversations c ON c.id = t.conversation_id AND c.root = :root
                LEFT JOIN managed_phases p ON p.id = c.phase_id AND p.root = c.root
                LEFT JOIN managed_runs r ON r.id = c.task_run_id AND r.root = c.root WHERE t.run_id = :run"""),
                {'run': run['id'], 'root': run['root']}).mappings().first()
            owner.update(phase=chat['code'] if chat else None, task=chat['task_id'] if chat else None,
                         chat={'conversation_id': chat['id'], 'task_run_id': chat['task_run_id']} if chat else None)
            crumb += [{'level': 'chat', 'id': chat['id'] if chat else None}]
        else:
            crumb += [{'level': 'lane', 'id': run['purpose']}, {'level': 'run', 'id': run['id']}]
        ordinal = db.scalar(text("""SELECT count(*) FROM managed_attempts a
            LEFT JOIN usage_invocations i ON i.source_kind = 'managed_attempt' AND i.source_id = a.id
            WHERE a.run_id = :run AND a.number <= (SELECT number FROM managed_attempts WHERE id = :a)
              AND COALESCE(i.role, json_extract(a.request_json, '$.role')) = :role"""),
            {'run': run['id'], 'a': invocation['attempt_id'], 'role': invocation['role']})
        crumb.append({'level': 'invocation', 'id': invocation['id'], 'role': invocation['role'], 'ordinal': ordinal})
        owner['breadcrumb'] = crumb
        return owner

    def _process_status(self, db, invocation):
        if invocation['attempt_id']:
            return db.scalar(text('SELECT status FROM managed_processes WHERE attempt_id = :id'),
                             {'id': invocation['attempt_id']})
        if invocation['source_kind'] == 'preparation_step':
            return db.scalar(text('SELECT status FROM managed_processes WHERE id = :id'), {'id': invocation['source_id']})
        return db.scalar(text("""SELECT json_extract(payload, '$.process.status') || '@' || status
            FROM configuration_operations WHERE id = :id"""), {'id': invocation['source_id']})

    def _invocation_version(self, db, invocation):
        run_version = db.scalar(text('SELECT version FROM managed_runs WHERE id = :id'), {'id': invocation['run_id']})
        root = invocation['run_root'] or invocation['root'] or invocation['registered_root']
        permissions = db.scalar(text("""SELECT max(x.sequence) FROM knowledge_projects k
            JOIN permission_records x ON x.project_id = k.id WHERE k.root = :root"""), {'root': root})
        deliveries = db.scalar(text('SELECT count(*) FROM knowledge_deliveries WHERE invocation_id = :i'),
                               {'i': invocation['id']})
        return wm.version({'run': run_version, 'process': self._process_status(db, invocation),
                           'ledger': [invocation['launch'], invocation['outcome'], invocation['finished_at']],
                           'markers': self._markers(db, [invocation['id']]), 'deliveries': deliveries,
                           'permissions': permissions})

    def invocation(self, project: str, invocation_id: str) -> dict:
        with self.engine.connect() as db:
            identity = self._project(db, project)
            invocation = self._invocation(db, identity, invocation_id)
            scope = wm.scope('invocation', identity['key'], invocation_id)
            version = self._invocation_version(db, invocation)
            owner = self._owner(db, identity, invocation)
            steps = ObservedSteps(self.engine).state(invocation_id, root=identity['root']) \
                if invocation['source_kind'] != 'configuration_assistance' else \
                {'state': 'lane_excluded', 'reason': 'steps_not_projected_for_lane'}
            head = {'invocation_id': invocation_id, 'lane': invocation['source_kind'], 'purpose': invocation['purpose'],
                    'role': invocation['role'], 'circle': wm.circle(invocation['role'], ROLES),
                    'started_at': invocation['started_at'], 'finished_at': invocation['finished_at'],
                    'launch': wm.status('launch', invocation['launch']), 'outcome': invocation['outcome'],
                    'process': self._process_status(db, invocation) if invocation['attempt_id'] is None else None}
            step = None
            if invocation['attempt_id'] is not None:
                [attempt] = self._attempts(db, invocation['run_id'],
                                           number=db.scalar(text('SELECT number FROM managed_attempts WHERE id = :a'),
                                                            {'a': invocation['attempt_id']}))
                run = self._run(db, identity, invocation['run_id'])
                self._ordinals(db, invocation['run_id'], [attempt])
                step = self._invocation_step(db, run, attempt, self._record_counts(db, run, [attempt]))
            evidence = None
            if invocation['run_id']:
                evidence = {'run': f"/api/managed/runs/{invocation['run_id']}",
                            'run_events': f"/api/managed/runs/{invocation['run_id']}/events",
                            'attempt_logs': f"/api/managed/runs/{invocation['run_id']}/attempts/"
                                            f"{invocation['attempt_id']}/logs" if invocation['attempt_id'] else None}
            summary = steps.get('summary') if isinstance(steps.get('summary'), dict) else None
            return {'format': wm.FORMAT, 'level': 'invocation', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'project': self._head(identity),
                    'invocation': head, 'owner': owner, 'step': step,
                    'steps': {'state': steps['state'], 'reason': steps.get('reason'),
                              'summary': _bounded(summary) if summary else None,
                              'observation': steps.get('observation'), 'failure': _bounded(steps.get('failure')),
                              'scope': wm.scope('trace', identity['key'], invocation_id)},
                    'related_scopes': {group: wm.scope('related', identity['key'], invocation_id, group)
                                       for group in GROUPS},
                    'evidence': evidence}

    def _trace_version(self, db, invocation):
        """A sealed trace changes only with its markers or with the retention of its own attempt's stdout (source
        record availability); activity of other attempts or runs never supersedes it."""
        markers = [list(r) for r in db.execute(text("""SELECT kind, id FROM trace_events WHERE dedupe_key IN
            (:p, :s, :f) ORDER BY id"""), {'p': f"steps_pending:{invocation['id']}", 's': f"steps:{invocation['id']}",
                                         'f': f"steps_failed:{invocation['id']}"}).all()]
        return wm.version({'steps': markers, 'removed': sorted(self._removed(db, invocation))})

    def trace(self, project: str, invocation_id: str, *, cursor=None, limit=wm.LIMITS['trace']) -> dict:
        limit = max(1, min(int(limit), wm.LIMITS['trace']))
        with self.engine.connect() as db:
            identity = self._project(db, project)
            invocation = self._invocation(db, identity, invocation_id)
            scope = wm.scope('trace', identity['key'], invocation_id)
        for _attempt in range(3):
            with self.engine.connect() as db:
                version = self._trace_version(db, invocation)
            after = wm.read_cursor(cursor, scope, version, (int,))
            page = ObservedSteps(self.engine).page(invocation_id, root=identity['root'],
                                                   after=after[0] if after else None, limit=limit) \
                if invocation['source_kind'] != 'configuration_assistance' else \
                {'state': 'lane_excluded', 'reason': 'steps_not_projected_for_lane', 'items': [], 'next_after': None}
            with self.engine.connect() as db:
                if self._trace_version(db, invocation) == version:
                    removed = self._removed(db, invocation)
                    oversize = self._oversize(db, page['items'], invocation)
                    archive = self._archive(db)
                    break  # sources unchanged while the page was read
        else:
            raise wm.StaleCursor()
        items = []
        for step in page['items']:
            records = []
            for ref in step.get('source_record') or []:
                if ref.get('run_id') != invocation['run_id'] or ref.get('attempt_id') != invocation['attempt_id']:
                    continue  # T019 only references the attempt's own run events; anything else is not resolved
                records.append(self._source_record(ref, oversize, removed))
            view = {k: v for k, v in step.items() if k not in ('source_record', 'cursor')}
            view['source_records'] = records
            items.append(view)
        return {'format': wm.FORMAT, 'level': 'trace', 'scope': scope, 'version': version,
                'read_only_archive': archive, 'project': self._head(identity),
                'invocation_id': invocation_id, 'state': page['state'], 'reason': page.get('reason'),
                'items': items,
                'next_cursor': wm.cursor(scope, version, [page['next_after']]) if page['next_after'] else None}

    @staticmethod
    def _removed(db, invocation):
        """Streams whose bytes the retention audit records as removed (`log_retention_removed`)."""
        if invocation['run_id'] is None:
            return set()
        return set(db.scalars(text(f"""SELECT json_extract(payload, '$.stream') FROM managed_events
            WHERE kind = '{REMOVED}' AND run_id = :run AND json_extract(payload, '$.attempt_id') = :a"""),
            {'run': invocation['run_id'], 'a': invocation['attempt_id']}).all())

    @staticmethod
    def _oversize(db, steps, invocation):
        sequences = sorted({ref['sequence'] for step in steps for ref in step.get('source_record') or []
                            if ref.get('oversize') and type(ref.get('sequence')) is int})
        if not sequences:
            return {}
        return {row['sequence']: _json(row['reference']) or {} for row in _rows(db, """
            SELECT sequence, json_extract(payload, '$.original_reference') AS reference FROM managed_events
            WHERE run_id = :run AND sequence IN (SELECT value FROM json_each(:seq)) AND kind = 'agent_event'""",
            run=invocation['run_id'], seq=json.dumps(sequences))}

    @staticmethod
    def _source_record(ref, oversize, removed):
        """T018 §6.4: links to the existing run-event and attempt-log routes, with availability; never content."""
        run, attempt, sequence = ref['run_id'], ref['attempt_id'], ref['sequence']
        record = {'run_id': run, 'attempt_id': attempt, 'sequence': sequence, 'record': ref.get('record'),
                  'oversize': bool(ref.get('oversize')),
                  'event': {'operation_id': 'managed_run_events', 'path': f'/api/managed/runs/{run}/events',
                            'query': {'after': sequence - 1, 'limit': 1}},
                  'log': None, 'availability': 'available', 'availability_source': 'derived'}
        if ref.get('oversize'):
            reference = oversize.get(sequence, {})
            record['log'] = {'operation_id': 'managed_attempt_logs',
                             'path': f'/api/managed/runs/{run}/attempts/{attempt}/logs',
                             'stream': reference.get('stream', 'stdout'), 'offset': reference.get('offset'),
                             'size': reference.get('size'), 'sha256': reference.get('sha256')}
            if reference.get('stream', 'stdout') in removed:
                record['availability'] = 'unavailable_after_retention'
        return record

    # --- L4: related records ----------------------------------------------------------------------------------

    def _standing(self, db, rows):
        """T010 validity of the page's request records with `PermissionLifecycle.active` (the canonical rule) and
        the reason it fails: an expiry or an end record in the request or its authorization ancestry, as T017
        resolves the item. The historical response (grant or deny) and the authority it currently confers are kept
        apart: a grant stops being effective when it, or its ancestry, expires or ends."""
        if not rows:
            return {}
        lifecycle = PermissionLifecycle(self.engine, clock=self.clock)
        clock = self.clock()
        result = {}
        with Session(bind=db) as session:
            for row in rows:
                record = session.get(PermissionRecordRow, row['id'])
                ends = set(db.scalars(text("""SELECT json_extract(payload, '$.record_id') FROM permission_records
                    WHERE project_id = :p AND kind = 'end'"""), {'p': record.project_id}))

                def lapse(item):
                    seen = set()
                    while item is not None and item.id not in seen:
                        seen.add(item.id)
                        expires = item.payload.get('expires_at')
                        if expires and clock >= expires:
                            return 'expired'
                        if item.id in ends:
                            return 'ended'
                        parent = item.payload.get('parent')
                        item = session.get(PermissionRecordRow, parent) if parent else None
                    return None
                answer = session.execute(text("""SELECT id, kind FROM permission_records WHERE project_id = :p
                    AND kind IN ('grant', 'deny') AND json_extract(payload, '$.request_id') = :r
                    ORDER BY sequence LIMIT 1"""), {'p': record.project_id, 'r': record.id}).mappings().first()
                try:
                    active = lifecycle.active(session, record)
                except Exception:  # an unreadable or tampered chain confers nothing (T010 `invalid`)
                    active = False
                if answer is not None:
                    status = 'GRANTED' if answer['kind'] == 'grant' else 'DENIED'
                    authority = None
                    if answer['kind'] == 'grant':
                        grant = session.get(PermissionRecordRow, answer['id'])
                        try:
                            effective = lifecycle.active(session, grant)
                        except Exception:
                            effective = False
                        authority = 'effective' if effective else lapse(grant) or 'invalid'
                    result[row['id']] = {'status': status, 'response': answer['kind'], 'authority': authority,
                                         'answerable': False}
                else:
                    reason = lapse(record)
                    status = 'EXPIRED' if reason == 'expired' else 'REVOKED' if reason == 'ended' else 'PENDING'
                    result[row['id']] = {'status': status, 'response': None, 'authority': None,
                                         'answerable': reason is None and active,
                                         **({'lapse': reason} if reason else {})}
        return result

    def _related_version(self, db, invocation, group):
        if group == 'records':
            marks = [db.scalar(text("SELECT max(id) FROM trace_events WHERE invocation_id = :i AND kind = :k"),
                               {'i': invocation['id'], 'k': kind}) for kind in sorted(RELATED)]
            return wm.version({'records': marks})
        if invocation['attempt_id'] is None:
            return wm.version({'permissions': []})
        root = invocation['run_root']
        return wm.version({'permissions': _rows(db, PERMISSION_MARKS, root=root, run=invocation['run_id'],
                                                attempt=invocation['attempt_id'], now=self.clock())[0]})

    def related(self, project: str, invocation_id: str, group: str, *, cursor=None, limit=wm.LIMITS['related']) -> dict:
        if group not in GROUPS:
            raise wm.TokenError('group')
        limit = max(1, min(int(limit), wm.LIMITS['related']))
        with self.engine.connect() as db:
            identity = self._project(db, project)
            invocation = self._invocation(db, identity, invocation_id)
            scope = wm.scope('related', identity['key'], invocation_id, group)
            version = self._related_version(db, invocation, group)
            if group == 'records':
                after = wm.read_cursor(cursor, scope, version, (int,))
                rows = _rows(db, """
                    SELECT e.id, e.event_id, e.kind, e.source, e.thread_id, e.operation_id, e.parent_event_id,
                           e.causation_id, e.payload, e.truncated, e.redactions, e.recorded_at
                    FROM trace_events e WHERE e.invocation_id = :i AND e.kind IN (SELECT value FROM json_each(:kinds))
                      AND e.id > :after ORDER BY e.id LIMIT :limit""", i=invocation_id,
                             kinds=json.dumps(sorted(RELATED)), after=after[0] if after else 0, limit=limit + 1)
                shown = rows[:limit]
                artifacts = {}
                for row in _rows(db, """SELECT event_id, sha256, size, media FROM trace_artifacts
                        WHERE event_id IN (SELECT value FROM json_each(:ids)) ORDER BY event_id, sha256""",
                                 ids=json.dumps([r['event_id'] for r in shown])):
                    artifacts.setdefault(row['event_id'], []).append(row)
                items = [self._record_view(row, artifacts.get(row['event_id'], []), identity) for row in shown]
                next_cursor = wm.cursor(scope, version, [shown[-1]['id']]) if len(rows) > limit else None
            else:
                after = wm.read_cursor(cursor, scope, version, (str, str))
                rows = [] if invocation['attempt_id'] is None else _rows(
                    db, PERMISSIONS, run=invocation['run_id'], root=invocation['run_root'],
                    attempt=invocation['attempt_id'], now=self.clock(), created=after[0] if after else None,
                    id=after[1] if after else None, limit=limit + 1)
                shown = rows[:limit]
                standing = self._standing(db, [r for r in shown if r['source'] == 'standing_permission'])
                items = []
                for r in shown:
                    if r['source'] == 'run_permission':
                        state = {'status': r['status'], 'response': {'GRANTED': 'grant', 'DENIED': 'deny',
                                                                     'CONSUMED': 'grant',
                                                                     'DENIED_CONSUMED': 'deny'}.get(r['status']),
                                 'authority': 'effective' if r['status'] == 'GRANTED' else None,
                                 'answerable': r['status'] == 'PENDING'}
                    else:
                        state = standing[r['id']]
                    items.append({'source': r['source'], 'id': r['id'],
                                  'status': {**wm.status('permission', state['status']),
                                             **({'lapse': state['lapse']} if state.get('lapse') else {})},
                                  'response': state['response'], 'authority': state['authority'],
                                  'answerable': state['answerable'], 'created_at': r['created_at'],
                                  'expires_at': r['expires_at'],
                                  'inbox_item_id': ('run-permission:' if r['source'] == 'run_permission'
                                                    else 'standing-permission:') + r['id']})
                next_cursor = wm.cursor(scope, version, [shown[-1]['created_at'], shown[-1]['id']]) \
                    if len(rows) > limit else None
            return {'format': wm.FORMAT, 'level': 'related', 'scope': scope, 'version': version,
                    'read_only_archive': self._archive(db), 'project': self._head(identity),
                    'invocation_id': invocation_id, 'group': group, 'items': items, 'next_cursor': next_cursor}

    @staticmethod
    def _record_view(row, artifacts, identity):
        category, fields = RELATED[row['kind']]
        payload = _json(row['payload']) or {}
        thread = row['thread_id']
        project = identity['knowledge_project_id']
        return {'sequence': row['id'], 'event_id': row['event_id'], 'kind': row['kind'], 'category': category,
                'source': row['source'], 'operation_id': row['operation_id'], 'thread_id': thread,
                'parent_event_id': row['parent_event_id'], 'causation_id': row['causation_id'],
                'recorded_at': row['recorded_at'], 'truncated': bool(row['truncated']), 'redactions': row['redactions'],
                'fields': {key: _bounded(payload[key]) for key in fields if key in payload},
                'artifacts': [{'sha256': a['sha256'], 'size': a['size'], 'media': a['media'],
                               'path': f"/api/managed/knowledge/projects/{project}/traces/{thread}/artifacts/{a['sha256']}"
                               if thread and project else None} for a in artifacts]}

    # --- activity poll ----------------------------------------------------------------------------------------

    def activity(self, scopes: list[str]) -> dict:
        if not isinstance(scopes, list) or len(scopes) > wm.MAX_SCOPES:
            raise wm.TokenError('scope')
        decoded = [(value, *wm.read_scope(value)) for value in scopes]
        with self.engine.connect() as db:
            archive = self._archive(db)
            active = self._active(db)
            harness = self._harness(db)
            bubbles = self._bubbles(db)
            results = []
            for value, level, parts in decoded:
                try:
                    results.append({'scope': value, 'version': self._version(db, level, parts, bubbles, active, harness)})
                except (MapNotFound, LookupError):
                    results.append({'scope': value, 'version': None, 'error': 'not_found'})
            keys = {p['root']: p['key'] for p in self._identities(db, {a['root'] for a in active} | set(harness))}
            listed = active[:50]
            return {'format': wm.FORMAT, 'read_only_archive': archive,
                    'polling': {**wm.POLLING, 'enabled': not archive},
                    'active': bool(active or harness), 'scopes': results,
                    'active_invocations': [{**self._active_view(a), 'project_id': keys.get(a['root'])} for a in listed],
                    'active_invocations_truncated': len(active) > len(listed),
                    'unscoped_invocations': self._unscoped(db),
                    'harness': sorted(keys[root] for root in harness if root in keys),
                    'bubbles': self._bubble_view(bubbles)}

    def _version(self, db, level, parts, bubbles, active, harness):
        if level == 'projects':
            return self._projects_version(db, bubbles, active, harness)
        identity = self._project(db, parts[0])
        if identity['key'] != parts[0]:
            raise MapNotFound(parts[0])
        root = identity['root']
        if level in ('phases', 'tasks'):
            if level == 'tasks':
                self._phase(db, identity, parts[1])
            return self._root_version(db, identity, bubbles=[b for b in bubbles if b['root'] == root],
                                      active=[a for a in active if a['root'] == root], harness=harness.get(root, []))
        if level == 'runs':
            revision, phase = self._phase(db, identity, parts[1])
            if not self._task_exists(db, root, revision, phase, parts[2]):
                raise MapNotFound(parts[2])
            return self._runs_version(db, root, parts[1], parts[2])
        if level == 'steps':
            return self._steps_version(db, self._run(db, identity, parts[1]))
        invocation = self._invocation(db, identity, parts[1])
        if level == 'invocation':
            return self._invocation_version(db, invocation)
        if level == 'trace':
            return self._trace_version(db, invocation)
        if parts[2] not in GROUPS:
            raise MapNotFound('scope')
        return self._related_version(db, invocation, parts[2])
