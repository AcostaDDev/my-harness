// Status classes of the persisted vocabularies the list pages show (T018 §§5.1–5.2, D304, P002-T022). The table is
// `status-classes.json`, an exact copy of T020's mapping for runs, attempts and phases (`core/engine/work_map.py`);
// a Python parity test compares both and the persisted vocabularies. The map itself never maps statuses: it shows the
// class T020 projects. A value without a mapping is `unknown` and keeps its raw code, never a guessed class.
import table from "./status-classes.json";
import type { StatusClass } from "./map/status.ts";

export type StatusEntity = keyof typeof table;

const INDEX = Object.fromEntries(Object.entries(table).map(([entity, classes]) =>
  [entity, new Map(Object.entries(classes).flatMap(([cls, codes]) => (codes as string[]).map(code => [code, cls as StatusClass])))])) as
  Record<StatusEntity, Map<string, StatusClass>>;

/** Class of one persisted code of one entity; `unknown` without a mapping. */
export function statusClass(entity: StatusEntity, code: string | null | undefined): StatusClass {
  return (code != null && INDEX[entity].get(code)) || "unknown";
}

/**
 * Class of a value shown by the shared `Status`: phases read the phase table; everything else is a run status or an
 * attempt outcome (the stored, upper-cased stream status), which share no code with different classes.
 */
export function listStatusClass(kind: "run" | "phase", code: string): StatusClass {
  if (kind === "phase") return statusClass("phase", code);
  const run = statusClass("run", code);
  return run === "unknown" ? statusClass("attempt", code) : run;
}
