// Live activity of a run (OT002): its confirmed events read as what the agent is doing now. Pure functions without
// React, also used by the Node tests. Only what the adapters recorded is shown (the agent's own JSONL records,
// lifecycle and validation events); nothing is inferred beyond them, and the full evidence stays on the run page.

export type RunEvent = { sequence: number; kind: string; recorded_at: string; payload: Record<string, unknown> };

export type ActivityKind = "lifecycle" | "message" | "thinking" | "command" | "read" | "edit" | "search" | "web" | "tool"
  | "plan" | "check" | "result" | "warning";
export type ActivityTone = "active" | "ok" | "danger" | "attention" | "neutral";
/** One line of the feed. `label` is the suffix of an `activity.*` catalog key; `detail` is literal agent text. */
export type ActivityItem = {
  key: string; sequence: number; at: string; kind: ActivityKind; label: string;
  params: Record<string, string | number>; detail?: string; tone: ActivityTone; running: boolean; role?: string;
};
/** What is being streamed right now, before its record is complete. */
export type ActivityNow = { kind: "writing" | "thinking" | "tool"; tool?: string; text: string; role?: string } | null;
export type Activity = { items: ActivityItem[]; now: ActivityNow };

type Data = Record<string, unknown>;
const object = (value: unknown): Data | undefined => value && typeof value === "object" && !Array.isArray(value) ? value as Data : undefined;
const text = (value: unknown) => typeof value === "string" ? value : undefined;
const list = (value: unknown) => Array.isArray(value) ? value : [];

/** Agent-stream noise that never becomes a line: raw byte notes and partial deltas other than the live block. */
export function relevant(event: RunEvent): boolean {
  if (event.kind === "stream_bytes" || event.kind === "process_intent" || event.kind === "checkpoint") return false;
  if (event.kind !== "agent_event") return true;
  const original = object(event.payload.original);
  if (!original) return true;
  if (original.type === "rate_limit_event") return false;
  if (original.type !== "stream_event") return true;
  const inner = object(original.event);
  return ["content_block_start", "content_block_delta", "content_block_stop", "message_stop"].includes(String(inner?.type));
}

/** Claude tool names by what they do; any other tool keeps its own name. */
const TOOLS: Record<string, [ActivityKind, string, (input: Data) => string | undefined]> = {
  Bash: ["command", "command", input => text(input.command) ?? text(input.description)],
  Read: ["read", "read", input => text(input.file_path)],
  Write: ["edit", "write", input => text(input.file_path)],
  Edit: ["edit", "edit", input => text(input.file_path)],
  MultiEdit: ["edit", "edit", input => text(input.file_path)],
  NotebookEdit: ["edit", "edit", input => text(input.notebook_path)],
  Grep: ["search", "search", input => [text(input.pattern), text(input.path)].filter(Boolean).join("  ") || undefined],
  Glob: ["search", "find", input => text(input.pattern)],
  LS: ["read", "list", input => text(input.path)],
  WebFetch: ["web", "fetch", input => text(input.url)],
  WebSearch: ["web", "web_search", input => text(input.query)],
  TodoWrite: ["plan", "plan", input => todos(list(input.todos).map(item => ({ text: text(object(item)?.content), done: object(item)?.status === "completed",
    active: object(item)?.status === "in_progress" })))],
  Task: ["tool", "subagent", input => text(input.description)],
  Agent: ["tool", "subagent", input => text(input.description)],
};

function todos(items: { text?: string; done: boolean; active?: boolean }[]) {
  if (!items.length) return undefined;
  const current = items.find(item => item.active) ?? items.find(item => !item.done);
  return `${items.filter(item => item.done).length}/${items.length}${current?.text ? ` · ${current.text}` : ""}`;
}

const seconds = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? Math.round(value * 10) / 10 : undefined;

/**
 * Folds the events (ascending sequence, any window of the run) into feed lines. A record repeated by the stream
 * (Claude repeats a message while it grows; Codex reports an item when it starts and completes) updates its line.
 */
export function activity(events: RunEvent[]): Activity {
  const items: ActivityItem[] = [];
  const index = new Map<string, number>();
  const roles = new Map<string, string>();
  let now: ActivityNow = null;
  let role: string | undefined;

  function put(item: Omit<ActivityItem, "role" | "params"> & { params?: ActivityItem["params"]; role?: string }) {
    const full: ActivityItem = { params: {}, role, ...item };
    const at = index.get(full.key);
    if (at === undefined) { index.set(full.key, items.length); items.push(full); return; }
    const previous = items[at];
    // The first sequence and time stay: a line is where the step started.
    items[at] = { ...previous, ...full, sequence: previous.sequence, at: previous.at, detail: full.detail ?? previous.detail };
  }
  function update(key: string, change: Partial<ActivityItem>) {
    const at = index.get(key);
    if (at !== undefined) items[at] = { ...items[at], ...change };
  }

  for (const event of events) {
    const p = event.payload;
    const base = { sequence: event.sequence, at: event.recorded_at };
    const attempt = text(p.attempt_id);
    role = attempt ? roles.get(attempt) ?? role : role;
    switch (event.kind) {
      case "job_queued":
        put({ ...base, key: `e${event.sequence}`, kind: "lifecycle", label: "queued", params: { action: String(p.action ?? "") }, tone: "neutral", running: false });
        break;
      case "job_claimed":
        put({ ...base, key: `e${event.sequence}`, kind: "lifecycle", label: "claimed", tone: "active", running: false });
        break;
      case "attempt_started":
        if (attempt && typeof p.role === "string") roles.set(attempt, p.role);
        role = typeof p.role === "string" ? p.role : role;
        put({ ...base, key: `e${event.sequence}`, kind: "lifecycle", label: "attempt", params: { number: Number(p.number ?? 0) }, tone: "active", running: false, role });
        break;
      case "process_spawned":
        put({ ...base, key: `process:${attempt ?? event.sequence}`, kind: "lifecycle", label: "process", tone: "active", running: true });
        break;
      case "process_finished": {
        const status = String(p.status ?? "");
        update(`process:${attempt ?? ""}`, { running: false });
        put({ ...base, key: `e${event.sequence}`, kind: "lifecycle", label: status === "complete" ? "process_done" : "process_failed",
          params: { status, seconds: seconds(p.wall_duration_seconds) ?? 0 }, tone: status === "complete" ? "ok" : status === "cancelled" ? "neutral" : "danger", running: false });
        now = null;
        break;
      }
      case "command_started": {
        const argv = list(object(p.command)?.argv).map(String);
        put({ ...base, key: `command:${String(p.command_id)}`, kind: "check", label: "check", detail: argv.join(" ") || undefined, tone: "active", running: true });
        break;
      }
      case "command_finished": {
        const result = object(p.result) ?? {};
        const passed = result.exit_code === 0 && !result.timed_out && !result.error;
        update(`command:${String(p.command_id)}`, { running: false, tone: passed ? "ok" : "danger", label: passed ? "check_passed" : result.timed_out ? "check_timeout" : "check_failed",
          params: { code: result.exit_code === null || result.exit_code === undefined ? "—" : String(result.exit_code), seconds: seconds(result.duration_seconds) ?? 0 } });
        break;
      }
      case "job_finished":
        put({ ...base, key: `e${event.sequence}`, kind: "lifecycle", label: "job_finished", params: { status: String(p.history_status ?? "") }, tone: "ok", running: false });
        now = null;
        break;
      case "job_refused":
        put({ ...base, key: `e${event.sequence}`, kind: "warning", label: "refused", detail: text(p.diagnostic), tone: "danger", running: false });
        break;
      case "recovery_required":
        put({ ...base, key: `e${event.sequence}`, kind: "warning", label: "recovery", detail: text(p.reason), tone: "attention", running: false });
        now = null;
        break;
      case "commit_recorded":
        put({ ...base, key: `e${event.sequence}`, kind: "result", label: "commit", detail: text(p.commit)?.slice(0, 12), tone: "ok", running: false });
        break;
      case "permission_requested":
        put({ ...base, key: `e${event.sequence}`, kind: "warning", label: "permission", tone: "attention", running: false });
        break;
      case "stream_diagnostic":
        put({ ...base, key: `e${event.sequence}`, kind: "warning", label: "stream_warning", params: { code: String(p.code ?? "") }, tone: "attention", running: false });
        break;
      case "agent_event":
        now = agent(event, attempt ?? "", now);
        break;
    }
  }

  function agent(event: RunEvent, attempt: string, live: ActivityNow): ActivityNow {
    const base = { sequence: event.sequence, at: event.recorded_at };
    const original = object(event.payload.original);
    if (!original) {
      const kind = text(event.payload.type) ?? "";
      if (kind === "assistant" || kind === "item.completed") {
        const reference = object(event.payload.original_reference);
        put({ ...base, key: `e${event.sequence}`, kind: "message", label: "large_record", params: { size: Math.round(Number(reference?.size ?? 0) / 1024) }, tone: "neutral", running: false });
      }
      return live;
    }
    const type = String(original.type ?? "");
    // --- Claude Code (stream-json) ---
    if (type === "system" && original.subtype === "init") {
      put({ ...base, key: `session:${attempt}`, kind: "lifecycle", label: "session", params: { model: text(original.model) ?? "—" }, tone: "neutral", running: false });
      return live;
    }
    if (type === "stream_event") {
      const inner = object(original.event) ?? {};
      if (inner.type === "content_block_start") {
        const block = object(inner.content_block) ?? {};
        if (block.type === "tool_use") {
          const name = text(block.name) ?? "tool";
          const [kind, label] = TOOLS[name] ?? ["tool", "tool"];
          put({ ...base, key: `${attempt}:${text(block.id) ?? event.sequence}`, kind, label, params: { tool: name }, tone: "active", running: true });
          return { kind: "tool", tool: name, text: "", role };
        }
        return { kind: block.type === "thinking" ? "thinking" : "writing", text: "", role };
      }
      if (inner.type === "content_block_delta") {
        const delta = object(inner.delta) ?? {};
        const piece = text(delta.text) ?? text(delta.thinking);
        if (piece === undefined) return live;
        const kind = delta.type === "thinking_delta" ? "thinking" : "writing";
        const previous = live && live.kind === kind ? live.text : "";
        return { kind, text: (previous + piece).slice(-600), role };
      }
      return null;
    }
    if (type === "assistant") {
      const message = object(original.message) ?? {};
      const id = text(message.id) ?? `e${event.sequence}`;
      list(message.content).forEach((value, position) => {
        const block = object(value) ?? {};
        if (block.type === "text" && text(block.text)?.trim()) {
          put({ ...base, key: `${attempt}:${id}:${position}`, kind: "message", label: "message", detail: text(block.text), tone: "neutral", running: false });
        } else if (block.type === "thinking") {
          put({ ...base, key: `${attempt}:${id}:${position}`, kind: "thinking", label: "thinking", detail: text(block.thinking)?.trim() || undefined, tone: "neutral", running: false });
        } else if (block.type === "tool_use") {
          const name = text(block.name) ?? "tool";
          const [kind, label, describe] = TOOLS[name] ?? ["tool", "tool", () => undefined];
          const input = object(block.input) ?? {};
          const key = `${attempt}:${text(block.id) ?? `${id}:${position}`}`;
          const done = index.has(key) && !items[index.get(key)!].running;
          put({ ...base, key, kind, label, params: { tool: name }, detail: describe(input), tone: done ? items[index.get(key)!].tone : "active", running: !done });
        }
      });
      return live;
    }
    if (type === "user") {
      const message = object(original.message) ?? {};
      for (const value of list(message.content)) {
        const block = object(value) ?? {};
        if (block.type === "tool_result" && text(block.tool_use_id)) update(`${attempt}:${text(block.tool_use_id)}`, { running: false, tone: block.is_error ? "danger" : "ok" });
      }
      return live;
    }
    if (type === "result") {
      const failed = original.is_error === true || original.subtype !== "success";
      put({ ...base, key: `result:${attempt}`, kind: "result", label: failed ? "agent_failed" : "agent_done",
        params: { turns: Number(original.num_turns ?? 0), seconds: seconds(Number(original.duration_ms ?? 0) / 1000) ?? 0, subtype: String(original.subtype ?? "") }, tone: failed ? "danger" : "ok", running: false });
      return null;
    }
    // --- Codex (exec --json) ---
    if (type === "thread.started") {
      put({ ...base, key: `session:${attempt}`, kind: "lifecycle", label: "thread", tone: "neutral", running: false });
      return live;
    }
    if (type.startsWith("item.")) {
      const item = object(original.item) ?? {};
      const key = `${attempt}:${text(item.id) ?? event.sequence}`;
      const running = type !== "item.completed" && item.status !== "completed" && item.status !== "failed";
      switch (item.type) {
        case "command_execution": {
          const code = item.exit_code;
          const failed = item.status === "failed" || (typeof code === "number" && code !== 0);
          put({ ...base, key, kind: "command", label: "command", detail: text(item.command), tone: running ? "active" : failed ? "danger" : "ok", running });
          break;
        }
        case "file_change": {
          const changes = list(item.changes).map(change => object(change) ?? {});
          put({ ...base, key, kind: "edit", label: "files", params: { count: changes.length }, detail: changes.map(change => text(change.path)).filter(Boolean).join("\n") || undefined,
            tone: running ? "active" : item.status === "failed" ? "danger" : "ok", running });
          break;
        }
        case "agent_message":
          if (text(item.text)?.trim()) put({ ...base, key, kind: "message", label: "message", detail: text(item.text), tone: "neutral", running: false });
          break;
        case "reasoning":
          put({ ...base, key, kind: "thinking", label: "thinking", detail: text(item.text)?.trim() || undefined, tone: "neutral", running: false });
          break;
        case "mcp_tool_call":
          put({ ...base, key, kind: "tool", label: "tool", params: { tool: [text(item.server), text(item.tool)].filter(Boolean).join(".") || "mcp" }, tone: running ? "active" : item.status === "failed" ? "danger" : "ok", running });
          break;
        case "web_search":
          put({ ...base, key, kind: "web", label: "web_search", detail: text(item.query), tone: running ? "active" : "ok", running });
          break;
        case "todo_list":
          put({ ...base, key, kind: "plan", label: "plan", detail: todos(list(item.items).map(entry => ({ text: text(object(entry)?.text), done: object(entry)?.completed === true }))), tone: "neutral", running: false });
          break;
        case "error":
          put({ ...base, key, kind: "warning", label: "agent_error", detail: text(item.message), tone: "danger", running: false });
          break;
      }
      return running && item.type === "command_execution" ? { kind: "tool", tool: "shell", text: text(item.command) ?? "", role } : live;
    }
    if (type === "turn.completed") {
      put({ ...base, key: `result:${attempt}`, kind: "result", label: "agent_done", params: { turns: 1, seconds: 0, subtype: "" }, tone: "ok", running: false });
      return null;
    }
    if (type === "turn.failed" || type === "error") {
      put({ ...base, key: type === "error" ? `e${event.sequence}` : `result:${attempt}`, kind: type === "error" ? "warning" : "result", label: "agent_error",
        detail: text(object(original.error)?.message) ?? text(original.message), tone: "danger", running: false });
      return null;
    }
    return live;
  }

  return { items, now };
}

/** Lines worth showing before the cursor reaches the present: enough context without the whole history. */
export function meaningful(events: RunEvent[]) {
  return activity(events).items.length;
}

/** Statuses in which a run still advances by itself (the feed polls fast only then). */
const LIVE = new Set(["QUEUED", "ACTIVE", "PLANNING", "PREPARING", "EXECUTING", "REVIEWING", "VALIDATING", "COMMITTING",
  "ANSWERING", "DISCOVERING", "CHECKING", "INTENT"]);
export const isLive = (status: string | undefined) => !!status && LIVE.has(status);

/** Keeps the newest relevant events in sequence order, without duplicates, bounded for long runs. */
export function merge(previous: RunEvent[], incoming: RunEvent[], limit = 1500): RunEvent[] {
  const seen = new Set(previous.map(event => event.sequence));
  const merged = [...previous, ...incoming.filter(event => relevant(event) && !seen.has(event.sequence))].sort((a, b) => a.sequence - b.sequence);
  return merged.length > limit ? merged.slice(merged.length - limit) : merged;
}
