import type { S } from "./managed-api";
import { managed, ManagedError } from "./managed-api";
import type { MessageKey } from "./i18n.ts";

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
  RESTART_REQUIRED: "configuration.mode.restart", RECOVERY_REQUIRED: "configuration.mode.recovery", READ_ONLY_ARCHIVE: "archive.title",
};
