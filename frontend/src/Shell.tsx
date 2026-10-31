import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";
import { Link } from "./navigation";
import { href, trail } from "./router.ts";
import type { Route } from "./router.ts";
import { useSession } from "./SessionGate";
import { useArchive, useServiceMode, useServiceError } from "./ServiceMode";
import { modeLabels } from "./configuration.ts";

type Theme = "system" | "light" | "dark";
const THEMES: Record<Theme, MessageKey> = { system: "shell.theme.system", light: "shell.theme.light", dark: "shell.theme.dark" };
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };

// Preference of this browser; if storage is unavailable, it follows the system.
function storedTheme(): Theme {
  try { const value = localStorage.getItem("harness-theme"); return value === "light" || value === "dark" ? value : "system"; }
  catch { return "system"; }
}

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useEffect(() => {
    if (theme === "system") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try { if (theme === "system") localStorage.removeItem("harness-theme"); else localStorage.setItem("harness-theme", theme); } catch { /* no saved preference */ }
  }, [theme]);
  return [theme, () => setTheme(NEXT[theme])];
}

function Supervisor() {
  const { t } = useI18n();
  const s = useServiceMode();
  const error = useServiceError();
  const [label, tone]: [MessageKey, string] = error && !s ? ["shell.supervisor.unreachable", "danger"] : !s ? ["shell.supervisor.connecting", "neutral"]
    : s.read_only_archive ? ["archive.title", "neutral"]
      : s.configuration_mode && s.configuration_mode !== "READY" ? [modeLabels[s.configuration_mode as keyof typeof modeLabels] ?? "configuration.status", "attention"]
      : !s.ports_configured ? ["shell.supervisor.read_only", "neutral"]
        : s.alive ? ["shell.supervisor.active", "ok"] : ["shell.supervisor.stopped", "attention"];
  return <span className={`status status-${tone}`} title={s?.last_error ?? error}>
    <span className="status-mark" aria-hidden="true" />{error && s ? t("shell.supervisor.stale", { status: t(label) }) : t(label)}</span>;
}

function SessionControls() {
  const { t, language } = useI18n();
  const { logout, busy, notice, expiresAt } = useSession();
  const until = new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit" }).format(expiresAt);
  return <div className="session">
    <span className="muted" title={t("session.until_hint")}>{t("session.until", { time: until })}</span>
    <button type="button" className="button-quiet" disabled={busy} onClick={() => void logout()}>{t("session.logout")}</button>
    {notice && <p role="alert" className="session-notice">{t(notice)}</p>}
  </div>;
}

function ProjectNav({ route, project }: { route: Route; project: string }) {
  const { t } = useI18n();
  const items: [MessageKey, Route, boolean][] = [
    ["nav.summary", { name: "project", project }, route.name === "project"],
    ["nav.phases", { name: "phases", project }, ["phases", "phase", "task", "run"].includes(route.name)],
    ["knowledge.title", { name: "project-knowledge", project }, route.name === "project-knowledge"],
    ["nav.docs", { name: "docs", project }, route.name === "docs"],
    ["nav.chat", { name: "chat", project }, route.name === "chat"],
    ["nav.stats", { name: "project-stats", project }, route.name === "project-stats"],
    ["nav.accounting", { name: "project-accounting", project }, route.name === "project-accounting"],
    ["nav.settings", { name: "settings", project }, route.name === "settings"],
  ];
  return <div className="nav-group">
    <p className="nav-project mono" title={project}>{project}</p>
    <ul>{items.map(([label, to, current]) => <li key={label}><Link to={to} current={current}>{t(label)}</Link></li>)}</ul>
  </div>;
}

export function Shell({ route, children }: { route: Route; children: ReactNode }) {
  const { t, unavailable, preferences } = useI18n();
  const archive = useArchive();
  const mode = useServiceMode();
  const configuring = !!mode?.configuration_mode && mode.configuration_mode !== "READY";
  const [theme, cycle] = useTheme();
  const items = archive ? [{ label: t("archive.title"), to: { name: "home" } as Route }, ...(route.name === "run-short" ? [{ label: route.run, to: route }] : [])] : trail(route, t);
  const project = "project" in route ? route.project : undefined;
  const path = href(route);
  const first = useRef(true);
  const current = items[items.length - 1].label;
  // The title also follows a language change; scroll and focus only a page change.
  useEffect(() => { document.title = `${current} | My Harness`; }, [current]);
  // On page change: scroll to top and focus on the heading (screen readers).
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    window.scrollTo(0, 0);
    requestAnimationFrame(() => document.getElementById("page-title")?.focus({ preventScroll: true }));
  }, [path]);
  return <div className="shell">
    <a className="skip" href="#main">{t("shell.skip")}</a>
    <header className="topbar">
      <Link to={{ name: "home" }} className="brand"><span className="brand-mark" aria-hidden="true" />My Harness</Link>
      <nav aria-label={t("shell.location")} className="crumbs">
        <ol>{items.map((item, index) => <li key={href(item.to)}>
          {index === items.length - 1 ? <span aria-current="page">{item.label}</span> : <Link to={item.to}>{item.label}</Link>}
        </li>)}</ol>
      </nav>
      <div className="topbar-tools">
        <Supervisor />
        <button type="button" className="button-quiet theme" onClick={cycle} aria-label={t("shell.theme.change", { theme: t(THEMES[theme]) })} title={t(THEMES[theme])}>
          <span aria-hidden="true" className={`theme-mark theme-${theme}`} />
        </button>
        <SessionControls />
      </div>
    </header>
    <nav className="sidebar" aria-label={t("shell.sections")}>
      <div className="nav-group">
        <ul>
          <li><Link to={{ name: "home" }} current={route.name === "home"}>{archive ? t("archive.title") : t("nav.projects")}</Link></li>
          {mode && !archive && !configuring && <li><Link to={{ name: "project-new" }} current={route.name === "project-new"}>{t("nav.new_project")}</Link></li>}
          <li><Link to={{ name: "knowledge" }} current={route.name === "knowledge"}>{t("knowledge.title")}</Link></li>
          <li><Link to={{ name: "stats" }} current={route.name === "stats"}>{t("nav.stats")}</Link></li>
          <li><Link to={{ name: "accounting" }} current={route.name === "accounting"}>{t("nav.accounting")}</Link></li>
          {mode && !archive && <li><Link to={{ name: "preferences" }} current={route.name === "preferences"}>{t("nav.preferences")}</Link></li>}
          {mode?.configuration_mode && !archive && <li><Link to={{ name: configuring ? "initial-setup" : "configuration" }} current={route.name === "configuration" || route.name === "initial-setup"}>{t("configuration.title")}</Link></li>}
        </ul>
      </div>
      {mode && !archive && !configuring && project && <ProjectNav route={route} project={project} />}
    </nav>
    <main id="main" className="content">
      {!archive && preferences?.status === "invalid" && route.name !== "preferences" && <p role="alert" className="state state-error">{t("preferences.invalid")}</p>}
      {unavailable && <p role="status" className="state state-stale">{t("preferences.unavailable")}</p>}
      {children}
    </main>
  </div>;
}
