/** P009-T020: choose phase and task from the documents instead of copying the contract by hand. */
import type { S } from "./managed-api";

type Source = S["TaskSourceRead"];

/** Phases the document offers, in their order; a phase fixed by the page only offers itself. */
export function sourcePhases(items: Source[], fixed?: string): string[] {
  const phases = [...new Set(items.map(item => item.phase_id))];
  return fixed ? phases.filter(phase => phase === fixed) : phases;
}

/** Tasks of the chosen phase; a task fixed by the page only offers itself. */
export function sourceTasks(items: Source[], phase: string, fixed?: string): Source[] {
  return items.filter(item => item.phase_id === phase && (!fixed || item.task_id === fixed));
}

/** Body of `POST /runs`: with a task from the document it carries its hash (CAS); blank notes are not sent. */
export function runBody(source: Source | null, manual: { task: string; phase: string; text: string }, notes: string): S["RunCreate"] {
  const extra = notes.trim() ? { notes: notes.trim() } : {};
  if (source) return { task_id: source.task_id, phase_id: source.phase_id, text: source.text, source_sha256: source.sha256, ...extra };
  return { task_id: manual.task.trim(), phase_id: manual.phase.trim(), text: manual.text, ...extra };
}
