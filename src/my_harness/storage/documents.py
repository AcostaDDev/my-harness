"""D072/H6.3: SQLite authority of the documentary contract.

SQLite projections for the managed blocks, mechanical regeneration in each task
commit, adoption of the hashes the harness itself writes and confirmed documentary editing
as a phase operation with a reconcilable intent. Disk reads happen outside the
transactions and are compared by hash; no foreign byte is overwritten.
"""

import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.core.engine.commit import CommitIntent, MechanicalUpdate
from my_harness.core.engine.context import relative_path
from my_harness.core.engine.contracts import context_snapshot, freeze
from my_harness.core.engine.document_ops import preview_edit, read_text, text_hash
from my_harness.core.engine.document_text import work_language
from my_harness.core.engine.documents import (
    BLOCK_REASON, blocks, budget_warnings, decision_index, layout, managed_bodies, replace_block, require_layout,
    validation_counts,
)
from my_harness.core.engine.evidence import matches
from my_harness.core.engine.phases import document_hashes
from my_harness.core.engine.serialization import load_history, restore_context
from my_harness.storage import run_projection
from my_harness.storage.managed import Conflict, _job
from my_harness.storage.metrics import phase_consumption
from my_harness.storage.models import (
    ManagedAttemptRow as AttemptRow, ManagedCommitRow as Commit, ManagedJobRow as Job, ManagedRunRow as Run,
    PhaseAuthorizationRow as Authorization, PhaseDefinitionRow as Definition, PhaseOperationRow as Operation,
    PhaseRow as Phase, RunProjectionCycleRow as Cycle, RunProjectionRow as Projection,
)
from my_harness.storage.permissions import actor
from my_harness.storage.phases import (
    PhaseRepository, _event, _latest, _open, _operation, _questions, expected_documents,
)
from my_harness.i18n import tr

DOCUMENT_KINDS = ('document_export', 'transition', 'document_edit', 'close')


# --- SQLite projections ------------------------------------------------------------------------


def _latest_run(session, root, code, task):
    return session.execute(select(Run.id, Run.status, Run.revisions).where(
        Run.root == root, Run.phase_id == code, Run.task_id == task, Run.purpose == 'task')
        .order_by(Run.created_at.desc(), Run.id).limit(1)).first()


def _commit_of(session, root, code, task):
    return session.scalar(select(Commit.commit_sha).join(Run, Run.id == Commit.run_id).where(
        Run.root == root, Run.phase_id == code, Run.task_id == task, Run.purpose == 'task',
        Commit.status == 'COMMITTED').order_by(Commit.finished_at.desc(), Commit.operation_id).limit(1))


def _result_text(payload_json):
    try:
        payload = json.loads(payload_json)
    except ValueError:
        return None
    return payload['result'] if isinstance(payload, dict) and isinstance(payload.get('result'), str) else None


def _history_facts(session, run_id):
    """Attempts per role, summary of the last executor, verdict and tests of the last cycle, from the history."""
    history = load_history(session.scalar(select(Run.history_json).where(Run.id == run_id)))
    attempts, summary = {}, None
    for attempt in history.attempts:
        attempts[attempt.request.role] = attempts.get(attempt.request.role, 0) + 1
    executed = [a for a in history.attempts if a.request.role == 'executor' and a.result.payload_json]
    if executed:
        summary = _result_text(executed[-1].result.payload_json)
    if not history.cycles:
        return attempts, summary, None, None
    return attempts, summary, history.cycles[-1].verdict, validation_counts(history.cycles[-1].validation)


def _projected_facts(session, run_id):
    """The same from the projection and `managed_attempts` (P010-T011), without decoding the history.

    The history attempts are rows 1..n of `managed_attempts` with the same request and result (`_history`
    requires it); the following ones, without a result, are not in the history yet and do not count."""
    run_projection.require(session, [run_id])
    recorded = (AttemptRow.run_id == run_id, AttemptRow.number <= select(Projection.attempts).where(
        Projection.run_id == run_id).scalar_subquery())
    role = func.json_extract(AttemptRow.request_json, '$.role')
    attempts = dict(session.execute(select(role, func.count()).where(*recorded).group_by(role)
                                    .order_by(func.min(AttemptRow.number))).all())
    payload = func.json_extract(AttemptRow.result_json, '$.payload_json')
    executed = session.scalar(select(payload).where(*recorded, role == 'executor', func.coalesce(payload, '') != '')
                              .order_by(AttemptRow.number.desc()).limit(1))
    summary = _result_text(executed) if executed is not None else None
    last = session.execute(select(Cycle.number, Cycle.verdict).where(Cycle.run_id == run_id)
                           .order_by(Cycle.number.desc()).limit(1)).first()
    if last is None:
        return attempts, summary, None, None
    tests, _ = run_projection.cycle_tests(session, select(Cycle.run_id, Cycle.number).where(
        Cycle.run_id == run_id, Cycle.number == last.number))[(run_id, last.number)]
    return attempts, summary, last.verdict, tests


def _task_view(session, phase, task, *, planned, committing_run_id=None, projected=False):
    run = _latest_run(session, phase.root, phase.code, task)
    attempts, summary, verdict, tests = {}, None, None, None
    if run is not None:
        attempts, summary, verdict, tests = (_projected_facts if projected else _history_facts)(session, run.id)
    committing = run is not None and run.id == committing_run_id
    return {'task_id': task, 'planned': planned, 'status': 'COMMITTED' if committing else (run.status if run else None),
            'verdict': verdict, 'commit': _commit_of(session, phase.root, phase.code, task), 'committing': committing,
            'summary': summary, 'tests': tests, 'attempts': attempts,
            'revisions': run.revisions if run is not None else None}


def state_snapshot(session, phase, committing_run_id=None, *, projected=False) -> dict:
    """STATE/NEXT_STEPS blocks: phase, planned and added tasks, questions and last check.

    The engine (commit, transition, export intent) reads the history; `projected` is only used by the export
    preview (P010-T011), whose result the confirmed submission compares with the history's."""
    tasks = [_task_view(session, phase, task, planned=True, committing_run_id=committing_run_id, projected=projected)
             for task in phase.definition['tasks']]
    extra = session.execute(select(Run.task_id).where(
        Run.root == phase.root, Run.phase_id == phase.code, Run.purpose == 'task',
        Run.task_id.notin_(phase.definition['tasks'] or [''])).group_by(Run.task_id)
        .order_by(Run.task_id)).scalars().all()
    tasks += [_task_view(session, phase, task, planned=False, committing_run_id=committing_run_id,
                         projected=projected) for task in extra]
    check = _latest(session, phase.id, 'check')
    return {'phase': {'code': phase.code, 'status': phase.status, 'objective': phase.definition['objective']},
            'tasks': tasks, 'open_questions': [q.text for q in _open(_questions(session, phase.id))],
            'latest_check': None if check is None else {'status': check.status,
                                                         'reasons': (check.result or {}).get('reasons') or []}}


def phases_snapshot(session, root) -> dict:
    rows = session.scalars(select(Phase).where(Phase.root == root).order_by(Phase.created_at, Phase.id)).all()
    result = {row.code: {'status': row.status, 'tag': row.definition.get('tag')} for row in rows}
    for row in rows:
        close = _latest(session, row.id, 'close')
        if close and close.result and close.result.get('archive'):
            archive = close.result['archive']
            result[row.code]['archive'] = archive.split('/archive/', 1)[-1]
            result[row.code]['archive'] = 'archive/' + result[row.code]['archive'].rstrip('/') + '/'
    return result


def summary_snapshot(session, phase) -> dict:
    state = state_snapshot(session, phase)
    questions = [{'text': q.text, 'status': q.status, 'answer': q.answer['text'] if q.answer else None}
                 for q in _questions(session, phase.id)]
    definitions = session.scalars(select(Definition).where(Definition.phase_id == phase.id)
                                  .order_by(Definition.number)).all()
    definition = phase.definition
    return {'phase': {'code': phase.code, 'status': phase.status, 'objective': definition['objective'],
                      'exit_criteria': definition['exit_criteria'], 'tag': definition.get('tag'),
                      'definition_number': phase.definition_number},
            'tasks': [task for task in state['tasks'] if task['planned']],
            'extra_tasks': [task for task in state['tasks'] if not task['planned']],
            'questions': questions,
            'definitions': [{'number': row.number, 'origin': row.origin, 'reason': row.reason} for row in definitions],
            'consumption': phase_consumption(session, phase.root, phase.code)}


def latest_phase(session, root):
    return session.scalar(select(Phase).where(Phase.root == root)
                          .order_by(Phase.created_at.desc(), Phase.id.desc()).limit(1))


# --- pending documentary intents --------------------------------------------------------------


def unresolved(session, root, kinds=DOCUMENT_KINDS) -> bool:
    """An uncertain intent keeps its authority until reconciliation; no mutation hides it."""
    rows = session.scalars(select(Operation).join(Phase, Phase.id == Operation.phase_id).where(
        Phase.root == root, Operation.kind.in_(kinds), Operation.status.in_(('QUEUED', 'INTENT', 'INTERRUPTED')))).all()
    return any(op.request.get('commit_intent') for op in rows)


def pending(session, phase, kind):
    rows = session.scalars(select(Operation).where(Operation.phase_id == phase.id, Operation.kind == kind,
                          Operation.status == 'INTERRUPTED', Operation.finished_at.is_not(None))
                          .order_by(Operation.created_at.desc(), Operation.id)).all()
    return next((op for op in rows if op.request.get('commit_intent')), None)


def record_operation_intent(managed, session, run, intent, kind, matches):
    op, phase = _operation(session, run)
    if (op.kind != kind or op.status != 'QUEUED' or intent.operation_id != op.id or intent.run_id != run.id
            or not matches(session, phase)):
        raise Conflict('Intent must match its exact reviewed preview and SQLite authority')
    op.request = {**op.request, 'commit_intent': intent.to_json()}
    op.status = 'INTENT'
    _event(managed, session, phase, f'{kind}_intent', {
        'operation_id': op.id, 'expected_commit': intent.expected_commit, 'expected_tree': intent.expected_tree})


def verify_committed(op, outcome):
    intent = CommitIntent.from_json(op.request['commit_intent'])
    if outcome['commit'] != intent.expected_commit or outcome['tree'] != intent.expected_tree:
        raise Conflict('Result differs from its sealed intent')


def observed_documents(run, shown):
    context = restore_context(run.context_json)
    expected = {doc['path']: doc['after_sha256'] for doc in shown['documents']}
    if document_hashes(context, list(expected)) != expected:
        raise Conflict(tr('documents.documents_changed_after_commit'))
    return context


def abort_operation(managed, session, run, status, reason, kind):
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        return
    op.status, op.result, op.finished_at = status, {'reason': reason}, managed._now()
    _event(managed, session, phase, f'{kind}_aborted', {'operation_id': op.id, 'status': status, 'reason': reason})


# --- task commits: regenerated blocks and adoption ---------------------------------------------


def task_commit_updates(managed, context, run_id, history):
    """Blocks regenerated over the reviewed content; reviewed documents only admit the block (reconciliation)."""
    target = require_layout(context)
    with Session(managed.engine) as session:
        run = session.get(Run, run_id)
        phase = session.scalar(select(Phase).where(Phase.root == run.root, Phase.code == run.phase_id))
        if phase is None:
            return (), frozenset()
        snap = state_snapshot(session, phase, committing_run_id=run_id)
        phases = phases_snapshot(session, run.root)
    texts = {path: read_text(context, path) for path in target.phase_documents}
    bodies = managed_bodies(target, snap, phases, texts, work_language(context))
    updates = []
    for path, (name, body) in bodies.items():
        if texts.get(path) is None:
            continue
        new = replace_block(texts[path], body, name)
        blocks(new)
        if new != texts[path]:
            updates.append(MechanicalUpdate(path, new, BLOCK_REASON))
    reviewed = set(history.acceptance.evidence.changed_paths) if history.acceptance is not None else set()
    return tuple(updates), frozenset(update.path for update in updates if update.path in reviewed)


def block_adoption(context, intent, writer) -> dict:
    """Only blocks over unreviewed documents: their prose is the base's, adopted or not."""
    adopt = {}
    for update in intent.mechanical:
        if update.reason != BLOCK_REASON or update.path in intent.reviewed_paths:
            continue
        blob = writer.read_blob(context, intent.base_revision, update.path)
        adopt[update.path] = [None if blob is None else hashlib.sha256(blob).hexdigest(), text_hash(update.content)]
    return adopt


def adopt_blocks(managed, session, run, adopt, commit):
    """In the transaction of the COMMITTED result: the adopted base advances only from its previous hash."""
    if not adopt:
        return
    phase = session.scalar(select(Phase).where(Phase.root == run.root, Phase.code == run.phase_id))
    if phase is None:
        return
    documents, changed = dict(phase.documents), {}
    for path, (before, after) in sorted(adopt.items()):
        if before is not None and documents.get(path) == before:
            documents[path] = changed[path] = after
    if changed:
        phase.documents = documents
        _event(managed, session, phase, 'managed_blocks_adopted', {'run_id': run.id, 'commit': commit,
                                                                  'documents': changed})


# --- confirmed documentary editing ----------------------------------------------------------------

TREE_LIMIT = 2000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# The viewer only links checkout images served by the API (H6.2 E3); it never points outside.
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
               '.webp': 'image/webp', '.avif': 'image/avif', '.svg': 'image/svg+xml'}


def _edit_phase(session, context, *, resume=False):
    root = str(context.root)
    from my_harness.storage.knowledge_exchange import require_documentary_lane
    require_documentary_lane(session, root)
    phase = latest_phase(session, root)
    if phase is None:
        raise Conflict(tr('documents.create_bootstrap_phase_before'))
    if PhaseRepository._root_pending(session, root) or phase.status in ('CHECKING', 'CLOSING'):
        raise Conflict(tr('documents.checkout_has_unfinished_work'))
    if not resume and unresolved(session, root):
        raise Conflict(tr('managed.document_intent_awaits_reconciliation'))
    from my_harness.storage.bootstrap import unresolved as bootstrap_unresolved
    if bootstrap_unresolved(session, root):
        raise Conflict(tr('managed.bootstrap_awaits_completion_explicit'))
    if session.scalar(select(Authorization.id).where(Authorization.phase_id == phase.id,
                      Authorization.kind == 'batch', Authorization.status == 'ACTIVE')):
        raise Conflict(tr('documents.revoke_active_batch_before'))
    return phase


class DocumentsRepository:
    def __init__(self, managed):
        self.managed = managed

    def status(self, context, git=None) -> dict:
        target = require_layout(context)
        root = str(context.root)
        with Session(self.managed.engine) as session:
            phase = latest_phase(session, root)
            # P010-T005: after closing, the reference includes what the closure and the confirmed edits renewed.
            baseline = expected_documents(session, phase) if phase is not None else {}
            phase_view = None if phase is None else {'id': phase.id, 'code': phase.code, 'status': phase.status}
            open_intent = unresolved(session, root)
        paths = [*target.product_documents, *target.phase_documents]
        documents, texts = [], {}
        for path in paths:
            item = {'path': path, 'kind': 'phase' if path in target.phase_documents else 'product',
                    'exists': False, 'sha256': None, 'adopted_sha256': baseline.get(path),
                    'drift': False, 'blocks': [], 'error': None}
            try:
                text = read_text(context, path)
                if text is not None:
                    texts[path] = text
                    item.update(exists=True, sha256=text_hash(text), blocks=sorted(blocks(text)))
            except (ValueError, OSError, UnicodeError) as exc:
                item['error'] = str(exc)
            item['drift'] = path in baseline and baseline[path] != item['sha256']
            documents.append(item)
        uncommitted, git_error = None, None
        if git is not None:
            try:
                evidence = git.capture(context)
                uncommitted = [{'path': path, 'editable': target.editable(path)} for path in evidence.changed_paths]
            except (RuntimeError, ValueError, OSError) as exc:
                git_error = f'{type(exc).__name__}: {exc}'
        archive = []
        folder = context.path(target.archive_dir)
        if folder.is_dir() and not folder.is_symlink():
            for phase_dir in sorted(item for item in folder.iterdir() if item.is_dir() and not item.is_symlink()):
                archive.append({'path': f'{target.archive_dir}/{phase_dir.name}',
                                'files': sorted(item.name for item in phase_dir.iterdir() if item.is_file())})
        try:
            decisions = decision_index(texts[target.decisions] if target.decisions in texts
                                       else read_text(context, target.decisions))
        except (ValueError, OSError, UnicodeError):
            decisions = []
        # D088: the API schema keeps `file`, `date` and `phase` until P008-T006.
        name = PurePosixPath(target.decisions).name
        decisions = [{**entry, 'file': name, 'date': None, 'phase': None} for entry in decisions]
        return {'layout': context.documents, 'phase': phase_view, 'documents': documents,
                'folders': [{'path': path, 'exists': context.path(path).is_dir()} for path in target.folders],
                'uncommitted': uncommitted, 'warnings': budget_warnings(target, texts), 'decisions': decisions,
                'archive': archive, 'unresolved_intent': open_intent, 'git_error': git_error}

    def read(self, context, path) -> dict:
        target = require_layout(context)
        archived = target.archived(path) and path.endswith('.md')
        if not (target.editable(path) or archived):
            raise LookupError(tr('documents.unknown_project_document'))
        text = read_text(context, path)
        if text is None:
            raise LookupError(tr('documents.document_does_not_exist'))
        return {'path': path, 'content': text, 'sha256': text_hash(text), 'editable': target.editable(path),
                'archived': archived, 'blocks': sorted(blocks(text))}

    def tree(self, context) -> dict:
        """Markdown of the README and the documentation directory, without following links or entering hidden ones."""
        target = require_layout(context)
        files, skipped = [], []

        def entry(path, size):
            kind = ('phase' if path in target.phase_documents else 'product' if path in target.product_documents
                    else 'archive' if target.archived(path) else 'other')
            return {'path': path, 'kind': kind, 'editable': target.editable(path), 'archived': target.archived(path),
                    'bytes': size}

        def walk(relative):
            try:
                items = sorted(os.scandir(context.root / relative), key=lambda item: item.name)
            except OSError:
                skipped.append(relative)
                return
            for item in items:
                path = f'{relative}/{item.name}'
                if item.name.startswith('.'):
                    continue
                if item.is_symlink():
                    skipped.append(path)
                elif item.is_dir(follow_symlinks=False):
                    walk(path)
                elif item.name.endswith('.md'):
                    if item.is_file(follow_symlinks=False):
                        files.append(entry(path, item.stat(follow_symlinks=False).st_size))
                    else:
                        skipped.append(path)

        readme = context.root / target.readme
        if readme.is_symlink():
            skipped.append(target.readme)
        elif readme.is_file():
            files.append(entry(target.readme, readme.stat().st_size))
        docs = context.root / target.docs
        if docs.is_symlink():
            skipped.append(target.docs)
        elif docs.is_dir():
            walk(target.docs)
        truncated = len(files) > TREE_LIMIT
        return {'docs': target.docs, 'files': files[:TREE_LIMIT], 'truncated': truncated, 'skipped': skipped[:100]}

    def image(self, context, path) -> tuple[bytes, str]:
        """Checkout image for the viewer: regular, no links, outside hidden and sensitive paths."""
        require_layout(context)
        parts = relative_path(path).parts
        kind = IMAGE_TYPES.get(PurePosixPath(path).suffix.lower())
        if (not parts or kind is None or any(part.startswith('.') for part in parts)
                or matches('/'.join(parts), context.profile.sensitive_paths)):
            raise LookupError(tr('documents.unknown_repository_image'))
        descriptors = []
        try:
            directory = os.open(context.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(directory)
            for part in parts[:-1]:
                directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                descriptors.append(directory)
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise LookupError(tr('documents.repository_images_regular_unshared'))
            if info.st_size > MAX_IMAGE_BYTES:
                raise ValueError(tr('documents.image_exceeds_mib', limit=MAX_IMAGE_BYTES // (1024 * 1024)))
            with os.fdopen(os.dup(descriptor), 'rb') as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
        except FileNotFoundError as exc:
            raise LookupError(tr('documents.image_does_not_exist')) from exc
        except (NotADirectoryError, IsADirectoryError) as exc:
            raise LookupError(tr('documents.unknown_repository_image')) from exc
        except OSError as exc:  # ELOOP: a component is a link
            raise LookupError(tr('documents.image_not_readable_without', strerror=exc.strerror)) from exc
        finally:
            for item in reversed(descriptors):
                os.close(item)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError(tr('documents.image_exceeds_mib', limit=MAX_IMAGE_BYTES // (1024 * 1024)))
        return data, kind

    def preview(self, context, git, *, source, changes, regenerate_blocks=False):
        with Session(self.managed.engine) as session:
            phase = _edit_phase(session, context, resume=True)
            stored = pending(session, phase, 'document_edit')
            if stored is not None:
                return {**stored.request['preview'], 'resume_operation_id': stored.id}
        try:
            shown = preview_edit(context, git, source=source, changes=changes, regenerate_blocks=regenerate_blocks)
        except (ValueError, OSError, UnicodeError, RuntimeError) as exc:  # RuntimeError: Git capture/sealing
            raise Conflict(str(exc)) from exc
        return {**shown, 'resume_operation_id': None}

    def submit(self, context, *, key, versions, preview_sha256, reason, confirmed, git, source, changes,
               resume_operation_id=None, regenerate_blocks=False):
        if confirmed is not True or not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('export.explicit_confirmation_exact_diff'))
        marker = freeze({'action': 'document_edit', 'root': str(context.root), 'preview_sha256': preview_sha256,
                         'reason': reason, 'confirmed': confirmed, 'resume_operation_id': resume_operation_id})
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
        try:
            shown = self.preview(context, git, source=source, changes=changes, regenerate_blocks=regenerate_blocks)
        except Conflict:
            with Session(self.managed.engine) as session:
                existing = self.managed._existing(session, key, marker)
                if existing:
                    return _job(existing)
            raise
        if shown['preview_sha256'] != preview_sha256 or shown['resume_operation_id'] != resume_operation_id:
            raise Conflict(tr('export.preview_changed_review_exact'))
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
            phase = _edit_phase(session, context, resume=resume_operation_id is not None)
            if resume_operation_id is not None:
                op = pending(session, phase, 'document_edit')
                if op is None or op.id != resume_operation_id:
                    raise Conflict(tr('documents.exact_interrupted_edit_intent'))
                job = _resume_job(self.managed, session, op, context, versions, key, marker, assessment, 'document_edit')
            else:
                job = self.managed._queue_new_run(session, assessment, context, versions, f'{phase.code}-DOCS',
                                                  phase.code, key, marker, purpose='document_edit')
                saved = {k: v for k, v in shown.items() if k != 'resume_operation_id'}
                op = Operation(id=str(uuid4()), phase_id=phase.id, kind='document_edit', run_id=job.run_id,
                               status='QUEUED', previous_status=phase.status, created_at=self.managed._now(),
                               request={'preview': saved, 'actor': actor(), 'reason': reason})
                session.add(op)
                origin = (saved.get('phase_plan') or {}).get('origin')
                if origin:
                    from my_harness.storage.planning import PlanningRepository
                    PlanningRepository(self.managed).mark_plan(session, origin, job.run_id, job.id,
                                                               decision='phase_plan')
            _event(self.managed, session, phase, 'document_edit_queued', {
                'operation_id': op.id, 'run_id': job.run_id, 'job_id': job.id, 'preview_sha256': preview_sha256,
                'paths': [doc['path'] for doc in shown['documents']], 'actor': actor(), 'reason': reason})
            return job

    def request(self, run_id):
        with Session(self.managed.engine) as session:
            run = session.get(Run, run_id)
            op, _ = _operation(session, run)
            if op.kind != 'document_edit' or op.status != 'QUEUED':
                raise Conflict('Document edit requires its queued operation')
            return {**op.request, 'operation_id': op.id}


def _resume_job(managed, session, op, context, versions, key, marker, assessment, stage):
    from my_harness.core.engine.documents import DOCUMENT_LAYOUT
    run = session.get(Run, op.run_id)
    frozen_versions = json.loads(run.versions_json)
    comparable = dict(frozen_versions)
    if (op.kind == 'transition' and op.request.get('commit_intent')
            and comparable.get('document_layout') in ('d088-1', 'd088-2', 'd088-3')
            and versions.get('document_layout') == DOCUMENT_LAYOUT):
        comparable['document_layout'] = DOCUMENT_LAYOUT  # only the already sealed writer, never agents or new bytes
    if run.context_json != context_snapshot(context) or comparable != versions:
        raise Conflict(tr('documents.frozen_context_versions_changed'))
    job = Job(idempotency_key=key, run_id=run.id, request_json=marker, status='QUEUED',
              created_at=managed._now(), activation_id=managed._admit(session, assessment),
              language_context=managed._language(session, run.id))
    session.add(job)
    session.flush()
    run.status, run.stage = 'QUEUED', stage
    managed._event(session, run, 'job_queued', {'job_id': job.id, 'action': stage})
    op.status, op.finished_at = 'QUEUED', None
    return _job(job)


def record_intent(managed, session, run, intent):
    def matches(session, phase):
        op, _ = _operation(session, run)
        data = op.request['preview'].get('phase_plan')
        if data is None:
            return True
        from my_harness.storage.phase_plan import verify
        return verify(session, phase, data)
    record_operation_intent(managed, session, run, intent, 'document_edit', matches)


def settle(managed, session, run, outcome):
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        raise Conflict('Document edit already settled')
    if outcome['status'] == 'COMMITTED':
        verify_committed(op, outcome)
        shown = op.request['preview']
        observed_documents(run, shown)
        documents, adopted = dict(phase.documents), {}
        for doc in shown['documents']:
            if doc['path'] in documents and documents[doc['path']] == doc['before_sha256']:
                documents[doc['path']] = adopted[doc['path']] = doc['after_sha256']
        if adopted:
            phase.documents = documents
        if shown.get('phase_plan'):
            from my_harness.storage.phase_plan import adopt
            adopt(managed, session, phase, op, shown, documents, outcome)
        outcome = {**outcome, 'adopted': adopted}
        run.status, run.stage = 'COMMITTED', 'committed'
    op.status, op.result, op.finished_at = outcome['status'], outcome, managed._now()
    _event(managed, session, phase, 'documents_edited' if outcome['status'] == 'COMMITTED' else 'document_edit_invalidated',
           {'operation_id': op.id, **outcome})


def abort(managed, session, run, status, reason):
    abort_operation(managed, session, run, status, reason, 'document_edit')
