// P002-T023: L4 over the bounded T020 reads, shared SVG/list and version refresh. No native content in cards.
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { Link, navigate, withBase } from "../navigation";
import { href } from "../router.ts";
import type { Route } from "../router.ts";
import { Empty, Loading, MapStatusBadge, PageHeader, Stale, message, when } from "../ui";
import { mapPaths } from "./api.ts";
import type { MapInvocation } from "./api.ts";
import { EvidenceLink, StepFields } from "./Inspector";
import { roleText } from "./projection.ts";
import { useLevel } from "./use-level.ts";
import { useActivity } from "./WorkMap";
import { MapView } from "./MapView";
import { MapWithDocs } from "./DocsDrawer";
import { ViewToggle } from "./LevelSwitch";
import { useViewMode } from "./view-mode.ts";
import { traceGraph, traceTitle, tracePosition } from "./trace.ts";
import { useTraceHistory } from "./trace-history.ts";
import type { TraceGroup } from "./trace-history.ts";
import { TraceDetails } from "./TraceDetails";
import { keepSheetFocus, SHEET_MEDIA } from "./sheet-focus.ts";
import { Announcer, statusChanges } from "./announce.ts";
import type { PollerDeps } from "./refresh.ts";
import { ReviewerTalk } from "../ReviewerTalk";
type Crumb = { level: string; id: string | null; role?: string | null; ordinal?: number | null };
const WINDOW_SIZE = 200;

function crumbRoute(project: string, crumb: Crumb, owner: MapInvocation["owner"]): Route | undefined {
  if (!crumb.id) return undefined;
  if (crumb.level === "project") return { name: "phases", project };
  if (crumb.level === "phase") return { name: "phase", project, phase: crumb.id };
  if (crumb.level === "task" && owner.phase) return { name: "task", project, phase: owner.phase, task: crumb.id };
  if (crumb.level === "run" && owner.phase && owner.task) return { name: "run", project, phase: owner.phase, task: owner.task, run: crumb.id };
  if (crumb.level === "chat") return { name: "chat", project, conversation: crumb.id };
  if (crumb.level === "phase_operation" && owner.phase) return { name: "phase", project, phase: owner.phase };
  return undefined;
}

export function InvocationPage({ project, invocation, archive, pollerDeps, base = "" }: { project: string; invocation: string; archive: boolean; pollerDeps?: () => PollerDeps; base?: string }) {
  const { t, n, language } = useI18n();
  const { mode, choose } = useViewMode();
  const [group, setGroup] = useState<TraceGroup>("all");
  const header = useLevel<MapInvocation>(mapPaths.invocation(project, invocation));
  const history = useTraceHistory(project, invocation, group);
  const data = header.state.head;
  const scopes = history.state.head?.scopes ?? [];
  const shown = Object.fromEntries(data ? [[data.scope, data.version], ...scopes] : scopes);
  const [pollError, setPollError] = useState<unknown>();
  useActivity(!archive && !!data && !data.read_only_archive, Object.keys(shown), {
    changed: changed => {
      if (data && changed.includes(data.scope)) header.reload();
      if (scopes.some(([scope]) => changed.includes(scope))) history.reload();
    },
    activity: () => setPollError(undefined), failed: setPollError,
  }, shown, pollerDeps);
  const [position, setPosition] = useState<{ page: symbol; window: number; followLatest: boolean }>();
  const [selected, setSelected] = useState<string>();
  const [sheet, setSheet] = useState(false);
  const bodyId = useId();
  const inspector = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    return keepSheetFocus({ query: window.matchMedia(SHEET_MEDIA), document, body: () => inspector.current,
      open: () => setSheet(true), frame: callback => requestAnimationFrame(callback) });
  }, []);
  const { pages, loading, skipped, recovered, error } = history.state;
  const latest = pages.length - 1;
  const held = position && !position.followLatest ? pages.findIndex(page => page.id === position.page) : -1;
  const pageIndex = held < 0 ? latest : held;
  const page = pages[pageIndex];
  const windowIndex = position && page?.id === position.page ? position.window : 0;
  const start = windowIndex * WINDOW_SIZE;
  const total = page?.items.length ?? 0;
  const atEnd = start + WINDOW_SIZE >= total;
  const items = useMemo(() => page?.items.slice(start, start + WINDOW_SIZE) ?? [], [page, start]);
  function showPage(index: number, lastWindow = false) {
    const target = pages[index];
    const window = lastWindow ? Math.max(0, Math.ceil(target.items.length / WINDOW_SIZE) - 1) : 0;
    setPosition({ page: target.id, window, followLatest: index === latest });
  }
  function showWindow(index: number) {
    setPosition({ page: page.id, window: index, followLatest: pageIndex === latest });
  }
  const graph = useMemo(() => traceGraph(items, t), [items, t]);
  const sections = useMemo(() => (["positioned", "unpositioned"] as const).map(kind => {
    const members = items.filter(item => (item.step !== undefined || item.anchorSeq !== undefined) === (kind === "positioned"));
    return { kind, items: members, graph: traceGraph(members, t) };
  }).filter(section => section.items.length), [items, t]);
  const selectedItem = items.find(item => item.id === selected) ?? items[0];
  const select = (id: string) => { setSelected(id); setSheet(true); };
  const [spoken, setSpoken] = useState("");
  const announcer = useRef<Announcer | undefined>(undefined);
  const previous = useRef<Map<string, { code: string; status: string; label: string }> | undefined>(undefined);
  useEffect(() => {
    if (archive) return;
    const current = new Announcer({ now: () => Date.now(), setTimeout: (cb, ms) => globalThis.setTimeout(cb, ms),
      clearTimeout: handle => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>) }, changes => setSpoken(t("trace.updated", { count: changes.length })));
    announcer.current = current;
    return () => { current.dispose(); announcer.current = undefined; };
  }, [archive, invocation, t]);
  useEffect(() => {
    const next = new Map(graph.nodes.map(node => [node.id, { code: node.code, status: node.status, label: node.title }]));
    announcer.current?.push(statusChanges(previous.current, next)); previous.current = next;
  }, [graph]);
  if (header.state.missing) return <><PageHeader title={t("map.invocation.title")} /><Empty title={t("map.invocation.missing")} /></>;
  if (!data) return header.state.error ? <><Stale error={message(header.state.error)} /><button type="button" className="button-quiet" onClick={header.reload}>{t("map.retry")}</button></> : <Loading />;
  const head = data.invocation, crumbs = data.owner.breadcrumb as Crumb[];
  const evidenceRun = head.lane === "managed_attempt" ? data.owner.run_id : null;
  const taskLane = data.owner.lane === "task";
  const parentCrumb = [...crumbs].reverse().find(crumb => crumb.level !== "invocation" && !(archive && crumb.level === "chat") && crumbRoute(project, crumb, data.owner));
  const parent = parentCrumb && crumbRoute(project, parentCrumb, data.owner);
  const state = history.state.head?.steps?.state ?? data.steps.state;
  const reason = history.state.head?.steps?.reason ?? data.steps.reason;
  const changeGroup = (next: TraceGroup) => { setGroup(next); setPosition(undefined); setSelected(undefined); };
  return <MapWithDocs project={project} archive={archive} checkoutProject={data.project.registered_project_id} context={{ level: 4, phase: data.owner.phase, task: taskLane ? data.owner.task : null }}>
    <ViewToggle mode={mode} choose={choose} />
    <PageHeader title={t("map.invocation.heading", { role: roleText(head.role, t) })}><p>{t("trace.lede")}</p></PageHeader>
    {!archive && !data.read_only_archive && data.project.registered_project_id && <ReviewerTalk project={data.project.registered_project_id}
      legacy={!data.project.knowledge_project_id}
      target={data.owner.run_id ? data.step?.harness_attempt?.value != null
        ? { kind: "step", target: data.owner.run_id, step_key: `${String(data.step.harness_attempt.value).padStart(6, "0")}.0000` }
        : { kind: "run", target: data.owner.run_id } : undefined} />}
    <Stale error={header.state.error ? message(header.state.error) : pollError ? message(pollError) : undefined} />
    <nav aria-label={t("map.invocation.owner")} className="map-owner"><ol>{crumbs.map((crumb, i) => {
      const to = crumbRoute(project, crumb, data.owner);
      const label = crumb.level === "invocation" ? `${roleText(crumb.role, t)}${crumb.ordinal ? ` #${crumb.ordinal}` : ""}`
        : `${t(`map.crumb.${crumb.level}` as MessageKey)}${crumb.id ? ` ${crumb.level === "run" ? crumb.id.slice(0, 8) : crumb.id}` : ""}`;
      return <li key={`${crumb.level}:${i}`}>{to && i < crumbs.length - 1 && !(archive && (to.name === "chat" || (to.name === "phase" && to.section)))
        ? <Link to={to}>{label}</Link> : <span>{label}</span>}</li>;
    })}</ol></nav>
    <details className="panel"><summary>{t("map.invocation.header")}</summary>
      <dl className="fields map-fields">
        <div><dt>{t("map.field.identity")}</dt><dd><code>{head.invocation_id}</code></dd></div>
        <div><dt>{t("map.field.circle")}</dt><dd>{head.circle ?? t("map.not_observed")} · {roleText(head.role, t)}</dd></div>
        <div><dt>{t("map.field.lane")}</dt><dd><code>{head.lane}</code> · <code>{head.purpose}</code></dd></div>
        <div><dt>{t("map.field.launch")}</dt><dd><MapStatusBadge status={head.launch} /></dd></div>
        <div><dt>{t("map.field.outcome")}</dt><dd><code>{head.outcome ?? t("map.not_observed")}</code></dd></div>
        <div><dt>{t("map.field.process")}</dt><dd><code>{head.process ?? t("map.not_observed")}</code></dd></div>
        <div><dt>{t("map.field.started")}</dt><dd>{when(head.started_at)}</dd></div>
        <div><dt>{t("map.field.finished")}</dt><dd>{when(head.finished_at)}</dd></div>
      </dl>
      {data.step && <StepFields step={data.step} project={project} texts={{ t, n, language }} />}
    </details>
    <p role="status"><code>{state}</code> · {t(`map.steps_state.${state}` as MessageKey)}
      {reason && <> · <code>{reason}</code></>}</p>
    {evidenceRun && <p><EvidenceLink project={project} run={evidenceRun} phase={taskLane ? data.owner.phase : null}
      task={taskLane ? data.owner.task : null} archive={archive} /></p>}
    {(data.steps.summary || data.steps.failure || data.steps.observation) && <details className="panel"><summary>{t("trace.coverage")}</summary>
      <pre className="trace-json">{JSON.stringify({ summary: data.steps.summary, failure: data.steps.failure, observation: data.steps.observation }, null, 2)}</pre></details>}
    <p className="hint">{t("trace.legend")}</p>
    <div className="map-view-toggle" role="group" aria-label={t("trace.groups")}>{(["all", "steps", "records", "permissions"] as const).map(key =>
      <button key={key} type="button" className="button-quiet" aria-pressed={group === key} onClick={() => changeGroup(key)}>{t(`trace.group.${key}`)}</button>)}</div>
    {error ? <Stale error={message(error)} /> : null}
    {recovered && <p role="status">{t("map.recovered")}</p>}
    <div className={`map-page${sheet ? " map-sheet-open" : ""}`}>
      <div className="map-main">
        <div className="trace-paging">
          <button type="button" className="button-quiet" disabled={loading} onClick={() => { setPosition(undefined); history.reload(); }}>{t("map.window.start")}</button>
          <button type="button" className="button-quiet" disabled={loading || pageIndex <= 0 || windowIndex > 0} onClick={() => showPage(pageIndex - 1, true)}>{t("trace.previous")}</button>
          <button type="button" className="button-quiet" disabled={loading || pageIndex === latest || !atEnd} onClick={() => showPage(pageIndex + 1)}>{t("trace.next")}</button>
          {history.canLoadMore && <button type="button" className="button-quiet" disabled={loading || pageIndex !== latest || !atEnd} onClick={history.loadMore}>{t("map.load_more")}</button>}
        </div>
        {total > WINDOW_SIZE && <div className="trace-paging">
          <button type="button" className="button-quiet" disabled={loading || !windowIndex} onClick={() => showWindow(windowIndex - 1)}>{t("trace.window_previous")}</button>
          <span>{t("trace.window", { first: start + 1, last: Math.min(start + WINDOW_SIZE, total), total })}</span>
          <button type="button" className="button-quiet" disabled={loading || atEnd} onClick={() => showWindow(windowIndex + 1)}>{t("trace.window_next")}</button>
        </div>}
        {skipped > 0 && <p className="hint">{n("map.window.skipped", skipped)}</p>}
        {loading && <Loading />}
        {!items.length && !loading && <Empty title={t("trace.empty")} />}
        {sections.map(section => <section key={section.kind} className="trace-section" data-trace-section={section.kind}>
          <h2>{t(section.kind === "positioned" ? "trace.positioned" : "trace.unpositioned")}</h2>
          {section.kind === "unpositioned" && <p className="hint">{t("trace.unpositioned_hint")}</p>}
          {mode === "map" ? <MapView viewKey={`${href({ name: "invocation", project, invocation })}:${group}:${section.kind}`} label={t(section.kind === "positioned" ? "trace.positioned" : "trace.unpositioned")}
          nodes={section.graph.nodes} edges={section.graph.edges} arrangement="layered" hrefOf={href} selected={selectedItem?.id}
          onSelect={node => select(node.id)} onEnter={node => select(node.id)}
          onLeave={() => navigate(withBase(base, href(parent ?? { name: "phases", project })))} />
          : <ol className="trace-list">{section.items.map((item, index) => <li key={item.id}><button type="button" className="button-quiet" aria-pressed={item.id === selectedItem?.id}
              onClick={() => select(item.id)}>{item.step ? `#${item.step.seq}` : item.record ? `e${item.record.sequence}` : item.permission!.id} · {traceTitle(item, t)}</button>
            <span>{item.permission ? <MapStatusBadge status={item.permission.status} /> : section.graph.nodes[index].statusLabel}</span>
            {!item.step && <span className="hint">{tracePosition(item, t)}</span>}</li>)}</ol>}
        </section>)}
      </div>
      <aside className="map-inspector" aria-label={t("map.inspector.label")}>
        <div className="map-inspector-head"><h2>{t("map.inspector.label")}</h2><button type="button" className="button-quiet map-sheet-toggle"
          aria-expanded={sheet} aria-controls={bodyId} onClick={() => setSheet(!sheet)}>{t(sheet ? "map.inspector.collapse" : "map.inspector.expand")}</button></div>
        <div className="map-inspector-body" id={bodyId} ref={inspector}>
          {selectedItem && <TraceDetails key={`${invocation}:${selectedItem.id}`} item={selectedItem} knowledgeProject={data.project.knowledge_project_id ?? undefined} />}
          {!selectedItem && <p>{t("trace.empty")}</p>}
        </div>
      </aside>
    </div><p className="visually-hidden" role="status" aria-live="polite">{spoken}</p>
  </MapWithDocs>;
}
