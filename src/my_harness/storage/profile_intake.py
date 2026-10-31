"""Accepted profile used only to render documentary commits; never installed as task authority."""
import json

from sqlalchemy import select

from my_harness.core.engine.context import IntakeContext, ProjectContext
from my_harness.i18n import tr
from my_harness.services.local_config import _profile
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PlanningProposalRow as Proposal, PlanningConversationRow as Conversation


def documentary_profile(managed, context, conversation_id, writer, versions):
    if not isinstance(context, IntakeContext):
        return context, {}
    from sqlalchemy.orm import Session
    from my_harness.storage.planning import PlanningRepository
    with Session(managed.engine) as session:
        conversation = session.get(Conversation, conversation_id)
        proposal = session.scalar(select(Proposal).where(Proposal.conversation_id == conversation_id,
            Proposal.kind == 'profile', Proposal.status == 'ACCEPTED'))
        if conversation and (conversation.source or {}).get('authority') == 'structured-intake-1':
            raise Conflict(tr('intake.export_pending'))
        if not conversation or not proposal:
            raise Conflict(tr('profile_proposal.required'))
        shown = PlanningRepository(managed).profile_preview(context, conversation_id, proposal.id,
            conversation.version, proposal.proposal_sha256, writer, session=session, versions=versions)
        if not shown['ready']:
            raise Conflict(tr('profile_proposal.stale'))
        candidate = json.loads(proposal.content)['candidate']
        profile = _profile(candidate['name'], candidate['profile'], allow_formatter=True)
        # Real accepted profile, confined to rendering documents. Runs retain IntakeContext.
        rendered = ProjectContext(context.root, profile, context.policy, context.next_steps_file,
                                  context.state_file, context.documents, context.work_language)
        return rendered, {'profile_proposal_sha256': proposal.proposal_sha256}


def structured_preview(engine, session, context, conversation, proposal_id, proposal_sha256, writer, versions):
    """Profile review binds the staged knowledge and source evidence, independently of export/adoption.

    A draft can qualify a profile preview before or after knowledge adoption. Neither confirmation
    creates private configuration, technical preparation or activation. Existing owner CAS handles writes.
    """
    from my_harness.core.engine.contracts import context_snapshot, freeze
    from my_harness.core.engine.chat import digest
    from my_harness.core.engine.definition import text_hash
    from my_harness.core.engine.knowledge import digest as knowledge_digest
    from my_harness.core.engine.domain_catalogue import CATALOGUE
    from my_harness.services.domain_operations import DomainOperations, owner_writer, DomainRefusal
    from my_harness.services.profile_proposal import validate
    from my_harness.services.intake import binding
    from my_harness.storage.intake_sources import sources
    from my_harness.storage.models import PlanningTurnRow as Turn, ManagedRunRow as Run
    from my_harness.storage.planning import current_questions, _executable
    from my_harness.storage.onboarding import read_inventory

    proposal = session.get(Proposal, proposal_id)
    if (proposal is None or proposal.conversation_id != conversation.id or proposal.kind != 'profile'
            or proposal.status not in ('PROPOSED', 'ACCEPTED') or proposal.proposal_sha256 != proposal_sha256
            or text_hash(proposal.content) != proposal.content_sha256):
        raise Conflict(tr('profile_proposal.stale'))
    payload = json.loads(proposal.content)
    turn = session.get(Turn, proposal.turn_id)
    latest = session.scalar(select(Turn).where(Turn.conversation_id == conversation.id).order_by(Turn.number.desc()))
    run = session.get(Run, turn.run_id)
    blockers, knowledge_binding = [], None
    bound = binding(conversation)
    if (latest.id != turn.id or turn.status != 'ANSWERED' or run.context_json != context_snapshot(context)
            or (versions is not None and run.versions_json != freeze(versions))
            or digest(turn.request['context']) != turn.request['context_sha256']):
        blockers.append(tr('profile_proposal.stale'))
    if not bound or bound['turn_id'] != turn.id or bound['proposal_sha256'] != payload['binding'].get('knowledge_proposal_sha256'):
        blockers.append(tr('intake.profile_knowledge_required'))
    else:
        ops, caller = DomainOperations(engine), owner_writer(conversation.root)
        try:
            view = ops.execute(caller, CATALOGUE.current('knowledge.draft.get').ref, {'draft_id': bound['draft_id']}).result
            head = ops.execute(caller, CATALOGUE.current('knowledge.head').ref, {}).result['revision']
            if (view['status'] not in ('DRAFT', 'ACCEPTED') or view['draft_sha256'] != bound.get('draft_sha256')
                    or (head and head['id'] != bound['draft_id'])):
                raise Conflict(tr('profile_proposal.stale'))
            # Identifies exact deterministic originals as well as the model proposal, including all links.
            knowledge_binding = {'revision_id': bound['draft_id'], 'knowledge_sha256': view['draft_sha256'],
                                 'status': view['status'], 'source_sha256': bound['source_sha256'],
                                 'sources_sha256': bound['sources_sha256']}
        except DomainRefusal:
            blockers.append(tr('profile_proposal.stale'))
    frozen = {**turn.request['context'], 'knowledge_proposal': turn.result['result'].get('knowledge')}
    try:
        if validate(payload['candidate'], frozen, [], context=context) != payload:
            blockers.append(tr('profile_proposal.stale'))
    except ValueError:
        blockers.append(tr('profile_proposal.invalid'))
    live_sources = sources(session, conversation, turn)
    captured_sources = frozen.get('intake_sources', {})
    if (any(live_sources.get(path) != sha for path, sha in captured_sources.items())
            or digest(conversation.source) != payload['binding'].get('intake_source_sha256')
            or digest(conversation.brief) != payload['binding'].get('intake_brief_sha256')
            or (bound and knowledge_digest(live_sources) != bound['sources_sha256'])):
        blockers.append(tr('profile_proposal.stale'))
    if conversation.kind == 'onboarding':
        if read_inventory(context, _executable(writer)) != conversation.source['inventory']:
            blockers.append(tr('profile_proposal.stale'))
    questions, _ = current_questions(session, conversation)
    if any(q['blocking'] and not q.get('deferred') for q in questions):
        blockers.append(tr('profile_proposal.questions'))
    shown = {'conversation_id': conversation.id, 'proposal_id': proposal.id,
             'expected_version': conversation.version, 'proposal_sha256': proposal.proposal_sha256,
             'profile': payload, 'blockers': blockers, 'ready': not blockers,
             'knowledge_binding': knowledge_binding, 'continuation': 'export_commit_pending_T013',
             'configuration_state': 'PROFILE_PROPOSED' if proposal.status == 'ACCEPTED' else 'PROFILE_REQUIRED'}
    return {**shown, 'preview_sha256': digest(shown)}
