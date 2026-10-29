"""P002-T007: immutable invocation boundaries and exact knowledge delivery records.

Content is stored here, never in trace payloads. Public readers scope by persisted knowledge project,
need no checkout and never write. All write helpers share the caller's transaction.
"""
import json
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.core.engine import frozen_context as core
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.trace_envelopes import knowledge_receipt
from my_harness.storage.knowledge import KnowledgeSession, Revision
from my_harness.storage.models import (ContextSnapshotRow as Snapshot, InvocationContextRow as Boundary,
    KnowledgeDeliveryRow as Delivery, KnowledgeProjectRow, KnowledgeRevisionRow, WorkflowOperationRow as Operation)
from my_harness.storage.operation_journal import now, record_envelope, record_event


def rebuild(revision, data):
    captures = {}
    for purpose in ('profile', 'code'):
        captures[purpose] = [dict(id=e['identity']['item_id'], version=e['identity']['version'], data=e['data'],
                                  sha256=e['digest'], provenance=e['provenance']) for e in data['entries']
                             if e['purpose'] == purpose]
    return core.assemble(revision, [e['identity']['item_id'] for e in data['entries']
                                   if e['purpose'] == 'knowledge'], client=data['client'],
                         profile=captures['profile'][0], code=captures['code'], context_format=data['format'])


def load(session, snapshot_id, project_id=None):
    row = session.get(Snapshot, snapshot_id)
    if row is None or project_id is not None and row.project_id != project_id:
        core.fail()
    data = core.verify(row.payload, row.sha256)
    revision = session.get(KnowledgeRevisionRow, row.revision_id)
    if (data['project_id'] != row.project_id or data['revision_id'] != row.revision_id or revision is None or
            revision.project_id != row.project_id or revision.status != 'ACCEPTED'):
        core.fail()
    verified = KnowledgeSession(session).revision(row.project_id, revision.number)
    if verified.revision_sha256 != data['revision_sha256']:
        core.fail()
    if freeze(rebuild(verified, data)) != row.payload:
        core.fail()
    return row, data


def seal(session, snapshot_id, operation, request):
    """Called only in managed.agent_started's fenced transaction, after the native invocation is sealed."""
    project = KnowledgeSession(session).project_id(operation.root)
    row, data = load(session, snapshot_id, project)
    if data['format'] != core.FORMAT:
        core.fail('legacy_context')  # read historical bytes; new invocations must use corrected instructions
    snap = json.loads(request.prompt_snapshot_json)
    marker = snap.get('canonical_context', {})
    if (project is None or marker != {'id': row.id, 'sha256': row.sha256, 'revision_id': row.revision_id,
                                      'client': data['client']} or
            snap.get('rendered') != request.prompt or snap.get('rendered_sha256') != core.digest(request.prompt)):
        core.fail()
    profile = next(e for e in data['entries'] if e['purpose'] == 'profile')
    if profile['data'] != freeze(json.loads(request.context_json)['profile']):
        core.fail()
    # Every source and mandatory instruction must actually have entered the rendered prompt.
    if data['instructions'] not in request.prompt or core.prompt_tail(data) not in request.prompt:
        core.fail()
    session.add(Boundary(invocation_id=operation.invocation_id, attempt_id=request.id, operation_id=operation.id,
                         snapshot_id=row.id, prompt_sha256=core.digest(request.prompt), created_at=now()))
    session.flush()
    record_event(session, kind='context.intended', dedupe_key=f'context:intent:{operation.invocation_id}',
                 payload={'snapshot_id': row.id, 'sha256': row.sha256, 'revision_id': row.revision_id},
                 root=operation.root, thread_id=operation.thread_id, operation_id=operation.id,
                 invocation_id=operation.invocation_id)


def bound(session, invocation_id, *, caller=None):
    boundary = session.get(Boundary, invocation_id)
    if boundary is None:
        core.fail()
    row, context = load(session, boundary.snapshot_id)
    operation = session.get(Operation, boundary.operation_id)
    if (operation is None or operation.invocation_id != invocation_id or
            operation.attempt_id != boundary.attempt_id):
        core.fail()
    project = session.get(KnowledgeProjectRow, row.project_id)
    if project is None or operation.root != project.root:
        core.fail()
    if caller is not None and (caller.attempt_id != boundary.attempt_id or
            caller.knowledge_project_id != row.project_id or caller.frozen_revision_id != row.revision_id or
            caller.thread_id != operation.thread_id or caller.role != operation.refs.get('role')):
        core.fail()
    return boundary, row, context, operation


def persist(session, invocation_id, key, request_sha256, channel, result, exposures, *, failure=None):
    boundary, snapshot, context, operation = bound(session, invocation_id)
    payload = freeze({'result': result, 'exposures': exposures, 'failure': failure})
    previous = session.scalar(select(Delivery).where(Delivery.invocation_id == invocation_id, Delivery.key == key))
    if previous is not None:
        delivery_data(previous)
        if previous.request_sha256 != request_sha256 or previous.payload != payload:
            core.fail()
        return previous
    delivery_id = str(uuid4())
    receipts = []
    for index, e in enumerate(exposures):
        identity = e['identity']
        receipt = {'format': 'knowledge-delivery-2', 'invocation_id': invocation_id, 'channel': channel,
                   'entity_type': identity['kind'], 'stable_id': identity['item_id'],
                   'revision_id': snapshot.revision_id, 'exposure': e['exposure'],
                   'page': e.get('page', {'truncated': e.get('truncated', False)}), 'failure': failure,
                   'delivery_id': delivery_id, 'index': index, 'authority': e.get('authority', 'canonical')}
        if failure is None:
            receipt['digest'] = core.digest(e['data'])
        for field in ('range',):
            if field in e:
                receipt[field] = e[field]
        if 'version' in identity:
            receipt['version'] = identity['version']
        if identity.get('content_sha256'):
            receipt['source_sha256'] = identity['content_sha256']
        receipts.append(receipt)
    session.add(Delivery(id=delivery_id, invocation_id=invocation_id, key=key, request_sha256=request_sha256,
                         channel=channel, payload=payload, sha256=delivery_digest(payload, receipts), receipts=receipts,
                         created_at=now()))
    session.flush()
    for receipt in receipts:
        record_envelope(session, 'knowledge.receipt', receipt, dedupe_key=f'receipt:{delivery_id}:{receipt["index"]}',
                        invocation_id=invocation_id, root=operation.root, thread_id=operation.thread_id,
                        operation_id=operation.id)
    return session.get(Delivery, delivery_id)


def delivery_digest(payload, receipts):
    return core.digest(freeze({'payload': payload, 'receipts': receipts}))


def delivery_data(row):
    if delivery_digest(row.payload, row.receipts) != row.sha256:
        core.fail()
    data = json.loads(row.payload)
    if len(data['exposures']) != len(row.receipts):
        core.fail()
    for index, (e, r) in enumerate(zip(data['exposures'], row.receipts)):
        knowledge_receipt(r)
        identity = e['identity']
        if (r['index'] != index or r['delivery_id'] != row.id or r['invocation_id'] != row.invocation_id or
                r['channel'] != row.channel or r['stable_id'] != identity['item_id'] or
                r['entity_type'] != identity['kind'] or r['failure'] != data['failure'] or
                r['authority'] != e.get('authority', 'canonical') or
                r['page'] != e.get('page', {'truncated': e.get('truncated', False)}) or
                r.get('source_sha256') != identity.get('content_sha256') or
                r.get('version') != identity.get('version') or r.get('range') != e.get('range')):
            core.fail()
        if r['failure'] is None and core.digest(e['data']) != r['digest']:
            core.fail()
    return data


def observe(session, attempt_id, prompt_sha256):
    boundary = session.scalar(select(Boundary).where(Boundary.attempt_id == attempt_id))
    if boundary is None:  # legacy paths have no canonical context or synthetic receipts
        return
    if boundary.prompt_sha256 != prompt_sha256:
        core.fail()
    _, _, context, _ = bound(session, boundary.invocation_id)
    persist(session, boundary.invocation_id, 'initial', prompt_sha256, 'initial_context',
            {'context_sha256': core.digest(freeze(context))}, context['entries'])


def launch_refused(session, attempt_id):
    """Known refusal before GO; an uncertain/partial write never becomes this absence claim."""
    boundary = session.scalar(select(Boundary).where(Boundary.attempt_id == attempt_id))
    if boundary is None:
        return
    _, _, context, _ = bound(session, boundary.invocation_id)
    persist(session, boundary.invocation_id, 'initial_failure', boundary.prompt_sha256, 'initial_context', None,
            [{'identity': e['identity'], 'authority': e['authority'], 'exposure': e['exposure'], 'data': ''}
             for e in context['entries']], failure='launch_refused')


class ContextRepository:
    def __init__(self, engine):
        self.engine = engine

    def prepare_for(self, context, item_ids, *, client, code=(), revision=None):
        """Consumer entry: capture the actual frozen profile, then select verified accepted knowledge."""
        return self.prepare(str(context.root), item_ids, client=client, profile=core.profile_capture(context),
                            code=code, revision=revision)

    def prepare(self, root, item_ids, *, client, profile, code=(), revision=None):
        try:
            with Session(self.engine) as session, session.begin():
                if session.execute(text('PRAGMA query_only')).scalar():
                    core.fail('query_only')
                session.execute(text('DELETE FROM context_snapshots WHERE 0'))
                knowledge = KnowledgeSession(session)
                project = knowledge.project_id(root)
                try:
                    accepted = knowledge.revision(project, revision)
                except LookupError:
                    core.fail('revision_unavailable')
                data = core.assemble(accepted, item_ids, client=client, profile=profile, code=code)
                payload = freeze(data)
                row = Snapshot(id=str(uuid4()), project_id=project, revision_id=accepted.id,
                               sha256=core.digest(payload), payload=payload, created_at=now())
                session.add(row)
                return row.id
        except core.ContextError as error:
            if error.code != 'query_only':
                with Session(self.engine) as session, session.begin():
                    record_event(session, kind='context.preparation_failed', dedupe_key=f'context:failed:{uuid4()}',
                                 payload={'failure': error.code}, root=root)
            raise

    def snapshot(self, project_id, snapshot_id):
        with Session(self.engine) as session:
            row, data = load(session, snapshot_id, project_id)
            return {'id': row.id, 'sha256': row.sha256, 'data': data}

    def render(self, project_id, snapshot_id, catalog, name, values, context, language=None):
        from my_harness.core.engine.prompts import render_attempt
        selected = self.snapshot(project_id, snapshot_id)
        return render_attempt(catalog, name, values, context, language, canonical=selected)

    def invocation(self, project_id, invocation_id):
        """Exact frozen prompt and boundary, including on an archive; no launch or comprehension inferred."""
        from my_harness.storage.models import ManagedAttemptRow
        with Session(self.engine) as session:
            boundary, row, _, operation = bound(session, invocation_id)
            if row.project_id != project_id:
                core.fail()
            attempt = session.get(ManagedAttemptRow, boundary.attempt_id)
            request = json.loads(attempt.request_json)
            if core.digest(request['prompt']) != boundary.prompt_sha256:
                core.fail()
            return {'invocation_id': invocation_id, 'attempt_id': attempt.id, 'operation_id': operation.id,
                    'snapshot_id': row.id, 'revision_id': row.revision_id, 'context_sha256': row.sha256,
                    'prompt_sha256': boundary.prompt_sha256, 'prompt': request['prompt'],
                    'prompt_snapshot': json.loads(request['prompt_snapshot_json'])}

    def deliveries(self, project_id, invocation_id, *, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            core.fail()
        with Session(self.engine) as session:
            _, row, _, _ = bound(session, invocation_id)
            if row.project_id != project_id:
                core.fail()
            rows = session.scalars(select(Delivery).where(Delivery.invocation_id == invocation_id)
                                   .order_by(Delivery.created_at, Delivery.id).offset(offset).limit(limit)).all()
            result = []
            for delivery in rows:
                data = delivery_data(delivery)
                for receipt in delivery.receipts:
                    if receipt['revision_id'] != row.revision_id:
                        core.fail()
                result.append({'id': delivery.id, 'channel': delivery.channel, 'sha256': delivery.sha256,
                               'payload': data, 'receipts': delivery.receipts})
            return result


class ReceiptSink:
    """T005 DeliverySink. Stable transport request keys replay one response, never another delivery."""
    def __init__(self, channel='query_result'):
        if channel not in ('query_result', 'tool_result'):
            core.fail()
        self.channel = channel

    def replay(self, session, caller, key, request_sha256):
        from my_harness.services.domain_operations import DomainRefusal
        try:
            bound(session, caller.invocation_id, caller=caller)
        except ValueError:
            raise DomainRefusal('caller_unavailable') from None
        if not isinstance(key, str) or not key.strip() or len(key) > 180:
            raise DomainRefusal('delivery_key_required')
        row = session.scalar(select(Delivery).where(Delivery.invocation_id == caller.invocation_id,
                                                    Delivery.key == self.channel + ':' + key))
        if row is None:
            return None
        if row.request_sha256 != request_sha256:
            raise DomainRefusal('idempotency_conflict')
        data = delivery_data(row)
        if data['failure']:
            raise DomainRefusal(data['failure'])
        return data['result']

    def record(self, session, caller, delivery):
        bound(session, caller.invocation_id, caller=caller)
        result = delivery['result']
        if len(freeze(result).encode('utf-8')) > core.MAX_RESULT:
            from my_harness.services.domain_operations import DomainRefusal
            raise DomainRefusal('delivery_over_limit')
        exposures = [dict(e) for e in result.get('exposures', [])]
        if not exposures:
            # Historical handlers: hash the bytes actually exposed, not the full source content hash.
            for item in result.get('items', result.get('members', [])):
                identity = {k: item[k] for k in ('item_id', 'kind', 'version', 'content_sha256') if k in item}
                exposures.append({'identity': identity, 'data': freeze(item),
                                  'exposure': 'full' if 'content' in item else 'metadata'})
            if 'item' in result:
                item = result['item']
                exposures.append({'identity': {k: item[k] for k in ('item_id', 'kind', 'version', 'content_sha256')},
                                  'data': freeze(item), 'exposure': 'full'})
        if 'draft_id' in result:
            for e in exposures:
                e['authority'] = 'capture'  # an invocation's own proposal is never accepted knowledge
        page = result.get('page', {'truncated': bool(result.get('delivery', {}).get('truncated', False))})
        for e in exposures:
            e['page'] = {**page, 'truncated': page['truncated'] or e.get('truncated', False)}
        exposures.append({'identity': {'kind': 'result', 'item_id': caller.frozen_revision_id},
                          'authority': 'response', 'data': freeze(result), 'exposure': 'full', 'page': page})
        persist(session, caller.invocation_id, self.channel + ':' + delivery['key'], delivery['request_sha256'],
                self.channel, result, exposures)

    def failure(self, session, caller, key, request_sha256, code):
        # Only an already-bound invocation can receive a failure receipt; caller forgery stays refused.
        try:
            bound(session, caller.invocation_id, caller=caller)
        except ValueError:
            return
        if not isinstance(key, str) or not key.strip() or len(key) > 180 or code == 'idempotency_conflict':
            return
        if session.scalar(select(Delivery.id).where(Delivery.invocation_id == caller.invocation_id,
                                                   Delivery.key == self.channel + ':' + key)):
            return
        persist(session, caller.invocation_id, self.channel + ':' + key, request_sha256, self.channel, None,
                [{'identity': {'kind': 'result', 'item_id': caller.frozen_revision_id},
                  'authority': 'response', 'data': '', 'exposure': 'metadata'}], failure=code)


def verify_archive(db):
    """Read-only integrity checks used before backup and restore; no checkout or source files."""
    snapshots = {}
    for sid, project, revision, sha, payload in db.execute(
            'SELECT id, project_id, revision_id, sha256, payload FROM context_snapshots'):
        data = core.verify(payload, sha)
        row = db.execute('SELECT project_id, revision_sha256, status FROM knowledge_revisions WHERE id = ?',
                         (revision,)).fetchone()
        if (not row or tuple(row) != (project, data['revision_sha256'], 'ACCEPTED') or
                data['project_id'] != project or data['revision_id'] != revision):
            core.fail()
        from my_harness.core.engine import knowledge
        members = {}
        for item, kind, document, code, version, content_sha, content, provenance, source, position in db.execute(
                'SELECT i.id, i.kind, i.document, i.code, v.number, v.content_sha256, v.content, v.provenance, '
                'v.source, m.root_position FROM knowledge_revision_members m JOIN knowledge_items i ON i.id = m.item_id '
                'JOIN knowledge_item_versions v ON v.id = m.version_id WHERE m.revision_id = ?', (revision,)):
            member = knowledge.Member(item, kind, document, code, version, content_sha, json.loads(content),
                                       provenance, json.loads(source) if source else None, position)
            if knowledge.content_sha256(kind, document, code, member.content, provenance, member.source) != content_sha:
                core.fail()
            members[item] = member
        links = tuple(knowledge.Link(*r) for r in db.execute('SELECT kind, source_item_id, target_item_id, '
                      'position, qualifier FROM knowledge_revision_links WHERE revision_id = ?', (revision,)))
        values = list(db.execute('SELECT id, project_id, number, base_revision_id, knowledge_sha256, revision_sha256, '
            'origin, actor, reason, changes, closed_at FROM knowledge_revisions WHERE id = ?', (revision,)).fetchone())
        values[7], values[9] = json.loads(values[7]), json.loads(values[9])
        accepted = Revision(*values, members, links)
        if (knowledge.knowledge_sha256(project, members.values(), links) != accepted.knowledge_sha256 or
                freeze(rebuild(accepted, data)) != payload):
            core.fail()
        snapshots[sid] = data
    boundaries = {}
    for invocation, attempt, operation, sid, sha in db.execute(
            'SELECT invocation_id, attempt_id, operation_id, snapshot_id, prompt_sha256 FROM invocation_contexts'):
        row = db.execute('SELECT attempt_id, invocation_id, root FROM workflow_operations WHERE id = ?',
                         (operation,)).fetchone()
        request = db.execute('SELECT request_json FROM managed_attempts WHERE id = ?', (attempt,)).fetchone()
        root = db.execute('SELECT root FROM knowledge_projects WHERE id = ?', (snapshots[sid]['project_id'],)).fetchone()
        if not row or tuple(row) != (attempt, invocation, root[0]) or not request:
            core.fail()
        request = json.loads(request[0])
        if core.digest(request['prompt']) != sha:
            core.fail()
        boundaries[invocation] = snapshots[sid]
    for did, invocation, channel, payload, sha, receipts in db.execute(
            'SELECT id, invocation_id, channel, payload, sha256, receipts FROM knowledge_deliveries'):
        if invocation not in boundaries:
            core.fail()
        receipts = json.loads(receipts)
        from types import SimpleNamespace
        delivery_data(SimpleNamespace(id=did, invocation_id=invocation, channel=channel, payload=payload,
                                      sha256=sha, receipts=receipts))
        for index, r in enumerate(receipts):
            if r['revision_id'] != boundaries[invocation]['revision_id']:
                core.fail()
            event = db.execute('SELECT payload FROM trace_events WHERE dedupe_key = ?',
                               (f'receipt:{did}:{index}',)).fetchone()
            if not event or json.loads(event[0]) != r:
                core.fail()
