// Bounded adapters only. Native messages/results never enter this model (TM14/TM17).
import type { S } from "../managed-api";
import type { Translate } from "../i18n.ts";
import type { MapNode, MapEdge } from "./MapView";
export type TraceStep = S["MapTraceStep"];
export type Related = S["MapRelatedRecord"];
export type Permission = S["MapPermissionRecord"];
export type TraceItem = { id: string; step?: TraceStep; record?: Related; permission?: Permission; anchorSeq?: number };
export const stepId = (seq: number) => `step:${seq}`;
export function traceItems(steps: readonly TraceStep[], records: readonly (Related | Permission)[]): TraceItem[] {
  return [...steps.map(step => ({ id: stepId(step.seq), step })), ...records.map(record => "event_id" in record
    ? { id: `record:${record.event_id}`, record } : { id: `permission:${record.source}:${record.id}`, permission: record })];
}
export function traceTitle(item: TraceItem, t: Translate): string {
  if (item.step) {
    const tool = item.step.tool;
    const name = tool && typeof tool === "object" && "name" in tool && typeof tool.name === "string" ? tool.name : undefined;
    return `${t(`trace.kind.${item.step.kind}`)}${name ? ` · ${name}` : ""}`;
  }
  if (item.record) return item.record.kind;
  return t("trace.permission");
}
export function traceOutcome(item: TraceItem): string {
  return item.step ? typeof item.step.outcome === "string" ? item.step.outcome : "not_observed"
    : item.permission ? item.permission.status.code ?? "not_observed" : "recorded";
}
/** Parent membership is not a claim of causation. Sequence edges order turns only, never serialize siblings. */
export function traceGraph(items: readonly TraceItem[], t: Translate): { nodes: MapNode[]; edges: MapEdge[] } {
  const ids = new Set(items.map(item => item.id));
  const edges: MapEdge[] = [];
  const turns = items.flatMap(item => item.step?.kind === "turn" ? [item.step.seq] : []).sort((a, b) => a - b);
  for (let i = 1; i < turns.length; i++)
    edges.push({ from: stepId(turns[i - 1]), to: stepId(turns[i]), kind: "sequence" });
  for (const item of items) {
    const step = item.step;
    if (item.anchorSeq !== undefined && ids.has(stepId(item.anchorSeq)))
      edges.push({ from: stepId(item.anchorSeq), to: item.id, kind: "correlation" });
    if (typeof step?.parent_seq === "number" && ids.has(stepId(step.parent_seq)))
      edges.push({ from: stepId(step.parent_seq), to: item.id, kind: "containment" });
    const parent = item.record?.parent_event_id;
    const cause = item.record?.causation_id;
    // When both fields point to the same event, draw the explicit cause once. The inspector shows both fields.
    if (parent && parent !== cause && ids.has(`record:${parent}`))
      edges.push({ from: `record:${parent}`, to: item.id, kind: "parentage" });
    if (cause && ids.has(`record:${cause}`))
      edges.push({ from: `record:${cause}`, to: item.id, kind: "causation" });
  }
  return { edges, nodes: items.map((item, index) => {
    const raw = traceOutcome(item);
    const cls = item.permission?.status.class ?? (raw === "cancelled_in_flight" ? "inactive" : ["error", "denied", "failed"].includes(raw) ? "failed"
      : ["completed", "recorded"].includes(raw) ? "done" : "unknown");
    return { id: item.id, kind: "step", order: String(index).padStart(6, "0"),
      code: item.step ? `#${item.step.seq}` : item.record ? `e${item.record.sequence}` : item.permission!.id,
      title: traceTitle(item, t), status: raw, statusClass: cls,
      statusLabel: item.permission ? undefined : t(`trace.outcome.${raw}` as Parameters<typeof t>[0]),
      badge: item.step?.parallel === true ? t("trace.parallel") : item.step ? undefined : tracePosition(item, t),
      counter: typeof item.step?.duration_ms === "number" ? `${item.step.duration_ms} ms · ${t("trace.receipt_short")}`
        : item.step ? t("map.not_observed") : t("trace.recorded"), errors: cls === "failed" ? 1 : 0 };
  }) };
}
/** Existing authenticated API target; no interpretation of offsets as a supported byte-range request. */
export function sourcePath(route: S["MapRoute"]): string {
  const path = route.path.replace(/^\/api\/managed/, "");
  const query = new URLSearchParams(Object.entries(route.query ?? {}).map(([key, value]) => [key, String(value)]));
  return `${path}${query.size ? `?${query}` : ""}`;
}

export function tracePosition(item: TraceItem, t: Translate): string {
  return item.anchorSeq === undefined ? t("trace.position_unknown") : t("trace.position_step", { seq: item.anchorSeq });
}

/** A batch is a bounded read unit, never a temporal watermark across independently ordered cursors.
 * Keep native seq. Only an exact, unambiguous persisted tool.links event identity anchors a record to a step in this
 * batch. All other evidence stays in a separate, explicitly unpositioned section, in its group's read order.
 * Never move an already published item when later pages arrive: held windows must be reproducible.
 */
export function traceOrder(items: readonly TraceItem[]): TraceItem[] {
  const anchors = new Map<string, number | null>();
  for (const { step } of items) {
    const tool = step?.tool;
    if (!step || !tool || typeof tool !== "object" || !("links" in tool)) continue;
    const links = tool.links;
    if (!links || typeof links !== "object" || Array.isArray(links)) continue;
    for (const key of ["call_event_id", "result_event_id", "logical_call_event_id", "logical_result_event_id", "discovery_event_id"]) {
      const id = (links as Record<string, unknown>)[key];
      if (typeof id === "string" && id) anchors.set(id, anchors.has(id) && anchors.get(id) !== step.seq ? null : step.seq);
    }
  }
  const positioned: TraceItem[] = [], unpositioned: TraceItem[] = [];
  for (const item of items) {
    if (item.step) { positioned.push(item); continue; }
    const anchor = item.record ? anchors.get(item.record.event_id) : undefined;
    if (typeof anchor === "number") positioned.push({ ...item, anchorSeq: anchor });
    else unpositioned.push(item);
  }
  const seq = (item: TraceItem) => item.step?.seq ?? item.anchorSeq!;
  return [...positioned.sort((a, b) => seq(a) - seq(b) || Number(!a.step) - Number(!b.step)), ...unpositioned];
}
