import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { activity, isLive, merge } from "./run-activity.ts";
import type { ActivityItem, ActivityNow, RunEvent } from "./run-activity.ts";
import { useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";
import { managed } from "./managed-api";
import type { S } from "./managed-api";
import { ROLES } from "./metrics.ts";
import { Link } from "./navigation";
import { PURPOSES } from "./pages/shared";
import { Status, message, usePoll } from "./ui";
import { useWorkspace } from "./workspace";

// Live activity rail (OT002): the steps of a run as they are confirmed, newest first. It reads the existing
// event cursor: a backfill of the latest windows, then forward pages. Read only; nothing here acts on the run.

const PAGE = 100;
const BACKFILL_PAGES = 8;
const WANTED = 12;
const SHOWN = 60;
const LIVE_POLL = 1500;
const SETTLED_POLL = 10000;

function label(t: (key: MessageKey, params?: Record<string, string | number>) => string, item: ActivityItem) {
  return t(`activity.${item.label}` as MessageKey, item.params);
}

function clip(value: string, limit: number) {
  const flat = value.trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

/** Reads the run's events from the present backwards, then follows them. */
function useRunEvents(runId: string, version: number | undefined, status: string | undefined, refresh: number) {
  const [events, setEvents] = useState<RunEvent[]>();
  const [error, setError] = useState("");
  const live = useRef(isLive(status));
  live.current = status === undefined ? true : isLive(status);
  const top = useRef(version);
  top.current = version;
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let cursor = 0;
    let started = false;
    const path = `/runs/${encodeURIComponent(runId)}/events`;
    async function backfill() {
      const latest = top.current ?? (await managed<S["ManagedRunRead"]>(`/runs/${encodeURIComponent(runId)}`)).version;
      let collected: RunEvent[] = [];
      let after = latest;
      cursor = latest;
      for (let page = 0; page < BACKFILL_PAGES && after > 0; page++) {
        after = Math.max(0, after - PAGE);
        const read = await managed<S["ManagedEventsRead"]>(`${path}?after=${after}&limit=${PAGE}`);
        if (page === 0) cursor = Math.max(cursor, read.cursor);
        collected = merge(collected, read.items as RunEvent[]);
        if (activity(collected).items.length >= WANTED) break;
      }
      return collected;
    }
    async function poll() {
      try {
        if (!started) {
          const first = await backfill();
          if (!active) return;
          started = true;
          setEvents(first);
        }
        const read = await managed<S["ManagedEventsRead"]>(`${path}?after=${cursor}&limit=${PAGE}`);
        if (!active) return;
        cursor = read.cursor;
        if (read.items.length) setEvents(previous => merge(previous ?? [], read.items as RunEvent[]));
        else setEvents(previous => previous ?? []);
        setError("");
        timer = setTimeout(() => void poll(), read.has_more ? 0 : live.current ? LIVE_POLL : SETTLED_POLL);
      } catch (e) {
        if (!active) return;
        setError(message(e));
        timer = setTimeout(() => void poll(), 4000);
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
    // The cursor is local to one run; a new run (or an action) starts a fresh read.
  }, [runId, refresh]);
  return { events, error };
}

function Now({ now, status, items }: { now: ActivityNow; status?: string; items: ActivityItem[] }) {
  const { t } = useI18n();
  const running = [...items].reverse().find(item => item.running);
  const role = now?.role ?? running?.role;
  const who = role && ROLES[role] ? t(ROLES[role]) : undefined;
  let text: string;
  if (status !== undefined && !isLive(status)) text = t("activity.now.settled");
  else if (now?.kind === "tool") text = t("activity.now.tool", { tool: now.tool ?? "" });
  else if (now?.kind === "thinking") text = t("activity.now.thinking");
  else if (now?.kind === "writing") text = t("activity.now.writing");
  else if (running) text = label(t, running);
  else if (status === "QUEUED") text = t("activity.now.queued");
  else text = t("activity.now.waiting");
  const streaming = status === undefined || isLive(status);
  return <div className={streaming ? "activity-now" : "activity-now activity-now-settled"}>
    <p role="status" aria-live="polite" className="activity-now-line">
      <span className={streaming ? "activity-pulse activity-pulse-on" : "activity-pulse"} aria-hidden="true" />
      {who && <span className="activity-role">{who}</span>}<span>{text}</span>
    </p>
    {streaming && now?.text && <p className={now.kind === "tool" ? "activity-stream activity-stream-code" : "activity-stream"} aria-hidden="true">{clip(now.text, 360)}</p>}
  </div>;
}

type FeedProps = { runId: string; version?: number; status?: string; refresh?: number; title?: string; context?: ReactNode };

/** The feed of one run. `version`/`status` come from the caller's own read when it has them. */
export function LiveActivity(props: FeedProps) {
  // Another run is another cursor: the feed starts over instead of mixing two runs.
  return <Feed key={props.runId} {...props} />;
}

/** Feed of the most recent run a runs query returns (a project, a phase or a task). */
export function LatestActivity({ query, refresh, title, empty }: { query: string; refresh: number; title: string; empty: string }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const read = usePoll<S["Page_ManagedRunSummaryRead_"]>(query, 2500, refresh);
  const run = read.data?.items[0];
  if (!run) return <section className="activity" aria-labelledby="activity-none">
    <div className="activity-head"><h2 id="activity-none">{title}</h2></div>
    {read.data ? <p className="hint">{empty}</p> : read.error ? <p className="state state-stale" role="status">{t("common.stale", { error: read.error })}</p>
      : <p className="state state-loading" role="status">{t("activity.loading")}</p>}
  </section>;
  return <LiveActivity runId={run.id} version={run.version} status={run.status} refresh={refresh} title={title}
    context={<>· {run.purpose === "task" ? <Link className="mono" to={{ name: "task", project, phase: run.phase_id, task: run.task_id }}>{run.task_id}</Link>
      : PURPOSES[run.purpose] ? t(PURPOSES[run.purpose]) : run.purpose}</>} />;
}

function Feed({ runId, version, status, refresh = 0, title, context }: FeedProps) {
  const { t, language } = useI18n();
  const { events, error } = useRunEvents(runId, version, status, refresh);
  const read = events ? activity(events) : undefined;
  const items = read?.items ?? [];
  const shown = items.slice(-SHOWN).reverse();
  const clock = new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return <section className="activity" aria-labelledby={`activity-${runId}`}>
    <div className="activity-head">
      <h2 id={`activity-${runId}`}>{title ?? t("activity.title")}</h2>
      {status && <Status value={status} />}
    </div>
    <p className="activity-run">
      <Link to={{ name: "run-short", run: runId }} className="mono">{t("trail.run", { id: runId.slice(0, 8) })}</Link>
      {context && <> {context}</>}
    </p>
    {error && <p className="state state-stale" role="status">{t("common.stale", { error })}</p>}
    {!read ? <p className="state state-loading" role="status">{t("activity.loading")}</p> : <>
      <Now now={read.now} status={status} items={items} />
      {!items.length ? <p className="hint">{t("activity.empty")}</p>
        : <ol className="activity-trace">{shown.map(item => <li key={item.key} className={`activity-step activity-${item.kind} activity-tone-${item.tone}${item.running ? " activity-running" : ""}`}>
          <span className="activity-node" aria-hidden="true" />
          <div className="activity-body">
            <p className="activity-line">
              <span className="activity-label">{label(t, item)}</span>
              <time className="activity-time" dateTime={item.at}>{Number.isNaN(Date.parse(item.at)) ? item.at : clock.format(new Date(item.at))}</time>
            </p>
            {item.detail && <p className={item.kind === "message" || item.kind === "thinking" ? "activity-text" : "activity-code"} title={item.detail.length > 240 ? item.detail : undefined}>
              {clip(item.detail, item.kind === "message" ? 420 : 240)}</p>}
          </div>
        </li>)}</ol>}
      {items.length > SHOWN && <p className="hint">{t("activity.older", { count: SHOWN })}</p>}
    </>}
  </section>;
}
