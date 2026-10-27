"""Protected, explicit assistance; GETs never create a turn or resume an interrupted one."""
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import Field

from my_harness.api.configuration import Input, Hash, Key, ConfigurationCandidate, ConfigurationOperationRead
from my_harness.api.schemas import ProblemResponse
from my_harness.api.security import local_request, problem
from my_harness.core.engine.journal import JournalError
from my_harness.i18n import tr
from my_harness.services.configuration_assistance import ConfigurationAssistance
from my_harness.storage.configuration import ConfigurationConflict, scope_name


class AssistanceSelection(Input):
    model: str = Field(min_length=1, max_length=200, pattern=r'^[^-].*$')
    effort: str = Field(min_length=1, max_length=20)


class AssistanceRequest(Input):
    scope: str = 'global'
    candidate: ConfigurationCandidate
    expected_version: int = Field(ge=0)
    active_sha256: Hash
    base_sha256: Hash
    role: Literal['reviewer', 'executor'] = 'reviewer'
    selection: AssistanceSelection | None = None
    message: str = Field(min_length=1, max_length=8000)
    documents: list[str] = Field(default_factory=list, max_length=4)


class AssistanceConfirm(AssistanceRequest):
    preview_sha256: Hash
    confirmed: Literal[True]


class AssistanceRecovery(Input):
    writers_stopped: bool


def configuration_assistance_router(runtime):
    router = APIRouter(prefix='/api/managed/configuration/assistance', dependencies=[Depends(local_request)],
        responses={status: {'model': ProblemResponse} for status in (403, 404, 409, 422)})
    service = ConfigurationAssistance(runtime)

    def call(work):
        try:
            return work()
        except ConfigurationConflict as error:
            raise problem(409, error.code, tr('setup.conflict')) from None
        except (ValueError, OSError, LookupError, JournalError):
            raise problem(422, 'configuration_assistance_invalid', tr('setup.invalid')) from None

    @router.post('/preview', response_model=dict[str, Any], operation_id='configuration_assistance_preview')
    def preview(body: AssistanceRequest):
        return call(lambda: service.preview(scope_name(body.scope), body.model_dump()))

    @router.post('/confirm', response_model=ConfigurationOperationRead, operation_id='configuration_assistance_confirm')
    def confirm(body: AssistanceConfirm, idempotency_key: Key):
        return call(lambda: service.confirm(scope_name(body.scope),
            body.model_dump(exclude={'preview_sha256', 'confirmed'}),
            preview_sha256=body.preview_sha256, key=idempotency_key))

    @router.post('/{operation_id}/recover', response_model=ConfigurationOperationRead,
                 operation_id='configuration_assistance_recover')
    def recover(operation_id: str, body: AssistanceRecovery):
        return call(lambda: service.recover(operation_id, writers_stopped=body.writers_stopped))

    return router
