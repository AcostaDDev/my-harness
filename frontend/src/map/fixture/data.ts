// Synthetic, reproducible map data for the T021 development fixture (never product data; no runs or credentials).
// One deep path with leaf siblings at each level (D309, T018 §12): project `atlas` → phase `P002` → task `P002-T005`.
import type { Route } from "../../router.ts";
import type { MapEdge, MapNode, Arrangement } from "../MapView";
import type { ActorRole } from "../labels.ts";
import { STATUS_CLASSES } from "../status.ts";
import type { StatusClass } from "../status.ts";

export const SCENARIOS = ["normal", "budget", "stress"] as const;
export type Scenario = typeof SCENARIOS[number];

/** Rows per level: normal review data, D309's per-level maxima, and the 200-visible-node stress case at L2. */
export const SIZES: Record<Scenario, { projects: number; phases: number; tasks: number; steps: number }> = {
  normal: { projects: 8, phases: 9, tasks: 14, steps: 8 },
  budget: { projects: 25, phases: 40, tasks: 80, steps: 40 },
  stress: { projects: 25, phases: 40, tasks: 200, steps: 40 },
};

export const DEEP = { project: "atlas", phase: "P002", task: "P002-T005", run: "run-0002" } as const;

export type FixtureLevel = {
  nodes: MapNode[];
  edges: MapEdge[];
  arrangement: Arrangement;
  level: "projects" | "phases" | "tasks" | "steps";
  scope: string;
};

/** Mulberry32: small deterministic generator, so every scenario renders the same data on every load. */
function random(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Titles mix English and Spanish, long titles, Latin Extended-A (second font subset) and scripts outside both
// subsets, which must fall back to the interface font.
const TITLES = [
  "Migrate the index of runs", "Revisar contratos de la API", "Añadir reseñas con ¿preguntas? y ¡avisos!",
  "Página de inicio «mapa» — borrador…", "Fix flaky retry on lease renewal", "Configurar el juez por proyecto",
  "Łódź, Gdańsk and Kraków locales", "Žluťoučký kůň: Czech sample labels", "Обзор журнала событий",
  "日本語のタスク名", "Document the archive restore path in detail with every edge case covered",
  "Mejorar la accesibilidad del teclado", "Ship the 0.2.0 release notes", "Validar códigos ñandú y pingüino",
  "Őrült ötletek: Hungarian ő and ű", "Small task", "Tâche française : élève, garçon, cœur",
  "Normalize trace payloads", "Cálculo de costes por modelo", "Retry budget per cause",
];

const ROLES: ActorRole[] = ["R", "E", "J", "H"];

function statusAt(i: number, rand: () => number): StatusClass {
  // The first seven rows cover every class in order; the rest are weighted towards realistic mixes.
  if (i < STATUS_CLASSES.length) return STATUS_CLASSES[i];
  const roll = rand();
  return roll < 0.45 ? "done" : roll < 0.6 ? "pending" : roll < 0.7 ? "progress" : roll < 0.78 ? "waiting"
    : roll < 0.86 ? "failed" : roll < 0.97 ? "inactive" : "unknown";
}

const RAW: Record<StatusClass, string[]> = {
  done: ["COMMITTED", "CLOSED", "SUCCEEDED"],
  progress: ["RUNNING", "QUEUED", "PLANNING"],
  waiting: ["WAITING_FOR_OWNER", "AWAITING_CONFIRMATION"],
  failed: ["FAILED", "BLOCKED", "INTERRUPTED"],
  pending: ["PENDING", "NOT_STARTED"],
  inactive: ["ABANDONED", "SUPERSEDED", "CANCELLED"],
  unknown: ["LEGACY_HOLD", "X_FUTURE_STATE"],
};

function node(id: string, kind: MapNode["kind"], code: string, title: string, cls: StatusClass, rand: () => number, to?: Route): MapNode {
  const raw = RAW[cls];
  return { id, kind, code, title, statusClass: cls, status: raw[Math.floor(rand() * raw.length)], order: code, ...(to ? { to } : {}) };
}

function pad(n: number) { return String(n).padStart(3, "0"); }

function projects(scenario: Scenario): FixtureLevel {
  const rand = random(101);
  const names = ["atlas", "bitácora", "cobalt", "dédalo", "emberline", "fjord", "galena", "hélice", "iris", "junco"];
  const nodes = Array.from({ length: SIZES[scenario].projects }, (_, i) => {
    const project = i === 0 ? DEEP.project : `${names[i % names.length]}-${pad(i)}`;
    const cls = i === 0 ? "progress" : statusAt(i - 1, rand);
    const item = node(`project:${project}`, "project", project, TITLES[(i * 7) % TITLES.length], cls, rand, { name: "phases", project });
    if (i === 0) return { ...item, actors: [{ role: "R" as const, active: true }, { role: "E" as const, active: false }, { role: "J" as const, active: false }], requests: 2 };
    if (i === 3) return { ...item, actors: [{ role: "R" as const, active: false }, { role: "E" as const, active: true }] };
    return item;
  });
  return { nodes, edges: [], arrangement: "grid", level: "projects", scope: "" };
}

function phases(scenario: Scenario, project: string): FixtureLevel {
  if (project !== DEEP.project) return { nodes: [], edges: [], arrangement: "layered", level: "phases", scope: project };
  const rand = random(202);
  const count = SIZES[scenario].phases;
  const nodes = Array.from({ length: count }, (_, i) => {
    const code = `P${pad(i + 1)}`;
    const cls: StatusClass = i === 0 ? "done" : i === 1 ? "progress" : statusAt(i - 2, rand);
    const item = node(`phase:${project}:${code}`, "phase", code, TITLES[(i * 3 + 1) % TITLES.length], cls, rand, { name: "phase", project, phase: code });
    return i === 1 ? { ...item, actors: ROLES.map(role => ({ role, active: role === "E" })) } : item;
  });
  const edges = nodes.slice(1).map((item, i) => ({ from: nodes[i].id, to: item.id, kind: "sequence" as const }));
  return { nodes, edges, arrangement: "layered", level: "phases", scope: project };
}

function tasks(scenario: Scenario, project: string, phase: string): FixtureLevel {
  if (project !== DEEP.project || phase !== DEEP.phase) return { nodes: [], edges: [], arrangement: "layered", level: "tasks", scope: phase };
  const rand = random(303);
  const count = SIZES[scenario].tasks;
  const perWave = scenario === "normal" ? 3 : 10;
  const nodes = Array.from({ length: count }, (_, i) => {
    const code = i === 4 ? DEEP.task : `${phase}-T${String(i + 1).padStart(3, "0")}`;
    const cls: StatusClass = i === 4 ? "progress" : i === 1 ? "pending" : statusAt(i, rand);
    const item = node(`task:${project}:${phase}:${code}`, "task", code, TITLES[(i * 3 + 2) % TITLES.length], cls, rand, { name: "task", project, phase, task: code });
    if (i === 4) return { ...item, actors: [{ role: "R" as const, active: false }, { role: "E" as const, active: true }, { role: "H" as const, active: false }] };
    if (cls === "waiting") return { ...item, actors: [{ role: "R" as const, active: false }], requests: 1 + Math.floor(rand() * 3) };
    return item;
  });
  // Dependencies only reach the previous wave, so the graph has layers of about `perWave` tasks.
  const edges: MapEdge[] = [];
  nodes.forEach((item, i) => {
    const wave = Math.floor(i / perWave);
    if (!wave || i % 11 === 10) return; // a few tasks stay unconnected and go to the grid below the graph
    const previous = nodes.slice((wave - 1) * perWave, wave * perWave);
    const links = 1 + Math.floor(rand() * 2);
    const sources = new Set(Array.from({ length: links }, () => previous[Math.floor(rand() * previous.length)].id));
    for (const from of sources) edges.push({ from, to: item.id, kind: "depends_on" });
  });
  // `replaces` lineage (D296): a replacement task points back to the inactive task it replaces.
  nodes.forEach((item, i) => {
    if (item.statusClass === "inactive" && i + perWave < nodes.length && i % 11 !== 10) edges.push({ from: item.id, to: nodes[i + perWave].id, kind: "replaces" });
  });
  return { nodes, edges, arrangement: "layered", level: "tasks", scope: phase };
}

function steps(scenario: Scenario, project: string, phase: string, task: string, run?: string): FixtureLevel {
  const empty: FixtureLevel = { nodes: [], edges: [], arrangement: "layered", level: "steps", scope: task };
  if (project !== DEEP.project || phase !== DEEP.phase || task !== DEEP.task || (run && run !== DEEP.run)) return empty;
  const rand = random(run ? 405 : 404);
  const kinds: [ActorRole, string][] = [["R", "Plan review"], ["E", "Implement"], ["H", "Validate"], ["H", "Format"], ["J", "Judge ruling"], ["R", "Revisión final"], ["H", "Commit"], ["E", "Corrección"]];
  const count = SIZES[scenario].steps;
  const nodes = Array.from({ length: count }, (_, i) => {
    const [role, title] = kinds[i % kinds.length];
    const code = `${role}#${Math.floor(i / kinds.length) + 1}`;
    // Every class appears: settled steps first, then the active step and one not yet started.
    const cls: StatusClass = i === count - 1 ? "pending" : i === count - 2 ? "progress"
      : ({ 2: "failed", 3: "inactive", 4: "waiting", 5: "unknown" } as Record<number, StatusClass>)[i] ?? "done";
    // Steps have no deeper level in T021 (the L4 trace is T023): they are focusable but not enterable.
    return { ...node(`step:${project}:${phase}:${task}:${run ?? "latest"}:${i}`, "step", code, `${title} ${i + 1}`, cls, rand), order: pad(i), actors: [{ role, active: cls === "progress" }] };
  });
  const edges = nodes.slice(1).map((item, i) => ({ from: nodes[i].id, to: item.id, kind: "sequence" as const }));
  return { nodes, edges, arrangement: "layered", level: "steps", scope: run ? `${task} · ${run}` : task };
}

/** Level shown for a route, or undefined when the route is not a map level. */
export function fixtureLevel(scenario: Scenario, route: Route): FixtureLevel | undefined {
  switch (route.name) {
    case "home": return projects(scenario);
    case "phases": return phases(scenario, route.project);
    case "phase": return route.section ? undefined : tasks(scenario, route.project, route.phase);
    case "task": return steps(scenario, route.project, route.phase, route.task);
    case "run": return steps(scenario, route.project, route.phase, route.task, route.run);
    default: return undefined;
  }
}
