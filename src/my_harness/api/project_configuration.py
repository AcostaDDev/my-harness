"""Protected own-profile editor and activation; no provider calls in these routes."""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import Field

from my_harness.api.configuration import (Input, Hash, Key, ConfigurationCandidate, ConfigurationChange,
    ConfigurationSave, ConfigurationPreviewRead, ConfigurationOperationRead, ConfigurationFormRead)
from my_harness.api.schemas import ProblemResponse
from my_harness.api.security import local_request, problem
from my_harness.i18n import tr
from my_harness.services.configuration import parse
from my_harness.storage.configuration import ConfigurationConflict
from my_harness.storage.managed import Conflict
from my_harness.services.project_registry import RegistryError
from my_harness.core.engine.journal import JournalError


class ProjectActivation(Input):
    revision: int = Field(ge=1)
    sha256: Hash
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class ProjectActivate(ProjectActivation):
    preview_sha256: Hash


class ProjectConfigurationRead(Input):
    scope: str
    version: int
    status: str
    saved: dict[str, Any] | None
    active: dict[str, Any] | None
    pending: dict[str, Any] | None
    working_sha256: str | None = None
    actual_sha256: str | None = None
    configuration_state: str
    candidate_state: str
    text: str | None
    form: dict[str, Any]
    proposal_id: str
    proposal_sha256: Hash
    profile: dict[str, Any]
    preparation: dict[str, Any]
    assistance_documents: list[str]


class ProfileEdit(Input):
    proposal_id: str = Field(min_length=1, max_length=100)
    proposal_sha256: Hash
    expected_version: int = Field(ge=0)
    candidate: ConfigurationCandidate
    reason: str = Field(min_length=1, max_length=2000)


def project_configuration_router(runtime):
    router = APIRouter(prefix='/api/managed/projects/{project_id}', dependencies=[Depends(local_request)],
        responses={status: {'model': ProblemResponse} for status in (403, 404, 409, 422)})

    def call(project_id, operation):
        try:
            runtime.project(project_id)
            return operation(runtime.project_configuration)
        except RegistryError as error:
            raise problem(error.status, error.code, str(error)) from None
        except JournalError:
            raise problem(409, 'project_preparation_changed', tr('setup.conflict')) from None
        except Conflict as error:
            raise problem(409, getattr(error, 'code', 'profile_conflict'), tr('setup.conflict')) from None
        except LookupError:
            raise problem(404, 'profile_not_found', tr('setup.not_found')) from None
        except (ValueError, OSError, TypeError, KeyError):
            raise problem(422, 'profile_invalid', tr('setup.invalid')) from None

    def change(service, project_id, body):
        values = body.model_dump(exclude={'text', 'form', 'reason', 'preview_sha256'})
        return [{'scope': 'project:' + project_id, 'text': service.candidate(project_id, text=body.text,
            form=body.form, validated=body.validated), **values}]

    @router.get('/configuration', response_model=ProjectConfigurationRead, operation_id='project_configuration_read')
    def read(project_id: str):
        return call(project_id, lambda service: service.read(project_id))

    @router.post('/configuration/edit-base', response_model=ConfigurationFormRead, operation_id='project_configuration_edit_base')
    def edit_base(project_id: str):
        return call(project_id, lambda service: service.edit_base(project_id))

    @router.post('/configuration/form', response_model=ConfigurationFormRead, operation_id='project_configuration_form')
    def form(project_id: str, body: ConfigurationCandidate):
        def convert(service):
            text = service.candidate(project_id, **body.model_dump())
            return {'text': text, 'form': parse(text, 'project:' + project_id, validated=False)}
        return call(project_id, convert)

    @router.post('/configuration/preview', response_model=ConfigurationPreviewRead, operation_id='project_configuration_preview')
    def preview(project_id: str, body: ConfigurationChange):
        return call(project_id, lambda service: service.repository.preview(change(service, project_id, body), reason=body.reason))

    @router.post('/configuration/save', response_model=ConfigurationOperationRead, operation_id='project_configuration_save')
    def save(project_id: str, body: ConfigurationSave, idempotency_key: Key):
        return call(project_id, lambda service: service.repository.save(change(service, project_id, body),
            reason=body.reason, preview_sha256=body.preview_sha256, key=idempotency_key))

    def refs(project_id, body):
        return [{'scope': 'project:' + project_id, **body.model_dump(exclude={'reason', 'preview_sha256'})}]

    @router.post('/configuration/activation/preview', response_model=ConfigurationPreviewRead,
        operation_id='project_configuration_activation_preview')
    def activation_preview(project_id: str, body: ProjectActivation):
        return call(project_id, lambda service: service.activation_preview(refs(project_id, body), reason=body.reason))

    @router.post('/configuration/activate', response_model=ConfigurationOperationRead, operation_id='project_configuration_activate')
    def activate(project_id: str, body: ProjectActivate, idempotency_key: Key):
        def apply(service):
            result = service.repository.activate(refs(project_id, body), reason=body.reason,
                preview_sha256=body.preview_sha256, key=idempotency_key)
            # If installation fails after publishing, the persisted reference remains authoritative and
            # resolution keeps task admission closed until it can be recomposed; replay only reinstalls.
            project = runtime.registry.registrar.refresh(runtime.project(project_id), force=True)
            runtime.install(service.install_active(project))
            return result
        return call(project_id, apply)

    @router.post('/planning/{conversation_id}/profile/form', response_model=ConfigurationFormRead,
        operation_id='project_profile_form')
    def profile_form(project_id: str, conversation_id: str, body: ConfigurationCandidate):
        def convert(service):
            import tomllib
            from my_harness.services.configuration_setup import toml_document
            if (body.form is None) == (body.text is None):
                raise ValueError(tr('setup.invalid'))
            text = toml_document(body.form) if body.form is not None else body.text
            if len(text.encode()) > 65536:
                raise ValueError(tr('setup.invalid'))
            data = tomllib.loads(text)
            from my_harness.services.configuration import secretless
            secretless(data)
            if (not isinstance(data.get('name'), str) or not isinstance(data.get('profile'), dict)
                    or not isinstance(data['profile'].get('executor_instructions'), str)):
                raise ValueError(tr('setup.invalid'))
            from my_harness.services.configuration import shape, PROFILE
            shape(data['profile'], PROFILE)
            return {'text': text, 'form': data}
        return call(project_id, convert)

    @router.post('/planning/{conversation_id}/profile/edit', response_model=dict[str, Any], operation_id='project_profile_edit')
    def edit(project_id: str, conversation_id: str, body: ProfileEdit, idempotency_key: Key):
        def apply(service):
            from my_harness.storage.planning import PlanningRepository
            from my_harness.services.configuration_setup import toml_document
            import tomllib
            item = runtime.project(project_id)
            if (body.candidate.form is None) == (body.candidate.text is None):
                raise ValueError(tr('setup.invalid'))
            text = toml_document(body.candidate.form) if body.candidate.form is not None else body.candidate.text
            if len(text.encode()) > 65536:
                raise ValueError(tr('setup.invalid'))
            candidate = tomllib.loads(text)
            writer = runtime.config.commit_factory(item.context, dict(item.versions))
            return PlanningRepository(runtime.repository).edit_profile(item.context, conversation_id,
                body.proposal_id, body.expected_version, body.proposal_sha256, candidate, body.reason,
                idempotency_key, writer=writer, versions=dict(item.versions))
        return call(project_id, apply)

    @router.get('/profile-templates/{name}', response_model=dict[str, Any], operation_id='project_profile_template')
    def template(project_id: str, name: str):
        def view(service):
            registrar = runtime.registry.registrar
            profile_name, commands = registrar.compositions[name]
            # Catalog copies stay data only and require the same documentary proposal/confirmation.
            from dataclasses import asdict
            profile = registrar.profiles[profile_name]
            data = asdict(profile)
            data.pop('name')
            reports = data.pop('junit_reports')
            for kind in ('preparation', 'validations'):
                for command in data[kind]:
                    report = next((r for r in reports if r['command'] == command), None)
                    command['argv'] = list(command['argv'])
                    command['environment'] = dict(command['environment'])
                    if report:
                        command['junit'] = {k: report[k] for k in ('path', 'coverage')}
            data['allowed_command_prefixes'] = [list(p) for p in profile.allowed_command_prefixes]
            for key in ('protected_paths', 'sensitive_paths', 'sensitive_allowlist', 'data_model_paths', 'formatter_paths', 'formatter_argv'):
                data[key] = list(data[key])
            if not profile.formatter_argv:
                data.pop('formatter_argv'); data.pop('formatter_paths')
            return {'name': profile_name, 'profile': data, 'commands': commands}
        return call(project_id, view)

    return router
