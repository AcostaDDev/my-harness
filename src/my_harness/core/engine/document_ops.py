"""D072/H6.3: phase transition and confirmed document editing. No agents.

Both operations follow the D036 export pattern: deterministic preview with
full content and diff, human confirmation of the exact hash, commit intent sealed
before writing and an H2.4 Git writer that reconciles after a crash. Foreign bytes
are never overwritten: each document admits only its previous hash (or absence) or the sealed one.
"""

from dataclasses import asdict, replace
import base64
import difflib
import hashlib

from my_harness.core.engine.commit import (
    CommitIntent, CommitPlan, MechanicalUpdate, git_provenance, validate_mechanical_updates,
)
from my_harness.core.engine.document_text import work_language, words
from my_harness.core.engine.documents import (
    MAX_DOCUMENT_BYTES, Layout, base_section, blocks, budget_warnings, decision_index, inline, markers,
    parse_roadmap, phase_data, plan_tasks, render_decisions, render_next_steps, render_review, render_roadmap,
    protected_write, render_state, render_summary, replace_block, require_layout, _span,
)
from my_harness.core.engine.phases import digest, document_hashes, phase_definition
from my_harness.i18n import tr

EDIT_REASON = 'User-confirmed document edit (D072)'
TRANSITION_REASON = 'Phase transition: archive and fresh documents (D072)'
TERMINAL = ('CLOSED', 'ABANDONED')


class BaseChanged(ValueError):
    """The document no longer has the hash it had when opened in the editor (base hash CAS)."""


class ManagedBlocksEdited(ValueError):
    """An edit touches the generated managed blocks; the API names it with its own code (P011-T022)."""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def read_text(context, path: str) -> str | None:
    """Bounded regular UTF-8 document; None if absent. Links and other types are rejected."""
    target = context.path(path)
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(tr('documents.regular_file', path=path))
    if not target.exists():
        return None
    data = target.read_bytes()
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError(tr('documents.exceeds_512_kib', path=path))
    return data.decode('utf-8')


def diff(path: str, old: str | None, new: str) -> str:
    delta = difflib.unified_diff((old or '').splitlines(keepends=True), new.splitlines(keepends=True),
                                 fromfile='/dev/null' if old is None else 'a/' + path, tofile='b/' + path)
    return ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in delta)


def _clean_capture(context, git):
    evidence = git.capture(context)
    provenance = git_provenance(evidence)
    if evidence.changed_paths or provenance.index_tree != provenance.base_tree:
        raise ValueError(tr('documents.operation_requires_clean_checkout'))
    return evidence, provenance


def _sealed_preview(context, evidence, provenance, tree: str,
                    changes: list[tuple[str, str | bytes | None, str | bytes | None]],
                    reason: str, extra: dict, disk: dict[str, str] | None = None) -> dict:
    """`disk`: local bytes the commit replaces in addition to the base ones (regenerated blocks)."""
    documents, updates, diffs = [], [], []
    for path, old, new in changes:
        if old == new:
            continue
        raw = new if isinstance(new, bytes) else (new.encode('utf-8') if new is not None else None)
        before = old if isinstance(old, bytes) else (old.encode('utf-8') if old is not None else None)
        if raw is not None and len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError(tr('definition.would_exceed_512_kib', path=path))
        binary = isinstance(new, bytes)
        content = base64.b64encode(new).decode('ascii') if binary else new
        documents.append({'path': path, 'before_sha256': None if before is None else hashlib.sha256(before).hexdigest(),
                          'after_sha256': None if raw is None else hashlib.sha256(raw).hexdigest(), 'content': content,
                          **({'encoding': 'base64'} if binary else {}),
                          **({'disk_sha256': text_hash(disk[path])} if disk and path in disk else {})})
        updates.append(MechanicalUpdate(path, content, reason, 'base64' if binary else 'utf-8'))
        diffs.append(f'Archive bytes: {path}\n' if isinstance(old, bytes) or binary else diff(path, old, new or ''))
    validate_mechanical_updates(context, (), tuple(updates))
    data = {**extra, 'head': evidence.base_revision, 'fingerprint': evidence.fingerprint, 'tree': tree,
            'index_tree': provenance.index_tree, 'documents': documents,
            'mechanical': [asdict(update) for update in updates], 'diff': ''.join(diffs)}
    return {**data, 'preview_sha256': digest(data)}


def _protected(context, paths):
    for path in paths:
        if protected_write(context, path):
            raise ValueError(tr('documents.protected_project_profile', path=path))


# --- transition ------------------------------------------------------------------------------


def _state_title(text: str, language: str) -> str:
    first = text.splitlines()[0] if text else ''
    return first if first.startswith('# ') and 'harness-local:managed-' not in first else words(language)['state_title']


def preview_transition(context, snapshot: dict, git, next_steps: str | None, plan_origin: dict | None = None,
                       *, unified=False) -> dict:
    """Byte archive of the finished phase, fresh documents and definition of the next one.

    `plan_origin` (H6.5): proposal of the `phase_planning` conversation the plan comes from; it enters the
    reviewed hash. Without it, the preview keeps exactly its previous shape."""
    target = require_layout(context)
    language = work_language(context)
    w = words(language)
    closed = snapshot['phase']
    code, status = closed['code'], closed['status']
    if status not in TERMINAL:
        raise ValueError(tr('documents.closed_abandoned_phase_archived'))
    baseline = closed['documents']
    if document_hashes(context, baseline) != baseline:
        raise ValueError(tr('documents.phase_documents_changed_externally'))
    evidence, provenance = _clean_capture(context, git)
    texts = {path: read_text(context, path) for path in target.phase_documents}
    missing = sorted(path for path, text in texts.items() if text is None)
    if missing:
        raise ValueError('Transition requires ' + ', '.join(missing))
    entries = parse_roadmap(texts[target.roadmap])
    codes = [entry['code'] for entry in entries]
    if code not in codes:
        raise ValueError(tr('documents.roadmap_has_no_section', code=code))
    following = entries[codes.index(code) + 1] if codes.index(code) + 1 < len(entries) else None
    archive = target.archive(code)
    folder = context.path(archive)
    if folder.exists() or folder.is_symlink():
        raise ValueError(tr('documents.already_exists_nothing_overwritten', archive=archive))
    definition = None
    if following is not None:
        if following['code'] in snapshot['existing_codes']:
            raise ValueError(tr('documents.phase_already_exists_checkout', code=following['code']))
        if unified:
            next_steps = (f"# {following['code']} — {inline(following['title'])}\n\n"
                          f"{w['objective']} {following['objective']}\n\n{w['exit_criteria']}\n"
                          + ''.join(f'- {item}\n' for item in following['exit_criteria'])
                          + w['next_plan_pending'])
        if not isinstance(next_steps, str) or not next_steps.strip():
            raise ValueError(tr('documents.provide_next_steps_plan', code=following['code']))
        if '\0' in next_steps:
            raise ValueError(tr('documents.plan_nul_free_text'))
        if set(blocks(next_steps)) - {'state'}:
            raise ValueError(tr('definition.plan_may_contain_managed'))
        tasks = plan_tasks(next_steps, following['code'])
        if not tasks and not unified:
            raise ValueError(tr('definition.plan_needs_least_one', code=following['code']))
        definition = phase_definition(context, phase_data(target, following, tasks))
        plan = next_steps
    else:
        if next_steps is not None:
            raise ValueError(tr('documents.roadmap_has_no_further'))
        tasks = []
        plan = w['roadmap_finished'].format(code=inline(code))
    titles = {entry['code']: entry['title'] for entry in entries}
    upcoming = None if following is None else {'code': following['code'], 'status': 'ACTIVE',
                                               'objective': following['objective']}
    fresh = {'phase': upcoming, 'tasks': [{'task_id': task, 'status': None, 'planned': True} for task, _ in tasks],
             'open_questions': [], 'latest_check': None}
    base = (base_section(texts[target.state]) or w['empty_baseline']).rstrip()
    begin, end = markers('state')
    active = (w['active_heading'].format(code=following['code'], title=inline(following['title']))
              if following else w['no_active_heading'])
    state = replace_block(f'{_state_title(texts[target.state], language)}\n\n{begin}\n{end}\n\n{base}\n\n{active}',
                          render_state(fresh, language))
    plan = replace_block(plan, render_next_steps(fresh, language))
    phases = {**snapshot['phases'], code: {'status': status, 'tag': closed['definition'].get('tag')}}
    if unified:
        phases[code]['archive'] = archive.removeprefix(target.docs + '/') + '/'
    if following is not None:
        phases[following['code']] = {'status': 'ACTIVE', 'tag': following['tag']}
    rows = [{'code': entry['code'], 'title': entry['title'], **phases.get(entry['code'], {})} for entry in entries]
    roadmap = replace_block(texts[target.roadmap], render_roadmap(rows, language), 'roadmap')
    decisions = replace_block(texts[target.decisions],
                              render_decisions(decision_index(texts[target.decisions]), language), 'decisions')
    summary = {**snapshot['summary'], 'phase': {**snapshot['summary']['phase'], 'title': titles[code]}}
    changes = [(f'{archive}/STATE.md', None, texts[target.state]),
               (f'{archive}/NEXT_STEPS.md', None, texts[target.next_steps]),
               (f'{archive}/REVIEW.md', None, render_review(code, snapshot['check'], status, language)),
               (f'{archive}/SUMMARY.md', None, render_summary(summary, language)),
               (target.state, texts[target.state], state), (target.next_steps, texts[target.next_steps], plan),
               (target.roadmap, texts[target.roadmap], roadmap), (target.decisions, texts[target.decisions], decisions)]
    for _, _, text in changes[4:]:
        blocks(text)  # no injected or partial marker in the fresh documents
    if unified:
        work = context.path(target.phase_dir)
        if work.exists():
            if not work.is_dir():
                raise ValueError(tr('documents.directory', phase_dir=target.phase_dir))
            reserved = {'STATE.md', 'NEXT_STEPS.md', 'REVIEW.md', 'SUMMARY.md'}
            for path in sorted(work.rglob('*')):
                relative = path.relative_to(work).as_posix()
                source = f'{target.phase_dir}/{relative}'
                safe = context.path(source)  # rejects file and directory links
                if safe.is_dir():
                    continue
                if not safe.is_file():
                    raise ValueError(tr('documents.regular_file_2', source=source))
                if relative.split('/')[0] in reserved:
                    raise ValueError(tr('documents.conflicts_phase_archive_documents', source=source))
                if safe.stat().st_size > MAX_DOCUMENT_BYTES:
                    raise ValueError(tr('documents.exceeds_512_kib_2', source=source))
                data = safe.read_bytes()
                changes.extend([(f'{archive}/{relative}', None, data), (source, data, None)])
    _protected(context, [path for path, _, _ in changes])
    after = {target.state: state, target.next_steps: plan, target.roadmap: roadmap, target.decisions: decisions}
    return _sealed_preview(context, evidence, provenance, provenance.worktree_tree, changes, TRANSITION_REASON, {
        'operation': 'phase_close' if unified else 'phase_transition', 'snapshot': snapshot, 'closed': code, 'archive': archive,
        'next': definition, 'warnings': budget_warnings(target, after),
        **({'plan_origin': plan_origin} if plan_origin is not None else {})})


# --- document editing ------------------------------------------------------------------------


def _edit_checks(target: Layout, path: str, old: str | None, new: str):
    if not target.editable(path):
        raise ValueError(tr('documents.not_editable_document_readme', path=path, docs=target.docs))
    if not isinstance(new, str) or '\0' in new:
        raise ValueError(tr('documents.nul_free_text', path=path))
    try:
        before = blocks(old or '')
        after = blocks(new)
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from exc
    if before != after:
        raise ManagedBlocksEdited(tr('documents.managed_blocks_generated_harness', path=path))


def restore_blocks(local: str, base: str | None, path: str) -> str:
    """Local prose with the base managed blocks: «regenerate» after a local edit of a block."""
    try:
        theirs, ours = blocks(local), blocks(base or '')
    except ValueError as exc:
        raise ValueError(tr('documents.restore_markers_hand_before', path=path, exc=exc)) from exc
    if set(theirs) != set(ours):
        raise ValueError(tr('documents.managed_markers_were_added', path=path))
    for name, block in ours.items():  # exact bytes of the base block, including its line endings
        start, stop = _span(local, name)
        local = local[:start] + block + local[stop:]
    return local


def preview_edit(context, git, *, source: str, changes: list[dict] | None, regenerate_blocks: bool = False) -> dict:
    """`content`: documents submitted over a clean checkout. `worktree`: local document changes.

    In `content`, a `base_sha256` (null: the document must not exist) is the editor CAS. In `worktree`,
    `regenerate_blocks` replaces locally edited managed blocks with the base ones; the preview lists them
    with the diff of what is discarded and the writer only admits those exact local bytes."""
    target = require_layout(context)
    if regenerate_blocks and source != 'worktree':
        raise ValueError(tr('documents.worktree_edit_regenerates_managed'))
    evidence = git.capture(context)
    provenance = git_provenance(evidence)
    proposed: dict[str, str] = {}
    previous: dict[str, str | None] = {}
    local: dict[str, str] = {}
    if source == 'content':
        if evidence.changed_paths or provenance.index_tree != provenance.base_tree:
            raise ValueError(tr('documents.checkout_has_local_changes'))
        if not changes:
            raise ValueError(tr('documents.send_least_one_document'))
        for item in changes:
            path, content = item.get('path'), item.get('content')
            if not isinstance(path, str) or path in proposed:
                raise ValueError(tr('documents.each_edited_document_needs'))
            if not target.editable(path):
                raise ValueError(tr('documents.not_editable_document_readme', path=path, docs=target.docs))
            previous[path] = read_text(context, path)
            proposed[path] = content
            if 'base_sha256' in item:
                current = None if previous[path] is None else text_hash(previous[path])
                if current != item['base_sha256']:
                    raise BaseChanged(tr('documents.changed_since_opened_editor', path=path,
                                         base_sha256=str(item['base_sha256'])[:12], current=str(current)[:12]))
    elif source == 'worktree':
        if changes is not None:
            raise ValueError(tr('documents.worktree_edit_takes_documents'))
        if not evidence.changed_paths:
            raise ValueError(tr('documents.no_local_document_changes'))
        import json
        deleted = json.loads(evidence.provenance_json).get('deleted_paths', [])
        if deleted:
            raise ValueError(tr('documents.deleted_not_confirmed', paths=', '.join(deleted[:20])))
        outside = [path for path in evidence.changed_paths if not target.editable(path)]
        if outside:
            raise ValueError(tr('documents.outside_editable', paths=', '.join(outside[:20])))
        for path in evidence.changed_paths:
            blob = git.read_blob(context, evidence.base_revision, path)
            previous[path] = None if blob is None else blob.decode('utf-8')
            proposed[path] = read_text(context, path)
            if regenerate_blocks and previous[path] is not None:
                restored = restore_blocks(proposed[path], previous[path], path)
                if restored != proposed[path]:
                    local[path], proposed[path] = proposed[path], restored
        if regenerate_blocks and not local:
            raise ValueError(tr('documents.no_local_change_touches'))
    else:
        raise ValueError('Unknown edit source')
    for path, content in proposed.items():
        _edit_checks(target, path, previous[path], content)
    # D088: editing DECISIONS regenerates its managed index, from its headings, in the same commit.
    if target.decisions in proposed:
        try:
            index = render_decisions(decision_index(proposed[target.decisions]), work_language(context))
        except ValueError as exc:
            raise ValueError(f'{target.decisions}: {exc}') from exc
        regenerated = replace_block(proposed[target.decisions], index, 'decisions')
        if source == 'worktree' and regenerated != proposed[target.decisions]:
            # Like «regenerate»: the writer admits the exact local bytes and the preview lists the change.
            local.setdefault(target.decisions, proposed[target.decisions])
        proposed[target.decisions] = regenerated
    _protected(context, proposed)
    changes_list = [(path, previous[path], proposed[path]) for path in sorted(proposed)]
    extra = {'operation': 'document_edit', 'source': source}
    if local:
        # What is discarded from the local bytes; part of the reviewed hash.
        extra['regenerated'] = [{'path': path, 'local_sha256': text_hash(local[path]),
                                 'diff': diff(path, local[path], proposed[path])} for path in sorted(local)]
    preview = _sealed_preview(context, evidence, provenance, provenance.base_tree, changes_list, EDIT_REASON,
                              extra, disk=local)
    if not preview['documents']:
        raise ValueError(tr('documents.documents_already_have_content'))
    if source == 'worktree':
        # The whole local change must stay within what was confirmed: the local documents, over the base,
        # reproduce the checkout tree. The index regenerated by the harness is added afterwards.
        probe = tuple(MechanicalUpdate(item['path'], local.get(item['path'], item['content']), item['reason'])
                      for item in preview['mechanical'] if item['path'] in evidence.changed_paths)
        plan = CommitPlan(evidence.base_revision, provenance.base_tree, probe, 'probe\n',
                          git.identity.name, git.identity.email, 0)
        tree, _ = git.seal(context, plan)
        if tree != provenance.worktree_tree:
            raise ValueError(tr('documents.local_changes_not_exactly'))
    return preview


# --- shared execution ------------------------------------------------------------------------


def seal_operation(context, history, request, git, journal, now, *, label):
    """Persists the complete intent before the first closing effect (including the tag)."""
    shown = request['preview']
    raw = request.get('commit_intent')
    if raw is None:
        if git.capture(context).fingerprint != shown['fingerprint']:
            raise BaseChanged(tr('documents.checkout_changed_after_preview'))
        updates = tuple(MechanicalUpdate(**item) for item in shown['mechanical'])
        message = (f"harness: {label}\n\nHarness-Operation: {request['operation_id']}\n"
                   f"Harness-Preview: {shown['preview_sha256']}\n")
        plan = CommitPlan(shown['head'], shown['tree'], updates, message, git.identity.name, git.identity.email,
                          int(now().timestamp()))
        tree, commit = git.seal(context, plan)
        kind = {'phase_transition': 'PHASE-TRANSITION', 'phase_close': 'PHASE-CLOSE'}.get(
            shown['operation'], 'DOCUMENT-EDIT')
        intent = CommitIntent(request['operation_id'], history.id, kind, shown['head'], shown['fingerprint'],
                              shown['tree'], shown['index_tree'], (), updates, tree, commit, message,
                              plan.author_name, plan.author_email, plan.committed_at)
        journal.document_intent(intent)
    else:
        intent = CommitIntent.from_json(raw)
    return intent


def execute(context, history, request, git, journal, now, *, label: str):
    """Prior sealed intent and H2.4 writer; an existing intent is only reconciled."""
    shown = request['preview']
    try:
        intent = seal_operation(context, history, request, git, journal, now, label=label)
    except BaseChanged as exc:
        return replace(history, status='stopped'), {'status': 'INVALIDATED', 'diagnostic': str(exc)}
    outcome = git.execute_documents(context, intent, shown['documents'])
    committed = outcome.status != 'invalidated'
    return replace(history, status='completed' if committed else 'stopped'), {
        'status': 'COMMITTED' if committed else 'INVALIDATED', 'commit': outcome.commit, 'tree': outcome.tree,
        'diagnostic': outcome.diagnostic, 'reconciled': outcome.status == 'reconciled'}
