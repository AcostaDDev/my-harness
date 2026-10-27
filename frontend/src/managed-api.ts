import { LocalizedError } from "./i18n.ts";
import { sessionResponse } from "./session.ts";
import type { components } from "./api.generated";
export type S = components["schemas"];
export class ManagedError extends Error {
  status: number;
  /** Stable code of the service problem (`detail.code`), when it sent one. */
  code?: string;
  /** Human diagnostic of the service, in the language it was emitted; absent when the service sent none. */
  diagnostic?: string;
  /** Structured corrections of a refused live configuration candidate (D238), when the service sent them. */
  details?: unknown[];
  constructor(status: number, message: string, code?: string, diagnostic?: string, details?: unknown[]) {
    super(message); this.status = status; this.code = code; this.diagnostic = diagnostic; this.details = details;
  }
}
export async function managed<T>(path: string, body?: unknown, key?: string, method = "POST"): Promise<T> {
  const response = await fetch(`/api/managed${path}`, body === undefined ? undefined : {
    method, headers: { "Content-Type": "application/json", "X-My-Harness": "1",
      ...(key ? { "Idempotency-Key": key } : {}) }, body: JSON.stringify(body),
  });
  sessionResponse(response);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    const diagnostic = typeof data?.detail?.diagnostic === "string" ? data.detail.diagnostic
      : data?.detail === undefined || data?.detail === null ? undefined : JSON.stringify(data.detail);
    // Without a diagnostic the message is the status and code only; the interface adds its own text.
    const code = data?.detail?.code ?? "request_failed";
    throw new ManagedError(response.status, `${response.status} · ${code}${diagnostic === undefined ? "" : `: ${diagnostic}`}`, data?.detail?.code, diagnostic,
      Array.isArray(data?.detail?.details) ? data.detail.details : undefined);
  }
  return response.json() as Promise<T>;
}
// Keep the exact request and key until an acknowledged response, including across reloads.
export type Pending = { path: string; body: S["RunCreate"] | S["RunActionCreate"] | S["PhaseCheckCreate"] | S["PhaseCloseCreate"] | S["PhaseBatchNextCreate"] | S["PhaseReconcileTaskCreate"]
  | S["ChatMessageCreate"] | S["ChatProposalAcceptCreate"] | S["DocumentExportCreate"]
  | S["DocumentEditCreate"] | S["PlanningMessageCreate"] | S["OnboardingConfirmCreate"] | S["DefinitionAcceptCreate"] | S["PhasePlanCreate"]; key: string };
const storageKey = "harness-managed-pending-v1";
export function readPending(): Pending | undefined {
  try { return JSON.parse(sessionStorage.getItem(storageKey) ?? "null") ?? undefined; } catch { return undefined; }
}
export function savePending(value?: Pending) {
  if (value) sessionStorage.setItem(storageKey, JSON.stringify(value));
  else sessionStorage.removeItem(storageKey);
}
export const managedApi = {
  confirm: (id: number, body: S["ConfirmStoppedCreate"]) => managed<S["ManagedRunRead"]>(`/jobs/${id}/confirm-stopped`, body),
};

// Reuse the last identical acknowledged request too: a fast response must not turn
// the second click into another job. A different body/version starts a new action.
export function jobRequest(path: string, body: Pending["body"]): Pending {
  const value = sessionStorage.getItem("harness-managed-last-request-v1");
  const previous: Pending | null = value ? JSON.parse(value) : null;
  if (previous?.path === path && JSON.stringify(previous.body) === JSON.stringify(body)) return previous;
  const request = { path, body, key: crypto.randomUUID() };
  sessionStorage.setItem("harness-managed-last-request-v1", JSON.stringify(request));
  return request;
}

// Creations without a job (conversations, D085): the key is kept while the same body has no acknowledged
// response, also across reloads; resending after losing the response returns the same conversation.
// After the response or a definitive rejection, the next submission carries another key and creates another.
const creationKey = "harness-managed-creation-v1";
export async function createOnce<T>(path: string, body: unknown): Promise<T> {
  const text = JSON.stringify(body);
  let saved: { path: string; body: string; key: string } | null = null;
  try { saved = JSON.parse(sessionStorage.getItem(creationKey) ?? "null"); } catch { /* no storage */ }
  const key = saved?.path === path && saved.body === text ? saved.key : crypto.randomUUID();
  const forget = () => { try { sessionStorage.removeItem(creationKey); } catch { /* no storage */ } };
  try { sessionStorage.setItem(creationKey, JSON.stringify({ path, body: text, key })); } catch { /* no storage */ }
  try {
    const created = await managed<T>(path, body, key);
    forget();
    return created;
  } catch (e) {
    if (e instanceof ManagedError && e.status >= 400 && e.status < 500 && e.status !== 401) forget();
    throw e;
  }
}

// Confirmations without a job: keep the whole envelope when the response is lost, also across reloads.
export type ConfirmationRequest = { path: string; body: unknown; key: string };
const confirmationKey = "harness-confirmation-v1";
export function readConfirmation(): ConfirmationRequest | undefined {
  try { return JSON.parse(sessionStorage.getItem(confirmationKey) ?? "null") ?? undefined; } catch { return undefined; }
}
export async function confirmOnce<T>(path: string, body: unknown): Promise<T> {
  const previous = readConfirmation();
  if (previous && (previous.path !== path || JSON.stringify(previous.body) !== JSON.stringify(body)))
    throw new LocalizedError("error.confirmation_pending");
  const request = previous ?? { path, body, key: crypto.randomUUID() };
  sessionStorage.setItem(confirmationKey, JSON.stringify(request));
  try {
    const result = await managed<T>(path, body, request.key);
    sessionStorage.removeItem(confirmationKey);
    return result;
  } catch (error) {
    if (error instanceof ManagedError && error.status >= 400 && error.status < 500 && error.status !== 401)
      sessionStorage.removeItem(confirmationKey);
    throw error;
  }
}
