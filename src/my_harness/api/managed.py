"""Local managed API: delegates to the H2.2–H2.5 authority without new engine logic.

Every route requires a loopback Host; every mutation additionally requires a loopback Origin
(if the browser sends it) and the `X-My-Harness: 1` header, which a foreign
page cannot add without a CORS preflight (the service does not enable CORS).
Mutations that create jobs require `Idempotency-Key`; those that change an
existing resource, `expected_version`. Conflicts and mode refusals return 409 with
a diagnostic; the library guarantees that no partial effects remain.
"""

from typing import Annotated
from contextvars import ContextVar

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import Field

from my_harness.api.schemas import (
    CycleDiffRead, CycleRead, JUnitCasesRead, ManagedLogRead,
    PromptScope, PromptDetailRead, PromptVersionRead, PromptDraftCreate, PromptActivateCreate,
    PromptValidateCreate, PromptValidationRead, PromptDiffRead,
    ConfirmStoppedCreate, ManagedAttemptRead,
    ManagedEventsRead, ManagedJobRead, ManagedProjectRead, ManagedRunRead, ManagedRunSummaryRead,
    ModeRead, Page, PhaseTaskRead, PreferencesRead, PreferencesUpdate, PreferencesUpdateRead, ProblemResponse,
    RunActionCreate, RunCreate, SupervisorRead, TaskSourcesRead, WorkLanguageMigrationApplyCreate,
    WorkLanguageMigrationApplyRead, WorkLanguageMigrationInput, WorkLanguageMigrationPreviewRead,
)
from my_harness.api.security import local_request, problem
from my_harness.adapters.bootstrap import DraftChanged
from my_harness.adapters.cli_compatibility import CompatibilityError
from my_harness.core.engine.document_ops import BaseChanged, ManagedBlocksEdited
from my_harness.core.engine.planning import task_sources
from my_harness.core.managed_mode import MigrationError
from my_harness.i18n import message
from my_harness.services.managed_runtime import ManagedRuntime, agents_view
from my_harness.storage.documents import IMAGE_TYPES
from my_harness.storage.managed import Conflict, OwnershipLost
from my_harness.storage.managed_mode import ModeConflict
from my_harness.storage.preferences import PreferencesChanged, PreferencesInvalid, PreferencesKeyReused, language
from my_harness.storage.work_language import WorkLanguageImmutable, WorkLanguageRequired

Offset = Annotated[int, Query(ge=0, le=2**53 - 1)]
Limit = Annotated[int, Query(ge=1, le=100)]
DiffLimit = Annotated[int, Query(ge=4096, le=512 * 1024)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200,
                                       description="The same key and the same action return the same job.")]
ERRORS = {status: {"model": ProblemResponse} for status in (403, 404, 409, 422)}
_resolved_cli = ContextVar('managed_cli_admission', default=None)


async def cli_admission_scope(request: Request):
    """Only explicit mutations may refresh clients; project/history/document reads stay passive."""
    token = _resolved_cli.set({} if request.method not in ('GET', 'HEAD', 'OPTIONS') else None)
    try:
        yield
    finally:
        _resolved_cli.reset(token)


def call(operation, /, *args, **kwargs):
    """Translates authority errors to HTTP. Order matters: all of them derive from ValueError."""
    try:
        return operation(*args, **kwargs)
    except CompatibilityError as error:
        raise problem(409, error.code, str(error)) from error
    except LookupError as error:
        raise problem(404, "not_found", str(error)) from error
    except PreferencesInvalid as error:  # the stored language is unusable: English diagnostic
        raise problem(409, "preferences_invalid", message("preferences.invalid", "en")) from error
    except WorkLanguageRequired as error:  # D167: new work waits for an explicit work language
        raise problem(409, "work_language_required", str(error)) from error
    except WorkLanguageImmutable as error:
        raise problem(409, "work_language_immutable", str(error)) from error
    except Conflict as error:
        # P011-T022: the client tells these refusals apart by code, never by the (localized) diagnostic.
        code = ("mode_refused" if isinstance(error.__cause__, ModeConflict)
                else "document_changed" if isinstance(error.__cause__, BaseChanged)
                else "managed_blocks_generated" if isinstance(error.__cause__, ManagedBlocksEdited)
                else "draft_changed" if isinstance(error.__cause__, DraftChanged)
                else "preparation_required" if str(error).startswith("preparation_required:") else "conflict")
        raise problem(409, code, str(error)) from error
    except ModeConflict as error:
        raise problem(409, "migration_conflict", str(error)) from error
    except MigrationError as error:
        raise problem(409, "migration_refused", str(error)) from error
    except OwnershipLost as error:
        raise problem(409, "ownership_lost", str(error)) from error
    except ValueError as error:
        raise problem(422, "invalid_request", str(error)) from error
    except OSError as error:
        raise problem(409, "checkout_unreadable", f"{type(error).__name__}: {error}") from error


def managed_router(runtime: ManagedRuntime):
    router = APIRouter(prefix="/api/managed", dependencies=[Depends(local_request), Depends(cli_admission_scope)],
                       responses=ERRORS)

    def say(key: str, **params) -> str:
        """Own diagnostic in the stored visual language (P011-T010); codes and statuses never change."""
        return message(key, language(runtime.engine), **params)

    def project_read(project):
        from my_harness.storage.work_language import read
        from my_harness.core.engine.context import profile_name
        state = planning_repository().profile_state(project.context.root) if profile_name(project.context) is None else 'ACTIVE'
        imported_profile = False
        if runtime.setup is not None and runtime.setup.legacy:
            imported_profile = bool(runtime.setup.repository.read('project:' + project.id)['saved'])
        if (runtime.setup is not None and (imported_profile or not runtime.setup.legacy
                and project.versions.get('local_config') == 'local-config-9') and state != 'PROFILE_REQUIRED'):
            try:
                state = runtime.project_configuration.read(project.id)['configuration_state']
            except (ValueError, OSError):
                state = 'PREPARATION_REQUIRED'
        return {"id": project.id, "root": str(project.context.root), "profile": profile_name(project.context),
                'configuration_state': state,
                "work_language": read(runtime.engine, project.context.root),
                "versions": dict(project.versions), "tag_kind": project.tag_kind, "agents": agents_view(project),
                "documents": project.context.documents, "bootstrap_enabled": project.bootstrap_enabled,
                "source": "registry" if "project_registry" in project.versions else "operator",
                "registry_version": int(project.versions["project_registry"])
                if "project_registry" in project.versions else None}

    def project(project_id: str):
        return call(runtime.project, project_id)

    def configured_actions(detail):
        if runtime.project_id(detail['root']) is None:
            return {**detail, 'actions': []}
        if runtime.config.commit_factory is None:
            return {**detail, 'actions': [a for a in detail['actions'] if a != 'commit']}
        return detail

    def registered_run(run_id: str):
        """Actions only operate on checkouts registered in this service."""
        run = call(runtime.views.run, run_id)
        project_id = runtime.project_id(run["root"])
        if project_id is None:
            raise problem(404, "not_found", say('api.run_unregistered'))
        return configured_actions({**run, "project_id": project_id})

    def queued(job):
        runtime.notify()
        return call(runtime.views.job, job.id)

    @router.get("/supervisor", response_model=SupervisorRead, operation_id="managed_supervisor")
    def supervisor():
        return call(runtime.supervisor_status)

    @router.get("/preferences", response_model=PreferencesRead, operation_id="managed_preferences")
    def preferences():
        """Global languages of this installation (D166); reading never creates or repairs the row."""
        runtime.ready()
        return runtime.preferences.read()

    @router.put("/preferences", response_model=PreferencesUpdateRead, operation_id="managed_preferences_update")
    def preferences_update(body: PreferencesUpdate, idempotency_key: IdempotencyKey):
        """CAS by version. Applies to jobs admitted afterwards; queued work and projects keep their values."""
        runtime.ready()

        def update():
            try:
                return runtime.preferences.update(**body.model_dump(), key=idempotency_key)
            except (PreferencesChanged, PreferencesKeyReused) as error:
                code, key = (("preferences_conflict", "preferences.conflict") if isinstance(error, PreferencesChanged)
                             else ("idempotency_conflict", "preferences.key_reused"))
                raise problem(409, code, message(key, runtime.preferences.read()["ui_language"])) from error
        return call(update)

    @router.get("/projects", response_model=list[ManagedProjectRead], operation_id="managed_projects")
    def projects():
        runtime.ready()
        return [project_read(item) for item in runtime.projects.values()]

    @router.get("/projects/{project_id}", response_model=ManagedProjectRead, operation_id="managed_project")
    def project_detail(project_id: str):
        return project_read(project(project_id))

    # --- project registry H6.2 E2 (D054/D076) ------------------------------------------
    from my_harness.api.schemas import (
        RegisteredProjectRead, RegistryApplyCreate, RegistryApplyRead, RegistryChangeInput, RegistryPreviewRead,
        RegistryRead,
    )
    from my_harness.services.project_registry import RegistryError

    def registry(operation, /, *args, **kwargs):
        def guarded():
            try:
                return operation(*args, **kwargs)
            except RegistryError as error:  # before ValueError in `call`: the registry's own codes
                raise problem(error.status, error.code, str(error)) from error
            except OSError as error:
                raise problem(409, 'target_identity_changed',
                              say('api.target_identity_changed')) from error
        return call(guarded)

    def change(body: RegistryChangeInput) -> dict:
        data = body.model_dump()
        if body.policy is not None:
            data['policy'] = body.policy.model_dump(exclude_none=True)
        return data

    @router.get("/registry", response_model=RegistryRead, operation_id="managed_registry")
    def registry_options():
        runtime.ready()
        return runtime.registry.options()

    @router.get("/registry/projects/{project_id}", response_model=RegisteredProjectRead,
                operation_id="managed_registered_project")
    def registered_project(project_id: str):
        runtime.ready()
        return registry(runtime.registry.read, project_id)

    @router.post("/registry/preview", response_model=RegistryPreviewRead, operation_id="managed_registry_preview")
    def registry_preview(body: RegistryChangeInput):
        """No effects: resulting row, changes, frozen versions and the hash that binds the confirmation."""
        runtime.ready()
        return registry(runtime.registry.preview, change(body))

    @router.post("/registry/apply", response_model=RegistryApplyRead, operation_id="managed_registry_apply")
    def registry_apply(body: RegistryApplyCreate):
        """Repeating the same confirmation returns the already applied result, without another version."""
        runtime.ready()
        return registry(runtime.registry.apply, change(body.change), preview_sha256=body.preview_sha256,
                        trust_root=body.trust_root, reason=body.reason)

    @router.post("/projects/{project_id}/work-language/preview", response_model=WorkLanguageMigrationPreviewRead,
                 operation_id="managed_work_language_preview")
    def work_language_preview(project_id: str, body: WorkLanguageMigrationInput):
        """No effects: for a project without a work language, the value to confirm and what blocks it (D167)."""
        runtime.ready()
        return registry(runtime.work_language.preview, project_id, body.model_dump())

    @router.post("/projects/{project_id}/work-language", response_model=WorkLanguageMigrationApplyRead,
                 operation_id="managed_work_language_apply")
    def work_language_apply(project_id: str, body: WorkLanguageMigrationApplyCreate):
        """Absent → en/es once, with the preview hash and a reason; afterwards it never changes."""
        runtime.ready()
        project, replayed = registry(runtime.work_language.apply, project_id, body.change.model_dump(),
                                     preview_sha256=body.preview_sha256, reason=body.reason)
        return {"project": project_read(project), "replayed": replayed}

    @router.get("/projects/{project_id}/mode", response_model=ModeRead, operation_id="managed_mode")
    def mode(project_id: str):
        root = str(project(project_id).context.root)
        return {"project_id": project_id, "root": root,
                "refusal": runtime.repository.guard.assess(root).refusal}

    # --- state of the conversational creation (D088) ---------------------------------
    from my_harness.api.schemas import BootstrapStatusRead
    from my_harness.storage.bootstrap import BootstrapRepository

    def bootstrap_writer(item):
        if not item.bootstrap_enabled:
            raise problem(409, 'bootstrap_disabled', say('api.bootstrap_unauthorized'))
        return call(runtime.config.commit_factory, item.context, frozen_versions(item))

    @router.get('/projects/{project_id}/bootstrap', response_model=BootstrapStatusRead,
                operation_id='managed_bootstrap_status')
    def bootstrap_status(project_id: str):
        """State of the definition and its root commit; the v1 creation is no longer exposed."""
        item = project(project_id)
        operation = call(BootstrapRepository(runtime.repository).get, item.context.root)
        target = (call(bootstrap_writer(item).inspect_definition, item.context)
                  if item.bootstrap_enabled and not operation else None)
        return {'enabled': item.bootstrap_enabled, 'import_required': bool(target and target['import_required']),
                'diagnostic': target.get('diagnostic') if target else None,
                'definition_operation': operation if item.context.documents is not None else None}

    # --- runs, jobs, attempts and events --------------------------------------------

    @router.get("/projects/{project_id}/runs", response_model=Page[ManagedRunSummaryRead],
                operation_id="managed_runs")
    def runs(project_id: str, offset: Offset = 0, limit: Limit = 30,
             phase: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
             task: Annotated[str | None, Query(min_length=1, max_length=120)] = None):
        page = runtime.views.runs(str(project(project_id).context.root), offset, limit, phase, task)
        return {**page, "items": [{**item, "project_id": project_id} for item in page["items"]]}

    def frozen_versions(item):
        from my_harness.core.engine.contracts import freeze
        resolutions = _resolved_cli.get()
        if resolutions is not None:
            if item.id not in resolutions:
                resolutions[item.id] = call(runtime.resolve_project, item.id)
            item = resolutions[item.id]
        versions = dict(item.versions)
        if item.permission_authority is not None:
            versions['permission_authority'] = freeze(item.permission_authority)
        return versions

    @router.get("/projects/{project_id}/task-sources", response_model=TaskSourcesRead,
                operation_id="managed_task_sources")
    def task_sources_read(project_id: str):
        """P009-T020: tasks of the live NEXT_STEPS, with the text that would be sent for each one and its hash."""
        return call(task_sources, documents_project(project_id).context)

    @router.post("/projects/{project_id}/runs", response_model=ManagedJobRead, status_code=202,
                 operation_id="managed_submit_run")
    def submit_run(project_id: str, body: RunCreate, idempotency_key: IdempotencyKey):
        item = project(project_id)
        if body.source_sha256 is not None:
            # P009-T020: the text chosen in the selector must still be the one in the live document (CAS).
            live = next((source for source in call(task_sources, documents_project(project_id).context)["items"]
                         if source["task_id"] == body.task_id), None)
            if (live is None or live["phase_id"] != body.phase_id or live["sha256"] != body.source_sha256
                    or live["text"] != body.text):
                raise problem(409, "task_source_changed", say('api.task_source_changed'))
        notes = body.notes.strip() if body.notes is not None and body.notes.strip() else None
        job = call(runtime.repository.submit, item.context, body.task_id, body.phase_id, body.text,
                   frozen_versions(item), key=idempotency_key, notes=notes)
        return queued(job)

    @router.get("/runs/{run_id}", response_model=ManagedRunRead, operation_id="managed_run")
    def run(run_id: str):
        runtime.ready()
        detail = call(runtime.views.run, run_id)
        return configured_actions({**detail, "project_id": runtime.project_id(detail["root"])})

    @router.get("/runs/{run_id}/jobs", response_model=Page[ManagedJobRead], operation_id="managed_run_jobs")
    def run_jobs(run_id: str, offset: Offset = 0, limit: Limit = 30):
        """From newest to oldest."""
        runtime.ready()
        return call(runtime.views.jobs, run_id, offset, limit)

    @router.get("/runs/{run_id}/cycles", response_model=Page[CycleRead], operation_id="managed_run_cycles")
    def run_cycles(run_id: str, offset: Offset = 0, limit: Limit = 10):
        """Review cycles by ascending number, without the diff text or the JUnit cases (D142)."""
        runtime.ready()
        return call(runtime.views.cycles, run_id, offset, limit)

    @router.get("/runs/{run_id}/cycles/{cycle}/diff", response_model=CycleDiffRead, operation_id="managed_cycle_diff")
    def cycle_diff(run_id: str, cycle: int, offset: Offset = 0, limit: DiffLimit = 64 * 1024,
                   sha256: Annotated[str | None, Query(pattern=r'^[0-9a-f]{64}$')] = None):
        """Reviewed diff of a cycle in pages of UTF-8 bytes that end at a line end; `offset` is 0 or a
        previous `next_offset`. With `sha256`, a diff other than the requested one responds 409."""
        runtime.ready()
        return call(runtime.views.cycle_diff, run_id, cycle, offset, limit, sha256)

    @router.get('/runs/{run_id}/cycles/{cycle}/validations/{entry}/reports/{report}',
                response_model=JUnitCasesRead, operation_id='managed_junit_cases')
    def junit_cases(run_id: str, cycle: int, entry: int, report: int, offset: Offset = 0, limit: Limit = 50):
        runtime.ready()
        return call(runtime.views.test_cases, run_id, cycle, entry, report, offset, limit)

    @router.get('/runs/{run_id}/cycles/{cycle}/validations/{entry}/reports/{report}/original',
                response_class=Response, operation_id='managed_junit_original',
                responses={200: {'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
    def junit_original(run_id: str, cycle: int, entry: int, report: int):
        runtime.ready()
        data, sha256 = call(runtime.views.test_original, run_id, cycle, entry, report)
        return Response(data, media_type='application/octet-stream', headers={
            'Content-Disposition': 'attachment; filename="junit.xml"', 'ETag': f'"{sha256}"',
            'X-Content-Type-Options': 'nosniff'})

    @router.get("/runs/{run_id}/attempts", response_model=Page[ManagedAttemptRead],
                operation_id="managed_run_attempts")
    def attempts(run_id: str, offset: Offset = 0, limit: Limit = 30):
        runtime.ready()
        return call(runtime.views.attempts, run_id, offset, limit)

    @router.get('/runs/{run_id}/attempts/{attempt_id}/logs', response_model=list[ManagedLogRead],
                operation_id='managed_attempt_logs')
    def attempt_logs(run_id: str, attempt_id: str):
        runtime.ready()
        from sqlalchemy import text
        from my_harness.storage.retention import inspect_logs
        with runtime.repository.engine.connect() as db:
            owner = db.scalar(text('SELECT run_id FROM managed_attempts WHERE id=:id'), {'id': attempt_id})
        if owner != run_id:
            raise problem(404, 'not_found', say('api.attempt_unknown'))
        return call(inspect_logs, runtime.repository.engine.url.database, attempt_id)

    @router.get("/runs/{run_id}/events", response_model=ManagedEventsRead, operation_id="managed_run_events")
    def events(run_id: str, after: Offset = 0, limit: Limit = 100):
        """Confirmed events only, by run sequence; `cursor` is the `after` of the next page."""
        runtime.ready()
        return call(runtime.views.events, run_id, after, limit)

    @router.post("/runs/{run_id}/actions", response_model=ManagedJobRead, status_code=202,
                 operation_id="managed_run_action")
    def run_action(run_id: str, body: RunActionCreate, idempotency_key: IdempotencyKey):
        runtime.ready()
        registered_run(run_id)
        if body.action == "commit":
            if runtime.config.commit_factory is None:
                raise problem(409, "commit_writer_unavailable",
                              say('api.writer_commit'))
            # No mechanical updates over HTTP: the commit contains exactly what was reviewed.
            job = call(runtime.repository.submit_commit, run_id, key=idempotency_key,
                       expected_version=body.expected_version)
        else:
            job = call(runtime.repository.resume, run_id, key=idempotency_key,
                       expected_version=body.expected_version, retry_executor=body.action == "retry_executor")
        return queued(job)

    @router.get("/jobs/{job_id}", response_model=ManagedJobRead, operation_id="managed_job")
    def job(job_id: int):
        runtime.ready()
        return call(runtime.views.job, job_id)

    @router.post("/jobs/{job_id}/confirm-stopped", response_model=ManagedRunRead,
                 operation_id="managed_confirm_stopped")
    def confirm_stopped(job_id: int, body: ConfirmStoppedCreate):
        """User assertion after ruling out the previous writer; the authority checks processes."""
        runtime.ready()
        detail = call(runtime.views.job, job_id)
        registered_run(detail["run_id"])
        call(runtime.repository.confirm_stopped, job_id, owner_token=body.owner_token,
             expected_version=body.expected_version, reason=body.reason)
        runtime.notify()
        return registered_run(detail["run_id"])

    @router.get("/projects/{project_id}/prompts", response_model=list[PromptDetailRead])
    def prompts(project_id: str, scope: PromptScope = "project"):
        from my_harness.core.engine.prompts import VARIABLES
        context = project(project_id).context
        return [call(runtime.prompts.detail, context, scope, name) for name in VARIABLES]

    @router.get("/projects/{project_id}/prompts/{name}", response_model=PromptDetailRead)
    def prompt_detail(project_id: str, name: str, scope: PromptScope = "project"):
        return call(runtime.prompts.detail, project(project_id).context, scope, name)

    @router.post("/projects/{project_id}/prompts/{name}/validate", response_model=PromptValidationRead)
    def validate_prompt(project_id: str, name: str, body: PromptValidateCreate):
        from my_harness.core.engine.prompts import validate
        project(project_id)
        return {"variables": call(validate, name, body.template)}

    @router.post("/projects/{project_id}/prompts/{name}/versions", response_model=PromptVersionRead, status_code=201)
    def draft_prompt(project_id: str, name: str, body: PromptDraftCreate, scope: PromptScope = "project"):
        return call(runtime.prompts.draft, project(project_id).context, scope, name, body.expected_version,
                    text=body.template, from_version=body.from_version)

    @router.post("/projects/{project_id}/prompts/{name}/activate", response_model=PromptDetailRead)
    def activate_prompt(project_id: str, name: str, body: PromptActivateCreate, scope: PromptScope = "project"):
        context = project(project_id).context
        call(runtime.prompts.activate, context, scope, name, body.expected_version, body.version_id, body.reason)
        return call(runtime.prompts.detail, context, scope, name)

    @router.get("/projects/{project_id}/prompts/{name}/diff", response_model=PromptDiffRead)
    def prompt_diff(project_id: str, name: str, before: str, after: str):
        return {"diff": call(runtime.prompts.diff, project(project_id).context, name, before, after)}

    from my_harness.api.schemas import PermissionCreate, PermissionDecisionCreate, PermissionRequestRead

    @router.get('/runs/{run_id}/permissions', response_model=list[PermissionRequestRead])
    def permissions(run_id: str):
        registered_run(run_id)
        return call(runtime.permissions.list, run_id)

    @router.post('/runs/{run_id}/permissions', response_model=PermissionRequestRead, status_code=201)
    def request_permission(run_id: str, body: PermissionCreate):
        registered_run(run_id)
        values = body.model_dump()
        expected = values.pop('expected_version')
        return call(runtime.permissions.create, run_id, expected, **values)

    @router.post('/runs/{run_id}/permissions/{permission_id}/decision', response_model=PermissionRequestRead)
    def decide_permission(run_id: str, permission_id: str, body: PermissionDecisionCreate):
        registered_run(run_id)
        values = body.model_dump(exclude={'confirmed'})
        expected = values.pop('expected_version')
        return call(runtime.permissions.decide, run_id, permission_id, expected, **values)

    # --- H3.3: phases ---------------------------------------------------------------

    from my_harness.api.schemas import (
        PhaseAbandonCreate, PhaseAmendCreate, PhaseAnswerCreate, PhaseBatchCreate, PhaseBatchNextCreate,
        PhaseCheckCreate, PhaseCloseCreate, PhaseCreate, PhaseQuestionCreate, PhaseRead, PhaseReconcileCreate,
        PhaseReconcileTaskCreate, PhaseRevokeCreate, PhaseSummaryRead,
    )
    from my_harness.core.engine.phases import document_hashes

    def phase_read(phase_id: str):
        """Read with current documents (disk) and actions computed by the server."""
        runtime.ready()
        root, definition = call(runtime.phases.definition, phase_id)
        project_id = runtime.project_id(root)
        current = archived = None
        if project_id is not None:
            context = runtime.projects[project_id].context
            try:
                current = document_hashes(context, definition["documents"])
            except (OSError, ValueError):
                current = None
            # P010-T005: the archive of a finished phase is checked file by file against what the closure wrote.
            archived = {}
            for path in call(runtime.phases.closure_files, phase_id):
                try:
                    archived.update(document_hashes(context, [path]))
                except (OSError, ValueError):
                    archived[path] = "unreadable"
        detail = call(runtime.phases.get, phase_id, current, archived)
        actions = detail["actions"] if project_id is not None else []
        if current is None:
            actions = [a for a in actions if a != "reconcile"]
        if runtime.config.commit_factory is None:
            actions = [a for a in actions if a not in ("check", "close", "reconcile_task", "abandon")]
        tag_kind = runtime.projects[project_id].tag_kind if project_id is not None else None
        return {**detail, "project_id": project_id, "actions": actions, "tag_kind": tag_kind}

    def registered_phase(phase_id: str):
        detail = phase_read(phase_id)
        if detail["project_id"] is None:
            raise problem(404, "not_found", say('api.phase_unregistered'))
        return runtime.projects[detail["project_id"]], detail

    @router.get("/projects/{project_id}/phases", response_model=list[PhaseSummaryRead], operation_id="managed_phases")
    def phases(project_id: str):
        return call(runtime.phases.list, str(project(project_id).context.root))

    @router.get("/projects/{project_id}/phases/{code}", response_model=PhaseRead, operation_id="managed_phase_by_code")
    def phase_by_code(project_id: str, code: str):
        """Read by the URL code (`P001`), unique per checkout (D076)."""
        return phase_read(call(runtime.phases.by_code, str(project(project_id).context.root), code))

    @router.get("/projects/{project_id}/phases/{code}/tasks", response_model=Page[PhaseTaskRead],
                operation_id="managed_phase_tasks")
    def phase_tasks(project_id: str, code: str, offset: Offset = 0, limit: Limit = 30):
        """Without a defined phase (v1 runs or runs before the definition), only the tasks with runs."""
        root = str(project(project_id).context.root)
        try:
            planned = list(runtime.phases.definition(runtime.phases.by_code(root, code))[1].get("tasks") or [])
        except LookupError:
            planned = []
        page = runtime.views.tasks(root, code, planned, offset, limit)
        return {**page, "items": [{**item, "latest": item["latest"] and {**item["latest"], "project_id": project_id}}
                                  for item in page["items"]]}

    @router.post("/projects/{project_id}/phases", response_model=PhaseRead, status_code=201,
                 operation_id="managed_create_phase")
    def create_phase(project_id: str, body: PhaseCreate):
        context = project(project_id).context
        data = body.model_dump()
        if data["documents"] is None:
            from my_harness.core.engine.documents import layout
            target = layout(context)
            data["documents"] = (list(target.phase_documents) if target is not None
                                 else [context.state_file, context.next_steps_file])
        return phase_read(call(runtime.phases.create, context, data))

    @router.get("/phases/{phase_id}", response_model=PhaseRead, operation_id="managed_phase")
    def phase(phase_id: str):
        return phase_read(phase_id)

    @router.get("/phases/{phase_id}/events", response_model=ManagedEventsRead, operation_id="managed_phase_events")
    def phase_events(phase_id: str, after: Offset = 0, limit: Limit = 100):
        runtime.ready()
        return call(runtime.phases.events, phase_id, after, limit)

    @router.post("/phases/{phase_id}/actions", response_model=ManagedJobRead, status_code=202,
                 operation_id="managed_phase_action")
    def phase_action(phase_id: str, body: Annotated[PhaseCheckCreate | PhaseCloseCreate, Field(discriminator="action")],
                     idempotency_key: IdempotencyKey):
        """check and close are jobs under the checkout lock; the closure requires its own authorization."""
        item, _ = registered_phase(phase_id)
        if runtime.config.commit_factory is None:
            raise problem(409, "commit_writer_unavailable",
                          say('api.writer_phase'))
        if body.action == "check":
            job = call(runtime.phases.submit_check, item.context, phase_id, body.expected_version,
                       key=idempotency_key, versions=frozen_versions(item))
        else:
            job = call(runtime.phases.submit_close, item.context, phase_id, body.expected_version,
                       key=idempotency_key, versions=frozen_versions(item), binding_sha256=body.binding_sha256,
                       reason=body.reason, ttl_seconds=body.ttl_seconds, tag_kind=item.tag_kind,
                       git=document_writer(item))
        return queued(job)

    @router.post("/phases/{phase_id}/reconcile", response_model=PhaseRead, operation_id="managed_phase_reconcile")
    def reconcile_phase(phase_id: str, body: PhaseReconcileCreate):
        item, _ = registered_phase(phase_id)
        call(runtime.phases.reconcile, item.context, phase_id, body.expected_version,
             documents_sha256=body.documents_sha256, reason=body.reason)
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/questions", response_model=PhaseRead, status_code=201,
                 operation_id="managed_phase_question")
    def raise_question(phase_id: str, body: PhaseQuestionCreate):
        registered_phase(phase_id)
        call(runtime.phases.raise_question, phase_id, body.expected_version, text=body.text)
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/questions/{question_id}/answer", response_model=PhaseRead,
                 operation_id="managed_phase_answer")
    def answer_question(phase_id: str, question_id: str, body: PhaseAnswerCreate):
        registered_phase(phase_id)
        call(runtime.phases.answer, phase_id, question_id, body.expected_version,
             expected_question_version=body.expected_question_version, answer=body.answer)
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/authorizations", response_model=PhaseRead, status_code=201,
                 operation_id="managed_phase_authorize_batch")
    def authorize_batch(phase_id: str, body: PhaseBatchCreate):
        """Batch only, never check or closure. With `chain_commits` the supervisor chains tasks and commits."""
        item, _ = registered_phase(phase_id)
        if body.chain_commits and runtime.config.commit_factory is None:
            raise problem(409, "commit_writer_unavailable",
                          say('api.writer_batch'))
        call(runtime.phases.authorize_batch, phase_id, body.expected_version, tasks=body.tasks,
             ttl_seconds=body.ttl_seconds, reason=body.reason, chain_commits=body.chain_commits, text=body.text,
             context=item.context, versions=frozen_versions(item))
        runtime.notify()
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/authorizations/{authorization_id}/revoke", response_model=PhaseRead,
                 operation_id="managed_phase_revoke")
    def revoke_batch(phase_id: str, authorization_id: str, body: PhaseRevokeCreate):
        registered_phase(phase_id)
        call(runtime.phases.revoke, phase_id, authorization_id, body.expected_version, reason=body.reason)
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/batch/next", response_model=ManagedJobRead, status_code=202,
                 operation_id="managed_phase_batch_next")
    def batch_next(phase_id: str, body: PhaseBatchNextCreate, idempotency_key: IdempotencyKey):
        item, _ = registered_phase(phase_id)
        job = call(runtime.phases.batch_next, item.context, phase_id, body.expected_version, key=idempotency_key,
                   versions=frozen_versions(item), authorization_id=body.authorization_id, text=body.text)
        return queued(job)

    # --- H3.4: amendment, abandonment and reconciliation with an agent ------------------

    @router.post("/phases/{phase_id}/amend", response_model=PhaseRead, operation_id="managed_phase_amend")
    def amend_phase(phase_id: str, body: PhaseAmendCreate):
        """New version of the definition (the previous one is kept); invalidates READY and current batches."""
        item, _ = registered_phase(phase_id)
        data = body.model_dump(exclude={"expected_version", "reason", "confirmed"})
        call(runtime.phases.amend, item.context, phase_id, body.expected_version, data=data, reason=body.reason)
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/abandon", response_model=PhaseRead, operation_id="managed_phase_abandon")
    def abandon_phase(phase_id: str, body: PhaseAbandonCreate, idempotency_key: IdempotencyKey):
        item, _ = registered_phase(phase_id)
        job = call(runtime.phases.abandon, phase_id, body.expected_version, reason=body.reason, context=item.context,
                   git=document_writer(item), key=idempotency_key, versions=frozen_versions(item))
        queued(job)
        return phase_read(phase_id)

    @router.post("/phases/{phase_id}/reconcile-task", response_model=ManagedJobRead, status_code=202,
                 operation_id="managed_phase_reconcile_task")
    def reconcile_task(phase_id: str, body: PhaseReconcileTaskCreate, idempotency_key: IdempotencyKey):
        """Normal task with a deterministic contract limited to the documents; no automatic adoption."""
        item, _ = registered_phase(phase_id)
        if runtime.config.commit_factory is None:
            raise problem(409, "commit_writer_unavailable",
                          say('api.writer_reconcile'))
        job = call(runtime.phases.submit_reconcile_task, item.context, phase_id, body.expected_version,
                   key=idempotency_key, versions=frozen_versions(item))
        return queued(job)

    # --- Confirmed mechanical export of documents ----------------------------------------------
    from my_harness.api.schemas import DocumentExportCreate, DocumentExportPreviewRead
    from my_harness.storage.document_export import DocumentExportRepository

    def export_writer(item):
        if runtime.config.commit_factory is None:
            raise problem(409, 'commit_writer_unavailable', say('api.writer_export'))
        return runtime.config.commit_factory(item.context, frozen_versions(item))

    @router.get('/phases/{phase_id}/export', response_model=DocumentExportPreviewRead,
                operation_id='managed_document_export_preview')
    def export_preview(phase_id: str):
        item, _ = registered_phase(phase_id)
        return call(DocumentExportRepository(runtime.repository).preview, item.context, phase_id, export_writer(item))

    @router.post('/phases/{phase_id}/export', response_model=ManagedJobRead, status_code=202,
                 operation_id='managed_document_export')
    def export_documents(phase_id: str, body: DocumentExportCreate, idempotency_key: IdempotencyKey):
        item, _ = registered_phase(phase_id)
        job = call(DocumentExportRepository(runtime.repository).submit, item.context, phase_id, body.expected_version,
                   key=idempotency_key, versions=frozen_versions(item), git=export_writer(item),
                   **body.model_dump(exclude={'expected_version'}))
        return queued(job)

    # --- D088: project documents and plan of the active phase -----------------------------------------
    from my_harness.api.schemas import (
        DocumentEditCreate, DocumentEditInput, DocumentEditPreviewRead, DocumentRead, DocumentsStatusRead,
        DocumentTreeRead,
    )
    from my_harness.storage.documents import DocumentsRepository
    from my_harness.api.documents import document_status, document_tree as project_document_tree

    def documents_project(project_id: str):
        item = project(project_id)
        if item.context.documents is None:
            raise problem(409, 'documents_layout', say('api.documents_layout'))
        return item

    def document_writer(item):
        if runtime.config.commit_factory is None:
            raise problem(409, 'commit_writer_unavailable', say('api.writer_documents'))
        return runtime.config.commit_factory(item.context, frozen_versions(item))

    @router.get('/projects/{project_id}/documents', response_model=DocumentsStatusRead,
                operation_id='managed_documents')
    def documents_status(project_id: str):
        """Documents, drift against the adopted base, local changes, warnings, decisions and archive."""
        item = documents_project(project_id)
        git = runtime.config.commit_factory(item.context, frozen_versions(item)) if runtime.config.commit_factory else None
        return call(document_status, DocumentsRepository(runtime.repository), item.context, git)

    @router.get('/projects/{project_id}/documents/content', response_model=DocumentRead,
                operation_id='managed_document')
    def document_content(project_id: str, path: Annotated[str, Query(min_length=1, max_length=500)]):
        return call(DocumentsRepository(runtime.repository).read, documents_project(project_id).context, path)

    @router.get('/projects/{project_id}/documents/tree', response_model=DocumentTreeRead,
                operation_id='managed_document_tree')
    def document_tree(project_id: str):
        """Instructions and Markdown of the contract; no symbolic links, hidden entries or content."""
        return call(project_document_tree, DocumentsRepository(runtime.repository), documents_project(project_id).context)

    @router.get('/projects/{project_id}/documents/image', response_class=Response,
                operation_id='managed_document_image',
                responses={200: {'content': {kind: {} for kind in sorted(set(IMAGE_TYPES.values()))},
                                 'description': 'Bytes of the checkout image'}})
    def document_image(project_id: str, path: Annotated[str, Query(min_length=1, max_length=500)]):
        """Checkout image for the viewer (H6.2 E3). No scripts or external resources even if opened on its own."""
        data, kind = call(DocumentsRepository(runtime.repository).image, documents_project(project_id).context, path)
        return Response(data, media_type=kind, headers={
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-cache'})

    @router.post('/projects/{project_id}/documents/edit/preview', response_model=DocumentEditPreviewRead,
                 operation_id='managed_document_edit_preview')
    def document_edit_preview(project_id: str, body: DocumentEditInput):
        """Exact diff without effects; the managed blocks and the phase archive are not edited."""
        item = documents_project(project_id)
        return call(DocumentsRepository(runtime.repository).preview, item.context, document_writer(item),
                    source=body.source, changes=_changes(body), regenerate_blocks=body.regenerate_blocks)

    @router.post('/projects/{project_id}/documents/edit', response_model=ManagedJobRead, status_code=202,
                 operation_id='managed_document_edit')
    def document_edit(project_id: str, body: DocumentEditCreate, idempotency_key: IdempotencyKey):
        item = documents_project(project_id)
        job = call(DocumentsRepository(runtime.repository).submit, item.context, key=idempotency_key,
                   versions=frozen_versions(item), preview_sha256=body.preview_sha256, reason=body.reason,
                   confirmed=body.confirmed, git=document_writer(item), source=body.source, changes=_changes(body),
                   resume_operation_id=body.resume_operation_id, regenerate_blocks=body.regenerate_blocks)
        return queued(job)

    def _changes(body):
        # Without `base_sha256` there is no CAS; with null, the document must not exist.
        return None if body.changes is None else [change.model_dump(exclude_unset=True) for change in body.changes]

    def _plan(body):
        return None if body.plan_proposal is None else body.plan_proposal.model_dump()

    from my_harness.api.schemas import PhasePlanCreate, PhasePlanInput, PhasePlanPreviewRead
    from my_harness.storage.phase_plan import PhasePlanRepository

    @router.post('/phases/{phase_id}/plan/preview', response_model=PhasePlanPreviewRead,
                 operation_id='managed_phase_plan_preview')
    def phase_plan_preview(phase_id: str, body: PhasePlanInput):
        item, _ = registered_phase(phase_id)
        plans = PhasePlanRepository(runtime.repository, phase_id, body.next_steps, _plan(body))
        return call(plans.preview, item.context, document_writer(item))

    @router.post('/phases/{phase_id}/plan', response_model=ManagedJobRead, status_code=202,
                 operation_id='managed_phase_plan')
    def phase_plan(phase_id: str, body: PhasePlanCreate, idempotency_key: IdempotencyKey):
        item, _ = registered_phase(phase_id)
        plans = PhasePlanRepository(runtime.repository, phase_id, body.next_steps, _plan(body))
        return queued(call(plans.submit, item.context, key=idempotency_key, versions=frozen_versions(item),
                           preview_sha256=body.preview_sha256, reason=body.reason, confirmed=body.confirmed,
                           git=document_writer(item), source='content', changes=None,
                           resume_operation_id=body.resume_operation_id))

    # --- H6.4: per-attempt metrics and aggregates (read-only) -----------------------------------------
    from my_harness.api.schemas import (
        AttemptMetricRead, MetricDimension, MetricGroupsRead, MetricOrder, MetricsSummaryRead, ModelMetricGroupsRead,
        TaskMetricsRead, ValidationDimension, ValidationGroupsRead,
    )
    from my_harness.storage.metrics import MetricsViews

    Scoped = Annotated[str | None, Query(min_length=1, max_length=200)]

    def metrics_scope(project_id, phase, task):
        """Without a project: global, all projects of this SQLite. Phase and task require a project."""
        runtime.ready()
        if project_id is None:
            if phase is not None or task is not None:
                raise problem(422, 'invalid_request', say('api.project_id_required'))
            return {'root': None, 'phase': None, 'task': None}
        return {'root': str(project(project_id).context.root), 'phase': phase, 'task': task}

    def metrics():
        return MetricsViews(runtime.repository.engine)

    @router.get('/metrics/summary', response_model=MetricsSummaryRead, operation_id='managed_metrics_summary')
    def metrics_summary(project_id: Scoped = None, phase: Scoped = None, task: Scoped = None):
        """Consumption, task quality, OK/KO tests of their last validation and stops by reason."""
        return call(metrics().summary, metrics_scope(project_id, phase, task))

    @router.get('/metrics/attempts', response_model=Page[AttemptMetricRead], operation_id='managed_metrics_attempts')
    def metrics_attempts(project_id: Scoped = None, phase: Scoped = None, task: Scoped = None, run_id: Scoped = None,
                         offset: Offset = 0, limit: Limit = 30):
        """Rows materialized per attempt, with per-field provenance; null is absence, not zero."""
        return call(metrics().attempts, metrics_scope(project_id, phase, task), offset, limit, run_id=run_id)

    @router.get('/metrics/groups', response_model=MetricGroupsRead, operation_id='managed_metrics_groups')
    def metrics_groups(dimension: MetricDimension, project_id: Scoped = None, phase: Scoped = None,
                       task: Scoped = None, role: Scoped = None, order: MetricOrder = 'attempts',
                       offset: Offset = 0, limit: Limit = 30):
        """Grouped consumption; with `role` and `order`, the favorite models and efforts by frequency or tokens."""
        return call(metrics().groups, metrics_scope(project_id, phase, task), dimension, offset, limit,
                    role=role, order=order)

    @router.get('/metrics/models', response_model=ModelMetricGroupsRead, operation_id='managed_metrics_models')
    def metrics_models(project_id: Scoped = None, phase: Scoped = None, task: Scoped = None, role: Scoped = None,
                       order: MetricOrder = 'attempts', offset: Offset = 0, limit: Limit = 30):
        """Consumption per reported model (Claude `modelUsage`); Codex does not report a model."""
        return call(metrics().groups, metrics_scope(project_id, phase, task), 'reported_model', offset, limit,
                    role=role, order=order)

    @router.get('/metrics/tasks', response_model=Page[TaskMetricsRead], operation_id='managed_metrics_tasks')
    def metrics_tasks(project_id: Scoped = None, phase: Scoped = None, task: Scoped = None,
                      offset: Offset = 0, limit: Limit = 30):
        """Per task: agents, attempts per role, corrections, first-time acceptance, times, tests and consumption."""
        return call(metrics().tasks, metrics_scope(project_id, phase, task), offset, limit)

    @router.get('/metrics/validations', response_model=ValidationGroupsRead, operation_id='managed_metrics_validations')
    def metrics_validations(dimension: ValidationDimension = 'phase', project_id: Scoped = None, phase: Scoped = None,
                            task: Scoped = None, offset: Offset = 0, limit: Limit = 30):
        """H6.2 E6: evolution of the tests. Each validation cycle of the tasks, OK/KO, by descending key."""
        return call(metrics().validations, metrics_scope(project_id, phase, task), dimension, offset, limit)

    # --- P001-T004 (D262): invocation accounting (read-only; never prices, backfills or launches) -------------
    from datetime import timezone
    from pydantic import AwareDatetime
    from my_harness.api.schemas import (
        AccountingCohortRead, AccountingDimension, AccountingGroupsRead, AccountingInvocationDetailRead,
        AccountingInvocationsRead, AccountingLaunch, AccountingModelKind, AccountingOrder, AccountingSource,
        AccountingSummaryRead, AccountingTasksRead, AccountingValuationRead, AccountingWork,
    )
    from my_harness.storage.accounting_views import AccountingViews

    def utc_text(value):
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds') if value is not None else None

    def accounting_query(project_id: Scoped = None, phase: Scoped = None, task: Scoped = None,
                         provider: Scoped = None, role: Scoped = None, purpose: Scoped = None,
                         source_kind: AccountingSource | None = None, outcome: Scoped = None,
                         launch: AccountingLaunch | None = None, requested_model: Scoped = None,
                         effective_model: Scoped = None, effective_model_kind: AccountingModelKind | None = None,
                         work: Annotated[list[AccountingWork] | None, Query(max_length=6)] = None,
                         started_from: AwareDatetime | None = None, started_before: AwareDatetime | None = None,
                         cohort: Scoped = None):
        """Filters of every accounting read; `cohort` (id or name) replaces the admission-bound selection."""
        filters = {**metrics_scope(project_id, phase, task), 'provider': provider, 'role': role,
                   'purpose': purpose, 'source_kind': source_kind, 'outcome': outcome, 'launch': launch,
                   'requested_model': requested_model, 'effective_model': effective_model,
                   'effective_model_kind': effective_model_kind, 'work': work,
                   'started_from': utc_text(started_from), 'started_before': utc_text(started_before)}
        return filters, cohort

    AccountingQuery = Annotated[tuple, Depends(accounting_query)]

    def accounting():
        return AccountingViews(runtime.repository.engine)

    @router.get('/accounting/summary', response_model=AccountingSummaryRead, operation_id='managed_accounting_summary')
    def accounting_summary(query: AccountingQuery):
        """Coverage, tokens, cache hit, wall throughput and compatible amount buckets of the scope."""
        filters, cohort = query
        return call(accounting().summary, filters, cohort)

    @router.get('/accounting/groups', response_model=AccountingGroupsRead, operation_id='managed_accounting_groups')
    def accounting_groups(dimension: AccountingDimension, query: AccountingQuery, order: AccountingOrder = 'invocations',
                          offset: Offset = 0, limit: Limit = 30):
        """Totals per group; each invocation enters exactly one group (mixed/unknown models are visible groups)."""
        filters, cohort = query
        return call(accounting().groups, filters, dimension, offset, limit, cohort=cohort, order=order)

    @router.get('/accounting/tasks', response_model=AccountingTasksRead, operation_id='managed_accounting_tasks')
    def accounting_tasks(query: AccountingQuery):
        """Task spend per bucket against attempted and verified-COMMITTED tasks, with explicit denominators."""
        filters, cohort = query
        return call(accounting().tasks, filters, cohort)

    @router.get('/accounting/invocations', response_model=AccountingInvocationsRead,
                operation_id='managed_accounting_invocations')
    def accounting_invocations(query: AccountingQuery, offset: Offset = 0, limit: Limit = 30):
        """Expected invocations by UTC start, including those without a capture or a valuation."""
        filters, cohort = query
        return call(accounting().invocations, filters, offset, limit, cohort)

    @router.get('/accounting/invocations/{invocation_id}', response_model=AccountingInvocationDetailRead,
                operation_id='managed_accounting_invocation')
    def accounting_invocation(invocation_id: str, cohort: Scoped = None):
        """One invocation: binding, latest allowlisted capture and its alternative component views."""
        runtime.ready()
        return call(accounting().invocation, invocation_id, cohort)

    @router.get('/accounting/invocations/{invocation_id}/valuations', response_model=Page[AccountingValuationRead],
                operation_id='managed_accounting_valuations')
    def accounting_valuations(invocation_id: str, offset: Offset = 0, limit: Limit = 10):
        """Every immutable valuation with lines, reference identity, discrepancy and cohort memberships."""
        runtime.ready()
        return call(accounting().valuations, invocation_id, offset, limit)

    @router.get('/accounting/cohorts', response_model=Page[AccountingCohortRead],
                operation_id='managed_accounting_cohorts')
    def accounting_cohorts(offset: Offset = 0, limit: Limit = 30):
        """Named backfill/repricing cohorts, newest first; a BUILDING cohort yields no full amount."""
        runtime.ready()
        return call(accounting().cohorts, offset, limit)

    # --- H4.1: contextual chat -----------------------------------------------------------------

    from my_harness.api.schemas import (
        ChatConversationCreate, ChatConversationRead, ChatConversationSummaryRead, ChatMessageCreate,
        ChatProposalAcceptCreate, ChatProposalDismissCreate, ChatCommandCreate, ChatCommandRead,
    )

    def conversation_read(conversation_id: str):
        runtime.ready()
        detail = call(runtime.chat.get, conversation_id)
        project_id = runtime.project_id(detail["root"])
        actions = detail["actions"] if project_id is not None else []
        proposals = [{**item, "actions": item["actions"] if project_id is not None else []}
                     for item in detail["proposals"]]
        return {**detail, "project_id": project_id, "actions": actions, "proposals": proposals}

    def registered_conversation(conversation_id: str):
        runtime.ready()
        project_id = runtime.project_id(call(runtime.chat.root, conversation_id))
        if project_id is None:
            raise problem(404, "not_found", say('api.conversation_unregistered'))
        return runtime.projects[project_id]

    @router.get("/projects/{project_id}/conversations", response_model=list[ChatConversationSummaryRead],
                operation_id="managed_conversations")
    def conversations(project_id: str):
        return call(runtime.chat.list, str(project(project_id).context.root))

    @router.post("/projects/{project_id}/conversations", response_model=ChatConversationRead, status_code=201,
                 operation_id="managed_create_conversation")
    def create_conversation(project_id: str, body: ChatConversationCreate, idempotency_key: IdempotencyKey):
        """Conversation separate from the execution flow; queues nothing. The same key and the same request return the
        same conversation."""
        context = project(project_id).context
        return conversation_read(call(runtime.chat.create, context, title=body.title, phase_id=body.phase_id,
                                      task_run_id=body.task_run_id, key=idempotency_key))

    @router.get("/conversations/{conversation_id}", response_model=ChatConversationRead,
                operation_id="managed_conversation")
    def conversation(conversation_id: str):
        return conversation_read(conversation_id)

    @router.post("/conversations/{conversation_id}/messages", response_model=ManagedJobRead, status_code=202,
                 operation_id="managed_chat_message")
    def chat_message(conversation_id: str, body: ChatMessageCreate, idempotency_key: IdempotencyKey):
        """New read-only turn: message and context are frozen when queued; no provider session."""
        item = registered_conversation(conversation_id)
        from my_harness.adapters.chat_snapshot import HeadSnapshot
        writer = call(runtime.config.commit_factory, item.context, frozen_versions(item)) if runtime.config.commit_factory else None
        reader = HeadSnapshot(item.context.root, executable=getattr(writer, 'executable', 'git'))
        job = call(runtime.chat.submit_message, item.context, conversation_id, body.expected_version,
                   key=idempotency_key, versions=frozen_versions(item), text=body.text, documents=body.documents,
                   run_ids=body.run_ids, reader=reader)
        return queued(job)

    @router.post("/conversations/{conversation_id}/commands/preview", response_model=ChatCommandRead,
                 operation_id="managed_chat_command_preview")
    def chat_command_preview(conversation_id: str, body: ChatCommandCreate):
        item = registered_conversation(conversation_id)
        return call(runtime.chat.command_preview, item.context, conversation_id, body.expected_version, body.text)

    @router.post("/conversations/{conversation_id}/proposals/{proposal_id}/accept", response_model=ManagedJobRead,
                 status_code=202, operation_id="managed_chat_accept")
    def accept_proposal(conversation_id: str, proposal_id: str, body: ChatProposalAcceptCreate,
                        idempotency_key: IdempotencyKey):
        """Explicit confirmation of the shown hash → linked normal task (plan, execute, review)."""
        item = registered_conversation(conversation_id)
        job = call(runtime.chat.accept, item.context, conversation_id, proposal_id, body.expected_version,
                   key=idempotency_key, versions=frozen_versions(item), proposal_sha256=body.proposal_sha256,
                   task_id=body.task_id, phase_id=body.phase_id, confirmed=body.confirmed)
        return queued(job)

    @router.post("/conversations/{conversation_id}/proposals/{proposal_id}/dismiss",
                 response_model=ChatConversationRead, operation_id="managed_chat_dismiss")
    def dismiss_proposal(conversation_id: str, proposal_id: str, body: ChatProposalDismissCreate):
        registered_conversation(conversation_id)
        call(runtime.chat.dismiss, conversation_id, proposal_id, body.expected_version, reason=body.reason)
        return conversation_read(conversation_id)

    # --- H6.5: conversational creation and planning ----------------------------------------------
    from my_harness.api.schemas import (
        DefinitionAcceptCreate, DefinitionPreviewRead, ImportPreviewRead, ImportEntryRead, PlanningApplyCreate, PlanningBriefRead,
        PlanningConversationCreate, PlanningConversationRead, PlanningConversationSummaryRead, PlanningDeferCreate,
        PlanningDismissCreate, PlanningDraftContentRead, PlanningDraftEdit, PlanningDraftsRead, PlanningMessageCreate,
        ProfileProposalPreviewCreate, ProfileProposalConfirmCreate, ProfileProposalPreviewRead, ProfileProposalAdoptedRead,
    )
    from my_harness.storage.planning import PlanningRepository

    def planning_repository():
        return PlanningRepository(runtime.repository)

    def planning_project(project_id: str):
        item = project(project_id)
        if item.context.documents is None:
            raise problem(409, 'documents_layout', say('api.planning_layout'))
        return item

    def conversation_of(item, conversation_id: str):
        root = call(planning_repository().root, conversation_id)
        if root != str(item.context.root):
            raise problem(404, 'not_found', say('api.conversation_other_project'))
        return conversation_id

    def definition_writer(item):
        """Reading and writing drafts: only targets with a bootstrap authorized by the server."""
        return bootstrap_writer(item)

    def import_reader(item):
        """P008-T011: read-only Git of the configured writer to read the tree of the project's HEAD."""
        if runtime.config.commit_factory is None:
            raise problem(409, 'git_unconfigured', say('api.reader_import'))
        return call(runtime.config.commit_factory, item.context, frozen_versions(item))

    def conversation_port(item, kind):
        """Port for each kind: bootstrap target (definition) or Git reader (import; its drafts live
        in the private area next to SQLite)."""
        port = {'definition': definition_writer, 'onboarding': import_reader}
        return port.get(kind, lambda _: None)(item)

    def drafts_port(item, conversation_id):
        """The drafts of an import are in the private area: they need neither Git nor bootstrap."""
        kind = call(planning_repository().get, conversation_id)['kind']
        return definition_writer(item) if kind == 'definition' else None

    def planning_read(item, conversation_id):
        detail = call(planning_repository().get, conversation_id)
        operation = None
        if detail['kind'] == 'definition':
            operation = call(BootstrapRepository(runtime.repository).get, item.context.root)
        return {**detail, 'project_id': item.id, 'operation': operation}

    @router.get('/projects/{project_id}/planning', response_model=list[PlanningConversationSummaryRead],
                operation_id='managed_planning_conversations')
    def planning_list(project_id: str):
        return call(planning_repository().list, planning_project(project_id).context.root)

    @router.post('/projects/{project_id}/planning', response_model=PlanningConversationRead, status_code=201,
                 operation_id='managed_planning_create')
    def planning_create(project_id: str, body: PlanningConversationCreate, idempotency_key: IdempotencyKey):
        """Definition (Markdown brief, empty target or with drafts), planning of the active phase without tasks or
        import of a project not yet managed (frozen inventory and HEAD map). The same key and the same
        request return the same conversation."""
        item = planning_project(project_id)
        writer = conversation_port(item, body.kind)
        conversation_id = call(planning_repository().create, item.context, kind=body.kind, title=body.title, brief=body.brief, structured=body.structured,
                               phase_id=body.phase_id, writer=writer, key=idempotency_key)
        return planning_read(item, conversation_id)

    @router.get('/projects/{project_id}/planning/{conversation_id}', response_model=PlanningConversationRead,
                operation_id='managed_planning_conversation')
    def planning_detail(project_id: str, conversation_id: str):
        item = planning_project(project_id)
        return planning_read(item, conversation_of(item, conversation_id))

    @router.get('/projects/{project_id}/planning/{conversation_id}/brief', response_model=PlanningBriefRead,
                operation_id='managed_planning_brief')
    def planning_brief(project_id: str, conversation_id: str):
        item = planning_project(project_id)
        return call(planning_repository().brief, conversation_of(item, conversation_id))

    @router.post('/projects/{project_id}/planning/{conversation_id}/messages', response_model=ManagedJobRead,
                 status_code=202, operation_id='managed_planning_message')
    def planning_message(project_id: str, conversation_id: str, body: PlanningMessageCreate,
                         idempotency_key: IdempotencyKey):
        """New read-only reviewer turn with the context frozen when it was queued."""
        item = planning_project(project_id)
        conversation_of(item, conversation_id)
        if runtime.config.ports_factory is None:
            raise problem(409, 'ports_unconfigured', say('api.ports_unconfigured'))
        kind = call(planning_repository().get, conversation_id)['kind']
        job = call(planning_repository().submit_message, item.context, conversation_id, body.expected_version,
                   key=idempotency_key, versions=frozen_versions(item), text=body.text,
                   writer=conversation_port(item, kind))
        return queued(job)

    @router.post('/projects/{project_id}/planning/{conversation_id}/profile/preview',
                 response_model=ProfileProposalPreviewRead, operation_id='managed_profile_proposal_preview')
    def profile_proposal_preview(project_id: str, conversation_id: str, body: ProfileProposalPreviewCreate):
        item = planning_project(project_id)
        conversation_of(item, conversation_id)
        kind = call(planning_repository().get, conversation_id)['kind']
        writer = profile_proposal_port(item, kind)
        return call(planning_repository().profile_preview, item.context, conversation_id, body.proposal_id,
                    body.expected_version, body.proposal_sha256, writer, versions=dict(item.versions))

    @router.post('/projects/{project_id}/planning/{conversation_id}/profile/confirm',
                 response_model=ProfileProposalAdoptedRead, operation_id='managed_profile_proposal_confirm')
    def profile_proposal_confirm(project_id: str, conversation_id: str, body: ProfileProposalConfirmCreate,
                                 idempotency_key: IdempotencyKey):
        item = planning_project(project_id)
        conversation_of(item, conversation_id)
        kind = call(planning_repository().get, conversation_id)['kind']
        return call(planning_repository().confirm_profile, item.context, conversation_id, body.proposal_id,
                    body.expected_version, proposal_sha256=body.proposal_sha256,
                    preview_sha256=body.preview_sha256, reason=body.reason, key=idempotency_key,
                    writer=profile_proposal_port(item, kind), versions=dict(item.versions))

    def profile_proposal_port(item, kind):
        # Reviewing/adopting a data-only draft never resolves clients or probes their versions.
        if runtime.config.commit_factory is None or (kind == 'definition' and not item.bootstrap_enabled):
            raise problem(409, 'profile_required', say('profile_proposal.required'))
        return call(runtime.config.commit_factory, item.context, dict(item.versions))

    @router.get('/projects/{project_id}/planning/{conversation_id}/drafts', response_model=PlanningDraftsRead,
                operation_id='managed_planning_drafts')
    def planning_drafts(project_id: str, conversation_id: str):
        """Drafts on disk against what the harness knows; foreign and invalid files."""
        item = planning_project(project_id)
        return call(planning_repository().drafts, item.context, conversation_of(item, conversation_id),
                    drafts_port(item, conversation_id))

    @router.get('/projects/{project_id}/planning/{conversation_id}/drafts/content', response_model=PlanningDraftContentRead,
                operation_id='managed_planning_draft')
    def planning_draft(project_id: str, conversation_id: str, path: Annotated[str, Query(min_length=1, max_length=500)]):
        """H6.2 E4: an admitted draft with its hash on disk, the base of the editor's CAS."""
        item = planning_project(project_id)
        return call(planning_repository().draft, item.context, conversation_of(item, conversation_id), path,
                    drafts_port(item, conversation_id))

    @router.put('/projects/{project_id}/planning/{conversation_id}/drafts', response_model=PlanningConversationRead,
                operation_id='managed_planning_draft_edit')
    def planning_draft_edit(project_id: str, conversation_id: str, body: PlanningDraftEdit):
        """User edit with CAS on the hash on disk; never overwrites another change."""
        item = planning_project(project_id)
        call(planning_repository().edit_draft, item.context, conversation_of(item, conversation_id), body.expected_version,
             path=body.path, content=body.content, base_sha256=body.base_sha256,
             writer=drafts_port(item, conversation_id))
        return planning_read(item, conversation_id)

    @router.post('/projects/{project_id}/planning/{conversation_id}/proposals/{proposal_id}/apply',
                 response_model=PlanningConversationRead, operation_id='managed_planning_apply')
    def planning_apply(project_id: str, conversation_id: str, proposal_id: str, body: PlanningApplyCreate):
        """The harness writes the confirmed draft if it is still the one the turn read (CAS)."""
        item = planning_project(project_id)
        call(planning_repository().apply, item.context, conversation_of(item, conversation_id), proposal_id,
             body.expected_version, proposal_sha256=body.proposal_sha256, confirmed=body.confirmed,
             writer=drafts_port(item, conversation_id))
        return planning_read(item, conversation_id)

    @router.post('/projects/{project_id}/planning/{conversation_id}/proposals/{proposal_id}/dismiss',
                 response_model=PlanningConversationRead, operation_id='managed_planning_dismiss')
    def planning_dismiss(project_id: str, conversation_id: str, proposal_id: str, body: PlanningDismissCreate):
        item = planning_project(project_id)
        call(planning_repository().dismiss, conversation_of(item, conversation_id), proposal_id, body.expected_version,
             reason=body.reason)
        return planning_read(item, conversation_id)

    @router.post('/projects/{project_id}/planning/{conversation_id}/questions/defer',
                 response_model=PlanningConversationRead, operation_id='managed_planning_defer')
    def planning_defer(project_id: str, conversation_id: str, body: PlanningDeferCreate):
        """Explicit deferral of a blocking question, with a reason; does not answer it."""
        item = planning_project(project_id)
        call(planning_repository().defer, conversation_of(item, conversation_id), body.expected_version,
             question_id=body.question_id, reason=body.reason)
        return planning_read(item, conversation_id)

    from my_harness.storage.onboarding_commit import OnboardingRepository
    from my_harness.api.schemas import OnboardingConfirmCreate

    @router.get('/projects/{project_id}/onboarding', response_model=ImportEntryRead,
                operation_id='managed_onboarding_entry')
    def onboarding_entry(project_id: str):
        item = planning_project(project_id)
        return {'refusal': runtime.repository.guard.assess(item.context.root).refusal,
                'operation': call(OnboardingRepository(runtime.repository).get, item.context.root)}

    @router.post('/projects/{project_id}/planning/{conversation_id}/onboarding/preview',
                 response_model=ImportPreviewRead, operation_id='managed_onboarding_preview')
    def onboarding_preview(project_id: str, conversation_id: str):
        item = planning_project(project_id)
        return call(OnboardingRepository(runtime.repository).preview, item.context,
                    conversation_of(item, conversation_id), frozen_versions(item), import_reader(item))

    @router.post('/projects/{project_id}/planning/{conversation_id}/onboarding/confirm',
                 response_model=ManagedJobRead, status_code=202, operation_id='managed_onboarding_confirm')
    def onboarding_confirm(project_id: str, conversation_id: str, body: OnboardingConfirmCreate,
                           idempotency_key: IdempotencyKey):
        item = planning_project(project_id)
        job = call(OnboardingRepository(runtime.repository).submit, item.context,
                   conversation_of(item, conversation_id), frozen_versions(item), import_reader(item),
                   key=idempotency_key, **body.model_dump())
        return queued(job)

    @router.post('/projects/{project_id}/planning/{conversation_id}/accept/preview',
                 response_model=DefinitionPreviewRead, operation_id='managed_definition_accept_preview')
    def definition_accept_preview(project_id: str, conversation_id: str):
        """Complete files of the root commit, phase-000 archive, blocks, P001, profile and commands; or blockers."""
        item = planning_project(project_id)
        return call(BootstrapRepository(runtime.repository).preview, item.context,
                    {'conversation_id': conversation_of(item, conversation_id)}, frozen_versions(item),
                    definition_writer(item))

    @router.post('/projects/{project_id}/planning/{conversation_id}/accept', response_model=ManagedJobRead,
                 status_code=202, operation_id='managed_definition_accept')
    def definition_accept(project_id: str, conversation_id: str, body: DefinitionAcceptCreate,
                          idempotency_key: IdempotencyKey):
        """Confirms the exact preview: D037 bootstrap with the v2 template and P001 ACTIVE adopted."""
        item = planning_project(project_id)
        job = call(BootstrapRepository(runtime.repository).submit, item.context,
                   {'conversation_id': conversation_of(item, conversation_id)}, frozen_versions(item),
                   definition_writer(item), key=idempotency_key, **body.model_dump())
        return queued(job)

    # --- UI authority for creating new children (P009-T002 / D116) ---------------------
    from my_harness.api.schemas import (
        CreationRootChangeInput, CreationRootApplyInput, CreationRootRead, CreationRootPreviewRead,
        CreationInput, CreationConfirmInput, CreationPreviewRead, CreationOperationRead,
        CreationResumeInput, CreationResumePreviewRead, CreationResumeConfirmInput, CreationCancelInput,
    )

    @router.get('/project-creation-root', response_model=CreationRootRead, operation_id='managed_creation_root')
    def creation_root():
        runtime.ready()
        return registry(runtime.creation.read_root)

    @router.post('/project-creation-root/preview', response_model=CreationRootPreviewRead,
                 operation_id='managed_creation_root_preview')
    def creation_root_preview(body: CreationRootChangeInput):
        return registry(runtime.creation.root_preview, body.model_dump(exclude_none=True))

    @router.post('/project-creation-root/apply', response_model=CreationRootPreviewRead,
                 operation_id='managed_creation_root_apply')
    def creation_root_apply(body: CreationRootApplyInput, idempotency_key: IdempotencyKey):
        return registry(runtime.creation.root_apply, body.model_dump(exclude_none=True), idempotency_key)

    @router.post('/project-creations/preview', response_model=CreationPreviewRead,
                 operation_id='managed_creation_preview')
    def creation_preview(body: CreationInput):
        return registry(runtime.creation.preview, body.model_dump(exclude_none=True))

    @router.post('/project-creations/confirm', response_model=CreationOperationRead,
                 operation_id='managed_creation_confirm')
    def creation_confirm(body: CreationConfirmInput, idempotency_key: IdempotencyKey):
        return registry(runtime.creation.confirm, body.model_dump(exclude_none=True), idempotency_key)

    @router.get('/project-creations/{operation_id}', response_model=CreationOperationRead,
                operation_id='managed_creation_operation')
    def creation_operation(operation_id: str):
        return registry(runtime.creation.repository.read, operation_id)

    @router.post('/project-creations/{operation_id}/resume/preview', response_model=CreationResumePreviewRead,
                 operation_id='managed_creation_resume_preview')
    def creation_resume_preview(operation_id: str, body: CreationResumeInput):
        return registry(runtime.creation.resume_preview, operation_id, body.model_dump(exclude_none=True))

    @router.post('/project-creations/{operation_id}/resume/confirm', response_model=CreationOperationRead,
                 operation_id='managed_creation_resume_confirm')
    def creation_resume_confirm(operation_id: str, body: CreationResumeConfirmInput, idempotency_key: IdempotencyKey):
        return registry(runtime.creation.resume, operation_id, body.model_dump(exclude_none=True), idempotency_key)

    @router.post('/project-creations/{operation_id}/cancel', response_model=CreationOperationRead,
                 operation_id='managed_creation_cancel')
    def creation_cancel(operation_id: str, body: CreationCancelInput, idempotency_key: IdempotencyKey):
        return registry(runtime.creation.cancel, operation_id, body.model_dump(exclude_none=True), idempotency_key)

    from my_harness.api.schemas import (
        PreparationChangeInput, PreparationConfirmInput, PreparationControlInput,
        ProfilePreparationChangeInput, ProfilePreparationConfirmInput,
        PreparationRead, PreparationPlanRead, PreparationOperationRead,
    )

    @router.get('/projects/{project_id}/preparation', response_model=PreparationRead,
                operation_id='managed_preparation')
    def preparation_status(project_id: str):
        return registry(runtime.preparation.read, project_id)

    @router.post('/projects/{project_id}/preparation/preview', response_model=PreparationPlanRead,
                 operation_id='managed_preparation_preview')
    def preparation_preview(project_id: str, body: PreparationChangeInput | ProfilePreparationChangeInput):
        return registry(runtime.preparation.preview, project_id, body.model_dump(exclude_none=True))

    @router.post('/projects/{project_id}/preparation/confirm', response_model=PreparationOperationRead,
                 operation_id='managed_preparation_confirm')
    def preparation_confirm(project_id: str, body: PreparationConfirmInput | ProfilePreparationConfirmInput, idempotency_key: IdempotencyKey):
        return registry(runtime.preparation.confirm, project_id, body.model_dump(exclude_none=True), idempotency_key)

    @router.get('/preparations/{operation_id}', response_model=PreparationOperationRead,
                operation_id='managed_preparation_operation')
    def preparation_operation(operation_id: str):
        return registry(runtime.preparation.repository.read, operation_id)

    @router.post('/preparations/{operation_id}/cancel', response_model=PreparationOperationRead,
                 operation_id='managed_preparation_cancel')
    def preparation_cancel(operation_id: str, body: PreparationControlInput, idempotency_key: IdempotencyKey):
        return registry(runtime.preparation.control, operation_id, body.model_dump(exclude_none=True), 'cancel', idempotency_key)

    @router.post('/preparations/{operation_id}/confirm-stopped', response_model=PreparationOperationRead,
                 operation_id='managed_preparation_confirm_stopped')
    def preparation_stopped(operation_id: str, body: PreparationControlInput, idempotency_key: IdempotencyKey):
        return registry(runtime.preparation.control, operation_id, body.model_dump(exclude_none=True), 'confirm-stopped', idempotency_key)

    return router
