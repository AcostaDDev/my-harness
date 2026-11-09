// T024: the tag's only submission field is `element`. Refresh locators never enter a message.
import { managed } from "./managed-api";
import type { S } from "./managed-api";

export type ElementTarget = { kind: "phase" | "task" | "run" | "step"; target: string; step_key?: string };
export type ElementSelection = { target?: ElementTarget; value: S["ChatElementRead"] };
const key = (project: string, conversation: string) => `harness-chat-element:${project}:${conversation}`;
export function saveElement(project: string, conversation: string, selection?: ElementSelection) {
  if (selection) sessionStorage.setItem(key(project, conversation), JSON.stringify(selection));
  else sessionStorage.removeItem(key(project, conversation));
}
export function loadElement(project: string, conversation: string): ElementSelection | undefined {
  try { return JSON.parse(sessionStorage.getItem(key(project, conversation)) ?? "null") ?? undefined; }
  catch { return undefined; }
}
export async function resolveElement(project: string, target: ElementTarget) {
  const query = new URLSearchParams({ kind: target.kind, target: target.target,
    ...(target.step_key ? { step_key: target.step_key } : {}) });
  return managed<S["ChatElementRead"]>(`/projects/${encodeURIComponent(project)}/chat-context?${query}`);
}
