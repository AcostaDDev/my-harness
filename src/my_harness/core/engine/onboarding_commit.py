"""P008-T015: confirmable Flow B documents, without generated code or fallback."""
from hashlib import sha256
import json

from my_harness.core.engine.contracts import context_snapshot, freeze
from my_harness.core.engine.definition import _block_names, allowed_draft, definition_layout, required_documents
from my_harness.core.engine.document_text import work_language, words
from my_harness.core.engine.documents import MAX_AGENTS_LINES, MAX_WRAPPER_LINES, blocks
from my_harness.core.engine.import_commit import adopt_documents, check_destinations, preview_tree
from my_harness.core.engine.phases import digest
from my_harness.i18n import tr

MESSAGE = 'docs: incorporar al control del harness'


def preview(context, source, contents, paths, drafts, record, inspection, writer):
    target = definition_layout(context)
    if record['pending_turn']:
        raise ValueError(tr('onboarding.onboarding_turn_pending_wait'))
    if inspection['invalid'] or inspection['foreign']:
        raise ValueError(tr('onboarding.invalid_foreign_entries_private'))
    if any(q['blocking'] and not q.get('deferred') for q in record['questions']):
        raise ValueError(tr('onboarding.blocking_questions_remain_open'))
    if any(not allowed_draft(target, path) for path in drafts):
        raise ValueError(tr('onboarding.documentation_drafts_allowed'))
    if not context.profile.validations:
        raise ValueError(tr('onboarding.operator_composition_needs_profile'))
    tree = dict(contents)
    tree.update({path: text.encode('utf-8') for path, text in drafts.items()})
    if missing := [path for path in required_documents(target) if not tree.get(path, b'').strip()]:
        raise ValueError(tr('definition.required_missing', paths=', '.join(missing)))
    # An existing README is retained by bytes unless the user explicitly drafts its replacement.
    for path in (set(required_documents(target)) - {target.readme}) | set(drafts):
        data = tree[path]
        text = data.decode('utf-8')
        if set(blocks(text)) - _block_names(target, path):
            raise ValueError(tr('onboarding.contains_managed_blocks_another', path=path))
    for path, limit in ((target.agents, MAX_AGENTS_LINES), (target.claude, MAX_WRAPPER_LINES),
                        (target.gemini, MAX_WRAPPER_LINES)):
        if len(tree[path].decode('utf-8').splitlines()) > limit:
            raise ValueError(tr('definition.contain_most_lines_d088', path=path, limit=limit))
    phase = adopt_documents(context, tree)
    if phase['code'] != 'P001':
        raise ValueError(tr('onboarding.onboarding_adopt_p001_active'))
    profile = json.loads(context_snapshot(context))['profile']
    preserved = []
    for path, original in sorted(contents.items()):
        if tree[path] != original:
            archive = f'{target.archive("P000")}/onboarding-originals/{path}'
            tree[archive] = original
            preserved.append({'source': path, 'target': archive, 'sha256': sha256(original).hexdigest()})
    archive = target.archive('P000')
    tree[archive + '/INVENTORY.json'] = (freeze(source['inventory']) + '\n').encode()
    summary = {'source': source['inventory']['head'], 'tree': source['inventory']['tree'],
               'conversation': record, 'profile': profile, 'preserved': preserved}
    tree[archive + '/SUMMARY.md'] = (words(work_language(context))['onboarding_summary'] + '```json\n'
        + json.dumps(summary, ensure_ascii=False, indent=2) + '\n```\n').encode()
    # Check all HEAD paths, including code outside the documentary preview. Never replace an existing archive.
    new = set(tree) - set(contents)
    check_destinations([*paths, *new])
    shown = preview_tree(context, source, contents, tree, phase, writer, {
        'flow': 'onboarding', 'origin': {'conversation_id': record['id'],
            'conversation_version': record['version'], 'drafts': inspection['drafts']},
        'source': {k: source['inventory'][k] for k in ('head', 'tree', 'inventory_sha256')},
        'profile': profile, 'profile_sha256': digest(profile),
        'profile_proposal': source['inventory']['profile_proposal'],
        'moves': [], 'preserved': preserved, 'foreign': [],
        'warnings': [tr('definition.pending', item=item) for item in record['pending']]
            + [tr('definition.deferred', question=q['text'], reason=q['deferred']['reason'])
               for q in record['questions'] if q.get('deferred')]}, MESSAGE)
    return shown
