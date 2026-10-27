import { lazy, Suspense, useState } from "react";
import { useI18n } from "../Language";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { PhaseCreate, PhaseDetail } from "../Phases";
import { Empty, Loading, PageHeader, Pagination, PhaseRail, Stale, Status, usePoll, when } from "../ui";
import { useWorkspace } from "../workspace";
import { TaskForm } from "./shared";

const PhasePlanPanel = lazy(() => import("./Planning").then(module => ({ default: module.PhasePlanPanel })));

export function PhaseListPage() {
  const { t } = useI18n();
  const { project, refresh } = useWorkspace();
  const phases = usePoll<S["PhaseSummaryRead"][]>(`/projects/${project}/phases`, 3000, refresh);
  const open = phases.data?.some(p => !["CLOSED", "ABANDONED"].includes(p.status));
  return <>
    <PageHeader title={t("nav.phases")}><p>{t("phases.lede")}</p></PageHeader>
    <Stale error={phases.data ? phases.error : undefined} />
    {!phases.data ? <Loading /> : !phases.data.length ? <Empty title={t("phases.empty.title")}>
      <p>{t("phases.empty.body")}</p></Empty>
      : <div className="table-scroll" role="region" aria-label={t("phases.table")} tabIndex={0}>
        <table className="table">
          <thead><tr><th scope="col">{t("runs.column.phase")}</th><th scope="col">{t("phase.field.objective")}</th><th scope="col">{t("runs.column.status")}</th><th scope="col">{t("runs.column.updated")}</th></tr></thead>
          <tbody>{[...phases.data].reverse().map(p => <tr key={p.id}>
            <td><Link className="mono strong" to={{ name: "phase", project, phase: p.code }}>{p.code}</Link></td>
            <td className="wide">{p.objective}</td>
            <td><Status kind="phase" value={p.status} /></td>
            <td>{when(p.updated_at)}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    {phases.data && !open && <PhaseCreate />}
  </>;
}

export function PhasePage({ code }: { code: string }) {
  const { t, rich } = useI18n();
  const { project, refresh } = useWorkspace();
  const [offset, setOffset] = useState(0);
  const base = `/projects/${project}/phases/${encodeURIComponent(code)}`;
  const phase = usePoll<S["PhaseRead"]>(base, 1500, refresh);
  const tasks = usePoll<S["Page_PhaseTaskRead_"]>(`${base}/tasks?offset=${offset}`, 2000, refresh);
  const info = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 0);
  const phases = usePoll<S["PhaseSummaryRead"][]>(`/projects/${project}/phases`, 5000, refresh);
  const data = phase.data;
  const v2 = info.data?.documents === "v2";
  // The next phase in the checkout (the list is in creation order); null if this is the last one.
  const index = phases.data?.findIndex(p => p.code === code) ?? -1;
  const following = phases.data && index >= 0 ? phases.data[index + 1]?.code ?? null : undefined;
  const undefinedPhase = phase.missing && !!tasks.data;
  const open = data && !["CLOSED", "ABANDONED"].includes(data.status);
  if (phase.missing && tasks.data && !tasks.data.items.length && !offset) return <>
    <PageHeader code title={code} />
    <Empty title={t("phases.missing.title", { phase: code })}>
      <p>{t("phases.missing.body")} <Link to={{ name: "phases", project }}>{t("phases.missing.back")}</Link></p>
    </Empty>
  </>;
  return <>
    <PageHeader code title={code} aside={data && <Status kind="phase" value={data.status} />}>
      {data ? <p>{String(data.definition.objective)}</p> : undefinedPhase ? <p>{t("phases.undefined")}</p> : <Loading />}
    </PageHeader>
    <Stale error={data ? phase.error : undefined} />
    {data && <PhaseRail status={data.status} />}
    <section className="panel" aria-labelledby="phase-tasks">
      <h2 id="phase-tasks">{t("stats.tasks")}</h2>
      {!tasks.data ? <Loading /> : !tasks.data.items.length ? <Empty title={t("phases.tasks.empty")}>
        <p>{data ? `${t("phases.tasks.none_defined")} ` : ""}{t("phases.tasks.queue_first")}</p></Empty>
        : <div className="table-scroll" role="region" aria-label={t("phases.tasks.table")} tabIndex={0}>
          <table className="table">
            <thead><tr><th scope="col">{t("runs.column.task")}</th><th scope="col">{t("phases.column.planned")}</th><th scope="col">{t("phases.column.latest")}</th><th scope="col" className="numeric">{t("runs.table")}</th><th scope="col">{t("phases.column.commit")}</th></tr></thead>
            <tbody>{tasks.data.items.map(task => {
              const commit = data?.tasks[task.task_id];
              return <tr key={task.task_id}>
                <td><Link className="mono strong" to={{ name: "task", project, phase: code, task: task.task_id }}>{task.task_id}</Link></td>
                <td>{task.planned ? t("common.yes") : t("common.no")}</td>
                <td>{task.latest ? <Status value={task.latest.status} /> : <span className="muted">{t("phases.no_runs")}</span>}</td>
                <td className="numeric">{task.runs}</td>
                <td>{commit?.commit ? <code className="hash" title={commit.commit}>{commit.commit.slice(0, 12)}</code> : <span className="muted">{data ? t("phases.commit.pending") : t("phases.commit.not_applicable")}</span>}</td>
              </tr>;
            })}</tbody>
          </table>
        </div>}
      <Pagination offset={offset} next={tasks.data?.next_offset} onChange={setOffset} label={t("stats.pages.tasks")} />
    </section>
    {(open || undefinedPhase) && <TaskForm phase={code} title={t("phases.queue")} />}
    {data && v2 && data.status === "ACTIVE" && !(data.definition.tasks as string[]).length
      && <Suspense fallback={<Loading />}><PhasePlanPanel key={data.id} phase={data} stale={!!phase.error} /></Suspense>}
    {data && following && <p className="hint">{rich("phases.following", { phase: <Link to={{ name: "phase", project, phase: following }}>{following}</Link> })}</p>}
    {data && <PhaseDetail phase={data} stale={!!phase.error} />}
  </>;
}
