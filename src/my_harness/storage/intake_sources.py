"""Conversation-scoped evidence locators; content is evidence, never authorization."""
from sqlalchemy import select
from my_harness.core.engine.definition import text_hash
from my_harness.core.engine.chat import digest
from my_harness.core.engine.contracts import ContractError
from my_harness.i18n import tr
from my_harness.storage.models import PlanningTurnRow


def sources(session, conversation, through=None):
    result = {}
    if conversation.brief:
        result['brief'] = conversation.brief['sha256']
    result.update({entry['path']: entry['sha256']
                   for entry in (conversation.source or {}).get('inventory', {}).get('entries', [])
                   if entry.get('status') == 'read' and entry.get('sha256')})
    query = select(PlanningTurnRow).where(PlanningTurnRow.conversation_id == conversation.id,
                                        PlanningTurnRow.status == 'ANSWERED')
    if through is not None:
        query = query.where(PlanningTurnRow.number <= through.number)
    for turn in session.scalars(query.order_by(PlanningTurnRow.number)):
        if (digest(turn.request['context']) != turn.request['context_sha256']
                or digest({'message': turn.message, 'context_sha256': turn.request['context_sha256']}) != turn.request_sha256):
            raise ContractError(tr('intake.invalid'))
        result['owner-turn:' + turn.id] = text_hash(turn.message)
    if through is not None:
        result['owner-message'] = text_hash(through.message)
    return result
