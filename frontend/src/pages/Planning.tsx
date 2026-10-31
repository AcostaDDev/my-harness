import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { unifiedDiff } from "../diff.ts";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { createOnce, jobRequest, managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import type { Route } from "../router";
import { ProfileProposal, ProfileReplay, ProjectProfile } from "./ProjectProfile";
import { Preparation } from "./Preparation";
import { Link, navigate } from "../navigation";
import { Alert, DiffBlock, Empty, Evidence, Fields, Hash, Loading, PageHeader, Stale, Status, Workbench, message, usePoll, when } from "../ui";
import { useWorkspace } from "../workspace";
import { EditProgress, MarkdownView } from "./Docs";
import { recipeText } from "../preparation.ts";
import { LiveActivity } from "../Activity";
import { QuestionAnswers } from "./Answers";
import { IntakeReview } from "./IntakeReview";
import { ProposalBatch } from "./ProposalBatch";

// Conversational creation and planning in the UI (H6.2 E4) over the H6.5 API (D075).
// The agent never writes: each draft is applied or edited with CAS on the hash shown, and the acceptance
// and the plan are confirmed on the exact preview. Nothing is written while typing or reloading.

type Conversation = S["PlanningConversationRead"];
type Summary = S["PlanningConversationSummaryRead"];
type Proposal = S["PlanningProposalRead"];
type Turn = S["PlanningTurnRead"];
type Drafts = S["PlanningDraftsRead"];
type DraftRead = S["PlanningDraftContentRead"];
type Acceptance = S["DefinitionPreviewRead"];
type Operation = S["DefinitionOperationRead"];
type TurnResult = { answer?: string; questions?: { text: string; blocking: boolean }[]; pending?: string[];
  drafts?: { path: string; reason: string }[]; plan?: { reason: string } | null };

const q = encodeURIComponent;
type ToneValue = [MessageKey, "active" | "ok" | "danger" | "neutral" | "attention"];
const TURN: Record<Turn["status"], ToneValue> = {
  QUEUED: ["chat.turn.queued", "active"], ANSWERED: ["chat.turn.answered", "ok"], FAILED: ["chat.turn.failed", "danger"],
  UNKNOWN: ["chat.turn.unknown", "attention"], REFUSED: ["chat.turn.refused", "neutral"],
};
const PROPOSAL: Record<Proposal["status"], ToneValue> = {
  PROPOSED: ["chat.proposal.proposed", "attention"], APPLIED: ["planning.proposal.applied", "ok"], ACCEPTED: ["planning.proposal.accepted", "ok"],
  DISMISSED: ["chat.proposal.dismissed", "neutral"], SUPERSEDED: ["planning.proposal.superseded", "neutral"],
};
const ORIGIN: Record<S["DefinitionDocumentRead"]["origin"], MessageKey> = {
  draft: "planning.origin.draft", "draft+blocks": "planning.origin.draft_blocks", template: "planning.origin.template",
  archive: "planning.origin.archive",
};
const STEPS: MessageKey[] = ["planning.step.brief", "planning.step.conversation", "planning.step.acceptance", "planning.step.first_task"];

function draftRoute(conversation: Conversation, project: string, path?: string): Route {
  return conversation.kind === "onboarding" ? { name: "onboarding", project, conversation: conversation.id, path }
    : { name: "setup", project, path };
}

function Tone({ value }: { value: ToneValue }) {
  const { t } = useI18n();
  return <span className={`status status-${value[1]}`}><span className="status-mark" aria-hidden="true" />{t(value[0])}</span>;
}

/** Creation steps on the same track as the phase lifecycle: where it is and what is missing. */
function Steps({ current }: { current: number }) {
  const { t } = useI18n();
  const labels = STEPS.map(key => t(key));
  return <div className="rail" role="img" aria-label={t("planning.steps", { step: current + 1, total: labels.length, label: labels[Math.min(current, labels.length - 1)] })}>
    <ol className="rail-track">{labels.map((label, index) => <li key={label} className={index < current ? "rail-past" : index === current ? "rail-now" : "rail-next"}>
      <span className="rail-stop" aria-hidden="true" /><span className="rail-label">{label}</span></li>)}</ol>
  </div>;
}

function conflictText(error: unknown) {
  return error instanceof ManagedError && error.status === 409 ? message(error) : undefined;
}

// --- shared conversation -----------------------------------------------------------------------

function TurnList({ conversation }: { conversation: Conversation }) {
  const { t, n, rich } = useI18n();
  if (!conversation.turns.length) return <p className="hint">{t("planning.turns.empty")}</p>;
  return <ol className="entry-list">{conversation.turns.map(turn => {
    const result = (turn.result?.result ?? null) as TurnResult | null;
    const reasons = Array.isArray(turn.result?.reasons) ? turn.result!.reasons as string[] : [];
    const run = <Link to={{ name: "run-short", run: turn.run_id }}>{t("trail.run", { id: turn.run_id.slice(0, 8) })}</Link>;
    return <li className="entry turn" key={turn.id}>
      <p className="turn-head"><strong>{t("chat.turn", { number: turn.number })}</strong> <Tone value={TURN[turn.status]} /> <span className="muted">{when(turn.created_at)}</span></p>
      <p className="turn-message">{turn.message}</p>
      {turn.status === "QUEUED" && turn.run_status === "RECOVERY_REQUIRED" && <p className="state state-attention">{rich("planning.turn.interrupted", { run })}</p>}
      {result?.answer && <p className="turn-answer">{result.answer}</p>}
      {!!result?.drafts?.length && <p className="hint">{t(turn.status === "ANSWERED" ? "planning.turn.drafts" : "planning.turn.rejected_drafts")} {result.drafts.map(d => <code key={d.path} className="chip">{d.path}</code>)}</p>}
      {result && "plan" in result && <p className="hint">{result.plan ? t("planning.turn.plan") : t("planning.turn.no_plan")}</p>}
      {reasons.length > 0 && <p className="state state-error">{reasons.join("; ")}</p>}
      <p className="hint">
        {run} <Status value={turn.run_status} />
        {" "}· {rich("planning.turn.context", { hash: <Hash value={turn.context_sha256} /> })}
        {turn.drafts.length > 0 && <> · {n("planning.turn.frozen_drafts", turn.drafts.length)}</>}
        {turn.documents.length > 0 && <> · {n("planning.turn.frozen_documents", turn.documents.length)}</>}
        {turn.user_edits.length > 0 && <> · {n("planning.turn.user_edits", turn.user_edits.length)}</>}
      </p>
      <Evidence title={t("planning.turn.evidence")} value={turn} />
    </li>;
  })}</ol>;
}

function MessageForm({ conversation, path, hint }: { conversation: Conversation; path: string; hint: ReactNode }) {
  const { t } = useI18n();
  const { busy, operate, send } = useWorkspace();
  const [text, setText] = useState("");
  const pending = conversation.turns.some(t => t.status === "QUEUED");
  const open = conversation.actions.includes("message");
  // Free follow-up beside the question answers: it never carries their drafts, so nothing is sent twice.
  const questions = conversation.questions.length > 0;
  return <form className="composer" onSubmit={e => { e.preventDefault(); if (open && text.trim()) void operate(async () => {
    await send(jobRequest(path, { expected_version: conversation.version, text } satisfies S["PlanningMessageCreate"]));
    setText("");
  }); }}>
    <label>{questions ? t("planning.message.other") : t("planning.message")}<textarea rows={4} value={text} maxLength={20000} onChange={e => setText(e.target.value)} disabled={!open} /></label>
    {questions && <p className="hint">{t("planning.message.other_hint")}</p>}
    <p className="hint">{hint}</p>
    {pending && <p role="status" className="state state-loading">{t("planning.message.pending")}</p>}
    <button disabled={busy || !open || !text.trim()}>{t("planning.message.send")}</button>
  </form>;
}

function Dismiss({ conversation, proposal, base }: { conversation: Conversation; proposal: Proposal; base: string }) {
  const { t } = useI18n();
  const { busy, operate } = useWorkspace();
  const [reason, setReason] = useState("");
  if (!proposal.actions.includes("dismiss")) return null;
  return <div className="form-row">
    <label>{t("chat.proposal.dismiss_reason")}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
    <button type="button" className="button-quiet" disabled={busy || !reason.trim()} onClick={() => void operate(async () => {
      await managed(`${base}/proposals/${proposal.id}/dismiss`, { expected_version: conversation.version, reason } satisfies S["PlanningDismissCreate"]);
    })}>{t("planning.proposal.dismiss")}</button>
  </div>;
}

// --- creation: /projects/:p/setup ----------------------------------------------------------------

export function SetupPage({ path }: { path?: string }) {
  const { t, rich } = useI18n();
  const { project, refresh } = useWorkspace();
  const info = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 0);
  const v2 = info.data?.documents === "v2";
  const status = usePoll<S["BootstrapStatusRead"]>(v2 ? `/projects/${project}/bootstrap` : null, 4000, refresh);
  const list = usePoll<Summary[]>(v2 ? `/projects/${project}/planning` : null, 4000, refresh);
  if (!info.data) return info.error ? <Alert>{info.error}</Alert> : <Loading />;
  if (!v2) return <>
    <PageHeader title={t("planning.setup.title")} />
    <Empty title={t("docs.legacy.title")}>
      <p>{t("planning.setup.legacy")} <Link to={{ name: "project", project }}>{t("planning.back_to_summary")}</Link></p>
    </Empty>
  </>;
  if (!status.data || !list.data) return status.error ?? list.error ? <Alert>{status.error ?? list.error}</Alert> : <Loading />;
  const definition = list.data.find(c => c.kind === "definition");
  if (definition) return <Definition key={definition.id} id={definition.id} path={path} status={status.data} />;
  if (status.data.definition_operation) return <Empty title={t("planning.setup.created")}><p><Link to={{ name: "project", project }}>{t("planning.back_to_summary")}</Link></p></Empty>;
  if (!status.data.enabled) return <>
    <PageHeader title={t("planning.setup.title")} />
    <Empty title={t("planning.setup.unauthorized")}>
      <p>{rich("planning.setup.unauthorized_body", { flag: <code>bootstrap_enabled</code>, section: <code>[registration]</code> })}</p>
    </Empty>
  </>;
  return <BriefForm status={status.data} />;
}

function BriefForm({ status }: { status: S["BootstrapStatusRead"] }) {
  const { t, n, rich } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const key = `harness-setup-brief-v1:${project}`;
  const [title, setTitle] = useState(() => { try { return JSON.parse(sessionStorage.getItem(key) ?? "null")?.title ?? ""; } catch { return ""; } });
  const [brief, setBrief] = useState(() => { try { return JSON.parse(sessionStorage.getItem(key) ?? "null")?.brief ?? ""; } catch { return ""; } });
  const [view, setView] = useState<"edit" | "preview">("edit");
  useEffect(() => { try { sessionStorage.setItem(key, JSON.stringify({ title, brief })); } catch { /* no draft */ } }, [key, title, brief]);
  const bytes = new TextEncoder().encode(brief).length;
  return <>
    <PageHeader title={t("planning.brief.page")}>
      <p>{t("planning.brief.lede")}</p>
    </PageHeader>
    <Steps current={0} />
    {status.import_required && <p role="alert" className="state state-attention">{status.diagnostic}</p>}
    <section className="panel" aria-labelledby="brief-title">
      <h2 id="brief-title">{t("planning.step.brief")}</h2>
      <p className="hint">{rich("planning.brief.hint", { path: <code>archive/phase-000/BRIEF.md</code> })}</p>
      <form onSubmit={e => { e.preventDefault(); void operate(async () => {
        await createOnce<Conversation>(`/projects/${project}/planning`, { structured: true, kind: "definition", title: title.trim(), brief, phase_id: null } satisfies S["PlanningConversationCreate"]);
        try { sessionStorage.removeItem(key); } catch { /* no draft */ }
      }); }}>
        <label>{t("planning.brief.name")}<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} required /></label>
        <div className="docs-editor-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={view === "edit"} className={view === "edit" ? "" : "button-quiet"} onClick={() => setView("edit")}>{t("docs.editor.write")}</button>
          <button type="button" role="tab" aria-selected={view === "preview"} className={view === "preview" ? "" : "button-quiet"} onClick={() => setView("preview")}>{t("docs.review.preview")}</button>
        </div>
        {view === "edit" ? <label><span className="visually-hidden">{t("planning.brief.markdown")}</span><textarea rows={16} value={brief} onChange={e => setBrief(e.target.value)} spellCheck
            placeholder={t("planning.brief.placeholder")} /></label>
          : <article className="doc-reader">{brief.trim() ? <MarkdownView source={brief} path="docs/BRIEF.md" /> : <p className="hint">{t("planning.brief.nothing")}</p>}</article>}
        <p className="hint">{n("planning.bytes", bytes)}{bytes > 256 * 1024 ? ` · ${t("planning.brief.too_large")}` : ""}</p>
        <button disabled={busy || !title.trim() || !brief.trim() || bytes > 256 * 1024 || status.import_required}>{t("planning.brief.start")}</button>
      </form>
    </section>
  </>;
}

function Definition({ id, path, status }: { id: string; path?: string; status: S["BootstrapStatusRead"] }) {
  const { t, n } = useI18n();
  const { project, refresh } = useWorkspace();
  const base = `/projects/${project}/planning/${id}`;
  const read = usePoll<Conversation>(base, 1500, refresh);
  const c = read.data;
  const drafts = usePoll<Drafts>(c && !c.structured && !c.created ? `${base}/drafts` : null, 3000, refresh);
  if (!c) return read.error ? <Alert>{read.error}</Alert> : <Loading />;
  if (c.structured) return <IntakeReview conversation={c} base={base} />;
  const op = c.operation ?? status.definition_operation ?? null;
  const proposed = c.proposals.filter(p => p.status === "PROPOSED" || !c.created && p.kind === "profile" && p.status === "ACCEPTED");
  const step = op?.status === "COMPLETED" ? 3 : op ? 2 : 1;
  return <div className="docs-layout">
    <DraftTree conversation={c} drafts={drafts.data} current={path} error={drafts.error} />
    <div className="docs-main">
      {path && !c.created ? <DraftPage key={path} conversation={c} path={path} drafts={drafts.data} />
        : <>
          <PageHeader title={c.title} aside={c.created ? <span className="status status-ok"><span className="status-mark" aria-hidden="true" />{t("planning.created")}</span> : undefined}>
            <p>{t("planning.definition.lede")}</p>
          </PageHeader>
          <Stale error={read.error} />
          <Steps current={step} />
          <Workbench aside={<ConversationRail conversation={c} />} label={t("planning.rail")}>
          {op?.status !== "COMPLETED" && <ProfileReplay />}
          {op?.status === "COMPLETED" && <><ProjectProfile /><LegacyPreparation /></>}
          {op && <OperationPanel conversation={c} op={op} />}
          <QuestionAnswers conversation={c} base={base} />
          <section className="panel" aria-labelledby="def-turns">
            <h2 id="def-turns">{t("planning.conversation")} <span className="count">{n("chat.turns", c.turns.length)}</span></h2>
            <TurnList conversation={c} />
            {!c.created && drafts.data?.drafts.length === 0 && <p className="hint">{t("planning.definition.new_folder")}</p>}
            {!c.created && <MessageForm conversation={c} path={`${base}/messages`} hint={t("planning.definition.message_hint")} />}
          </section>
          <BriefPanel base={base} brief={c.brief} />
          {(proposed.length > 0 || c.proposals.length > 0) && <section className="panel" aria-labelledby="def-proposals">
            <h2 id="def-proposals">{t("planning.proposals")} <span className="count">{n("planning.proposals.pending", proposed.length)}</span></h2>
            {proposed.length === 0 && <p className="hint">{t("planning.proposals.empty")}</p>}
            <ProposalBatch conversation={c} base={base} />
            {proposed.map(p => <ProposalEntry key={p.id} conversation={c} proposal={p} base={base} drafts={drafts.data} />)}
            <ProposalHistory proposals={c.proposals.filter(p => p.status !== "PROPOSED")} />
          </section>}
          {!c.created && !op && <AcceptPanel conversation={c} base={base} drafts={drafts.data} />}
          </Workbench>
        </>}
    </div>
  </div>;
}

function BriefPanel({ base, brief }: { base: string; brief: Conversation["brief"] }) {
  const { t, n, rich } = useI18n();
  const [open, setOpen] = useState(false);
  const read = usePoll<S["PlanningBriefRead"]>(open ? `${base}/brief` : null, 0);
  return <details className="panel panel-collapsible" onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
    <summary><h2>{t("planning.brief.frozen")}</h2></summary>
    <p className="hint">{rich("planning.brief.hash", { hash: <Hash value={brief ? String(brief.sha256) : null} /> })} · {brief ? n("planning.bytes", Number(brief.size)) : ""}</p>
    {open && (read.data ? <article className="doc-reader"><MarkdownView source={read.data.content} path="docs/BRIEF.md" /></article> : read.error ? <Alert>{read.error}</Alert> : <Loading />)}
  </details>;
}

/** Right rail of a documentary conversation: what its latest turn is doing and where the conversation stands. */
function ConversationRail({ conversation }: { conversation: Conversation }) {
  const { t } = useI18n();
  const { refresh } = useWorkspace();
  const latest = conversation.turns.reduce<Turn | undefined>((last, turn) => !last || turn.number > last.number ? turn : last, undefined);
  const blocking = conversation.questions.filter(q => q.blocking && !q.deferred).length;
  const proposals = conversation.proposals.filter(p => p.status === "PROPOSED").length;
  return <>
    {latest ? <LiveActivity runId={latest.run_id} status={latest.run_status} refresh={refresh} title={t("activity.title.turn", { number: latest.number })} />
      : <section className="activity" aria-labelledby="rail-activity"><div className="activity-head"><h2 id="rail-activity">{t("activity.title")}</h2></div>
        <p className="hint">{t("activity.no_turns")}</p></section>}
    <section className="rail-panel" aria-labelledby="rail-status">
      <h2 id="rail-status">{t("planning.rail.status")}</h2>
      <dl className="rail-stats">
        <div className={blocking ? "rail-stat rail-stat-attention" : "rail-stat"}><dt>{t("planning.rail.blocking")}</dt><dd>{blocking}</dd></div>
        <div className="rail-stat"><dt>{t("planning.rail.informative")}</dt><dd>{conversation.questions.filter(q => !q.blocking).length}</dd></div>
        <div className={proposals ? "rail-stat rail-stat-attention" : "rail-stat"}><dt>{t("planning.rail.proposals")}</dt><dd>{proposals}</dd></div>
        <div className="rail-stat"><dt>{t("planning.rail.turns")}</dt><dd>{conversation.turns.length}</dd></div>
      </dl>
      <p className="hint">{conversation.created ? t("planning.rail.closed") : t("planning.rail.version", { version: conversation.version })}</p>
    </section>
  </>;
}

function ProposalHistory({ proposals }: { proposals: Proposal[] }) {
  const { t } = useI18n();
  if (!proposals.length) return null;
  return <details className="evidence"><summary>{t("planning.proposals.history", { count: proposals.length })}</summary>
    <ul className="docs-changes">{proposals.map(p => <li key={p.id}>
      <span className="mono">#{p.number}</span> {p.path ? <code className="path">{p.path}</code> : t("planning.plan")} <Tone value={PROPOSAL[p.status]} />
      <span className="muted"> · {t("planning.turn_number", { number: p.turn_number })}{p.decision?.reason ? ` · ${String(p.decision.reason)}` : ""}</span></li>)}</ul>
  </details>;
}

/** Current content of a draft (null if it does not exist) through the same inspection as the CAS. */
function useDraft(conversation: string, path: string | null, refresh: number, interval = 0) {
  const { project } = useWorkspace();
  const read = usePoll<DraftRead>(path ? `/projects/${project}/planning/${conversation}/drafts/content?path=${q(path)}` : null, interval, refresh);
  return { draft: read.data, missing: read.missing, error: read.missing ? undefined : read.error, loading: read.loading };
}

function ProposalEntry({ conversation, proposal, base, drafts }: { conversation: Conversation; proposal: Proposal; base: string; drafts?: Drafts }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const [open, setOpen] = useState(false);
  if (proposal.kind === "profile") return <ProfileProposal conversation={conversation} proposal={proposal} base={base} />;
  const disk = drafts?.drafts.find(d => d.path === proposal.path);
  const moved = disk && disk.sha256 !== proposal.base_sha256 && disk.sha256 !== proposal.content_sha256;
  return <div className="entry entry-open">
    <p><strong>#{proposal.number}</strong> <Link to={draftRoute(conversation, project, proposal.path!)}><code className="path">{proposal.path}</code></Link>{" "}
      <span className="muted">· {t("planning.turn_number", { number: proposal.turn_number })} · {proposal.base_sha256 ? t("planning.proposal.replaces") : t("planning.proposal.new_document")}</span></p>
    <p>{proposal.reason}</p>
    {moved && <p className="state state-attention">{t("planning.proposal.moved")}</p>}
    <details onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}><summary>{t("planning.proposal.review")}</summary>
      {open && <ProposalReview conversation={conversation} proposal={proposal} base={base} />}
    </details>
  </div>;
}

/** Diff from the draft on disk to the proposal and confirmation bound to its hash; the harness writes with CAS. */
function ProposalReview({ conversation, proposal, base }: { conversation: Conversation; proposal: Proposal; base: string }) {
  const { t, rich } = useI18n();
  const { busy, refresh, operate } = useWorkspace();
  const { draft, missing, error } = useDraft(conversation.id, proposal.path, refresh);
  const [confirmed, setConfirmed] = useState(false);
  const [conflict, setConflict] = useState<string>();
  const [view, setView] = useState<"diff" | "render">("diff");
  useEffect(() => { setConfirmed(false); }, [conversation.version, draft?.sha256]);
  if (error) return <Alert>{error}</Alert>;
  if (!draft && !missing) return <Loading />;
  const current = draft?.content ?? null;
  const diff = unifiedDiff(proposal.path!, current, proposal.content, t("diff.eol"));
  const canApply = proposal.actions.includes("apply");
  return <div className="docs-review">
    <Fields items={[[t("planning.review.disk"), draft ? <Hash value={draft.sha256} /> : t("planning.review.missing")], [t("planning.review.read"), proposal.base_sha256 ? <Hash value={proposal.base_sha256} /> : t("planning.review.did_not_exist")],
      [t("planning.review.proposed"), <Hash value={proposal.content_sha256} />], [t("planning.review.proposal"), <Hash value={proposal.proposal_sha256} />]]} />
    <div className="docs-editor-tabs" role="tablist">
      <button type="button" role="tab" aria-selected={view === "diff"} className={view === "diff" ? "" : "button-quiet"} onClick={() => setView("diff")}>{t("planning.review.diff")}</button>
      <button type="button" role="tab" aria-selected={view === "render"} className={view === "render" ? "" : "button-quiet"} onClick={() => setView("render")}>{t("planning.review.document")}</button>
    </div>
    {view === "render" ? <article className="doc-reader"><MarkdownView source={proposal.content} path={proposal.path!} /></article>
      : diff === null ? <p className="hint">{t("planning.review.too_large")}</p>
        : diff === "" ? <p className="hint">{t("planning.review.same")}</p>
          : <DiffBlock diff={diff} label={t("planning.review.diff_label", { path: proposal.path ?? "" })} />}
    {conflict && <p role="alert" className="state state-error">{conflict}</p>}
    {canApply && <>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{rich("planning.review.confirm", { hash: proposal.proposal_sha256.slice(0, 12), path: <code>{proposal.path}</code> })}</label>
      <div className="actions"><button type="button" disabled={busy || !confirmed} onClick={() => void operate(async () => {
        setConflict(undefined);
        try {
          await managed(`${base}/proposals/${proposal.id}/apply`, { expected_version: conversation.version, proposal_sha256: proposal.proposal_sha256, confirmed: true } satisfies S["PlanningApplyCreate"]);
        } catch (e) { const text = conflictText(e); if (text) setConflict(t("planning.review.not_applied", { error: text })); else throw e; }
      })}>{t("planning.review.apply")}</button></div>
    </>}
    <Dismiss conversation={conversation} proposal={proposal} base={base} />
  </div>;
}

// --- drafts --------------------------------------------------------------------------------------

function matchesPattern(path: string, patterns: string[]) {
  return patterns.some(pattern => {
    const folder = pattern.slice(0, -"/*.md".length);
    const name = path.slice(folder.length + 1);
    return path.startsWith(`${folder}/`) && name.endsWith(".md") && !name.includes("/") && name.length > 3;
  });
}

function DraftTree({ conversation, drafts, current, error }: { conversation: Conversation; drafts?: Drafts; current?: string; error?: string }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const pending = new Set(conversation.proposals.filter(p => p.status === "PROPOSED").map(p => p.path));
  const present = new Map(drafts?.drafts.filter(d => d.sha256).map(d => [d.path, d]));
  const required = new Set(drafts?.allowed.required);
  const paths = [...new Set([...(drafts?.allowed.fixed ?? []), ...present.keys(), ...[...pending].filter(Boolean) as string[]])].sort();
  // Documentation folder (STATE's): tree names are relative to it; the full path goes in the title.
  const docsFolder = drafts?.allowed.required.find(p => p.endsWith("/STATE.md"))?.slice(0, -"/STATE.md".length);
  return <nav className="docs-tree" aria-label={t("planning.drafts")}>
    <p className="docs-tree-title"><Link to={draftRoute(conversation, project)} current={!current}>{conversation.kind === "onboarding" ? t("trail.onboarding") : t("purpose.definition")}</Link></p>
    {conversation.created ? <p className="hint">{conversation.kind !== "definition" ? t("planning.drafts.onboarded") : t("planning.drafts.created")} <Link to={{ name: "docs", project }}>{t("nav.docs")}</Link></p>
      : !drafts ? (error ? <Alert>{error}</Alert> : <Loading />) : <>
        <ul className="docs-tree-list">{paths.map(path => {
          const draft = present.get(path);
          return <li key={path}><Link to={draftRoute(conversation, project, path)} current={path === current} className="docs-tree-file">
            <span className={draft ? "docs-tree-name" : "docs-tree-name muted"} title={path}>{docsFolder && path.startsWith(`${docsFolder}/`) ? path.slice(docsFolder.length + 1) : path}</span>
            {pending.has(path) && <span className="docs-flag docs-flag-local" title={t("planning.flag.proposal_hint")}>{t("planning.flag.proposal")}</span>}
            {draft?.user_edited && <span className="docs-flag docs-flag-drift" title={t("planning.flag.edited_hint")}>{t("planning.flag.edited")}</span>}
            {!draft && required.has(path) && <span className="docs-flag" title={t("planning.flag.required_hint")}>{t("docs.flag.missing")}</span>}
          </Link></li>;
        })}</ul>
        {drafts.invalid.length > 0 && <p className="hint">{t("planning.drafts.invalid")} {drafts.invalid.map(p => <code key={p} className="chip">{p}</code>)}</p>}
        {drafts.foreign.length > 0 && <div className="docs-tree-missing"><p className="hint">{t("planning.drafts.foreign")}</p>
          <ul className="docs-tree-list">{drafts.foreign.map(p => <li key={p}><code className="path">{p}</code></li>)}</ul>
          {drafts.foreign_truncated && <p className="hint">{t("planning.drafts.truncated")}</p>}</div>}
        <NewDraft conversation={conversation} patterns={drafts.allowed.patterns} existing={new Set(paths)} />
      </>}
  </nav>;
}

function NewDraft({ conversation, patterns, existing }: { conversation: Conversation; patterns: string[]; existing: Set<string> }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const [path, setPath] = useState("");
  const valid = matchesPattern(path.trim(), patterns) && !existing.has(path.trim());
  return <form className="docs-new" onSubmit={e => { e.preventDefault(); if (valid) navigate(draftRoute(conversation, project, path.trim())); }}>
    <label>{t("planning.draft.new")}<input value={path} onChange={e => setPath(e.target.value)} placeholder={patterns[0]?.replace("*", "D002-title")} maxLength={400} /></label>
    <p className="hint">{t("planning.draft.allowed")} {patterns.map(p => <code key={p} className="chip">{p}</code>)}</p>
    <button className="button-quiet" disabled={!valid}>{t("planning.draft.create")}</button>
  </form>;
}

type Edit = { base: string | null; text: string };

function loadEdit(key: string): Edit | undefined {
  try { return JSON.parse(sessionStorage.getItem(key) ?? "null") ?? undefined; } catch { return undefined; }
}
function saveEdit(key: string, value?: Edit) {
  try { if (value) sessionStorage.setItem(key, JSON.stringify(value)); else sessionStorage.removeItem(key); } catch { /* no saved draft */ }
}

function DraftPage({ conversation, path, drafts }: { conversation: Conversation; path: string; drafts?: Drafts }) {
  const { t, rich } = useI18n();
  const { project, refresh } = useWorkspace();
  const base = `/projects/${project}/planning/${conversation.id}`;
  // Reread: an edit on disk shows up (and the editor warns about it) before trying to save.
  const { draft, missing, error } = useDraft(conversation.id, path, refresh, 3000);
  const key = conversation.kind === "onboarding" ? `harness-onboarding-draft-v1:${project}:${conversation.id}:${path}`
    : `harness-setup-draft-v1:${project}:${path}`;
  const [editing, setEditing] = useState(() => !!loadEdit(key));
  const state = drafts?.drafts.find(d => d.path === path);
  const allowed = !!drafts && (drafts.allowed.fixed.includes(path) || matchesPattern(path, drafts.allowed.patterns));
  const proposal = conversation.proposals.find(p => p.status === "PROPOSED" && p.path === path);
  const canEdit = conversation.actions.includes("edit_draft");
  const blocked = canEdit ? undefined : conversation.turns.some(turn => turn.status === "QUEUED") ? t("planning.draft.turn_running") : t("planning.draft.closed");
  const name = path.split("/").pop()!;
  if (error) return <><PageHeader title={name} code><p><code className="path">{path}</code></p></PageHeader><Alert>{error}</Alert></>;
  if (!draft && !missing) return <Loading />;
  return <>
    <PageHeader title={name} code aside={!editing && canEdit && allowed && <button type="button" onClick={() => setEditing(true)}>{draft ? t("docs.document.edit") : t("planning.draft.create_short")}</button>}>
      <p><code className="path">{path}</code>{draft && <> · <Hash value={draft.sha256} /></>}{drafts?.allowed.required.includes(path) && ` · ${t("planning.draft.required")}`}</p>
    </PageHeader>
    {drafts && !allowed && <p className="state state-attention">{t("planning.draft.not_allowed")}</p>}
    {state?.user_edited && <p className="state state-neutral" role="status">{rich("planning.draft.edited", { before: <Hash value={state.known_sha256} length={8} />, after: <Hash value={state.sha256} length={8} /> })}</p>}
    {blocked && <p className="hint">{blocked}</p>}
    {proposal && <section className="decision decision-attention" aria-labelledby="draft-proposal">
      <h2 id="draft-proposal">{t("planning.draft.proposal", { number: proposal.number, turn: proposal.turn_number })}</h2>
      <p>{proposal.reason}</p>
      <ProposalReview conversation={conversation} proposal={proposal} base={base} />
    </section>}
    {editing ? <DraftEditor conversation={conversation} path={path} draft={draft ?? null} editKey={key} blocked={blocked} onClose={() => setEditing(false)} />
      : draft ? <article className="doc-reader"><MarkdownView source={draft.content} path={path} /></article>
        : <Empty title={t("planning.draft.missing")}><p>{allowed ? t("planning.draft.missing_hint") : t("planning.draft.back")}</p></Empty>}
  </>;
}

/** Draft editor: full text, preview and diff; saved with CAS on the hash it was opened with. */
function DraftEditor({ conversation, path, draft, editKey, blocked, onClose }: {
  conversation: Conversation; path: string; draft: DraftRead | null; editKey: string; blocked?: string; onClose: () => void;
}) {
  const { t, rich } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const [edit, setEdit] = useState<Edit>(() => loadEdit(editKey) ?? { base: draft?.sha256 ?? null, text: draft?.content ?? "" });
  const [view, setView] = useState<"edit" | "preview" | "review">("edit");
  const [confirmed, setConfirmed] = useState(false);
  const [conflict, setConflict] = useState<string>();
  const [removing, setRemoving] = useState(false);
  useEffect(() => { saveEdit(editKey, edit); }, [editKey, edit]);
  useEffect(() => { setConfirmed(false); }, [edit.text, view, removing]);
  const stale = edit.base !== (draft?.sha256 ?? null);
  const after = removing ? null : edit.text;
  const diff = unifiedDiff(path, draft?.content ?? null, after, t("diff.eol"));
  function close() { saveEdit(editKey); onClose(); }
  async function save() {
    setConflict(undefined);
    try {
      await managed(`/projects/${project}/planning/${conversation.id}/drafts`,
        { expected_version: conversation.version, path, content: after, base_sha256: edit.base } satisfies S["PlanningDraftEdit"], undefined, "PUT");
      close();
    } catch (e) {
      const text = conflictText(e);
      if (!text) throw e;
      setConflict(e instanceof ManagedError && e.code === "draft_changed" ? t("planning.editor.conflict") : text);
    }
  }
  const blocks = /<!-- harness-local:managed-[a-z-]+:(start|end) -->/.test(edit.text);
  return <section className="docs-editor" aria-label={t("docs.editor.label", { path })}>
    {stale && <p className="state state-attention" role="status">{rich("planning.editor.stale", { base: <Hash value={edit.base} length={8} />, current: <Hash value={draft?.sha256} length={8} /> })}</p>}
    {blocks && <p className="hint">{rich("planning.editor.blocks", { marker: <code>harness-local:managed-…</code> })}</p>}
    <div className="docs-editor-tabs" role="tablist">
      <button type="button" role="tab" aria-selected={view === "edit"} className={view === "edit" ? "" : "button-quiet"} onClick={() => setView("edit")}>{t("docs.editor.write")}</button>
      <button type="button" role="tab" aria-selected={view === "preview"} className={view === "preview" ? "" : "button-quiet"} onClick={() => setView("preview")}>{t("docs.review.preview")}</button>
      <button type="button" role="tab" aria-selected={view === "review"} className={view === "review" ? "" : "button-quiet"} onClick={() => setView("review")}>{t("planning.editor.review")}</button>
    </div>
    {view === "edit" && <label className="docs-editor-prose"><span className="visually-hidden">{t("planning.editor.content", { path })}</span>
      <textarea value={edit.text} spellCheck rows={Math.min(36, Math.max(16, edit.text.split("\n").length + 1))} onChange={e => { setRemoving(false); setEdit({ ...edit, text: e.target.value }); }} /></label>}
    {view === "preview" && <article className="doc-reader"><MarkdownView source={edit.text} path={path} /></article>}
    {view === "review" && <div className="docs-review">
      {diff === null ? <p className="hint">{t("planning.editor.too_large")}</p> : diff === "" ? <p className="hint">{t("planning.editor.no_changes")}</p> : <DiffBlock diff={diff} label={t("planning.editor.changes", { path })} />}
      {draft && <label className="check"><input type="checkbox" checked={removing} onChange={e => setRemoving(e.target.checked)} />{t("planning.editor.remove")}</label>}
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{rich(removing ? "planning.editor.confirm_remove" : "planning.editor.confirm_write", { path: <code>{path}</code>, base: <Hash value={edit.base} length={8} /> })}</label>
    </div>}
    {conflict && <p role="alert" className="state state-error">{conflict}</p>}
    <div className="actions">
      {view === "review" && <button type="button" disabled={busy || !confirmed || !!blocked || diff === "" || stale} onClick={() => void operate(save)}>{removing ? t("planning.editor.remove_submit") : t("planning.editor.save")}</button>}
      <button type="button" className="button-quiet" disabled={busy} onClick={close}>{edit.text !== (draft?.content ?? "") ? t("planning.editor.discard") : t("docs.editor.close")}</button>
      {blocked && <span className="hint">{blocked}</span>}
    </div>
  </section>;
}

// --- acceptance ------------------------------------------------------------------------------------

function AcceptPanel({ conversation, base, drafts }: { conversation: Conversation; base: string; drafts?: Drafts }) {
  const { t, rich } = useI18n();
  const { busy, operate } = useWorkspace();
  const [preview, setPreview] = useState<Acceptance>();
  const signature = drafts?.drafts.map(d => `${d.path}:${d.sha256}`).join("|");
  // The preview is valid for the conversation version and the bytes on disk it was requested with.
  const shownFor = useRef<string | undefined>(undefined);
  useEffect(() => { if (shownFor.current !== `${conversation.version}/${signature}`) setPreview(undefined); }, [conversation.version, signature]);
  const can = conversation.actions.includes("accept");
  return <section className="panel" aria-labelledby="def-accept">
    <h2 id="def-accept">{t("planning.accept.title")}</h2>
    <p className="hint">{rich("planning.accept.hint", { archive: <code>archive/phase-000/</code> })}</p>
    {!can && <p className="hint">{t("planning.accept.running")}</p>}
    <button type="button" disabled={busy || !can} onClick={() => void operate(async () => {
      const shown = await managed<Acceptance>(`${base}/accept/preview`, {});
      shownFor.current = `${conversation.version}/${signature}`;
      setPreview(shown);
    })}>{preview ? t("registry.review_again") : t("planning.accept.review")}</button>
    {preview && <AcceptReview conversation={conversation} base={base} preview={preview} />}
  </section>;
}

function AcceptReview({ conversation, base, preview, resume }: { conversation: Conversation; base: string; preview: Acceptance; resume?: Operation }) {
  const { t, rich } = useI18n();
  const { busy, operate, send } = useWorkspace();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setConfirmed(false); }, [preview.preview_sha256]);
  const phase = preview.phase as { code: string; objective: string; exit_criteria: string[]; tasks: string[]; tag?: string | null } | null;
  const task = preview.first_task as Record<string, unknown> | null;
  return <div className="docs-review">
    {preview.blockers.length > 0 ? <div className="state state-error" role="alert"><p className="state-title">{t("planning.accept.blocked")}</p>
      <ul>{preview.blockers.map(b => <li key={b}>{b}</li>)}</ul></div>
      : <p className="state state-ok" role="status">{t("planning.accept.ready")}</p>}
    {preview.warnings.length > 0 && <div className="state state-attention"><p className="state-title">{t("planning.accept.warnings")}</p><ul>{preview.warnings.map(w => <li key={w}>{w}</li>)}</ul></div>}
    {phase && <>
      <h3>{rich("chat.conversation.phase", { phase: <span className="mono">{phase.code}</span> })}</h3>
      <p>{phase.objective}</p>
      <ul className="checklist">{phase.exit_criteria.map(c => <li key={c}>{c}</li>)}</ul>
      <Fields items={[[t("stats.tasks"), phase.tasks.map(item => <code key={item} className="chip">{item}</code>)], [t("settings.tag"), phase.tag ? <code>{phase.tag}</code> : <span className="muted">{t("phase.no_tag")}</span>],
        [t("planning.accept.first_task"), task ? <><code>{String(task.task_id)}</code> {task.planner === "agent" ? `· ${t("planning.accept.planner_contract")}` : `· ${t("planning.accept.deterministic_contract")}`}</> : "—"],
        [t("settings.profile"), preview.profile], [t("docs.review.preview"), <Hash value={preview.preview_sha256} />]]} />
    </>}
    {preview.documents.length > 0 && <>
      <h3>{t("planning.accept.files")} <span className="count">{preview.documents.length}</span></h3>
      <ul className="docs-changes">{preview.documents.map(doc => <li key={doc.path}><AcceptedDocument conversation={conversation.id} doc={doc} /></li>)}</ul>
    </>}
    <Evidence title={t("planning.accept.evidence")} value={{ definition: preview.definition, policy: preview.policy, preparation: preview.preparation, validations: preview.validations, versions: preview.versions, git: preview.git, author: preview.author, first_task: preview.first_task }} />
    {preview.ready && <>
      <p className="hint">{t("planning.accept.commit_hint")}</p>
      <label>{t("docs.review.reason")}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} placeholder={t("planning.accept.reason_placeholder")} /></label>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("planning.accept.confirm", { hash: preview.preview_sha256.slice(0, 12) })}</label>
      <button type="button" disabled={busy || !confirmed || !reason.trim()} onClick={() => void operate(() => send(jobRequest(`${base}/accept`, {
        preview_sha256: preview.preview_sha256, confirmed: true, reason,
        resume_operation_id: resume?.id ?? null, expected_version: resume ? resume.expected_version : null,
      } satisfies S["DefinitionAcceptCreate"])))}>{resume ? t("planning.accept.reconcile") : t("planning.brief.page")}</button>
    </>}
  </div>;
}

function AcceptedDocument({ conversation, doc }: { conversation: string; doc: S["DefinitionDocumentRead"] }) {
  const { t, rich } = useI18n();
  const [open, setOpen] = useState(false);
  const after = <Hash value={doc.sha256} length={8} />;
  return <details onToggle={e => setOpen((e.target as HTMLDetailsElement).open)}>
    <summary><code className="path">{doc.path}</code> <span className="muted">· {t(ORIGIN[doc.origin])} · {doc.before_sha256 === doc.sha256 ? rich("planning.accepted.unchanged", { after })
      : doc.before_sha256 ? rich("docs.review.change", { before: <Hash value={doc.before_sha256} length={8} />, after }) : rich("docs.review.new", { after })}</span></summary>
    {open && (doc.origin === "draft+blocks" ? <RegeneratedDiff conversation={conversation} doc={doc} /> : <pre>{doc.content}</pre>)}
  </details>;
}

/** What acceptance changes in a draft: only the regenerated managed blocks. */
function RegeneratedDiff({ conversation, doc }: { conversation: string; doc: S["DefinitionDocumentRead"] }) {
  const { t } = useI18n();
  const { refresh } = useWorkspace();
  const { draft, error } = useDraft(conversation, doc.path, refresh);
  if (error) return <Alert>{error}</Alert>;
  if (!draft) return <Loading />;
  if (draft.sha256 !== doc.before_sha256) return <p className="state state-attention">{t("planning.regenerated.changed")}</p>;
  const diff = unifiedDiff(doc.path, draft.content, doc.content, t("diff.eol"));
  return <>{diff ? <DiffBlock diff={diff} label={t("planning.regenerated.label", { path: doc.path })} /> : <p className="hint">{t("planning.regenerated.none")}</p>}
    <details><summary>{t("preparation.full_content")}</summary><pre>{doc.content}</pre></details></>;
}

function OperationPanel({ conversation, op }: { conversation: Conversation; op: Operation }) {
  const { t, rich } = useI18n();
  const { project, busy, operate, send } = useWorkspace();
  const base = `/projects/${project}/planning/${conversation.id}`;
  const preview = op.preview;
  const task = preview.first_task as { task_id?: string } | null;
  const phase = preview.phase as { code?: string } | null;
  const preparation = usePoll<S["PreparationRead"]>(`/projects/${project}/preparation`, 2000);
  const info = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 2000);
  const preparationRequired = info.data?.configuration_state !== "ACTIVE" || !info.data.versions.project_configuration && preparation.data?.available && !preparation.data.prepared;
  const commit = op.result?.commit ? String(op.result.commit) : undefined;
  return <section className={op.status === "COMPLETED" ? "decision" : "decision decision-attention"} aria-labelledby="def-operation">
    <h2 id="def-operation">{op.status === "COMPLETED" ? t("planning.created") : op.status === "INTERRUPTED" ? t("planning.operation.interrupted") : t("planning.operation.creating")}</h2>
    <Fields items={[[t("runs.column.status"), <><Status value={op.status} /> · <Link to={{ name: "run-short", run: op.run_id }} className="mono">{t("trail.run", { id: op.run_id.slice(0, 8) })}</Link> <Status value={op.run_status} /></>],
      [t("planning.operation.root_commit"), commit ? <Hash value={commit} /> : <span className="muted">{t("phases.commit.pending")}</span>], [t("docs.review.preview"), <Hash value={preview.preview_sha256} />]]} />
    {op.run_status === "RECOVERY_REQUIRED" && <p>{rich("planning.operation.recovery", { run: <Link to={{ name: "run-short", run: op.run_id }}>{t("trail.run", { id: op.run_id.slice(0, 8) })}</Link> })}</p>}
    {op.status === "INTERRUPTED" && <AcceptReview conversation={conversation} base={base} preview={{ ...preview, resume_operation_id: op.id, expected_version: op.expected_version }} resume={op} />}
    {op.status === "COMPLETED" && <>
      <p>{rich("planning.operation.active", { phase: <Link className="mono" to={{ name: "phase", project, phase: phase?.code ?? "P001" }}>{phase?.code ?? "P001"}</Link> })} <Link to={{ name: "docs", project }}>{t("docs.document.back")}</Link></p>
      {preparationRequired && <p className="hint">{recipeText(preparation.data?.recipe, t, "planning.operation.prepare", "planning.operation.prepare_generic")}</p>}
      {op.first_task_run ? <p>{rich("planning.operation.first_task", { task: <Link to={{ name: "run-short", run: op.first_task_run.run_id }} className="mono">{task?.task_id ?? "run"}</Link> })} <Status value={op.first_task_run.status} /></p>
        : task?.task_id && phase?.code && <>
          <p>{rich("planning.operation.queue_hint", { task: <code>{task.task_id}</code> })}</p>
          <button type="button" disabled={busy || preparationRequired} onClick={() => void operate(() => send(jobRequest(`/projects/${project}/runs`, {
            task_id: task.task_id!, phase_id: phase.code!, text: preview.task_text ?? "",
          } satisfies S["RunCreate"])))}>{t("planning.operation.queue")}</button>
        </>}
    </>}
  </section>;
}

// --- active phase planning: /projects/:p/phases/:code/plan -------------------------------------

export function PlanPage({ phase, conversation }: { phase: string; conversation?: string }) {
  const { t, n, rich } = useI18n();
  const { project, busy, refresh, operate } = useWorkspace();
  const read = usePoll<S["PhaseRead"]>(`/projects/${project}/phases/${q(phase)}`, 5000, refresh);
  const list = usePoll<Summary[]>(`/projects/${project}/planning`, 4000, refresh);
  const [title, setTitle] = useState("");
  const data = read.data;
  if (read.missing) return <Empty title={t("planning.plan.missing", { phase })}><p><Link to={{ name: "phases", project }}>{t("nav.phases")}</Link></p></Empty>;
  if (!data || !list.data) return read.error ?? list.error ? <Alert>{read.error ?? list.error}</Alert> : <Loading />;
  const mine = list.data.filter(c => c.kind === "phase_planning" && c.phase_id === data.id);
  const canPlan = data.status === "ACTIVE" && !(data.definition.tasks as string[]).length && !read.error;
  return <>
    <PageHeader title={t("planning.plan.title", { phase })}>
      <p>{rich("planning.plan.lede", { page: <Link to={{ name: "phase", project, phase }}>{t("planning.plan.page", { phase })}</Link> })}</p>
    </PageHeader>
    <Stale error={read.error ?? list.error} />
    <div className="split">
      <nav className="panel split-list" aria-label={t("planning.plan.conversations")}>
        <h2>{t("chat.conversations")}</h2>
        {!mine.length ? <p className="hint">{t("planning.plan.none")}</p> : <ul className="link-list">{mine.map(c => <li key={c.id}>
          <Link to={{ name: "plan", project, phase, conversation: c.id }} current={conversation === c.id}>
            <span className="link-title">{c.title}</span><span className="link-meta">{n("chat.turns", c.turns)} · {when(c.updated_at)}</span></Link></li>)}</ul>}
        <form onSubmit={e => { e.preventDefault(); if (!canPlan) return; void operate(async () => {
          const created = await createOnce<Conversation>(`/projects/${project}/planning`, { structured: false, kind: "phase_planning", title: title.trim(), brief: null, phase_id: data.id } satisfies S["PlanningConversationCreate"]);
          setTitle(""); navigate({ name: "plan", project, phase, conversation: created.id });
        }); }}>
          <label>{t("chat.new")}<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} placeholder={t("planning.plan.placeholder", { phase })} /></label>
          <button className="button-quiet" disabled={busy || !title.trim() || !canPlan}>{t("chat.new.create")}</button>
        </form>
        {(data.status !== "ACTIVE" || !!(data.definition.tasks as string[]).length) && <p className="hint">{t("planning.plan.only_active")}</p>}
      </nav>
      <div className="split-main">
        {conversation ? <PlanConversation key={conversation} id={conversation} phase={phase} writable={canPlan} />
          : <Empty title={t("planning.plan.choose")}><p>{t("planning.plan.choose_hint")}</p></Empty>}
      </div>
    </div>
  </>;
}

function PlanConversation({ id, phase, writable }: { id: string; phase: string; writable: boolean }) {
  const { t, rich } = useI18n();
  const { project, refresh } = useWorkspace();
  const base = `/projects/${project}/planning/${id}`;
  const read = usePoll<Conversation>(base, 1500, refresh);
  const c = read.data;
  if (read.missing) return <Empty title={t("chat.missing.title")}><p>{t("chat.missing.body")}</p></Empty>;
  if (!c) return read.error ? <Alert>{read.error}</Alert> : <Loading />;
  if (c.kind !== "phase_planning" || c.phase?.code !== phase) return <Empty title={t("planning.plan.other_phase")} />;
  const plans = c.proposals.filter(p => p.kind === "plan");
  return <Workbench aside={<ConversationRail conversation={c} />} label={t("planning.rail")}>
    <QuestionAnswers conversation={c} base={base} />
    <section className="panel" aria-labelledby="plan-title">
    <h2 id="plan-title">{c.title}</h2>
    <p className="hint">{rich("planning.plan.from_phase", { phase: <Link className="mono" to={{ name: "phase", project, phase }}>{phase}</Link> })} <Status kind="phase" value={c.phase.status} /> · {t("planning.plan.version", { version: c.version })}</p>
    <Stale error={read.error} />
    <TurnList conversation={c} />
    {c.questions.length > 0 && <p className="hint">{t("planning.plan.questions_hint")}</p>}
    <h3>{t("planning.plan.proposed")}</h3>
    {!plans.length && <p className="hint">{t("planning.plan.no_plans")}</p>}
    {plans.map(p => <div key={p.id} className={p.status === "PROPOSED" ? "entry entry-open" : "entry"}>
      <p><strong>{t("planning.plan.number", { number: p.number })}</strong> <Tone value={PROPOSAL[p.status]} /> <span className="muted">· {t("planning.turn_number", { number: p.turn_number })} · <Hash value={p.proposal_sha256} /></span></p>
      <p>{p.reason}</p>
      <details><summary>{t("planning.plan.view")}</summary><article className="doc-reader"><MarkdownView source={p.content} path="docs/NEXT_STEPS.md" /></article>
        <details><summary>{t("planning.plan.exact")}</summary><pre>{p.content}</pre></details></details>
      {writable && p.status === "PROPOSED" && <p><Link to={{ name: "phase", project, phase }}>{t("planning.plan.confirm_link", { phase })}</Link></p>}
      <Dismiss conversation={c} proposal={p} base={base} />
    </div>)}
    {writable && <><h3>{t("planning.plan.new_message")}</h3>
      <MessageForm conversation={c} path={`${base}/messages`} hint={t("planning.plan.message_hint")} /></>}
    </section>
  </Workbench>;
}

// --- confirmed plan of the active phase (on the phase page) --------------------------------------------------------

type Source = { kind: "proposal"; conversation: string; proposal: Proposal; title: string } | { kind: "text" };

/** Proposed plans (PROPOSED) from the planning conversations of this phase. */
function usePlans(project: string, phaseId: string, refresh: number) {
  const list = usePoll<Summary[]>(`/projects/${project}/planning`, 5000, refresh);
  const mine = useMemo(() => list.data?.filter(c => c.kind === "phase_planning" && c.phase_id === phaseId) ?? [], [list.data, phaseId]);
  const signature = mine.map(c => `${c.id}:${c.version}`).join("|");
  const [plans, setPlans] = useState<{ conversation: Summary; proposal: Proposal }[]>();
  useEffect(() => {
    let active = true;
    void Promise.all(mine.map(c => managed<Conversation>(`/projects/${project}/planning/${c.id}`)
      .then(detail => detail.proposals.filter(p => p.kind === "plan" && p.status === "PROPOSED").map(proposal => ({ conversation: c, proposal })))))
      .then(items => { if (active) setPlans(items.flat().reverse()); }).catch(() => { if (active) setPlans([]); });
    return () => { active = false; };
  }, [project, signature]);
  return { plans: list.data ? plans : undefined, error: list.error };
}

/** Installs NEXT_STEPS from text or a proposal in the empty ACTIVE phase the closure leaves. */
export function PhasePlanPanel({ phase, stale = false }: { phase: S["PhaseRead"]; stale?: boolean }) {
  const { t, rich } = useI18n();
  const { project, busy, refresh, operate, send } = useWorkspace();
  const { plans } = usePlans(project, phase.id, refresh);
  const [choice, setChoice] = useState("");
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<{ body: S["PhasePlanInput"]; shown: S["PhasePlanPreviewRead"] }>();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [run, setRun] = useState<string>();
  const [refused, setRefused] = useState<string>();
  const sources: [string, Source][] = [
    ...(plans ?? []).map(({ conversation, proposal }) => [`plan:${proposal.id}`, { kind: "proposal", conversation: conversation.id, proposal, title: conversation.title }] as [string, Source]),
    ["text", { kind: "text" }],
  ];
  const selected = choice || sources[0][0];
  const source = sources.find(([key]) => key === selected)?.[1];
  const body: S["PhasePlanInput"] = source?.kind === "proposal"
    ? { next_steps: null, plan_proposal: { conversation_id: source.conversation, proposal_id: source.proposal.id, proposal_sha256: source.proposal.proposal_sha256 } }
    : { next_steps: text, plan_proposal: null };
  const signature = JSON.stringify(body);
  useEffect(() => { setPreview(undefined); setConfirmed(false); }, [phase.version, signature]);
  useEffect(() => { setConfirmed(false); }, [preview?.shown.preview_sha256]);
  const pending = [...phase.operations].reverse().find(op => op.kind === "document_edit"
    && ["QUEUED", "INTENT", "INTERRUPTED"].includes(op.status)
    && (op.request.preview as { phase_plan?: unknown } | undefined)?.phase_plan);
  if (phase.status !== "ACTIVE" || (phase.definition.tasks as string[]).length) return null;
  return <section className="panel" id="phase-plan" aria-labelledby="phase-plan-title">
    <h2 id="phase-plan-title">{t("planning.plan.title", { phase: phase.code })}</h2>
    <p className="hint">{t("planning.panel.hint")}</p>
    {pending && !run && <p className="state state-attention">{pending.status === "INTERRUPTED" ? t("planning.panel.interrupted") : t("planning.panel.running")} {pending.run_id && <Link to={{ name: "run-short", run: pending.run_id }}>{t("planning.panel.see_run")}</Link>}</p>}
    {run ? <EditProgress run={run} title={t("planning.panel.queued")} done={<p>{t("planning.panel.done", { phase: phase.code })}</p>} /> : <>
      <fieldset disabled={busy || stale}>
        <legend>{t("planning.panel.legend", { phase: phase.code })}</legend>
        {plans === undefined && <Loading>{t("planning.panel.searching")}</Loading>}
        {sources.map(([value, item]) => <label key={value} className="check"><input type="radio" name="plan-source" checked={selected === value} onChange={() => setChoice(value)} />
          {item.kind === "proposal" ? <span>{rich("planning.panel.source", { number: item.proposal.number, title: item.title, turn: item.proposal.turn_number, hash: <Hash value={item.proposal.proposal_sha256} length={8} /> })}</span> : t("planning.panel.write")}</label>)}
        <p className="hint"><Link to={{ name: "plan", project, phase: phase.code }}>{t("planning.panel.with_reviewer", { phase: phase.code })}</Link></p>
        {source?.kind === "text" && <label>{rich("planning.panel.text", { heading: <code>## {phase.code}-TNNN — title</code> })}<textarea rows={10} value={text} maxLength={512 * 1024} onChange={e => { setChoice("text"); setText(e.target.value); }} /></label>}
        {source?.kind === "proposal" && <details><summary>{t("planning.panel.view_chosen")}</summary><article className="doc-reader"><MarkdownView source={source.proposal.content} path="docs/NEXT_STEPS.md" /></article></details>}
      </fieldset>
      <button type="button" disabled={busy || stale || (!pending && (!source || (source.kind === "text" && !text.trim())))} onClick={() => void operate(async () => {
        setRefused(undefined); setPreview(undefined);
        try { setPreview({ body, shown: await managed<S["PhasePlanPreviewRead"]>(`/phases/${phase.id}/plan/preview`, body) }); }
        catch (error) { const diagnostic = conflictText(error); if (diagnostic) setRefused(diagnostic); else throw error; }
      })}>{t("planning.panel.review")}</button>
      {refused && <p role="alert" className="state state-error">{refused}</p>}
      {preview && <div className="docs-review">
        <h3>{t("planning.panel.review_title")}</h3>
        {preview.shown.resume_operation_id && <p className="state state-attention">{t("planning.panel.resume")}</p>}
        <ul className="docs-changes">{preview.shown.documents.map(document => <li key={document.path}><code className="path">{document.path}</code> · <Hash value={document.after_sha256} /></li>)}</ul>
        <DiffBlock diff={preview.shown.diff} label={t("planning.panel.diff")} />
        <Fields items={[[t("docs.review.base"), <Hash value={preview.shown.head} />], [t("docs.review.preview"), <Hash value={preview.shown.preview_sha256} />]]} />
        <label>{t("docs.review.reason")}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("planning.panel.confirm", { phase: phase.code })}</label>
        <button type="button" disabled={busy || stale || !confirmed || !reason.trim()} onClick={() => void operate(async () => {
          const job = await send(jobRequest(`/phases/${phase.id}/plan`, {
            ...preview.body, preview_sha256: preview.shown.preview_sha256,
            resume_operation_id: preview.shown.resume_operation_id ?? null, reason, confirmed: true,
          } satisfies S["PhasePlanCreate"]));
          setRun(job.run_id);
        })}>{t("planning.panel.submit")}</button>
      </div>}
    </>}
  </section>;
}

// --- onboarding: /projects/:p/onboarding[/:c/*draft] ---------------------------------------------------

export function ImportPage({ conversation, path }: { conversation?: string; path?: string }) {
  const flow = "onboarding";
  const routeName = "onboarding";
  const { t, n, rich } = useI18n();
  const { project, refresh, busy, operate } = useWorkspace();
  const entry = usePoll<S["ImportEntryRead"]>(`/projects/${project}/${routeName}`, 3000, refresh);
  const list = usePoll<Summary[]>(`/projects/${project}/planning`, 4000, refresh);
  const [title, setTitle] = useState("");
  if (!entry.data || !list.data) return entry.error ?? list.error ? <Alert>{entry.error ?? list.error}</Alert> : <Loading />;
  if (entry.data.refusal) return <Alert>{entry.data.refusal}</Alert>;
  const mine = list.data.filter(c => c.kind === flow);
  const op = entry.data.operation;
  const selected = conversation ?? op?.conversation_id;
  return <>
    <PageHeader title={t("onboarding.title")}><p>{t("onboarding.lede")}</p></PageHeader>
    <Stale error={entry.error ?? list.error} />
    {!op && <section className="panel conversation-picker">
      <ul className="link-list">{mine.map(c => <li key={c.id}><Link to={{ name: routeName, project, conversation: c.id }} current={selected === c.id}>{c.title} · {n("chat.turns", c.turns)}</Link></li>)}</ul>
      <form onSubmit={e => { e.preventDefault(); void operate(async () => {
        const created = await createOnce<Conversation>(`/projects/${project}/planning`, { structured: true, kind: flow, title: title.trim(), brief: null, phase_id: null } satisfies S["PlanningConversationCreate"]);
        setTitle(""); navigate({ name: routeName, project, conversation: created.id });
      }); }}><label>{t("onboarding.new")}<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></label><button disabled={busy || !title.trim()}>{t("onboarding.create")}</button></form>
    </section>}
    {op && selected !== op.conversation_id ? <p>{rich("onboarding.confirmed", { link: <Link to={{ name: routeName, project, conversation: op.conversation_id }}>{t("onboarding.see_operation")}</Link> })}</p>
      : selected && <ImportConversation key={selected} id={selected} path={path} operation={op} kind={flow} />}
  </>;
}

function ImportConversation({ id, path, operation, kind }: { id: string; path?: string; operation: S["ImportOperationRead"] | null; kind: "onboarding" }) {
  const { t } = useI18n();
  const { project, refresh } = useWorkspace();
  const base = `/projects/${project}/planning/${id}`;
  const read = usePoll<Conversation>(base, 1500, refresh);
  const c = read.data;
  const drafts = usePoll<Drafts>(c && !c.structured && !c.created ? `${base}/drafts` : null, 3000, refresh);
  if (!c) return read.error ? <Alert>{read.error}</Alert> : <Loading />;
  if (c.structured) return <IntakeReview conversation={c} base={base} />;
  if (c.kind !== kind) return <Alert>{t("onboarding.other_flow")}</Alert>;
  return <div className="docs-layout">
    <DraftTree conversation={c} drafts={drafts.data} current={path} error={drafts.error} />
    <div className="docs-main"><Stale error={read.error} />
      {path && !c.created ? <DraftPage key={path} conversation={c} path={path} drafts={drafts.data} /> : <Workbench aside={<ConversationRail conversation={c} />} label={t("planning.rail")}>
        {operation?.status !== "COMPLETED" && <ProfileReplay />}
        <h2>{c.title}</h2><Evidence title={t("onboarding.source")} value={c.source} />
        <QuestionAnswers conversation={c} base={base} />
        <section className="panel"><h3>{t("planning.conversation")}</h3><TurnList conversation={c} />
          {!c.created && <MessageForm conversation={c} path={`${base}/messages`} hint={t("onboarding.message_hint")} />}
        </section>
        <ProposalBatch conversation={c} base={base} />
        {c.proposals.filter(p => p.status === "PROPOSED" || !c.created && p.kind === "profile" && p.status === "ACCEPTED").map(p => <ProposalEntry key={p.id} conversation={c} proposal={p} base={base} drafts={drafts.data} />)}
        <ProposalHistory proposals={c.proposals.filter(p => p.status !== "PROPOSED")} />
        {operation?.status === "COMPLETED" && <ProjectProfile />}
        <ImportConfirmation base={base} conversation={c} operation={operation} />
      </Workbench>}
    </div>
  </div>;
}

function ImportConfirmation({ base, conversation, operation }: { base: string; conversation: Conversation; operation: S["ImportOperationRead"] | null }) {
  const { t, rich } = useI18n();
  const { project, busy, operate, send } = useWorkspace();
  const [shown, setShown] = useState<S["ImportPreviewRead"]>();
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => { setShown(undefined); setConfirmed(false); }, [conversation.version, operation?.status]);
  const endpoint = "onboarding";
  const completed = operation?.status === "COMPLETED";
  const queued = operation?.status === "QUEUED";
  return <section className="panel">
    <h3>{completed ? t("onboarding.completed") : t("onboarding.confirm.title")}</h3>
    {operation && <><p><Status value={operation.status} /> · <Link to={{ name: "run-short", run: operation.run_id }}>{t("planning.panel.see_run")}</Link> <Status value={operation.run_status} /></p>
      {operation.result && <Evidence title={t("onboarding.result")} value={operation.result} />}
      {completed && <p>{t("onboarding.adopted")} <Link to={{ name: "phase", project, phase: String(operation.preview.phase.code) }}>{t("onboarding.continue", { phase: String(operation.preview.phase.code) })}</Link></p>}
      {operation.run_status === "RECOVERY_REQUIRED" && <p>{t("onboarding.recovery")}</p>}
    </>}
    {!completed && !queued && <button disabled={busy} onClick={() => void operate(async () => {
      setShown(undefined); setConfirmed(false);
      setShown(await managed<S["ImportPreviewRead"]>(`${base}/${endpoint}/preview`, {}));
    })}>{operation ? t("onboarding.review_intent") : t("onboarding.review")}</button>}
    {shown && <div className="docs-review">
      <p>{rich("onboarding.phase", { phase: <strong>{String(shown.phase.code)}</strong> })}</p>
      <Fields items={[[t("docs.review.base"), <Hash value={shown.head} />], [t("docs.review.preview"), <Hash value={shown.preview_sha256} />]]} />
      <Evidence title={t("onboarding.tree_evidence")} value={{ tree: shown.result_tree, moves: shown.moves, preserved: shown.preserved, foreign: shown.foreign, phase: shown.phase }} />
      {shown.warnings.length > 0 && <ul>{shown.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
      {<>
        <Evidence title={t("onboarding.profile_proposal")} value={{ proposal: shown.profile_proposal, accepted_sha256: shown.profile_proposal_sha256 }} />
        <Evidence title={t("onboarding.profile")} value={shown.profile} />
        <p>{t("onboarding.profile_hint")}</p>
        <Fields items={[[t("onboarding.profile_hash"), <Hash value={shown.profile_sha256 ?? ""} />]]} />
      </>}
      <DiffBlock diff={shown.diff} label={t("onboarding.diff")} />
      <details><summary>{t("onboarding.bytes")}</summary>{shown.documents.map(doc => <details key={String(doc.path)}><summary>{String(doc.path)} · {doc.content === null ? t("onboarding.removed") : String(doc.after_sha256).slice(0, 12)}</summary><pre>{doc.content == null ? t("onboarding.removed_hint") : String(doc.content)}</pre></details>)}</details>
      <label>{t("docs.review.reason")}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("onboarding.confirm", { hash: shown.preview_sha256.slice(0, 12) })}</label>
      <button disabled={busy || !confirmed || !reason.trim()} onClick={() => void operate(async () => {
        await send(jobRequest(`${base}/${endpoint}/confirm`, { preview_sha256: shown.preview_sha256, reason, confirmed: true,
          resume_operation_id: shown.resume_operation_id ?? null, expected_version: shown.expected_version ?? null,
          profile_sha256: shown.profile_sha256! }));
        setShown(undefined); setConfirmed(false);
      })}>{operation ? t("onboarding.reconcile") : t("onboarding.submit")}</button>
    </div>}
  </section>;
}

function LegacyPreparation() {
  const { project } = useWorkspace();
  const read = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 0);
  return read.data?.versions.project_recipe ? <Preparation /> : null;
}
