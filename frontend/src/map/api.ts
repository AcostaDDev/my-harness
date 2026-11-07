// Read client of T020's work-map projections (`GET /api/managed/map/…`, D306, D311) and of the element request list
// (P002-T022 review, D314). Paths only carry encoded identities, exact filters and the opaque cursor or scope tokens
// the service issued; the client never decodes them.
import { managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";

export type MapProjects = S["MapProjectsRead"];
export type MapPhases = S["MapPhasesRead"];
export type MapTasks = S["MapTasksRead"];
export type MapRuns = S["MapRunsRead"];
export type MapSteps = S["MapStepsRead"];
export type MapActivity = S["MapActivityRead"];
export type MapInvocation = S["MapInvocationRead"];
export type MapTrace = S["MapTraceRead"];
export type MapRelated = S["MapRelatedRead"];
export type MapBubblesPage = S["MapBubblesRead"];
/** Exact scope and circle of an element's request list (T020 attribution; absent filters match every item). */
export type BubbleFilter = { phase?: string; task?: string; run?: string; attempt?: string; circle?: string };
/** Every paged level read shares these fields. */
export type Paged = { scope: string; version: string; read_only_archive: boolean; next_cursor?: string | null };

const e = encodeURIComponent;

export const mapPaths = {
  projects: () => "/map/projects",
  phases: (project: string) => `/map/projects/${e(project)}/phases`,
  tasks: (project: string, phase: string) => `/map/projects/${e(project)}/phases/${e(phase)}/tasks`,
  runs: (project: string, phase: string, task: string) => `/map/projects/${e(project)}/phases/${e(phase)}/tasks/${e(task)}/runs`,
  steps: (project: string, run: string) => `/map/projects/${e(project)}/runs/${e(run)}/steps`,
  invocation: (project: string, invocation: string) => `/map/projects/${e(project)}/invocations/${e(invocation)}`,
  trace: (project: string, invocation: string) => `/map/projects/${e(project)}/invocations/${e(invocation)}/steps?limit=200`,
  related: (project: string, invocation: string, group: "records" | "permissions") => `/map/projects/${e(project)}/invocations/${e(invocation)}/related?group=${group}&limit=200`,
  documents: (project: string, path?: string) => `/map/projects/${e(project)}/documents${path ? `?path=${e(path)}` : ""}`,
  /** One element's open requests with their circle, filtered by exact scope and circle on every page. */
  bubbles: (project: string, filter: BubbleFilter = {}) => {
    const params = new URLSearchParams();
    for (const key of ["phase", "task", "run", "attempt", "circle"] as const) if (filter[key]) params.set(key, filter[key]!);
    const query = params.toString();
    return `/map/projects/${e(project)}/bubbles${query ? `?${query}` : ""}`;
  },
  /** At most 10 scopes per poll (T020); duplicates are sent once. */
  activity: (scopes: readonly string[]) => `/map/activity?${[...new Set(scopes)].slice(0, MAX_SCOPES).map(scope => `scope=${e(scope)}`).join("&")}`,
};

export const MAX_SCOPES = 10;

/** The next page of `path`: the opaque cursor is passed back unchanged. */
export function pageOf(path: string, cursor?: string | null): string {
  return cursor ? `${path}${path.includes("?") ? "&" : "?"}cursor=${e(cursor)}` : path;
}

/** `409 cursor_stale`: the page's version was superseded; the caller reloads the first page (D029 gap recovery). */
export function isStaleCursor(error: unknown): boolean {
  return error instanceof ManagedError && error.status === 409 && error.code === "cursor_stale";
}

export function isMissing(error: unknown): boolean {
  return error instanceof ManagedError && error.status === 404;
}

/** Reads through the shared managed client (GET, session-aware). */
export const read = <T,>(path: string) => managed<T>(path);
