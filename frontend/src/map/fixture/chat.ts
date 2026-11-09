// T024 visual fixture only: the real composer against in-memory synthetic responses. No backend mutation.
import type { S } from "../../managed-api";
import type { SyntheticMap } from "./projections";
import { DEEP } from "./projections";

type Reply = { status: number; body: unknown };
export function chatFixture(map: SyntheticMap) {
  const conversations = new Map<string, S["ChatConversationRead"]>();
  const revision = () => `synthetic-accepted-${map.version}`;
  const evidence = () => String(map.version).padStart(64, "0");
  const at = "2026-11-09T10:00:00Z";
  return (path: string, method = "GET", body?: Record<string, unknown>): Reply | undefined => {
    const url = new URL(path, "http://synthetic"), p = url.pathname.replace(/^\/api\/managed\//, "").split("/");
    const okay = (body: unknown, status = 200) => ({ status, body });
    if (p[0] === "projects" && p[2] === "chat-context") {
      const kind = url.searchParams.get("kind") as S["ChatElementReference"]["kind"];
      const target = url.searchParams.get("target") ?? "synthetic";
      const reference: S["ChatElementReference"] = { kind, project: DEEP.key,
        ...(kind === "phase" || kind === "task" ? { stable_id: `synthetic-${target}`, revision_id: revision() }
          : { run_id: target, evidence_digest: evidence(), ...(kind === "step" ? { step_key: url.searchParams.get("step_key") } : {}) }) };
      return okay({ reference, label: target + (kind === "step" ? ` / ${reference.step_key}` : ""), reason: null });
    }
    if (p[0] === "projects" && p[2] === "conversations") {
      if (method === "GET") {
        const summaries = Array.from(conversations.values(), (value): S["ChatConversationSummaryRead"] => ({
          id: value.id, title: value.title, phase_id: value.phase?.id ?? null, phase_code: value.phase?.code ?? null,
          task_run_id: value.task_run_id, turns: value.turns.length, version: value.version,
          created_at: value.created_at, updated_at: value.updated_at,
        }));
        return okay(summaries);
      }
      if (method !== "POST") return undefined;
      const id = `synthetic-chat-${conversations.size + 1}`;
      const value: S["ChatConversationRead"] = { id, project_id: DEEP.registered, root: "/synthetic/atlas",
        title: String(body?.title ?? "Synthetic conversation"), phase: null, task_run_id: null, actor: {},
        version: 0, created_at: at, updated_at: at, turns: [], proposals: [], actions: ["message"] };
      conversations.set(id, value); return okay(value, 201);
    }
    if (p[0] === "projects" && p[2] === "phases") return okay([]);
    if (p[0] === "projects" && p[2] === "runs") return okay({ items: [], offset: 0, next_offset: null });
    if (p[0] === "conversations") {
      const value = conversations.get(p[1]);
      if (!value) return okay({ detail: { code: "not_found" } }, 404);
      if (method === "GET") return okay(value);
      if (p[2] !== "messages" || method !== "POST") return undefined;
      const reference = body?.element as S["ChatElementReference"] | undefined;
      if (reference && (reference.revision_id ? reference.revision_id !== revision() : reference.evidence_digest !== evidence()))
        return okay({ detail: { code: "element_stale", diagnostic: "Synthetic context changed; refresh the tag." } }, 409);
      const number = value.turns.length + 1, run = `synthetic-chat-run-${number}`;
      value.turns.push({ id: `synthetic-turn-${number}`, number, status: "ANSWERED", run_id: run,
        run_status: "COMPLETED", message: String(body?.text ?? ""), documents: [], run_ids: [], phase_code: null,
        head: "a".repeat(40), command: null, previous_turns: number - 1, context_sha256: "b".repeat(64),
        request_sha256: "c".repeat(64), actor: {}, created_at: at, finished_at: at,
        element: reference ? { reference, label: reference.stable_id ?? reference.run_id ?? null, reason: null } : null,
        result: { status: "ANSWERED", result: { answer: "Synthetic answer. No provider ran; this fixture simulates the conversation only.", references: [], proposals: [] } } });
      value.version++; return okay({ id: number, run_id: run, status: "COMPLETED" }, 202);
    }
    if (p[0] === "runs" && p[1]?.startsWith("synthetic-chat-run-")) return p[2] === "events"
      ? okay({ items: [], cursor: 0 }) : okay({ id: p[1], project_id: DEEP.registered, phase_id: "CHAT", task_id: "CHAT", version: 0 });
    return undefined;
  };
}
