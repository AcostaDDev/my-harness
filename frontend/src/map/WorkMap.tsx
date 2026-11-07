// Product work map L0–L3 (P002-T022; T018 §§3–5, 8, 11; D304, D306, D309). Each level reads T020's projection for
// its route, renders it with T021's engine and keeps it current with one aggregated activity poll over every scope
// known in view (a task without runs is followed through its run selector, so its first run appears by itself). L3's
// chat lane comes from the run's own steps read (T020 lists the run's active chats there, within its version), never
// from the global activity list, so an archive shows it without polling and a truncated activity list hides nothing.
// Selecting a node fills the inspector (a side panel, or a bottom sheet on narrow screens); circles open their
// invocation and bubbles open T017's conversation over the map, never the card's own navigation. Archives
// (`read_only_archive`) read the same projections once: no poll, no timers, no actions; the table display is their
// list alternative, with the same details, invocations and requests reachable from each row.
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "../Language";
import { Link, navigate, withBase } from "../navigation";
import { href } from "../router.ts";
import type { Route } from "../router.ts";
import { Alert, Empty, Loading, MapStatusBadge, message, PageHeader, Stale, when } from "../ui";
import { Announcer, statusChanges } from "./announce.ts";
import type { StatusChange } from "./announce.ts";
import { mapPaths, read } from "./api.ts";
import type { MapActivity, MapRuns, MapSteps, Paged } from "./api.ts";
import { EvidenceLink, InspectorBody, itemTitle } from "./Inspector";
import { statusText } from "./labels.ts";
import type { ActorRole, NodeActor } from "./labels.ts";
import { MapView } from "./MapView";
import type { MapNode } from "./MapView";
import { chatsOf, phasesView, projectsView, statusSnapshot, stepsView, tasksView } from "./projection.ts";
import type { Active, LevelItem, LevelView, Texts } from "./projection.ts";
import { ActivityPoller, changedScopes } from "./refresh.ts";
import type { PollerDeps } from "./refresh.ts";
import { RequestsPanel } from "./Requests";
import { keepSheetFocus, SHEET_MEDIA } from "./sheet-focus.ts";
import type { RequestsTarget } from "./Requests";
import { mapLevel, useMapNavigation } from "./routes.ts";
import { STATUS_LABELS, statusClassOf } from "./status.ts";
import { useLevel } from "./use-level.ts";
import type { Loaded } from "./use-level.ts";

export type MapRoute = Extract<Route, { name: "home" | "phases" | "phase" | "task" | "run" }>;

export function isMapRoute(route: Route): route is MapRoute {
  return mapLevel(route) !== undefined;
}

function browserDeps(): PollerDeps {
  const doc = typeof document === "undefined" ? undefined : document;
  return {
    fetchActivity: scopes => read(mapPaths.activity(scopes)),
    setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
    clearTimeout: handle => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
    hidden: () => doc?.visibilityState === "hidden",
    onVisibility: listener => {
      doc?.addEventListener?.("visibilitychange", listener);
      return () => doc?.removeEventListener?.("visibilitychange", listener);
    },
  };
}

export type ActivityHandlers = {
  /** Scopes in view whose version changed or that vanished. */
  changed: (scopes: string[]) => void;
  /** Every response (that the poll works again). */
  activity?: (activity: MapActivity) => void;
  /** A read failed; the poller retries at the idle interval. */
  failed?: (error: unknown) => void;
};

/** The activity poll for the scopes in view; nothing (no timer, no listener) when `enabled` is false. */
export function useActivity(enabled: boolean, scopes: readonly string[], handlers: ActivityHandlers,
  shown: Readonly<Record<string, string | undefined>>, deps: () => PollerDeps = browserDeps) {
  const latest = useRef({ handlers, shown });
  latest.current = { handlers, shown };
  const poller = useRef<ActivityPoller | undefined>(undefined);
  const key = [...scopes].sort().join("\n");
  useEffect(() => {
    if (!enabled) return;
    const current = new ActivityPoller(deps(), ({ activity }) => {
      const { handlers: on, shown: versions } = latest.current;
      on.activity?.(activity);
      const stale = changedScopes(activity, versions);
      if (stale.length) on.changed(stale);
    }, error => latest.current.handlers.failed?.(error));
    poller.current = current;
    current.setScopes(key ? key.split("\n") : []);
    current.start();
    return () => { current.stop(); poller.current = undefined; };
  }, [enabled]);
  useEffect(() => { if (enabled) poller.current?.setScopes(key ? key.split("\n") : []); }, [key, enabled]);
}

function announcement(changes: StatusChange[], texts: Texts): string {
  const listed = changes.slice(0, 3).map(change => `${change.code}: ${change.label}`).join(", ");
  const more = changes.length > 3 ? ` ${texts.t("map.announce.more", { count: changes.length - 3 })}` : "";
  return texts.n("map.announce.changes", changes.length, { list: `${listed}${more}` });
}

const announcerDeps = { now: () => Date.now(), setTimeout: (callback: () => void, ms: number) => globalThis.setTimeout(callback, ms),
  clearTimeout: (handle: unknown) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>) };

export type WorkMapProps = {
  route: MapRoute;
  /** Restored query-only archive (resolved before mounting): no poll, no actions, read-only requests. */
  archive: boolean;
  /** T017 controls may act (ordinary mode with configuration READY). */
  canRespond: boolean;
  /** `table`: the list alternative built from the same projections (archives, where the list pages are blocked). */
  display?: "map" | "table";
  /** Test seam: poll dependencies. */
  pollerDeps?: () => PollerDeps;
  /** Path prefix of the development fixture (D312); empty in the product. */
  base?: string;
};

export function WorkMap({ route, archive, canRespond, display = "map", pollerDeps, base = "" }: WorkMapProps) {
  const { t, n, language } = useI18n();
  const texts = useMemo<Texts>(() => ({ t, n, language }), [t, n, language]);
  const nav = useMapNavigation(base);
  const go = useCallback((to: Route, options?: { replace?: boolean }) => navigate(withBase(base, href(to)), options), [base]);
  const hrefOf = useCallback((to: Route) => withBase(base, href(to)), [base]);
  const level = mapLevel(route)!;
  const project = route.name === "home" ? undefined : route.project;
  const path = href(route);

  const runsPath = route.name === "task" || route.name === "run" ? mapPaths.runs(route.project, route.phase, route.task) : null;
  const runs = useLevel<MapRuns>(runsPath);
  const runsHead = runs.state.head ?? runs.state.pages[0];
  const latestRun = runsHead?.latest_run_id ?? undefined;
  const runId = route.name === "run" ? route.run : latestRun;
  const mainPath = route.name === "home" ? mapPaths.projects() : route.name === "phases" ? mapPaths.phases(route.project)
    : route.name === "phase" ? mapPaths.tasks(route.project, route.phase) : runId ? mapPaths.steps(route.project, runId) : null;
  // The page type depends on the level; the adapters below read it as their level's projection.
  const main = useLevel<Paged & Record<string, unknown>>(mainPath);
  const pages = main.state.pages;
  const head = (main.state.head ?? pages[0]) as (Paged & { project?: { key: string; name: string }; phase?: unknown; run?: MapSteps["run"] }) | undefined;
  const projectKey = head?.project?.key ?? runsHead?.project?.key ?? project;

  // Active chats attached to the run shown (L3 chat lane): a snapshot from the run's steps read, the same on every
  // page and reread with it when its version changes (a chat starts, changes process or ends).
  const runChats = level === 3 ? (head as Partial<MapSteps> | undefined)?.chats : undefined;
  const chats = useMemo<readonly Active[]>(() => chatsOf(runChats ?? [], projectKey, runId), [runChats, projectKey, runId]);
  const chatsTruncated = level === 3 && (head as Partial<MapSteps> | undefined)?.chats_truncated === true;
  const view: LevelView = useMemo(() => {
    switch (level) {
      case 0: return projectsView(pages as never, archive, texts);
      case 1: return phasesView(pages as never, project!, texts);
      case 2: return tasksView(pages as never, project!, (route as { phase: string }).phase, texts);
      default: return stepsView(pages as never, project!, texts, chats);
    }
  }, [pages, level, archive, texts, project, path, chats]);

  // The canonical run URL (as the run page does): a selected run of another phase or task is corrected in place.
  const runHead = head?.run;
  useEffect(() => {
    if (route.name !== "run" || !runHead || runHead.purpose !== "task") return;
    if (runHead.phase !== route.phase || runHead.task !== route.task)
      go({ ...route, phase: runHead.phase, task: runHead.task }, { replace: true });
  }, [runHead?.run_id, path]);

  // Selection and requests belong to the level shown.
  const [selected, setSelected] = useState<string>();
  const [requests, setRequests] = useState<RequestsTarget>();
  const [sheet, setSheet] = useState(false);
  const bodyId = useId();
  const inspectorBody = useRef<HTMLDivElement>(null);
  // Narrowing the window while the focus is in the inspector opens the sheet instead of hiding that focus.
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    return keepSheetFocus({ query: window.matchMedia(SHEET_MEDIA), document, body: () => inspectorBody.current,
      open: () => setSheet(true), frame: callback => { requestAnimationFrame(callback); } });
  }, []);
  const [pollError, setPollError] = useState<unknown>();
  useEffect(() => { setSelected(undefined); setRequests(undefined); setSheet(false); setPollError(undefined); }, [path]);
  const item = selected ? view.items.get(selected) : undefined;

  const reloadAll = useCallback(() => { main.reload(); runs.reload(); }, [main.reload, runs.reload]);

  // One activity poll for every scope known in view (level and run selector), even before a task has runs; a
  // changed or vanished scope reloads it. A failed read is shown as possibly out of date until a read works again.
  const scopes = [head?.scope, runsHead?.scope].filter((scope): scope is string => !!scope);
  const shown: Record<string, string | undefined> = {};
  if (head) shown[head.scope] = head.version;
  if (runsHead) shown[runsHead.scope] = runsHead.version;
  const polling = !archive && scopes.length > 0 && !head?.read_only_archive && !runsHead?.read_only_archive;
  useActivity(polling, scopes, {
    changed: stale => {
      if (head && stale.includes(head.scope)) main.reload();
      if (runsHead && stale.includes(runsHead.scope)) runs.reload();
    },
    activity: () => setPollError(undefined),
    failed: error => setPollError(error),
  }, shown, pollerDeps);

  // Polite announcements of status changes in view, at most one summary every 10 s; nothing on a level's first read.
  const [spoken, setSpoken] = useState("");
  const announcer = useRef<Announcer | undefined>(undefined);
  const textsRef = useRef(texts);
  textsRef.current = texts;
  useEffect(() => {
    if (archive) return;
    const current = new Announcer(announcerDeps, changes => setSpoken(announcement(changes, textsRef.current)));
    announcer.current = current;
    return () => { current.dispose(); announcer.current = undefined; };
  }, [mainPath, archive]);
  const snapshot = useRef<{ key: string | null; map: ReturnType<typeof statusSnapshot> } | undefined>(undefined);
  useEffect(() => {
    if (!pages.length) return;
    const next = statusSnapshot(view.nodes, node => statusText(node, t));
    const previous = snapshot.current?.key === mainPath ? snapshot.current.map : undefined;
    snapshot.current = { key: mainPath, map: next };
    announcer.current?.push(statusChanges(previous, next));
  }, [view]);

  // The element's exact scope travels with its requests: a step is its run and attempt, never the whole run.
  const requestsOf = useCallback((target: LevelItem, role?: ActorRole) => {
    if (target.level === 3 && target.chat) return;
    const bubbles = target.item.bubbles;
    if (!bubbles) return;
    const key = target.level === 0 ? target.item.id : projectKey;
    if (!key) return;
    const scope = target.level === 1 ? { phase: target.item.code }
      : target.level === 2 ? { phase: target.phase, task: target.item.code }
      : target.level === 3 ? { run: runId, attempt: typeof target.item.attempt_id === "string" ? target.item.attempt_id : undefined } : undefined;
    setRequests({ project: key, label: itemTitle(target, t), bubbles, role, scope });
    setSheet(true);
  }, [projectKey, runId, t]);

  const onSelect = useCallback((node: Pick<MapNode, "id">) => { setSelected(node.id); setRequests(undefined); setSheet(true); }, []);
  const onActor = useCallback((_node: MapNode, actor: NodeActor) => { if (actor.target) go(actor.target); }, [go]);
  const onRequests = useCallback((node: Pick<MapNode, "id">, role?: ActorRole) => {
    const target = view.items.get(node.id);
    if (target) { setSelected(node.id); requestsOf(target, role); }
  }, [view, requestsOf]);

  const label = t("map.label", { level: level === 0 ? t("map.level.projects") : level === 1 ? t("map.level.phases", { project: head?.project?.name ?? project ?? "" })
    : level === 2 ? t("map.level.tasks", { phase: (route as { phase: string }).phase }) : t("map.level.steps", { task: (route as { task: string }).task }) });

  const title = level === 0 ? (archive ? t("archive.title") : t("home.title")) : level === 1 ? t("nav.phases")
    : level === 2 ? (route as { phase: string }).phase : (route as { task: string }).task;
  const noRuns = runsPath && !runs.state.loading && runs.state.pages.length > 0 && !runId;
  const error = main.state.error ?? runs.state.error;
  // A failed reread over a snapshot still shown (the level's pages, or a run selector read empty before) keeps that
  // snapshot as possibly out of date, with the error and "Read again" visible in the view.
  const stale = error !== undefined && (pages.length > 0 || !!noRuns);
  const missing = main.state.missing || runs.state.missing;
  const loading = main.state.loading || runs.state.loading;
  const retry = <button type="button" className="button-quiet" disabled={loading} onClick={reloadAll}>{t("map.retry")}</button>;
  const summary = <LevelSummary level={level} head={head} archive={archive} route={route} />;
  const body: ReactNode = missing ? <Empty title={t("map.missing")}><p><Link to={nav.parent ?? { name: "home" }}>{t("map.up")}</Link></p></Empty>
    : noRuns ? <Empty title={t("map.runs.none")}><p>{t(archive ? "map.runs.none_archive" : "map.runs.none_hint")}</p></Empty>
    : !pages.length ? error ? <><Alert>{message(error)}</Alert>{retry}</> : <Loading>{t("map.loading")}</Loading>
    : display === "table" ? <MapTable view={view} level={level} selected={selected} onSelect={onSelect} onRequests={onRequests} />
    : <MapView viewKey={path} label={label} nodes={view.nodes} edges={view.edges} arrangement={view.arrangement}
      hrefOf={hrefOf} onEnter={node => node.to && nav.enter(node.to, node.id)} onLeave={nav.parent ? nav.leave : undefined}
      selected={selected} onSelect={onSelect} onActor={onActor} onRequests={onRequests} />;

  return <>
    <PageHeader title={title} code={level >= 2}>
      <p>{t(archive ? "map.lede.archive" : "map.lede")}</p>
    </PageHeader>
    {stale && <><Stale error={message(error)} />{retry}</>}
    {pollError !== undefined && <p role="status" className="state state-stale">{t("map.poll.failed", { error: message(pollError) })}</p>}
    {main.state.recovered && <p role="status" className="state state-stale">{t("map.recovered")}</p>}
    <div className={`map-page${sheet ? " map-sheet-open" : ""}`}>
      <div className="map-main">
        {runsPath && <RunSelector runs={runs} current={runId} route={route as Extract<MapRoute, { name: "task" | "run" }>} go={go} />}
        {main.state.skipped > 0 && <p className="hint">{n("map.window.skipped", main.state.skipped)}{" "}
          <button type="button" className="button-quiet" disabled={main.state.loading} onClick={main.reload}>{t("map.window.start")}</button></p>}
        {body}
        {chatsTruncated && <p className="hint">{t("map.chat.truncated", { count: String(chats.length) })}</p>}
        {main.canLoadMore && <button type="button" className="button-quiet map-more" disabled={main.state.loading} onClick={main.loadMore}>{t("map.load_more")}</button>}
      </div>
      <aside className="map-inspector" aria-label={t("map.inspector.label")}>
        <div className="map-inspector-head">
          <h2>{item ? itemTitle(item, t) : t("map.inspector.level")}</h2>
          <button type="button" className="button-quiet map-sheet-toggle" aria-expanded={sheet} aria-controls={bodyId} onClick={() => setSheet(!sheet)}>
            {sheet ? t("map.inspector.collapse") : t("map.inspector.expand")}</button>
        </div>
        <div className="map-inspector-body" id={bodyId} ref={inspectorBody}>
          {requests
            ? <RequestsPanel key={`${requests.project}:${requests.label}:${requests.role ?? ""}`} target={requests} canRespond={canRespond && !archive}
              onClose={() => setRequests(undefined)} onChange={reloadAll} />
            : <InspectorBody item={item} texts={texts} summary={summary} onRequests={item ? role => requestsOf(item, role) : undefined} />}
        </div>
      </aside>
    </div>
    <p className="visually-hidden" role="status" aria-live="polite">{spoken}</p>
  </>;
}

function LevelSummary({ level, head, archive, route }: { level: number; head?: Paged & Record<string, unknown>; archive: boolean; route: MapRoute }) {
  const { t, n } = useI18n();
  if (!head) return null;
  const items = (head.items as unknown[] | undefined)?.length ?? 0;
  if (level === 0) return <p>{n("map.summary.projects", items)}</p>;
  const project = head.project as { key: string; name: string } | undefined;
  if (level === 1) return <p>{t("map.summary.project", { name: project?.name ?? "" })} <code>{project?.key}</code></p>;
  if (level === 2) {
    const phase = head.phase as { code: string; title: string | null; status: { code?: string | null; class: string } };
    return <p><code>{phase.code}</code> {phase.title} <MapStatusBadge status={phase.status} /></p>;
  }
  const run = head.run as MapSteps["run"];
  const owner = route.name === "task" || route.name === "run" ? route.project : project?.key ?? "";
  return <>
    <p>{t("map.summary.run", { id: run.run_id.slice(0, 12) })} <MapStatusBadge status={run.status} /></p>
    <dl className="fields map-fields">
      <div><dt>{t("map.field.stage")}</dt><dd><code>{run.stage}</code></dd></div>
      <div><dt>{t("map.field.revision_rounds")}</dt><dd>{t("map.field.attempts_value", { value: String(run.revisions), limit: String(run.revision_limit) })}</dd></div>
      <div><dt>{t("map.field.started")}</dt><dd>{when(run.created_at)}</dd></div>
    </dl>
    <p><EvidenceLink project={owner} run={run.run_id} phase={run.purpose === "task" ? run.phase : null}
      task={run.purpose === "task" ? run.task : null} archive={archive} /></p>
  </>;
}

/** Run selector of L3 (T018 §3): latest first, earlier runs on demand; choosing one is a navigation of its own. */
function RunSelector({ runs, current, route, go }: { runs: Loaded<MapRuns>; current?: string; route: Extract<MapRoute, { name: "task" | "run" }>; go: (to: Route) => void }) {
  const { t, n } = useI18n();
  const items = runs.state.pages.flatMap(page => page.items);
  const latest = (runs.state.head ?? runs.state.pages[0])?.latest_run_id;
  if (!items.length) return null;
  const known = items.some(run => run.run_id === current);
  return <div className="map-runs actions">
    <label>{t("map.runs.label")}{" "}
      <select value={current ?? ""} onChange={event => go({ name: "run", project: route.project, phase: route.phase, task: route.task, run: event.target.value })}>
        {!known && current && <option value={current}>{current.slice(0, 12)}</option>}
        {items.map(run => <option key={run.run_id} value={run.run_id}>
          {run.run_id.slice(0, 12)} · {t(STATUS_LABELS[statusClassOf(run.status.class)])}{run.status.code ? ` (${run.status.code})` : ""} · {run.created_at.slice(0, 16).replace("T", " ")}{latest === run.run_id ? ` · ${t("map.runs.latest")}` : ""}
        </option>)}
      </select>
    </label>
    {runs.state.skipped > 0 && <span className="hint">{n("map.window.skipped", runs.state.skipped)}{" "}
      <button type="button" className="button-quiet" disabled={runs.state.loading} onClick={runs.reload}>{t("map.window.start")}</button></span>}
    {runs.canLoadMore && <button type="button" className="button-quiet" disabled={runs.state.loading} onClick={runs.loadMore}>{t("map.runs.earlier")}</button>}
    {route.name === "run" && <Link to={{ name: "task", project: route.project, phase: route.phase, task: route.task }}>{t("map.runs.show_latest")}</Link>}
  </div>;
}

/**
 * The list alternative over the same projection (archives): one row per node with its status, counter, actors,
 * requests and errors, and keyboard controls that fill the inspector with the row's details (steps included), open
 * each actor's invocation and open the element's requests, exactly as the map's overlays do. Read-only: no action,
 * no write and no timer of its own.
 */
function MapTable({ view, level, selected, onSelect, onRequests }: {
  view: LevelView; level: number; selected?: string;
  onSelect: (node: Pick<MapNode, "id">) => void; onRequests: (node: Pick<MapNode, "id">, role?: ActorRole) => void;
}) {
  const { t, n } = useI18n();
  return <div className="table-scroll" role="region" aria-label={t("map.table")} tabIndex={0}>
    <table className="table">
      <thead><tr>
        <th scope="col">{t("map.column.element")}</th><th scope="col">{t("map.column.title")}</th><th scope="col">{t("map.field.status")}</th>
        <th scope="col">{t("map.column.counter")}</th><th scope="col">{t("map.column.actors")}</th><th scope="col">{t("map.inspector.requests")}</th>
        <th scope="col">{t("map.inspector.errors")}</th><th scope="col">{t("map.column.details")}</th>
      </tr></thead>
      <tbody>{view.nodes.map(node => {
        const item = view.items.get(node.id)!;
        const status = item.level === 3 && item.chat ? { code: item.item.process, class: "progress" as const } : item.item.status;
        return <tr key={node.id} aria-current={selected === node.id ? "true" : undefined}>
          <td>{node.to ? <Link className="mono strong" to={node.to}>{node.code}</Link> : <span className="mono">{node.code}</span>}</td>
          <td className="wide">{node.title}</td>
          <td><MapStatusBadge status={status} /></td>
          <td>{node.counter}</td>
          <td>{node.actors?.length ? <ul className="map-table-actors">{node.actors.map((actor, i) => {
            const name = t(`map.actor.${actor.role}`);
            return <li key={`${actor.role}:${i}`}>
              <span className={`map-circle-chip${actor.active ? " map-circle-active" : ""}`} aria-hidden="true">{actor.role}</span>{" "}
              {actor.target ? <Link to={actor.target}>{t(actor.chat && actor.active ? "map.circle.open_chat" : "map.circle.open", { actor: name })}</Link>
                : <span className="muted">{t("map.circle.inert", { actor: name })}</span>}
              {!!actor.requests && <> · <button type="button" className="button-quiet" onClick={() => onRequests(node, actor.role)}>
                {n("map.circle.requests", actor.requests, { actor: name })}</button></>}
            </li>;
          })}</ul> : "—"}</td>
          <td>{node.requests ? <button type="button" className="button-quiet" onClick={() => onRequests(node)}>{n("map.node.requests", node.requests)}</button> : "—"}</td>
          <td>{node.errors ? n("map.node.errors", node.errors) : "—"}</td>
          <td><button type="button" className="button-quiet" aria-pressed={selected === node.id} onClick={() => onSelect(node)}>
            {t("map.table.inspect", { code: node.code })}</button></td>
        </tr>;
      })}</tbody>
    </table>
    {level === 3 && <p className="hint">{t("map.table.steps_hint")}</p>}
  </div>;
}
