"""D088: confirmed plan of an ACTIVE phase without tasks, as a reconcilable documentary edit."""

from sqlalchemy.orm import Session

from my_harness.core.engine.document_ops import read_text, _clean_capture, _sealed_preview
from my_harness.core.engine.document_text import work_language
from my_harness.core.engine.documents import plan_tasks, render_next_steps, render_state, replace_block, require_layout
from my_harness.core.engine.phases import digest, phase_definition, document_hashes
from my_harness.storage.documents import DocumentsRepository, _edit_phase
from my_harness.storage.managed import Conflict
from my_harness.storage.planning import PlanningRepository
from my_harness.i18n import tr


class PhasePlanRepository(DocumentsRepository):
    def __init__(self, managed, phase_id, next_steps=None, plan_proposal=None):
        super().__init__(managed)
        self.phase_id, self.next_steps, self.plan_proposal = phase_id, next_steps, plan_proposal

    def preview(self, context, git, *, source='content', changes=None, regenerate_blocks=False):
        target = require_layout(context)
        origin = None
        with Session(self.managed.engine) as session:
            phase = _edit_phase(session, context, resume=True)
            from my_harness.storage.documents import pending
            stored = pending(session, phase, 'document_edit')
            if stored and stored.request['preview'].get('phase_plan', {}).get('phase_id') == self.phase_id:
                return {**stored.request['preview'], 'resume_operation_id': stored.id}
            _edit_phase(session, context)
            if phase.id != self.phase_id or phase.status != 'ACTIVE' or phase.definition['tasks']:
                raise Conflict(tr('planning.plan_latest_active_phase'))
            plan = self.next_steps
            if self.plan_proposal is not None:
                if plan is not None:
                    raise ValueError(tr('planning.provide_plan_text_proposal'))
                plan, origin = PlanningRepository(self.managed).plan(session, context, phase.id, self.plan_proposal)
            if not isinstance(plan, str) or not plan.strip():
                raise ValueError(tr('planning.provide_next_steps_plan'))
            from my_harness.core.engine.definition import validate_plan
            tasks = validate_plan(plan, phase.code)
            definition = phase_definition(context, {**phase.definition, 'tasks': [task for task, _ in tasks]})
            data = {'phase_id': phase.id, 'definition_sha256': phase.definition_sha256,
                    'definition': definition, 'origin': origin}
            baseline = phase.documents
        if document_hashes(context, baseline) != baseline:
            raise Conflict(tr('planning.phase_documents_changed_externally'))
        fresh = {'phase': {'code': definition['code'], 'status': 'ACTIVE', 'objective': definition['objective']},
                 'tasks': [{'task_id': task, 'status': None, 'planned': True} for task, _ in plan_tasks(plan)],
                 'open_questions': [], 'latest_check': None}
        language = work_language(context)
        content = replace_block(plan, render_next_steps(fresh, language))
        evidence, provenance = _clean_capture(context, git)
        old_state = read_text(context, target.state)
        shown = _sealed_preview(context, evidence, provenance, provenance.worktree_tree, [
            (target.next_steps, read_text(context, target.next_steps), content),
            (target.state, old_state, replace_block(old_state, render_state(fresh, language)))], 'Confirmed phase plan (D088)',
            {'operation': 'document_edit', 'source': 'content', 'phase_plan': data})
        return {**shown, 'resume_operation_id': None}


def verify(session, phase, data):
    return (phase.id == data['phase_id'] and phase.status == 'ACTIVE' and not phase.definition['tasks']
            and phase.definition_sha256 == data['definition_sha256'])


def adopt(managed, session, phase, op, shown, documents, outcome):
    from uuid import uuid4
    from my_harness.storage.models import PhaseDefinitionRow as Definition
    from my_harness.storage.permissions import actor
    from my_harness.storage.phases import _event, _invalidate_batches
    data = shown['phase_plan']
    if not verify(session, phase, data):
        raise Conflict(tr('planning.phase_changed_after_plan'))
    definition = data['definition']
    phase.definition_number += 1
    phase.definition, phase.definition_sha256, phase.documents = definition, digest(definition), documents
    session.add(Definition(id=str(uuid4()), phase_id=phase.id, number=phase.definition_number,
                           definition=definition, definition_sha256=phase.definition_sha256,
                           documents=documents, origin='amended', reason=op.request['reason'], actor=actor(),
                           created_at=managed._now()))
    _invalidate_batches(managed, session, phase, tr('planning.plan_confirmed_reason'))
    _event(managed, session, phase, 'phase_plan_confirmed', {
        'operation_id': op.id, 'definition_number': phase.definition_number, 'commit': outcome['commit']})
