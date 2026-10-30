import { StandingPermissions } from '../StandingPermissions';
import { useState } from "react";
import { useI18n } from "../Language";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { Empty, Loading, PageHeader, Pagination, PhaseRail, Stale, Status, Workbench, usePoll } from "../ui";
import { LatestActivity } from "../Activity";
import { useWorkspace } from "../workspace";
import { ProjectProfile } from "./ProjectProfile";
import { Preparation } from "./Preparation";
import { RunTable, TaskForm } from "./shared";

const OPEN: S["PhaseSummaryRead"]["status"][] = ["ACTIVE", "CHECKING", "READY_TO_CLOSE", "NEEDS_RECONCILIATION", "BLOCKED", "CLOSING"];
export function ProjectPage() {
  const { t, n, rich } = useI18n();
  const { project, refresh } = useWorkspace();
  const [offset, setOffset] = useState(0);
  const detail = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 10000, refresh);
  const mode = usePoll<S["ModeRead"]>(`/projects/${project}/mode`, 3000, refresh);
  const phases = usePoll<S["PhaseSummaryRead"][]>(`/projects/${project}/phases`, 3000, refresh);
  const runs = usePoll<S["Page_ManagedRunSummaryRead_"]>(`/projects/${project}/runs?offset=${offset}&limit=10`, 2000, refresh);
  if (detail.missing) return <Empty title={t("project.missing", { project })}><p>{t("not_found.hint")} <Link to={{ name: "home" }}>{t("not_found.back")}</Link></p></Empty>;
  const open = phases.data?.find(p => OPEN.includes(p.status));
  return <>
    <PageHeader code title={project}>
      {detail.data ? <p>{rich(detail.data.documents === "v2" ? "project.lede.v2" : "project.lede", { root: <code className="path">{detail.data.root}</code>, profile: detail.data.profile })}</p> : <Loading />}
    </PageHeader>
    <Stale error={detail.data ? detail.error ?? mode.error ?? phases.error ?? runs.error : undefined} />
    {mode.data?.refusal && <p className="state state-attention">{mode.data.refusal}</p>}
    <Workbench label={t("activity.rail")} aside={<LatestActivity query={`/projects/${project}/runs?limit=1`} refresh={refresh} title={t("activity.title.project")} empty={t("activity.no_runs.project")} />}>

    {detail.data?.versions.project_recipe && !!phases.data?.length && <Preparation />}

    {(detail.data?.versions.local_config === "local-config-9" || detail.data?.configuration_state === "PREPARATION_REQUIRED" || detail.data?.configuration_state === "READY_TO_ACTIVATE") && detail.data.configuration_state !== "PROFILE_REQUIRED" && <ProjectProfile />}

    <section className="panel" aria-labelledby="active-phase">
      <h2 id="active-phase">{t("project.open_phase")}</h2>
      {!phases.data ? <Loading /> : open ? <>
        <div className="phase-summary">
          <Link className="mono strong large" to={{ name: "phase", project, phase: open.code }}>{open.code}</Link>
          <Status kind="phase" value={open.status} />
        </div>
        <p>{open.objective}</p>
        <PhaseRail status={open.status} />
      </> : <Empty title={t("project.no_open_phase")}>
        <p>{phases.data.length ? `${n("project.closed_phases", phases.data.length)} ` : ""}{t("project.define_next")} <Link to={{ name: "phases", project }}>{t("nav.phases")}</Link></p>
      </Empty>}
    </section>

    <StandingPermissions />
    <section className="panel" aria-labelledby="recent-runs">
      <h2 id="recent-runs">{t("project.recent")}</h2>
      {runs.data ? <RunTable runs={runs.data.items} project={project} /> : <Loading />}
      <Pagination offset={offset} next={runs.data?.next_offset} onChange={setOffset} size={10} label={t("runs.pages")} />
    </section>

    {detail.data?.documents === "v2" && !phases.data?.length && <p><Link to={{ name: "onboarding", project }}>{t("project.onboard")}</Link></p>}
    {detail.data?.documents === "v2" && !phases.data?.length ? <Creation /> : detail.data?.configuration_state === "ACTIVE" ? <TaskForm /> : null}
    </Workbench>
  </>;
}

/** v2 project (H6.5/H6.2 E4): created through the definition conversation, on its own page. */
function Creation() {
  const { t } = useI18n();
  const { project, refresh } = useWorkspace();
  const status = usePoll<S["BootstrapStatusRead"]>(`/projects/${project}/bootstrap`, 5000, refresh);
  const op = status.data?.definition_operation;
  if (!status.data) return null;
  if (op?.status === "COMPLETED") return op.first_task_run ? <TaskForm /> : <section className="decision decision-attention" aria-labelledby="creation-title">
    <h2 id="creation-title">{t("project.created.title")}</h2>
    <p>{t("project.created.body")} <Link to={{ name: "setup", project }}>{t("project.creation.open")}</Link></p>
  </section>;
  if (!status.data.enabled && !op) return <TaskForm />;
  return <section className="decision decision-attention" aria-labelledby="creation-title">
    <h2 id="creation-title">{op ? t("project.creation.running") : t("project.creation.pending")}</h2>
    {status.data.import_required ? <p>{status.data.diagnostic}</p>
      : <p>{t("project.creation.body")}</p>}
    <p><Link to={{ name: "setup", project }}>{op ? t("project.creation.view") : t("project.creation.go")}</Link></p>
  </section>;
}
