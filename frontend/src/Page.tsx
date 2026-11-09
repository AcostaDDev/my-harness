import { lazy, Suspense, useEffect } from "react";
import { AutonomousRun } from "./AutonomousRun";
import { InboxPage } from "./Inbox";
import { Chat } from "./Chat";
import { useI18n } from "./Language";
import { Link, navigate } from "./navigation";
import { ConfigurationPage } from "./pages/Configuration";
import { Home } from "./pages/Home";
import { PhaseListPage, PhasePage } from "./pages/Phases";
import { PreferencesPage } from "./pages/Preferences";
import { ProjectPage } from "./pages/Project";
import { RegisterPage } from "./pages/Registry";
import { RunPage, RunRedirect } from "./pages/Run";
import { SettingsPage } from "./pages/Settings";
import { TaskPage } from "./pages/Task";
import type { Route } from "./router.ts";
import { useServiceMode, useServiceError } from "./ServiceMode";
import { ArchiveBlocked, ArchiveHome, ArchiveRun } from "./pages/Archive";
import { Empty, Loading, PageHeader } from "./ui";
import { ProjectWorkspace, useWorkspace } from "./workspace";
import { InvocationPage } from "./map/InvocationPage";
import { MapLevelSwitch } from "./map/LevelSwitch";

// Documentation (markdown-it and, when drawing, Mermaid) is only downloaded when opened (H6.2 E3).
const KnowledgePage = lazy(() => import("./pages/Knowledge").then(module => ({ default: module.KnowledgePage })));
const DocsPage = lazy(() => import("./pages/Docs").then(module => ({ default: module.DocsPage })));
// Creation and planning (H6.2 E4) share the Markdown viewer: same lazy-loading rule.
const ImportPage = lazy(() => import("./pages/Planning").then(module => ({ default: module.ImportPage })));
const SetupPage = lazy(() => import("./pages/Planning").then(module => ({ default: module.SetupPage })));
const PlanPage = lazy(() => import("./pages/Planning").then(module => ({ default: module.PlanPage })));
// Statistics (H6.2 E6): charts and tables in their own chunk.
const StatsPage = lazy(() => import("./pages/Stats").then(module => ({ default: module.StatsPage })));
// Accounting (P001-T005a): calculated valuations over the accounting API, in its own chunk too.
const AccountingPage = lazy(() => import("./pages/Accounting").then(module => ({ default: module.AccountingPage })));
const AccountingInvocationPage = lazy(() => import("./pages/Accounting").then(module => ({ default: module.AccountingInvocationPage })));

function ProjectPageFor({ route }: { route: Exclude<Route, { name: "inbox" | "project-inbox" | "knowledge" | "home" | "stats" | "accounting" | "accounting-invocation" | "preferences" | "initial-setup" | "configuration" | "project-new" | "run-short" | "not-found" }> }) {
  const { t } = useI18n();
  switch (route.name) {
    case "project-knowledge": return null;
    case "project": return <ProjectPage />;
    // Map levels (P002-T022): the map, or the existing page with its controls one toggle away (`?view=list`).
    case "phases": return <MapLevelSwitch route={route} list={<PhaseListPage />} />;
    case "phase": return route.section === "check" ? <PhasePage key={route.phase} code={route.phase} checkOnly />
      : <MapLevelSwitch route={route} list={<PhasePage key={route.phase} code={route.phase} />} />;
    case "project-autonomous": return <><PageHeader title={t("autonomy.title")} /><AutonomousRun key={route.run} runId={route.run} /></>;
    case "task": return <MapLevelSwitch route={route} list={<TaskPage key={`${route.phase}/${route.task}`} phase={route.phase} task={route.task} />} />;
    case "run": return <MapLevelSwitch route={route} list={<RunPage key={route.run} phase={route.phase} task={route.task} run={route.run} />} />;
    case "invocation": return <InvocationPage key={route.invocation} project={route.project} invocation={route.invocation} archive={false} />;
    case "chat": return <Chat conversation={route.conversation} />;
    case "settings": return <SettingsPage />;
    case "project-stats": return <Suspense fallback={<Loading />}><ProjectStats /></Suspense>;
    case "project-accounting": return <Suspense fallback={<Loading />}><ProjectAccounting /></Suspense>;
    case "docs": return <Suspense fallback={<Loading />}><DocsPage path={route.path} /></Suspense>;
    case "onboarding": return <Suspense fallback={<Loading />}><ImportPage conversation={route.conversation} path={route.path} /></Suspense>;
    case "setup": return <Suspense fallback={<Loading />}><SetupPage path={route.path} /></Suspense>;
    case "plan": return <Suspense fallback={<Loading />}><PlanPage key={route.phase} phase={route.phase} conversation={route.conversation} /></Suspense>;
  }
}

function ProjectStats() {
  const { project, refresh } = useWorkspace();
  return <StatsPage project={project} refresh={refresh} />;
}

function ProjectAccounting() {
  const { project, refresh } = useWorkspace();
  return <AccountingPage project={project} refresh={refresh} />;
}

export function Page({ route }: { route: Route }) {
  const { t } = useI18n();
  const mode = useServiceMode();
  const error = useServiceError();
  if (!mode) return error ? <p role="alert" className="state state-error">{error}</p> : <Loading />;
  if (route.name === "knowledge" || route.name === "project-knowledge") return <Suspense fallback={<Loading />}><KnowledgePage key={route.name === "knowledge" ? "read" : route.project} project={route.name === "project-knowledge" && !mode.read_only_archive && (!mode.configuration_mode || mode.configuration_mode === "READY") ? route.project : undefined} /></Suspense>;
  if (route.name === "inbox" || route.name === "project-inbox") {
    const scope = route.name === "project-inbox" ? route.project : undefined;
    return <InboxPage key={scope ?? "global"} project={scope} item={route.name === "project-inbox" ? route.item : undefined}
      canRespond={!mode.read_only_archive && (!mode.configuration_mode || mode.configuration_mode === "READY")} />;
  }
  if (route.name === "accounting-invocation") return <Suspense fallback={<Loading />}>
    <AccountingInvocationPage key={route.invocation} invocation={route.invocation} />
  </Suspense>;
  // Archives resolve before any workspace or pending-action handling: the map levels and their table read SQLite
  // projections only; every operational page stays blocked.
  if (mode.read_only_archive) {
    switch (route.name) {
      case "home": return <ArchiveHome />;
      case "phases": case "task": case "run": return <MapLevelSwitch route={route} />;
      case "phase": return route.section ? <ArchiveBlocked /> : <MapLevelSwitch route={route} />;
      case "invocation": return <InvocationPage key={route.invocation} project={route.project} invocation={route.invocation} archive />;
      case "run-short": return <ArchiveRun key={route.run} run={route.run} />;
      case "stats": return <Suspense fallback={<Loading />}><StatsPage /></Suspense>;
      case "accounting": return <Suspense fallback={<Loading />}><AccountingPage /></Suspense>;
      default: return <ArchiveBlocked />;
    }
  }
  if (mode.configuration_mode && mode.configuration_mode !== "READY") {
    // Consultation remains available without a project action workspace while setup closes admission.
    if (route.name === "run-short" || route.name === "run") return <ArchiveRun key={route.run} run={route.run} />;
    if (!["preferences", "initial-setup", "configuration", "stats", "accounting"].includes(route.name)) return <ConfigurationRedirect />;
  }
  switch (route.name) {
    case "initial-setup":
    case "configuration": return <ConfigurationPage />;
    case "home": return <MapLevelSwitch route={route} list={<Home />} />;
    case "preferences": return <PreferencesPage />;
    case "stats": return <Suspense fallback={<Loading />}><StatsPage /></Suspense>;
    case "accounting": return <Suspense fallback={<Loading />}><AccountingPage /></Suspense>;
    case "project-new": return <RegisterPage />;
    case "run-short": return <RunRedirect run={route.run} />;
    case "not-found": return <>
      <PageHeader title={t("not_found.title")} />
      <Empty title={t("not_found.empty", { path: route.path })}><p>{t("not_found.hint")} <Link to={{ name: "home" }}>{t("not_found.back")}</Link></p></Empty>
    </>;
  }
  // Each project has its own action workspace; switching projects resets it.
  return <ProjectWorkspace key={route.project} project={route.project}><ProjectPageFor route={route} /></ProjectWorkspace>;
}

function ConfigurationRedirect() {
  useEffect(() => { navigate({ name: "initial-setup" }, { replace: true }); }, []);
  return <Loading />;
}
