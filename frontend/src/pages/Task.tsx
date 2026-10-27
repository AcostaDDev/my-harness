import { lazy, Suspense, useState } from "react";
import { useI18n } from "../Language";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { Empty, Loading, PageHeader, Pagination, Stale, Status, Workbench, usePoll } from "../ui";
import { LatestActivity } from "../Activity";
import { useWorkspace } from "../workspace";
import { RunTable, TaskForm } from "./shared";

// Task metrics (H6.2 E6): same lazy chunk as the statistics.
const TaskMetrics = lazy(() => import("./Stats").then(module => ({ default: module.TaskMetrics })));

export function TaskPage({ phase, task }: { phase: string; task: string }) {
  const { t, rich } = useI18n();
  const { project, refresh } = useWorkspace();
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({ phase, task, offset: String(offset) });
  const runs = usePoll<S["Page_ManagedRunSummaryRead_"]>(`/projects/${project}/runs?${query}`, 2000, refresh);
  const latest = runs.data?.items[0];
  return <>
    <PageHeader code title={task} aside={latest && !offset ? <Status value={latest.status} /> : undefined}>
      <p>{rich("task.lede", { phase: <Link className="mono" to={{ name: "phase", project, phase }}>{phase}</Link> })}</p>
    </PageHeader>
    <Stale error={runs.data ? runs.error : undefined} />
    <Workbench label={t("activity.rail")} aside={<LatestActivity query={`/projects/${project}/runs?${new URLSearchParams({ phase, task, limit: "1" })}`} refresh={refresh}
      title={t("activity.title.latest")} empty={t("activity.no_runs.task")} />}>
    <section className="panel" aria-labelledby="task-runs">
      <h2 id="task-runs">{t("runs.table")}</h2>
      {!runs.data ? <Loading /> : !runs.data.items.length && !offset
        ? <Empty title={t("task.empty.title")}><p>{t("task.empty.body")}</p></Empty>
        : <RunTable runs={runs.data.items} project={project} show={[]} />}
      <Pagination offset={offset} next={runs.data?.next_offset} onChange={setOffset} label={t("runs.pages")} />
    </section>
    {latest && <Suspense fallback={<Loading />}><TaskMetrics project={project} phase={phase} task={task} refresh={refresh} /></Suspense>}
    <TaskForm phase={phase} task={task} title={latest ? t("task.queue_again") : t("task.queue")} />
    </Workbench>
  </>;
}
