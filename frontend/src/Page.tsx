import { lazy, Suspense, useEffect } from "react";
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

function ProjectPageFor({ route }: { route: Exclude<Route, { name: "knowledge" | "home" | "stats" | "accounting" | "preferences" | "initial-setup" | "configuration" | "project-new" | "run-short" | "not-found" }> }) {
  switch (route.name) {
    case "project-knowledge": return null;
    case "project": return <ProjectPage />;
    case "phases": return <PhaseListPage />;
    case "phase": return <PhasePage key={route.phase} code={route.phase} />;
    case "task": return <TaskPage key={`${route.phase}/${route.task}`} phase={route.phase} task={route.task} />;
    case "run": return <RunPage key={route.run} phase={route.phase} task={route.task} run={route.run} />;
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
  if (mode.read_only_archive) {
    switch (route.name) {
      case "home": return <ArchiveHome />;
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
    case "home": return <Home />;
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
