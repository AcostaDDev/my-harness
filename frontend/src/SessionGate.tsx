import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import type { components, operations } from "./api.generated";
import { useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";

type Session = components["schemas"]["SessionRead"];
// Messages are kept as keys: a notice shown before a language change is shown again in the new language.
type Notice = MessageKey | "";
type SessionControls = { logout: () => Promise<void>; busy: boolean; notice: Notice; expiresAt: number };

const SessionContext = createContext<SessionControls | null>(null);

/** Session controls for the header; only exists inside a started session. */
export function useSession(): SessionControls {
  const value = useContext(SessionContext);
  if (!value) throw new Error("Session missing");
  return value;
}

export function SessionGate({ children }: { children: ReactNode }) {
  const { t, refresh } = useI18n();
  const epoch = useRef(0);
  const [session, setSession] = useState<Session>();
  const [checking, setChecking] = useState(true);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Notice>("");
  const [expiresAt, setExpiresAt] = useState(0);
  const known = useRef(false);
  useEffect(() => { if (session) { known.current = true; setExpiresAt(Date.now() + session.expires_in * 1000); } }, [session]);
  useEffect(() => {
    let active = true;
    // Without a previous session on this page there is nothing to warn about: it is the normal sign-in.
    const expired = () => { epoch.current++; if (known.current) setError("session.expired_pending"); known.current = false; setSession(undefined); };
    window.addEventListener("harness-session-required", expired);
    const check = async () => {
      const version = epoch.current;
      try {
        const response = await fetch("/api/session");
        const observed = response.ok ? await response.json() as Session : undefined;
        if (!active || version !== epoch.current) return;
        if (observed) { setSession(observed); void refresh(); }
        else expired();
      } catch { if (active && version === epoch.current) { setSession(undefined); setError("session.check_failed"); } }
      finally { if (active) setChecking(false); }
    };
    // Each session check, also when the window regains focus, rereads the global preferences.
    const focused = () => { void check(); };
    void check();
    const timer = setInterval(() => { void check(); }, 15000);
    window.addEventListener("focus", focused);
    return () => { active = false; clearInterval(timer); window.removeEventListener("harness-session-required", expired); window.removeEventListener("focus", focused); };
  }, [refresh]);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(() => { epoch.current++; setSession(undefined); setError("session.expired"); }, session.expires_in * 1000);
    return () => clearTimeout(timer);
  }, [session]);
  async function login(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    epoch.current++;
    setBusy(true); setError("");
    const submitted: operations["start_session"]["requestBody"]["content"]["application/json"] = { key };
    setKey("");
    try {
      const response = await fetch("/api/session", { method: "POST",
        headers: { "Content-Type": "application/json", "X-My-Harness": "1" }, body: JSON.stringify(submitted) });
      if (!response.ok) { setError(response.status === 429 ? "session.rate_limited" : "session.login_failed"); return; }
      setSession(await response.json() as Session);
      void refresh();
    } catch { setError("session.login_failed"); }
    finally { epoch.current++; setBusy(false); }
  }
  async function logout() {
    if (busy) return;
    epoch.current++;
    setBusy(true);
    try {
      const response = await fetch("/api/session", { method: "DELETE", headers: { "X-My-Harness": "1" } });
      if (!response.ok && response.status !== 401) throw new Error();
      setSession(undefined); setError("session.closed");
    } catch { setError("session.logout_failed"); }
    finally { epoch.current++; setBusy(false); }
  }
  if (checking) return <main className="gate"><p role="status" className="state state-loading">{t("session.checking")}</p></main>;
  if (session) return <SessionContext.Provider value={{ logout, busy, notice: error, expiresAt }}>{children}</SessionContext.Provider>;
  return <main className="gate">
    <div className="gate-card">
      <p className="brand"><span className="brand-mark" aria-hidden="true" />My Harness</p>
      <h1>{t("session.title")}</h1>
      <p>{t("session.instructions")}</p>
      <form onSubmit={login}><label htmlFor="login-key">{t("session.key_label")}</label><input id="login-key" type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} maxLength={128} required disabled={busy} />
        <button className="button-primary" disabled={busy || !key}>{t("session.submit")}</button></form>
      {error && <p role="alert" className="state state-error">{t(error)}</p>}
    </div>
  </main>;
}
