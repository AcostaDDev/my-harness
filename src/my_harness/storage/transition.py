"""D072/H6.3: phase transition over existing phase operations and jobs; SQLite is the authority.

After CLOSED (or ABANDONED) and without touching the D032 closure: archives the phase by bytes, opens
fresh STATE/NEXT_STEPS and installs the next ROADMAP phase in a single reconcilable commit.
The new phase is created in the transaction that records the result, together with its adopted base.
"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.document_ops import TERMINAL, preview_transition
from my_harness.core.engine.phases import document_hashes
from my_harness.storage.documents import (
    _resume_job, abort_operation, latest_phase, observed_documents, pending, phases_snapshot,
    record_operation_intent, summary_snapshot, unresolved, verify_committed,
)
from my_harness.storage.managed import Conflict, _job
from my_harness.storage.models import ManagedRunRow as Run, PhaseOperationRow as Operation, PhaseRow as Phase
from my_harness.storage.permissions import actor
from my_harness.storage.phases import PhaseRepository, _event, _latest, _operation, insert_phase
from my_harness.i18n import tr


def snapshot(session, phase) -> dict:
    """SQLite authority that the preview freezes: finished phase, states, check and summary."""
    check = _latest(session, phase.id, 'check')
    result = (check.result or {}) if check is not None else {}
    codes = sorted(session.scalars(select(Phase.code).where(Phase.root == phase.root)).all())
    return {'phase': {'id': phase.id, 'code': phase.code, 'status': phase.status, 'definition': phase.definition,
                      'definition_number': phase.definition_number, 'documents': phase.documents},
            'phases': phases_snapshot(session, phase.root),
            'check': None if check is None else {
                'status': check.status, 'result': result.get('result'), 'reasons': result.get('reasons') or [],
                'binding': result.get('binding'), 'binding_sha256': result.get('binding_sha256'),
                'validation': result.get('validation')},
            'summary': summary_snapshot(session, phase), 'existing_codes': codes}


def reviewed(session, phase, stored) -> bool:
    """Is the reviewed authority still current? A preview from before H6.4 did not freeze consumption: it is compared
    without it and exactly what was reviewed is written."""
    current = snapshot(session, phase)
    if 'consumption' not in stored['summary']:
        current = {**current, 'summary': {k: v for k, v in current['summary'].items() if k != 'consumption'}}
    return current == stored


def _phase(session, context, phase_id, expected=None):
    from my_harness.storage.knowledge_exchange import require_documentary_lane
    require_documentary_lane(session, context.root)
    phase = session.get(Phase, phase_id)
    if phase is None or phase.root != str(context.root):
        raise LookupError(tr('export.unknown_phase_checkout'))
    if expected is not None and (type(expected) is not int or phase.version != expected):
        raise Conflict(tr('transition.phase_changed_reload_before'))
    if latest_phase(session, phase.root).id != phase.id:
        raise Conflict(tr('transition.latest_phase_checkout_archived'))
    if phase.status not in TERMINAL:
        raise Conflict(tr('transition.close_abandon_phase_before'))
    if PhaseRepository._root_pending(session, phase.root):
        raise Conflict(tr('transition.checkout_has_unfinished_jobs'))
    return phase


class TransitionRepository:
    def __init__(self, managed):
        self.managed = managed

    def _retired(self):
        raise Conflict(tr('transition.separate_phase_transitions_retired'))

    def preview(self, context, phase_id, git, next_steps=None, plan_proposal=None):
        """`plan_proposal` (H6.5): exact reference to a plan proposed in `phase_planning`, instead of the text."""
        origin = None
        with Session(self.managed.engine) as session:
            phase = _phase(session, context, phase_id)
            stored = pending(session, phase, 'transition')
            if stored is not None:
                return {**stored.request['preview'], 'expected_version': phase.version,
                        'resume_operation_id': stored.id}
            self._retired()
            if unresolved(session, phase.root):
                raise Conflict(tr('managed.document_intent_awaits_reconciliation'))
            if plan_proposal is not None:
                if next_steps is not None:
                    raise ValueError(tr('transition.provide_either_plan_text'))
                from my_harness.storage.planning import PlanningRepository
                next_steps, origin = PlanningRepository(self.managed).plan(session, context, phase.id, plan_proposal)
            state, version = snapshot(session, phase), phase.version
        try:
            shown = preview_transition(context, state, git, next_steps, origin)
        except (ValueError, OSError, UnicodeError, RuntimeError) as exc:  # RuntimeError: Git capture/sealing
            raise Conflict(str(exc)) from exc
        return {**shown, 'expected_version': version, 'resume_operation_id': None}

    def submit(self, context, phase_id, expected, *, key, versions, preview_sha256, reason, confirmed, git,
               next_steps=None, resume_operation_id=None, plan_proposal=None):
        if confirmed is not True or not isinstance(reason, str) or not reason.strip():
            raise ValueError(tr('export.explicit_confirmation_exact_diff'))
        marker = freeze({'action': 'phase_transition', 'phase_id': phase_id, 'expected_version': expected,
                         'preview_sha256': preview_sha256, 'reason': reason, 'confirmed': confirmed,
                         'resume_operation_id': resume_operation_id,
                         **({'plan_proposal': plan_proposal} if plan_proposal is not None else {})})
        with Session(self.managed.engine) as session:
            existing = self.managed._existing(session, key, marker)
            if existing:
                return _job(existing)
        try:
            shown = self.preview(context, phase_id, git, next_steps, plan_proposal)
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
            phase = _phase(session, context, phase_id, expected)
            if shown['expected_version'] != expected:
                raise Conflict(tr('export.phase_changed_since_preview'))
            if resume_operation_id is not None:
                op = pending(session, phase, 'transition')
                if op is None or op.id != resume_operation_id:
                    raise Conflict(tr('transition.exact_interrupted_transition_intent'))
                job = _resume_job(self.managed, session, op, context, versions, key, marker, assessment,
                                  'phase_transition')
            else:
                if unresolved(session, phase.root):
                    raise Conflict(tr('managed.document_intent_awaits_reconciliation'))
                if snapshot(session, phase) != shown['snapshot']:
                    raise Conflict(tr('export.sqlite_authority_changed_after_2'))
                job = self.managed._queue_new_run(session, assessment, context, versions, f'{phase.code}-TRANSITION',
                                                  phase.code, key, marker, purpose='phase_transition')
                saved = {k: v for k, v in shown.items() if k not in ('expected_version', 'resume_operation_id')}
                op = Operation(id=str(uuid4()), phase_id=phase.id, kind='transition', run_id=job.run_id,
                               status='QUEUED', previous_status=phase.status, created_at=self.managed._now(),
                               request={'preview': saved, 'actor': actor(), 'reason': reason})
                session.add(op)
                if shown.get('plan_origin') is not None:
                    # The proposed plan becomes accepted with the transition that uses it, in the same transaction.
                    from my_harness.storage.planning import PlanningRepository
                    PlanningRepository(self.managed).mark_plan(session, shown['plan_origin'], job.run_id, job.id)
            _event(self.managed, session, phase, 'phase_transition_queued', {
                'operation_id': op.id, 'run_id': job.run_id, 'job_id': job.id, 'preview_sha256': preview_sha256,
                'next': (shown['next'] or {}).get('code'), 'actor': actor(), 'reason': reason})
            return job

    def request(self, run_id):
        with Session(self.managed.engine) as session:
            op, phase = _operation(session, session.get(Run, run_id))
            if op.kind != 'transition' or op.status != 'QUEUED':
                raise Conflict('Transition requires its queued operation')
            if not op.request.get('commit_intent') and not reviewed(session, phase, op.request['preview']['snapshot']):
                raise Conflict(tr('transition.sqlite_authority_changed_after'))
            return {**op.request, 'operation_id': op.id}



def record_intent(managed, session, run, intent):
    def matches(session, phase):
        op, _ = _operation(session, run)
        return reviewed(session, phase, op.request['preview']['snapshot'])
    record_operation_intent(managed, session, run, intent, 'transition', matches)


def settle(managed, session, run, outcome):
    op, phase = _operation(session, run)
    if op.status not in ('QUEUED', 'INTENT'):
        raise Conflict('Transition already settled')
    shown = op.request['preview']
    if outcome['status'] == 'COMMITTED':
        verify_committed(op, outcome)
        context = observed_documents(run, shown)
        following = shown['next']
        if following is not None:
            if session.scalar(select(Phase.id).where(Phase.root == phase.root, Phase.code == following['code'])):
                raise Conflict(tr('transition.phase_already_exists_recover', code=following['code']))
            if session.scalar(select(Phase.id).where(Phase.root == phase.root, Phase.status.notin_(TERMINAL))):
                raise Conflict(tr('transition.another_phase_open_recover'))
            documents = document_hashes(context, following['documents'])
            outcome = {**outcome, 'next_phase_id': insert_phase(
                managed, session, phase.root, following, documents,
                source={'kind': 'transition', 'operation_id': op.id, 'from_phase': phase.code,
                        'commit': outcome['commit']})}
        run.status, run.stage = 'COMMITTED', 'committed'
    op.status, op.result, op.finished_at = outcome['status'], outcome, managed._now()
    _event(managed, session, phase, 'phase_transitioned' if outcome['status'] == 'COMMITTED'
           else 'phase_transition_invalidated', {'operation_id': op.id, 'archive': shown['archive'], **outcome})


def abort(managed, session, run, status, reason):
    abort_operation(managed, session, run, status, reason, 'transition')
