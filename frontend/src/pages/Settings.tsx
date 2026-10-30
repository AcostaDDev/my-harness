import { useState, type ReactNode } from "react";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import type { S } from "../managed-api";
import { Prompts } from "../Prompts";
import { Fields, Loading, PageHeader, Stale, usePoll } from "../ui";
import { RegistrySettings } from "./Registry";
import { WorkLanguageSettings } from "../WorkLanguage";
import { useWorkspace } from "../workspace";
import { ProjectProfile } from "./ProjectProfile";

const SELECTION: Record<"catalog" | "open", MessageKey> = { catalog: "settings.selection.catalog", open: "settings.selection.open" };
const PLANNING: Record<"auto" | "agent" | "deterministic", MessageKey> = {
  auto: "settings.planning.auto", agent: "settings.planning.agent", deterministic: "settings.planning.deterministic",
};

/** Effective settings; per-project selection through the V5 registry and operator presets (D116). */
export function SettingsPage() {
  const { t, rich } = useI18n();
  const { project } = useWorkspace();
  const [revision, setRevision] = useState(0);
  const read = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 15000, revision);
  const p = read.data;
  return <>
    <PageHeader title={t("nav.settings")}><p>{t("settings.lede")}</p></PageHeader>
    <Stale error={p ? read.error : undefined} />
    {!p ? <Loading /> : <>
      <section className="panel" aria-labelledby="settings-agents">
        <h2 id="settings-agents">{t("settings.agents")}</h2>
        <div className="agents">
          <div><h3>{t("settings.reviewer")}</h3><Fields items={[
            [t("settings.provider"), p.agents.reviewer.provider ?? t("common.undeclared")], [t("settings.model"), <code>{p.agents.reviewer.model}</code>], [t("settings.effort"), p.agents.reviewer.effort],
            ...(p.agents.planner.model !== p.agents.reviewer.model || p.agents.planner.effort !== p.agents.reviewer.effort
              ? [[t("settings.planner"), rich("settings.planner_value", { model: <code>{p.agents.planner.model}</code>, effort: p.agents.planner.effort })] as [string, ReactNode]] : []),
          ]} /></div>
          {p.agents.judge && <div><h3>{t("settings.judge")}</h3><Fields items={[
            [t("settings.provider"), p.agents.judge.provider ?? t("common.undeclared")],
            [t("settings.model"), p.agents.judge.model], [t("settings.effort"), p.agents.judge.effort],
          ]} /></div>}
          <div><h3>{t("settings.executor")}</h3><Fields items={[
            [t("settings.provider"), p.agents.executor.provider ?? t("common.undeclared")], [t("settings.selection"), t(SELECTION[p.agents.executor.selection_mode])],
            [t("settings.models"), p.agents.executor.models.map(m => <code key={m} className="chip">{m}</code>)], [t("settings.efforts"), p.agents.executor.efforts.join(", ")],
          ]} /></div>
        </div>
        <Fields items={[[t("settings.planning"), t(PLANNING[p.agents.planning_mode])]]} />
      </section>
      <section className="panel" aria-labelledby="settings-project">
        <h2 id="settings-project">{t("settings.project")}</h2>
        <p>{rich("settings.checkout", { root: <code className="path">{p.root}</code> })}</p>
        <p className="hint">{p.source === "registry" ? t("settings.source.registry", { version: p.registry_version ?? "" }) : t("settings.source.toml")}</p>
        <Fields items={[
          [t("settings.profile"), p.profile],
          [t("settings.documents"), p.documents === "v2" ? t("settings.documents.v2") : t("settings.documents.legacy")],
          [t("settings.tag"), p.tag_kind === "annotated" ? t("settings.tag.annotated") : t("settings.tag.lightweight")],
          [t("settings.bootstrap"), p.bootstrap_enabled ? t("settings.bootstrap.allowed") : t("common.no")],
        ]} />
        <h3>{t("settings.versions")}</h3>
        <Fields items={Object.entries(p.versions).map(([k, v]) => [k, v === null ? <span className="muted">{t("common.not_recorded")}</span> : <code>{v}</code>])} />
      </section>
      {/* OT004: the project's own profile, commands and agents, with the same save/preparation/activation gates. */}
      {(p.versions.local_config === "local-config-9" || p.configuration_state === "PREPARATION_REQUIRED" || p.configuration_state === "READY_TO_ACTIVATE")
        && p.configuration_state !== "PROFILE_REQUIRED" && <ProjectProfile />}
      <WorkLanguageSettings project={project} work={p.work_language} onChanged={() => setRevision(n => n + 1)} />
      {p.source === "registry" && <RegistrySettings project={project} onChanged={() => setRevision(n => n + 1)} />}
      <Prompts project={project} />
    </>}
  </>;
}
