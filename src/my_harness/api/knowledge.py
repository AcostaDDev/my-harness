"""P002-T005 (D286): owner routes of the typed knowledge operations.

Every route calls the same `DomainOperations.execute` pipeline as graphs and (from T008) the tool broker, with the
catalogue reference of its operation and an owner caller bound from the local session; no body field can name a
project, role, origin or actor. Reads are addressed by the persisted knowledge project and need neither the
runtime's project map nor a checkout, so they also serve restored query-only copies. Mutations and the adoption
preview stay under the registered project, require `Idempotency-Key` (mutations) and keep the session, Host/Origin,
CSRF and `restored_read_only` guards of `/api/managed`.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path

from my_harness.api.managed import ERRORS, IdempotencyKey, Limit, Offset
from my_harness.api.schemas import (
    IntakeStageCreate, IntakePreviewCreate, IntakeAdoptCreate, KnowledgeAdoptCreate, KnowledgeAdoptRead, KnowledgeDocument, KnowledgeDraftChangesCreate,
    KnowledgeDraftChangesRead, KnowledgeDraftDiscardRead, KnowledgeDraftOpenCreate, KnowledgeDraftOpenRead,
    KnowledgeDraftRead, KnowledgeHeadRead, KnowledgeItemRead, KnowledgeItemsRead, KnowledgeKind, KnowledgePreviewRead,
    KnowledgeProjectsRead, JudgeRequestRead, JudgeRequestsRead,
    StandingPermissionsRead, StandingPermissionRequestCreate, StandingPermissionRequestRead,
    StandingPermissionPreviewCreate, StandingPermissionPreviewRead, StandingPermissionResponseCreate, StandingPermissionResponseRead,
)
from my_harness.api.security import local_request, problem
from my_harness.core.engine.domain_catalogue import CATALOGUE
from my_harness.i18n import message
from my_harness.services.domain_operations import DomainRefusal, owner_reader, owner_writer
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage.preferences import language

Number = Annotated[int, Path(ge=1, le=2 ** 31)]


def knowledge_router(runtime: ManagedRuntime) -> APIRouter:
    router = APIRouter(prefix='/api/managed', dependencies=[Depends(local_request)], responses=ERRORS)

    def run(caller, operation_id: str, arguments: dict, key: str | None = None) -> dict:
        try:
            return runtime.domain_operations().execute(
                caller, CATALOGUE.current(operation_id).ref, arguments, key).body()
        except DomainRefusal as refusal:
            raise problem(refusal.status, refusal.code,
                          message(f'domain.{refusal.code}', language(runtime.engine), **refusal.params)) from None

    def registered(project_id: str):
        try:
            return owner_writer(str(runtime.project(project_id).context.root))
        except (LookupError, RuntimeError):
            raise problem(404, 'project_unregistered',
                          message('domain.project_unregistered', language(runtime.engine))) from None

    @router.get('/knowledge/projects/{knowledge_project_id}/permissions', response_model=StandingPermissionsRead,
                operation_id='standing_permissions')
    def standing_permissions(knowledge_project_id: str):
        return run(owner_reader(knowledge_project_id), 'permissions.inspect', {})

    @router.get('/projects/{project_id}/permissions', response_model=StandingPermissionsRead,
                operation_id='project_standing_permissions')
    def project_permissions(project_id: str):
        return run(registered(project_id), 'permissions.inspect', {})

    @router.post('/projects/{project_id}/permissions/requests', response_model=StandingPermissionRequestRead,
                 operation_id='standing_permission_request')
    def permission_request(project_id: str, body: StandingPermissionRequestCreate, idempotency_key: IdempotencyKey):
        return run(registered(project_id), 'permissions.request', body.model_dump(), idempotency_key)

    @router.post('/projects/{project_id}/permissions/preview', response_model=StandingPermissionPreviewRead,
                 operation_id='standing_permission_preview')
    def permission_preview(project_id: str, body: StandingPermissionPreviewCreate):
        return run(registered(project_id), 'permissions.preview', body.model_dump())

    @router.post('/projects/{project_id}/permissions/responses', response_model=StandingPermissionResponseRead,
                 operation_id='standing_permission_response')
    def permission_response(project_id: str, body: StandingPermissionResponseCreate, idempotency_key: IdempotencyKey):
        return run(registered(project_id), 'permissions.respond', body.model_dump(), idempotency_key)

    @router.post('/projects/{project_id}/intake/stage', response_model=dict, operation_id='intake_stage')
    def intake_stage(project_id: str, body: IntakeStageCreate, idempotency_key: IdempotencyKey):
        return run(registered(project_id), 'intake.stage', body.model_dump(), idempotency_key)

    @router.post('/projects/{project_id}/intake/preview', response_model=dict, operation_id='intake_preview')
    def intake_preview(project_id: str, body: IntakePreviewCreate):
        return run(registered(project_id), 'intake.preview', body.model_dump())

    @router.post('/projects/{project_id}/intake/adopt', response_model=dict, operation_id='intake_adopt')
    def intake_adopt(project_id: str, body: IntakeAdoptCreate, idempotency_key: IdempotencyKey):
        return run(registered(project_id), 'intake.adopt', body.model_dump(), idempotency_key)

    @router.get('/knowledge/projects', response_model=KnowledgeProjectsRead, operation_id='knowledge_projects')
    def projects(offset: Offset = 0, limit: Limit = 50):
        """Persisted knowledge projects, including those of restored archives and unregistered roots."""
        return run(owner_reader(), 'knowledge.projects', {'offset': offset, 'limit': limit})

    @router.get('/knowledge/projects/{knowledge_project_id}', response_model=KnowledgeHeadRead,
                operation_id='knowledge_head')
    def head(knowledge_project_id: str):
        return run(owner_reader(knowledge_project_id), 'knowledge.head', {})

    @router.get('/knowledge/projects/{knowledge_project_id}/revisions/{number}/items',
                response_model=KnowledgeItemsRead, operation_id='knowledge_items')
    def items(knowledge_project_id: str, number: Number,
              kind: KnowledgeKind | None = None, document: KnowledgeDocument | None = None, offset: Offset = 0,
              limit: Limit = 50):
        arguments = {'revision': number, 'offset': offset, 'limit': limit}
        if kind is not None:
            arguments['kind'] = kind
        if document is not None:
            arguments['document'] = document
        return run(owner_reader(knowledge_project_id), 'knowledge.list', arguments)

    @router.get('/knowledge/projects/{knowledge_project_id}/revisions/{number}/items/{item_id}',
                response_model=KnowledgeItemRead, operation_id='knowledge_item')
    def item(knowledge_project_id: str, number: Number, item_id: str):
        return run(owner_reader(knowledge_project_id), 'knowledge.get', {'revision': number, 'item_id': item_id})

    @router.get('/knowledge/projects/{knowledge_project_id}/drafts/{draft_id}', response_model=KnowledgeDraftRead,
                operation_id='knowledge_draft')
    def draft(knowledge_project_id: str, draft_id: str):
        return run(owner_reader(knowledge_project_id), 'knowledge.draft.get', {'draft_id': draft_id})

    @router.post('/projects/{project_id}/knowledge/drafts', response_model=KnowledgeDraftOpenRead, status_code=201,
                 operation_id='knowledge_draft_open')
    def draft_open(project_id: str, body: KnowledgeDraftOpenCreate, idempotency_key: IdempotencyKey):
        return run(registered(project_id), 'knowledge.draft.open', body.model_dump(), idempotency_key)

    @router.post('/projects/{project_id}/knowledge/drafts/{draft_id}/changes',
                 response_model=KnowledgeDraftChangesRead, operation_id='knowledge_draft_apply')
    def draft_apply(project_id: str, draft_id: str, body: KnowledgeDraftChangesCreate,
                    idempotency_key: IdempotencyKey):
        arguments = {'draft_id': draft_id, 'expected_draft_sha256': body.expected_draft_sha256,
                     'changes': [change.model_dump(exclude_unset=True) for change in body.changes]}
        return run(registered(project_id), 'knowledge.draft.apply', arguments, idempotency_key)

    @router.post('/projects/{project_id}/knowledge/drafts/{draft_id}/discard',
                 response_model=KnowledgeDraftDiscardRead, operation_id='knowledge_draft_discard')
    def draft_discard(project_id: str, draft_id: str, idempotency_key: IdempotencyKey):
        return run(registered(project_id), 'knowledge.draft.discard', {'draft_id': draft_id}, idempotency_key)

    @router.post('/projects/{project_id}/knowledge/drafts/{draft_id}/adoption/preview',
                 response_model=KnowledgePreviewRead, operation_id='knowledge_adoption_preview')
    def preview(project_id: str, draft_id: str):
        """Classified changes and the hash an adoption must confirm; nothing is written."""
        return run(registered(project_id), 'knowledge.adoption.preview', {'draft_id': draft_id})

    @router.post('/projects/{project_id}/knowledge/drafts/{draft_id}/adopt', response_model=KnowledgeAdoptRead,
                 operation_id='knowledge_adopt')
    def adopt(project_id: str, draft_id: str, body: KnowledgeAdoptCreate, idempotency_key: IdempotencyKey):
        """`owner_confirmed` adoption of the exact previewed draft; a reason is required for sensitive changes."""
        arguments = {'draft_id': draft_id, **body.model_dump(exclude_unset=True)}
        arguments.setdefault('reason', None)
        return run(registered(project_id), 'knowledge.adopt', arguments, idempotency_key)

    @router.get('/knowledge/projects/{knowledge_project_id}/judge/requests',
                response_model=JudgeRequestsRead, operation_id='judge_requests')
    def judge_requests(knowledge_project_id: str, offset: Offset = 0, limit: Limit = 50):
        try:
            return runtime.judges().list(knowledge_project_id, offset=offset, limit=limit)
        except LookupError:
            raise problem(404, 'judge_not_found', message('judge.not_found', language(runtime.engine))) from None

    @router.get('/knowledge/projects/{knowledge_project_id}/judge/requests/{request_id}',
                response_model=JudgeRequestRead, operation_id='judge_request')
    def judge_request(knowledge_project_id: str, request_id: str):
        try:
            return runtime.judges().read(knowledge_project_id, request_id)
        except LookupError:
            raise problem(404, 'judge_not_found', message('judge.not_found', language(runtime.engine))) from None

    return router
