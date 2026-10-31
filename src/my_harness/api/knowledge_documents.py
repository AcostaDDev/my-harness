"""D294 explicit project document exchange; archive consultation has no mutation routes enabled."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from my_harness.api.security import local_request, problem
from my_harness.api.managed import IdempotencyKey, ERRORS
from my_harness.api.schemas import (KnowledgeDocumentStageCreate, KnowledgeDocumentConsentCreate,
    KnowledgeDocumentRecordCreate, KnowledgeOwnershipPrepareCreate, KnowledgeDeliveryCreate, KnowledgeExchangeRead, KnowledgeDocumentsBundleRead)
from my_harness.core.engine.domain_catalogue import CATALOGUE
from my_harness.core.engine import knowledge_documents as d
from my_harness.services.domain_operations import owner_writer, DomainRefusal
from my_harness.services.knowledge_delivery import baseline, KnowledgeDelivery
from my_harness.storage.preferences import language
from my_harness.i18n import message


def knowledge_documents_router(runtime):
    router = APIRouter(prefix='/api/managed/projects/{project_id}/knowledge/documents',
                       dependencies=[Depends(local_request)], responses=ERRORS)

    def project(ident):
        try:
            return runtime.project(ident)
        except (LookupError, RuntimeError):
            raise problem(404, 'project_unregistered', message('domain.project_unregistered', language(runtime.engine))) from None

    def run(ident, operation, arguments, key=None):
        bound = project(ident)
        try:
            return runtime.domain_operations().execute(owner_writer(str(bound.context.root)),
                        CATALOGUE.current(operation).ref, arguments, key).body()
        except DomainRefusal as exc:
            raise problem(exc.status, exc.code, message('domain.' + exc.code, language(runtime.engine), **exc.params)) from None

    def previous(project_id, operation, key):
        from my_harness.storage.models import DomainCommandRow, KnowledgeProjectRow
        bound = project(project_id)
        with Session(runtime.engine) as session:
            scope = session.scalar(select(KnowledgeProjectRow.id).where(KnowledgeProjectRow.root == str(bound.context.root)))
            row = session.scalar(select(DomainCommandRow).where(DomainCommandRow.knowledge_project_id == scope,
                DomainCommandRow.scope == owner_writer(str(bound.context.root)).scope,
                DomainCommandRow.idempotency_key == key, DomainCommandRow.outcome == 'ACCEPTED'))
            if row is not None and row.operation_id != operation:
                raise problem(409, 'idempotency_conflict', message('domain.idempotency_conflict', language(runtime.engine)))
            return row.result if row else None

    def external(action):
        try:
            return action()
        except (ValueError, OSError, RuntimeError) as exc:
            raise problem(409, 'document_exchange_refused', message('documents.refused', language(runtime.engine), detail=str(exc))) from None

    @router.get('/bundle', response_model=KnowledgeDocumentsBundleRead, operation_id='knowledge_documents_bundle')
    def bundle(project_id: str):
        return {'result': run(project_id, 'documents.bundle', {})}

    @router.post('/stage', response_model=KnowledgeExchangeRead, operation_id='knowledge_documents_stage')
    def stage(project_id: str, body: KnowledgeDocumentStageCreate, idempotency_key: IdempotencyKey):
        return {'result': run(project_id, 'documents.stage', body.model_dump(), idempotency_key)}

    @router.post('/preview', response_model=KnowledgeExchangeRead, operation_id='knowledge_documents_preview')
    def preview(project_id: str, body: KnowledgeDocumentRecordCreate):
        return {'result': run(project_id, 'documents.preview', body.model_dump())}

    @router.post('/adopt', response_model=KnowledgeExchangeRead, operation_id='knowledge_documents_adopt')
    def adopt(project_id: str, body: KnowledgeDocumentConsentCreate, idempotency_key: IdempotencyKey):
        return {'result': run(project_id, 'documents.adopt', body.model_dump(), idempotency_key)}

    @router.post('/ownership/preview', response_model=KnowledgeExchangeRead, operation_id='knowledge_ownership_preview')
    def ownership_preview(project_id: str, body: KnowledgeOwnershipPrepareCreate, idempotency_key: IdempotencyKey):
        bound = project(project_id)
        wrappers = sorted(body.wrappers)
        prior = previous(project_id, 'documents.ownership.prepare', idempotency_key)
        if prior:
            selected = sorted(w for w in ('claude', 'gemini') if d.INSTRUCTIONS[w] in prior['files'])
            if wrappers != selected:
                raise problem(409, 'idempotency_conflict', message('domain.idempotency_conflict', language(runtime.engine)))
            return {'result': run(project_id, 'documents.ownership.prepare',
                    {'payload': d.freeze({'wrappers': wrappers, 'baseline': prior['baseline']})}, idempotency_key)}
        manifest = d.ownership('preview', bound.context.work_language or 'en', wrappers)
        captured = external(lambda: baseline(bound.context.root, [t['path'] for t in manifest['targets']]))
        return {'result': run(project_id, 'documents.ownership.prepare',
                               {'payload': d.freeze({'wrappers': wrappers, 'baseline': captured})}, idempotency_key)}

    @router.post('/ownership/adopt', response_model=KnowledgeExchangeRead, operation_id='knowledge_ownership_adopt')
    def ownership_adopt(project_id: str, body: KnowledgeDocumentConsentCreate, idempotency_key: IdempotencyKey):
        return {'result': run(project_id, 'documents.ownership.adopt', body.model_dump(), idempotency_key)}

    @router.post('/export/preview', response_model=KnowledgeExchangeRead, operation_id='knowledge_export_preview')
    def export_preview(project_id: str, body: KnowledgeDocumentRecordCreate, idempotency_key: IdempotencyKey):
        # record_id identifies the adopted ownership displayed by the client; rechecked in the command.
        bound = project(project_id)
        prior = previous(project_id, 'documents.export.prepare', idempotency_key)
        if prior:
            captured = {**prior['baseline'], 'ownership_id': body.record_id}
            return {'result': run(project_id, 'documents.export.prepare', {'payload': d.freeze(captured)}, idempotency_key)}
        download = run(project_id, 'documents.bundle', {})
        files = download['files']
        if files is None:
            raise problem(409, 'document_exchange_refused', message('documents.refused', language(runtime.engine),
                         detail=download['render_error']))
        captured = external(lambda: baseline(bound.context.root, files))
        captured['ownership_id'] = body.record_id
        return {'result': run(project_id, 'documents.export.prepare', {'payload': d.freeze(captured)}, idempotency_key)}

    @router.post('/export', response_model=KnowledgeExchangeRead, operation_id='knowledge_export_deliver')
    def export(project_id: str, body: KnowledgeDeliveryCreate, idempotency_key: IdempotencyKey):
        bound = project(project_id)
        summary = run(project_id, 'knowledge.head', {})
        if runtime.config is None or runtime.config.commit_factory is None:
            raise problem(409, 'document_exchange_refused', message('documents.writer_required', language(runtime.engine)))
        writer = runtime.config.commit_factory(bound.context, dict(bound.versions))
        return {'result': external(lambda: KnowledgeDelivery(runtime.engine, bound.context.root, summary['knowledge_project_id'])
            .execute(body.record_id, body.preview_sha256, writer.identity, writer_stopped=body.writer_stopped, key=idempotency_key))}

    @router.get('/records/{record_id}', response_model=KnowledgeExchangeRead, operation_id='knowledge_exchange_status')
    def status(project_id: str, record_id: str):
        bound = project(project_id)
        summary = run(project_id, 'knowledge.head', {})
        return {'result': external(lambda: KnowledgeDelivery(runtime.engine, bound.context.root, summary['knowledge_project_id']).status(record_id))}

    return router
