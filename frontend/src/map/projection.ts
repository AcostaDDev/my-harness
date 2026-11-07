// T020 projections → map cards (P002-T022, T018 §§3–5, D304, D311). Pure functions: the status class, counters,
// circles, rays, chat lane and bubbles are shown exactly as projected, never recomputed. A counter whose source is
// `absent` (or whose value is missing) is labelled "not observed", never drawn as zero (INV-09). Every active
// invocation is its own actor (two concurrent R lanes are two circles), and at L3 an active chat attached to the run
// shown is a lane node of its own, outside the run's step sequence.
import type { Plural, Translate } from "../i18n.ts";
import type { S } from "../managed-api";
import type { Route } from "../router.ts";
import type { ActorRole, NodeActor, NodeSlot } from "./labels.ts";
import type { Arrangement, MapEdge, MapNode } from "./MapView";
import type { MapPhases, MapProjects, MapSteps, MapTasks } from "./api.ts";

export type Card = S["MapProjectCard"];
export type PhaseNode = S["MapPhaseNode"];
export type TaskNode = S["MapTaskNode"];
export type Step = S["MapStep"];
export type Circle = S["MapCircleState"];
export type Counter = S["MapCounter"];
export type Active = S["MapActiveInvocation"];

export type LevelItem =
  | { level: 0; item: Card; project: string }
  | { level: 1; item: PhaseNode; project: string }
  | { level: 2; item: TaskNode; project: string; phase: string }
  | { level: 3; item: Step; project: string; chat?: undefined }
  /** An active chat invocation attached to the run shown (T018 §5.3 chat lane): not a step of the run. */
  | { level: 3; item: Active; project: string; chat: true };

export type LevelView = { nodes: MapNode[]; edges: MapEdge[]; arrangement: Arrangement; items: Map<string, LevelItem> };
export type Texts = { t: Translate; n: Plural; language: string };
export const ROLE_CIRCLES: readonly ActorRole[] = ["R", "E", "J", "H"];

/** Value of a counter, or undefined when it was not observed (absent source or no value). */
export function observed(counter: Counter | null | undefined): unknown {
  if (!counter || counter.source === "absent" || counter.value === null || counter.value === undefined) return undefined;
  return counter.value;
}

function numberOf(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/** Human duration from measured milliseconds, in the interface language. */
export function duration(ms: number, language: string): string {
  const format = (value: number, digits: number) => new Intl.NumberFormat(language, { maximumFractionDigits: digits }).format(value);
  if (ms < 1000) return `${format(ms, 0)} ms`;
  if (ms < 60000) return `${format(ms / 1000, 1)} s`;
  const minutes = Math.floor(ms / 60000), seconds = Math.round((ms % 60000) / 1000);
  return `${format(minutes, 0)} min ${format(seconds, 0)} s`;
}

/** "{done}/{total}" counters (phases closed/total, tasks committed/total); absent stays absent. */
function fraction(counter: Counter, key: "map.counter.phases" | "map.counter.tasks", { t }: Texts): string {
  const done = numberOf(observed(counter)), total = numberOf(counter.total);
  return done === undefined || total === undefined ? t(`${key}_absent`) : t(key, { done, total });
}

/** L2 primary counter: executor attempts of the latest run / its revision limit (supplied). */
export function attemptsText(task: TaskNode, { t }: Texts): string {
  if (!task.latest) return t("map.counter.no_runs");
  const value = numberOf(observed(task.latest.attempts)), limit = numberOf(task.latest.attempts.revision_limit);
  return value === undefined || limit === undefined ? t("map.counter.attempts_absent") : t("map.counter.attempts", { value, limit });
}

export function durationText(step: Step, { t, language }: Texts): string {
  const ms = numberOf(observed(step.duration_ms));
  return ms === undefined ? t("map.counter.duration_absent") : duration(ms, language);
}

export function invocationRoute(project: string, invocation: string): Route {
  return { name: "invocation", project, invocation };
}

/**
 * Circles as the card draws them. An idle circle is one actor whose `target` is its latest invocation in the element
 * (L4 header). An active circle is one actor per active invocation of the element (`active`, T020's own list), each
 * opening that invocation and carrying its own chat flag, so a reviewer and a chat running at once are two R circles;
 * the circle's request count sits on its first actor only. H has no invocations: one actor, lit by Harness work.
 */
export function actorsOf(circles: readonly Circle[], project: string, active: readonly Active[] = []): NodeActor[] {
  return circles.flatMap((circle): NodeActor[] => {
    const requests = circle.bubbles || undefined;
    const running = circle.circle === "H" || !circle.active ? [] : active.filter(item => item.circle === circle.circle);
    if (!running.length) return [{ role: circle.circle, active: circle.active, chat: circle.chat, requests,
      target: circle.latest_invocation ? invocationRoute(project, circle.latest_invocation.invocation_id) : undefined }];
    return running.map((item, i) => ({ role: circle.circle, active: true, chat: item.chat, requests: i === 0 ? requests : undefined,
      target: item.invocation_id ? invocationRoute(project, item.invocation_id) : undefined }));
  });
}

/** Circles sit where work happens (T018 §5.3): every project card, and deeper only where something runs or waits. */
function working(circles: readonly Circle[]): boolean {
  return circles.some(circle => circle.active || circle.waiting || circle.bubbles > 0);
}

/** Identity used in URLs below L0: the configured project in ordinary mode (its list pages need it), else the key. */
export function routeProject(card: Card, archive: boolean): string {
  return archive ? card.id : card.registered_project_id ?? card.id;
}

const ordinal = (i: number) => String(i).padStart(5, "0");

export function projectsView(pages: readonly MapProjects[], archive: boolean, texts: Texts): LevelView {
  const { t } = texts;
  const items = new Map<string, LevelItem>();
  const nodes = pages.flatMap(page => page.items).map((card, i): MapNode => {
    const project = routeProject(card, archive);
    items.set(card.id, { level: 0, item: card, project });
    const phase = card.active_phase;
    return {
      id: card.id, kind: "project", order: ordinal(i), code: card.name,
      title: phase ? (phase.title ? `${phase.code} · ${phase.title}` : phase.code) : t("map.card.no_open_phase"),
      statusClass: card.status.class, status: card.status.code ?? card.status.class,
      actors: actorsOf(card.circles, project, card.active_invocations), requests: card.bubbles.total || undefined,
      counter: fraction(card.phases, "map.counter.phases", texts), errors: card.errors.length || undefined,
      badge: t(card.mode.kind === "autonomous" ? "map.mode.autonomous" : "map.mode.manual"),
      to: { name: "phases", project },
    };
  });
  return { nodes, edges: [], arrangement: "grid", items };
}

function slotsOf(phase: PhaseNode, { t }: Texts): NodeSlot[] {
  return (["plan", "check", "close"] as const).map(key => {
    const slot = phase.slots[key];
    return { key, label: t(`map.slot.${key}`), statusClass: slot?.status.class, actors: slot ? [...new Set(slot.actors.map(actor => actor.circle))] : [] };
  });
}

export function phasesView(pages: readonly MapPhases[], project: string, texts: Texts): LevelView {
  const items = new Map<string, LevelItem>();
  const seen = new Set<string>();
  const nodes = pages.flatMap(page => page.items).map((phase): MapNode => {
    seen.add(phase.code);
    items.set(phase.code, { level: 1, item: phase, project });
    return {
      id: phase.code, kind: "phase", order: phase.code, code: phase.code, title: phase.title ?? phase.objective ?? "",
      statusClass: phase.status.class, status: phase.status.code ?? phase.status.class,
      actors: phase.active || working(phase.circles) ? actorsOf(phase.circles, project, phase.active_invocations) : undefined,
      requests: phase.bubbles.total || undefined, counter: fraction(phase.tasks, "map.counter.tasks", texts),
      errors: phase.errors.length || undefined, slots: slotsOf(phase, texts),
      to: { name: "phase", project, phase: phase.code },
    };
  });
  // Roadmap order: consecutive codes; the engine tolerates an endpoint on another page.
  const edges = pages.flatMap(page => page.edges).filter(edge => edge.kind === "roadmap_order")
    .map((edge): MapEdge => ({ from: edge.source, to: edge.target, kind: "sequence" }))
    .filter(edge => seen.has(edge.from) || seen.has(edge.to));
  return { nodes, edges: dedupe(edges), arrangement: "layered", items };
}

export function tasksView(pages: readonly MapTasks[], project: string, phase: string, texts: Texts): LevelView {
  const items = new Map<string, LevelItem>();
  const nodes = pages.flatMap(page => page.items).map((task, i): MapNode => {
    items.set(task.code, { level: 2, item: task, project, phase });
    const lit = working(task.circles) || ["progress", "waiting"].includes(task.status.class);
    return {
      id: task.code, kind: "task", order: ordinal(i), code: task.code, title: task.title ?? task.problem.value ?? "",
      statusClass: task.status.class, status: task.status.code ?? task.status.class,
      actors: lit ? actorsOf(task.circles, project, task.active_invocations) : undefined, requests: task.bubbles.total || undefined,
      counter: attemptsText(task, texts), errors: task.errors.length || undefined,
      to: { name: "task", project, phase, task: task.code },
    };
  });
  // T020: `source` depends on (or replaces) `target`; the engine draws prerequisite → dependent and replaced → successor.
  const edges = pages.flatMap(page => page.edges)
    .filter(edge => edge.kind === "depends_on" || edge.kind === "replaces")
    .map((edge): MapEdge => ({ from: edge.target, to: edge.source, kind: edge.kind as "depends_on" | "replaces" }));
  return { nodes, edges: dedupe(edges), arrangement: "layered", items };
}

const ROLE_KEYS = new Set(["executor", "reviewer", "planner", "phase", "chat", "bootstrap", "definition", "planning", "configuration", "judge", "preparation"]);

export function roleText(role: string | null | undefined, t: Translate): string {
  if (!role) return t("map.role.unknown");
  return ROLE_KEYS.has(role) ? t(`map.role.${role}` as Parameters<Translate>[0]) : role;
}

/** "Executor #2" for an invocation; the stage name for a Harness step. */
export function stepLabel(step: Step, t: Translate): string {
  if (step.kind === "harness") return t(`map.stage.${step.stage ?? "unknown"}` as Parameters<Translate>[0]);
  const label = step.label as { role?: string; ordinal?: number } | null | undefined;
  return label?.ordinal ? t("map.step.label", { role: roleText(label.role ?? step.role, t), ordinal: label.ordinal }) : roleText(step.role, t);
}

function stepTitle(step: Step, t: Translate): string {
  if (step.kind === "harness") {
    const cycle = numberOf((step as { cycle?: unknown }).cycle);
    const commit = (step as { evidence?: { commit?: unknown } }).evidence?.commit;
    if (step.stage === "commit") return typeof commit === "string" && commit ? commit.slice(0, 12) : t("map.step.no_commit");
    return cycle === undefined ? t("map.step.harness") : t("map.step.cycle", { cycle: cycle + 1 });
  }
  const identity = step.identity as { agent?: string | null; client?: string | null; requested_model?: string | null } | null | undefined;
  const parts = [identity?.client ?? identity?.agent, identity?.requested_model].filter(Boolean);
  return parts.length ? parts.join(" · ") : t("map.step.identity_absent");
}

/** Active chat invocations of `project` attached to `run` (T020 activity: the conversation's task run). */
export function chatsOf(active: readonly (Active & { project_id?: string | null })[], project: string | undefined, run: string | undefined): Active[] {
  return run ? active.filter(item => item.chat && item.scope.run_id === run && (!project || item.project_id === project)) : [];
}

/**
 * L3: the run's steps in T020's order, plus one lane node per active chat attached to the run (`chats`): drawn with
 * R lit and labelled "chat", its persisted invocation as target, and no edge into the step sequence.
 */
export function stepsView(pages: readonly MapSteps[], project: string, texts: Texts, chats: readonly Active[] = []): LevelView {
  const { t } = texts;
  const items = new Map<string, LevelItem>();
  const nodes = pages.flatMap(page => page.items).map((step, i): MapNode => {
    const id = step.key ?? `step-${i}`;
    items.set(id, { level: 3, item: step, project });
    const circle = step.circle ?? (step.kind === "harness" ? "H" : undefined);
    const active = step.kind === "harness" ? step.status.class === "progress" : (step as { active?: unknown }).active === true;
    const bubbles = step.bubbles?.total ?? 0;
    const actors: NodeActor[] | undefined = circle ? [{ role: circle, active, requests: bubbles || undefined,
      target: step.kind === "invocation" && step.invocation_id ? invocationRoute(project, step.invocation_id) : undefined }] : undefined;
    return {
      id, kind: "step", order: id, code: stepLabel(step, t), title: stepTitle(step, t),
      statusClass: step.status.class, status: step.status.code ?? step.status.class,
      actors, requests: bubbles || undefined, counter: durationText(step, texts),
    };
  });
  chats.forEach((chat, i) => {
    const id = `chat:${chat.invocation_id ?? chat.attempt_id ?? i}`;
    items.set(id, { level: 3, item: chat, project, chat: true });
    nodes.push({
      id, kind: "step", order: `chat.${String(i).padStart(4, "0")}`, code: t("map.chat.lane"), title: chatTitle(chat, t),
      statusClass: "progress", status: chat.process,
      actors: [{ role: chat.circle ?? "R", active: true, chat: true, target: chat.invocation_id ? invocationRoute(project, chat.invocation_id) : undefined }],
      counter: texts.t("map.counter.duration_absent"),
    });
  });
  const edges = pages.flatMap(page => page.edges).filter(edge => edge.kind === "step_order")
    .map((edge): MapEdge => ({ from: edge.source, to: edge.target, kind: "sequence" }));
  // Consecutive pages: link the last step of one page to the first of the next.
  for (let p = 1; p < pages.length; p++) {
    const before = pages[p - 1].items.at(-1)?.key, after = pages[p].items[0]?.key;
    if (before && after) edges.push({ from: before, to: after, kind: "sequence" });
  }
  return { nodes, edges: dedupe(edges), arrangement: "layered", items };
}

/** "Reviewer · codex": the chat's role and agent as the activity read reports them. */
export function chatTitle(chat: Active, t: Translate): string {
  return [roleText(chat.role, t), chat.agent].filter(Boolean).join(" · ");
}

function dedupe(edges: MapEdge[]): MapEdge[] {
  const seen = new Set<string>();
  return edges.filter(edge => { const key = `${edge.from}->${edge.to}:${edge.kind}`; if (seen.has(key)) return false; seen.add(key); return true; });
}

/** Status snapshot for live-region announcements: class and raw code of each node, with its visible text. */
export function statusSnapshot(nodes: readonly MapNode[], statusText: (node: MapNode) => string) {
  return new Map(nodes.map(node => [node.id, { code: node.code, status: `${node.statusClass}|${node.status}`, label: statusText(node) }]));
}
