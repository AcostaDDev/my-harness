import { useState } from "react";
import type { S } from "../managed-api";
import { useI18n } from "../Language";
import { useWorkspace } from "../workspace";
import { DiffBlock, Hash, message } from "../ui";
import { unifiedDiff } from "../diff";
import { applicableDocuments, applyReviewedDocuments, reviewDocumentProposals } from "../proposal-batch";
import type { ProposalBatchResult, ProposalBatchReview } from "../proposal-batch";

export function ProposalBatch({ conversation, base }: { conversation: S["PlanningConversationRead"]; base: string }) {
  const { t } = useI18n();
  const { busy, operate } = useWorkspace();
  const [review, setReview] = useState<ProposalBatchReview>();
  const [selected, setSelected] = useState<string[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<ProposalBatchResult>();
  const [applied, setApplied] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string>();
  const proposals = applicableDocuments(conversation);
  const chosen = review?.documents.filter(d => selected.includes(d.proposal.id)) ?? [];
  const stale = !!review && (conversation.version !== review.version || proposals.length === 0);
  if (!proposals.length && !result) return null;
  return <section className="panel" aria-label={t("planning.batch.title")}>
    <h3>{t("planning.batch.title")}</h3>
    <p className="hint">{t("planning.batch.hint")}</p>
    {!!proposals.length && <button type="button" disabled={busy} onClick={() => void operate(async () => {
      setError(undefined); setReview(undefined); setResult(undefined); setApplied([]); setConfirmed(false);
      try {
        const shown = await reviewDocumentProposals(base, conversation);
        setReview(shown); setSelected(shown.documents.map(d => d.proposal.id));
      } catch (error) { setError(message(error)); }
    })}>{t("planning.batch.review", { count: proposals.length })}</button>}
    {error && <p role="alert" className="state state-error">{error}</p>}
    {running && <p role="status">{t("planning.batch.progress", { count: applied.length, total: chosen.length })}</p>}
    {result && <div role="status" className={`state ${result.error ? "state-attention" : "state-ok"}`}>
      <p>{t(result.error ? "planning.batch.stopped" : "planning.batch.done", { count: result.applied.length })}</p>
      {!!result.applied.length && <ul>{result.applied.map(path => <li key={path}><code>{path}</code></li>)}</ul>}
      {result.unconfirmed && <p>{t("planning.batch.unconfirmed", { path: result.unconfirmed })}</p>}
      {!!result.remaining.length && <p>{t("planning.batch.remaining", { paths: result.remaining.join(", ") })}</p>}
      {result.error !== undefined && <p>{message(result.error)}</p>}
    </div>}
    {review && <div className="decision">
      <p>{t("planning.batch.order_hint")}</p>
      {stale && !running && <p role="alert" className="state state-attention">{t("planning.batch.stale")}</p>}
      {review.documents.map(({ proposal, before, conflict }) => {
        const diff = unifiedDiff(proposal.path!, before?.content ?? null, proposal.content, t("diff.eol"));
        return <div className="docs-review" key={proposal.id}>
          <label className="check"><input type="checkbox" checked={selected.includes(proposal.id)} disabled={busy || stale}
            onChange={e => { setSelected(ids => e.target.checked ? [...ids, proposal.id] : ids.filter(id => id !== proposal.id)); setConfirmed(false); }} />
            <code>{proposal.path}</code></label>
          <p className="hint">{proposal.reason} · <Hash value={proposal.proposal_sha256} /></p>
          {conflict && <p className="state state-attention">{t("planning.proposal.moved")}</p>}
          <details><summary>{t("planning.review.diff_label", { path: proposal.path! })}</summary>
            {diff === null ? <><p>{t("planning.batch.full_document")}</p>
              <p>{t("planning.review.disk")}</p><pre>{before?.content ?? t("planning.review.did_not_exist")}</pre>
              <p>{t("planning.review.proposed")}</p><pre>{proposal.content}</pre></>
              : diff === "" ? <p>{t("planning.review.same")}</p> : <DiffBlock diff={diff} label={t("planning.review.diff_label", { path: proposal.path! })} />}
          </details>
        </div>;
      })}
      <label className="check"><input type="checkbox" checked={confirmed} disabled={busy || stale || !chosen.length}
        onChange={e => setConfirmed(e.target.checked)} />{t("planning.batch.confirm", { count: chosen.length })}</label>
      <div className="actions">
        <button type="button" disabled={busy || stale || !confirmed || !chosen.length || chosen.some(d => d.conflict)}
          onClick={() => void operate(async () => {
            if (stale || !confirmed || !chosen.length) return;
            setRunning(true); setConfirmed(false); setError(undefined);
            try { setResult(await applyReviewedDocuments(base, { ...review, documents: chosen }, setApplied)); }
            finally { setRunning(false); setReview(undefined); }
          })}>{t("planning.batch.apply", { count: chosen.length })}</button>
        <button type="button" className="button-quiet" disabled={busy} onClick={() => { setReview(undefined); setConfirmed(false); }}>{t("planning.batch.cancel")}</button>
      </div>
    </div>}
  </section>;
}
