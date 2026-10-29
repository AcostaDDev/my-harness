"""P002-T006 (D287): read-only trace of one graph thread inside one persisted knowledge project.

Addressed by the knowledge project, so it needs neither the runtime's project map nor a checkout or provider and
also serves restored query-only copies; nothing here writes. A thread whose operations belong to another project
answers like a missing one. Pages are bounded; events are ordered by their global sequence; content an event
offloaded is read back by digest.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from my_harness.api.managed import ERRORS, Limit, Offset
from my_harness.api.schemas import TraceArtifactRead, TraceEventsRead, TraceOperationsRead, TraceThreadRead
from my_harness.api.security import local_request, problem
from my_harness.i18n import message
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage.models import KnowledgeProjectRow
from my_harness.storage.preferences import language

After = Annotated[int, Query(ge=0, le=2 ** 53 - 1)]
Sha256 = Annotated[str, Path(pattern='^[0-9a-f]{64}$')]


def trace_router(runtime: ManagedRuntime) -> APIRouter:
    router = APIRouter(prefix='/api/managed/knowledge/projects/{knowledge_project_id}/traces',
                       dependencies=[Depends(local_request)], responses=ERRORS)

    def scoped(knowledge_project_id: str, read):
        with Session(runtime.engine) as session:
            project = session.get(KnowledgeProjectRow, knowledge_project_id)
        try:
            if project is None:
                raise LookupError(knowledge_project_id)
            return read(runtime.operation_journal(), project.root)
        except LookupError:
            raise problem(404, 'trace_unknown', message('journal.trace_unknown', language(runtime.engine))) from None

    @router.get('/{thread_id}', response_model=TraceThreadRead, operation_id='trace_thread')
    def thread(knowledge_project_id: str, thread_id: str):
        return scoped(knowledge_project_id, lambda journal, root: journal.thread(root, thread_id))

    @router.get('/{thread_id}/operations', response_model=TraceOperationsRead, operation_id='trace_operations')
    def operations(knowledge_project_id: str, thread_id: str, offset: Offset = 0, limit: Limit = 50):
        return scoped(knowledge_project_id,
                      lambda journal, root: journal.operations(root, thread_id, offset=offset, limit=limit))

    @router.get('/{thread_id}/events', response_model=TraceEventsRead, operation_id='trace_events')
    def events(knowledge_project_id: str, thread_id: str, after: After = 0, limit: Limit = 100,
               operation_id: str | None = None):
        """Ordered events after the `after` sequence; `operation_id` narrows to one operation."""
        return scoped(knowledge_project_id, lambda journal, root: journal.events(
            root, thread_id, after=after, limit=limit, operation_id=operation_id))

    @router.get('/{thread_id}/artifacts/{sha256}', response_model=TraceArtifactRead, operation_id='trace_artifact')
    def artifact(knowledge_project_id: str, thread_id: str, sha256: Sha256):
        """Content an event of this thread offloaded (`trace-payload-1` references), verified on read."""
        return scoped(knowledge_project_id, lambda journal, root: journal.artifact(root, thread_id, sha256))

    return router
