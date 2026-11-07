// Synthetic, typed T023 evidence only. Generated a page at a time; no service or real agent is involved.
import type { S } from "../../managed-api";
export const TRACE_SIZE = 5000;
const DIGEST = "a".repeat(64);
const at = (seq: number) => new Date(Date.UTC(2026, 10, 7, 10, 0, 0) + seq * 10).toISOString();
export function traceStep(seq: number): S["MapTraceStep"] {
  const kind = (["turn", "tool_call", "tool_call", "message", "reasoning", "tool_call", "not_observed", "message", "tool_call", "not_observed"] as const)[seq % 10];
  const oversize = seq % 10 === 1;
  const log = oversize ? { operation_id: "managed_attempt_logs", path: "/api/managed/runs/fixture-run/attempts/fixture-attempt/logs",
    stream: "stdout", offset: seq * 20, size: 20000, sha256: DIGEST } : null;
  return { seq, kind, source_records: kind === "not_observed" ? [] : [{ run_id: "fixture-run", attempt_id: "fixture-attempt", sequence: seq + 1, record: seq + 1, oversize,
    event: { operation_id: "managed_run_events", path: "/api/managed/runs/fixture-run/events", query: { after: seq, limit: 1 } }, log,
    availability: seq === 11 ? "unavailable_after_retention" : "available", availability_source: "derived" }],
    format: "observed-step-1", parent_seq: kind === "turn" ? null : seq - seq % 10,
    unit: kind === "turn" ? seq % 20 === 0 ? "codex_turn" : "claude_message" : undefined,
    tool: kind === "tool_call" ? { name: seq % 10 === 5 ? "retry.lookup" : "synthetic.lookup", origin: "native" } : undefined,
    call_id: kind === "tool_call" ? `call-${seq}` : undefined,
    parallel: kind === "tool_call" && seq % 10 < 3,
    outcome: seq === 1 ? "error" : kind === "not_observed" || seq % 10 === 8 ? "not_observed" : "completed",
    reason: kind === "not_observed" ? "partial_tail" : undefined,
    started_at: ["message", "reasoning", "not_observed"].includes(kind) ? null : at(seq), finished_at: at(seq + 3),
    duration_ms: ["message", "reasoning", "not_observed"].includes(kind) ? null : 30, timing: "chunk_receipt",
    arguments: kind === "tool_call" ? { size: 42, sha256: DIGEST, summary: "synthetic [REDACTED]" } : undefined,
    message: kind === "message" ? { present: true, size: 32, sha256: DIGEST, final: seq % 10 === 7 } : undefined,
    reasoning: kind === "reasoning" ? { present: true, size: 64, sha256: DIGEST } : undefined,
  };
}
export function relatedRecords(): S["MapRelatedRead"]["items"] {
  return ["knowledge.delivered", "knowledge.receipt", "tool.discovered", "tool.discovered", "judge.requested", "judge.ruled"].map((kind, index) => ({
    sequence: index + 1, event_id: `fixture-event-${index}`, kind, category: index < 2 ? "receipt" : index < 4 ? "discovery" : "ruling",
    source: "measured", operation_id: "fixture-operation", thread_id: "fixture-thread", parent_event_id: index ? `fixture-event-${index - 1}` : null,
    // First in event-id read order, received near step #4500: group pages are not temporal windows.
    causation_id: index === 5 ? "fixture-event-4" : null, recorded_at: at(index === 0 ? 4500 : index * 3), truncated: false, redactions: 0,
    fields: index < 2 ? { revision_id: "fixture-revision", exposure: "available", digest: DIGEST }
      : index < 4 ? { action: index === 2 ? "search" : "describe", schema_sha256: DIGEST } : { request_id: "fixture-request", status: "VALIDATED" },
    artifacts: index === 1 ? [{ sha256: DIGEST, size: 22, media: "application/json", path: `/api/managed/knowledge/projects/kp-atlas/traces/fixture-thread/artifacts/${DIGEST}` }] : [],
  }));
}
export function permissionRecords(): S["MapPermissionRecord"][] {
  return [{ source: "standing_permission", id: "fixture-request", status: { code: "EXPIRED", class: "inactive" }, response: "grant", authority: "expired",
    answerable: false, created_at: at(5), expires_at: at(9), inbox_item_id: "standing_permission:fixture-request" }];
}
export function tracePage(header: S["MapInvocationRead"], url: URL, group: string, size = TRACE_SIZE) {
  const prefix = `opaque-t023-${header.invocation.invocation_id}-${header.version}-${group}-`;
  const cursor = url.searchParams.get("cursor");
  if (cursor && !cursor.startsWith(prefix)) return { stale: true };
  const start = cursor ? Number(cursor.slice(prefix.length)) : 0;
  const total = group === "steps" ? size : group === "records" ? relatedRecords().length : permissionRecords().length;
  const limit = Math.min(200, Number(url.searchParams.get("limit") ?? 200));
  const items = group === "steps" ? Array.from({ length: Math.min(limit, total - start) }, (_, i) => traceStep(start + i))
    : (group === "records" ? relatedRecords() : permissionRecords()).slice(start, start + limit);
  return { format: "work-map-1", level: group === "steps" ? "trace" : "related", scope: `s1.fixture.${group}.${header.invocation.invocation_id}`,
    version: header.version, read_only_archive: header.read_only_archive, project: header.project, invocation_id: header.invocation.invocation_id,
    state: header.steps.state, reason: header.steps.reason, group, items, next_cursor: start + limit < total ? prefix + (start + limit) : null };
}
const DOCS: Record<string, string> = {
  "docs/ROADMAP.md": "# Roadmap\n\n## P002 — Synthetic phase\n\n[Tasks](NEXT_STEPS.md)\n",
  "docs/NEXT_STEPS.md": "# Tasks\n\n## P002-T005 — Synthetic task\n\nAccepted canonical knowledge.\n\n[Roadmap](ROADMAP.md#p002--synthetic-phase)\n\n```mermaid\ngraph LR\n  A-->B\n```\n",
  "docs/SPECIFICATION.md": "# Specification\n\nSynthetic read-only documentation.\n",
};
export function fixtureDocuments(url: URL): S["MapDocumentsRead"] {
  const path = url.searchParams.get("path");
  return { source: "canonical", revision_id: "fixture-revision", tree: { docs: "docs", truncated: false, skipped: [], files: Object.entries(DOCS).map(([path, text]) => ({
    path, kind: "other", editable: false, archived: false, bytes: text.length })) }, path, content: path ? DOCS[path] ?? null : null };
}
export function originalFixture(parts: string[], url: URL): unknown {
  if (parts[0] === "runs" && parts[1] === "fixture-run") {
    if (parts[2] === "events") {
      const sequence = Number(url.searchParams.get("after")) + 1, step = traceStep(sequence - 1);
      return { items: [{ id: sequence, sequence, kind: "agent_event", recorded_at: at(sequence), payload: { attempt_id: "fixture-attempt",
        ...(step.source_records[0]?.oversize ? { original_reference: step.source_records[0].log } : { original: { type: "synthetic", text: "Original synthetic record" } }) } }], cursor: sequence, has_more: false };
    }
    if (parts[4] === "logs") {
      const sequence = Number(url.searchParams.get("sequence"));
      if (sequence) {
        const source = traceStep(sequence - 1).source_records[0], log = source.log!;
        const retained = source.availability === "available";
        const text = JSON.stringify({ type: "synthetic", text: "Original large synthetic record <script>escaped text</script>" });
        return { run_id: "fixture-run", attempt_id: "fixture-attempt", sequence, stream: "stdout", offset: log.offset,
          size_bytes: log.size, sha256: log.sha256, encoding: "utf-8", limit_bytes: 4194305,
          state: retained ? "retained" : "purged", diagnostic: null,
          content: retained ? text.padEnd(Number(log.size) - 1, " ") + "\n" : null };
      }
      return [{ stream: "stdout", source: "sealed", sha256: DIGEST, size_bytes: 100000, state: "retained", diagnostic: null, authorization: null }];
    }
  }
  if (parts[0] === "knowledge" && parts[1] === "projects" && parts[3] === "traces")
    return parts[5] === "artifacts" ? { content: { synthetic: true }, sha256: DIGEST }
      : { items: [{ event_id: `fixture-event-${url.searchParams.get("after")}`, payload: { synthetic: true } }], has_more: false };
  return undefined;
}
