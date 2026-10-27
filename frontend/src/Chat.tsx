import { useEffect, useState } from "react";
import { translateNow, useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";
import { createOnce, managed, jobRequest, ManagedError } from "./managed-api";
import type { S } from "./managed-api";
import { Link, navigate } from "./navigation";
import { Empty, Evidence, Loading, PageHeader, Stale, Status, message, usePoll } from "./ui";
import { useWorkspace } from "./workspace";
import { ChatCommand } from "./ChatCommand";
import { commandNames, isCommand } from "./chat-commands";

const lines = (value: string) => value.split("\n").map(item => item.trim()).filter(Boolean);
const turnNames: Record<S["ChatTurnRead"]["status"], MessageKey> = {
  QUEUED: "chat.turn.queued", ANSWERED: "chat.turn.answered", FAILED: "chat.turn.failed", UNKNOWN: "chat.turn.unknown",
  REFUSED: "chat.turn.refused",
};
const proposalNames: Record<S["ChatProposalRead"]["status"], MessageKey> = {
  PROPOSED: "chat.proposal.proposed", ACCEPTED: "chat.proposal.accepted", DISMISSED: "chat.proposal.dismissed",
};

/** Contextual chat (D035) with the conversation selected in the URL. */
export function Chat({ conversation }: { conversation?: string }) {
  const { t, n, rich } = useI18n();
  const { project, busy, refresh, operate } = useWorkspace();
  const conversations = usePoll<S["ChatConversationSummaryRead"][]>(`/projects/${project}/conversations`, 3000, refresh);
  const phases = usePoll<S["PhaseSummaryRead"][]>(`/projects/${project}/phases`, 10000, refresh);
  const [title, setTitle] = useState("");
  const [phase, setPhase] = useState("");
  const [taskRun, setTaskRun] = useState("");
  const [runOffset, setRunOffset] = useState(0);
  const runs = usePoll<S["Page_ManagedRunSummaryRead_"]>(`/projects/${project}/runs?offset=${runOffset}&limit=20`, 5000, refresh);
  return <>
    <PageHeader title={t("nav.chat")}>
      <p>{t("chat.lede")}</p>
    </PageHeader>
    <Stale error={conversations.data ? conversations.error : undefined} />
    <div className="split">
      <nav className="panel split-list" aria-label={t("chat.conversations")}>
        <h2>{t("chat.conversations")}</h2>
        {!conversations.data ? <Loading /> : !conversations.data.length ? <p className="hint">{t("chat.conversations.empty")}</p>
          : <ul className="link-list">{conversations.data.map(c => <li key={c.id}>
            <Link to={{ name: "chat", project, conversation: c.id }} current={conversation === c.id}>
              <span className="link-title">{c.title}</span>
              <span className="link-meta">{c.phase_code ? <>{rich("chat.conversation.phase", { phase: <code>{c.phase_code}</code> })}, </> : ""}{n("chat.turns", c.turns)}</span>
            </Link></li>)}</ul>}
        <form onSubmit={e => { e.preventDefault(); void operate(async () => {
          const created = await createOnce<S["ChatConversationRead"]>(`/projects/${project}/conversations`, { title, phase_id: phase || null, task_run_id: taskRun || null } satisfies S["ChatConversationCreate"]);
          setTitle(""); navigate({ name: "chat", project, conversation: created.id });
        }); }}>
          <label>{t("chat.new")}<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></label>
          <label>{t("chat.new.phase")}<select value={phase} onChange={e => setPhase(e.target.value)}>
            <option value="">{t("chat.new.no_phase")}</option>{phases.data?.map(p => <option key={p.id} value={p.id}>{p.code}</option>)}</select></label>
          <label>{t("chat.new.task")}<select value={taskRun} onChange={e => setTaskRun(e.target.value)}>
            <option value="">{t("chat.new.no_task")}</option>{runs.data?.items.filter(r => r.purpose === "task").map(r => <option key={r.id} value={r.id}>{r.task_id} · {r.id.slice(0, 8)}</option>)}</select></label>
          <div className="actions"><button type="button" className="button-quiet" disabled={!runOffset} onClick={() => { setRunOffset(Math.max(0, runOffset - 20)); setTaskRun(""); }}>{t("chat.new.previous_tasks")}</button>
            <button type="button" className="button-quiet" disabled={runs.data?.next_offset == null} onClick={() => { setRunOffset(runs.data!.next_offset!); setTaskRun(""); }}>{t("chat.new.more_tasks")}</button></div>
          <button className="button-quiet" disabled={busy || !title.trim()}>{t("chat.new.create")}</button>
        </form>
      </nav>
      <div className="split-main">
        {conversation ? <Conversation key={conversation} id={conversation} />
          : <Empty title={t("chat.choose.title")}><p>{t("chat.choose.body")}</p></Empty>}
      </div>
    </div>
  </>;
}

function Conversation({ id }: { id: string }) {
  const { t, n, rich } = useI18n();
  const { project, busy, refresh, operate, send } = useWorkspace();
  const [missing, setMissing] = useState(false);
  const [conversation, setConversation] = useState<S["ChatConversationRead"]>();
  const [error, setError] = useState("");
  const [text, setText] = useState("");
  const [command, setCommand] = useState<S["ChatCommandRead"]>();
  const [documents, setDocuments] = useState("");
  const [runIds, setRunIds] = useState("");
  const [tasks, setTasks] = useState<Record<string, string>>({});
  const [phaseIds, setPhaseIds] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [reasons, setReasons] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try { const c = await managed<S["ChatConversationRead"]>(`/conversations/${encodeURIComponent(id)}`); if (active) {
        if (c.project_id !== project) { setConversation(undefined); setMissing(true); setError(translateNow("chat.other_project")); }
        else { setConversation(c); setMissing(false); setError(""); }
      } }
      catch (e) { if (active) { setError(message(e)); setMissing(e instanceof ManagedError && e.status === 404); } }
      if (active) timer = setTimeout(() => void poll(), 1500);
    }
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [id, project, refresh]);
  // A confirmation is only valid for the version and the exact proposal that were shown.
  useEffect(() => { setConfirmed({}); }, [conversation?.version]);
  if (!conversation) return missing ? <Empty title={t("chat.missing.title")}><p>{t("chat.missing.body")}</p></Empty>
    : error ? <p role="alert" className="state state-error">{error}</p> : <Loading>{t("chat.loading")}</Loading>;
  const v = conversation.version;
  const canSend = !busy && !error && (isCommand(text) || conversation.actions.includes("message"));
  return <section className="panel" aria-labelledby="conversation-title">
    <h2 id="conversation-title">{conversation.title}</h2>
    <p className="hint">{conversation.phase ? <>{rich("chat.context.phase", { phase: <Link className="mono" to={{ name: "phase", project, phase: conversation.phase.code }}>{conversation.phase.code}</Link> })} <Status kind="phase" value={conversation.phase.status} /></> : t("chat.context.no_phase")} · {t("chat.context.version", { version: v })}</p>
    {conversation.task_run_id && <p className="hint">{rich("chat.context.task", { run: <Link to={{ name: "run-short", run: conversation.task_run_id }}>{t("trail.run", { id: conversation.task_run_id.slice(0, 8) })}</Link> })}</p>}
    <Stale error={error} />
    {conversation.turns.map(turn => {
      const result = turn.result?.result as { answer?: string; references?: string[] } | null | undefined;
      const run = <Link to={{ name: "run-short", run: turn.run_id }}>{t("trail.run", { id: turn.run_id.slice(0, 8) })}</Link>;
      return <div className="entry turn" key={turn.id}><p className="turn-head"><strong>{t("chat.turn", { number: turn.number })}</strong> {t(turnNames[turn.status])}</p>
        <p className="turn-message">{turn.message}</p>
        <p className="hint">{turn.command ? t("chat.turn.command") : turn.head ? rich("chat.turn.head", { head: <code className="hash">{turn.head.slice(0, 12)}</code> }) : t("chat.turn.legacy")}</p>
        {turn.status === "QUEUED" && turn.run_status === "RECOVERY_REQUIRED" && <p className="state state-attention">{rich("chat.turn.interrupted", { run })}</p>}
        {turn.status === "ANSWERED" && result?.answer && <p className="turn-answer">{result.answer}</p>}
        {turn.status === "ANSWERED" && !!result?.references?.length && <p className="hint">{t("chat.turn.references")} {result.references.map(r => <code key={r} className="chip">{r}</code>)}</p>}
        {turn.status !== "ANSWERED" && Array.isArray(turn.result?.reasons) && <p className="state state-error">{(turn.result!.reasons as string[]).join("; ")}</p>}
        <p className="hint">{run} <Status value={turn.run_status} /> · {rich("chat.turn.context", { hash: <code className="hash">{turn.context_sha256.slice(0, 12)}</code>,
          documents: n("chat.documents", turn.documents.length), runs: n("chat.runs", turn.run_ids.length), turns: n("chat.previous_turns", turn.previous_turns) })}</p>
        <Evidence title={t("chat.turn.evidence")} value={turn} /></div>;
    })}

    <h3>{t("chat.proposals")}</h3>
    {!conversation.proposals.length && <p className="hint">{t("chat.proposals.empty")}</p>}
    {conversation.proposals.map(p => {
      const data = p.proposal as { title: string; objective: string; scope: string; acceptance_criteria: string[]; validation: string[]; rationale: string };
      const task = tasks[p.id] ?? `CHAT-T${String(p.number).padStart(3, "0")}`;
      const phaseId = phaseIds[p.id] ?? conversation.phase?.code ?? "";
      return <div className={p.actions.includes("accept") ? "entry entry-open" : "entry"} key={p.id}><p><strong>{p.number}. {data.title}</strong> {t(proposalNames[p.status])}</p>
        <p>{data.objective}</p>
        {data.scope && <p>{t("chat.proposal.scope", { scope: data.scope })}</p>}
        <ul>{data.acceptance_criteria.map(c => <li key={c}>{c}</li>)}</ul>
        {data.validation.length > 0 && <p>{t("chat.proposal.validation", { validation: data.validation.join("; ") })}</p>}
        {data.rationale && <p className="hint">{data.rationale}</p>}
        <p className="hint">{rich("chat.proposal.origin", { turn: p.turn_number, hash: <code className="hash">{p.proposal_sha256.slice(0, 12)}</code> })}</p>
        {p.run && <p>{rich("chat.proposal.task", { task: <Link className="mono" to={{ name: "task", project, phase: p.run.phase_id, task: p.run.task_id }}>{p.run.task_id}</Link>,
          run: p.run_id ? <Link to={{ name: "run-short", run: p.run_id }}>{t("chat.proposal.its_run")}</Link> : t("chat.proposal.its_run") })} <Status value={p.run.status} />{p.run.commit ? <> {rich("chat.proposal.commit", { commit: <code className="hash">{p.run.commit.slice(0, 12)}</code> })}</> : null}</p>}
        {p.actions.includes("accept") && <>
          <div className="form-row"><label>{t("task_form.task")}<input value={task} maxLength={120} onChange={e => { setTasks({ ...tasks, [p.id]: e.target.value }); setConfirmed({ ...confirmed, [p.id]: false }); }} /></label>
            <label>{t("task_form.phase")}<input value={phaseId} maxLength={120} onChange={e => { setPhaseIds({ ...phaseIds, [p.id]: e.target.value }); setConfirmed({ ...confirmed, [p.id]: false }); }} /></label></div>
          <label className="check"><input type="checkbox" checked={!!confirmed[p.id]} onChange={e => setConfirmed({ ...confirmed, [p.id]: e.target.checked })} />{t("chat.proposal.confirm", { hash: p.proposal_sha256.slice(0, 12) })}</label>
          <button disabled={busy || !!error || !confirmed[p.id] || !task.trim() || !phaseId.trim()} onClick={() => void operate(() => send(jobRequest(`/conversations/${id}/proposals/${p.id}/accept`, {
            expected_version: v, proposal_sha256: p.proposal_sha256, task_id: task.trim(), phase_id: phaseId.trim(), confirmed: true,
          })))}>{t("chat.proposal.accept")}</button></>}
        {p.actions.includes("dismiss") && <div className="form-row"><label>{t("chat.proposal.dismiss_reason")}<input value={reasons[p.id] ?? ""} maxLength={2000} onChange={e => setReasons({ ...reasons, [p.id]: e.target.value })} /></label>
          <button disabled={busy || !!error || !(reasons[p.id] ?? "").trim()} onClick={() => void operate(async () => {
            await managed(`/conversations/${id}/proposals/${p.id}/dismiss`, { expected_version: v, reason: reasons[p.id] } satisfies S["ChatProposalDismissCreate"]);
          })}>{t("chat.proposal.dismiss")}</button></div>}
        <Evidence title={t("chat.proposal.evidence")} value={p} /></div>;
    })}

    <h3>{t("chat.message.title")}</h3>
    <p className="hint">{t("chat.message.hint")}</p>
    <div className="command-list" aria-label={t("chat.commands")}>{commandNames.map(name => <button type="button" key={name} className="button-quiet mono" onClick={() => { setText(`/${name}${name === "tarea" ? " " : ""}`); setCommand(undefined); }}>/{name}</button>)}</div>
    {!conversation.actions.includes("message") && <p>{t("chat.message.pending")}</p>}
    <form onSubmit={e => { e.preventDefault(); if (canSend && text.trim()) void operate(async () => {
      if (isCommand(text)) {
        const preview = await managed<S["ChatCommandRead"]>(`/conversations/${id}/commands/preview`, { expected_version: v, text } satisfies S["ChatCommandCreate"]);
        if (preview.name !== "tarea") { setCommand(preview); setText(""); return; }
      }
      await send(jobRequest(`/conversations/${id}/messages`, { expected_version: v, text, documents: lines(documents).length ? lines(documents) : null, run_ids: lines(runIds) }));
      setText(""); setCommand(undefined);
    }); }}>
      <label>{t("chat.message")}<textarea rows={4} value={text} maxLength={20000} onChange={e => { setText(e.target.value); setCommand(undefined); }} /></label>
      <div className="form-row"><label>{t("chat.message.documents")}<textarea rows={2} value={documents} onChange={e => setDocuments(e.target.value)} /></label>
        <label>{t("chat.message.runs")}<textarea rows={2} value={runIds} onChange={e => setRunIds(e.target.value)} /></label></div>
      <button disabled={!canSend || !text.trim()}>{isCommand(text) ? t("chat.message.prepare") : t("chat.message.send")}</button>
    </form>
    {command && <section className="decision chat-command" aria-label={t("chat.command.result", { command: `/${command.name}` })}>
      <div className="actions"><h3 className="mono">/{command.name}</h3><button type="button" className="button-quiet" onClick={() => setCommand(undefined)}>{t("chat.command.close")}</button></div>
      <p className="hint">{t("chat.command.hint")}</p>
      <ChatCommand key={command.preview_sha256} command={command} />
    </section>}
  </section>;
}
