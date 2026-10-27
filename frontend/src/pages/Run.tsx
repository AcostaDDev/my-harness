import { useEffect, useRef, useState } from "react";
import { useI18n } from "../Language";
import { managed, managedApi, jobRequest, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import { Link, navigate } from "../navigation";
import { Permissions } from "../Permissions";
import { href, runRoute } from "../router.ts";
import { Empty, Loading, message, usePoll } from "../ui";
import { RunEvidence } from "./RunEvidence";
import { LiveActivity } from "../Activity";
import { useWorkspace } from "../workspace";

/** `/runs/:id`: resolves the canonical run URL and replaces it in the history. */
export function RunRedirect({ run }: { run: string }) {
  const { t } = useI18n();
  const read = usePoll<S["ManagedRunRead"]>(`/runs/${encodeURIComponent(run)}`, 0);
  useEffect(() => {
    const route = read.data && runRoute(read.data);
    if (route) navigate(route, { replace: true });
  }, [read.data]);
  if (read.missing) return <Empty title={t("run.missing")}><p>{t("not_found.hint")} <Link to={{ name: "home" }}>{t("not_found.back")}</Link></p></Empty>;
  if (read.data && !read.data.project_id) return <Empty title={t("run.unregistered.title")}><p>{t("run.unregistered.body")}</p></Empty>;
  return read.error ? <p role="alert" className="state state-error">{read.error}</p> : <Loading>{t("run.searching")}</Loading>;
}

// With a job queued, running or pending recovery the run changes by itself; without one, it only changes through
// a new action (from this page, which rereads at once, or from another tab), so a spaced poll is enough.
const ACTIVE_POLL = 1500;
const SETTLED_POLL = 15000;

export function RunPage({ phase, task, run: id }: { phase: string; task: string; run: string }) {
  const { t, rich } = useI18n();
  const { project, busy, refresh, operate, send } = useWorkspace();
  const [run, setRun] = useState<S["ManagedRunRead"]>();
  const [jobs, setJobs] = useState<S["Page_ManagedJobRead_"]>();
  const [jobOffset, setJobOffset] = useState(0);
  const [attempts, setAttempts] = useState<S["Page_ManagedAttemptRead_"]>();
  const [offset, setOffset] = useState(0);
  const [cycles, setCycles] = useState<S["Page_CycleRead_"]>();
  const [cycleOffset, setCycleOffset] = useState(0);
  const [events, setEvents] = useState<S["ManagedEventRead"][]>([]);
  const [missing, setMissing] = useState(false);
  const cursor = useRef(0);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [commitConfirmed, setCommitConfirmed] = useState(false);
  const path = `/runs/${encodeURIComponent(id)}`;
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const [r, j, a, e, c] = await Promise.all([managed<S["ManagedRunRead"]>(path), managed<S["Page_ManagedJobRead_"]>(`${path}/jobs?offset=${jobOffset}`),
          managed<S["Page_ManagedAttemptRead_"]>(`${path}/attempts?offset=${offset}`), managed<S["ManagedEventsRead"]>(`${path}/events?after=${cursor.current}&limit=50`),
          managed<S["Page_CycleRead_"]>(`${path}/cycles?offset=${cycleOffset}`)]);
        if (active) {
          setRun(r); setJobs(j); setAttempts(a); setCycles(c); setError(""); cursor.current = e.cursor;
          setEvents(previous => [...previous, ...e.items.filter(item => !previous.some(old => old.sequence === item.sequence))]);
          timer = setTimeout(() => void poll(), e.has_more ? 0 : r.active_job === null ? SETTLED_POLL : ACTIVE_POLL);
        }
      } catch (e) {
        if (!active) return;
        if (e instanceof ManagedError && e.status === 404) setMissing(true);
        setError(message(e)); timer = setTimeout(() => void poll(), 3000);
      }
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [path, offset, jobOffset, cycleOffset, refresh]);
  useEffect(() => { setCommitConfirmed(false); setConfirmed(false); }, [run?.version]);
  // A URL with another phase, task or project is corrected to the canonical one without adding history.
  const canonical = run && runRoute(run);
  useEffect(() => {
    if (canonical && href(canonical) !== window.location.pathname) navigate(canonical, { replace: true });
  }, [canonical && href(canonical)]);
  if (missing && !run) return <Empty title={t("run.missing")}><p>{rich("run.back_to_task", { task: <Link className="mono" to={{ name: "task", project, phase, task }}>{task}</Link> })}</p></Empty>;
  if (!run) return error ? <p role="alert" className="state state-error">{error}</p> : <Loading>{t("run.loading")}</Loading>;
  const locked = run.locked_by_job !== null;
  const stale = !!error;
  function action(name: S["RunActionCreate"]["action"]) {
    void operate(() => send(jobRequest(`/runs/${run!.id}/actions`, { action: name, expected_version: run!.version })));
  }
  return <RunEvidence run={run} project={project} error={error} jobs={jobs} attempts={attempts} cycles={cycles}
    events={events} jobOffset={jobOffset} offset={offset} cycleOffset={cycleOffset}
    setJobOffset={setJobOffset} setOffset={setOffset} setCycleOffset={setCycleOffset}
    aside={<LiveActivity runId={run.id} version={run.version} status={run.status} refresh={refresh} />}
    decisions={run.purpose === "task" && ["revalidate", "retry_executor", "commit"].some(a => run.actions.includes(a as S["RunActionCreate"]["action"])) && <section className="decision decision-attention" aria-labelledby="run-decision">
      <h2 id="run-decision">{t("run.decision")}</h2>
      <div className="actions">
        <button className="button-quiet" disabled={busy || locked || stale || !run.actions.includes("revalidate")} onClick={() => action("revalidate")}>{t("run.revalidate")}</button>
        <button className="button-quiet" disabled={busy || locked || stale || !run.actions.includes("retry_executor")} onClick={() => { if (window.confirm(t("run.retry_confirm"))) action("retry_executor"); }}>{t("run.retry")}</button>
      </div>
      <label className="check"><input type="checkbox" checked={commitConfirmed} onChange={e => setCommitConfirmed(e.target.checked)} />{t("run.commit_confirm")}</label>
      <button disabled={busy || locked || stale || !commitConfirmed || !run.actions.includes("commit")} onClick={() => action("commit")}>{t("run.commit_submit")}</button>
    </section>}
    permissions={run.purpose === "task" && <Permissions run={run} busy={busy || stale} refresh={refresh} operate={operate} />}
    jobActions={job => job.status === "RECOVERY_REQUIRED" && <div className="decision decision-attention">
          <p>{t("run.recovery.lease")} {t(run.purpose === "bootstrap" ? "run.recovery.bootstrap" : run.purpose === "bootstrap_discovery" ? "run.recovery.discovery"
            : run.purpose === "document_export" ? "run.recovery.export" : "run.recovery.task")}</p>
          <label>{t("run.recovery.evidence")}<input value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} /></label>
          <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("run.recovery.confirm")}</label>
          <button disabled={busy || stale || !confirmed || !reason.trim() || !job.owner_token} onClick={() => void operate(async () => {
            await managedApi.confirm(job.id, { owner_token: job.owner_token!, expected_version: run.version, reason }); setConfirmed(false);
          })}>{t("run.recovery.submit")}</button>
        </div>} />;
}
