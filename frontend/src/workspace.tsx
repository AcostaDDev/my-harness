import { createContext, useContext, useRef, useState } from "react";
import type { ReactNode } from "react";
import { managed, ManagedError, readPending, savePending } from "./managed-api";
import type { Pending, S } from "./managed-api";
import { useI18n } from "./Language";
import { navigate } from "./navigation";
import { runRoute } from "./router.ts";
import { Evidence, message } from "./ui";

// Project actions shared by its pages. A submission without an acknowledged response is kept
// with its key (also across reloads) and only repeated by explicit action (H2).
export type Workspace = {
  project: string;
  busy: boolean;
  refresh: number;
  operate: (action: () => Promise<unknown>) => Promise<void>;
  send: (request: Pending) => Promise<S["ManagedJobRead"]>;
};

const Context = createContext<Workspace | null>(null);

export function useWorkspace(): Workspace {
  const value = useContext(Context);
  if (!value) throw new Error("Workspace outside a project");
  return value;
}

export function ProjectWorkspace({ project, children }: { project: string; children: ReactNode }) {
  const { t } = useI18n();
  const [pending, setPending] = useState<Pending | undefined>(readPending);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const guard = useRef(false);
  function remember(value?: Pending) { savePending(value); setPending(value); }
  async function operate(action: () => Promise<unknown>) {
    if (guard.current) return;
    guard.current = true; setBusy(true); setError("");
    try { await action(); }
    catch (e) { setError(message(e)); }
    finally { guard.current = false; setBusy(false); setRefresh(n => n + 1); }
  }
  async function send(request: Pending) {
    remember(request);
    try {
      const job = await managed<S["ManagedJobRead"]>(request.path, request.body, request.key);
      remember();
      const run = await managed<S["ManagedRunRead"]>(`/runs/${job.run_id}`).catch(() => undefined);
      const route = run && runRoute(run);
      // Actions on an already open run do not change page; those that create one do.
      if (route && (request.path.endsWith("/runs") || request.path.endsWith("/batch/next"))) navigate(route);
      return job;
    } catch (e) {
      // A definitive rejection allows a new action after rereading the current version.
      if (e instanceof ManagedError && e.status >= 400 && e.status < 500 && e.status !== 401) remember();
      throw e;
    }
  }
  const value: Workspace = { project, busy: busy || !!pending, refresh, operate, send };
  return <Context.Provider value={value}>
    {error && <div className="toast" role="alert"><p>{error}</p>
      <button type="button" className="button-quiet" onClick={() => setError("")}>{t("workspace.dismiss")}</button></div>}
    {pending && <section className="decision decision-attention decision-pending" aria-labelledby="pending-title">
      <h2 id="pending-title">{t("workspace.pending.title")}</h2>
      <p>{t("workspace.pending.body")}</p>
      <Evidence title={t("workspace.pending.evidence")} value={pending} />
      <button type="button" disabled={busy} onClick={() => void operate(() => send(pending))}>{t("workspace.pending.repeat")}</button>
    </section>}
    {children}
  </Context.Provider>;
}
