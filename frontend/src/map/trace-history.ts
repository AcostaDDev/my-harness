import { isStaleCursor, mapPaths, pageOf, read } from "./api.ts";
import type { MapRelated, MapTrace } from "./api.ts";
import { traceItems, traceOrder } from "./trace.ts";
import type { TraceItem } from "./trace.ts";
import { usePagedLevel } from "./use-level.ts";

const GROUPS = ["steps", "records", "permissions"] as const;
type Group = typeof GROUPS[number];
export type TraceGroup = Group | "all";
type Request = { group: Group; path: string; cursor?: string };
type TracePage = {
  id: symbol;
  items: TraceItem[];
  scopes: [string, string][];
  steps?: Pick<MapTrace, "state" | "reason">;
  next_cursor?: Request[];
};

async function readGroup(request: Request) {
  const path = pageOf(request.path, request.cursor);
  if (request.group === "steps") {
    const page = await read<MapTrace>(path);
    return { page, items: traceItems(page.items, []), steps: { state: page.state, reason: page.reason } };
  }
  const page = await read<MapRelated>(path);
  return { page, items: traceItems([], page.items), steps: undefined };
}

export function useTraceHistory(project: string, invocation: string, group: TraceGroup) {
  async function readBatch(_path: string, pending?: Request[] | null): Promise<TracePage> {
    const groups = group === "all" ? GROUPS : [group];
    const requests = pending ?? groups.map(key => ({ group: key, path: key === "steps"
      ? mapPaths.trace(project, invocation) : mapPaths.related(project, invocation, key) }));
    // Commit a whole batch together. If any cursor is stale, discard the batch and restart all its scopes.
    const results = await Promise.allSettled(requests.map(readGroup));
    const stale = results.find(result => result.status === "rejected" && isStaleCursor(result.reason));
    if (stale?.status === "rejected") throw stale.reason;
    const pages = results.map(result => {
      if (result.status === "rejected") throw result.reason;
      return result.value;
    });
    const next = pages.flatMap(({ page }, index) => page.next_cursor
      ? [{ ...requests[index], cursor: page.next_cursor }] : []);
    const items = pages.flatMap(part => part.items);
    return { id: Symbol(), items: traceOrder(items),
      scopes: pages.map(({ page }) => [page.scope, page.version]), steps: pages.find(part => part.steps)?.steps,
      next_cursor: next.length ? next : undefined };
  }
  return usePagedLevel(`${mapPaths.invocation(project, invocation)}?group=${group}`, readBatch);
}
