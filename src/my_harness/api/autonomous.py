"""P002-T016 (D276, D299): minimal per-project controls of autonomous roadmap runs.

Start (readiness, owner answers to readiness gaps, preview, owner confirmation by exact hash), status, events and questions, answer, pause, resume,
revoke, recover and a new authorization revision. Every mutation is an ordinary guarded command with fresh checks
and the local-request guard; refusals are 409 with the stable refusal code. There is no global inbox here (T017).
"""
from fastapi import APIRouter, Depends

from my_harness.api.managed import ERRORS, IdempotencyKey, Limit, Offset, call
from my_harness.api.schemas import (
    AutonomousAnswerCreate, AutonomousConfirmCreate, AutonomousGapAnswerCreate, AutonomousGapAnswerRead, AutonomousEventRead, AutonomousPreviewRead,
    AutonomousQuestionRead, AutonomousReadinessRead, AutonomousReasoned, AutonomousRecoverCreate, AutonomousRequest,
    AutonomousRunRead, AutonomousVersioned,
)
from my_harness.api.security import local_request, problem
from my_harness.core.engine.autonomy import AutonomyRefusal
from my_harness.i18n import message
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage.preferences import language


def autonomous_router(runtime: ManagedRuntime) -> APIRouter:
    router = APIRouter(prefix='/api/managed/projects/{project_id}/autonomous', dependencies=[Depends(local_request)],
                       responses=ERRORS)

    def guarded(operation, /, *args, **kwargs):
        def run():
            try:
                return operation(*args, **kwargs)
            except AutonomyRefusal as error:  # before ValueError in `call`: stable refusal codes
                raise problem(409, error.code, message('autonomy.refused', language(runtime.engine),
                                                       reason=error.code)) from error
        return call(run)

    def scoped(project_id):
        project = call(runtime.project, project_id)
        return project, runtime.autonomous_roadmap()

    def plain(body: AutonomousRequest) -> dict:
        data = body.model_dump()
        data['caps'] = {k: v for k, v in data['caps'].items() if v is not None}
        if data['delegation']['duration_ceiling'].get('seconds') is None:
            data['delegation']['duration_ceiling'].pop('seconds', None)
        return data

    @router.post('/readiness', response_model=AutonomousReadinessRead, operation_id='autonomous_readiness')
    def readiness(project_id: str, body: AutonomousRequest):
        project, service = scoped(project_id)
        report = guarded(service.readiness, project.context.root, plain(body))
        return {**report, 'pending_gates': report.get('pending_gates', report['gates']['pending_gates'])}

    @router.post('/preview', response_model=AutonomousPreviewRead, operation_id='autonomous_preview')
    def preview(project_id: str, body: AutonomousRequest):
        project, service = scoped(project_id)
        return guarded(service.preview, project.context.root, plain(body))

    @router.post('/gaps/answer', response_model=AutonomousGapAnswerRead, status_code=201,
                 operation_id='autonomous_gap_answer')
    def gap_answer(project_id: str, body: AutonomousGapAnswerCreate, idempotency_key: IdempotencyKey):
        project, service = scoped(project_id)
        return guarded(service.answer_gap, project.context.root, gap_sha256=body.gap_sha256, text=body.text,
                       key=idempotency_key)

    @router.post('/confirm', response_model=AutonomousRunRead, status_code=201, operation_id='autonomous_confirm')
    def confirm(project_id: str, body: AutonomousConfirmCreate, idempotency_key: IdempotencyKey):
        project, service = scoped(project_id)
        return guarded(service.confirm, project.context.root, plain(body.request),
                       preview_sha256=body.preview_sha256, key=idempotency_key, reason=body.reason,
                       confirmed=body.confirmed, acknowledgement_version=body.acknowledgement_version)

    @router.get('', response_model=AutonomousRunRead, operation_id='autonomous_status')
    def status(project_id: str):
        project, service = scoped(project_id)
        found = guarded(service.status, project.context.root)
        if found is None:
            raise problem(404, 'not_found', message('autonomy.refused', language(runtime.engine), reason='no_run'))
        return found

    @router.get('/runs/{run_id}/events', response_model=list[AutonomousEventRead], operation_id='autonomous_events')
    def events(project_id: str, run_id: str, after: Offset = 0, limit: Limit = 100):
        project, service = scoped(project_id)
        return guarded(service.events, project.context.root, run_id, after=after, limit=limit)

    @router.get('/runs/{run_id}/questions', response_model=list[AutonomousQuestionRead],
                operation_id='autonomous_questions')
    def questions(project_id: str, run_id: str):
        project, service = scoped(project_id)
        run = guarded(service.status_by_id, run_id)
        if run['root'] != str(project.context.root):
            raise problem(404, 'not_found', message('autonomy.refused', language(runtime.engine), reason='no_run'))
        return run['questions']

    @router.post('/runs/{run_id}/questions/{question_id}/answer', response_model=AutonomousQuestionRead,
                 operation_id='autonomous_answer')
    def answer(project_id: str, run_id: str, question_id: str, body: AutonomousAnswerCreate,
               idempotency_key: IdempotencyKey):
        project, service = scoped(project_id)
        return guarded(service.answer, project.context.root, run_id, question_id,
                       expected_version=body.expected_version, answer={'text': body.text, 'choice': body.choice},
                       key=idempotency_key)

    @router.post('/runs/{run_id}/pause', response_model=AutonomousRunRead, operation_id='autonomous_pause')
    def pause(project_id: str, run_id: str, body: AutonomousReasoned):
        project, service = scoped(project_id)
        return guarded(service.pause, project.context.root, run_id, expected_version=body.expected_version,
                       reason=body.reason)

    @router.post('/runs/{run_id}/resume', response_model=AutonomousRunRead, operation_id='autonomous_resume')
    def resume(project_id: str, run_id: str, body: AutonomousVersioned):
        project, service = scoped(project_id)
        return guarded(service.resume, project.context.root, run_id, expected_version=body.expected_version)

    @router.post('/runs/{run_id}/revoke', response_model=AutonomousRunRead, operation_id='autonomous_revoke')
    def revoke(project_id: str, run_id: str, body: AutonomousReasoned):
        project, service = scoped(project_id)
        return guarded(service.revoke, project.context.root, run_id, expected_version=body.expected_version,
                       reason=body.reason)

    @router.post('/runs/{run_id}/recover', response_model=AutonomousRunRead, operation_id='autonomous_recover')
    def recover(project_id: str, run_id: str, body: AutonomousRecoverCreate):
        project, service = scoped(project_id)
        return guarded(service.recover, project.context.root, run_id, expected_version=body.expected_version,
                       writer_stopped=body.writer_stopped, reason=body.reason)

    @router.post('/runs/{run_id}/revise', response_model=AutonomousRunRead, operation_id='autonomous_revise')
    def revise(project_id: str, run_id: str, body: AutonomousConfirmCreate, idempotency_key: IdempotencyKey):
        project, service = scoped(project_id)
        return guarded(service.revise, project.context.root, run_id, plain(body.request),
                       preview_sha256=body.preview_sha256, key=idempotency_key, reason=body.reason,
                       confirmed=body.confirmed, acknowledgement_version=body.acknowledgement_version)

    return router
