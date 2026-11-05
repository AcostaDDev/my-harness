"""P002-T020 (D306, D311): read-only `GET` work-map projections under `/api/managed/map/`.

No mutation route exists here and edges execute nothing. The routes read SQLite only, through the same session and
Host/Origin guards as every API route, and serve restored `query_only` archives unchanged (no checkout, provider or
project composition). Unknown and foreign identifiers answer alike (404); cursors bound to another scope, level or
project are refused (422) and a cursor of a superseded version answers `409 cursor_stale`.
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query

from my_harness.api.managed import ERRORS
from my_harness.api.schemas import (
    MapActivityRead, MapInvocationRead, MapPhasesRead, MapProjectsRead, MapRelatedRead, MapRunsRead, MapStepsRead,
    MapTasksRead, MapTraceRead,
)
from my_harness.api.security import local_request, problem
from my_harness.core.engine import work_map as wm
from my_harness.i18n import message
from my_harness.services.managed_runtime import ManagedRuntime, agents_view
from my_harness.storage.operation_journal import now
from my_harness.storage.preferences import language
from my_harness.storage.work_map import MapNotFound, WorkMap

Ident = Annotated[str, Path(min_length=1, max_length=200)]
Cursor = Annotated[str | None, Query(min_length=1, max_length=2048, description='Opaque keyset cursor of the previous page.')]


def _limit(level):
    return Annotated[int, Query(ge=1, le=wm.LIMITS[level])]


def work_map_router(runtime: ManagedRuntime) -> APIRouter:
    router = APIRouter(prefix='/api/managed/map', dependencies=[Depends(local_request)], responses=ERRORS)

    def work_map() -> WorkMap:
        projects = dict(runtime.projects)  # empty in restored archives: nothing is composed there
        return WorkMap(runtime.engine, {p.id: str(p.context.root) for p in projects.values()},
                       {str(p.context.root): agents_view(p) for p in projects.values()},
                       runtime.repository._now if runtime.repository else now)

    def say(key):
        return message(key, language(runtime.engine))

    def call(read, *args, **kwargs):
        try:
            return read(*args, **kwargs)
        except MapNotFound:
            raise problem(404, 'map_not_found', say('work_map.not_found')) from None
        except wm.StaleCursor:
            raise problem(409, 'cursor_stale', say('work_map.cursor_stale')) from None
        except wm.TokenError as error:
            if error.args and error.args[0] == 'scope':
                raise problem(422, 'scope_invalid', say('work_map.scope_invalid')) from None
            raise problem(422, 'cursor_invalid', say('work_map.cursor_invalid')) from None

    @router.get('/projects', response_model=MapProjectsRead, operation_id='map_projects')
    def projects(cursor: Cursor = None, limit: _limit('projects') = wm.LIMITS['projects']):
        """L0: project cards (status class, mode, circles, active invocations, counters, bubbles)."""
        return call(work_map().projects, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/phases', response_model=MapPhasesRead, operation_id='map_phases')
    def phases(project_id: Ident, cursor: Cursor = None, limit: _limit('phases') = wm.LIMITS['phases']):
        """L1: roadmap phases with their instances, Plan · Check · Close slots and roadmap order edges."""
        return call(work_map().phases, project_id, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/phases/{code}/tasks', response_model=MapTasksRead, operation_id='map_tasks')
    def tasks(project_id: Ident, code: Ident, cursor: Cursor = None, limit: _limit('tasks') = wm.LIMITS['tasks']):
        """L2: task nodes of one phase with `depends_on` and `replaces` edges."""
        return call(work_map().tasks, project_id, code, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/phases/{code}/tasks/{task}/runs', response_model=MapRunsRead,
                operation_id='map_task_runs')
    def runs(project_id: Ident, code: Ident, task: Ident, cursor: Cursor = None,
             limit: _limit('runs') = wm.LIMITS['runs']):
        """Run selector of one task, latest first."""
        return call(work_map().runs, project_id, code, task, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/runs/{run_id}/steps', response_model=MapStepsRead, operation_id='map_run_steps')
    def steps(project_id: Ident, run_id: Ident, cursor: Cursor = None, limit: _limit('steps') = wm.LIMITS['steps']):
        """L3: agent invocations and Harness validate, format and commit stages of one run, in order."""
        return call(work_map().steps, project_id, run_id, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/invocations/{invocation_id}', response_model=MapInvocationRead,
                operation_id='map_invocation')
    def invocation(project_id: Ident, invocation_id: Ident):
        """L4 header: identity, owning context for navigation, counters and the observed-step state."""
        return call(work_map().invocation, project_id, invocation_id)

    @router.get('/projects/{project_id}/invocations/{invocation_id}/steps', response_model=MapTraceRead,
                operation_id='map_invocation_steps')
    def trace(project_id: Ident, invocation_id: Ident, cursor: Cursor = None,
              limit: _limit('trace') = wm.LIMITS['trace']):
        """L4: observed steps (T019) with source records resolved to the existing event and log routes."""
        return call(work_map().trace, project_id, invocation_id, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/invocations/{invocation_id}/related', response_model=MapRelatedRead,
                operation_id='map_invocation_related')
    def related(project_id: Ident, invocation_id: Ident, group: Literal['records', 'permissions'],
                cursor: Cursor = None, limit: _limit('related') = wm.LIMITS['related']):
        """L4 related records: receipts, discovery and schema loads, broker and tool events, rulings and
        artifacts (`records`), or the permission requests the attempt raised (`permissions`)."""
        return call(work_map().related, project_id, invocation_id, group, cursor=cursor, limit=limit)

    @router.get('/activity', response_model=MapActivityRead, operation_id='map_activity')
    def activity(scope: Annotated[list[str], Query(description='Scope ids returned by the level responses '
                                                               f'(at most {wm.MAX_SCOPES}).')] = []):
        """Polling summary: version token per requested scope, active invocations and bubble counters."""
        return call(work_map().activity, scope)

    return router
