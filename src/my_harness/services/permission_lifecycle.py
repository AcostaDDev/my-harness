"""D291 permission authority. Trusted consumers prepare boundaries; models never supply authority."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.core.engine import domain_policy, permission_targets as targets
from my_harness.core.engine.domain_catalogue import digest
from my_harness.core.engine.judge import duration_check as judge_duration_check, within, DURATION
from my_harness.core.engine.domain_catalogue import validate
from my_harness.storage.models import (PermissionRecordRow as Record, PermissionBoundaryRow as Boundary,
    KnowledgeProjectRow as Project, JudgeRulingRow, JudgeRequestRow)
from my_harness.storage.operation_journal import record_event


def duration_check(value):
    validate(DURATION, value)
    judge_duration_check(value)


def delegation_within(child, parent):
    """Every delegable tier and eligibility/evidence bound narrows the parent's stored contract."""
    try:
        return (within(child['duration_ceiling'], parent['duration_ceiling']) and
                child['policy_version'] == parent['policy_version'] and child['revision'] == parent['revision'] and
                (not child['active'] or parent['active']) and
                (not child['compound_safe'] or parent['compound_safe']) and
                child['reconsiderations'] <= parent['reconsiderations'] and
                all(set(child[field]) <= set(parent[field]) for field in
                    ('duties', 'permitted_alternatives', 'intent_ids')) and
                set(map(digest, child['effective_grants'])) <= set(map(digest, parent['effective_grants'])) and
                all(set(values) <= set(parent['delegable'].get(dimension, ()))
                    for dimension, values in child['delegable'].items()))
    except (KeyError, TypeError, ValueError):
        return False


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def invalid():
    from my_harness.services.domain_operations import DomainRefusal
    raise DomainRefusal('permission_invalid')


class PermissionLifecycle:
    def __init__(self, engine, *, authority=None, clock=now):
        self.engine, self.authority, self.clock = engine, authority, clock

    def records(self, session, project):
        return list(session.scalars(select(Record).where(Record.project_id == project).order_by(Record.sequence)))

    def append(self, session, project, kind, payload, key, *, identity=None):
        rows = self.records(session, project)
        previous = next((r for r in rows if r.record_key == key), None)
        sha = digest({'kind': kind, 'payload': payload})
        if previous:
            if previous.sha256 != sha:
                invalid()
            return previous
        row = Record(id=identity or str(uuid4()), project_id=project, sequence=len(rows)+1, record_key=key, kind=kind,
                     payload=payload, sha256=sha, created_at=self.clock())
        session.add(row)
        session.flush()
        record_event(session, kind='permission.'+kind, dedupe_key='permission:'+row.id,
                     payload={'record_id': row.id, 'sha256': sha}, root=session.get(Project, project).root)
        return row

    def get(self, session, project, identity, kind=None):
        if not isinstance(identity, str) or not identity:
            invalid()
        row = session.get(Record, identity)
        if row is None or row.project_id != project or kind and row.kind != kind or row.sha256 != digest({'kind': row.kind, 'payload': row.payload}):
            invalid()
        return row

    def active(self, session, row, seen=None):
        seen = set() if seen is None else seen
        if row.id in seen:
            return False
        seen.add(row.id)
        p = row.payload
        if p.get('expires_at') and self.clock() >= p['expires_at']:
            return False
        if any(r.kind == 'end' and r.payload['record_id'] == row.id for r in self.records(session, row.project_id)):
            return False
        parent = p.get('parent')
        if row.kind == 'authorization' and p.get('delegation'):
            if any(targets.owner_only(t) for t in p['targets']):
                return False
            if parent:
                ancestor = self.get(session, row.project_id, parent, 'authorization')
                if not ancestor.payload.get('delegation') or not delegation_within(p['delegation'], ancestor.payload['delegation']):
                    return False
        return not parent or self.active(session, self.get(session, row.project_id, parent, 'authorization'), seen)

    def inspect(self, session, project):
        if project is None or session.get(Project, project) is None:
            invalid()
        rows = self.records(session, project)
        current = self.authority(session, project) if self.authority else None
        items = []
        for row in rows:
            active = self.active(session, row)
            effective = None
            if row.kind == 'grant' and current is not None:
                effective = active and all(not targets.owner_only(t) and all(targets.token(t) in current.get(layer, {}).get(t['dimension'], ()) for layer in ('global', 'project', 'contract', 'provider')) for t in row.payload['targets'])
            items.append({'id': row.id, 'kind': row.kind, 'sha256': row.sha256, 'payload': row.payload,
                          'active': active, 'effective': effective, 'created_at': row.created_at})
        return {'revision': len(rows), 'items': items}

    def handler(self, call):
        try:
            return self._handler(call)
        except (ValueError, KeyError, TypeError, OSError):
            invalid()

    def _handler(self, call):
        call.authorize()
        a = call.arguments
        if call.entry.id == 'permissions.inspect':
            return self.inspect(call.session, call.project_id)
        if call.entry.id == 'permissions.request':
            return self.request(call.session, call.project_id, a['request'], call.caller)
        if a['expected_revision'] != len(self.records(call.session, call.project_id)):
            from my_harness.services.domain_operations import DomainRefusal
            raise DomainRefusal('stale_revision')
        if call.entry.id == 'permissions.preview':
            return self.preview(call.session, call.project_id, a['action'], a['response'])
        preview = self.preview(call.session, call.project_id, a['action'], a['response'])
        if preview['preview_sha256'] != a['preview_sha256'] or not a['confirmed']:
            invalid()
        return self.respond(call.session, call.project_id, a['action'], a['response'],
            {**call.caller.actor(), 'confirmation': {'preview_sha256': a['preview_sha256'], 'revision': a['expected_revision']}})

    def request(self, session, project, data, caller):
        required = {'grantee', 'dimension', 'targets', 'purpose', 'snapshot_id', 'duration', 'operation_key', 'parent', 'replaces'}
        if set(data) != required or data['grantee'] not in ('reviewer', 'executor', 'judge') or caller.principal == 'agent' and data['grantee'] != caller.role:
            invalid()
        if not isinstance(data['purpose'], str) or not data['purpose'].strip() or len(data['purpose']) > 100 or not isinstance(data['operation_key'], str) or not 1 <= len(data['operation_key']) <= 100:
            invalid()
        duration_check(data['duration'])
        from my_harness.storage.frozen_context import load
        snapshot, _ = load(session, data['snapshot_id'], project)
        if caller.principal == 'agent':
            boundary = session.get(Boundary, caller.invocation_id)
            bound = self.get(session, project, boundary.snapshot_id, 'snapshot') if boundary else None
            if bound is None or data['purpose'] != bound.payload['purpose'] or data['operation_key'] != bound.payload['operation_key'] or snapshot.revision_id != caller.frozen_revision_id:
                invalid()
        root = session.get(Project, project).root
        if not isinstance(data['targets'], list) or not 1 <= len(data['targets']) <= 100:
            invalid()
        canonical = sorted({digest(t): t for t in [targets.normalize(data['dimension'], t, root) for t in data['targets']]}.values(), key=digest)
        self.validate_targets(session, project, canonical)
        parent = self.get(session, project, data['parent'], 'authorization') if data['parent'] else None
        if parent and not self.active(session, parent):
            invalid()
        if caller.principal != 'owner' and parent is None:
            invalid()
        if parent and (parent.payload['grantee'] != data['grantee'] or parent.payload['purpose'] != data['purpose'] or not set(map(digest, canonical)) <= set(map(digest, parent.payload['targets']))):
            invalid()
        if data['replaces']:
            old = self.get(session, project, data['replaces'])
            if caller.principal != 'owner' or old.kind not in ('request', 'grant', 'deny', 'escalate'):
                invalid()
        subject = digest({'project': project, 'role': data['grantee'], 'dimension': data['dimension'],
                          'purpose': data['purpose'], 'operation': data['operation_key']})
        prior = [r for r in self.records(session, project) if r.kind == 'request' and r.payload['subject'] == subject]
        same = next((r for r in prior if r.payload['evidence'] == snapshot.sha256 and (caller.principal != 'owner' or r.payload['replaces'] == data['replaces'])), None)
        if same:
            return {'request_id': same.id, 'replayed': True, 'state': self.request_state(session, same)}
        p = {**data, 'targets': canonical, 'subject': subject, 'evidence': snapshot.sha256,
             'origin': 'owner_confirmed' if caller.principal == 'owner' else 'harness_deterministic',
             'policy_version': domain_policy.POLICY_VERSION, 'source_attempt_id': caller.attempt_id, 'submitted_targets': data['targets']}
        row = self.append(session, project, 'request', p, 'request:'+subject+':'+snapshot.sha256+':'+str(data['replaces']))
        return {'request_id': row.id, 'replayed': False, 'state': self.request_state(session, row)}

    def request_state(self, session, row):
        response = next((r for r in reversed(self.records(session, row.project_id)) if r.kind in ('grant', 'deny', 'escalate') and r.payload.get('request_id') == row.id), None)
        return response.kind if response else 'awaiting_owner'  # manual default; a trusted consumer can ask T009

    def preview(self, session, project, action, data):
        if action not in ('grant', 'deny', 'escalate', 'revoke', 'end') or not isinstance(data, dict):
            invalid()
        expected = {'record_id', 'reason'} if action in ('revoke', 'end') else {'request_id', 'reason', 'duration'}
        if set(data) != expected or not isinstance(data['reason'], str) or not data['reason'].strip() or len(data['reason']) > 2000:
            invalid()
        row = self.get(session, project, data['record_id'] if 'record_id' in data else data['request_id'])
        if action in ('revoke', 'end'):
            if row.kind not in ('grant', 'authorization'):
                invalid()
        else:
            if row.kind != 'request' or self.request_state(session, row) not in ('awaiting_owner', 'escalate') or not self.active(session, row):
                invalid()
            from my_harness.storage.models import ManagedAttemptRow
            source = session.get(ManagedAttemptRow, row.payload.get('source_attempt_id')) if row.payload.get('source_attempt_id') else None
            if source is not None and source.result_json is None:
                invalid()
            duration_check(data['duration'])
            if not within(data['duration'], row.payload['duration']):
                invalid()
            # Recheck canonical identity and filesystem/executable drift at owner confirmation.
            self.validate_targets(session, project, row.payload['targets'])
        revision = len(self.records(session, project))
        return {'revision': revision, 'preview_sha256': digest({'project': project, 'revision': revision,
            'action': action, 'response': data, 'record_sha256': row.sha256,
            'current_authority': self.authority(session, project) if self.authority else None}), 'action': action, 'response': data}

    def validate_targets(self, session, project, values):
        root = session.get(Project, project).root
        for target in values:
            d, value = target['dimension'], target['target']
            if d == 'network':
                host = '['+value['host']+']' if ':' in value['host'] else value['host']
                value = {'destination': f"{value['scheme']}://{host}:{value['port']}"}
            if targets.normalize(d, value, root) != target:
                invalid()
            if d in ('product', 'acceptance'):
                from my_harness.storage.models import KnowledgeRevisionRow, KnowledgeRevisionMemberRow
                revision = session.get(KnowledgeRevisionRow, value['revision'])
                if revision is None or revision.project_id != project or revision.status != 'ACCEPTED':
                    invalid()
                if value['entity'] != project and session.scalar(select(KnowledgeRevisionMemberRow.item_id).where(KnowledgeRevisionMemberRow.revision_id == revision.id, KnowledgeRevisionMemberRow.item_id == value['entity'])) is None:
                    invalid()

    def respond(self, session, project, action, data, actor, *, ruling=None):
        if action in ('end', 'revoke'):
            row = self.get(session, project, data['record_id'])
            result = self.append(session, project, 'end', {**data, 'cause': action, 'origin': 'owner_confirmed', 'actor': actor}, 'end:'+row.id)
            return {'record_id': result.id, 'state': 'ended'}
        req = self.get(session, project, data['request_id'], 'request')
        p = req.payload
        parent = p['parent']
        if parent:
            ancestor = self.get(session, project, parent, 'authorization')
            if not self.active(session, ancestor) or ancestor.payload['grantee'] != p['grantee'] or not set(map(digest, p['targets'])) <= set(map(digest, ancestor.payload['targets'])):
                invalid()
        origin = 'owner_delegated' if ruling else 'owner_confirmed'
        if action == 'grant' and not parent:
            parent = self.append(session, project, 'authorization', {'parent': None, 'origin': 'owner_confirmed',
                'grantee': p['grantee'], 'targets': p['targets'], 'purpose': p['purpose'],
                'policy_version': domain_policy.POLICY_VERSION, 'expires_at': None, 'actor': actor}, 'authorization:'+req.id).id
        expires = None
        if data['duration']['kind'] == 'time_limited':
            expires = (datetime.fromisoformat(self.clock()) + timedelta(seconds=data['duration']['seconds'])).isoformat(timespec='microseconds')
        result = self.append(session, project, action, {'request_id': req.id, 'parent': parent, 'origin': origin,
            'ruling_id': ruling, 'actor': actor, 'targets': p['targets'], 'grantee': p['grantee'], 'purpose': p['purpose'],
            'operation_key': p['operation_key'], 'duration': data['duration'], 'expires_at': expires,
            'policy_version': domain_policy.POLICY_VERSION, 'reason': data['reason'],
            'alternative': session.get(JudgeRulingRow, ruling).payload.get('candidate', {}).get('alternative') if ruling else None}, 'response:'+req.id+':'+action)
        if action == 'grant' and p['replaces']:
            self.append(session, project, 'end', {'record_id': p['replaces'], 'cause': 'superseded',
                'replacement': result.id, 'origin': origin}, 'end:'+p['replaces'])
        return {'record_id': result.id, 'state': action}

    def consume_ruling(self, project, request_id, ruling_id):
        """Explicit trusted consumer. A T009 VALIDATED proposal still requires current ancestry/ceilings."""
        with Session(self.engine) as session, session.begin():
            session.execute(text('DELETE FROM permission_records WHERE 0'))
            req = self.get(session, project, request_id, 'request')
            consumed = next((r for r in self.records(session, project) if r.payload.get('ruling_id') == ruling_id), None)
            if consumed and consumed.payload.get('request_id') != request_id:
                invalid()
            if consumed:
                # Recovery observes the same application even if authority has since ended; it never reapplies it.
                return {'record_id': consumed.id, 'state': consumed.kind}
            ruling = session.get(JudgeRulingRow, ruling_id)
            judge = session.get(JudgeRequestRow, ruling.request_id) if ruling else None
            if not judge or judge.project_id != project or judge.duty != 'permission' or ruling.status not in ('VALIDATED', 'ESCALATED'):
                invalid()
            p = req.payload
            from my_harness.storage.models import ManagedAttemptRow
            source = session.get(ManagedAttemptRow, p['source_attempt_id']) if p.get('source_attempt_id') else None
            if source is not None and source.result_json is None:
                invalid()
            parent = self.get(session, project, p['parent'], 'authorization')
            policy = parent.payload.get('delegation')
            candidate = ruling.payload.get('candidate', {})
            inp = judge.payload['inputs']
            if (not self.active(session, parent) or not policy or judge.subject != p['subject'] or
                judge.payload['policy'] != policy or judge.snapshot_id != p['snapshot_id'] or
                inp['dimension'] != p['dimension'] or inp['targets'] != [targets.token(t) for t in p['targets']] or
                any(targets.owner_only(t) for t in p['targets']) or self.request_state(session, req) != 'awaiting_owner'):
                invalid()
            if ruling.status == 'ESCALATED':
                return self.respond(session, project, 'escalate', {'request_id': req.id, 'reason': ruling.payload.get('reason', 'Judge escalation'), 'duration': p['duration']}, {'principal': 'judge'}, ruling=ruling_id)
            from my_harness.core.engine import judge as judge_core
            from my_harness.core.engine.contracts import freeze
            judge_core.candidate('permission', inp, judge.payload['evidence'], policy, freeze(candidate))
            outcome = candidate.get('outcome')
            if outcome not in ('grant', 'deny', 'escalate'):
                invalid()
            duration = candidate.get('duration', p['duration'])
            if outcome == 'grant' and (not within(duration, p['duration']) or not within(duration, policy['duration_ceiling'])):
                invalid()
            self.validate_targets(session, project, p['targets'])
            current = self.authority(session, project) if self.authority else None
            if outcome == 'grant' and any(not all(targets.token(t) in (current or {}).get(layer, {}).get(t['dimension'], ()) for layer in ('global', 'project', 'contract', 'provider')) for t in p['targets']):
                invalid()
            return self.respond(session, project, outcome, {'request_id': req.id, 'reason': candidate['rationale'],
                'duration': duration}, {'principal': 'judge'}, ruling=ruling_id)

    def prepare(self, project, *, role, purpose, operation_key, authority, policy_version=domain_policy.POLICY_VERSION):
        """Trusted new-boundary preparation. Does not mutate a live invocation or reserve consumption."""
        with Session(self.engine) as session, session.begin():
            session.execute(text('DELETE FROM permission_records WHERE 0'))
            if role not in ('reviewer', 'executor', 'judge') or policy_version != domain_policy.POLICY_VERSION:
                invalid()
            grants = [r for r in self.records(session, project) if r.kind == 'grant' and r.payload['grantee'] == role
                      and r.payload['purpose'] == purpose and self.active(session, r)
                      and (r.payload['duration']['kind'] != 'operation' or r.payload['operation_key'] == operation_key)]
            current = self.authority(session, project) if self.authority else None
            grants = [g for g in grants if all(not targets.owner_only(t) and all(
                targets.token(t) in (authority or {}).get(layer, {}).get(t['dimension'], ()) and
                targets.token(t) in (current or {}).get(layer, {}).get(t['dimension'], ())
                for layer in ('global', 'project', 'contract', 'provider')) for t in g.payload['targets'])]
            row = self.append(session, project, 'snapshot', {'role': role, 'purpose': purpose, 'operation_key': operation_key,
                'grants': [r.id for r in grants], 'authority': authority, 'policy_version': policy_version}, 'snapshot:'+str(uuid4()))
            return {'id': row.id, 'sha256': row.sha256}

    def state(self, session, caller):
        if not caller.invocation_id or not caller.attempt_id:
            return None
        boundary = session.get(Boundary, caller.invocation_id)
        if boundary is None or boundary.attempt_id != caller.attempt_id:
            return None
        snap = self.get(session, caller.knowledge_project_id, boundary.snapshot_id, 'snapshot')
        p = snap.payload
        if p['role'] != caller.role or not self.authority:
            return None
        current = self.authority(session, caller.knowledge_project_id)
        if current is None:
            return None
        entries, unavailable, role_ceiling = [], set(), {}
        if p['policy_version'] != domain_policy.POLICY_VERSION:
            return None
        for identity in p['grants']:
            grant = self.get(session, snap.project_id, identity, 'grant')
            live = self.active(session, grant) and grant.payload['policy_version'] == domain_policy.POLICY_VERSION
            try:
                self.validate_targets(session, snap.project_id, grant.payload['targets'])
            except (ValueError, OSError):
                live = False
            for target in grant.payload['targets']:
                d, t = target['dimension'], targets.token(target)
                if targets.owner_only(target):
                    live = False
                if d == 'product' and (target['target']['entity'] != snap.project_id or target['target']['revision'] != caller.frozen_revision_id):
                    live = False
                entries.append((identity, d, t))
                role_ceiling.setdefault(d, set()).add(t)
            if not live:
                unavailable.add(identity)
        return domain_policy.PermissionState(snap.sha256, tuple(entries), frozenset(unavailable), p['authority'], current,
            {k: frozenset(v) for k, v in role_ceiling.items()})

    def authorize(self, project, *, grantee, targets_list, purpose, parent=None, expires_at=None, delegation=None):
        """Trusted later-consumer interface, never a model/API action. No autonomy limits are invented."""
        with Session(self.engine) as session, session.begin():
            session.execute(text('DELETE FROM permission_records WHERE 0'))
            self.validate_targets(session, project, targets_list)
            if grantee not in ('reviewer', 'executor', 'judge') or not purpose:
                invalid()
            if expires_at is not None:
                expires = datetime.fromisoformat(expires_at)
                if expires.tzinfo is None:
                    invalid()
                expires_at = expires.astimezone(timezone.utc).isoformat(timespec='microseconds')
            if parent:
                ancestor = self.get(session, project, parent, 'authorization')
                if not self.active(session, ancestor) or ancestor.payload['grantee'] != grantee or ancestor.payload['purpose'] != purpose or not set(map(digest, targets_list)) <= set(map(digest, ancestor.payload['targets'])):
                    invalid()
            identity = str(uuid4())
            if delegation is not None:
                required = {'revision', 'policy_version', 'reconsiderations', 'active', 'duties', 'effective_grants',
                            'compound_safe', 'delegable', 'duration_ceiling', 'permitted_alternatives', 'intent_ids'}
                if set(delegation) != required or type(delegation['reconsiderations']) is not int or delegation['reconsiderations'] < 0 or any(targets.owner_only(t) for t in targets_list):
                    invalid()
                duration_check(delegation['duration_ceiling'])
                if not all(set(v) <= {targets.token(t) for t in targets_list if t['dimension'] == d} for d, v in delegation['delegable'].items()):
                    invalid()
                if parent:
                    ceiling = ancestor.payload.get('delegation')
                    if not ceiling or not delegation_within(delegation, ceiling):
                        invalid()
                delegation = {**delegation, 'id': identity}
            row = self.append(session, project, 'authorization', {'parent': parent,
                'origin': 'owner_delegated' if parent else 'owner_confirmed', 'grantee': grantee,
                'targets': targets_list, 'purpose': purpose, 'expires_at': expires_at,
                'policy_version': domain_policy.POLICY_VERSION, 'delegation': delegation}, 'authorization:'+identity, identity=identity)
            return row.id

    def judge_policy(self, session, project, duty, subject):
        request = next((r for r in reversed(self.records(session, project)) if r.kind == 'request' and r.payload['subject'] == subject), None)
        if request is None or not request.payload['parent']:
            return None
        parent = self.get(session, project, request.payload['parent'], 'authorization')
        return parent.payload.get('delegation') if self.active(session, parent) else None

    def seal(self, session, project, marker, operation, request, frozen_authority):
        snapshot = self.get(session, project, marker['id'], 'snapshot')
        p = snapshot.payload
        if (p['policy_version'] != domain_policy.POLICY_VERSION or marker != {'id': snapshot.id, 'sha256': snapshot.sha256} or p['role'] != request.role or
                p['operation_key'] != operation.key or p['authority'] != frozen_authority or
                session.scalar(select(Boundary.invocation_id).where(Boundary.snapshot_id == snapshot.id))):
            invalid()
        current = self.authority(session, project) if self.authority else None
        for identity in p['grants']:
            grant = self.get(session, project, identity, 'grant')
            if (not self.active(session, grant) or any(targets.owner_only(t) or not all(targets.token(t) in (current or {}).get(layer, {}).get(t['dimension'], ()) and targets.token(t) in (frozen_authority or {}).get(layer, {}).get(t['dimension'], ()) for layer in ('global', 'project', 'contract', 'provider')) for t in grant.payload['targets'])):
                invalid()
            self.validate_targets(session, project, grant.payload['targets'])
            if grant.payload['duration']['kind'] == 'operation':
                consumed = next((r for r in self.records(session, project) if r.kind == 'consumed' and r.payload['grant_id'] == grant.id), None)
                if consumed and consumed.payload['operation_id'] != operation.id:
                    invalid()
                self.append(session, project, 'consumed', {'grant_id': grant.id, 'operation_id': operation.id,
                    'origin': 'harness_deterministic'}, 'consumed:'+grant.id)
        session.add(Boundary(invocation_id=operation.invocation_id, snapshot_id=snapshot.id,
            attempt_id=request.id, operation_id=operation.id, created_at=self.clock()))
        session.flush()

    def stage_attempt(self, session, run_id, *, command=False):
        """Current native stage, never a union of old snapshots. Settled executor owns postprocessing."""
        from my_harness.storage.models import ManagedAttemptRow
        attempts = session.scalars(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id == run_id)
                                  .order_by(ManagedAttemptRow.number.desc()))
        for attempt in attempts:
            if not command and attempt.result_json is None:
                return attempt.id
            if json.loads(attempt.request_json)['role'] == 'executor':
                return attempt.id
        return None

    def cancelled(self, session, run_id, *, command_id=None, job_id=None):
        from my_harness.storage.models import ManagedAttemptRow, ManagedEventRow
        if command_id is not None:
            started = next((e for e in session.scalars(select(ManagedEventRow).where(
                ManagedEventRow.run_id == run_id, ManagedEventRow.kind == 'command_started'))
                if e.payload.get('command_id') == command_id and e.payload.get('job_id') == job_id), None)
            if started is None:
                invalid()
            # New command intents pin their source stage. Historical unmarked events keep their old path.
            attempt_id = started.payload.get('permission_attempt_id')
        else:
            attempt_id = self.stage_attempt(session, run_id)
        if attempt_id is None:
            return False
        attempt = session.get(ManagedAttemptRow, attempt_id)
        if attempt is None or attempt.run_id != run_id:
            invalid()
        b = session.scalar(select(Boundary).where(Boundary.attempt_id == attempt_id))
        if b is None:
            return False  # an unmarked current legacy attempt never inherits an older boundary
        snap = session.get(Record, b.snapshot_id)
        for identity in snap.payload['grants']:
            grant = self.get(session, snap.project_id, identity, 'grant')
            if not self.active(session, grant):
                return True
            if self.authority:
                authority = self.authority(session, snap.project_id)
                for target in grant.payload['targets']:
                    if not all(targets.token(target) in (authority or {}).get(layer, {}).get(target['dimension'], ())
                               for layer in ('global', 'project', 'contract', 'provider')):
                        return True
        return False
