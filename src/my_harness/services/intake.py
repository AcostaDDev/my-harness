"""T011 intake commands. All mutations share the domain service transaction and outcome.

The conversation is evidence; D284 members/versions/links are the draft authority. Log entries
hold only binding references. No export, profile activation or operational phase is created here.
"""
from sqlalchemy import select

from my_harness.core.engine import knowledge as core
from my_harness.i18n import tr
from my_harness.services.domain_operations import DomainRefusal
from my_harness.storage.models import PlanningConversationRow as Conversation, PlanningTurnRow as Turn
from my_harness.storage.planning import current_questions

FORMAT = 'structured-intake-1'


def identity(item):
    return ':'.join((item['kind'], item.get('document') or '', item['code']))


def conversation(call):
    row = call.session.get(Conversation, call.arguments['conversation_id'])
    if row is None or row.root != call.caller.root or (row.source or {}).get('authority') != FORMAT:
        raise DomainRefusal('not_found')
    if row.version != call.arguments['expected_version']:
        raise DomainRefusal('preview_stale')
    if call.session.scalar(select(Turn.id).where(Turn.conversation_id == row.id, Turn.status == 'QUEUED')):
        raise DomainRefusal('preview_stale')
    return row


def binding(row):
    return next((entry for entry in reversed(row.log) if entry.get('action') == FORMAT), None)


def stage(call):
    row = conversation(call)
    turn = call.session.scalar(select(Turn).where(Turn.conversation_id == row.id).order_by(Turn.number.desc()))
    if turn is None or turn.status != 'ANSWERED' or turn.id != call.arguments['turn_id']:
        raise DomainRefusal('preview_stale')
    proposal = turn.result['result'].get('knowledge')
    if not proposal or core.digest(proposal) != call.arguments['proposal_sha256']:
        raise DomainRefusal('preview_stale')
    head = call.knowledge.head(call.project_id)
    # Intake never implicitly converts a previously adopted project.
    if head is not None:
        raise DomainRefusal('stale_revision')
    call.authorize()
    previous = binding(row)
    if previous:
        if previous['turn_id'] == turn.id:
            raise DomainRefusal('draft_not_open')
        call.knowledge.discard(previous['draft_id'])
    draft = call.knowledge.open_draft(call.project_id, None)
    from my_harness.core.engine.definition import text_hash
    from my_harness.storage.intake_sources import sources
    evidence_sources = sources(call.session, row, turn)
    source_hashes = set(evidence_sources.values())
    instruction_report, originals, original_links = [], {}, []
    if row.kind == 'onboarding':
        from pathlib import Path
        from my_harness.adapters.chat_snapshot import HeadSnapshot
        from my_harness.adapters.local_git import LocalGit
        reader = HeadSnapshot(Path(row.root))
        reader.git = LocalGit(Path(row.root))
        head_id = row.source['inventory']['head']
        entries = reader.entries(head_id)
        texts = {}
        for path in ('AGENTS.md', 'CLAUDE.md', 'GEMINI.md'):
            if path in entries:
                oid, size, _mode = entries[path]
                if size > core.MAX_TEXT:
                    raise ValueError(tr('intake.invalid'))
                data = reader.git.run('cat-file', 'blob', oid)
                if len(data) != size:
                    raise ValueError(tr('intake.invalid'))
                texts[path] = data.decode('utf-8')
        staged = core.stage_instructions(texts.get('AGENTS.md', ''), {
            target: texts[path] for target, path in (('claude', 'CLAUDE.md'), ('gemini', 'GEMINI.md')) if path in texts})
        instruction_report = staged['report']
        for entry in staged['sections']:
            path = {'agents': 'AGENTS.md', 'claude': 'CLAUDE.md', 'gemini': 'GEMINI.md'}[entry['target']]
            code = 'original-' + entry['code']
            originals['section:instructions:' + code] = {
                'op': 'put', 'kind': 'section', 'document': 'instructions', 'code': code,
                'content': {'title': entry['title'], 'body': entry['body'], 'target': entry['target'],
                            'format': 'markdown', 'status': 'active'}, 'provenance': 'known',
                'source': {'kind': 'observation', 'reference': head_id, 'sha256': text_hash(texts[path]), 'path': path},
                'root_position': entry['position'] if entry['parent'] is None else None}
            if entry['parent'] is not None:
                original_links.append({'kind': 'part_of', 'source': 'section:instructions:' + code,
                    'target': 'section:instructions:original-' + entry['parent'], 'position': entry['position']})
    previous_members = call.knowledge.manifest(previous['draft_id'])[0] if previous else {}
    previous_originals = {identity({'kind': m.kind, 'document': m.document, 'code': m.code}): m
                          for m in previous_members.values() if identity({'kind': m.kind, 'document': m.document, 'code': m.code}) in originals}
    proposed_originals = {identity(item): item for item in proposal['items'] if identity(item) in originals}
    for key, item in proposed_originals.items():
        expected = originals[key]
        old = previous_originals.get(key)
        if (old is None or item['content'] != expected['content'] or item['source'] != expected['source']
                or item['provenance'] != expected['provenance'] or item.get('root_position') != old.root_position
                or old.content != expected['content'] or old.source != expected['source']
                or old.provenance != expected['provenance']):
            raise ValueError(tr('intake.invalid'))
    ordinary = [item for item in proposal['items'] if identity(item) not in originals]
    roots = sorted((item for item in ordinary if item.get('document') == 'instructions'
                    and item.get('root_position') is not None), key=lambda item: item['root_position'])
    # Removing preserved originals leaves slots; compact only this deterministic document merge.
    ordinary = [dict(item) for item in ordinary]
    positions = {identity(item): position for position, item in enumerate(roots)}
    for item in ordinary:
        if identity(item) in positions:
            item['root_position'] = positions[identity(item)]
    offset = len(roots)
    for item in originals.values():
        if item['root_position'] is not None:
            item['root_position'] += offset
    trusted_links = {(l['kind'], l['source'], l['target']): l for l in original_links}
    links = []
    for link in proposal['links']:
        if link['source'] in originals or link['target'] in originals:
            expected = trusted_links.get((link['kind'], link['source'], link['target']))
            if (expected is None or link.get('position') != expected.get('position')
                    or link.get('qualifier') is not None):
                raise ValueError(tr('intake.invalid'))
        else:
            links.append(link)
    merged_items = [*ordinary, *originals.values()]
    merged_links = [*links, *original_links]
    ids = {}
    for item in merged_items:
        key = identity(item)
        if key in ids:
            raise ValueError(tr('intake.invalid'))
        if identity(item) not in originals and (not item.get('source') or item['source'].get('sha256') not in source_hashes):
            raise ValueError(tr('intake.invalid'))
        source = item.get('source') or {}
        if identity(item) not in originals:
            if ('path' in source and evidence_sources.get(source['path']) != source.get('sha256')
                    or source.get('reference', '').startswith('owner-turn:')
                    and evidence_sources.get(source['reference']) != source.get('sha256')):
                raise ValueError(tr('intake.invalid'))
        ids[key] = call.knowledge.put(draft, item['kind'], item['code'], item['content'],
            document=item.get('document'), provenance=item['provenance'], source=item['source'],
            root_position=item.get('root_position'))
    for link in merged_links:
        if link['source'] not in ids or link['target'] not in ids:
            raise ValueError(tr('intake.invalid'))
        call.knowledge.link(draft, link['kind'], ids[link['source']], ids[link['target']],
                            position=link.get('position'), qualifier=link.get('qualifier'))
    call.draft_id = draft
    members, manifest_links = call.knowledge.manifest(draft)
    row.log = [*row.log, {'action': FORMAT, 'draft_id': draft, 'turn_id': turn.id,
                          'proposal_sha256': call.arguments['proposal_sha256'],
                          'instruction_report': instruction_report, 'sources_sha256': core.digest(evidence_sources),
                          'draft_sha256': core.knowledge_sha256(call.project_id, members.values(), manifest_links),
                          'source_sha256': core.digest(row.source), 'brief_sha256': core.digest(row.brief)}]
    row.version += 1
    return {'draft_id': draft, 'conversation_id': row.id}


def preview(call):
    row = conversation(call)
    bound = binding(row)
    if bound is None:
        raise DomainRefusal('not_found')
    turn = call.session.scalar(select(Turn).where(Turn.conversation_id == row.id).order_by(Turn.number.desc()))
    if turn is None or turn.id != bound['turn_id'] or core.digest(row.source) != bound['source_sha256']:
        raise DomainRefusal('preview_stale')
    from my_harness.storage.intake_sources import sources
    if core.digest(sources(call.session, row, turn)) != bound['sources_sha256']:
        raise DomainRefusal('preview_stale')
    if core.digest(row.brief) != bound['brief_sha256']:
        raise DomainRefusal('preview_stale')
    if row.kind == 'onboarding':
        from my_harness.storage.onboarding import read_inventory
        from types import SimpleNamespace
        from pathlib import Path
        layout = turn.request['context']['project']['layout']
        try:
            inventory = read_inventory(SimpleNamespace(root=Path(row.root), state_file=layout['state'],
                                                       next_steps_file=layout['next_steps']))
        except (RuntimeError, ValueError):
            raise DomainRefusal('preview_stale') from None
        if inventory != row.source['inventory']:
            raise DomainRefusal('preview_stale')
    try:
        call.knowledge.draft(bound['draft_id'])
    except ValueError:
        raise DomainRefusal('draft_not_open') from None
    members, links = call.knowledge.manifest(bound['draft_id'])
    if core.knowledge_sha256(call.project_id, members.values(), links) != bound.get('draft_sha256'):
        raise DomainRefusal('preview_stale')
    core.validate_revision(members, links, adoption=True)
    active = [m for m in members.values() if m.content['status'] not in ('retired', 'withdrawn')]
    kinds = {m.kind for m in active}
    if not {'requirement', 'criterion', 'phase', 'task', 'section'} <= kinds:
        raise ValueError(tr('intake.invalid'))
    if set(core.DOCUMENTS) - {m.document for m in active if m.kind == 'section'}:
        raise ValueError(tr('intake.invalid'))
    for m in active:
        if m.kind in ('requirement', 'phase', 'task') and not any(
                l.kind == 'criterion_of' and l.target == m.item_id for l in links):
            raise ValueError(tr('intake.invalid'))
    questions, pending = current_questions(call.session, row)
    blockers = [q for q in questions if q['blocking'] and not q.get('deferred')]
    if blockers:
        raise ValueError(tr('intake.invalid'))
    call.authorize()
    changes = core.change_summary(members, links, None)
    data = {'conversation_id': row.id, 'version': row.version, **bound,
            'draft_sha256': core.knowledge_sha256(call.project_id, members.values(), links),
            'questions': questions, 'gaps': pending, 'changes': changes,
            'members': [call.service._member(m) for m in sorted(members.values(), key=lambda m: (m.kind, m.code))],
            'links': [call.service._link(l) for l in sorted(links, key=core.Link.key)],
            'continuation': 'document_ownership_required',
            'gates': ['profile_confirmation', 'preparation', 'activation', 'readiness_T016']}
    return {**data, 'preview_sha256': core.digest(data)}


def adopt(call):
    shown = preview(call)
    if shown['preview_sha256'] != call.arguments['preview_sha256']:
        raise DomainRefusal('preview_stale')
    if not call.arguments['reason'].strip():
        raise DomainRefusal('reason_required')
    if call.knowledge.head(call.project_id) is not None:
        raise DomainRefusal('stale_revision')
    require_profile_continuation(call)
    revision = call.knowledge.adopt(shown['draft_id'], None, origin='owner_confirmed',
                                   actor=call.caller.actor(), reason=call.arguments['reason'])
    call.draft_id = call.revision_id = revision.id
    from my_harness.services.knowledge_exchange import request_export
    request_export(call.session, call.project_id, revision.id, {'conversation_id': call.arguments['conversation_id'],
        'intake_preview': shown})
    return {'revision_id': revision.id, 'number': revision.number, 'origin': revision.origin,
            'revision_sha256': revision.revision_sha256, 'continuation': shown['continuation'],
            'intake_preview': shown}


def require_profile_continuation(call):
    """Do not close profileless intake until an independently confirmable profile is available.

    The frozen run context determines whether a profile was selected; model output cannot waive
    the guard. Reuse the existing exact profile preview in this adoption transaction. Merely
    having a proposal row is insufficient, and no profile confirmation is performed here.
    """
    from my_harness.core.engine.context import IntakeContext
    from my_harness.core.engine.serialization import restore_context
    from my_harness.storage.models import ManagedRunRow, PlanningProposalRow
    from my_harness.storage.profile_intake import structured_preview
    from my_harness.storage.managed import Conflict

    row = conversation(call)
    turn = call.session.scalar(select(Turn).where(Turn.conversation_id == row.id).order_by(Turn.number.desc()))
    context = restore_context(call.session.get(ManagedRunRow, turn.run_id).context_json)
    if not isinstance(context, IntakeContext):
        return
    for proposal in call.session.scalars(select(PlanningProposalRow).where(
            PlanningProposalRow.conversation_id == row.id, PlanningProposalRow.turn_id == turn.id,
            PlanningProposalRow.kind == 'profile', PlanningProposalRow.status.in_(('PROPOSED', 'ACCEPTED')))):
        try:
            shown = structured_preview(call.service.engine, call.session, context, row, proposal.id,
                                       proposal.proposal_sha256, None, None)
            if shown['ready']:
                return
        except (Conflict, ValueError, DomainRefusal):
            continue
    raise DomainRefusal('intake_profile_required')
