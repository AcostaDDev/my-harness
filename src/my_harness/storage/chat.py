"""H4.1: SQLite authority of the contextual chat, serialized with the managed queue.

The conversation lives separately from the execution flow. Each message freezes, in the transaction that
queues its turn, the message and the explicit context: project, phase, documents (bounded content
with hash) and selected run evidence, plus the previous turns. The turn is a
`chat` run with a `chat_snapshot` job over HEAD, without the checkout lock (E5). It reuses supervisor,
mode guard, quarantine and attempt persistence. Old `chat_turn` jobs keep
the lock. A crash leaves the turn with an unknown result and it is never retried.

Proposals execute nothing. Accepting one requires explicit confirmation, the observed version and
the exact hash shown, and queues a normal task (planner, executor, review and commit)
linked to the proposal. The chat grants no permissions and sets no contracts.
"""

import hashlib
import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.core.engine.chat import TASK_ID, digest, task_text
from my_harness.core.engine.chat_commands import parse, proposal as command_proposal
from my_harness.adapters.chat_snapshot import HeadSnapshot
from my_harness.core.engine.contracts import context_snapshot, freeze
from my_harness.core.engine.serialization import load_history
from my_harness.storage.managed import Conflict, _job, existing_creation
from my_harness.storage.models import (
    ChatConversationRow as Conversation, ChatProposalRow as Proposal, ChatTurnRow as Turn,
    ManagedCommitRow as Commit, ManagedJobRow as Job, ManagedRunRow as Run, PhaseRow as Phase,
)
from my_harness.storage.permissions import actor
from my_harness.i18n import tr

MAX_DOCUMENTS = 8
MAX_DOCUMENT_BYTES = 64 * 1024
MAX_RUNS = 10
MAX_PREVIOUS_TURNS = 10
MAX_MESSAGE = 20_000


def read_documents(context, paths) -> list[dict]:
    """Disk read outside a transaction: bounded content, with hash and size of the complete file."""
    result = []
    for path in paths:
        item = context.path(path)
        if item.is_symlink() or (item.exists() and not item.is_file()):
            raise ValueError(tr('chat.chat_document_regular_file', path=path))
        if not item.exists():
            result.append({'path': path, 'sha256': None, 'size': None, 'content': None, 'truncated': False})
            continue
        data = item.read_bytes()
        result.append({'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                       'content': data[:MAX_DOCUMENT_BYTES].decode('utf-8', errors='replace'),
                       'truncated': len(data) > MAX_DOCUMENT_BYTES})
    return result


def _distinct(values, name, limit):
    if (not isinstance(values, list) or len(values) > limit or len(set(values)) != len(values)
            or not all(isinstance(v, str) and v.strip() for v in values)):
        raise ValueError(tr('chat.chat_list_most_distinct', name=name, limit=limit))
    return values


def _run_evidence(session, root, run_id):
    run = session.get(Run, run_id)
    if run is None or run.root != root:
        raise LookupError(tr('chat.selected_run_does_not'))
    history = load_history(run.history_json)
    task = json.loads(history.task_json) if history.task_json else None
    review = history.cycles[-1].review_json if history.cycles else None
    commit = session.scalar(select(Commit.commit_sha).where(Commit.run_id == run.id, Commit.status == 'COMMITTED'))
    return {'run_id': run.id, 'purpose': run.purpose, 'task_id': run.task_id, 'phase_id': run.phase_id,
            'status': run.status, 'contract': None if task is None else {
                key: task.get(key) for key in ('title', 'objective', 'allowed_paths', 'acceptance_criteria',
                                               'validation_commands')},
            'stop': None if history.stop is None else {'stage': history.stop.stage, 'reason': history.stop.reason},
            'review': None if review is None else json.loads(review),
            'acceptance': None if history.acceptance is None else {
                'eligible': history.acceptance.eligible, 'changed_paths': list(history.acceptance.evidence.changed_paths)},
            'commit': commit}


def _phase_context(session, phase):
    from my_harness.storage.phases import _open, _questions, committed_tasks
    return {'id': phase.id, 'code': phase.code, 'status': phase.status, 'definition': phase.definition,
            'definition_number': phase.definition_number, 'baseline_documents': phase.documents,
            'tasks': committed_tasks(session, phase),
            'open_questions': [q.text for q in _open(_questions(session, phase.id))]}


def _touch(managed, conversation):
    conversation.version += 1
    conversation.updated_at = managed._now()


def _turn(session, run):
    turn = session.scalar(select(Turn).where(Turn.run_id == run.id))
    if turn is None:
        raise Conflict('Chat run without its turn')
    return turn, session.get(Conversation, turn.conversation_id)


def settle(managed, session, run, outcome):
    """Turn result, atomic with the end of the job (called from `finish`)."""
    turn, conversation = _turn(session, run)
    if turn.status != 'QUEUED':
        raise Conflict('Chat turn already settled')
    attempts = load_history(run.history_json).attempts
    turn.status, turn.finished_at = outcome['status'], managed._now()
    turn.result = {**outcome, 'attempt_id': attempts[-1].request.id if attempts else None}
    if outcome['status'] == 'ANSWERED':
        number = session.scalar(select(func.max(Proposal.number)).where(
            Proposal.conversation_id == conversation.id)) or 0
        for item in outcome['result']['proposals']:
            number += 1
            session.add(Proposal(id=str(uuid4()), conversation_id=conversation.id, turn_id=turn.id, number=number,
                                 status='PROPOSED', proposal=item, proposal_sha256=digest(item), run_id=None,
                                 decision=None, version=1, created_at=turn.finished_at))
    _touch(managed, conversation)


def abort(managed, session, run, status, reason):
    """Writer confirmed stopped (unknown result) or refused job: never retried on its own."""
    turn, conversation = _turn(session, run)
    if turn.status != 'QUEUED':
        return
    turn.status = 'UNKNOWN' if status == 'INTERRUPTED' else 'REFUSED'
    turn.finished_at = managed._now()
    turn.result = {'status': turn.status, 'reasons': [reason], 'result': None, 'checkout': None}
    _touch(managed, conversation)


class ChatRepository:
    def __init__(self, managed):
        self.managed = managed

    def _conversation(self, session, conversation_id, expected=None, context=None):
        row = session.get(Conversation, conversation_id)
        if row is None:
            raise LookupError(tr('chat.unknown_chat_conversation'))
        if context is not None and row.root != str(context.root):
            raise LookupError(tr('planning.conversation_belongs_another_checkout'))
        if expected is not None and (type(expected) is not int or row.version != expected):
            raise Conflict(tr('planning.conversation_changed_reload_before'))
        return row

    # --- reads ------------------------------------------------------------------------

    def root(self, conversation_id):
        with Session(self.managed.engine) as session:
            return self._conversation(session, conversation_id).root

    def list(self, root):
        with Session(self.managed.engine) as session:
            rows = session.scalars(select(Conversation).where(Conversation.root == root)
                                   .order_by(Conversation.created_at, Conversation.id)).all()
            result = []
            for row in rows:
                phase = session.get(Phase, row.phase_id) if row.phase_id else None
                turns = session.scalar(select(func.count()).select_from(Turn).where(Turn.conversation_id == row.id))
                result.append({'id': row.id, 'title': row.title, 'phase_id': row.phase_id,
                               'phase_code': phase.code if phase else None, 'task_run_id': row.task_run_id, 'turns': turns, 'version': row.version,
                               'created_at': row.created_at, 'updated_at': row.updated_at})
            return result

    def get(self, conversation_id):
        """Projection with the live state of the linked runs and actions computed by the server."""
        with Session(self.managed.engine) as session:
            row = self._conversation(session, conversation_id)
            phase = session.get(Phase, row.phase_id) if row.phase_id else None
            turns = session.scalars(select(Turn).where(Turn.conversation_id == row.id).order_by(Turn.number)).all()
            proposals = session.scalars(select(Proposal).where(Proposal.conversation_id == row.id)
                                        .order_by(Proposal.number)).all()
            numbers = {turn.id: turn.number for turn in turns}
            turn_views = []
            for turn in turns:
                context = turn.request['context']
                turn_views.append({
                    'id': turn.id, 'number': turn.number, 'status': turn.status, 'run_id': turn.run_id,
                    'run_status': session.get(Run, turn.run_id).status, 'message': turn.message,
                    'documents': [{key: item[key] for key in ('path', 'sha256', 'size', 'truncated')}
                                  for item in context['documents']],
                    'run_ids': [item['run_id'] for item in context['runs']],
                    'phase_code': context['phase']['code'] if context['phase'] else None,
                    'previous_turns': len(context['previous_turns']), 'head': context.get('head'),
                    'command': context.get('command'),
                    'context_sha256': turn.request['context_sha256'], 'request_sha256': turn.request_sha256,
                    'result': turn.result, 'actor': turn.actor, 'created_at': turn.created_at,
                    'finished_at': turn.finished_at})
            proposal_views = []
            for item in proposals:
                run = session.get(Run, item.run_id) if item.run_id else None
                commit = None if run is None else session.scalar(select(Commit.commit_sha).where(
                    Commit.run_id == run.id, Commit.status == 'COMMITTED'))
                proposal_views.append({
                    'id': item.id, 'number': item.number, 'turn_id': item.turn_id, 'turn_number': numbers[item.turn_id],
                    'status': item.status, 'proposal': item.proposal, 'proposal_sha256': item.proposal_sha256,
                    'run_id': item.run_id, 'run': None if run is None else {
                        'task_id': run.task_id, 'phase_id': run.phase_id, 'status': run.status, 'commit': commit},
                    'decision': item.decision, 'version': item.version, 'created_at': item.created_at,
                    'actions': ['accept', 'dismiss'] if item.status == 'PROPOSED' else []})
            pending = any(turn.status == 'QUEUED' for turn in turns)
            return {'id': row.id, 'root': row.root, 'title': row.title, 'task_run_id': row.task_run_id,
                    'phase': None if phase is None else {'id': phase.id, 'code': phase.code, 'status': phase.status},
                    'actor': row.actor, 'version': row.version, 'created_at': row.created_at,
                    'updated_at': row.updated_at, 'turns': turn_views, 'proposals': proposal_views,
                    'actions': [] if pending else ['message']}

    def snapshot(self, run_id):
        """Frozen request for the turn's job."""
        with Session(self.managed.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise LookupError(tr('managed.unknown_managed_run'))
            turn, _ = _turn(session, run)
            return {'turn_id': turn.id, 'message': turn.message, 'context': turn.request['context'],
                    'context_sha256': turn.request['context_sha256']}

    # --- conversation and turns --------------------------------------------------------

    def create(self, context, *, title, phase_id=None, task_run_id=None, key=None):
        """`key` (API): a retry with the same request returns the same conversation, without another empty one."""
        request = digest({'action': 'chat_conversation', 'root': str(context.root), 'title': title,
                          'phase_id': phase_id, 'task_run_id': task_run_id})
        if key is not None:
            with Session(self.managed.engine) as session:
                if found := existing_creation(session, Conversation, key, request):
                    return found
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError(tr('planning.conversation_title_contain_1'))
        with self.managed._write() as session:
            if key is not None and (found := existing_creation(session, Conversation, key, request)):
                return found
            if phase_id is not None:
                phase = session.get(Phase, phase_id)
                if phase is None or phase.root != str(context.root):
                    raise LookupError(tr('planning.unknown_phase_checkout'))
            if task_run_id is not None:
                task = session.get(Run, task_run_id)
                if task is None or task.root != str(context.root) or task.purpose != 'task':
                    raise LookupError(tr('chat.unknown_task_run_checkout'))
                if phase_id and phase.code != task.phase_id:
                    raise ValueError(tr('chat.task_context_belong_selected'))
                if phase_id is None:
                    phase_id = session.scalar(select(Phase.id).where(
                        Phase.root == str(context.root), Phase.code == task.phase_id))
            now = self.managed._now()
            row = Conversation(id=str(uuid4()), root=str(context.root), title=title.strip(), phase_id=phase_id,
                               actor=actor(), task_run_id=task_run_id, version=0, created_at=now, updated_at=now,
                               idempotency_key=key, request_sha256=request if key is not None else None)
            session.add(row)
            return row.id

    def submit_message(self, context, conversation_id, expected, *, key, versions, text, documents=None, run_ids=None, reader=None):
        """Freezes message and explicit context in the transaction that queues the turn."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE:
            raise ValueError(tr('chat.chat_message_contain_1', max_message=MAX_MESSAGE))
        command = parse(text)
        if command and command['name'] != 'tarea':
            raise ValueError(tr('chat.use_deterministic_command_preview'))
        run_ids = _distinct([] if run_ids is None else run_ids, 'runs', MAX_RUNS)
        request = freeze({'action': 'chat_command' if command else 'chat_snapshot', 'conversation_id': conversation_id, 'expected_version': expected,
                          'text': text, 'documents': documents, 'run_ids': run_ids})
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            row = self._conversation(session, conversation_id, context=context)
            if row.task_run_id and row.task_run_id not in run_ids:
                run_ids = _distinct([row.task_run_id, *run_ids], 'runs', MAX_RUNS)
            phase = session.get(Phase, row.phase_id) if row.phase_id else None
            selected = documents if documents is not None else (
                list(phase.definition['documents']) if phase else [context.state_file, context.next_steps_file])
        reader = reader or HeadSnapshot(context.root)
        head = None if command else reader.head()
        observed = [] if command else reader.documents(context, head, _distinct(selected, 'documents', MAX_DOCUMENTS))
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            conversation = self._conversation(session, conversation_id, expected, context)
            if session.scalar(select(Turn.id).where(Turn.conversation_id == conversation.id, Turn.status == 'QUEUED')):
                raise Conflict(tr('planning.previous_turn_conversation_still'))
            phase = session.get(Phase, conversation.phase_id) if conversation.phase_id else None
            previous = session.scalars(select(Turn).where(Turn.conversation_id == conversation.id)
                                       .order_by(Turn.number.desc()).limit(MAX_PREVIOUS_TURNS)).all()
            history = []
            for turn in reversed(previous):
                answered = turn.status == 'ANSWERED'
                history.append({'number': turn.number, 'status': turn.status, 'message': turn.message,
                                'answer': turn.result['result']['answer'] if answered else None,
                                'proposals': [{'number': p.number, 'title': p.proposal['title'], 'status': p.status}
                                              for p in session.scalars(select(Proposal).where(Proposal.turn_id == turn.id)
                                                                       .order_by(Proposal.number))]})
            number = 1 + (session.scalar(select(func.max(Turn.number)).where(
                Turn.conversation_id == conversation.id)) or 0)
            frozen = {'project': {'root': str(context.root), 'profile': context.profile.name,
                                  'state_file': context.state_file, 'next_steps_file': context.next_steps_file},
                      'conversation': {'id': conversation.id, 'title': conversation.title, 'turn': number},
                      'phase': None if phase is None else _phase_context(session, phase),
                      'documents': observed, 'runs': [_run_evidence(session, conversation.root, r) for r in run_ids],
                      'previous_turns': history, 'head': head, 'snapshot_format': 'head-export-1',
                      'command': command,
                      **({'command_result': command_proposal(command['argument'], context.work_language)} if command else {})}
            job = self.managed._queue_new_run(session, assessment, context, versions,
                                              f'CHAT-{conversation.id[:8]}-{number}', phase.code if phase else 'CHAT',
                                              key, request, purpose='chat')
            context_sha256 = digest(frozen)
            session.add(Turn(id=str(uuid4()), conversation_id=conversation.id, number=number, run_id=job.run_id,
                             status='QUEUED', message=text, request={'context': frozen, 'context_sha256': context_sha256},
                             request_sha256=digest({'message': text, 'context_sha256': context_sha256}),
                             result=None, actor=actor(), created_at=self.managed._now()))
            _touch(self.managed, conversation)
            return job

    def command_preview(self, context, conversation_id, expected, text):
        command = parse(text)
        if command is None:
            raise ValueError(tr('chat.expected_slash_command'))
        with Session(self.managed.engine) as session:
            row = self._conversation(session, conversation_id, expected, context)
            phase = session.get(Phase, row.phase_id) if row.phase_id else None
            if phase is None:
                phase = session.scalar(select(Phase).where(Phase.root == row.root)
                                       .order_by(Phase.created_at.desc()).limit(1))
            run = session.get(Run, row.task_run_id) if row.task_run_id else None
            if run is None:
                query = select(Run).where(Run.root == row.root, Run.purpose == 'task')
                if phase:
                    query = query.where(Run.phase_id == phase.code)
                run = session.scalar(query.order_by(Run.created_at.desc()).limit(1))
            result = {**command, 'conversation_version': row.version,
                      'phase_code': phase.code if phase else None,
                      'phase_version': phase.version if phase else None,
                      'run_id': run.id if run else None, 'run_version': run.version if run else None}
            return {**result, 'preview_sha256': digest(result)}

    # --- proposals -------------------------------------------------------------------

    def accept(self, context, conversation_id, proposal_id, expected, *, key, versions, proposal_sha256, task_id,
               phase_id, confirmed):
        """Explicit confirmation → linked normal task; without confirmation nothing is queued."""
        if confirmed is not True:
            raise ValueError(tr('chat.accepting_proposal_requires_explicit'))
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise ValueError(tr('chat.task_id_1_120'))
        if not isinstance(phase_id, str) or not TASK_ID.fullmatch(phase_id):
            raise ValueError(tr('chat.phase_id_1_120'))
        marker = {'kind': 'chat_proposal', 'conversation_id': conversation_id, 'proposal_id': proposal_id,
                  'proposal_sha256': proposal_sha256, 'expected_version': expected, 'task_id': task_id,
                  'phase_id': phase_id}
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            prior = session.scalar(select(Job).where(Job.idempotency_key == key))
            if prior is not None:
                if json.loads(prior.request_json).get('chat_proposal') != marker:
                    raise Conflict(tr('managed.idempotency_key_already_names_2'))
                return _job(prior)
            conversation = self._conversation(session, conversation_id, expected, context)
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.conversation_id != conversation.id:
                raise LookupError(tr('planning.unknown_proposal_conversation'))
            if proposal.status != 'PROPOSED':
                raise Conflict(tr('planning.proposal_already', status=proposal.status.lower()))
            if proposal.proposal_sha256 != proposal_sha256:
                raise Conflict(tr('chat.accept_exact_proposal_shown'))
            turn = session.get(Turn, proposal.turn_id)
            text = task_text(proposal.proposal, task_id, {
                'conversation_id': conversation.id, 'turn_number': turn.number, 'proposal_id': proposal.id,
                'proposal_sha256': proposal.proposal_sha256}, context.work_language or 'en')
            request = freeze({'action': 'start', 'context_json': context_snapshot(context),
                              'versions_json': freeze(versions), 'task_id': task_id, 'phase_id': phase_id,
                              'text': text, 'chat_proposal': marker})
            job = self.managed._queue_new_run(session, assessment, context, versions, task_id, phase_id, key, request)
            proposal.status, proposal.run_id, proposal.version = 'ACCEPTED', job.run_id, proposal.version + 1
            proposal.decision = {'decision': 'accept', 'actor': actor(), 'at': self.managed._now(), 'task_id': task_id,
                                 'phase_id': phase_id, 'job_id': job.id, 'text_sha256': digest(text)}
            _touch(self.managed, conversation)
            return job

    def dismiss(self, conversation_id, proposal_id, expected, *, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('planning.explicit_dismissal_reason_required'))
        with self.managed._write() as session:
            conversation = self._conversation(session, conversation_id, expected)
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.conversation_id != conversation.id:
                raise LookupError(tr('planning.unknown_proposal_conversation'))
            if proposal.status != 'PROPOSED':
                raise Conflict(tr('planning.proposal_already', status=proposal.status.lower()))
            proposal.status, proposal.version = 'DISMISSED', proposal.version + 1
            proposal.decision = {'decision': 'dismiss', 'actor': actor(), 'at': self.managed._now(),
                                 'reason': reason.strip()}
            _touch(self.managed, conversation)
