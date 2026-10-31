"""D294 insert-only, project-bound exchange records. Transactions belong to the domain/effect service."""
from uuid import uuid4
from sqlalchemy import select, text
from my_harness.storage.models import KnowledgeExchangeRow as Row
from my_harness.storage.knowledge import now, KnowledgeIntegrityError
from my_harness.core.engine.knowledge import digest


def records(session, project, kind=None):
    query = select(Row).where(Row.project_id == project)
    if kind:
        query = query.where(Row.kind == kind)
    rows = list(session.scalars(query.order_by(text('knowledge_exchange_records.rowid'))))
    for row in rows:
        if digest(row.payload) != row.sha256:
            raise KnowledgeIntegrityError('exchange_integrity')
    return rows


def get(session, project, ident):
    row = session.get(Row, ident)
    if row is None or row.project_id != project:
        raise ValueError('exchange_not_found')
    if digest(row.payload) != row.sha256:
        raise KnowledgeIntegrityError('exchange_integrity')
    return row


def add(session, project, kind, payload, key=None):
    ident = str(uuid4())
    row = Row(id=ident, project_id=project, kind=kind, payload=payload, sha256=digest(payload),
              record_key=key or ident, created_at=now())
    session.add(row)
    session.flush()
    return row


def latest(session, project, kind):
    rows = records(session, project, kind)
    return rows[-1] if rows else None


def owned_at_root(session, root):
    from my_harness.storage.models import KnowledgeProjectRow
    project = session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == str(root)))
    return latest(session, project, 'ownership') if project else None


def completed_for_project(session, project):
    """Current delivery requires the exact adopted ownership and its renderer, not just knowledge."""
    from my_harness.storage.models import KnowledgeRevisionRow
    current = session.scalar(select(KnowledgeRevisionRow).where(KnowledgeRevisionRow.project_id == project,
        KnowledgeRevisionRow.status == 'ACCEPTED').order_by(KnowledgeRevisionRow.number.desc()).limit(1))
    ownership = latest(session, project, 'ownership')
    complete = latest(session, project, 'export_completed')
    if not current or not ownership or not complete:
        return None
    intent = get(session, project, complete.payload['intent_id'])
    manifest = ownership.payload['manifest']
    if (intent.kind != 'export_intent' or complete.payload.get('status') != 'COMPLETED'
            or complete.payload.get('revision_id') != current.id
            or complete.payload.get('revision_sha256') != current.revision_sha256
            or intent.payload.get('revision_id') != current.id
            or intent.payload.get('revision_sha256') != current.revision_sha256
            or intent.payload.get('ownership_id') != ownership.id
            or intent.payload.get('manifest') != manifest
            or set(intent.payload.get('files', {})) != {t['path'] for t in manifest['targets']}):
        return None
    return {'result': complete.payload, 'intent': intent.payload, 'knowledge_sha256': current.knowledge_sha256}


def completed_at_root(session, root):
    from my_harness.storage.models import KnowledgeProjectRow
    project = session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == str(root)))
    return completed_for_project(session, project) if project else None


def require_documentary_lane(session, root):
    """New ownership never authorizes the retained Markdown-authority workflows (T014/T015)."""
    if owned_at_root(session, str(root)):
        from my_harness.storage.managed import Conflict
        from my_harness.i18n import tr
        raise Conflict(tr('intake.database_owned'))


def verify_archive(db):
    import json
    stored = {}
    for row in db.execute('SELECT * FROM knowledge_exchange_records'):
        payload = json.loads(row['payload'])
        if digest(payload) != row['sha256']:
            raise ValueError('exchange_integrity')
        stored[row['id']] = (row, payload)
    for row, payload in stored.values():
        if payload.get('intent_id'):
            target = stored.get(payload['intent_id'])
            if target is None or target[0]['project_id'] != row['project_id'] or target[0]['kind'] != 'export_intent':
                raise ValueError('exchange_reference')
            if row['kind'] == 'export_target':
                content = target[1]['files'].get(payload['path'])
                from my_harness.core.engine.knowledge_documents import sha
                if content is None or sha(content) != payload['sha256']:
                    raise ValueError('exchange_target_integrity')
        if row['kind'] == 'identity_map':
            for ident in payload['map'].values():
                found = db.execute('SELECT project_id FROM knowledge_items WHERE id=?', (ident,)).fetchone()
                if not found or found[0] != row['project_id']:
                    raise ValueError('exchange_mapping_integrity')
