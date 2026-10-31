"""H6.2 E2 (D054/D076): project registry in SQLite, versioned, audited and with logical retirement.

Each change is a transaction: it checks the expected version, that the checkout has no
unfinished work, and writes the row and its audit event. Repeating an
already applied confirmation returns the same result without another version.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.storage.managed import Conflict
from my_harness.storage.models import (
    CheckoutLockRow as Lock, ManagedJobRow as Job, ManagedRunRow as Run,
    RegisteredProjectEventRow as Event, RegisteredProjectRow as Row,
)
from my_harness.storage.permissions import actor
from my_harness.i18n import tr

UNFINISHED = ('QUEUED', 'ACTIVE', 'RECOVERY_REQUIRED')


def _empty_failed_intake_turn(status, result):
    if status != 'FAILED' or not isinstance(result, dict) or result.get('result') is not None:
        return False
    observed = result.get('observed')
    return (isinstance(observed, dict) and observed.get('unchanged') is True
            and all(isinstance(observed.get(side), dict) and not observed[side].get('drafts')
                    for side in ('before', 'after')))


def confirm_work_language(session, project_id, root, preview, source, preview_sha256, reason, now):
    """P011-T008: the root's work language, in the transaction of the confirmation that fixes it (D167).

    The provenance records the default current at confirmation; it never replaces the chosen value."""
    from my_harness.storage import work_language
    from my_harness.storage.models import ProductPreferencesRow
    from my_harness.storage.preferences import view as preferences_view
    current = preferences_view(session.get(ProductPreferencesRow, 1))
    confirmation = {'preview_sha256': preview_sha256, 'actor': actor(), 'reason': reason,
                    'default_work_language': current['default_work_language'],
                    'preferences_version': current['version']}
    try:
        return work_language.associate(session, root=root, project_id=project_id, work_language=preview['work_language'],
                                       source=source, confirmation=confirmation, now=now)
    except work_language.WorkLanguageImmutable as exc:
        raise RegistryConflict('work_language_immutable', str(exc)) from None


class RegistryConflict(Conflict):
    def __init__(self, code, diagnostic):
        super().__init__(diagnostic)
        self.code = code


def view(row):
    return {'id': row.id, 'version': row.version, 'status': row.status, 'root': row.root,
            'composition': row.composition, 'profile': row.profile, 'row': row.row, 'row_sha256': row.row_sha256,
            'trust': row.trust, 'creation_id': row.creation_id,
            'created_at': row.created_at, 'updated_at': row.updated_at}


def event_view(row):
    return {'version': row.version, 'action': row.action, 'row': row.row, 'row_sha256': row.row_sha256,
            'previous_sha256': row.previous_sha256, 'preview_sha256': row.preview_sha256, 'actor': row.actor,
            'reason': row.reason, 'recorded_at': row.recorded_at}


class ProjectRegistryRepository:
    def __init__(self, managed):
        self.managed = managed

    def _read(self):
        return Session(self.managed.engine)

    def rows(self):
        with self._read() as session:
            return [view(row) for row in session.scalars(select(Row).order_by(Row.created_at, Row.id))]

    def get(self, project_id):
        with self._read() as session:
            row = session.get(Row, project_id)
            return view(row) if row else None

    def history(self, project_id):
        with self._read() as session:
            return [event_view(row) for row in session.scalars(
                select(Event).where(Event.project_id == project_id).order_by(Event.version))]

    @staticmethod
    def _unfinished(session, root):
        jobs = session.scalars(select(Job.id).join(Run, Run.id == Job.run_id)
                               .where(Run.root == root, Job.status.in_(UNFINISHED))).all()
        from my_harness.storage.models import ProjectPreparationOperationRow as Preparation
        locked = session.get(Lock, root)
        pending = {f'preparation:{value}' for value in session.scalars(select(Preparation.id).where(
            Preparation.root == root, Preparation.reserved.is_(True)))}
        if locked is not None:
            pending.add(locked.job_id if locked.job_id is not None else f'export:{locked.exchange_id}' if locked.exchange_id else f'preparation:{locked.preparation_id}')
        return sorted(set(jobs) | {p for p in pending if isinstance(p, int)}) + sorted(p for p in pending if isinstance(p, str))

    def unfinished(self, root):
        with self._read() as session:
            return [value for value in self._unfinished(session, root) if isinstance(value, int)]

    @staticmethod
    def _configuration_blockers(session, root):
        """V5: work that is still acceptable cannot survive the composition change."""
        from my_harness.storage.models import ManagedCommitRow, ProjectBootstrapRow, ProjectImportRow
        from my_harness.storage.models import ProjectPreparationOperationRow as Preparation
        blockers = [tr('registry.blocker_preparation', id=value) for value in session.scalars(
            select(Preparation.id).where(Preparation.root == root, Preparation.reserved.is_(True)))]
        blockers += [tr('registry.blocker_acceptance', id=value) for value in session.scalars(
            select(Run.id).where(Run.root == root, Run.status == 'ACCEPTANCE_READY'))]
        blockers += [tr('registry.blocker_commit', id=value) for value in session.scalars(
            select(ManagedCommitRow.operation_id).join(Run, Run.id == ManagedCommitRow.run_id)
            .where(Run.root == root, ManagedCommitRow.status == 'INTENT'))]
        blockers += ProjectRegistryRepository._documentary_blockers(session, root)
        lock = session.get(Lock, root)
        if lock is not None and lock.exchange_id:
            blockers.append(tr('registry.blocker_documents', id=lock.exchange_id))
        for model in (ProjectBootstrapRow, ProjectImportRow):
            blockers += [tr('registry.blocker_documents', id=value) for value in session.scalars(
                select(model.id).where(model.root == root, model.status != 'COMPLETED'))]
        return sorted(blockers)

    @staticmethod
    def _documentary_blockers(session, root):
        """Chat proposals and substantive intake conversations: no job, but bound to the composition."""
        from my_harness.storage.models import (
            ChatConversationRow, ChatProposalRow, PlanningConversationRow, PlanningProposalRow, PlanningTurnRow,
        )
        from my_harness.storage.planning import PlanningRepository
        blockers = [tr('registry.blocker_proposal', id=value) for value in session.scalars(
            select(ChatProposalRow.id).join(ChatConversationRow,
                                           ChatConversationRow.id == ChatProposalRow.conversation_id)
            .where(ChatConversationRow.root == root, ChatProposalRow.status == 'PROPOSED'))]
        for conversation in session.scalars(select(PlanningConversationRow).where(
                PlanningConversationRow.root == root, PlanningConversationRow.kind != 'phase_planning')):
            turns = session.execute(select(PlanningTurnRow.status, PlanningTurnRow.result).where(
                PlanningTurnRow.conversation_id == conversation.id)).all()
            # A completed failure with no output or draft changes is not adoptable work.
            # Keeping it as a barrier prevents correcting the client timeout after onboarding fails.
            empty_failures = bool(turns) and all(_empty_failed_intake_turn(*turn) for turn in turns)
            empty_failures = (empty_failures and not conversation.known and not conversation.log
                              and not conversation.deferred
                              and session.scalar(select(PlanningProposalRow.id).where(
                                  PlanningProposalRow.conversation_id == conversation.id).limit(1)) is None)
            if (not PlanningRepository._drafts_created(session, conversation) and turns
                    and not empty_failures):
                blockers.append(tr('registry.blocker_conversation', id=conversation.id))
        return blockers

    def configuration_blockers(self, root):
        with self._read() as session:
            return self._configuration_blockers(session, root)

    def _supersede_plans(self, session, root, version):
        from my_harness.storage.models import PlanningConversationRow as Conversation, PlanningProposalRow as Proposal
        for proposal in session.scalars(select(Proposal).join(Conversation,
                Conversation.id == Proposal.conversation_id).where(
                    Conversation.root == root, Conversation.kind == 'phase_planning', Proposal.status == 'PROPOSED')):
            proposal.status, proposal.version = 'SUPERSEDED', proposal.version + 1
            proposal.decision = {'decision': 'configuration_changed', 'registry_version': version,
                                 'actor': actor(), 'at': self.managed._now()}
            conversation = session.get(Conversation, proposal.conversation_id)
            conversation.version += 1
            conversation.updated_at = self.managed._now()

    def replay(self, project_id, expected_version, preview_sha256):
        """The already applied confirmation (same preview, next version) is returned as is."""
        with self._read() as session:
            row = session.get(Row, project_id)
            if row is None or row.version != expected_version + 1:
                return None
            event = session.scalar(select(Event).where(Event.project_id == project_id,
                                                       Event.version == row.version))
            return view(row) if event is not None and event.preview_sha256 == preview_sha256 else None

    def apply(self, action, project_id, *, expected_version, row, row_sha256, profile, preview_sha256,
              trust=None, reason=None, protect_agents=False, work_language=None):
        with self.managed._write() as session:
            current = session.get(Row, project_id)
            if (current.version if current else 0) != expected_version:
                raise RegistryConflict('stale_version', tr('registry.stale_preview'))
            now = self.managed._now()
            if action == 'register':
                from my_harness.storage.project_creation import CreationRepository
                CreationRepository.conflicts(session, project_id, row['root'])
                if current is not None:
                    raise RegistryConflict('duplicate_id', tr('registry.id_registered', id=project_id))
                if session.scalar(select(Row.id).where(Row.root == row['root'], Row.status == 'ACTIVE')):
                    raise RegistryConflict('root_taken', tr('registry.root_registered'))
                current = Row(id=project_id, version=1, status='ACTIVE', root=row['root'],
                              composition=row['composition'], profile=profile, row=row, row_sha256=row_sha256,
                              trust=trust, created_at=now, updated_at=now)
                session.add(current)
                previous = None
                if work_language is not None:
                    confirm_work_language(session, project_id, row['root'], work_language, 'registration',
                                          preview_sha256, reason, now)
            else:
                if current is None:
                    raise LookupError(tr('registry.unknown'))
                if current.status != 'ACTIVE':
                    raise RegistryConflict('retired', tr('registry.retired'))
                unfinished = self._unfinished(session, current.root)
                if unfinished:
                    raise RegistryConflict('pending_jobs', tr('registry.unfinished', jobs=unfinished))
                if protect_agents:
                    blockers = self._configuration_blockers(session, current.root)
                    if blockers:
                        raise RegistryConflict('pending_configuration', '; '.join(blockers))
                    self._supersede_plans(session, current.root, expected_version + 1)
                previous = current.row_sha256
                current.version += 1
                current.updated_at = now
                if action == 'retire':
                    current.status = 'RETIRED'
                else:
                    current.composition, current.profile = row['composition'], profile
                    current.row, current.row_sha256 = row, row_sha256
            session.flush()
            session.add(Event(project_id=project_id, version=current.version, action=action, row=current.row,
                              row_sha256=current.row_sha256, previous_sha256=previous, preview_sha256=preview_sha256,
                              actor=actor(), reason=reason, recorded_at=now))
            return view(current)
