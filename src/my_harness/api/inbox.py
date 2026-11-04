"""Authenticated inbox reads and the read receipt. Domain responses use their ordinary routes."""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from my_harness.api.managed import ERRORS, Limit
from my_harness.api.schemas import InboxItemDetail, InboxItemRead, InboxKind, InboxMarkRead, InboxMode, InboxPageRead, InboxState
from my_harness.api.security import local_request, problem
from my_harness.i18n import message
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.storage.inbox import Inbox
from my_harness.storage.operation_journal import now
from my_harness.storage.preferences import language

Ref = Annotated[str, Query(min_length=1, max_length=160)]
ItemId = Annotated[str, Path(min_length=1, max_length=160)]


def inbox_router(runtime: ManagedRuntime) -> APIRouter:
    router = APIRouter(prefix='/api/managed/inbox', dependencies=[Depends(local_request)], responses=ERRORS)

    def inbox():
        return Inbox(runtime.engine, {p.id: str(p.context.root) for p in runtime.projects.values()},
                     runtime.repository._now if runtime.repository else now)

    def scoped(read, /, *args, **kwargs):
        try:
            return read(*args, **kwargs)
        except LookupError:
            raise problem(404, 'inbox_not_found', message('inbox.not_found', language(runtime.engine))) from None
        except PermissionError:
            raise problem(409, 'restored_read_only',
                          message('api.restored_read_only', language(runtime.engine))) from None

    @router.get('', response_model=InboxPageRead, operation_id='inbox_page')
    def page(project: Ref | None = None, kind: InboxKind | None = None, state: InboxState | None = None,
             mode: InboxMode | None = None, before: Ref | None = None, limit: Limit = 30):
        return scoped(inbox().page, project, kind=kind, mode=mode, state=state, before=before, limit=limit)

    @router.get('/{item_id}', response_model=InboxItemDetail, operation_id='inbox_item')
    def item(item_id: ItemId, project: Ref):
        return scoped(inbox().item, project, item_id)

    @router.post('/{item_id}/read', response_model=InboxItemRead, operation_id='inbox_mark_read')
    def mark_read(item_id: ItemId, body: InboxMarkRead):
        return scoped(inbox().mark_read, body.project_id, item_id)

    return router
