"""P008-T014: reverse-engineering conversation over HEAD; private drafts, no effects on the project.

Reuses the bounded export of D083, the import CAS and `planning_conversations.source` (0019).
Does not run sources or commands of the proposed profile. Adoption and commit belong to T015.
"""
from my_harness.adapters.chat_snapshot import HeadSnapshot
from my_harness.adapters.project_onboarding import _InventoryGit, read_inventory as inventory_of
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.definition import MAX_CONTEXT_DRAFT_BYTES, allowed_drafts_view
from my_harness.core.engine.documents import MAX_AGENTS_LINES, MAX_WRAPPER_LINES
from my_harness.core.project_onboarding import OnboardingInventoryError
from my_harness.storage.private_drafts import PrivateDrafts
from my_harness.storage.managed import Conflict
from my_harness.i18n import tr


class OnboardingDrafts(PrivateDrafts):
    area = 'onboarding-drafts'


def read_inventory(context, executable='git'):
    try:
        inventory = inventory_of(context.root, executable=executable)
        target = context.state_file, context.next_steps_file
        reader = HeadSnapshot(context.root, executable=executable)
        reader.git = _InventoryGit(context.root, executable=executable)
        entries = reader.entries(inventory['head'])
        if any(path in entries for path in target) or any(path.startswith('.harness/') for path in entries):
            raise Conflict(tr('onboarding.repository_already_has_harness'))
        if len(freeze(inventory).encode('utf-8')) > MAX_CONTEXT_DRAFT_BYTES:
            raise ValueError(tr('onboarding.onboarding_inventory_exceeds_2'))
        return inventory
    except OnboardingInventoryError as exc:
        raise Conflict(tr('onboarding.project_cannot_onboarded', exc=exc)) from exc


def identity(source):
    inventory = source['inventory']
    return {key: inventory[key] for key in ('head', 'tree', 'inventory_sha256')}


def observation(inspection):
    return {'drafts': dict(sorted(inspection['drafts'].items())), 'invalid': list(inspection['invalid'])}


def turn_context(target, source, texts, inspection):
    drafts = [{'path': path, 'sha256': inspection['drafts'][path], 'size': len(content.encode('utf-8')),
               'content': content} for path, content in sorted(texts.items())]
    result = {'inventory': source['inventory'], **identity(source), 'snapshot_format': 'head-export-1',
              'drafts': drafts, 'foreign': inspection['foreign'], 'invalid': inspection['invalid'],
              'allowed': allowed_drafts_view(target),
              'limits': {target.agents: MAX_AGENTS_LINES, target.claude: MAX_WRAPPER_LINES,
                         target.gemini: MAX_WRAPPER_LINES}}
    if len(freeze(result).encode('utf-8')) > MAX_CONTEXT_DRAFT_BYTES:
        raise ValueError(tr('onboarding.onboarding_inventory_drafts_exceed'))
    return result


def export_snapshot(root, head, destination, executable='git'):
    reader = HeadSnapshot(root, executable=executable)
    # The same no-lazy-fetch requirement as the inventory; no filters, hooks or project processes.
    reader.git = _InventoryGit(root, executable=executable)
    return reader.export(head, destination)
