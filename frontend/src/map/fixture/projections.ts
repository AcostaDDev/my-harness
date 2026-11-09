// Synthetic T020 projections (P002-T022): responses shaped exactly as `GET /api/managed/map/…` returns them (typed
// by the generated client), plus the T017 inbox reads the map's requests panel makes. Never product data: no runs,
// credentials or private content. One deep path (project `atlas` → phase `P002` → task `P002-T005` → its latest run)
// with leaf siblings (T018 §12): every status class each level can project, absent telemetry, permissions, a judge,
// a chat invocation running beside the task lane (listed by its run's steps read; optionally a task reviewer on R at
// the same time), unattributed requests, truncated request lists answered by the element request list, and a task
// whose first run can be started.
// Shared by the Node tests and the development fixture page (a fetch shim; D312), and versioned so that refresh can
// be exercised.
import type { S } from "../../managed-api";
import { tracePage, fixtureDocuments, originalFixture } from "./trace.ts";

type Status = S["MapStatus"];
type Counter = S["MapCounter"];
type Circle = S["MapCircleState"];
type Bubbles = S["MapBubbles"];
type BubbleItem = S["MapBubbleItem"];
type Active = S["MapActiveInvocation"];

export const PROJECTION_SCENARIOS = ["review", "budget"] as const;
export type ProjectionScenario = typeof PROJECTION_SCENARIOS[number];

/** Rows per level; `budget` is T018 §12 / D309 (25 projects, 40 phases, 80 tasks, 30 runs, 40 steps, 300 open items). */
export const PROJECTION_SIZES: Record<ProjectionScenario, { projects: number; phases: number; tasks: number; runs: number; steps: number; inbox: number }> = {
  review: { projects: 6, phases: 8, tasks: 12, runs: 4, steps: 12, inbox: 4 },
  budget: { projects: 25, phases: 40, tasks: 80, runs: 30, steps: 40, inbox: 300 },
};

export const DEEP = { key: "kp-atlas", registered: "atlas", name: "atlas", phase: "P002", task: "P002-T005" } as const;
export const MAX_LIST = 20;
const T0 = Date.UTC(2026, 10, 6, 9, 0, 0);
const at = (minutes: number) => new Date(T0 + minutes * 60000).toISOString();
const status = (code: string | null, cls: Status["class"], extra: Record<string, unknown> = {}): Status => ({ code, class: cls, ...extra });
const counter = (value: unknown, source: Counter["source"], extra: Record<string, unknown> = {}): Counter =>
  value === null || value === undefined ? { value: null, source: "absent", reason: "not_observed", ...extra } : { value, source, reason: null, ...extra };
const pad = (n: number, width = 3) => String(n).padStart(width, "0");

function bubbles(items: BubbleItem[], identities: boolean): Bubbles {
  const view: Bubbles = { total: items.length, source: "derived", by_kind: {}, by_circle: {}, unattributed: 0 };
  for (const item of items) {
    view.by_kind[item.kind] = (view.by_kind[item.kind] ?? 0) + 1;
    view.by_circle[item.circle] = (view.by_circle[item.circle] ?? 0) + 1;
    view.unattributed += item.attributed ? 0 : 1;
  }
  if (identities) { view.items = items.slice(0, MAX_LIST); view.items_truncated = items.length > MAX_LIST; }
  return view;
}

function circles(opts: { judge?: "judge_profile" | "judge_history"; active?: Active[]; items?: BubbleItem[]; harness?: boolean; target?: (role: string) => string | undefined }): Circle[] {
  const active = opts.active ?? [], items = opts.items ?? [];
  const roles = ["R", "E", ...(opts.judge ? ["J"] : []), "H"] as const;
  return roles.map(name => {
    const mine = active.filter(item => item.circle === name);
    const marks = items.filter(item => item.circle === name);
    const target = name === "H" ? undefined : opts.target?.(name);
    return {
      circle: name, shown: name === "J" ? opts.judge! : "always",
      active: name === "H" ? !!opts.harness : mine.length > 0, active_invocations: name === "H" ? 0 : mine.length,
      chat: mine.some(item => item.chat),
      harness: name === "H" && opts.harness ? [{ reason: "stage", run_id: "run-atlas-latest", phase: DEEP.phase, task: DEEP.task, stage: "validation", status: "VALIDATING" }] : [],
      bubbles: marks.length, waiting: marks.length > 0,
      latest_invocation: target ? { invocation_id: target, role: name === "R" ? "reviewer" : name === "E" ? "executor" : "judge", lane: "managed_attempt", started_at: at(30) } : null,
      inert: !target && mine.length === 0,
    } as Circle;
  });
}

const REVIEW_PROJECT_CLASSES: Status["class"][] = ["progress", "failed", "waiting", "done", "pending"];
const PHASE_STATES: [string | null, Status["class"], string][] = [
  ["CLOSED", "done", "instance"], ["READY_TO_CLOSE", "waiting", "instance"], ["BLOCKED", "failed", "instance"],
  ["planned", "pending", "roadmap"], ["ABANDONED", "inactive", "instance"], [null, "unknown", "runs"],
];
const TASK_STATES: [string | null, Status["class"]][] = [
  ["COMMITTED", "done"], ["ACCEPTANCE_READY", "waiting"], ["REVISION_LIMIT", "failed"], [null, "pending"], ["STOPPED", "inactive"],
  ["replaced", "inactive"], ["MYSTERY", "unknown"],
];
const TITLES = ["Migrate the index of runs", "Revisar contratos de la API", "Añadir reseñas con ¿preguntas? y ¡avisos!",
  "Página de inicio «mapa» — borrador…", "Fix flaky retry on lease renewal", "Configurar el juez por proyecto",
  "Document the archive restore path in detail with every edge case covered", "Validar códigos ñandú y pingüino"];

export type SyntheticMap = ReturnType<typeof syntheticMap>;

/**
 * A deterministic synthetic map. `version` advances the tokens (see `bump`), as a real writer would; cursors carry
 * the version they were issued for and become `cursor_stale` once it changed.
 */
export function syntheticMap(scenario: ProjectionScenario = "review", options: { archive?: boolean; reviewer?: boolean; legacy?: boolean } = {}) {
  const size = PROJECTION_SIZES[scenario];
  const archive = !!options.archive;
  const state = { version: 1, finished: false, chatEnded: false, started: new Set<string>() };
  const deepRun = "run-atlas-latest";
  const executorRunning = "inv-atlas-executor-2";
  const executorAttempt = "att-atlas-6";
  const reviewerRunning = "inv-atlas-reviewer-3";
  const chatInvocation = "inv-atlas-chat-1";
  const head = (key: string = DEEP.key, name: string = DEEP.name) => ({ key, name, knowledge_project_id: options.legacy ? null : key, registered_project_id: archive ? null : key === DEEP.key ? DEEP.registered : null });

  // Requests: permissions raised by the running executor and task questions on the deep task; phase questions
  // without a run (unattributed, on H) on the deep phase. The budget scenario carries 300 open items.
  const taskItems: BubbleItem[] = [], phaseItems: BubbleItem[] = [];
  const total = size.inbox;
  for (let i = 0; i < total; i++) {
    if (i % 2 === 0) taskItems.push(i % 4 === 0
      ? { id: `run-permission:${pad(i)}`, kind: "permission", topic: "run_permission", circle: "E", attributed: true }
      : { id: `gap:${pad(i)}`, kind: "question", topic: "task_gap", circle: "R", attributed: true });
    else phaseItems.push({ id: `phase-question:${pad(i)}`, kind: "question", topic: "phase_question", circle: "H", attributed: false });
  }
  const allItems = [...taskItems, ...phaseItems];
  // T020's scope of each item (what the request list filters on): task items on the deep run, the permissions
  // raised by its running executor attempt; phase questions on the deep phase only.
  const scopeOf = (item: BubbleItem) => item.topic === "phase_question" ? { phase: DEEP.phase, task: null, run_id: null, attempt_id: null }
    : { phase: DEEP.phase, task: DEEP.task, run_id: deepRun, attempt_id: item.topic === "run_permission" ? executorAttempt : null };
  const active = (): Active[] => state.finished ? [] : [
    { source_kind: "managed_attempt", invocation_id: executorRunning, attempt_id: executorAttempt, run_id: deepRun, number: 6, role: "executor", circle: "E",
      agent: "executor", lane: "task", chat: false, scope: { phase: DEEP.phase, task: DEEP.task, run_id: deepRun }, process: "RUNNING", started_at: at(50) },
    ...(options.reviewer ? [{ source_kind: "managed_attempt", invocation_id: reviewerRunning, attempt_id: "att-atlas-7", run_id: deepRun, number: 7, role: "reviewer", circle: "R",
      agent: "reviewer", lane: "task", chat: false, scope: { phase: DEEP.phase, task: DEEP.task, run_id: deepRun }, process: "RUNNING", started_at: at(51) } as Active] : []),
    ...(state.chatEnded ? [] : [{ source_kind: "managed_attempt", invocation_id: chatInvocation, attempt_id: "att-chat-1", run_id: "run-chat-1", number: 1, role: "chat", circle: "R",
      agent: "reviewer", lane: "chat", chat: true, scope: { phase: DEEP.phase, task: DEEP.task, run_id: deepRun }, process: "RUNNING", started_at: at(52) } as Active]),
  ];
  const chatsOf = (run: string) => active().filter(item => item.chat && item.scope.run_id === run).map(item => ({ ...item, project_id: DEEP.key }));
  const target = (role: string) => role === "E" ? executorRunning : role === "R" ? chatInvocation : role === "J" ? "inv-atlas-judge-1" : undefined;
  const version = (scope: string) => `v1.${scope.length.toString(16)}.${state.version}`;
  const scopes = {
    projects: "s1.fixture.projects",
    phases: (p: string) => `s1.fixture.phases.${p}`,
    tasks: (p: string, phase: string) => `s1.fixture.tasks.${p}.${phase}`,
    runs: (p: string, phase: string, task: string) => `s1.fixture.runs.${p}.${phase}.${task}`,
    steps: (p: string, run: string) => `s1.fixture.steps.${p}.${run}`,
  };

  function card(i: number): S["MapProjectCard"] {
    const deep = i === 0;
    const key = deep ? DEEP.key : `kp-p${pad(i + 1, 2)}`;
    const cls: Status["class"] = deep ? (state.finished ? "waiting" : "progress") : REVIEW_PROJECT_CLASSES[i % REVIEW_PROJECT_CLASSES.length];
    const mine = deep ? active() : [];
    const items = deep ? allItems : [];
    const closed = deep ? 1 : i % 3, phases = deep ? size.phases : 3;
    return {
      id: key, name: deep ? DEEP.name : `project-${pad(i + 1, 2)}`, name_source: deep ? "registered" : "root_basename",
      knowledge_project_id: key, registered_project_id: archive ? null : deep ? DEEP.registered : i % 2 ? `p${pad(i + 1, 2)}` : null,
      status: status(null, cls, { source: "derived" }),
      mode: deep ? { kind: "autonomous", autonomous_run: { id: "auto-atlas-1", status: status("RUNNING", "progress"), reason: null, bounds: { max_tasks: 12, max_phases: 2 }, updated_at: at(55) } }
        : { kind: "manual", autonomous_run: i === 2 ? { id: `auto-${key}`, status: status("FAILED", "failed"), reason: "limit_check_failed", bounds: null, updated_at: at(20) } : null },
      active_phase: deep ? { code: DEEP.phase, title: "Work map", status: status("ACTIVE", "progress") } : cls === "done" ? null : { code: "P001", title: TITLES[i % TITLES.length], status: status("ACTIVE", "progress") },
      phases: i === 4 ? counter(null, "derived", { reason: "no_phases", total: null, meaning: "phases closed / total" }) : counter(closed, "derived", { total: phases, meaning: "phases closed / total" }),
      circles: circles({ judge: deep ? "judge_profile" : undefined, active: mine, items, harness: deep && !state.finished, target: deep ? target : () => i % 2 ? `inv-${key}-r` : undefined }),
      active_invocations: mine,
      last_activity: i === 4 ? counter(null, "derived", { reason: "no_activity" }) : counter(at(55 - i), "derived"),
      errors: cls === "failed" ? [{ kind: "autonomous_run", id: `auto-${key}`, status: status("FAILED", "failed") }] : [],
      bubbles: bubbles(items, false),
      configuration: archive || !(deep || i % 2) ? null : { reviewer: { provider: "codex", model: "gpt-synthetic", effort: "medium" }, planner: { model: "gpt-synthetic", effort: "low" },
        executor: { provider: "claude", selection_mode: "fixed", models: ["claude-synthetic"], efforts: ["high"], effort_vocabulary: ["low", "high"] },
        ...(deep ? { judge: { provider: "claude", model: "claude-synthetic-judge", effort: "low" } } : {}), planning_mode: "reviewer" },
      configuration_source: archive || !(deep || i % 2) ? "absent" : "supplied",
    };
  }

  function phaseNode(p: string, i: number): S["MapPhaseNode"] {
    const code = `P${pad(i + 1)}`;
    const deep = p === DEEP.key && code === DEEP.phase;
    const [raw, cls, origin] = deep ? ["ACTIVE", "progress", "instance"] as const : i === 0 ? ["CLOSED", "done", "instance"] as const : PHASE_STATES[(i - 1) % PHASE_STATES.length];
    const instance = origin === "instance" ? { id: `ph-${p}-${code}`, status: raw!, version: 3 + i, created_at: at(i), updated_at: at(i + 5) } : null;
    const mine = deep ? active() : [];
    const items = deep ? phaseItems.concat(taskItems) : [];
    const slot = (kind: string, code2: string, cls2: Status["class"], actors: S["MapSlotActor"][]): S["MapSlot"] => ({
      operation_id: `op-${code}-${kind}`, run_id: `run-${code}-${kind}`, status: status(code2, cls2), created_at: at(i * 2), finished_at: cls2 === "progress" ? null : at(i * 2 + 1), history: kind === "check" ? 2 : 1, actors });
    const slots: Record<string, S["MapSlot"] | null> = instance ? {
      plan: slot("plan", "ADOPTED", "done", [{ circle: "R", status: status("COMPLETE", "done"), invocation_id: `inv-${code}-plan` }]),
      check: i === 0 || cls === "waiting" ? slot("check", "READY", "done", [{ circle: "R", status: status("COMPLETE", "done"), invocation_id: `inv-${code}-check` }, { circle: "J", status: status("VALIDATED", "done"), invocation_id: `inv-${code}-judge` }, { circle: "H", status: null, invocation_id: null }])
        : cls === "failed" ? slot("check", "NOT_READY", "failed", [{ circle: "R", status: status("COMPLETE", "done"), invocation_id: `inv-${code}-check` }]) : null,
      close: i === 0 ? slot("close", "CLOSED", "done", [{ circle: "H", status: null, invocation_id: null }]) : null,
    } : { plan: null, check: null, close: null };
    const committed = deep ? Math.floor(size.tasks / 3) : cls === "done" ? 4 : 1;
    return {
      code, title: origin === "runs" ? null : deep ? "Work map" : TITLES[i % TITLES.length], origin: origin as S["MapPhaseNode"]["origin"],
      identity: origin === "runs" ? null : { item_id: `item-${code}`, status: status(origin === "roadmap" ? "planned" : "accepted", origin === "roadmap" ? "pending" : "unknown") },
      instance, status: origin === "runs" ? status(null, "unknown", { reason: "no_phase_record" }) : status(raw, cls),
      objective: origin === "runs" ? null : `Synthetic objective ${code}`, tag: cls === "done" ? `v0.${i}.0` : null,
      criteria: counter(origin === "runs" ? null : 3, "derived", { reason: "no_criteria", covered: instance ? 2 : null }),
      slots, ready: cls === "waiting", last_check: slots.check,
      tasks: origin === "runs" ? counter(null, "derived", { reason: "no_tasks", total: null, meaning: "tasks committed / total" }) : counter(committed, "derived", { total: deep ? size.tasks : 4, meaning: "tasks committed / total" }),
      active: deep, circles: circles({ judge: deep ? "judge_profile" : cls === "done" ? "judge_history" : undefined, active: mine, items, harness: deep && !state.finished, target: deep ? target : () => instance ? `inv-${code}-plan` : undefined }),
      active_invocations: mine, errors: cls === "failed" ? [{ kind: "phase", id: code, status: status(raw, cls) }] : [],
      bubbles: bubbles(items, true),
    };
  }

  function taskNode(phase: string, i: number): S["MapTaskNode"] {
    const code = `${phase}-T${pad(i + 1)}`;
    const deep = phase === DEEP.phase && code === DEEP.task;
    const [raw, cls] = deep ? ["EXECUTING", "progress"] as const : TASK_STATES[i % TASK_STATES.length];
    const replaced = raw === "replaced";
    const hasRun = raw !== null && !(raw === "replaced");
    const mine = deep ? active() : [];
    const items = deep ? taskItems : [];
    const latest: S["MapLatestRun"] | null = deep ? {
      run_id: deepRun, status: status("EXECUTING", "progress"), stage: "execution", revisions: 1, created_at: at(40), updated_at: at(55),
      attempts: counter(2, "derived", { revision_limit: 3, revision_limit_source: "supplied", meaning: "executor attempts of the latest run / revision limit" }),
      cycles: 1, acceptance: { state: "absent", eligible: null, reasons: [], source: "absent", reason: "not_evaluated" }, commit: null,
    } : hasRun ? {
      run_id: `run-${code}`, status: status(raw, cls), stage: cls === "done" ? "commit" : "review", revisions: i % 3, created_at: at(i), updated_at: at(i + 3),
      attempts: i % 5 === 3 ? counter(null, "derived", { reason: "no_projection", revision_limit: 3, revision_limit_source: "supplied" }) : counter(1 + (i % 3), "derived", { revision_limit: 3, revision_limit_source: "supplied" }),
      cycles: i % 5 === 3 ? null : 1 + (i % 2),
      acceptance: cls === "done" ? { state: "eligible", eligible: true, reasons: [], source: "derived", reason: null }
        : cls === "failed" ? { state: "rejected", eligible: false, reasons: ["validation_failed"], source: "derived", reason: null } : { state: "absent", eligible: null, reasons: [], source: "absent", reason: "not_evaluated" },
      commit: cls === "done" ? { status: status("COMMITTED", "done"), commit: "a1b2c3d4e5f6a7b8", finished_at: at(i + 4) } : null,
    } : null;
    return {
      code, title: TITLES[i % TITLES.length], in_plan: i % 9 !== 8, identity: { item_id: `item-${code}`, status: status(replaced ? "replaced" : "accepted", replaced ? "inactive" : "unknown") },
      problem: i % 6 === 5 ? { value: null, source: "absent", reason: "no_accepted_identity", truncated: false } : { value: `Synthetic problem of ${code}.`, source: "supplied", reason: null, truncated: false },
      expected_result: { value: `Synthetic expected result of ${code}.`, source: "supplied", reason: null, truncated: i === 1 },
      status: replaced ? status("replaced", "inactive", { run_status: "REVISION_LIMIT" }) : raw === null ? status(null, "pending", { reason: "planned_without_run" }) : status(raw, cls),
      runs: deep ? size.runs : hasRun ? 1 + (i % 2) : 0, latest,
      replaces: replaced ? [] : i % TASK_STATES.length === 6 && i > 0 ? [`${phase}-T${pad(i)}`] : [],
      replaced_by: replaced ? [`${phase}-T${pad(i + 2)}`] : [],
      depends_on: i > 0 && i % 3 !== 0 ? [`${phase}-T${pad(i)}`] : [],
      circles: circles({ judge: deep ? "judge_profile" : i === 0 ? "judge_history" : undefined, active: mine, items, harness: deep && !state.finished, target: deep ? target : () => hasRun ? `inv-${code}-e` : undefined }),
      active_invocations: mine, errors: cls === "failed" && hasRun ? [{ kind: "run", id: `run-${code}`, status: status(raw, cls) }] : [],
      bubbles: bubbles(items, true),
    };
  }

  function stepItems(run: string): S["MapStep"][] {
    if (run !== deepRun) return [invocationStep(run, 1, 1, "executor", "E", status("COMPLETE", "done"), 42000, true)];
    // Full review rounds (executor, its format and validate, reviewer; a judge after the first review), cut to the
    // scenario's size, then the running executor and the commit record (T020's order: attempts, cycles, tail).
    const steps: S["MapStep"][] = [];
    const ordinals: Record<string, number> = {};
    let number = 0;
    const next = (role: string) => { number++; ordinals[role] = (ordinals[role] ?? 0) + 1; return [number, ordinals[role]] as const; };
    const room = size.steps - (state.finished ? 1 : 2);
    for (let round = 1; steps.length < room; round++) {
      const [n, o] = next("executor");
      steps.push(invocationStep(run, n, o, "executor", "E", round === 2 ? status("INVALID", "failed") : round === 3 ? status("CANCELLED", "inactive") : status("COMPLETE", "done"),
        30000 + round * 1000, round % 2 === 1, false, round));
      steps.push({ key: `${pad(n, 6)}.0001`, kind: "harness", stage: "format", circle: "H", status: round === 1 ? status("passed", "done") : status("not_recorded", "inactive"),
        duration_ms: counter(null, "derived", { reason: "not_measured_separately" }), cycle: round - 1, evidence: { formatting_recorded: round === 1 } } as S["MapStep"]);
      steps.push({ key: `${pad(n, 6)}.0002`, kind: "harness", stage: "validate", circle: "H", status: round === 1 ? status("failed", "failed") : status("passed", "done"),
        duration_ms: counter(4200 + round, "derived", { includes: ["format"], timing: "stage_events" }), cycle: round - 1, started_at: at(round * 3), finished_at: at(round * 3 + 1),
        evidence: { commands: [2, round === 1 ? 1 : 2], verdict: round === 1 ? "REVISE" : "ACCEPT" } } as S["MapStep"]);
      const [r, ro] = next("reviewer");
      steps.push(invocationStep(run, r, ro, "reviewer", "R", round === 3 ? status("WEIRD", "unknown") : status("COMPLETE", "done"), round === 3 ? null : 12000 + round, false, false, round));
      if (round === 1) { const [j, jo] = next("judge"); steps.push(invocationStep(run, j, jo, "judge", "J", status("COMPLETE", "done"), 9000, false, false, round)); }
    }
    steps.length = Math.min(steps.length, room);
    if (!state.finished) { const [n, o] = next("executor"); steps.push(invocationStep(run, n, o, "executor", "E", status("RUNNING", "progress", { process: "RUNNING" }), null, false, true, ordinals.executor)); }
    steps.push({ key: `999999.0000`, kind: "harness", stage: "commit", circle: "H", status: state.finished ? status("COMMITTED", "done") : status("INTENT", "progress"),
      duration_ms: counter(state.finished ? 1800 : null, "derived", { reason: "not_finished", timing: "commit_record" }), started_at: at(56), finished_at: state.finished ? at(57) : null,
      evidence: { commit: state.finished ? "f00dfeedcafe1234" : null }, operation_id: "op-commit-1" } as S["MapStep"]);
    return steps;
  }

  function invocationStep(run: string, number: number, ordinal: number, role: string, circle: "R" | "E" | "J", st: Status, duration: number | null, reported: boolean, running = false, round = 1): S["MapStep"] {
    const invocation = running ? executorRunning : role === "judge" ? "inv-atlas-judge-1" : `inv-${run}-${number}`;
    const client = role === "executor" ? "claude" : "codex";
    const settled = !running;
    return {
      key: `${pad(number, 6)}.0000`, kind: "invocation", invocation_id: invocation, attempt_id: running ? executorAttempt : `att-${run}-${number}`, role, circle,
      label: { role, ordinal }, status: st, active: running,
      harness_attempt: counter(number, "supplied"), revision_round: counter(round, "derived", { reason: "no_metrics" }),
      duration_ms: counter(duration, "measured", { reason: "no_capture" }), started_at: at(number * 3), finished_at: settled ? at(number * 3 + 2) : null,
      identity: { agent: role === "judge" ? "judge" : role === "executor" ? "executor" : "reviewer", client, client_version: client === "claude" ? "2.1.304" : "0.163.0", adapter_version: "cli-14",
        requested_model: `${client}-synthetic`, requested_effort: "medium", source: "supplied" },
      reported_model: reported && settled ? counter([`${client}-synthetic-reported`], "reported", { provenance: { reported_models: "reported" } })
        : counter(null, "reported", { reason: client === "codex" ? "not_reported_by_client" : "not_reported", provenance: null }),
      launch: status(settled ? "observed" : "pending", settled ? "done" : "progress"),
      termination: settled ? { class: st.class === "done" ? "completed" : st.class === "inactive" ? "cancelled" : "invalid_stream", source: "measured" } : null,
      observation: settled ? { source: "trace", persisted: true, counters: {
        native_turns: counter(client === "claude" ? 6 + number : 1, client === "claude" ? "reported" : "measured", { coverage: "complete" }),
        tool_calls: { ...counter(3 + number, "measured", { coverage: "complete" }), by_name: { Read: 2, Edit: 1 + number } },
        permission_denials: client === "codex" ? counter(null, "absent", { reason: "not_reported_by_client", coverage: "absent" }) : counter(0, "reported", { coverage: "complete" }),
      }, usage: client === "claude" ? { view: "terminal", source: "reported", coverage: "complete", alternatives: [] } : { view: null, source: "absent", coverage: "absent", reason: "not_reported", alternatives: [] },
      missing: client === "codex" ? [{ signal: "permission_denials", reason: "not_reported_by_client" }, { signal: "reported_model", reason: "not_reported_by_client" }] : [] } : null,
      records: { deliveries: counter(settled ? 2 : 0, "derived"), discovery: counter(settled ? 1 : 0, "derived"), rulings: counter(role === "judge" ? 1 : 0, "derived"), permission_requests: counter(running ? 2 : 0, "derived") },
      steps: running ? { state: "not_settled", reason: null } : number === 1 ? { state: "not_projected", reason: "settled_before_t019" } : { state: "sealed", reason: null },
      bubbles: bubbles(running ? taskItems.filter(item => item.topic === "run_permission") : [], true),
    } as S["MapStep"];
  }

  function paged<T>(items: T[], scope: string, url: URL, cap: number) {
    const limit = Math.min(cap, Number(url.searchParams.get("limit") ?? cap) || cap);
    const cursor = url.searchParams.get("cursor");
    let offset = 0;
    if (cursor) {
      const [, issued, start] = cursor.split(".");
      if (issued !== String(state.version)) return { stale: true as const };
      offset = Number(start);
    }
    const page = items.slice(offset, offset + limit);
    return { stale: false as const, page, next: offset + limit < items.length ? `c1.${state.version}.${offset + limit}` : null, scope };
  }

  const read = { format: "work-map-1" as const, read_only_archive: archive };

  return {
    scopes,
    deepRun,
    /** Advances every version (as a writer would); `finish` also settles the deep run. */
    bump(options: { finish?: boolean } = {}) { state.version++; if (options.finish) state.finished = true; },
    /** The first run of a task without runs (`…-T004`) is created: its run selector's version advances. */
    startRun(task: string) { state.started.add(task); state.version++; },
    /** The chat attached to the deep run settles: it leaves the run's steps read (and activity); versions advance. */
    endChat() { state.chatEnded = true; state.version++; },
    get version() { return state.version; },
    projects(url = new URL("http://x/")): S["MapProjectsRead"] | { stale: true } {
      const scope = scopes.projects;
      const result = paged(Array.from({ length: size.projects }, (_, i) => card(i)), scope, url, 100);
      if (result.stale) return result;
      return { ...read, level: "projects", scope, version: version(scope), items: result.page, next_cursor: result.next };
    },
    phases(project: string, url = new URL("http://x/")): S["MapPhasesRead"] | { stale: true } | undefined {
      const key = project === DEEP.registered ? DEEP.key : project;
      const index = key === DEEP.key ? 0 : Number(key.replace("kp-p", "")) - 1;
      if (!(index >= 0 && index < size.projects)) return undefined;
      const count = index === 0 ? size.phases : 3;
      const scope = scopes.phases(key);
      const result = paged(Array.from({ length: count }, (_, i) => phaseNode(key, i)), scope, url, 200);
      if (result.stale) return result;
      const codes = result.page.map(node => node.code);
      return { ...read, level: "phases", scope, version: version(scope), project: head(key, index === 0 ? DEEP.name : `project-${pad(index + 1, 2)}`), items: result.page,
        edges: codes.slice(1).map((code, i) => ({ kind: "roadmap_order", source: codes[i], target: code })), next_cursor: result.next };
    },
    tasks(project: string, phase: string, url = new URL("http://x/")): S["MapTasksRead"] | { stale: true } | undefined {
      const key = project === DEEP.registered ? DEEP.key : project;
      if (key !== DEEP.key && !/^kp-p\d+$/.test(key)) return undefined;
      const count = key === DEEP.key && phase === DEEP.phase ? size.tasks : 4;
      const scope = scopes.tasks(key, phase);
      const nodes = Array.from({ length: count }, (_, i) => taskNode(phase, i));
      const result = paged(nodes, scope, url, 300);
      if (result.stale) return result;
      const shown = new Set(result.page.map(node => node.code));
      const edges: S["MapEdge"][] = [];
      for (const node of result.page) {
        for (const dep of node.depends_on) edges.push({ kind: "depends_on", source: node.code, target: dep, target_in_phase: true });
        for (const old of node.replaces) edges.push({ kind: "replaces", source: node.code, target: old, target_in_phase: true });
        for (const successor of node.replaced_by) if (!shown.has(successor)) edges.push({ kind: "replaces", source: successor, target: node.code, target_in_phase: true });
      }
      return { ...read, level: "tasks", scope, version: version(scope), project: head(key), phase: { code: phase, title: "Work map", status: status("ACTIVE", "progress"), instance: null },
        items: result.page, edges, next_cursor: result.next };
    },
    runs(project: string, phase: string, task: string, url = new URL("http://x/")): S["MapRunsRead"] | { stale: true } | undefined {
      const key = project === DEEP.registered ? DEEP.key : project;
      const deep = key === DEEP.key && task === DEEP.task;
      const count = deep ? size.runs : task.endsWith("T004") && !state.started.has(task) ? 0 : 1;
      const scope = scopes.runs(key, phase, task);
      const items: S["MapRunItem"][] = Array.from({ length: count }, (_, i) => ({
        run_id: deep ? (i === 0 ? deepRun : `run-atlas-${pad(count - i)}`) : `run-${task}`,
        status: deep && i === 0 ? status(state.finished ? "COMMITTED" : "EXECUTING", state.finished ? "done" : "progress") : [status("REVISION_LIMIT", "failed"), status("STOPPED", "inactive"), status("COMMITTED", "done")][i % 3],
        stage: "execution", revisions: i % 3, revision_limit: 3, attempts: counter(1 + (i % 3), "derived", { executor: 1 + (i % 2) }), cycles: i % 3,
        acceptance: { state: "absent", eligible: null, reasons: [], source: "absent", reason: "not_evaluated" }, commit: null,
        created_at: at(40 - i), updated_at: at(41 - i),
      }));
      const result = paged(items, scope, url, 50);
      if (result.stale) return result;
      return { ...read, level: "runs", scope, version: version(scope), project: head(key), phase, task, latest_run_id: url.searchParams.get("cursor") ? null : result.page[0]?.run_id ?? null,
        items: result.page, next_cursor: result.next };
    },
    steps(project: string, run: string, url = new URL("http://x/")): S["MapStepsRead"] | { stale: true } | undefined {
      const key = project === DEEP.registered ? DEEP.key : project;
      const scope = scopes.steps(key, run);
      const items = stepItems(run);
      const result = paged(items, scope, url, 200);
      if (result.stale) return result;
      const task = run === deepRun || run.startsWith("run-atlas-") ? DEEP.task : run.replace(/^run-/, "");
      return { ...read, level: "steps", scope, version: version(scope), project: head(key),
        run: { run_id: run, purpose: "task", phase: task.split("-")[0], task, status: run === deepRun ? status(state.finished ? "COMMITTED" : "EXECUTING", state.finished ? "done" : "progress") : status("COMMITTED", "done"),
          stage: "execution", revisions: 1, revision_limit: 3, created_at: at(40), updated_at: at(55) },
        items: result.page, bubbles: bubbles(run === deepRun ? taskItems.filter(item => item.topic === "run_permission") : [], false),
        // T020's run-scoped chat lane: the project's active chats attached to this run, on every page, at most 20.
        chats: chatsOf(run).slice(0, MAX_LIST), chats_truncated: chatsOf(run).length > MAX_LIST,
        edges: result.page.slice(1).map((step, i) => ({ kind: "step_order", source: result.page[i].key!, target: step.key! })), next_cursor: result.next };
    },
    invocation(project: string, invocation: string): S["MapInvocationRead"] | undefined {
      const key = project === DEEP.registered ? DEEP.key : project;
      const step = options.reviewer && invocation === reviewerRunning
        ? { ...invocationStep(deepRun, 7, 3, "reviewer", "R", status("RUNNING", "progress", { process: "RUNNING" }), null, false, true), invocation_id: reviewerRunning, attempt_id: "att-atlas-7" } as S["MapStep"]
        : stepItems(deepRun).find(item => item.invocation_id === invocation);
      const chat = invocation === chatInvocation;
      if (!step && !chat) return undefined;
      return { ...read, level: "invocation", scope: `s1.fixture.invocation.${invocation}`, version: `v1.${state.version}`, project: head(key),
        invocation: { invocation_id: invocation, lane: "managed_attempt", purpose: chat ? "chat" : "task", role: chat ? "chat" : step!.role ?? "executor", circle: chat ? "R" : step!.circle,
          started_at: at(50), finished_at: null, launch: status("pending", "progress"), outcome: null, process: null },
        owner: chat ? { lane: "chat", run_id: "run-chat-1", phase: DEEP.phase, task: DEEP.task, breadcrumb: [{ level: "project", id: key }, { level: "chat", id: "conv-1" }, { level: "invocation", id: invocation, role: "chat", ordinal: 1 }] }
          : { lane: "task", run_id: deepRun, phase: DEEP.phase, task: DEEP.task, breadcrumb: [{ level: "project", id: key }, { level: "phase", id: DEEP.phase }, { level: "task", id: DEEP.task }, { level: "run", id: deepRun }, { level: "invocation", id: invocation, role: step!.role, ordinal: 1 }] },
        step: chat ? null : step!, steps: { state: chat ? "not_settled" : "sealed", reason: null, summary: null, observation: null, failure: null, scope: `s1.fixture.trace.${invocation}` },
        related_scopes: {}, evidence: { run: `/api/managed/runs/${deepRun}`, run_events: `/api/managed/runs/${deepRun}/events`, attempt_logs: null } };
    },
    activity(requested: readonly string[]): S["MapActivityRead"] {
      const lit = active();
      return { format: "work-map-1", read_only_archive: archive, polling: { active_interval_ms: 2000, idle_interval_ms: 10000, pause_when_hidden: true, enabled: !archive },
        active: lit.length > 0, scopes: requested.map(scope => scope.startsWith("s1.fixture.") ? { scope, version: version(scope) } : { scope, version: null, error: "not_found" }),
        active_invocations: lit.map(item => ({ ...item, project_id: DEEP.key })), active_invocations_truncated: false, unscoped_invocations: [], harness: lit.length ? [DEEP.key] : [],
        bubbles: bubbles(allItems, false) };
    },
    /** The element request list: exact filters on every page, 50 per page by id, cursors bound to the version. */
    bubbleList(project: string, url: URL): S["MapBubblesRead"] | { stale: true } | undefined {
      const key = project === DEEP.registered ? DEEP.key : project;
      if (key !== DEEP.key && !/^kp-p\d+$/.test(key)) return undefined;
      const filter = { phase: url.searchParams.get("phase"), task: url.searchParams.get("task"), run: url.searchParams.get("run"),
        attempt: url.searchParams.get("attempt"), circle: url.searchParams.get("circle") as BubbleItem["circle"] | null };
      const items = (key === DEEP.key ? allItems : []).map(item => ({ ...item, ...scopeOf(item) })).sort((a, b) => a.id < b.id ? -1 : 1)
        .filter(item => (!filter.phase || item.phase === filter.phase) && (!filter.task || item.task === filter.task) && (!filter.run || item.run_id === filter.run)
          && (!filter.attempt || item.attempt_id === filter.attempt) && (!filter.circle || item.circle === filter.circle));
      const scope = `s1.fixture.bubbles.${key}.${url.searchParams.toString()}`;
      const result = paged(items, scope, url, 50);
      if (result.stale) return result;
      return { ...read, level: "bubbles", scope, version: version(scope), project: head(key), filter, bubbles: bubbles(items, false),
        items: result.page.map(({ attempt_id: _attempt, ...item }) => item), next_cursor: result.next };
    },
    inboxPage(url: URL): S["InboxPageRead"] {
      const before = url.searchParams.get("before");
      const start = before ? allItems.findIndex(item => item.id === before) + 1 : 0;
      const page = allItems.slice(start, start + 30);
      return { items: page.map(item => inboxItem(item)), next_before: start + 30 < allItems.length ? page[page.length - 1].id : null };
    },
    inboxItem(id: string): S["InboxItemDetail"] | undefined {
      const item = allItems.find(entry => entry.id === id);
      if (!item) return undefined;
      const resolved = state.finished && item.topic === "run_permission";
      return { ...inboxItem(item), phase_instance_id: null, resolved, current_state: resolved ? "GRANTED" : "PENDING",
        response: archive || resolved ? null : item.topic === "run_permission"
          ? { target_id: deepRun, version: 10 + state.version, request_version: 2, proof: "a".repeat(64), prompts: [] }
          : item.topic === "task_gap" ? { target_id: deepRun, version: 10 + state.version, request_version: 7, proof: "b".repeat(64), prompts: ["Synthetic question?"] }
          : { target_id: "ph-kp-atlas-P002", version: 4, request_version: 1, prompts: ["Synthetic phase question?"] },
        standing_permission: null, continuation: null, context: ["Synthetic context line"] };
    },
  };

  function inboxItem(item: BubbleItem): S["InboxItemRead"] & Omit<S["InboxItemDetail"], "response" | "standing_permission" | "continuation" | "context" | "phase_instance_id" | "current_state"> {
    const task = item.topic !== "phase_question";
    return { id: item.id, kind: item.kind, topic: item.topic, mode: "manual", project_id: DEEP.key, registered_project_id: archive ? null : DEEP.registered,
      knowledge_project_id: DEEP.key, at: at(45), origin: item.topic === "phase_question" ? "phase" : "managed", event_id: item.id.split(":")[1],
      phase_id: DEEP.phase, task_id: task ? DEEP.task : null, run_id: task ? deepRun : null, autonomous_run_id: null, operation_id: null,
      request_id: item.id.split(":")[1], evidence_id: task ? "att-atlas-6" : null, thread_id: null, read_at: null, resolved: false } as never;
  }
}

/**
 * Answers the map and inbox reads of the work map from `map`, as the service would (JSON with the status), for the
 * fetch shim of the development fixture and for tests. Unknown paths answer 404; superseded cursors 409.
 */
export function respond(map: SyntheticMap, path: string): { status: number; body: unknown } {
  const url = new URL(path, "http://synthetic");
  const parts = url.pathname.replace(/^\/api\/managed/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const found = (value: unknown) => value === undefined ? { status: 404, body: { detail: { code: "map_not_found" } } }
    : value && typeof value === "object" && "stale" in value && (value as { stale: boolean }).stale ? { status: 409, body: { detail: { code: "cursor_stale" } } }
    : { status: 200, body: value };
  const original = originalFixture(parts, url);
  if (original) return found(original);
  if (parts[0] === "inbox") return parts.length === 1 ? found(map.inboxPage(url)) : found(map.inboxItem(parts[1]));
  if (parts[0] !== "map") return { status: 404, body: { detail: { code: "not_found" } } };
  if (parts[1] === "activity") return found(map.activity(url.searchParams.getAll("scope")));
  const [, , project, level, a, b, c, d] = parts;
  if (parts.length === 2 && parts[1] === "projects") return found(map.projects(url));
  if (level === "phases" && parts.length === 4) return found(map.phases(project, url));
  if (level === "phases" && b === "tasks" && parts.length === 6) return found(map.tasks(project, a, url));
  if (level === "phases" && b === "tasks" && d === "runs" && parts.length === 8) return found(map.runs(project, a, c, url));
  if (level === "runs" && b === "steps") return found(map.steps(project, a, url));
  if (level === "documents") return found(fixtureDocuments(url));
  if (level === "invocations" && (b === "steps" || b === "related")) {
    const header = map.invocation(project, a);
    return found(header && tracePage(header, url, b === "steps" ? "steps" : url.searchParams.get("group") ?? "records"));
  }
  if (level === "invocations" && parts.length === 5) return found(map.invocation(project, a));
  if (level === "bubbles" && parts.length === 4) return found(map.bubbleList(project, url));
  return { status: 404, body: { detail: { code: "map_not_found" } } };
}
