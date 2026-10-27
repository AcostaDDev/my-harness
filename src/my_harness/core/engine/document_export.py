"""Pure mechanical export: delimited blocks, deterministic bytes and exact commit."""
from dataclasses import asdict, replace
import difflib
import hashlib
import json

from my_harness.core.engine.commit import (
    CommitIntent, CommitPlan, MechanicalUpdate, git_provenance, validate_mechanical_updates,
)
from my_harness.core.engine.document_text import work_language
from my_harness.core.engine.phases import digest, document_hashes
from my_harness.core.engine import documents as layout_v2
from my_harness.i18n import tr

BEGIN, END = layout_v2.markers('state')
MAX_DOCUMENT_BYTES = 512 * 1024


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def replace_block(text, body):
    """Does not normalize or interpret the surrounding prose, including its line endings."""
    return layout_v2.replace_block(text, body, 'state')


def render(snapshot, *, next_steps=False):
    """Readable rendering; free values are escaped as JSON so they cannot inject markers/HTML."""
    # Stable JSON also keeps absent data (null) and unanswered questions explicitly.
    # It excludes export versions/events, the current date and the export's own commit.
    if next_steps:
        data = {'phase': snapshot['phase'], 'pending_tasks': [
            task for task, value in snapshot['tasks'].items() if value['commit'] is None],
            'open_questions': snapshot['open_questions'], 'latest_check': snapshot['latest_check'],
            'batches': snapshot['batches']}
    else:
        data = snapshot
    # Escape HTML, Markdown fences and marker lines in human-provided values.
    pretty = json.dumps(data, ensure_ascii=True, sort_keys=True, indent=2)
    pretty = pretty.replace('<', '\\u003c').replace('>', '\\u003e').replace('`', '\\u0060')
    return 'Estado gestionado por My Harness (SQLite).\n\n```json\n' + pretty + '\n```\n'


def _targets(context, snapshot, baseline):
    """Paths and bodies: D036 (JSON in STATE/NEXT_STEPS) or D072 (readable blocks of the phase documents)."""
    target = layout_v2.layout(context)
    if target is None:
        return [(context.state_file, 'state', render(snapshot)),
                (context.next_steps_file, 'state', render(snapshot, next_steps=True))]
    from my_harness.core.engine.document_ops import read_text
    texts = {path: read_text(context, path) for path in target.phase_documents if path in baseline}
    bodies = layout_v2.managed_bodies(target, snapshot['state'], snapshot['phases'], texts, work_language(context))
    return [(path, *bodies[path]) for path in target.phase_documents if path in bodies and path in baseline]


def preview(context, snapshot, baseline, git):
    paths = (context.state_file, context.next_steps_file)
    if len(set(paths)) != 2 or not set(paths) <= baseline.keys():
        raise ValueError(tr('export.state_next_steps_distinct'))
    targets = _targets(context, snapshot, baseline)
    if document_hashes(context, baseline) != baseline:
        raise ValueError(tr('export.phase_documents_changed_externally'))
    evidence = git.capture(context)
    provenance = git_provenance(evidence)
    if evidence.changed_paths or provenance.index_tree != provenance.base_tree:
        raise ValueError(tr('export.document_export_requires_clean'))
    documents, updates, diffs = [], [], []
    for path, name, body in targets:
        target = context.path(path)
        if not target.is_file() or target.is_symlink() or target.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ValueError(tr('export.export_requires_adopted_regular'))
        old = target.read_bytes().decode('utf-8')
        if text_hash(old) != baseline[path]:
            raise ValueError(tr('export.changed_externally_review_reconcile', path=path))
        new = layout_v2.replace_block(old, body, name)
        if len(new.encode('utf-8')) > MAX_DOCUMENT_BYTES:
            raise ValueError(tr('export.exported_document_exceeds_512'))
        documents.append({'path': path, 'before_sha256': text_hash(old), 'after_sha256': text_hash(new),
                          'content': new})
        if old != new:
            updates.append(MechanicalUpdate(path, new, 'SQLite mechanical state export'))
        delta = difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                    fromfile='a/' + path, tofile='b/' + path)
        diffs.append(''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n'
                             for line in delta))
    validate_mechanical_updates(context, (), tuple(updates))
    for path, _, _ in targets:
        if layout_v2.protected_write(context, path):
            raise ValueError(tr('export.document_export_targets_protected'))
    data = {'snapshot': snapshot, 'baseline': baseline, 'head': evidence.base_revision,
            'fingerprint': evidence.fingerprint, 'tree': provenance.worktree_tree, 'index_tree': provenance.index_tree,
            'documents': documents, 'mechanical': [asdict(u) for u in updates], 'diff': ''.join(diffs)}
    return {**data, 'preview_sha256': digest(data)}


def execute(context, history, request, git, journal, now):
    """No agents: human confirmation of the diff, prior intent and H2.4 writer."""
    shown = request['preview']
    raw = request.get('commit_intent')
    exported = {document['path'] for document in shown['documents']}
    unchanged = {p: sha for p, sha in shown['baseline'].items() if p not in exported}
    if document_hashes(context, unchanged) != unchanged:
        return replace(history, status='stopped'), {'status': 'INVALIDATED', 'diagnostic': tr('export.documents_changed_preview')}
    if raw is None:
        if git.capture(context).fingerprint != shown['fingerprint']:
            return replace(history, status='stopped'), {'status': 'INVALIDATED', 'diagnostic': tr('export.checkout_changed_preview')}
        updates = tuple(MechanicalUpdate(**u) for u in shown['mechanical'])
        frozen = shown['snapshot'].get('state') if shown['snapshot'].get('layout') == 'v2' else shown['snapshot']
        message = (f"harness: export phase {frozen['phase']['code']} documents\n\n"
                   f"Harness-Operation: {request['operation_id']}\nHarness-Preview: {shown['preview_sha256']}\n")
        plan = CommitPlan(shown['head'], shown['tree'], updates, message, git.identity.name, git.identity.email,
                          int(now().timestamp()))
        tree, commit = git.seal(context, plan)
        intent = CommitIntent(request['operation_id'], history.id, 'DOCUMENT-EXPORT', shown['head'],
                              shown['fingerprint'], shown['tree'], shown['index_tree'], (), updates, tree, commit,
                              message, plan.author_name, plan.author_email, plan.committed_at)
        journal.export_intent(intent)
    else:
        intent = CommitIntent.from_json(raw)
    outcome = git.execute_export(context, intent, shown['documents'])
    return replace(history, status='completed' if outcome.status != 'invalidated' else 'stopped'), {
        'status': 'COMMITTED' if outcome.status != 'invalidated' else 'INVALIDATED',
        'commit': outcome.commit, 'tree': outcome.tree, 'diagnostic': outcome.diagnostic,
        'reconciled': outcome.status == 'reconciled'}
