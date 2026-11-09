"""T024 admission and frozen element evidence, sharing the managed enqueue transaction."""
import json

from sqlalchemy import select

from my_harness.core.engine import chat_context as core, frozen_context
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.knowledge_documents import render_entity
from my_harness.i18n import tr
from my_harness.storage.frozen_context import accepted_revision, prepare_snapshot
from my_harness.storage.managed import Conflict
from my_harness.storage.models import ContextSnapshotRow, ChatTurnRow
from my_harness.storage.work_map import WorkMap, MapNotFound


class StaleElement(Conflict):
    pass


def selected(session, root, kind, target, step_key=None):
    """Read the current server-owned reference. `project` is the persisted knowledge identity."""
    revision = accepted_revision(session, root=root)
    if revision is None:
        return None
    project = revision.project_id
    ref = {'kind': kind, 'project': project}
    if kind in ('phase', 'task'):
        if step_key is not None:
            raise ValueError(tr('chat.element_invalid'))
        member = revision.members.get(target) or revision.item(kind, target)
        if member is None or member.kind != kind:
            raise LookupError(tr('chat.element_invalid'))
        ref.update(stable_id=member.item_id, revision_id=revision.id)
        raw = render_entity(member)
        identity = frozen_context.metadata(member)
        label = member.code + ' — ' + member.content['title'][:200]
    elif kind in ('run', 'step') and (kind == 'step') == (step_key is not None):
        if step_key is not None:
            # Validate before splitting or using the key for projection selection.
            core.reference({**ref, 'run_id': target, 'step_key': step_key, 'evidence_digest': '0' * 64})
        try:
            data = WorkMap(session.bind).contextual_evidence(session.connection(), root, target, step_key)
        except MapNotFound:
            raise LookupError(tr('chat.element_invalid')) from None
        raw = freeze(data)
        sha = frozen_context.digest(raw)
        ref.update(run_id=target, evidence_digest=sha)
        if step_key is not None:
            ref['step_key'] = step_key
        identity = {'kind': 'run_evidence', 'item_id': target + (':' + step_key if step_key else ''),
                    'version': sha, 'content_sha256': sha}
        label = target[:12] + (' / ' + step_key if step_key else '')
    else:
        raise ValueError(tr('chat.element_invalid'))
    return {'reference': ref, 'label': label, 'exposure': core.exposure(raw, identity, reference=ref, label=label)}


def admit(session, context, reference, versions):
    core.reference(reference)
    revision = accepted_revision(session, root=str(context.root))
    if revision is None or revision.project_id != reference['project']:
        raise LookupError(tr('chat.element_invalid'))
    if reference['kind'] in ('phase', 'task') and revision.id != reference['revision_id']:
        raise StaleElement(tr('chat.element_stale'))
    value = selected(session, str(context.root), reference['kind'],
                     reference.get('stable_id', reference.get('run_id')), reference.get('step_key'))
    if value is None or value['reference'] != reference:
        raise StaleElement(tr('chat.element_stale'))
    client = versions.get('reviewer_provider', 'codex')
    row = prepare_snapshot(session, revision, [], client=client, profile=frozen_context.profile_capture(context))
    return value, {'id': row.id, 'sha256': row.sha256, 'revision_id': revision.id, 'client': client}


def verify_element(element, revision):
    """Rebuild canonical bytes; captured run evidence remains historical, never replaced by a live read."""
    ref, e = element['reference'], element['exposure']
    core.reference(ref)
    if ref['project'] != revision.project_id:
        frozen_context.fail()
    if ref['kind'] in ('phase', 'task'):
        member = revision.members.get(ref['stable_id'])
        if member is None or member.kind != ref['kind'] or ref['revision_id'] != revision.id:
            frozen_context.fail()
        label = member.code + ' — ' + member.content['title'][:200]
        expected = core.exposure(render_entity(member), frozen_context.metadata(member), reference=ref, label=label)
        if e != expected or element['label'] != label:
            frozen_context.fail()
    else:
        identity = {'kind': 'run_evidence', 'item_id': ref['run_id'] + (':' + ref['step_key'] if ref['kind'] == 'step' else ''),
                    'version': ref['evidence_digest'], 'content_sha256': ref['evidence_digest']}
        r = e['range']
        prefix = core.evidence_prefix(ref, element['label'])
        truncated = r['total'] > len(e['data'])
        if (e['identity'] != identity or e['authority'] != 'capture' or e['purpose'] != 'element'
                or not e['data'].startswith(prefix) or e['truncated'] != truncated
                or e['page'] != {'max_bytes': core.MAX_ELEMENT, 'truncated': truncated}
                or e['exposure'] != ('excerpt' if truncated else 'full')
                or r != {'unit': 'unicode_codepoint', 'start': 0, 'end': len(e['data']), 'total': r['total']}
                or r['total'] < len(e['data'])):
            frozen_context.fail()
        if not truncated and frozen_context.digest(e['data'][len(prefix):]) != ref['evidence_digest']:
            frozen_context.fail()


def turn_element(request, frozen_request, revision=None):
    """Verify the prompt's exact selection against the admitted turn, never a live revision/run."""
    marker = json.loads(request.prompt_snapshot_json or '{}')
    element = frozen_request['context'].get('element')
    if not element:
        if 'chat_element' in marker:
            frozen_context.fail()
        return None
    if (frozen_context.digest(freeze(frozen_request['context'])) != frozen_request['context_sha256']
            or marker.get('chat_element') != element or marker.get('canonical_context') != frozen_request.get('canonical')
            or frozen_context.digest(element['exposure']['data']) != element['exposure']['digest']
            or len(element['exposure']['data'].encode('utf-8')) > core.MAX_ELEMENT
            or core.EVIDENCE_NOTICE not in request.prompt
            or element['exposure']['data'] not in request.prompt
            or freeze(core.prompt_context(frozen_request['context'])) not in request.prompt):
        frozen_context.fail()
    if revision is not None:
        verify_element(element, revision)
    return element['exposure']


def invocation_element(session, attempt_id, snapshot=None):
    from my_harness.storage.models import ManagedAttemptRow
    attempt = session.get(ManagedAttemptRow, attempt_id)
    turn = session.scalar(select(ChatTurnRow).where(ChatTurnRow.run_id == attempt.run_id))
    if turn is None:
        return None
    from types import SimpleNamespace
    revision = None
    if turn.request['context'].get('element'):
        snapshot = snapshot or session.get(ContextSnapshotRow, turn.request['canonical']['id'])
        if snapshot is None:
            frozen_context.fail()
        revision = accepted_revision(session, project=snapshot.project_id, revision_id=snapshot.revision_id)
        if revision is None:
            frozen_context.fail()
    return turn_element(SimpleNamespace(**json.loads(attempt.request_json)), turn.request, revision)
