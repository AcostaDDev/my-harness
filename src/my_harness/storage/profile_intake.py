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
