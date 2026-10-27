"""Classify persisted legacy/A work without loading its code or executing its intent."""
import json

from sqlalchemy import select

from my_harness.storage.models import (
    PlanningConversationRow as Conversation, PlanningTurnRow as Turn, ProjectImportRow as Import,
)
from my_harness.i18n import tr


def reason(session, run, request_json=None):
    action = None
    if request_json is not None:
        try:
            action = json.loads(request_json)['action']
        except (ValueError, TypeError, KeyError):
            return tr('retired.request_unclassified')
    if ((run.purpose == 'import_commit' and action not in (None, 'import_commit'))
            or (action == 'import_commit' and run.purpose != 'import_commit')
            or (action == 'planning_turn' and run.purpose not in ('definition', 'phase_planning', 'onboarding', 'project_import'))):
        return tr('retired.import_request_unclassified')
    if run.purpose == 'project_import':
        return tr('retired.removed')
    if run.purpose == 'import_commit':
        op = session.scalar(select(Import).where(Import.run_id == run.id))
        conversation = session.get(Conversation, op.conversation_id) if op else None
        if conversation is not None and conversation.kind == 'project_import':
            return tr('retired.removed')
        inventory = conversation.source.get('inventory') if conversation and isinstance(conversation.source, dict) else None
        origin = op.preview.get('origin') if op and isinstance(op.preview, dict) else None
        if (op is None or conversation is None or conversation.kind != 'onboarding'
                or conversation.root != run.root or op.root != run.root
                or not isinstance(op.preview, dict) or op.preview.get('flow') != 'onboarding'
                or not isinstance(inventory, dict)
                or inventory.get('format') != 'harness-local/onboarding-inventory/1'
                or op.preview.get('source') != {key: inventory.get(key) for key in ('head', 'tree', 'inventory_sha256')}
                or not isinstance(origin, dict) or origin.get('conversation_id') != conversation.id):
            return tr('retired.import_unclassified')
    if run.purpose in ('definition', 'phase_planning', 'onboarding'):
        turn = session.scalar(select(Turn).where(Turn.run_id == run.id))
        conversation = session.get(Conversation, turn.conversation_id) if turn else None
        if (conversation is None or conversation.kind != run.purpose or conversation.root != run.root
                or not isinstance(turn.request, dict) or not isinstance(turn.request.get('context'), dict)
                or turn.request['context'].get('kind') != run.purpose):
            return tr('retired.conversation_inconsistent')
    return None


def abort(managed, session, run, status, diagnostic):
    # Preserve conversations, drafts, sealed intents and operation rows verbatim.
    managed._event(session, run, 'retired_work_resolved', {'status': status, 'reason': diagnostic})
