import { memo, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { appendDiffPage, byteSize } from "../diff.ts";
import type { LoadedDiff } from "../diff.ts";
import { useI18n } from "../Language";
import { Logs } from "../Logs";
import { ROLES } from "../metrics.ts";
import { managed } from "../managed-api";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { Tests } from "../Tests";
import { DiffLines, Evidence, Fields, Hash, Loading, PageHeader, Pagination, Stale, Status, message, when } from "../ui";

type Props = {
  run: S["ManagedRunRead"]; project?: string; error?: string;
  jobs?: S["Page_ManagedJobRead_"]; attempts?: S["Page_ManagedAttemptRead_"]; cycles?: S["Page_CycleRead_"];
  events?: S["ManagedEventRead"][];
  jobOffset: number; offset: number; cycleOffset: number;
  setJobOffset: (n: number) => void; setOffset: (n: number) => void; setCycleOffset: (n: number) => void;
  decisions?: ReactNode; permissions?: ReactNode; jobActions?: (job: S["ManagedJobRead"]) => ReactNode;
};

/** Shared evidence presentation. Operational controls are supplied only by RunPage. */
export function RunEvidence({ run, project, error, jobs, attempts, cycles, events,
  jobOffset, offset, cycleOffset, setJobOffset, setOffset, setCycleOffset, decisions, permissions, jobActions }: Props) {
  const { t, n, rich } = useI18n();
  const documentRun = run.purpose === "document_export" || run.purpose === "bootstrap";
  const outcome = documentRun ? (run.purpose === "bootstrap" ? t("run.outcome.bootstrap") : t("run.outcome.export"))
    : run.status === "COMMITTED" ? t("run.outcome.committed")
      : run.history.acceptance?.eligible ? t("run.outcome.eligible") : t("run.outcome.none");
  return <>
    <PageHeader code title={t("trail.run", { id: run.id.slice(0, 8) })} aside={<Status value={run.status} />}>
      <p>{rich("run.lede", { task: (project ? <Link className="mono" to={{ name: "task", project, phase: run.phase_id, task: run.task_id }}>{run.task_id}</Link> : <code>{run.task_id}</code>),
        phase: (project ? <Link className="mono" to={{ name: "phase", project, phase: run.phase_id }}>{run.phase_id}</Link> : <code>{run.phase_id}</code>) })} {outcome}</p>
    </PageHeader>
    {!project && <p className="path"><code>{run.root}</code></p>}
    <Stale error={error} />
    {run.history.stop && <p className="state state-attention">{t("run.stop", { stage: run.history.stop.stage, reason: run.history.stop.reason })}</p>}

    <section className="panel" aria-labelledby="run-summary">
      <h2 id="run-summary">{t("stats.summary")}</h2>
      <Fields items={[
        [t("stats.column.stage"), run.stage], [t("phase.observed_version"), `${run.version}`], [t("stats.revisions"), t("runs.revisions", { count: run.revisions, limit: run.revision_limit })],
        [t("run.commit"), run.commit ? <><Status value={run.commit.status} /> <Hash value={run.commit.commit ?? run.commit.expected_commit} /></> : <span className="muted">{t("stats.no_commit")}</span>],
        [t("run.created"), when(run.created_at)], [t("tests.identifier"), <code>{run.id}</code>],
      ]} />
      {!documentRun && <p className="hint">{t("run.checkpoint")}</p>}
      {typeof run.history.task?.additional_notes === "string" && <div className="entry"><h3>{t("run.notes")}</h3><p className="turn-answer">{run.history.task.additional_notes}</p></div>}
      <Evidence title={t("run.history_evidence")} value={run.history} />
      <Evidence title={t("run.commit_evidence")} value={{ commit: run.commit, versions: run.versions }} />
    </section>

    {decisions}

    {run.history.cycle_count > 0 && <section className="panel" aria-labelledby="run-cycles">
      <h2 id="run-cycles">{t("stats.revisions")} <span className="count">{run.history.cycle_count}</span></h2>
      {!cycles && <p className="hint">{t("common.not_recorded")}</p>}
      {cycles?.items.map(c => <div className="entry" key={c.number}>
        <h3>{t("run.cycle", { number: c.number, verdict: c.verdict ?? t("run.no_verdict") })}</h3>
        <CycleDiff runId={run.id} number={c.number} sha256={c.diff_sha256} bytes={c.diff_bytes} paths={c.changed_paths.length} />
        <Tests runId={run.id} cycle={c.number} validation={c.validation} />
        {c.formatting && <Evidence title={n("run.formatting", (c.formatting.paths as string[] | undefined)?.length ?? 0)} value={c.formatting} />}
        <Evidence title={t("run.validation_evidence")} value={c.validation} /><Evidence title={t("run.review_evidence")} value={c.review} />
      </div>)}
      <Pagination offset={cycleOffset} next={cycles?.next_offset} onChange={setCycleOffset} size={10} label={t("run.pages.cycles")} />
    </section>}

    {permissions}

    <section className="panel" aria-labelledby="run-jobs">
      <h2 id="run-jobs">{t("run.jobs")}</h2>
      {!jobs && <p className="hint">{t("common.not_recorded")}</p>}
      {jobs && !jobs.items.length && <p className="hint">{t("run.jobs.empty")}</p>}
      {jobs?.items.map(job => <div key={job.id} className={job.status === "RECOVERY_REQUIRED" ? "entry entry-open" : "entry"}>
        <p><strong>{t("run.job", { id: job.id })}</strong> {job.action} <Status value={job.status} /></p>
        {job.diagnostic && <p>{job.diagnostic}</p>}
        {jobActions?.(job)}
        <Evidence title={t("run.job.evidence", { id: job.id })} value={job} />
      </div>)}
      <Pagination offset={jobOffset} next={jobs?.next_offset} onChange={setJobOffset} label={t("run.pages.jobs")} />
    </section>

    <section className="panel" aria-labelledby="run-attempts">
      <h2 id="run-attempts">{t("stats.attempts.title")}</h2>
      {!attempts && <p className="hint">{t("common.not_recorded")}</p>}
      {attempts && !attempts.items.length && <p className="hint">{t("run.attempts.empty")}</p>}
      {attempts?.items.map(a => <div className="entry" key={a.id}>
        <p><strong>{t("run.attempt", { number: a.number })}</strong> {ROLES[a.role] ? t(ROLES[a.role]) : a.role} <Status value={a.status} /></p>
        <Logs runId={run.id} attemptId={a.id} />
        <Evidence title={t("run.attempt.evidence")} value={a} /></div>)}
      <Pagination offset={offset} next={attempts?.next_offset} onChange={setOffset} label={t("stats.pages.attempts")} />
    </section>

    <details className="panel panel-collapsible">
      <summary><h2>{t("run.events")} <span className="count">{events?.length ?? "—"}</span></h2></summary>
      {!events && <p className="hint">{t("common.not_recorded")}</p>}
      <ol className="events">{events?.map(e => <li key={e.sequence}><p><strong>{e.sequence}</strong> {e.kind} {when(e.recorded_at)}</p><Evidence title={t("run.event.evidence")} value={e.payload} /></li>)}</ol>
    </details>
  </>;
}

/**
 * Reviewed diff of a cycle: read when opened, in 64 KiB pages bound to the hash of the run summary, and not
 * requested again on every poll. A page that does not continue what is shown discards it instead of mixing it.
 * Scalar props and memo: polling the run does not repaint a diff of thousands of lines; each page is its chunk.
 */
const CycleDiff = memo(function CycleDiff({ runId, number, sha256, bytes, paths }: { runId: string; number: number; sha256: string; bytes: number; paths: number }) {
  const { t, n, language } = useI18n();
  const [diff, setDiff] = useState<LoadedDiff>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(0);
  useEffect(() => { request.current++; setDiff(undefined); setError(""); setLoading(false); }, [runId, number, sha256]);
  async function more(current?: LoadedDiff) {
    const id = ++request.current;
    setLoading(true); setError("");
    try {
      const page = await managed<S["CycleDiffRead"]>(`/runs/${encodeURIComponent(runId)}/cycles/${number}/diff?offset=${current?.next ?? 0}&sha256=${sha256}`);
      if (id !== request.current) return;
      const next = appendDiffPage(current, page);
      setDiff(next ?? undefined);
      if (!next) setError(t("run.diff.discontinuous"));
    } catch (e) {
      if (id === request.current) setError(message(e));
    } finally {
      if (id === request.current) setLoading(false);
    }
  }
  return <details className="evidence" onToggle={e => { if (e.currentTarget.open && !diff && !loading) void more(); }}>
    <summary>{t("run.diff.summary", { paths: n("run.diff.paths", paths), size: byteSize(bytes, language) })}</summary>
    {diff && (diff.size ? <pre className="diff" aria-label={t("run.diff.label", { number })}>{diff.pages.map((page, index) => <DiffLines key={index} text={page} />)}</pre>
      : <p className="hint">{t("prompts.no_diff")}</p>)}
    {loading && <Loading>{t("run.diff.loading")}</Loading>}
    {error && <p role="alert" className="state state-error">{error}</p>}
    {diff && diff.size > 0 && <p className="hint">{diff.next === null ? t("run.diff.complete") : t("stats.of", { part: byteSize(diff.loaded, language), whole: byteSize(diff.size, language) })} · <Hash value={diff.sha256} /></p>}
    {(diff?.next != null || (error && !loading)) && <button type="button" className="button-quiet" disabled={loading} onClick={() => void more(diff)}>
      {diff ? t("run.diff.more") : t("run.diff.load")}</button>}
  </details>;
});
