"""D088: preparation and adoption of the documentary closure over the existing operations."""

from sqlalchemy import select

from my_harness.core.engine.document_ops import preview_transition
from my_harness.core.engine.phases import document_hashes
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PhaseRow as Phase
from my_harness.i18n import tr


def prepare(context, state, git):
    if git is None:
        raise Conflict(tr('phases.unified_phase_closure_requires'))
    try:
        if state.get('structured'):
            from my_harness.storage.structured_phases import closure_preview
            return closure_preview(context, state, git)
        return preview_transition(context, state, git, None, unified=True)
    except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
        raise Conflict(str(exc)) from exc


def adopt(managed, session, run, op, phase, outcome):
    from my_harness.storage.documents import observed_documents, verify_committed
    from my_harness.storage.phases import insert_phase
    verify_committed(op, outcome)
    shown = op.request['preview']
    context = None if outcome.get('published_recovery') else observed_documents(run, shown)
    if shown.get('structured'):
        from my_harness.storage.structured_phases import complete_export
        complete_export(session, phase, op, outcome)
    phase.status = outcome['status']
    session.flush()  # releases the single-open-phase constraint before creating N+1
    following = shown['next']
    if following:
        if session.scalar(select(Phase.id).where(Phase.root == phase.root, Phase.code == following['code'])):
            raise Conflict(tr('phases.successor_already_exists_reconcile'))
        outcome = {**outcome, 'next_phase_id': insert_phase(
            managed, session, phase.root, following, {} if shown.get('structured') else document_hashes(context, following['documents']),
            source={'kind': 'closure', 'operation_id': op.id, 'from_phase': phase.code, 'commit': outcome['commit']})}
    run.status, run.stage = 'COMMITTED', 'committed'
    return outcome
