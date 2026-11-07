// Read header of one invocation at `/projects/:p/invocations/:i` (T018 §4 L4 URL; P002-T022). Circles and steps
// open it so that their T020 targets never lead to a missing page. It shows only T020's existing L4 header read
// (identity, owning context, counters and the observed-step state) and links to the run evidence; the trace graph,
// its lazy history, related records and the documentation drawer are T023 and are not drawn here.
import { useState } from "react";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { Link } from "../navigation";
import type { Route } from "../router.ts";
import { Empty, Loading, MapStatusBadge, PageHeader, Stale, usePoll, when } from "../ui";
import { mapPaths } from "./api.ts";
import type { MapInvocation } from "./api.ts";
import { EvidenceLink, NotObserved, StepFields } from "./Inspector";
import { roleText } from "./projection.ts";

type Crumb = { level: string; id: string | null; role?: string | null; ordinal?: number | null };

function crumbRoute(project: string, crumb: Crumb, owner: MapInvocation["owner"]): Route | undefined {
  if (!crumb.id) return undefined;
  if (crumb.level === "project") return { name: "phases", project };
  if (crumb.level === "phase") return { name: "phase", project, phase: crumb.id };
  if (crumb.level === "task" && owner.phase) return { name: "task", project, phase: owner.phase, task: crumb.id };
  if (crumb.level === "run" && owner.phase && owner.task) return { name: "run", project, phase: owner.phase, task: owner.task, run: crumb.id };
  if (crumb.level === "chat") return { name: "chat", project, conversation: crumb.id };
  if (crumb.level === "phase_operation" && owner.phase) return { name: "phase", project, phase: owner.phase, section: "check" };
  return undefined;
}

export function InvocationPage({ project, invocation, archive }: { project: string; invocation: string; archive: boolean }) {
  const { t, n, language } = useI18n();
  const [refresh, setRefresh] = useState(0);
  // One bounded read; the archive never polls (`usePoll` has no timer there) and ordinary mode rereads on demand.
  const read = usePoll<MapInvocation>(mapPaths.invocation(project, invocation), 0, refresh);
  if (read.missing) return <><PageHeader title={t("map.invocation.title")} /><Empty title={t("map.invocation.missing")} /></>;
  if (!read.data) return read.error ? <Stale error={read.error} /> : <Loading />;
  const data = read.data;
  const head = data.invocation;
  const crumbs = data.owner.breadcrumb as Crumb[];
  // The run evidence of a managed attempt: the task's run page (list view) on the task lane, else the short run URL.
  const evidenceRun = head.lane === "managed_attempt" ? data.owner.run_id : null;
  const taskLane = data.owner.lane === "task";
  return <>
    <PageHeader title={t("map.invocation.heading", { role: roleText(head.role, t) })}>
      <p>{t("map.invocation.lede")}</p>
    </PageHeader>
    <Stale error={read.error} />
    <nav aria-label={t("map.invocation.owner")} className="map-owner">
      <ol>{crumbs.map((crumb, i) => {
        const to = crumbRoute(project, crumb, data.owner);
        const label = crumb.level === "invocation" ? `${roleText(crumb.role, t)}${crumb.ordinal ? ` #${crumb.ordinal}` : ""}`
          : `${t(`map.crumb.${crumb.level}` as MessageKey)}${crumb.id ? ` ${crumb.level === "run" ? crumb.id.slice(0, 8) : crumb.id}` : ""}`;
        return <li key={`${crumb.level}:${i}`}>{to && i < crumbs.length - 1 ? <Link to={to}>{label}</Link> : <span>{label}</span>}</li>;
      })}</ol>
    </nav>
    <section className="panel" aria-labelledby="invocation-head">
      <h2 id="invocation-head">{t("map.invocation.header")}</h2>
      <dl className="fields map-fields">
        <div><dt>{t("map.field.circle")}</dt><dd>{head.circle ?? t("map.role.unknown")}</dd></div>
        <div><dt>{t("map.field.lane")}</dt><dd><code>{head.lane}</code> · <code>{head.purpose}</code></dd></div>
        <div><dt>{t("map.field.launch")}</dt><dd><MapStatusBadge status={head.launch} /></dd></div>
        <div><dt>{t("map.field.outcome")}</dt><dd>{head.outcome ? <code>{head.outcome}</code> : <NotObserved />}</dd></div>
        {head.process && <div><dt>{t("map.field.process")}</dt><dd><code>{head.process}</code></dd></div>}
        <div><dt>{t("map.field.started")}</dt><dd>{when(head.started_at)}</dd></div>
        <div><dt>{t("map.field.finished")}</dt><dd>{when(head.finished_at)}</dd></div>
      </dl>
      {data.step && <StepFields step={data.step} project={project} texts={{ t, n, language }} />}
    </section>
    <section className="panel" aria-labelledby="invocation-steps">
      <h2 id="invocation-steps">{t("map.inspector.observed_steps")}</h2>
      <p><code>{data.steps.state}</code>{data.steps.reason && <> · <code>{data.steps.reason}</code></>} · {t(`map.steps_state.${data.steps.state}` as MessageKey)}</p>
      <p className="hint">{t("map.invocation.trace_later")}</p>
      {evidenceRun && <p><EvidenceLink project={project} run={evidenceRun} phase={taskLane ? data.owner.phase : null}
        task={taskLane ? data.owner.task : null} archive={archive} /></p>}
    </section>
    {!archive && <button type="button" className="button-quiet" onClick={() => setRefresh(value => value + 1)}>{t("map.invocation.reload")}</button>}
  </>;
}
