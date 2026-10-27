import { useEffect, useRef, useState } from "react";
import { MESSAGE_LIMIT, characters, compose, draftFor, draftsKey, entries, markSent, orphans, prune, readDrafts, resolved,
  sourceTurn, standings, writeDrafts } from "../answers.ts";
import type { Draft, Drafts, Standing } from "../answers.ts";
import { useI18n } from "../Language";
import { jobRequest, managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import { message } from "../ui";
import { useWorkspace } from "../workspace";

// Question-first answers (OT002): the reviewer's open questions are the next action of a documentary conversation.
// Each has its own answer field; typing saves a draft in this browser and calls nothing. One explicit review sends
// one answer, a selection or every prepared answer as ONE message (one turn) through the existing endpoint, with
// its version check and idempotency key. Deferral stays a separate action with its own reason.

type Conversation = S["PlanningConversationRead"];
type Review = { ids: string[]; version: number };

function storage() {
  try { return globalThis.localStorage; } catch { return undefined; }
}

function useDrafts(key: string) {
  const [drafts, setDrafts] = useState<Drafts>(() => readDrafts(storage(), key));
  useEffect(() => { writeDrafts(storage(), key, drafts); }, [key, drafts]);
  return [drafts, setDrafts] as const;
}

function useStoredText(key: string) {
  const [value, setValue] = useState(() => { try { return storage()?.getItem(key) ?? ""; } catch { return ""; } });
  useEffect(() => { try { if (value) storage()?.setItem(key, value); else storage()?.removeItem(key); } catch { /* kept in memory */ } }, [key, value]);
  return [value, setValue] as const;
}

export function QuestionAnswers({ conversation, base }: { conversation: Conversation; base: string }) {
  const { t, n } = useI18n();
  const { project, busy, operate, send } = useWorkspace();
  const key = draftsKey(project, conversation.id);
  const [drafts, setDrafts] = useDrafts(key);
  const [context, setContext] = useStoredText(`${key}:context`);
  const [review, setReview] = useState<Review>();
  const [conflict, setConflict] = useState<string>();
  const [submitted, setSubmitted] = useState<number>();
  const [notice, setNotice] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const reviewTitle = useRef<HTMLHeadingElement>(null);
  const title = useRef<HTMLHeadingElement>(null);
  const questions = conversation.questions;
  const turns = conversation.turns;
  // Resolved answers sent unchanged leave the drafts once the reviewer has answered; the rest stays.
  const turnSignature = turns.map(turn => `${turn.number}:${turn.status}`).join();
  useEffect(() => { setDrafts(previous => prune(previous, questions, turns)); }, [conversation.version, turnSignature]);
  useEffect(() => { if (review) reviewTitle.current?.focus(); }, [review?.ids.join(), review === undefined]);
  useEffect(() => { if (notice) title.current?.focus(); }, [notice]);
  const source = sourceTurn(turns) ?? 0;
  useEffect(() => { setNotice(false); setSubmitted(undefined); }, [source]);
  const state = standings(questions, turns);
  const waiting = new Set(Object.entries(state).filter(([, value]) => value.kind === "awaiting").map(([id]) => id));
  const earlier = orphans(drafts, questions);
  const done = resolved(questions, turns);
  const running = turns.some(turn => turn.status === "QUEUED");
  const editable = !conversation.created && (conversation.actions.includes("message") || running);
  const sendable = conversation.actions.includes("message") && !running && submitted !== conversation.version;
  const canDefer = conversation.actions.includes("defer_question");
  if (!questions.length && !conversation.pending.length && !earlier.length && !done.length) return null;

  // Open blocking questions first; the composed message follows the same order as the cards.
  const ordered = [...questions.filter(q => q.blocking && !q.deferred), ...questions.filter(q => !q.blocking || q.deferred)];
  const prepared = ordered.filter(q => !waiting.has(q.id) && drafts[q.id]?.text.trim()).map(q => q.id);
  const selected = [...prepared.filter(id => drafts[id]?.selected), ...earlier.filter(([, draft]) => draft.selected).map(([id]) => id)];
  const openBlocking = questions.filter(q => q.blocking && !q.deferred).length;

  function edit(id: string, change: Partial<Draft>, fallback: Draft) {
    setNotice(false);
    setDrafts(previous => ({ ...previous, [id]: { ...(previous[id] ?? fallback), ...change } }));
  }
  function discard(id: string) {
    setDrafts(previous => Object.fromEntries(Object.entries(previous).filter(([other]) => other !== id)));
  }
  function open(ids: string[]) { setConflict(undefined); setNotice(false); setReview({ ids, version: conversation.version }); }

  const items = review ? entries(review.ids, drafts, ordered, waiting) : [];
  const labels = {
    intro: t("answers.message.intro", { turn: source, count: items.length }),
    blocking: t("answers.message.blocking"), informative: t("answers.message.informative"),
    earlier: t("answers.message.earlier"), answer: t("answers.message.answer"), context: t("answers.message.context"),
  };
  const composed = items.length ? compose(items, context, labels) : "";
  const size = characters(composed);
  const over = size > MESSAGE_LIMIT;
  const stale = !!review && review.version !== conversation.version;

  function submit() {
    if (!review || !items.length || over || stale || !sendable) return;
    const ids = items.map(item => item.id);
    void operate(async () => {
      setConflict(undefined);
      try {
        await send(jobRequest(`${base}/messages`, { expected_version: conversation.version, text: composed } satisfies S["PlanningMessageCreate"]));
      } catch (error) {
        if (error instanceof ManagedError && error.status === 409) { setConflict(error.diagnostic ?? message(error)); return; }
        throw error;
      }
      setDrafts(previous => markSent(previous, ids));
      setContext("");
      setReview(undefined);
      setSubmitted(conversation.version);
      setNotice(true);
    });
  }

  return <section className="panel answers" aria-labelledby="answers-title">
    <div className="panel-head">
      <h2 id="answers-title" tabIndex={-1} ref={title}>{t("answers.title")}</h2>
      <p className="answers-summary">{questions.length ? <>{n("answers.summary.blocking", openBlocking)} · {n("answers.summary.prepared", prepared.length)}</> : t("answers.summary.none")}</p>
    </div>
    <p className="hint">{editable ? t("answers.hint") : t("answers.closed")}</p>
    {running && <p className="state state-loading" role="status">{t("answers.running")}</p>}
    {notice && <p className="state state-ok" role="status">{t("answers.sent")}</p>}

    {ordered.length > 0 && <ol className="answers-list">{ordered.map(question => {
      const draft = draftFor(drafts, question, source);
      const standing = state[question.id] ?? { kind: "open" };
      const locked = !editable || standing.kind === "awaiting";
      const field = `answer-${question.id.slice(0, 12)}`;
      const tone = question.deferred ? "answer-deferred" : question.blocking ? "answer-blocking" : "answer-informative";
      return <li key={question.id} className={`answer ${tone}`} aria-labelledby={`${field}-q`}>
        <div className="answer-head">
          <span className="answer-kind">{question.deferred ? t("answers.kind.deferred") : question.blocking ? t("answers.kind.blocking") : t("answers.kind.informative")}</span>
          <StandingText standing={standing} draft={draft} source={source} />
        </div>
        <p className="answer-question" id={`${field}-q`}>{question.text}</p>
        {question.deferred && <p className="hint">{t("planning.question.deferred_reason", { reason: String(question.deferred.reason) })}</p>}
        {(editable || draft.text) && <label htmlFor={field} id={`${field}-label`} className="answer-label">{t("answers.field")}</label>}
        {(editable || draft.text) && <textarea id={field} className="answer-field" rows={draft.text ? Math.min(10, Math.max(3, draft.text.split("\n").length + 1)) : 3}
          value={draft.text} readOnly={locked} aria-labelledby={`${field}-label ${field}-q`} maxLength={MESSAGE_LIMIT}
          onChange={e => edit(question.id, { text: e.target.value, question: question.text, blocking: question.blocking, turn: source }, draft)} />}
        {editable && standing.kind !== "awaiting" && <div className="answer-actions">
          <label className="check"><input id={`${field}-select`} type="checkbox" checked={draft.selected && !!draft.text.trim()} disabled={!draft.text.trim()}
            onChange={e => edit(question.id, { selected: e.target.checked }, draft)} />{t("answers.select")}</label>
          <button type="button" className="button-quiet" disabled={!draft.text.trim() || busy} onClick={() => open([question.id])}>{t("answers.review_one")}</button>
        </div>}
        {canDefer && question.blocking && !question.deferred && <details className="answer-defer">
          <summary>{t("answers.defer.summary")}</summary>
          <p className="hint">{t("answers.defer.hint")}</p>
          <div className="form-row"><label>{t("planning.question.defer_reason")}<input value={reasons[question.id] ?? ""} maxLength={2000} onChange={e => setReasons({ ...reasons, [question.id]: e.target.value })} /></label>
            <button type="button" className="button-quiet" disabled={busy || !(reasons[question.id] ?? "").trim()} onClick={() => void operate(async () => {
              await managed(`${base}/questions/defer`, { expected_version: conversation.version, question_id: question.id, reason: reasons[question.id] } satisfies S["PlanningDeferCreate"]);
            })}>{t("planning.question.defer")}</button></div>
        </details>}
      </li>;
    })}</ol>}

    {conversation.pending.length > 0 && <div className="answers-pending">
      <h3>{t("planning.pending")}</h3>
      <p className="hint">{t("planning.pending.hint")}</p>
      <ul className="checklist">{conversation.pending.map(item => <li key={item}>{item}</li>)}</ul>
    </div>}

    {earlier.length > 0 && <div className="answers-earlier" role="group" aria-labelledby="answers-earlier-title">
      <h3 id="answers-earlier-title">{t("answers.earlier.title")}</h3>
      <p className="hint">{t("answers.earlier.hint")}</p>
      <ul className="answers-list">{earlier.map(([id, draft]) => <li key={id} className="answer answer-earlier">
        <p className="answer-question">{draft.question}</p>
        <p className="hint">{t("answers.earlier.turn", { turn: draft.turn })}</p>
        <pre className="answer-saved">{draft.text}</pre>
        {editable && <div className="answer-actions">
          <label className="check"><input type="checkbox" checked={draft.selected} onChange={e => setDrafts(previous => ({ ...previous, [id]: { ...draft, selected: e.target.checked } }))} />{t("answers.earlier.include")}</label>
          <button type="button" className="button-quiet" onClick={() => discard(id)}>{t("answers.earlier.discard")}</button>
        </div>}
      </li>)}</ul>
    </div>}

    {done.length > 0 && <details className="evidence answers-resolved">
      <summary>{n("answers.resolved.summary", done.length)}</summary>
      <ul className="docs-changes">{done.map(item => <li key={item.id}>{item.text || <code>{item.id}</code>} <span className="muted">· {t("answers.resolved.turn", { turn: item.turn })}</span></li>)}</ul>
    </details>}

    {review && <div className="answers-review" role="region" aria-labelledby="answers-review-title">
      <h3 id="answers-review-title" tabIndex={-1} ref={reviewTitle}>{n("answers.review.title", items.length)}</h3>
      <p className="hint">{t("answers.review.hint")}</p>
      {stale && <div className="state state-attention" role="alert"><p>{t("answers.review.stale")}</p>
        <button type="button" className="button-quiet" onClick={() => open(review.ids)}>{t("answers.review.again")}</button></div>}
      {!items.length ? <p className="state state-attention">{t("answers.review.empty")}</p> : <>
        <label>{t("answers.review.context")}<textarea rows={3} value={context} onChange={e => setContext(e.target.value)} /></label>
        <p className="hint">{t("answers.review.context_hint")}</p>
        <pre className="answers-preview" aria-label={t("answers.review.preview")}>{composed}</pre>
        <p className={over ? "state state-error" : "hint"} role={over ? "alert" : undefined}>
          {over ? t("answers.review.over", { size, limit: MESSAGE_LIMIT }) : t("answers.review.size", { size, limit: MESSAGE_LIMIT })}</p>
      </>}
      {conflict && <p className="state state-error" role="alert">{t("answers.review.conflict", { error: conflict })}</p>}
      {!sendable && <p className="hint">{running ? t("answers.running") : submitted === conversation.version ? t("answers.review.just_sent") : t("answers.closed")}</p>}
      <div className="actions">
        <button type="button" disabled={busy || !items.length || over || stale || !sendable} onClick={submit}>{t("answers.review.send")}</button>
        <button type="button" className="button-quiet" onClick={() => { setReview(undefined); setConflict(undefined); }}>{t("answers.review.back")}</button>
      </div>
    </div>}

    {editable && !review && (prepared.length > 0 || selected.length > 0) && <div className="answers-bar" role="group" aria-label={t("answers.bar")}>
      <p>{n("answers.bar.selected", selected.length)}</p>
      <div className="actions">
        <button type="button" className="button-quiet" disabled={busy || !selected.length} onClick={() => open(selected)}>{t("answers.review_selected", { count: selected.length })}</button>
        <button type="button" disabled={busy || !prepared.length} onClick={() => open(prepared)}>{t("answers.review_all", { count: prepared.length })}</button>
      </div>
    </div>}
  </section>;
}

function StandingText({ standing, draft, source }: { standing: Standing; draft: Draft; source: number }) {
  const { t } = useI18n();
  const [text, tone] = standing.kind === "awaiting" ? [t("answers.state.awaiting", { turn: standing.turn }), "active"]
    : standing.kind === "unreviewed" ? [t("answers.state.unreviewed", { turn: standing.turn }), "attention"]
      : standing.kind === "asked_again" ? [t("answers.state.asked_again", { turn: standing.turn }), "attention"]
        : draft.text.trim() ? [draft.turn !== source ? t("answers.state.carried", { turn: draft.turn }) : t("answers.state.draft"), "neutral"]
          : [t("answers.state.empty"), "muted"];
  return <span className={`answer-state answer-state-${tone}`}>{text}</span>;
}
