"""P002-T017: read-through projection of committed owner-facing facts.

Each branch chooses one authoritative representation. Trace mirrors of phase events and
autonomous wait events that repeat question creation are intentionally not unioned.
Only read marks are stored here. Filtering and keyset paging happen in SQLite.
"""
import json

from sqlalchemy import text

from my_harness.core.engine.trace_payload import MASK, SECRET_VALUES
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.operation_journal import now

# Each branch emits identifiers, fixed codes and state only. The source JSON is never serialized
# into the list. Joins include the owner when an event's payload carries a secondary reference.
FACTS = """
WITH facts(id, kind, topic, source_mode, root, at, origin, event_id, phase_id, task_id, run_id,
           operation_id, request_id, evidence_id, thread_id, resolved) AS (
    SELECT 'run-permission:' || p.id, 'permission', 'run_permission', 'manual', r.root, e.recorded_at,
           'managed', CAST(e.id AS TEXT), r.phase_id, r.task_id, r.id, w.id, p.id,
           a.id, w.thread_id,
           p.status != 'PENDING' OR p.expires_at <= :now OR r.status = 'COMMITTED'
    FROM managed_events e
    JOIN permission_requests p ON p.id = json_extract(e.payload, '$.id') AND p.run_id = e.run_id
    JOIN managed_runs r ON r.id = p.run_id
    LEFT JOIN managed_attempts a ON a.id = json_extract(p.request, '$.source_attempt_id') AND a.run_id = r.id
    LEFT JOIN workflow_operations w ON w.attempt_id = a.id AND w.root = r.root
    WHERE e.kind = 'permission_requested'

    UNION ALL
    SELECT 'standing-permission:' || p.id, 'permission', 'standing_permission', 'manual', e.root, e.recorded_at,
           'trace', e.event_id, r.phase_id, r.task_id, r.id, w.id, p.id,
           CASE WHEN r.id IS NOT NULL THEN a.id END, w.thread_id,
           EXISTS (
               SELECT 1 FROM permission_records x WHERE x.project_id = p.project_id
                 AND x.kind IN ('grant', 'deny') AND json_extract(x.payload, '$.request_id') = p.id
           ) OR EXISTS (
               WITH RECURSIVE ancestry(id, payload) AS (
                   SELECT p.id, p.payload
                   UNION
                   SELECT parent.id, parent.payload FROM permission_records parent JOIN ancestry child
                     ON parent.id = json_extract(child.payload, '$.parent')
                    AND parent.project_id = p.project_id AND parent.kind = 'authorization'
               )
               SELECT 1 FROM ancestry WHERE json_extract(payload, '$.expires_at') <= :now
                 OR EXISTS (SELECT 1 FROM permission_records x WHERE x.project_id = p.project_id
                            AND x.kind = 'end' AND json_extract(x.payload, '$.record_id') = ancestry.id)
           )
    FROM trace_events e
    JOIN permission_records p ON p.id = json_extract(e.payload, '$.record_id') AND p.kind = 'request'
    JOIN knowledge_projects k ON k.id = p.project_id AND k.root = e.root
    LEFT JOIN managed_attempts a ON a.id = json_extract(p.payload, '$.source_attempt_id')
    LEFT JOIN managed_runs r ON r.id = a.run_id AND r.root = k.root
    LEFT JOIN workflow_operations w ON w.attempt_id = a.id AND w.root = r.root
    WHERE e.kind = 'permission.request'

    UNION ALL
    SELECT 'gap:' || e.id,
           'question', 'task_gap', 'manual', r.root, e.recorded_at, 'managed', CAST(e.id AS TEXT),
           r.phase_id, r.task_id, r.id, w.id, CAST(e.id AS TEXT), a.id, w.thread_id,
           r.status = 'COMMITTED' OR EXISTS (
               SELECT 1 FROM managed_events x WHERE x.run_id = r.id AND x.kind = 'task_decision_requested'
                 AND json_extract(x.payload, '$.kind') = 'blocking_questions'
                 AND json_extract(x.payload, '$.request_sha256') != json_extract(e.payload, '$.request_sha256')
                 AND x.sequence > e.sequence
           ) OR EXISTS (
               SELECT 1 FROM managed_events x WHERE x.run_id = r.id AND x.kind = 'task_gap_resolved'
                 AND json_extract(x.payload, '$.request_sha256') = json_extract(e.payload, '$.request_sha256')
                 AND (
                   EXISTS (SELECT 1 FROM managed_events y WHERE y.run_id = r.id
                           AND y.kind = 'task_gap_resolution_applied'
                           AND json_extract(y.payload, '$.resolution_id') = x.id)
                   OR (json_extract(x.payload, '$.expires_at') > :now AND NOT EXISTS (
                       SELECT 1 FROM managed_events y WHERE y.run_id = r.id
                         AND y.kind = 'task_gap_resolution_revoked'
                         AND json_extract(y.payload, '$.resolution_id') = x.id
                   ))
                 )
           )
    FROM managed_events e JOIN managed_runs r ON r.id = e.run_id
    LEFT JOIN managed_attempts a ON a.id = json_extract(e.payload, '$.source_attempt_id') AND a.run_id = r.id
    LEFT JOIN workflow_operations w ON w.attempt_id = a.id AND w.root = r.root
    WHERE e.kind = 'task_decision_requested' AND json_extract(e.payload, '$.kind') = 'blocking_questions'
      AND e.id = (SELECT x.id FROM managed_events x WHERE x.run_id = r.id AND x.kind = e.kind
                  AND json_extract(x.payload, '$.kind') = 'blocking_questions'
                  AND json_extract(x.payload, '$.request_sha256') = json_extract(e.payload, '$.request_sha256')
                  ORDER BY x.sequence LIMIT 1)

    UNION ALL
    SELECT 'phase-question:' || q.id, 'question', 'phase_question', 'manual', p.root, q.created_at,
           'phase', CAST(e.id AS TEXT), p.code, NULL, r.id, op.id, q.id, q.id, NULL,
           q.status != 'OPEN' OR p.status IN ('CLOSED', 'ABANDONED')
    FROM phase_questions q
    JOIN managed_phases p ON p.id = q.phase_id
    JOIN phase_events e ON e.phase_id = p.id AND (
         (e.kind = 'question_raised' AND json_extract(e.payload, '$.id') = q.id)
         OR (e.kind = 'phase_checked' AND json_extract(q.source, '$.kind') = 'phase_check'
             AND json_extract(e.payload, '$.operation_id') = json_extract(q.source, '$.operation_id'))
    )
    LEFT JOIN phase_operations op ON op.id = json_extract(q.source, '$.operation_id') AND op.phase_id = p.id
    LEFT JOIN managed_runs r ON r.id = op.run_id AND r.root = p.root

    UNION ALL
    SELECT 'phase-ready:' || op.id, 'lifecycle', 'phase_ready', 'manual', p.root, e.recorded_at, 'phase',
           CAST(e.id AS TEXT), p.code, NULL, r.id, op.id, NULL, op.id, NULL,
           p.status NOT IN ('READY_TO_CLOSE', 'CLOSING') OR op.status != 'READY'
           OR op.id != (SELECT x.id FROM phase_operations x WHERE x.phase_id = p.id AND x.kind = 'check'
                        ORDER BY x.created_at DESC, x.id DESC LIMIT 1)
    FROM phase_events e JOIN managed_phases p ON p.id = e.phase_id
    JOIN phase_operations op ON op.id = json_extract(e.payload, '$.operation_id') AND op.phase_id = p.id
    LEFT JOIN managed_runs r ON r.id = op.run_id AND r.root = p.root
    WHERE e.kind = 'phase_checked' AND json_extract(e.payload, '$.status') = 'READY_TO_CLOSE'

    UNION ALL
    SELECT 'judge:' || j.id, 'judge', 'judge_escalation', 'manual', e.root, e.recorded_at, 'trace',
           e.event_id, p.code, NULL, r.id, COALESCE(w.id, CASE WHEN p.id IS NOT NULL THEN op.id END),
           j.id, u.id, w.thread_id,
           -- Resolution follows the blocker the escalation came from (D302): an answered correlated permission
           -- escalation, the phase check it judged no longer being current or its phase ended, or every autonomous
           -- stop that carries this request closed. A decision link, a read mark or opening the item never counts;
           -- without a derivable blocker the item stays unresolved.
           EXISTS (SELECT 1 FROM permission_records esc JOIN permission_records answer
                   ON answer.project_id = esc.project_id AND answer.kind IN ('grant', 'deny')
                   AND json_extract(answer.payload, '$.request_id') = json_extract(esc.payload, '$.request_id')
                   WHERE esc.project_id = j.project_id AND esc.kind = 'escalate'
                   AND json_extract(esc.payload, '$.ruling_id') = u.id)
           OR (op.kind = 'check' AND p.id IS NOT NULL AND (
               p.status IN ('CLOSED', 'ABANDONED')
               OR op.id != (SELECT x.id FROM phase_operations x WHERE x.phase_id = p.id AND x.kind = 'check'
                            ORDER BY x.created_at DESC, x.id DESC LIMIT 1)))
           OR (EXISTS (SELECT 1 FROM autonomous_events s JOIN autonomous_runs ar ON ar.id = s.run_id AND ar.root = s.root
                       WHERE s.root = k.root AND substr(s.kind, 1, 4) = 'run_'
                         AND json_extract(s.payload, '$.detail.stop.judge_request_id') = j.id)
               AND NOT EXISTS (
                   SELECT 1 FROM autonomous_events s JOIN autonomous_runs ar ON ar.id = s.run_id AND ar.root = s.root
                   WHERE s.root = k.root AND substr(s.kind, 1, 4) = 'run_'
                     AND json_extract(s.payload, '$.detail.stop.judge_request_id') = j.id
                     AND ar.status NOT IN ('REVOKED', 'COMPLETED')
                     AND CASE WHEN json_extract(s.refs, '$.question_id') IS NOT NULL
                         THEN NOT EXISTS (SELECT 1 FROM autonomous_questions q
                                          WHERE q.id = json_extract(s.refs, '$.question_id') AND q.run_id = ar.id
                                            AND q.status != 'OPEN')
                         ELSE NOT EXISTS (SELECT 1 FROM autonomous_events x WHERE x.run_id = ar.id AND x.id > s.id
                                          AND x.kind IN ('run_running', 'run_waiting_for_owner', 'run_paused',
                                                         'run_limit_reached', 'run_recovery_required', 'run_failed',
                                                         'run_revoked', 'run_completed'))
                     END))
    FROM trace_events e
    JOIN judge_rulings u ON u.id = json_extract(e.payload, '$.ruling_id') AND u.status = 'ESCALATED'
    JOIN judge_requests j ON j.id = u.request_id
    JOIN knowledge_projects k ON k.id = j.project_id AND k.root = e.root
    LEFT JOIN workflow_operations w ON w.id = e.operation_id AND w.root = k.root
    LEFT JOIN phase_operations op ON op.id = json_extract(j.payload, '$.evidence.check_operation_id')
    LEFT JOIN managed_phases p ON p.id = op.phase_id AND p.root = k.root
    LEFT JOIN managed_runs r ON r.id = op.run_id AND r.root = k.root AND p.id IS NOT NULL
    WHERE e.kind = 'judge.ruled' AND json_extract(e.payload, '$.status') = 'ESCALATED'
      AND json_extract(e.payload, '$.continuation') = 'owner'
      AND json_extract(u.payload, '$.continuation') = 'owner'
      AND json_extract(e.payload, '$.request_id') = j.id

    UNION ALL
    SELECT 'auto-question:' || q.id, 'question', 'autonomous_question', 'autonomous', r.root, e.created_at,
           'autonomous', CAST(e.id AS TEXT), p.code, COALESCE(task_id.code, task_code.code), r.id,
           op.id, q.id, q.id, r.thread_id,
           q.status != 'OPEN' OR r.status IN ('REVOKED', 'COMPLETED')
    FROM autonomous_events e
    JOIN autonomous_runs r ON r.id = e.run_id AND r.root = e.root
    JOIN autonomous_questions q ON q.id = json_extract(e.refs, '$.question_id') AND q.run_id = r.id
    JOIN autonomous_authorizations a ON a.id = r.authorization_id AND a.root = r.root
    LEFT JOIN managed_phases p ON p.root = r.root AND p.code = json_extract(q.subject, '$.phase')
    LEFT JOIN knowledge_items task_id ON task_id.project_id = a.project_id AND task_id.kind = 'task'
        AND task_id.id = json_extract(q.subject, '$.task')
    LEFT JOIN knowledge_items task_code ON task_code.project_id = a.project_id AND task_code.kind = 'task'
        AND task_code.document IS NULL AND task_code.code = json_extract(q.subject, '$.task')
    LEFT JOIN phase_operations op ON op.id = json_extract(q.subject, '$.operation_id') AND op.phase_id = p.id
    WHERE e.kind = 'question_opened'

    UNION ALL
    SELECT 'auto-stop:' || e.id, 'lifecycle', substr(e.kind, 5), 'autonomous', r.root, e.created_at,
           'autonomous', CAST(e.id AS TEXT), COALESCE(p.code, mr.phase_id), mr.task_id, r.id,
           op.id, NULL, CAST(e.id AS TEXT), r.thread_id,
           EXISTS (SELECT 1 FROM autonomous_events x WHERE x.run_id = r.id AND x.id > e.id
                   AND x.kind IN ('run_running', 'run_waiting_for_owner', 'run_paused', 'run_limit_reached',
                                  'run_recovery_required', 'run_failed', 'run_revoked', 'run_completed'))
    FROM autonomous_events e JOIN autonomous_runs r ON r.id = e.run_id AND r.root = e.root
    LEFT JOIN managed_phases p ON p.root = r.root AND p.code = COALESCE(json_extract(e.refs, '$.phase'),
                                                                      json_extract(e.payload, '$.detail.stop.phase'))
    LEFT JOIN managed_runs mr ON mr.root = r.root
        AND mr.id = COALESCE(NULLIF(json_extract(e.refs, '$.run_id'), r.id), json_extract(e.payload, '$.detail.stop.run_id'))
    LEFT JOIN phase_operations op ON op.phase_id = p.id AND op.id = COALESCE(json_extract(e.refs, '$.operation_id'),
                                                                           json_extract(e.payload, '$.detail.stop.operation_id'))
    WHERE e.kind IN ('run_limit_reached', 'run_recovery_required', 'run_failed')

    UNION ALL
    SELECT 'task-completed:' || c.operation_id, 'notification', 'task_completed',
           CASE WHEN EXISTS (SELECT 1 FROM managed_events x WHERE x.run_id = r.id AND x.kind = 'task_delegated')
                THEN 'autonomous' ELSE 'manual' END,
           r.root, e.recorded_at, 'managed', CAST(e.id AS TEXT), r.phase_id, r.task_id, r.id,
           c.operation_id, NULL, c.commit_sha, NULL, 1
    FROM managed_events e JOIN managed_runs r ON r.id = e.run_id
    JOIN managed_commits c ON c.operation_id = json_extract(e.payload, '$.operation_id')
        AND c.run_id = r.id AND c.status = 'COMMITTED'
    WHERE e.kind = 'commit_recorded' AND r.purpose = 'task' AND r.status = 'COMMITTED'
      AND json_extract(e.payload, '$.status') = 'COMMITTED'

    UNION ALL
    SELECT 'phase-closed:' || op.id, 'notification', 'phase_closed',
           CASE WHEN json_extract(a.scope, '$.origin') = 'owner_delegated'
                THEN 'autonomous' ELSE 'manual' END,
           p.root, e.recorded_at, 'phase', CAST(e.id AS TEXT), p.code, NULL, r.id,
           op.id, NULL, op.id, NULL, 1
    FROM phase_events e JOIN managed_phases p ON p.id = e.phase_id
    JOIN phase_operations op ON op.id = json_extract(e.payload, '$.operation_id')
        AND op.phase_id = p.id AND op.kind = 'close' AND op.status = 'CLOSED'
    LEFT JOIN phase_authorizations a ON a.id = json_extract(op.request, '$.authorization_id') AND a.phase_id = p.id
    LEFT JOIN managed_runs r ON r.id = op.run_id AND r.root = p.root
    WHERE e.kind = 'phase_closed' AND p.status = 'CLOSED' AND json_extract(e.payload, '$.status') = 'CLOSED'
),
deduped AS (
    SELECT *, row_number() OVER (PARTITION BY id ORDER BY
           CASE WHEN origin = 'trace' THEN (SELECT id FROM trace_events WHERE trace_events.event_id = facts.event_id)
                ELSE CAST(event_id AS INTEGER) END) AS delivery
    FROM facts WHERE (:root IS NULL OR root = :root)
),
delegated AS (
    SELECT j.run_id, min(a.id) AS autonomous_run_id
    FROM autonomous_children c JOIN autonomous_runs a ON a.id = c.run_id
    JOIN managed_jobs j ON j.idempotency_key = c.operation_key
    JOIN managed_runs r ON r.id = j.run_id AND r.root = a.root
    GROUP BY j.run_id
),
linked AS (
    SELECT d.*,
           CASE WHEN d.origin = 'autonomous' THEN d.run_id ELSE COALESCE(a.autonomous_run_id, (
               SELECT r.id FROM judge_requests j
               JOIN autonomous_authorizations b ON b.id = json_extract(j.payload, '$.policy.id')
                    AND b.project_id = j.project_id AND b.root = d.root
               JOIN autonomous_runs r ON r.lineage_id = b.lineage_id AND r.root = b.root
               WHERE d.topic = 'judge_escalation' AND j.id = d.request_id
                 AND instr(j.subject, 'roadmap:' || b.permission_record_id || ':') = 1
           )) END AS autonomous_run_id
    FROM deduped d LEFT JOIN delegated a ON a.run_id = d.run_id AND d.origin != 'autonomous'
    WHERE d.delivery = 1
),
items AS (
    SELECT d.*, m.read_at,
           CASE WHEN d.autonomous_run_id IS NOT NULL THEN 'autonomous' ELSE d.source_mode END AS mode,
           p.id AS phase_instance_id,
           CASE WHEN d.origin = 'autonomous' THEN (SELECT status FROM autonomous_runs WHERE id = d.run_id)
                WHEN d.origin = 'phase' THEN p.status
                WHEN d.origin = 'managed' THEN (SELECT status FROM managed_runs WHERE id = d.run_id)
           END AS current_state
    FROM linked d LEFT JOIN inbox_read_marks m ON m.item_id = d.id
    LEFT JOIN managed_phases p ON p.root = d.root AND p.code = d.phase_id
)
"""

# The legacy ledgers are root-scoped. Prefer a persisted project ID for archive links, falling back
# to the first run or phase of that checkout when no project was ever persisted.
PROJECTS = """
WITH roots(root) AS (SELECT value FROM json_each(:roots))
    SELECT roots.root, k.id AS knowledge_id,
           COALESCE(k.id, rp.id,
               'run:' || (SELECT r.id FROM managed_runs r WHERE r.root = roots.root ORDER BY r.rowid LIMIT 1),
               'phase:' || (SELECT p.id FROM managed_phases p WHERE p.root = roots.root ORDER BY p.rowid LIMIT 1)) AS project_id
    FROM roots LEFT JOIN knowledge_projects k ON k.root = roots.root
    LEFT JOIN registered_projects rp ON rp.root = roots.root AND rp.status = 'ACTIVE'
"""

ITEM_FIELDS = ('id', 'kind', 'topic', 'mode', 'at', 'origin', 'event_id', 'phase_id', 'phase_instance_id', 'task_id', 'run_id',
               'operation_id', 'request_id', 'evidence_id', 'thread_id', 'read_at', 'current_state', 'autonomous_run_id')


class Inbox:
    def __init__(self, engine, projects, clock=now):
        self.engine = engine
        self.clock = clock
        self.projects = projects  # registered UI IDs and checkout roots; no checkout or provider access

    def _root(self, db, project, *, include_retired=False):
        if project is None:
            return None
        root = db.scalar(text("""
            SELECT root FROM knowledge_projects WHERE id = :project
            UNION ALL SELECT root FROM registered_projects WHERE id = :project AND (status = 'ACTIVE' OR :include_retired)
            UNION ALL SELECT root FROM managed_runs WHERE id = substr(:project, 5) AND :project LIKE 'run:%'
            UNION ALL SELECT root FROM managed_phases WHERE id = substr(:project, 7) AND :project LIKE 'phase:%'
            LIMIT 1
        """), {'project': project, 'include_retired': include_retired}) or self.projects.get(project)
        if root is None:
            raise LookupError(project)
        return root

    def project_root(self, project):
        """Resolve a persisted consultation identity without composing a checkout."""
        with self.engine.connect() as db:
            return self._root(db, project, include_retired=True)

    def _views(self, db, rows):
        if not rows:
            return []
        roots = sorted({row['root'] for row in rows})
        projects = db.execute(text(PROJECTS), {'roots': json.dumps(roots)}).mappings()
        by_root = {row['root']: row for row in projects}
        configured = {root: ident for ident, root in self.projects.items()}
        return [{**{key: row[key] for key in ITEM_FIELDS},
                 'project_id': by_root[row['root']]['project_id'],
                 'knowledge_project_id': by_root[row['root']]['knowledge_id'],
                 'registered_project_id': configured.get(row['root']),
                 'resolved': bool(row['resolved'])} for row in rows]

    def page(self, project, *, kind, mode, state, before, limit):
        with self.engine.connect() as db:
            params = {'root': self._root(db, project), 'kind': kind, 'mode': mode, 'state': state, 'before': before,
                      'now': self.clock(), 'limit': limit + 1}
            if before is not None and self._item(db, before, params['root']) is None:
                raise LookupError(before)
            rows = db.execute(text(FACTS + """
                SELECT * FROM items WHERE (:kind IS NULL OR kind = :kind)
                  AND (:mode IS NULL OR mode = :mode)
                  AND (:state IS NULL OR (:state = 'unread' AND read_at IS NULL)
                       OR (:state = 'unresolved' AND NOT resolved) OR (:state = 'resolved' AND resolved))
                  AND (:before IS NULL OR (at, id) < (SELECT at, id FROM items WHERE id = :before))
                ORDER BY at DESC, id DESC LIMIT :limit
            """), params).mappings().all()
            return {'items': self._views(db, rows[:limit]),
                    'next_before': rows[limit - 1]['id'] if len(rows) > limit else None}

    def _item(self, db, item, root):
        return db.execute(text(FACTS + 'SELECT * FROM items WHERE id = :item'),
                          {'now': self.clock(), 'root': root, 'item': item}).mappings().first()

    def item(self, project, item):
        with self.engine.connect() as db:
            row = self._item(db, item, self._root(db, project))
            if row is None:
                raise LookupError(item)
            view = self._views(db, [row])[0]
            writable = view['registered_project_id'] and not db.scalar(text('PRAGMA query_only'))
            view['response'] = self._response(db, row) if writable and not view['resolved'] else None
            view['standing_permission'] = self._standing_permission(db, row) if writable and not view['resolved'] else None
            view['continuation'] = self._continuation(db, row) if writable else None
            view['context'] = self._context(db, row)
            return view

    def mark_read(self, project, item):
        with self.engine.begin() as db:
            if (db.scalar(text('PRAGMA user_version')) == RESTORED_USER_VERSION
                    or db.scalar(text('PRAGMA query_only'))):
                raise PermissionError('restored_read_only')
            # Serialize the existence check and insert with ordinary domain writers.
            db.execute(text('UPDATE inbox_read_marks SET read_at = read_at WHERE 0'))
            row = self._item(db, item, self._root(db, project))
            if row is None:
                raise LookupError(item)
            db.execute(text("""
                INSERT INTO inbox_read_marks (item_id, read_at) VALUES (:item, :at)
                ON CONFLICT (item_id) DO NOTHING
            """), {'item': item, 'at': self.clock()})
            return self._views(db, [self._item(db, item, row['root'])])[0]

    def _response(self, db, row):
        """Small, origin-bound envelopes for the existing command routes."""
        query = RESPONSES.get(row['topic'])
        if query is None:
            return None
        response = db.execute(text(query), {'root': row['root'], 'run': row['run_id'],
            'request': row['request_id'], 'event': row['event_id']}).mappings().first()
        if response is None:
            return None
        data = dict(response)
        prompts = json.loads(data.pop('prompts')) if 'prompts' in data else []
        if not isinstance(prompts, list) or len(prompts) > 100:
            return None
        data['prompts'] = [safe_prompt(value) for value in prompts]
        if row['topic'] == 'run_permission' and data['prompts'] != prompts:
            return None
        return data

    def _context(self, db, row):
        query = CONTEXT.get(row['topic'])
        if query is None:
            return []
        values = db.scalar(text(query), {'event': row['event_id'], 'request': row['request_id'],
                                         'evidence': row['evidence_id']})
        prompts = json.loads(values) if values else []
        return [safe_prompt(value) for value in prompts[:100]] if isinstance(prompts, list) else []

    def _continuation(self, db, row):
        if row['topic'] != 'task_gap':
            return None
        result = db.execute(text("""
            SELECT r.id AS target_id, r.version, x.id AS resolution_id
            FROM managed_runs r JOIN managed_events e ON e.run_id = r.id AND e.id = :event
            JOIN managed_events gap ON gap.id = (
                SELECT id FROM managed_events WHERE run_id = r.id AND kind = 'task_decision_requested'
                  AND json_extract(payload, '$.kind') = 'blocking_questions' ORDER BY sequence DESC LIMIT 1)
            JOIN managed_events x ON x.run_id = r.id AND x.kind = 'task_gap_resolved'
                AND json_extract(x.payload, '$.gap_event_id') = gap.id
            WHERE r.id = :run AND r.root = :root AND r.status IN ('STOPPED', 'BLOCKED', 'REVISION_LIMIT', 'INTERRUPTED')
              AND json_extract(gap.payload, '$.request_sha256') = json_extract(e.payload, '$.request_sha256')
              AND json_extract(x.payload, '$.expires_at') > :now
              AND NOT EXISTS (SELECT 1 FROM managed_events y WHERE y.run_id = r.id
                  AND y.kind IN ('task_gap_resolution_applied', 'task_gap_resolution_revoked')
                  AND json_extract(y.payload, '$.resolution_id') = x.id)
            LIMIT 1
        """), {'root': row['root'], 'run': row['run_id'], 'event': row['event_id'], 'now': self.clock()}).mappings().first()
        return dict(result) if result else None

    def _standing_permission(self, db, row):
        if row['topic'] != 'standing_permission':
            return None
        found = db.execute(text("""
            SELECT json_extract(p.payload, '$.targets') AS targets,
                   json_extract(p.payload, '$.duration') AS duration,
                   (SELECT max(x.sequence) FROM permission_records x WHERE x.project_id = p.project_id) AS revision
            FROM permission_records p
            LEFT JOIN managed_attempts a ON a.id = json_extract(p.payload, '$.source_attempt_id')
            WHERE p.id = :request AND (a.id IS NULL OR a.result_json IS NOT NULL)
        """), {'request': row['request_id']}).mappings().first()
        if found is None:
            return None
        targets = json.loads(found['targets'])
        if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
            return None
        shown = [json.dumps(target, ensure_ascii=False, sort_keys=True) for target in targets]
        if any(safe_prompt(target) != target for target in shown):
            return None  # consent requires the owner to see the exact targets
        return {'revision': found['revision'], 'duration': json.loads(found['duration']), 'targets': shown}



# These reads never provide a new authority. The corresponding write commands validate the
# same request, versions and proof under the ordinary writer lock.
RESPONSES = {
    'run_permission': """
        SELECT r.id AS target_id, r.version, p.version AS request_version, p.fingerprint AS proof,
               json_array(json_extract(p.request, '$.operation'), json_extract(p.request, '$.target')) AS prompts
        FROM permission_requests p JOIN managed_runs r ON r.id = p.run_id
        WHERE p.id = :request AND r.id = :run AND r.root = :root
          AND r.status IN ('STOPPED', 'BLOCKED', 'REVISION_LIMIT', 'INTERRUPTED')
    """,
    'task_gap': """
        SELECT r.id AS target_id, r.version, x.id AS request_version,
               json_extract(x.payload, '$.request_sha256') AS proof,
               json_extract(x.payload, '$.questions') AS prompts
        FROM managed_runs r JOIN managed_events e ON e.id = :event AND e.run_id = r.id
        JOIN managed_events x ON x.id = (SELECT id FROM managed_events
            WHERE run_id = r.id AND kind = 'task_decision_requested'
              AND json_extract(payload, '$.kind') = 'blocking_questions' ORDER BY sequence DESC LIMIT 1)
        WHERE r.id = :run AND r.root = :root AND r.status IN ('STOPPED', 'BLOCKED', 'REVISION_LIMIT', 'INTERRUPTED')
          AND json_extract(x.payload, '$.request_sha256') = json_extract(e.payload, '$.request_sha256')
          AND NOT EXISTS (SELECT 1 FROM managed_events y WHERE y.run_id = r.id AND y.kind = 'task_gap_resolved'
                          AND json_extract(y.payload, '$.gap_event_id') = x.id)
    """,
    'phase_question': """
        SELECT p.id AS target_id, p.version, q.version AS request_version, json_array(q.text) AS prompts
        FROM phase_questions q JOIN managed_phases p ON p.id = q.phase_id
        WHERE q.id = :request AND p.root = :root AND p.status NOT IN ('CLOSING', 'CLOSED', 'ABANDONED')
    """,
    'autonomous_question': """
        SELECT r.id AS target_id, r.version, q.version AS request_version, json_array(q.kind) AS prompts
        FROM autonomous_questions q JOIN autonomous_runs r ON r.id = q.run_id
        WHERE q.id = :request AND r.id = :run AND r.root = :root AND r.status = 'WAITING_FOR_OWNER'
    """,
}


# Only the prompt or fixed evidence fields needed in a conversation are shown, also in archives.
# All identities below came from the root-scoped joins above.
CONTEXT = {
    'task_gap': "SELECT json_extract(payload, '$.questions') FROM managed_events WHERE id = :event",
    'phase_question': 'SELECT json_array(text) FROM phase_questions WHERE id = :request',
    'autonomous_question': 'SELECT json_array(kind) FROM autonomous_questions WHERE id = :request',
    'run_permission': """SELECT json_array(json_extract(request, '$.operation'), json_extract(request, '$.target'))
                         FROM permission_requests WHERE id = :request""",
    'standing_permission': """SELECT json_array(json_extract(payload, '$.dimension'), json_extract(payload, '$.grantee'))
                              FROM permission_records WHERE id = :request""",
    'judge_escalation': """SELECT json_array(j.duty, u.status, COALESCE(json_extract(u.payload, '$.candidate.rationale'),
                          json_extract(u.payload, '$.reason'))) FROM judge_rulings u
                          JOIN judge_requests j ON j.id = u.request_id WHERE j.id = :request AND u.id = :evidence""",
    **dict.fromkeys(('limit_reached', 'recovery_required', 'failed'),
                    "SELECT json_array(json_extract(payload, '$.reason')) FROM autonomous_events WHERE id = :event"),
}


def safe_prompt(value):
    """Bound owner-visible context without copying raw event bodies or credential-shaped text."""
    value = value if isinstance(value, str) else ''
    for pattern in SECRET_VALUES:
        value = pattern.sub(MASK, value)
    return value if len(value) <= 1000 else value[:999] + '…'
