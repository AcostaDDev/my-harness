import type { S } from "./managed-api";
import { managed, ManagedError } from "./managed-api";
import type { MessageKey } from "./i18n.ts";
import { agentIssues, commandsIssues, isObject, profileIssues, texts } from "./profile-form.ts";

export type Form = Record<string, unknown>;
export type Draft = {
  form: Form; text: string; source: "form" | "text"; reason: string; validated: boolean;
  importExternal: boolean; base: S["ConfigurationRead"];
};
export type Review = { body: S["ConfigurationChange"]; preview: S["ConfigurationPreviewRead"] };
export type Action = { path: string; body: unknown; key: string };
const DRAFT = "harness-configuration-draft-v1";
const ACTION = "harness-configuration-action-v1";

export function stored<T>(key: string): T | undefined {
  try { return JSON.parse(sessionStorage.getItem(key) ?? "null") ?? undefined; } catch { return undefined; }
}
export const readDraft = () => stored<Draft>(DRAFT);
export function storeDraft(draft: Draft) { sessionStorage.setItem(DRAFT, JSON.stringify(draft)); }
export const readAction = () => stored<Action>(ACTION);

// Only this explicit retry resends a confirmation after a lost response. Never replay during render/mount.
export async function sendAction(action: Action) {
  sessionStorage.setItem(ACTION, JSON.stringify(action));
  try {
    const result = await managed<S["ConfigurationOperationRead"]>(action.path, action.body, action.key);
    sessionStorage.removeItem(ACTION);
    return result;
  } catch (error) {
    if (error instanceof ManagedError && error.status >= 400 && error.status < 500 && error.status !== 401)
      sessionStorage.removeItem(ACTION);
    throw error;
  }
}

export function initialDraft(base: S["ConfigurationRead"]): Draft {
  return { base, source: "form", text: base.text ?? "", reason: "", validated: true, importExternal: false,
    form: base.form ?? { service: { supervisor: false }, git: { executable: "", author_name: "", author_email: "" },
      agents: { reviewer: { provider: "", model: "", effort: "medium", timeout_seconds: 300, environment: { USER: "", PATH: "" } },
        executor: { provider: "", timeout_seconds: 300, environment: { USER: "", PATH: "" } } },
      registration: { roots: [], bootstrap_enabled: false } } };
}

export function field(form: Form, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => value && typeof value === "object" ? (value as Form)[key] : undefined, form);
}
export function changeField(form: Form, path: string, value: unknown): Form {
  const next = structuredClone(form);
  const keys = path.split(".");
  let parent = next;
  for (const key of keys.slice(0, -1)) {
    if (!parent[key] || typeof parent[key] !== "object" || Array.isArray(parent[key])) parent[key] = {};
    parent = parent[key] as Form;
  }
  if (value === undefined) delete parent[keys.at(-1)!];
  else parent[keys.at(-1)!] = value;
  return next;
}

export const efforts: Record<string, string[]> = {
  codex: ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"], claude: ["low", "medium", "high", "xhigh", "max"],
};
// D231: packaged suggestions only. Any other valid model is still typed by hand; the server validates the form.
export const models: Record<string, string[]> = {
  codex: ["gpt-6.1-sol", "gpt-6-sol", "gpt-6-astra", "gpt-6-luna"],
  claude: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
};
/** Packaged models for the provider, then any extra offered or already chosen, without duplicates and in order. */
export function modelOptions(provider: string | undefined, ...extra: string[][]): string[] {
  return [...new Set([...(models[provider ?? ""] ?? []), ...extra.flat()])];
}
export function errors(draft: Draft): Record<string, MessageKey> {
  const result: Record<string, MessageKey> = {};
  if (!draft.reason.trim()) result.reason = "configuration.required";
  if (draft.source === "text") {
    if (!draft.text.trim()) result.text = "configuration.required";
    return result;
  }
  if (!draft.validated) return result;
  const required = ["git.executable", "git.author_name", "git.author_email", "agents.reviewer.model",
    "agents.reviewer.environment.USER", "agents.executor.environment.USER"];
  for (const path of required) if (typeof field(draft.form, path) !== "string" || !String(field(draft.form, path)).trim())
    result[path] = "configuration.required";
  const paths = ["git.executable", ...["reviewer", "executor"].map(role => `agents.${role}.executable`)];
  for (const path of paths) {
    const value = field(draft.form, path);
    if (value && !(Array.isArray(value) ? String(value[0]) : String(value)).startsWith("/")) result[path] = "configuration.absolute";
  }
  for (const role of ["reviewer", "executor"]) {
    const prefix = `agents.${role}`;
    if (!efforts[String(field(draft.form, `${prefix}.provider`))]) result[`${prefix}.provider`] = "configuration.required";
    if (!(Number(field(draft.form, `${prefix}.timeout_seconds`)) > 0)) result[`${prefix}.timeout_seconds`] = "configuration.positive";
  }
  if (!(efforts[String(field(draft.form, "agents.reviewer.provider"))] ?? []).includes(String(field(draft.form, "agents.reviewer.effort"))))
    result["agents.reviewer.effort"] = "configuration.effort_invalid";
  const roots = field(draft.form, "registration.roots");
  if (Array.isArray(roots) && roots.some(root => typeof root !== "string" || !root.startsWith("/"))) result["registration.roots"] = "configuration.absolute";
  for (const role of ["reviewer", "executor"])
    for (const [key, issue] of Object.entries(agentIssues(field(draft.form, `agents.${role}`), `agents.${role}`, [role], efforts))) result[key] ??= issue;
  return { ...result, ...catalogIssues(draft.form) };
}

const MODEL = /^[A-Za-z0-9][A-Za-z0-9._:@[\]-]{0,127}$/;
/** OT004: reusable profiles, compositions and presets of the global form; the server repeats every check. */
export function catalogIssues(form: Form): Record<string, MessageKey> {
  const result: Record<string, MessageKey> = {};
  const profiles = isObject(form.profiles) ? form.profiles : {};
  for (const [name, profile] of Object.entries(profiles)) Object.assign(result, profileIssues(profile, `profiles.${name}`));
  for (const [name, composition] of Object.entries(isObject(form.compositions) ? form.compositions : {})) {
    const prefix = `compositions.${name}`;
    if (!isObject(composition)) { result[prefix] = "editor.command_invalid"; continue; }
    if (typeof composition.profile !== "string" || !composition.profile) result[`${prefix}.profile`] = "configuration.required";
    // Recipe compositions have fixed executables and authorization, checked by the server against the recipe.
    if (!composition.recipe) Object.assign(result, commandsIssues(composition, prefix, profiles[String(composition.profile)]));
  }
  for (const [name, preset] of Object.entries(isObject(form.agent_presets) ? form.agent_presets : {})) {
    const prefix = `agent_presets.${name}`;
    if (!isObject(preset)) { result[prefix] = "configuration.required"; continue; }
    const roles = texts(preset.roles);
    Object.assign(result, agentIssues(preset, prefix, roles, efforts));
    if (!roles.length || new Set(roles).size !== roles.length || roles.some(role => role !== "reviewer" && role !== "executor"))
      result[`${prefix}.roles`] = "editor.roles_required";
    const models = texts(preset.models);
    if (!models.length || new Set(models).size !== models.length || models.some(model => !MODEL.test(model)))
      result[`${prefix}.models`] = "editor.models_invalid";
    const chosen = texts(preset.efforts);
    if (!chosen.length || new Set(chosen).size !== chosen.length || chosen.some(effort => !(efforts[String(preset.provider)] ?? []).includes(effort)))
      result[`${prefix}.efforts`] = "configuration.effort_invalid";
  }
  return result;
}

export function candidate(draft: Draft): S["ConfigurationCandidate"] {
  return { ...(draft.source === "form" ? { form: draft.form } : { text: draft.text }), validated: draft.validated };
}
export function change(draft: Draft): S["ConfigurationChange"] {
  return { ...candidate(draft), expected_version: draft.base.version, base_sha256: draft.base.actual_sha256 ?? null,
    active_sha256: draft.base.active?.sha256 ?? null, reason: draft.reason, import_external: draft.importExternal };
}
export function baseChanged(a: S["ConfigurationRead"], b: S["ConfigurationRead"]) {
  return a.version !== b.version || a.actual_sha256 !== b.actual_sha256 || a.active?.sha256 !== b.active?.sha256;
}

export const modeLabels: Record<S["ConfigurationRead"]["mode"], MessageKey> = {
  UNCONFIGURED: "configuration.mode.unconfigured", INVALID: "configuration.mode.invalid", READY: "configuration.mode.ready",
  APPLY_PENDING: "configuration.mode.apply_pending", RESTART_REQUIRED: "configuration.mode.restart",
  RECOVERY_REQUIRED: "configuration.mode.recovery", READ_ONLY_ARCHIVE: "archive.title",
};

const WAITING: Record<string, MessageKey> = {
  job: "configuration.waiting.job", phase_operation: "configuration.waiting.phase_operation",
  acceptance: "configuration.waiting.acceptance", commit: "configuration.waiting.commit",
  documents: "configuration.waiting.documents", assistance: "configuration.waiting.assistance",
  project_creation: "configuration.waiting.project_creation",
};
/** D238 waiting reason `kind:id` (a job id may itself be `preparation:<id>`) as a catalog key and its identifier. */
export function waitingReason(reason: string): { key: MessageKey; id: string } {
  const [kind, ...rest] = reason.split(":");
  const id = rest.join(":");
  if (kind === "job" && id.startsWith("preparation:")) return { key: "configuration.waiting.preparation", id: id.slice(12) };
  return { key: WAITING[kind] ?? "configuration.waiting.other", id: id || reason };
}

export type LiveRefusal = S["LiveRefusalRead"];
/** One correction line of a refused live candidate: where (project or role/setting), the code and its diagnostic. */
export function refusalLine(item: LiveRefusal): string {
  const where = item.project ?? item.setting ?? item.role ?? "";
  return [where, item.code, item.diagnostic].filter(Boolean).join(" · ");
}
