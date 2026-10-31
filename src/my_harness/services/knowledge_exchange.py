"""D294 owner-only document commands. Canonical changes share the domain transaction and consent."""
from copy import deepcopy
from dataclasses import replace
from sqlalchemy import select
from my_harness.core.engine import knowledge as k, knowledge_documents as d
from my_harness.storage import knowledge_exchange as store
from my_harness.storage.models import KnowledgeProjectRow, KnowledgeItemRow
from my_harness.storage.work_language import get as get_language


def language(call):
    root = call.session.get(KnowledgeProjectRow, call.project_id).root
    value = get_language(call.session, root)
    if not value:
        raise ValueError('work_language_required')
    return value['work_language']


def head(call):
    row = call.knowledge.head(call.project_id)
    if not row:
        raise ValueError('accepted_revision_required')
    return call.knowledge.revision(call.project_id, row.number)


def bundle(call):
    call.authorize()
    revision = head(call)
    ownership = store.latest(call.session, call.project_id, 'ownership')
    manifest = ownership.payload['manifest'] if ownership else d.ownership(call.project_id, language(call))
    data = d.snapshot(revision)
    # Download capabilities are independent: rendering gates never confer or block portability.
    files, portable, render_error, portable_error = None, None, None, None
    try:
        files = d.render(data, manifest)
    except ValueError as exc:
        render_error = str(exc)
    try:
        portable = d.portable(data, language(call))
    except ValueError as exc:
        portable_error = str(exc)
    return {'files': files, 'portable': portable, 'render_error': render_error, 'portable_error': portable_error,
            'ownership_adopted': ownership is not None, 'ownership_id': ownership.id if ownership else None,
            'revision_id': revision.id, 'delivery': delivery_state(call.session, call.project_id)}


def _stage(call):
    call.authorize()
    body = d.loads(call.arguments['payload'])
    body.setdefault('preserve', [])
    d.closed(body, ('files', 'portable', 'mode', 'choices', 'acknowledged', 'expected_revision_id', 'preserve'))
    current = call.knowledge.head(call.project_id)
    expected = current.id if current else None
    if expected != body['expected_revision_id'] or body['mode'] not in ('new', 'update'):
        raise ValueError('stale_revision')
    if body['mode'] == 'new' and current:
        raise ValueError('new_destination_has_knowledge')
    if bool(body['files']) == bool(body['portable']):
        raise ValueError('select_one_input_mode')
    selected_files = dict(body['files'])
    preserved = []
    for resolution in body['preserve']:
        d.closed(resolution, ('path', 'document', 'code'))
        path, document, code = resolution['path'], resolution['document'], resolution['code']
        if path == d.META or path not in selected_files or document not in ('specification', 'architecture', 'data_model', 'flows'):
            raise ValueError('invalid_preservation_choice')
        preserved.append((path, document, code, selected_files.pop(path)))
    data, report, source_language = d.parse_portable(body['portable']) if body['portable'] else d.parse(selected_files)
    if preserved and body['portable']:
        raise ValueError('preservation_requires_documents')
    if source_language is not None and source_language != language(call):
        report.append({'code': 'source_language_differs', 'blocking': False})
    members = call.knowledge.manifest(expected)[0] if expected else {}
    mappings = {}
    for record in store.records(call.session, call.project_id, 'identity_map'):
        if record.payload['source_project'] == data['source_project_id']:
            mappings.update(record.payload['map'])
    explicit_preserved = set()
    for path, document, code, text in preserved:
        source_id = 'preserved-' + d.sha(path)[:32]
        content = {'title': code, 'body': text, 'format': 'markdown', 'target': 'agents', 'status': 'active'}
        source = {'kind': 'legacy_document', 'path': path, 'sha256': d.sha(text)}
        position = max([m.root_position for m in members.values() if m.document == document and m.root_position is not None] +
                       [m['root_position'] for m in data['members'] if m['document'] == document and m['root_position'] is not None] + [-1]) + 1
        data['members'].append({'item_id': source_id, 'kind': 'section', 'document': document, 'code': code,
            'content': content, 'source': source, 'provenance': 'known', 'version': 1, 'root_position': position,
            'content_sha256': k.content_sha256('section', document, code, content, 'known', source)})
        explicit_preserved.add(source_id)
        report.append({'code': 'document_preserved_as_section', 'path': path, 'item': source_id, 'blocking': False})
    resolved, excluded, proposals = {}, set(), []
    for original in data['members']:
        m = deepcopy(original)
        source_id = m['item_id']
        choice = body['choices'].get(source_id)
        if source_id in explicit_preserved:
            choice = {'action': 'create', 'code': m['code'], 'target': ''}
        destination = source_id if data['source_project_id'] == call.project_id and source_id in members else mappings.get(source_id)
        if body['mode'] == 'new':
            destination = None
        if choice:
            d.closed(choice, ('action', 'target', 'code'))
            if choice['action'] == 'exclude':
                excluded.add(source_id)
                report.append({'code': 'explicit_exclusion', 'item': source_id, 'blocking': False})
                continue
            if choice['action'] == 'map':
                destination = choice['target']
            elif choice['action'] == 'create':
                destination = None
                m['code'] = choice['code']
            else:
                raise ValueError('invalid_identity_choice')
        if destination:
            old = members.get(destination)
            if old and choice and choice['action'] == 'map' and (old.kind, old.document) == (m['kind'], m['document']):
                m['code'] = old.code
            if old is None or (old.kind, old.document, old.code) != (m['kind'], m['document'], m['code']):
                raise ValueError('identity_mismatch')
            if original['version'] != old.version or original['content_sha256'] != old.content_sha256:
                report.append({'code': 'source_version_differs', 'item': source_id, 'blocking': False})
        elif body['mode'] != 'new' and not choice:
            report.append({'code': 'identity_choice_required', 'item': source_id, 'blocking': True})
            continue
        else:
            # Never let KnowledgeSession.put infer identity by a natural-key collision, including retired items.
            if not isinstance(m['item_id'], str):
                raise ValueError('invalid_identity')
            collision = call.session.scalar(select(KnowledgeItemRow.id).where(
                KnowledgeItemRow.project_id == call.project_id, KnowledgeItemRow.kind == m['kind'],
                KnowledgeItemRow.document.is_(None) if m['document'] is None else KnowledgeItemRow.document == m['document'],
                KnowledgeItemRow.code == m['code']))
            if collision:
                raise ValueError('code_collision_requires_mapping')
        proposals.append((source_id, destination, m))
    unresolved = [r for r in report if r['blocking']]
    acknowledgements = {k.digest(r) for r in report if not r['blocking']}
    if not acknowledgements <= set(body['acknowledged']):
        unresolved += [{'code': 'report_acknowledgement_required', 'report_sha256': sorted(acknowledgements), 'blocking': True}]
    if unresolved:
        row = store.add(call.session, call.project_id, 'import_report', {'input': body, 'report': report + [r for r in unresolved if r not in report]})
        return {'record_id': row.id, 'draft_id': None, 'report': row.payload['report'], 'members': data['members']}
    proposals = _merge_roots(members, proposals)
    draft = call.knowledge.open_draft(call.project_id, expected)
    for source_id, destination, m in proposals:
        ident = call.knowledge.put(draft, m['kind'], m['code'], m['content'], document=m['document'],
            provenance=m['provenance'], source=m['source'], root_position=m['root_position'])
        if destination and ident != destination:
            raise ValueError('identity_mismatch')
        if ident in resolved.values():
            raise ValueError('duplicate_identity_mapping')
        resolved[source_id] = ident
    # Patch selected source links; omission retains destination links. Explicit link changes use the ordinary editor.
    imported_links = []
    selected_ids = {m['item_id'] for m in data['members']}
    for link in data['links']:
        if link['source'] not in selected_ids:
            raise ValueError('link_outside_selected_scope')
        if link['source'] in excluded or link['target'] in excluded:
            raise ValueError('excluded_reference_requires_resolution')
        source = resolved.get(link['source']) or (link['source'] if data['source_project_id'] == call.project_id and link['source'] in members else mappings.get(link['source']))
        target = resolved.get(link['target']) or (link['target'] if data['source_project_id'] == call.project_id and link['target'] in members else mappings.get(link['target']))
        if not source or not target:
            raise ValueError('missing_reference')
        imported_links.append(k.Link(link['kind'], source, target, link['position'], link['qualifier']))
    _merge_links(call, draft, imported_links)
    proposed, links = call.knowledge.manifest(draft)
    k.validate_revision(proposed, links, {'members': members, 'links': call.knowledge.manifest(expected)[1]} if expected else None, adoption=True)
    row = store.add(call.session, call.project_id, 'import_stage', {'input': body, 'draft_id': draft,
        'report': report, 'source_project': data['source_project_id'], 'map': resolved,
        'draft_sha256': k.knowledge_sha256(call.project_id, proposed.values(), links)})
    call.draft_id = draft
    return {'record_id': row.id, 'draft_id': draft, 'report': report, 'members': data['members']}


def preview(call):
    record = store.get(call.session, call.project_id, call.arguments['record_id'])
    if record.kind != 'import_stage':
        raise ValueError('import_not_staged')
    call.arguments = {'draft_id': record.payload['draft_id']}
    value = call.service._preview_of(call)
    if value['draft_sha256'] != record.payload['draft_sha256']:
        raise ValueError('import_draft_changed')
    call.authorize()
    value.update(record_id=record.id, report=record.payload['report'], mapping=record.payload['map'])
    value['preview_sha256'] = k.digest({'canonical': value['preview_sha256'], 'input': record.sha256})
    return value


def adopt(call):
    args = dict(call.arguments)
    value = preview(call)
    if value['preview_sha256'] != args['preview_sha256'] or value['base_revision_id'] != args['expected_revision_id']:
        raise ValueError('preview_stale')
    if not args['reason'].strip():
        raise ValueError('reason_required')
    revision = call.knowledge.adopt(value['draft_id'], args['expected_revision_id'], origin='owner_confirmed',
                                    actor=call.caller.actor(), reason=args['reason'])
    record = store.get(call.session, call.project_id, args['record_id'])
    store.add(call.session, call.project_id, 'identity_map', {'source_project': record.payload['source_project'],
        'map': record.payload['map'], 'revision_id': revision.id, 'consent': args})
    call.draft_id = call.revision_id = revision.id
    request_export(call.session, call.project_id, revision.id, {'import_record': args['record_id']})
    return {'revision_id': revision.id, 'revision_sha256': revision.revision_sha256,
            'continuation': 'export_required'}


def ownership_prepare(call):
    call.authorize()
    body = d.loads(call.arguments['payload'])
    d.closed(body, ('wrappers', 'baseline'))
    revision = head(call)
    manifest = d.ownership(call.project_id, language(call), body['wrappers'])
    files = d.render(d.snapshot(revision), manifest)
    previous = store.latest(call.session, call.project_id, 'ownership')
    if previous and not {t['path'] for t in previous.payload['manifest']['targets']} <= set(files):
        raise ValueError('ownership_removal_unsupported')
    if set(body['baseline']['targets']) != set(files):
        raise ValueError('baseline_targets')
    payload = {'manifest': manifest, 'baseline': body['baseline'], 'revision_id': revision.id, 'files': files}
    row = store.add(call.session, call.project_id, 'ownership_preview', payload)
    return {'record_id': row.id, 'preview_sha256': row.sha256, **payload}


def ownership_adopt(call):
    call.authorize()
    args = call.arguments
    row = store.get(call.session, call.project_id, args['record_id'])
    from my_harness.storage.models import CheckoutLockRow
    from my_harness.storage.models import ManagedJobRow, ManagedRunRow
    from my_harness.storage.registry import UNFINISHED
    pending = call.session.scalar(select(ManagedJobRow.id).join(ManagedRunRow, ManagedJobRow.run_id == ManagedRunRow.id).where(
        ManagedRunRow.root == call.caller.root, ManagedJobRow.status.in_(UNFINISHED)))
    if pending or call.session.get(CheckoutLockRow, call.caller.root):
        raise ValueError('checkout_writer_active')
    if row.kind != 'ownership_preview' or row.sha256 != args['preview_sha256'] or row.payload['revision_id'] != head(call).id:
        raise ValueError('preview_stale')
    if args['expected_revision_id'] != row.payload['revision_id']:
        raise ValueError('stale_revision')
    if not args['reason'].strip():
        raise ValueError('reason_required')
    result = store.add(call.session, call.project_id, 'ownership', {**row.payload, 'actor': call.caller.actor(),
                      'reason': args['reason'], 'preview_sha256': row.sha256})
    return {'record_id': result.id, 'manifest': result.payload['manifest'], 'continuation': 'export_required'}


def export_prepare(call):
    call.authorize()
    adopted = store.latest(call.session, call.project_id, 'ownership')
    if not adopted:
        raise ValueError('ownership_required')
    revision = head(call)
    files = d.render(d.snapshot(revision), adopted.payload['manifest'])
    baseline = d.loads(call.arguments['payload'])
    if baseline.pop('ownership_id', None) != adopted.id:
        raise ValueError('ownership_stale')
    if set(baseline['targets']) != set(files):
        raise ValueError('baseline_targets')
    intake_binding = None
    from my_harness.storage.models import PlanningConversationRow
    requests = store.records(call.session, call.project_id, 'export_requested')
    intake_request = next((r for r in requests if (r.payload.get('source') or {}).get('conversation_id')), None)
    if intake_request:
        source = intake_request.payload['source']
        conversation = call.session.get(PlanningConversationRow, source['conversation_id'])
        if conversation is None or conversation.root != call.caller.root:
            raise ValueError('intake_source_missing')
        intake_binding = {'conversation_id': conversation.id, 'source': conversation.source,
                          'preview': source['intake_preview']}
        if not store.latest(call.session, call.project_id, 'export_completed'):
            original_head = (conversation.source or {}).get('inventory', {}).get('head')
            if baseline['head'] != original_head:
                raise ValueError('intake_head_changed')
    payload = {'intake_binding': intake_binding, 'ownership_id': adopted.id, 'manifest': adopted.payload['manifest'], 'baseline': baseline,
               'revision_id': revision.id, 'revision_sha256': revision.revision_sha256, 'files': files}
    row = store.add(call.session, call.project_id, 'export_intent', payload)
    return {'record_id': row.id, 'preview_sha256': row.sha256, **payload}


def stage(call):
    call.authorize()
    try:
        with call.session.begin_nested():
            return _stage(call)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
        call.draft_id = None
        report = [{'code': getattr(exc, 'code', 'input_invalid'), 'detail': str(exc),
                   **getattr(exc, 'location', {}), 'blocking': True}]
        row = store.add(call.session, call.project_id, 'import_report',
                        {'raw_payload': call.arguments['payload'], 'report': report})
        return {'record_id': row.id, 'draft_id': None, 'report': report, 'members': []}


HANDLERS = {'documents.bundle': bundle, 'documents.stage': stage, 'documents.preview': preview,
            'documents.adopt': adopt, 'documents.ownership.prepare': ownership_prepare,
            'documents.ownership.adopt': ownership_adopt, 'documents.export.prepare': export_prepare}


def delivery_state(session, project):
    complete = store.completed_for_project(session, project)
    if complete:
        return {**complete['result'], 'effect_status': complete['result']['status'], 'status': 'export_committed'}
    adopted = store.latest(session, project, 'ownership')
    return {'status': 'export_required' if adopted else 'document_ownership_required'}


def request_export(session, project, revision_id, source=None):
    store.add(session, project, 'export_requested', {'revision_id': revision_id, 'source': source})


def _merged_order(existing, imported):
    """Reorder selected existing slots only; append new entries in their explicit source order."""
    selected = set(imported) & set(existing)
    ordered = iter(i for i in imported if i in selected)
    return [next(ordered) if i in selected else i for i in existing] + [i for i in imported if i not in existing]


def _source_order(entries):
    positions = [position for position, _ in entries]
    if any(type(p) is not int or p < 0 for p in positions) or len(set(positions)) != len(positions):
        raise ValueError('invalid_source_order')
    return [ident for _, ident in sorted(entries)]


def _merge_roots(existing, proposals):
    replacements = {dest: m for _, dest, m in proposals if dest}
    groups = {}
    for source, dest, m in proposals:
        if m['root_position'] is not None:
            groups.setdefault(m['document'], []).append((m['root_position'], dest or source))
    positions = {}
    for document, imported in groups.items():
        roots = sorted((m for m in existing.values() if m.document == document and m.root_position is not None
                        and (m.item_id not in replacements or replacements[m.item_id]['root_position'] is not None)),
                       key=lambda m: m.root_position)
        merged = _merged_order([m.item_id for m in roots], _source_order(imported))
        positions.update({ident: position for position, ident in enumerate(merged)})
    return [(source, dest, {**m, 'root_position': positions[dest or source] if m['root_position'] is not None else None})
            for source, dest, m in proposals]


def _merge_links(call, draft, imported):
    _, existing = call.knowledge.manifest(draft)
    ordered = {}
    for link in imported:
        if link.kind in k.ORDERED_LINKS:
            ordered.setdefault((link.kind, link.target), []).append(link)
        else:
            call.knowledge.link(draft, link.kind, link.source, link.target, position=link.position, qualifier=link.qualifier)
    for (kind, target), incoming in ordered.items():
        prior = sorted((l for l in existing if l.kind == kind and l.target == target), key=lambda l: l.position)
        by_source = {l.source: l for l in (*prior, *incoming)}
        order = _merged_order([l.source for l in prior], _source_order([(l.position, l.source) for l in incoming]))
        # Clear only the draft's touched group before reinsertion: the unique position index forbids swaps in place.
        for link in prior:
            call.knowledge.unlink(draft, kind, link.source, target)
        for position, source in enumerate(order):
            link = replace(by_source[source], position=position)
            call.knowledge.link(draft, kind, source, target, position=link.position, qualifier=link.qualifier)
