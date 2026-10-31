"""H6.5: SQLite authority of the definition and phase planning conversations.

Reuses the chat infrastructure (D035): each message freezes, in the transaction that queues its
turn, the message and the explicit context; the turn is a run (`definition` or `phase_planning`) with a job
under the checkout lock, with supervisor, mode guard, quarantine and attempt persistence.
A crash leaves the turn with an unknown result and it is never retried.

Definition: the brief and the drafts of the target folder (with their hash) form the context. The agent
never writes. Applying a confirmed proposal writes the draft with CAS on the hash the
turn read; a user edit in between is a conflict and is not overwritten. User edits
(on disk or through the API) are detected by hash in the next turn. Acceptance is the
preview of the D037 bootstrap with the v2 template (`storage/bootstrap.py`).

Planning: proposes NEXT_STEPS for the active phase without tasks (or the next one in earlier conversations).
Confirming the plan writes the documents and versions the definition; the agent never produces effects.

"""

import json

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import uuid4

from my_harness.core.engine.chat import digest
from my_harness.core.engine.context import IntakeContext, profile_name
from my_harness.core.engine.contracts import context_snapshot, freeze
from my_harness.core.engine.definition import (
    DRAFT_KINDS, MAX_CONTEXT_DRAFT_BYTES, acceptance, allowed_draft, allowed_drafts_view, brief as brief_payload,
    default_documents, definition_layout, text_hash,
)
from my_harness.core.engine.document_ops import read_text
from my_harness.core.engine.document_text import work_language
from my_harness.core.engine.documents import base_section, parse_roadmap, require_layout, skeleton
from my_harness.core.engine.serialization import load_history
from my_harness.storage.chat import MAX_MESSAGE, MAX_PREVIOUS_TURNS, read_documents
from my_harness.storage.managed import Conflict, _job, existing_creation
from my_harness.storage.models import (
    ManagedRunRow as Run, PhaseRow as Phase, PlanningConversationRow as Conversation,
    PlanningProposalRow as Proposal, PlanningTurnRow as Turn, ProjectBootstrapRow as Bootstrap,
)
from my_harness.storage.permissions import actor
from my_harness.storage.onboarding import (
    OnboardingDrafts, identity as onboarding_identity, observation as onboarding_observation,
    read_inventory, turn_context as onboarding_context,
)
from my_harness.i18n import tr

KINDS = ('definition', 'phase_planning', 'onboarding')


def _executable(reader) -> str:
    """Git of the configured reader (the same as the writer's); `git` on the PATH if there is none."""
    return getattr(reader, 'executable', 'git')


def _touch(managed, conversation):
    conversation.version += 1
    conversation.updated_at = managed._now()


def _turn(session, run):
    turn = session.scalar(select(Turn).where(Turn.run_id == run.id))
    if turn is None:
        raise Conflict('Planning run without its turn')
    return turn, session.get(Conversation, turn.conversation_id)


def current_questions(session, conversation) -> tuple[list[dict], list[str]]:
    """Questions and pending items of the last answered turn, with the explicit deferrals."""
    turn = session.scalar(select(Turn).where(Turn.conversation_id == conversation.id, Turn.status == 'ANSWERED')
                          .order_by(Turn.number.desc()).limit(1))
    if turn is None:
        return [], []
    result = turn.result['result']
    return ([{**q, 'deferred': conversation.deferred.get(q['id'])} for q in result['questions']],
            list(result['pending']))


def _bootstrapped(session, root) -> bool:
    return session.scalar(select(Bootstrap.id).where(Bootstrap.root == root)) is not None


def settle(managed, session, run, outcome):
    """Turn result, atomic with the end of the job; the new proposals replace the pending ones."""
    turn, conversation = _turn(session, run)
    if turn.status != 'QUEUED':
        raise Conflict('Planning turn already settled')
    attempts = load_history(run.history_json).attempts
    turn.status, turn.finished_at = outcome['status'], managed._now()
    result = outcome['result']
    stored = result
    if result and 'knowledge' in result:
        from my_harness.core.engine.knowledge import digest as knowledge_digest
        result = {**result, 'knowledge_sha256': knowledge_digest(result['knowledge'])}
        stored = result
    if outcome['status'] == 'ANSWERED' and conversation.kind in DRAFT_KINDS:
        # The complete content lives in each proposal; the turn keeps path, reason and hash.
        stored = {**result, 'drafts': [{'path': d['path'], 'reason': d['reason'], 'content_sha256': text_hash(d['content'])}
                                       for d in result['drafts']]}
    elif outcome['status'] == 'ANSWERED' and result['plan'] is not None:
        stored = {**result, 'plan': {'reason': result['plan']['reason'],
                                     'content_sha256': text_hash(result['plan']['content'])}}
    turn.result = {**outcome, 'result': stored, 'attempt_id': attempts[-1].request.id if attempts else None}
    if outcome['status'] == 'ANSWERED':
        if turn.request['context'].get('capabilities') == 'project-intake-1':
            for older in session.scalars(select(Proposal).where(
                    Proposal.conversation_id == conversation.id, Proposal.kind == 'profile',
                    Proposal.status.in_(('PROPOSED', 'ACCEPTED')))):
                older.status, older.version = 'SUPERSEDED', older.version + 1
                older.decision = {**(older.decision or {}), 'superseded_by_turn': turn.number,
                                  'superseded_at': turn.finished_at}
        if conversation.kind in DRAFT_KINDS:
            bases = {item['path']: item['sha256'] for item in turn.request['context']['drafts']}
            # Only an answered turn «sees» the drafts: a failed one shows the edits again to the next one.
            conversation.known = dict(bases)
            items = [('draft', d['path'], d['content'], d['reason'], bases.get(d['path'])) for d in result['drafts']]
            if result.get('profile') is not None:
                items.append(('profile', None, freeze(result['profile']),
                              result['profile']['candidate']['rationale'], None))
        else:
            plan = result['plan']
            items = [] if plan is None else [('plan', None, plan['content'], plan['reason'], None)]
        number = session.scalar(select(func.max(Proposal.number)).where(
            Proposal.conversation_id == conversation.id)) or 0
        for kind, path, content, reason, base in items:
            older = select(Proposal).where(Proposal.conversation_id == conversation.id, Proposal.kind == kind,
                                           Proposal.status == 'PROPOSED')
            older = older.where(Proposal.path == path) if path is not None else older.where(Proposal.path.is_(None))
            for row in session.scalars(older):
                row.status, row.version = 'SUPERSEDED', row.version + 1
                row.decision = {**(row.decision or {}), 'decision': 'superseded', 'by_turn': turn.number, 'at': turn.finished_at}
            number += 1
            content_sha256 = text_hash(content)
            session.add(Proposal(
                id=str(uuid4()), conversation_id=conversation.id, turn_id=turn.id, number=number, kind=kind, path=path,
                content=content, reason=reason, content_sha256=content_sha256, base_sha256=base,
                proposal_sha256=digest({'kind': kind, 'path': path, 'content_sha256': content_sha256,
                                        'base_sha256': base, 'reason': reason, 'turn_id': turn.id}),
                status='PROPOSED', decision=None, version=1, created_at=turn.finished_at))
    _touch(managed, conversation)


def abort(managed, session, run, status, reason):
    """Writer confirmed stopped (unknown result) or refused job: never retried on its own."""
    turn, conversation = _turn(session, run)
    if turn.status != 'QUEUED':
        return
    turn.status = 'UNKNOWN' if status == 'INTERRUPTED' else 'REFUSED'
    turn.finished_at = managed._now()
    turn.result = {'status': turn.status, 'reasons': [reason], 'result': None, 'observed': None}
    _touch(managed, conversation)


def lock_for_bootstrap(session, shown):
    """In the transaction that queues the v2 bootstrap: the conversation is still the reviewed one."""
    definition = shown['definition']
    conversation = session.get(Conversation, definition['conversation_id'])
    if conversation is None or conversation.version != definition['conversation_version']:
        raise Conflict(tr('planning.definition_conversation_changed_since'))
    if session.scalar(select(Turn.id).where(Turn.conversation_id == conversation.id, Turn.status == 'QUEUED')):
        raise Conflict(tr('planning.definition_turn_pending_accept'))


def definition_acceptance(managed, context, data, writer) -> dict:
    """Preview of the v2 acceptance: SQLite snapshot + target drafts, without effects."""
    if not isinstance(data, dict) or set(data) != {'conversation_id'}:
        raise ValueError(tr('planning.projects_documents_v2_created'))
    inspection = writer.inspect_definition(context, texts=True)
    texts = inspection.pop('texts')
    with Session(managed.engine) as session:
        conversation = session.get(Conversation, data['conversation_id'])
        if conversation is None or conversation.root != str(context.root) or conversation.kind != 'definition':
            raise LookupError(tr('planning.unknown_definition_conversation_project'))
        if session.scalar(select(Turn.id).where(Turn.conversation_id == conversation.id, Turn.status == 'QUEUED')):
            raise Conflict(tr('planning.definition_turn_pending_accept'))
        if (conversation.source or {}).get('authority') == 'structured-intake-1':
            raise Conflict(tr('intake.database_owned'))
        snapshot = PlanningRepository._record(session, conversation)
    shown = acceptance(context, snapshot, inspection, texts)
    return {**shown, 'target': inspection, 'ready': not shown['blockers']}


class PlanningRepository:
    def __init__(self, managed):
        self.managed = managed

    def _conversation(self, session, conversation_id, expected=None, context=None):
        row = session.get(Conversation, conversation_id)
        if row is None:
            raise LookupError(tr('planning.unknown_planning_conversation'))
        if context is not None and row.root != str(context.root):
            raise LookupError(tr('planning.conversation_belongs_another_checkout'))
        if row.kind not in KINDS:
            raise Conflict(tr('planning.legacy_support_has_been'))
        if expected is not None and (type(expected) is not int or row.version != expected):
            raise Conflict(tr('planning.conversation_changed_reload_before'))
        return row

    def _port(self, conversation, writer):
        """Drafts on disk: target folder of the definition or private area of the import."""
        if conversation.kind == 'onboarding':
            return OnboardingDrafts.of(self.managed.engine, conversation.id)
        return writer

    @staticmethod
    def _drafts_created(session, conversation):
        """Only definition and import have drafts; True if the definition already created the project."""
        if conversation.kind not in DRAFT_KINDS:
            raise Conflict(tr('planning.definition_import_conversations_have'))
        if conversation.kind == 'onboarding':
            from my_harness.storage.documents import latest_phase
            from my_harness.storage.models import ProjectImportRow
            return (_bootstrapped(session, conversation.root) or latest_phase(session, conversation.root) is not None
                    or session.scalar(select(ProjectImportRow.id).where(
                        ProjectImportRow.root == conversation.root)) is not None)
        return conversation.kind == 'definition' and _bootstrapped(session, conversation.root)

    @staticmethod
    def _record(session, conversation) -> dict:
        """What the acceptance summarizes in DEFINITION.md: SQLite data, deterministic."""
        turns = session.scalars(select(Turn).where(Turn.conversation_id == conversation.id).order_by(Turn.number)).all()
        questions, pending = current_questions(session, conversation)
        return {'id': conversation.id, 'title': conversation.title, 'version': conversation.version,
                'brief': conversation.brief, 'log': list(conversation.log), 'questions': questions, 'pending': pending,
                'turns': [{'number': t.number, 'status': t.status, 'message': t.message,
                           'answer': (t.result or {}).get('result', {}).get('answer') if t.status == 'ANSWERED' else None,
                           'drafts': (t.result['result']['drafts'] if t.status == 'ANSWERED' else [])}
                          for t in turns]}

    # --- reads ------------------------------------------------------------------------

    def root(self, conversation_id):
        with Session(self.managed.engine) as session:
            return self._conversation(session, conversation_id).root

    def list(self, root):
        with Session(self.managed.engine) as session:
            rows = session.scalars(select(Conversation).where(Conversation.root == str(root), Conversation.kind.in_(KINDS))
                                   .order_by(Conversation.created_at, Conversation.id)).all()
            result = []
            for row in rows:
                phase = session.get(Phase, row.phase_id) if row.phase_id else None
                turns = session.scalar(select(func.count()).select_from(Turn).where(Turn.conversation_id == row.id))
                result.append({'id': row.id, 'kind': row.kind, 'title': row.title, 'phase_id': row.phase_id,
                               'phase_code': phase.code if phase else None, 'turns': turns, 'version': row.version,
                               'created_at': row.created_at, 'updated_at': row.updated_at})
            return result

    def get(self, conversation_id):
        """Projection with the live state of the runs and actions computed by the server."""
        with Session(self.managed.engine) as session:
            row = self._conversation(session, conversation_id)
            phase = session.get(Phase, row.phase_id) if row.phase_id else None
            turns = session.scalars(select(Turn).where(Turn.conversation_id == row.id).order_by(Turn.number)).all()
            proposals = session.scalars(select(Proposal).where(Proposal.conversation_id == row.id)
                                        .order_by(Proposal.number)).all()
            numbers = {turn.id: turn.number for turn in turns}
            pending = any(turn.status == 'QUEUED' for turn in turns)
            created = self._drafts_created(session, row) if row.kind in DRAFT_KINDS else False
            structured = (row.source or {}).get('authority') == 'structured-intake-1'
            if structured:
                from my_harness.storage.models import KnowledgeProjectRow, KnowledgeRevisionRow
                created = session.scalar(select(KnowledgeRevisionRow.id).join(
                    KnowledgeProjectRow, KnowledgeRevisionRow.project_id == KnowledgeProjectRow.id).where(
                    KnowledgeProjectRow.root == row.root, KnowledgeRevisionRow.status == 'ACCEPTED')) is not None
            open_ = not pending and not created
            questions, items = current_questions(session, row)
            turn_views = [{
                'id': turn.id, 'number': turn.number, 'status': turn.status, 'run_id': turn.run_id,
                'run_status': session.get(Run, turn.run_id).status, 'message': turn.message,
                'context_sha256': turn.request['context_sha256'], 'request_sha256': turn.request_sha256,
                'drafts': [{key: item[key] for key in ('path', 'sha256', 'size')}
                           for item in turn.request['context'].get('drafts', [])],
                'user_edits': turn.request['context'].get('user_edits', []),
                'documents': [{key: item[key] for key in ('path', 'sha256', 'size', 'truncated')}
                              for item in turn.request['context'].get('documents', [])],
                'result': turn.result, 'actor': turn.actor, 'created_at': turn.created_at,
                'finished_at': turn.finished_at} for turn in turns]
            proposal_views = []
            for item in proposals:
                actions = []
                if item.status == 'PROPOSED' and open_:
                    actions = ['apply', 'dismiss'] if item.kind == 'draft' else ['dismiss']
                proposal_views.append({
                    'id': item.id, 'number': item.number, 'turn_id': item.turn_id, 'turn_number': numbers[item.turn_id],
                    'kind': item.kind, 'path': item.path, 'content': item.content, 'reason': item.reason,
                    'content_sha256': item.content_sha256, 'base_sha256': item.base_sha256,
                    'proposal_sha256': item.proposal_sha256, 'status': item.status, 'decision': item.decision,
                    'version': item.version, 'created_at': item.created_at, 'actions': actions})
            actions = []
            if open_:
                actions = ['message'] + {'definition': ['edit_draft', 'defer_question', 'accept'],
                                         'onboarding': ['edit_draft', 'defer_question']}.get(row.kind, [])
            if structured:
                actions = ['defer_question'] if open_ else []
                if open_:
                    actions.append('message')
            return {'structured': (row.source or {}).get('authority') == 'structured-intake-1',
                    'id': row.id, 'root': row.root, 'kind': row.kind, 'title': row.title,
                    'phase': None if phase is None else {'id': phase.id, 'code': phase.code, 'status': phase.status},
                    'brief': None if row.brief is None else {k: row.brief[k] for k in ('sha256', 'size')},
                    'source': (None if row.source is None else onboarding_identity(row.source)
                               if row.kind == 'onboarding' else None),
                    'known': row.known, 'log': row.log, 'questions': questions, 'pending': items,
                    'actor': row.actor, 'version': row.version, 'created_at': row.created_at,
                    'updated_at': row.updated_at, 'created': created, 'turns': turn_views,
                    'proposals': proposal_views, 'actions': actions}

    def brief(self, conversation_id):
        with Session(self.managed.engine) as session:
            row = self._conversation(session, conversation_id)
            if row.brief is None:
                raise LookupError(tr('planning.conversation_has_no_brief'))
            return dict(row.brief)

    def drafts(self, context, conversation_id, writer):
        """Target drafts against what the harness knows: the differences belong to the user."""
        target = definition_layout(context)
        with Session(self.managed.engine) as session:
            row = self._conversation(session, conversation_id, context=context)
            known = dict(row.known)
            if self._drafts_created(session, row):
                return {'created': True, 'allowed': allowed_drafts_view(target), 'drafts': [], 'foreign': [],
                        'foreign_truncated': False, 'invalid': [], 'import_required': False}
            writer = self._port(row, writer)
        inspection = writer.inspect_definition(context)
        drafts = [{'path': path, 'sha256': inspection['drafts'].get(path), 'known_sha256': known.get(path),
                   'user_edited': inspection['drafts'].get(path) != known.get(path)}
                  for path in sorted(set(inspection['drafts']) | {p for p, v in known.items() if v is not None})]
        return {'created': False, 'allowed': allowed_drafts_view(target), 'drafts': drafts,
                'foreign': inspection['foreign'], 'foreign_truncated': inspection['foreign_truncated'],
                'invalid': inspection['invalid'], 'import_required': inspection['import_required']}

    def draft(self, context, conversation_id, path, writer):
        """H6.2 E4: content of a draft through the same inspection the turn and the CAS use."""
        target = definition_layout(context)
        if not allowed_draft(target, path):
            raise LookupError(tr('planning.not_allowed_definition_draft', path=path))
        with Session(self.managed.engine) as session:
            row = self._conversation(session, conversation_id, context=context)
            if self._drafts_created(session, row):
                raise Conflict(tr('planning.project_already_created_read'))
            known = row.known.get(path)
            writer = self._port(row, writer)
        inspection = writer.inspect_definition(context, texts=True)
        if path in inspection['invalid']:
            raise Conflict(tr('planning.not_valid_draft_utf', path=path))
        if path not in inspection['texts']:
            raise LookupError(tr('planning.does_not_exist_target', path=path))
        return {'path': path, 'content': inspection['texts'][path], 'sha256': inspection['drafts'][path],
                'known_sha256': known}

    def snapshot(self, run_id):
        """Frozen request for the turn's job."""
        with Session(self.managed.engine) as session:
            run = session.get(Run, run_id)
            if run is None:
                raise LookupError(tr('managed.unknown_managed_run'))
            turn, conversation = _turn(session, run)
            return {'kind': conversation.kind, 'conversation_id': conversation.id, 'turn_id': turn.id,
                    'message': turn.message,
                    'context': turn.request['context'], 'context_sha256': turn.request['context_sha256'],
                    'observed': turn.request.get('observed')}

    # --- conversation ------------------------------------------------------------------

    def create(self, context, *, kind, title, brief=None, phase_id=None, writer=None, key=None, structured=False):
        """`key` (API): a retry with the same request returns the same conversation before reevaluating the
        target, which the original registration may have changed (project already created, phase transitioned)."""
        if kind not in KINDS:
            raise ValueError(tr('planning.conversation_kind_definition_phase'))
        if isinstance(context, IntakeContext) and kind not in DRAFT_KINDS:
            raise Conflict(tr('profile_proposal.required'))
        request = digest({'action': 'planning_conversation', 'root': str(context.root), 'kind': kind, 'title': title,
                          'brief': brief, 'phase_id': phase_id, **({'structured': True} if structured else {})})
        if key is not None:
            with Session(self.managed.engine) as session:
                if found := existing_creation(session, Conversation, key, request):
                    return found
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError(tr('planning.conversation_title_contain_1'))
        source = None
        if kind == 'definition':
            definition_layout(context)
            frozen = brief_payload(brief)
            if phase_id is not None:
                raise ValueError(tr('planning.definition_conversation_has_no'))
            if writer.inspect_definition(context)['import_required']:
                raise Conflict(tr('planning.target_belongs_git_repository'))
        elif kind == 'onboarding':
            definition_layout(context)
            if brief is not None or phase_id is not None:
                raise ValueError(tr('planning.onboarding_conversation_has_no'))
            inventory = read_inventory(context, _executable(writer))
            source, frozen = {'inventory': inventory}, None
        else:
            require_layout(context)
            if brief is not None:
                raise ValueError(tr('planning.phase_planning_conversation_has'))
            frozen = None
        if structured:
            if kind not in DRAFT_KINDS:
                raise ValueError(tr('intake.invalid'))
            source = {**(source or {}), 'authority': 'structured-intake-1'}
        try:
            with self.managed._write() as session:
                if key is not None and (found := existing_creation(session, Conversation, key, request)):
                    return found
                if kind == 'definition':
                    from my_harness.storage.bootstrap import BootstrapRepository
                    if _bootstrapped(session, str(context.root)):
                        raise Conflict(tr('planning.project_already_created_plan'))
                    BootstrapRepository._empty_authority(session, str(context.root))
                elif kind == 'onboarding':
                    self._importable(session, str(context.root))
                else:
                    phase = session.get(Phase, phase_id) if isinstance(phase_id, str) else None
                    if phase is None or phase.root != str(context.root):
                        raise LookupError(tr('planning.unknown_phase_checkout'))
                    from my_harness.storage.documents import latest_phase
                    if latest_phase(session, phase.root).id != phase.id:
                        raise Conflict(tr('planning.plan_latest_phase_checkout'))
                if structured:
                    from my_harness.storage.models import KnowledgeProjectRow, KnowledgeRevisionRow
                    if session.scalar(select(KnowledgeRevisionRow.id).join(KnowledgeProjectRow,
                            KnowledgeRevisionRow.project_id == KnowledgeProjectRow.id).where(
                            KnowledgeProjectRow.root == str(context.root), KnowledgeRevisionRow.status == 'ACCEPTED')):
                        raise Conflict(tr('intake.database_owned'))
                now = self.managed._now()
                row = Conversation(id=str(uuid4()), root=str(context.root), kind=kind, phase_id=phase_id,
                                   title=title.strip(), brief=frozen, known={}, deferred={}, log=[], actor=actor(),
                                   version=0, created_at=now, updated_at=now, idempotency_key=key,
                                   request_sha256=request if key is not None else None, source=source)
                session.add(row)
                session.flush()
                return row.id
        except IntegrityError as exc:
            raise Conflict(tr('planning.project_already_has_definition')) from exc

    @staticmethod
    def _importable(session, root):
        """Onboarding admits projects the harness does not manage yet: no creation or own phases."""
        from my_harness.storage.documents import latest_phase
        if _bootstrapped(session, root):
            raise Conflict(tr('planning.project_created_harness_nothing'))
        if latest_phase(session, root) is not None:
            raise Conflict(tr('planning.project_already_has_managed'))
        from my_harness.storage.models import ProjectImportRow
        if session.scalar(select(ProjectImportRow.id).where(ProjectImportRow.root == root)):
            raise Conflict(tr('planning.import_already_confirmed_complete'))

    # --- turns -------------------------------------------------------------------------

    def submit_message(self, context, conversation_id, expected, *, key, versions, text, writer=None):
        """Freezes message and context in the transaction that queues the turn."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_MESSAGE:
            raise ValueError(tr('planning.planning_message_contain_1', max_message=MAX_MESSAGE))
        request = freeze({'action': 'planning_turn', 'conversation_id': conversation_id, 'expected_version': expected,
                          'text': text})
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            conversation = self._conversation(session, conversation_id, context=context)
            kind, source = conversation.kind, conversation.source
            if kind == 'definition' and _bootstrapped(session, conversation.root):
                raise Conflict(tr('planning.project_already_created_definition'))
            port = self._port(conversation, writer)
        observed, prepared = None, {}
        if kind == 'onboarding':
            if isinstance(context, IntakeContext) and read_inventory(context, _executable(writer)) != source['inventory']:
                raise Conflict(tr('profile_proposal.stale'))
            target = definition_layout(context)
            inspection = port.inspect_definition(context, texts=True)
            texts = inspection.pop('texts')
            prepared = onboarding_context(target, source, texts, inspection)
            observed = onboarding_observation(inspection)
        elif kind == 'definition':
            target = definition_layout(context)
            inspection = writer.inspect_definition(context, texts=True)
            texts = inspection.pop('texts')
            if inspection['import_required']:
                raise Conflict(tr('planning.target_belongs_git_repository'))
            if sum(len(value.encode('utf-8')) for value in texts.values()) > MAX_CONTEXT_DRAFT_BYTES:
                raise ValueError(tr('planning.drafts_exceed_2_mib'))
            observed = inspection
            prepared = {'drafts': [{'path': path, 'sha256': inspection['drafts'][path],
                                    'size': len(texts[path].encode('utf-8')), 'content': texts[path]}
                                   for path in sorted(texts)],
                        'foreign': inspection['foreign'], 'invalid': inspection['invalid'],
                        'allowed': allowed_drafts_view(target)}
        else:
            target = require_layout(context)
            roadmap, state = read_text(context, target.roadmap), read_text(context, target.state)
            prepared = {'documents': read_documents(context, [target.roadmap, target.state, target.specification,
                                                              target.architecture, target.decisions, target.next_steps,
                                                              target.ddbb_diagram, *target.instructions]),
                        'entries': parse_roadmap(roadmap) if roadmap is not None else [],
                        'base': base_section(state) if state is not None else None}
        assessment = self.managed.guard.assess(context.root)
        with self.managed._write() as session:
            existing = self.managed._existing(session, key, request)
            if existing:
                return _job(existing)
            conversation = self._conversation(session, conversation_id, expected, context)
            if session.scalar(select(Turn.id).where(Turn.conversation_id == conversation.id, Turn.status == 'QUEUED')):
                raise Conflict(tr('planning.previous_turn_conversation_still'))
            previous = session.scalars(select(Turn).where(Turn.conversation_id == conversation.id)
                                       .order_by(Turn.number.desc()).limit(MAX_PREVIOUS_TURNS)).all()
            history = []
            for turn in reversed(previous):
                answered = turn.status == 'ANSWERED'
                history.append({'number': turn.number, 'status': turn.status, 'message': turn.message,
                                'answer': turn.result['result']['answer'] if answered else None,
                                **({'knowledge_proposal': turn.result['result']['knowledge']}
                                   if answered and 'knowledge' in turn.result['result'] else {}),
                                'reasons': list((turn.result or {}).get('reasons', [])),
                                'proposals': [{'number': p.number, 'kind': p.kind, 'path': p.path, 'status': p.status}
                                              for p in session.scalars(select(Proposal).where(Proposal.turn_id == turn.id)
                                                                       .order_by(Proposal.number))]})
            number = 1 + (session.scalar(select(func.max(Turn.number)).where(
                Turn.conversation_id == conversation.id)) or 0)
            questions, pending = current_questions(session, conversation)
            frozen = {'kind': conversation.kind,
                      'project': {'root': str(context.root), 'profile': profile_name(context),
                                  'layout': {'docs': target.docs, 'state': target.state,
                                             'next_steps': target.next_steps, 'decisions': target.decisions,
                                             'ddbb_diagram': target.ddbb_diagram, 'flows': target.flows_dir,
                                             'phase': target.phase_dir}},
                      'conversation': {'id': conversation.id, 'title': conversation.title, 'turn': number},
                      'questions': questions, 'pending': pending, 'previous_turns': history}
            if (conversation.source or {}).get('authority') == 'structured-intake-1':
                if self.get(conversation.id)['created']:
                    raise Conflict(tr('intake.staged'))
                frozen['knowledge_authority'] = 'structured-intake-1'
                frozen['accepted_revision'] = None
                from my_harness.services.intake import binding
                bound = binding(conversation)
                if bound:
                    from my_harness.services.domain_operations import DomainOperations, owner_writer
                    from my_harness.core.engine.domain_catalogue import CATALOGUE
                    frozen['structured_draft'] = dict(DomainOperations(self.managed.engine).execute(
                        owner_writer(conversation.root), CATALOGUE.current('knowledge.draft.get').ref,
                        {'draft_id': bound['draft_id']}).result)
                from my_harness.storage.intake_sources import sources
                frozen['intake_source_sha256'] = digest(conversation.source)
                frozen['intake_brief_sha256'] = digest(conversation.brief)
                frozen['intake_sources'] = sources(session, conversation)
                frozen['intake_sources']['owner-message'] = text_hash(text)
                frozen['owner_message_source'] = {'kind': 'observation', 'reference': 'owner-message', 'sha256': text_hash(text)}
            if isinstance(context, IntakeContext):
                frozen['capabilities'] = 'project-intake-1'
                frozen['executor_policy'] = {
                    'mode': context.policy.executor_mode,
                    'models': list(context.policy.executor_models),
                    'efforts': list(context.policy.executor_efforts),
                    'effort_vocabulary': list(context.policy.executor_effort_vocabulary)}
                profile = session.scalar(select(Proposal).where(
                    Proposal.conversation_id == conversation.id, Proposal.kind == 'profile',
                    Proposal.status.in_(('PROPOSED', 'ACCEPTED'))).order_by(Proposal.number.desc()).limit(1))
                frozen['profile_draft'] = (None if profile is None else {
                    'id': profile.id, 'proposal_sha256': profile.proposal_sha256,
                    'status': profile.status, 'content': json.loads(profile.content)})
            if conversation.kind in DRAFT_KINDS:
                if conversation.kind == 'definition' and _bootstrapped(session, conversation.root):
                    raise Conflict(tr('planning.project_already_created_definition'))
                if conversation.kind == 'onboarding':
                    self._importable(session, conversation.root)
                known, drafts = conversation.known, observed['drafts']
                defaults = skeleton(target, conversation.title,
                                    preparation=([command.argv for command in context.profile.preparation]
                                                 if not isinstance(context, IntakeContext) else []),
                                    validations=([command.argv for command in context.profile.validations]
                                                 if not isinstance(context, IntakeContext) else []),
                                    language=work_language(context))
                frozen.update(prepared, user_edits=[
                    {'path': path, 'before_sha256': known.get(path), 'after_sha256': drafts.get(path)}
                    for path in sorted(set(known) | set(drafts)) if known.get(path) != drafts.get(path)],
                    template_defaults=({} if conversation.kind == 'onboarding' else
                                       {path: defaults[path] for path in default_documents(target)}))
                if conversation.kind == 'definition':
                    frozen['brief'] = conversation.brief
                    task_id = f'DEF-{conversation.id[:8]}-{number}'
                else:
                    prefix = 'ONB' if conversation.kind == 'onboarding' else 'IMP'
                    task_id = f'{prefix}-{conversation.id[:8]}-{number}'
                phase_code = 'P000'
            else:
                from my_harness.storage.documents import latest_phase, summary_snapshot
                phase = session.get(Phase, conversation.phase_id)
                if latest_phase(session, phase.root).id != phase.id:
                    raise Conflict(tr('planning.newer_phase_exists_plan'))
                codes = [entry['code'] for entry in prepared['entries']]
                following = (prepared['entries'][codes.index(phase.code) + 1]
                             if phase.code in codes and codes.index(phase.code) + 1 < len(codes) else None)
                if phase.status == 'ACTIVE' and not phase.definition['tasks']:
                    following = next((entry for entry in prepared['entries'] if entry['code'] == phase.code), None)
                frozen.update(documents=prepared['documents'], base=prepared['base'], next=following,
                              phase={'id': phase.id, 'code': phase.code, 'status': phase.status,
                                     'summary': summary_snapshot(session, phase)})
                task_id, phase_code = f'PLAN-{conversation.id[:8]}-{number}', phase.code
            job = self.managed._queue_new_run(session, assessment, context, versions, task_id, phase_code, key, request,
                                              purpose=conversation.kind)
            context_sha256 = digest(frozen)
            session.add(Turn(id=str(uuid4()), conversation_id=conversation.id, number=number, run_id=job.run_id,
                             status='QUEUED', message=text,
                             request={'context': frozen, 'context_sha256': context_sha256, 'observed': observed},
                             request_sha256=digest({'message': text, 'context_sha256': context_sha256}),
                             result=None, actor=actor(), created_at=self.managed._now()))
            _touch(self.managed, conversation)
            return job

    # --- drafts --------------------------------------------------------------------------

    def profile_state(self, root):
        """Describes an adopted draft, never preparation readiness; GET performs no filesystem probes."""
        with Session(self.managed.engine) as session:
            adopted = session.scalar(select(Proposal.id).join(Conversation,
                Conversation.id == Proposal.conversation_id).where(
                    Conversation.root == str(root), Proposal.kind == 'profile', Proposal.status == 'ACCEPTED').limit(1))
            return 'PROFILE_PROPOSED' if adopted else 'PROFILE_REQUIRED'

    def profile_preview(self, context, conversation_id, proposal_id, expected, proposal_sha256, writer=None,
                        *, session=None, versions=None):
        """Adoption preview only. Current drafts, HEAD, questions and frozen agent context are checked again."""
        if session is None:
            with Session(self.managed.engine) as read:
                return self.profile_preview(context, conversation_id, proposal_id, expected, proposal_sha256,
                                            writer, session=read, versions=versions)
        if not isinstance(context, IntakeContext):
            raise Conflict(tr('profile_proposal.required'))
        conversation = self._conversation(session, conversation_id, expected, context)
        if (conversation.source or {}).get('authority') == 'structured-intake-1':
            from my_harness.storage.profile_intake import structured_preview
            return structured_preview(self.managed.engine, session, context, conversation, proposal_id, proposal_sha256, writer, versions)
        self._definition_open(session, conversation)
        proposal = session.get(Proposal, proposal_id)
        if (proposal is None or proposal.conversation_id != conversation.id or proposal.kind != 'profile'
                or proposal.status not in ('PROPOSED', 'ACCEPTED') or proposal.proposal_sha256 != proposal_sha256
                or text_hash(proposal.content) != proposal.content_sha256):
            raise Conflict(tr('profile_proposal.stale'))
        payload = json.loads(proposal.content)
        turn = session.get(Turn, proposal.turn_id)
        latest = session.scalar(select(Turn).where(Turn.conversation_id == conversation.id)
                                .order_by(Turn.number.desc()).limit(1))
        run = session.get(Run, turn.run_id)
        blockers = []
        if (latest.id != turn.id or turn.status != 'ANSWERED'
                or run.context_json != context_snapshot(context)
                or (versions is not None and run.versions_json != freeze(versions))
                or digest(turn.request['context']) != turn.request['context_sha256']):
            blockers.append(tr('profile_proposal.stale'))
        port = self._port(conversation, writer)
        inspection = port.inspect_definition(context, texts=True)
        texts = inspection.pop('texts')
        expected_documents = payload['binding']['documents']
        actual_documents = inspection['drafts']
        missing = sorted(expected_documents.keys() - actual_documents.keys())
        changed = sorted(path for path in actual_documents
                         if path not in expected_documents or actual_documents[path] != expected_documents[path])
        if missing:
            blockers.append(tr('profile_proposal.documents_required', paths=', '.join(missing)))
        if changed:
            blockers.append(tr('profile_proposal.documents_changed', paths=', '.join(changed)))
        if inspection['invalid'] or inspection['foreign']:
            blockers.append(tr('profile_proposal.stale'))
        documents_ready = not (missing or changed or inspection['invalid'] or inspection['foreign'])
        if conversation.kind == 'onboarding':
            if read_inventory(context, _executable(writer)) != conversation.source['inventory']:
                blockers.append(tr('profile_proposal.stale'))
        elif inspection['import_required']:
            blockers.append(tr('profile_proposal.stale'))
        questions, _ = current_questions(session, conversation)
        if any(question['blocking'] and not question.get('deferred') for question in questions):
            blockers.append(tr('profile_proposal.questions'))
        # A missing/changed documentary base is not an invalid candidate. Re-parse only once the exact
        # document bytes are present; confirmation still repeats every guard before adopting anything.
        if documents_ready:
            from my_harness.services.profile_proposal import validate
            frozen = {**turn.request['context'], 'drafts': [
                {'path': path, 'sha256': text_hash(content)} for path, content in sorted(texts.items())]}
            try:
                checked = validate(payload['candidate'], frozen, [], context=context)
                if checked != payload:
                    blockers.append(tr('profile_proposal.stale'))
            except ValueError:
                blockers.append(tr('profile_proposal.invalid'))
        shown = {'conversation_id': conversation.id, 'proposal_id': proposal.id,
                 'expected_version': conversation.version, 'proposal_sha256': proposal.proposal_sha256,
                 'profile': payload, 'blockers': blockers, 'ready': not blockers,
                 'configuration_state': 'PROFILE_PROPOSED' if proposal.status == 'ACCEPTED' else 'PROFILE_REQUIRED'}
        return {**shown, 'preview_sha256': digest(shown)}

    def edit_profile(self, context, conversation_id, proposal_id, expected, proposal_sha256,
                     candidate, reason, key, writer=None, versions=None):
        """Version a user edit, keeping the reviewer result and every previous confirmation immutable."""
        request = digest({'root': str(context.root), 'conversation_id': conversation_id, 'proposal_id': proposal_id, 'expected': expected,
                          'proposal_sha256': proposal_sha256, 'candidate': candidate, 'reason': reason})
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError(tr('profile_proposal.invalid'))
        with self.managed._write() as session:
            for row in session.scalars(select(Proposal).where(Proposal.kind == 'profile')):
                if (row.decision or {}).get('edit_key') == key:
                    if row.decision['edit_request_sha256'] != request:
                        raise Conflict(tr('profile_proposal.key_reused'))
                    return row.decision['edit_result']
            shown = self.profile_preview(context, conversation_id, proposal_id, expected, proposal_sha256,
                                         writer, session=session, versions=versions)
            if not shown['ready']:
                raise Conflict(tr('profile_proposal.stale'))
            old = session.get(Proposal, proposal_id)
            turn = session.get(Turn, old.turn_id)
            from my_harness.services.profile_proposal import validate
            frozen = {**turn.request['context'], 'drafts': [
                {'path': path, 'sha256': value} for path, value in shown['profile']['binding']['documents'].items()]}
            conversation = session.get(Conversation, conversation_id)
            if (conversation.source or {}).get('authority') == 'structured-intake-1':
                frozen['knowledge_proposal'] = turn.result['result']['knowledge']
            payload = validate(candidate, frozen, [], context=context)
            if payload is None:
                raise ValueError(tr('profile_proposal.invalid'))
            content = freeze(payload)
            number = session.scalar(select(func.max(Proposal.number)).where(Proposal.conversation_id == conversation_id)) + 1
            identifier = str(uuid4())
            result = {'proposal_id': identifier, 'version': expected + 1}
            session.add(Proposal(id=identifier, conversation_id=conversation_id, turn_id=old.turn_id,
                number=number, kind='profile', path=None, content=content, reason=reason,
                content_sha256=text_hash(content), base_sha256=None,
                proposal_sha256=digest({'content': content, 'previous': old.id, 'reason': reason}),
                status='PROPOSED', version=1, created_at=self.managed._now(),
                decision={'edit_key': key, 'edit_request_sha256': request, 'actor': actor(), 'edit_result': result}))
            old.status, old.version = 'SUPERSEDED', old.version + 1
            old.decision = {**(old.decision or {}), 'superseded_by_edit': identifier}
            _touch(self.managed, session.get(Conversation, conversation_id))
            return result

    def confirm_profile(self, context, conversation_id, proposal_id, expected, *, proposal_sha256,
                        preview_sha256, reason, key, writer=None, versions=None):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError(tr('profile_proposal.invalid'))
        request = digest({'conversation_id': conversation_id, 'proposal_id': proposal_id, 'expected': expected,
                          'proposal_sha256': proposal_sha256, 'preview_sha256': preview_sha256, 'reason': reason})
        with self.managed._write() as session:
            # Replay precedes the CAS check and never re-applies files or starts a preparation.
            for row in session.scalars(select(Proposal).where(
                    Proposal.kind == 'profile', Proposal.decision['key'].as_string() == key)):
                if row.decision and row.decision.get('key') == key:
                    if row.decision.get('request_sha256') != request:
                        raise Conflict(tr('profile_proposal.key_reused'))
                    return row.decision['result']
            shown = self.profile_preview(context, conversation_id, proposal_id, expected, proposal_sha256,
                                         writer, session=session, versions=versions)
            if not shown['ready'] or shown['preview_sha256'] != preview_sha256:
                raise Conflict(tr('profile_proposal.stale'))
            proposal = session.get(Proposal, proposal_id)
            if proposal.status != 'PROPOSED':
                raise Conflict(tr('profile_proposal.stale'))
            result = {'conversation_id': conversation_id, 'proposal_id': proposal_id,
                      'configuration_state': 'PROFILE_PROPOSED', 'version': expected + 1,
                      'proposal_sha256': proposal_sha256}
            proposal.status, proposal.version = 'ACCEPTED', proposal.version + 1
            proposal.decision = {**(proposal.decision or {}), 'decision': 'profile_draft_adopted', 'key': key, 'request_sha256': request,
                                 'preview_sha256': preview_sha256, 'reason': reason, 'actor': actor(),
                                 'at': self.managed._now(), 'result': result}
            if shown.get('knowledge_binding') is not None:
                proposal.decision = {**proposal.decision, 'origin': 'owner_confirmed',
                                     'knowledge_binding': shown['knowledge_binding'], 'profile_preview': shown}
            _touch(self.managed, session.get(Conversation, conversation_id))
            return result

    def _definition_open(self, session, conversation, *, documentary=True):
        if (conversation.source or {}).get('authority') == 'structured-intake-1':
            if documentary or self.get(conversation.id)['created']:
                raise Conflict(tr('intake.database_owned'))
        if self._drafts_created(session, conversation):
            raise Conflict(tr('planning.project_already_created_edit'))
        if conversation.kind == 'onboarding':
            self._importable(session, conversation.root)
        if session.scalar(select(Turn.id).where(Turn.conversation_id == conversation.id, Turn.status == 'QUEUED')):
            raise Conflict(tr('planning.turn_conversation_pending_act'))

    def apply(self, context, conversation_id, proposal_id, expected, *, proposal_sha256, confirmed, writer):
        """Explicit confirmation → the harness writes the draft if it is still the one the turn read."""
        from my_harness.adapters.bootstrap import DraftConflict
        if confirmed is not True:
            raise ValueError(tr('planning.applying_draft_requires_explicit'))
        with self.managed._write() as session:
            conversation = self._conversation(session, conversation_id, expected, context)
            self._definition_open(session, conversation)
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.conversation_id != conversation.id or proposal.kind != 'draft':
                raise LookupError(tr('planning.unknown_draft_proposal_conversation'))
            if proposal.status != 'PROPOSED':
                raise Conflict(tr('planning.proposal_already', status=proposal.status.lower()))
            if proposal.proposal_sha256 != proposal_sha256:
                raise Conflict(tr('planning.apply_exact_proposal_shown'))
            try:
                written = self._port(conversation, writer).write_draft(context, proposal.path, proposal.content,
                                                                       proposal.base_sha256)
            except DraftConflict as exc:
                raise Conflict(tr('planning.user_edit_preserved_ask', exc=exc)) from exc
            turn = session.get(Turn, proposal.turn_id)
            now = self.managed._now()
            proposal.status, proposal.version = 'APPLIED', proposal.version + 1
            proposal.decision = {'decision': 'apply', 'actor': actor(), 'at': now, 'before': written['before'],
                                 'after': written['after'], 'written': written['written']}
            conversation.known = {**conversation.known, proposal.path: proposal.content_sha256}
            conversation.log = [*conversation.log, {
                'source': 'proposal', 'path': proposal.path, 'proposal_id': proposal.id,
                'proposal_number': proposal.number, 'turn_number': turn.number, 'before': written['before'],
                'after': written['after'], 'at': now}]
            _touch(self.managed, conversation)

    def edit_draft(self, context, conversation_id, expected, *, path, content, base_sha256, writer):
        """User edit through the API with CAS; the next turn sees it as a user edit."""
        from my_harness.adapters.bootstrap import DraftConflict
        target = definition_layout(context)
        if not allowed_draft(target, path):
            raise ValueError(tr('planning.not_allowed_definition_draft', path=path))
        if content is not None and (not isinstance(content, str) or '\0' in content
                                    or len(content.encode('utf-8')) > 512 * 1024):
            raise ValueError(tr('planning.draft_content_nul_free'))
        with self.managed._write() as session:
            conversation = self._conversation(session, conversation_id, expected, context)
            self._definition_open(session, conversation)
            try:
                written = self._port(conversation, writer).write_draft(context, path, content, base_sha256)
            except DraftConflict as exc:
                raise Conflict(tr('planning.nothing_overwritten', exc=exc)) from exc
            conversation.log = [*conversation.log, {'source': 'api', 'path': path, 'before': written['before'],
                                                    'after': written['after'], 'actor': actor(),
                                                    'at': self.managed._now()}]
            _touch(self.managed, conversation)
            return written

    def defer(self, conversation_id, expected, *, question_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('planning.explicit_deferral_reason_required'))
        with self.managed._write() as session:
            conversation = self._conversation(session, conversation_id, expected)
            self._definition_open(session, conversation, documentary=False)
            questions, _ = current_questions(session, conversation)
            question = next((q for q in questions if q['id'] == question_id), None)
            if question is None:
                raise LookupError(tr('planning.unknown_open_question_latest'))
            if not question['blocking'] or question['deferred']:
                raise Conflict(tr('planning.open_blocking_question_deferred'))
            conversation.deferred = {**conversation.deferred, question_id: {
                'text': question['text'], 'reason': reason.strip(), 'actor': actor(), 'at': self.managed._now()}}
            _touch(self.managed, conversation)

    def dismiss(self, conversation_id, proposal_id, expected, *, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('planning.explicit_dismissal_reason_required'))
        with self.managed._write() as session:
            conversation = self._conversation(session, conversation_id, expected)
            if conversation.kind == 'onboarding':
                self._definition_open(session, conversation)
            proposal = session.get(Proposal, proposal_id)
            if proposal is None or proposal.conversation_id != conversation.id:
                raise LookupError(tr('planning.unknown_proposal_conversation'))
            if proposal.status != 'PROPOSED':
                raise Conflict(tr('planning.proposal_already', status=proposal.status.lower()))
            proposal.status, proposal.version = 'DISMISSED', proposal.version + 1
            proposal.decision = {'decision': 'dismiss', 'actor': actor(), 'at': self.managed._now(),
                                 'reason': reason.strip()}
            _touch(self.managed, conversation)

    # --- plan of the next phase ------------------------------------------------------------

    def plan(self, session, context, phase_id, reference) -> tuple[str, dict]:
        """Proposed and confirmed plan for a transition: exact content and its origin."""
        if not isinstance(reference, dict) or set(reference) != {'conversation_id', 'proposal_id', 'proposal_sha256'}:
            raise ValueError(tr('planning.plan_proposal_reference_needs'))
        conversation = self._conversation(session, reference['conversation_id'], context=context)
        proposal = session.get(Proposal, reference['proposal_id'])
        if (conversation.kind != 'phase_planning' or conversation.phase_id != phase_id or proposal is None
                or proposal.conversation_id != conversation.id or proposal.kind != 'plan'):
            raise LookupError(tr('planning.unknown_plan_proposal_phase'))
        if proposal.status != 'PROPOSED':
            raise Conflict(tr('planning.plan_proposal_already', status=proposal.status.lower()))
        if proposal.proposal_sha256 != reference['proposal_sha256']:
            raise Conflict(tr('planning.use_exact_plan_proposal'))
        turn = session.get(Turn, proposal.turn_id)
        return proposal.content, {**reference, 'turn_number': turn.number, 'content_sha256': proposal.content_sha256}

    def mark_plan(self, session, origin, run_id, job_id, *, decision='transition'):
        proposal = session.get(Proposal, origin['proposal_id'])
        if proposal.status != 'PROPOSED' or proposal.proposal_sha256 != origin['proposal_sha256']:
            raise Conflict(tr('planning.plan_proposal_changed_since'))
        proposal.status, proposal.version = 'ACCEPTED', proposal.version + 1
        proposal.decision = {'decision': decision, 'actor': actor(), 'at': self.managed._now(),
                             'run_id': run_id, 'job_id': job_id}
        _touch(self.managed, session.get(Conversation, proposal.conversation_id))
