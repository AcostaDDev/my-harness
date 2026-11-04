import { useId, useState } from "react";
import { useI18n } from "./Language";
import { Link } from "./navigation";
import { confirmOnce, jobRequest, managed } from "./managed-api";
import type { S } from "./managed-api";
import { StandingPermissionPanel } from "./StandingPermissions";
import { Empty, Loading, message, PageHeader, Stale, usePoll, when } from "./ui";
import type { Route } from "./router";
import { inboxResponse } from "./inbox-actions.ts";

type Item = S["InboxItemRead"];
type Detail = S["InboxItemDetail"];
const KINDS = ["permission", "question", "judge", "lifecycle", "notification"] as const;
const STATES = ["unread", "unresolved", "resolved"] as const;
const MODES = ["manual", "autonomous"] as const;
const e = encodeURIComponent;

function projectScope(item: Item): string {
  return item.registered_project_id ?? item.project_id;
}

function InboxState({ item }: { item: Item }) {
  const { t } = useI18n();
  return <span>{t(item.read_at ? "inbox.read" : "inbox.state.unread")}
    {item.kind !== "notification" && <> · {t(item.resolved ? "inbox.state.resolved" : "inbox.state.unresolved")}</>}</span>;
}

export function InboxPage({ project, item, canRespond }: { project?: string; item?: string; canRespond: boolean }) {
  const { t } = useI18n();
  const [kind, setKind] = useState("");
  const [state, setState] = useState("");
  const [mode, setMode] = useState("");
  const [cursors, setCursors] = useState<string[]>([]);
  const [refresh, setRefresh] = useState(0);
  const params = new URLSearchParams({ limit: "30" });
  if (project) params.set("project", project);
  if (kind) params.set("kind", kind);
  if (state) params.set("state", state);
  if (mode) params.set("mode", mode);
  if (cursors.length) params.set("before", cursors[cursors.length - 1]);
  const page = usePoll<S["InboxPageRead"]>(item ? null : `/inbox?${params}`, 4000, refresh);
  return <>
    <PageHeader title={t("inbox.title")}>
      <p>{t("inbox.lede")}</p>
      {project && <p><code>{project}</code> · <Link to={{ name: "inbox" }}>{t("inbox.all_projects")}</Link></p>}
    </PageHeader>
    {project && item ? <InboxConversation key={item} project={project} item={item} canRespond={canRespond}
      onChange={() => setRefresh(n => n + 1)} /> : <>
      <div className="panel actions">
        <label>{t("inbox.filter.kind")}<select value={kind} onChange={ev => { setKind(ev.target.value); setCursors([]); }}>
          <option value="">{t("inbox.filter.all")}</option>
          {KINDS.map(k => <option key={k} value={k}>{t(`inbox.kind.${k}`)}</option>)}
        </select></label>
        <label>{t("inbox.filter.state")}<select value={state} onChange={ev => { setState(ev.target.value); setCursors([]); }}>
          <option value="">{t("inbox.filter.all")}</option>
          {STATES.map(s => <option key={s} value={s}>{t(`inbox.state.${s}`)}</option>)}
        </select></label>
        <label>{t("inbox.filter.mode")}<select value={mode} onChange={ev => { setMode(ev.target.value); setCursors([]); }}>
          <option value="">{t("inbox.filter.all")}</option>
          {MODES.map(m => <option key={m} value={m}>{t(`inbox.mode.${m}`)}</option>)}
        </select></label>
      </div>
      <Stale error={page.error} />
      {page.data ? page.data.items.length ? <ul className="panel">
        {page.data.items.map(entry => <li key={entry.id} className="entry">
          <h2><Link to={{ name: "project-inbox", project: project ?? entry.project_id, item: entry.id }}>{t(`inbox.topic.${entry.topic}`)}</Link></h2>
          <p><InboxState item={entry} /> · {when(entry.at)} · {t(`inbox.mode.${entry.mode}`)}</p>
          <p><Link to={{ name: "project-inbox", project: project ?? entry.project_id }}>{projectScope(entry)}</Link>
            {entry.phase_id && <> · <code>{entry.phase_id}</code></>}{entry.task_id && <> · <code>{entry.task_id}</code></>}</p>
        </li>)}
      </ul> : <Empty title={t("inbox.empty")} /> : !page.error && <Loading />}
      <nav className="actions" aria-label={t("inbox.pages")}>
        <button type="button" disabled={!cursors.length || page.loading} onClick={() => setCursors(cursors.slice(0, -1))}>{t("inbox.previous")}</button>
        <button type="button" disabled={!page.data?.next_before || page.loading}
          onClick={() => { if (page.data?.next_before) setCursors([...cursors, page.data.next_before]); }}>{t("inbox.next")}</button>
      </nav>
    </>}
  </>;
}

type ConversationProps = { project: string; item: string; canRespond: boolean; onChange?: () => void };

/** Entry point for the inbox and a future caller with a project and item reference. */
export function InboxConversation(props: ConversationProps) {
  return <Conversation key={JSON.stringify([props.project, props.item])} {...props} />;
}

function Conversation({ project, item, canRespond, onChange }: ConversationProps) {
  const { t } = useI18n();
  const heading = useId();
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const path = `/inbox/${e(item)}`;
  const read = usePoll<Detail>(`${path}?project=${e(project)}`, 4000, refresh);
  const data = read.data;

  async function operate(effect: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try { await effect(); }
    catch (e) { setError(message(e)); }
    finally { setRefresh(n => n + 1); onChange?.(); setBusy(false); }
  }

  if (!data) return read.error ? <Stale error={read.error} /> : <Loading />;
  const active = canRespond && !read.error && !read.loading && !data.resolved;
  const registered = data.registered_project_id;
  const response = data.response;
  return <section className="panel" aria-labelledby={heading}>
    <h2 id={heading}>{t(`inbox.topic.${data.topic}`)}</h2>
    <p><InboxState item={data} /> · {when(data.at)}</p>
    <Stale error={read.error} />
    {error && <p role="alert" className="state state-error">{error}</p>}
    {data.current_state && <p>{t("inbox.current_state")} <code>{data.current_state}</code></p>}
    {data.context.some(Boolean) && <ul>{data.context.map((line, i) => line && <li key={i}>{line}</li>)}</ul>}
    <InboxEvidence item={data} live={canRespond} />
    {data.kind === "judge" && <p>{t("inbox.judge_read_only")}</p>}
    {data.topic === "autonomous_question" && <p>{t("inbox.answer_resume")}</p>}
    {canRespond && data.continuation && <div className="decision">
      <p>{t("inbox.task_resume")}</p>
      <button type="button" disabled={busy || !!read.error || read.loading} onClick={() => {
        if (!data.continuation || !window.confirm(t("run.retry_confirm"))) return;
        const request = jobRequest(`/runs/${e(data.continuation.target_id)}/actions`, {
          action: "retry_executor", expected_version: data.continuation.version, gap_resolution_id: data.continuation.resolution_id,
        } satisfies S["RunActionCreate"]);
        void operate(() => managed(request.path, request.body, request.key));
      }}>{t("run.retry")}</button>
    </div>}
    {canRespond && !data.read_at && <button type="button" className="button-quiet" disabled={busy || !!read.error}
      onClick={() => void operate(() => managed(`${path}/read`, { project_id: project } satisfies S["InboxMarkRead"]))}>{t("inbox.mark_read")}</button>}
    {canRespond && !data.resolved && registered && data.request_id && data.standing_permission &&
      <StandingPermissionPanel key={data.request_id} project={registered} refresh={refresh}
        focused={{ ...data.standing_permission, requestId: data.request_id }}
        busy={busy || !active} operate={operate} />}
    {canRespond && response && !data.resolved && <InboxReply
      key={`${data.id}:${response.version}:${response.request_version}:${response.proof ?? ""}`}
      item={data} busy={busy || !active} operate={operate} />}
  </section>;
}

function InboxEvidence({ item, live }: { item: Detail; live: boolean }) {
  const { t } = useI18n();
  const project = item.registered_project_id;
  const phase = item.phase_id;
  const task = item.task_id;
  const run = item.run_id;
  const managedRun: Route | undefined = !run || item.origin === "autonomous" ? undefined
    : project && phase && task && item.origin === "managed" ? { name: "run", project, phase, task, run }
    : { name: "run-short", run };
  const auto = item.autonomous_run_id;
  const autoRun: Route | undefined = project && auto && live ? { name: "project-autonomous", project, run: auto } : undefined;
  const knowledge = item.knowledge_project_id && `/api/managed/knowledge/projects/${e(item.knowledge_project_id)}`;
  const phaseEvidence = item.phase_instance_id && `/api/managed/phases/${e(item.phase_instance_id)}`;
  const trace = item.origin !== "autonomous" && item.thread_id && knowledge && `${knowledge}/traces/${e(item.thread_id)}/events`;
  return <dl>
    <dt>{t("inbox.project")}</dt>
    <dd><Link to={project && live ? { name: "project", project } : { name: "project-inbox", project: projectScope(item) }}>{projectScope(item)}</Link>
      {project && live && <> · <Link to={{ name: "chat", project }}>{t("nav.chat")}</Link></>}</dd>
    {phase && <><dt>{t("inbox.phase")}</dt><dd>{project && live
      ? <Link to={{ name: "phase", project, phase, ...(item.kind === "lifecycle" || item.topic === "phase_closed" ? { section: "check" } : {}) }}>{phase}</Link>
      : phaseEvidence ? <a href={phaseEvidence}>{phase}</a> : <code>{phase}</code>}</dd></>}
    {task && <><dt>{t("inbox.task")}</dt><dd>{project && phase && live
      ? <Link to={{ name: "task", project, phase, task }}>{task}</Link>
      : managedRun ? <Link to={managedRun}>{task}</Link> : <code>{task}</code>}</dd></>}
    {run && <><dt>{t("inbox.run")}</dt><dd>{managedRun
      ? <Link to={managedRun}>{t("inbox.open_run", { id: run })}</Link>
      : autoRun ? <Link to={autoRun}>{t("inbox.open_run", { id: run })}</Link> : <code>{run}</code>}</dd></>}
    {auto && auto !== run && <><dt>{t("autonomy.title")}</dt><dd>{autoRun
      ? <Link to={autoRun}>{t("inbox.open_run", { id: auto })}</Link> : <code>{auto}</code>}</dd></>}
    {item.request_id && <><dt>{t("inbox.request")}</dt><dd>{item.kind === "judge" && knowledge
      ? <a href={`${knowledge}/judge/requests/${e(item.request_id)}`}>{item.request_id}</a>
      : <code>{item.request_id}</code>}</dd></>}
    {item.operation_id && <><dt>{t("inbox.operation")}</dt><dd>{trace
      ? <a href={`${trace}?operation_id=${e(item.operation_id)}`}>{item.operation_id}</a>
      : phaseEvidence && item.origin !== "managed" ? <a href={phaseEvidence}>{item.operation_id}</a>
      : <code>{item.operation_id}</code>}</dd></>}
    <dt>{t("inbox.origin")}</dt><dd><code>{item.origin} · {item.event_id}</code></dd>
    {item.evidence_id && <><dt>{t("inbox.evidence")}</dt><dd><code>{item.evidence_id}</code></dd></>}
  </dl>;
}

function InboxReply({ item, busy, operate }: { item: Detail; busy: boolean; operate: (effect: () => Promise<unknown>) => Promise<void> }) {
  const { t } = useI18n();
  const [answers, setAnswers] = useState(() => Array(item.topic === "task_gap" ? item.response?.prompts.length ?? 0 : 1).fill("") as string[]);
  const [reason, setReason] = useState("");
  const [scope, setScope] = useState<"once" | "task">("once");
  const [ttl, setTtl] = useState(3600);
  const [confirmed, setConfirmed] = useState(false);
  const permission = item.topic === "run_permission";
  const values = { answers, reason, scope, confirmed, ttl };
  function send(decision?: "grant" | "deny") {
    const request = inboxResponse(item, values, decision);
    if (!request || busy) return;
    setConfirmed(false);
    void operate(() => request.once ? confirmOnce(request.path, request.body) : managed(request.path, request.body));
  }
  return <div className="decision">
    {permission ? <>
      <label>{t("permissions.reason")}<input value={reason} maxLength={2000} onChange={ev => { setReason(ev.target.value); setConfirmed(false); }} /></label>
      <label>{t("permissions.scope")}<select value={scope} onChange={ev => { setScope(ev.target.value === "task" ? "task" : "once"); setConfirmed(false); }}>
        <option value="once">{t("permissions.scope.once")}</option><option value="task">{t("permissions.scope.task")}</option>
      </select></label>
    </> : answers.map((answer, index) => <label key={index}>
      {t("inbox.answer_number", { number: index + 1 })}
      <textarea value={answer} maxLength={item.topic === "autonomous_question" ? 8000 : 4000}
        onChange={ev => { setAnswers(answers.map((value, i) => i === index ? ev.target.value : value)); setConfirmed(false); }} />
    </label>)}
    {item.topic === "task_gap" && <label>{t("permissions.ttl")}
      <input type="number" min={1} max={86400} value={ttl} onChange={ev => { setTtl(Number(ev.target.value)); setConfirmed(false); }} />
    </label>}
    <label className="check"><input type="checkbox" checked={confirmed} onChange={ev => setConfirmed(ev.target.checked)} />
      {t(permission ? "permissions.confirm" : "inbox.confirm_answer")}</label>
    {permission ? <div className="actions">
      <button type="button" disabled={busy || !inboxResponse(item, values, "grant")} onClick={() => send("grant")}>{t("permissions.grant")}</button>
      <button type="button" className="button-danger" disabled={busy || !inboxResponse(item, values, "deny")} onClick={() => send("deny")}>{t("permissions.deny")}</button>
    </div> : <button type="button" disabled={busy || !inboxResponse(item, values)} onClick={() => send()}>{t("autonomy.send_answer")}</button>}
  </div>;
}
