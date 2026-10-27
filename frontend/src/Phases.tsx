import { useEffect, useState } from "react";
import { useI18n } from "./Language";
import { managed, jobRequest } from "./managed-api";
import type { S } from "./managed-api";
import { Link, navigate } from "./navigation";
import { Evidence, Fields, Hash, when } from "./ui";
import { useWorkspace } from "./workspace";

const lines = (value: string) => value.split("\n").map(item => item.trim()).filter(Boolean);

/** Frozen definition of a new phase (H3.3); creating it opens its URL. */
export function PhaseCreate() {
  const { t } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const [code, setCode] = useState("");
  const [objective, setObjective] = useState("");
  const [criteria, setCriteria] = useState("");
  const [tasks, setTasks] = useState("");
  const [documents, setDocuments] = useState("");
  const [tag, setTag] = useState("");
  return <section className="panel" aria-labelledby="phase-create">
    <h2 id="phase-create">{t("phase.create.title")}</h2>
    <p className="hint">{t("phase.create.hint")}</p>
    <form onSubmit={e => { e.preventDefault(); void operate(async () => {
      const created = await managed<S["PhaseRead"]>(`/projects/${project}/phases`, {
        code, objective, exit_criteria: lines(criteria), tasks: lines(tasks),
        documents: lines(documents).length ? lines(documents) : null, tag: tag.trim() || null,
      } satisfies S["PhaseCreate"]);
      navigate({ name: "phase", project, phase: created.code });
    }); }}>
      <div className="form-row"><label>{t("phase.field.code")}<input required value={code} maxLength={120} placeholder="P001" onChange={e => setCode(e.target.value)} /></label>
        <label>{t("phase.field.tag")}<input value={tag} maxLength={100} onChange={e => setTag(e.target.value)} /></label></div>
      <label>{t("phase.field.objective")}<input required value={objective} maxLength={4000} onChange={e => setObjective(e.target.value)} /></label>
      <label>{t("phase.field.criteria")}<textarea required rows={3} value={criteria} onChange={e => setCriteria(e.target.value)} /></label>
      <label>{t("phase.field.tasks_accepted")}<textarea rows={3} value={tasks} onChange={e => setTasks(e.target.value)} /></label>
      <label>{t("phase.field.documents_reference")}<textarea rows={2} value={documents} onChange={e => setDocuments(e.target.value)} /></label>
      <button disabled={busy || !code.trim() || !objective.trim() || !lines(criteria).length}>{t("phase.create.submit")}</button>
    </form>
  </section>;
}

/** Phase operations on the read the page shows; each confirmation is valid for that version. */
export function PhaseDetail({ phase, stale, section }: { phase: S["PhaseRead"]; stale: boolean; section?: string }) {
  const { t, n, rich } = useI18n();
  const { busy, operate, send } = useWorkspace();
  const id = phase.id;
  const [reason, setReason] = useState("");
  const [question, setQuestion] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answerConfirmed, setAnswerConfirmed] = useState(false);
  const [reconcileConfirmed, setReconcileConfirmed] = useState(false);
  const [closeReason, setCloseReason] = useState("");
  const [closeConfirmed, setCloseConfirmed] = useState(false);
  const [batchTasks, setBatchTasks] = useState<string[]>([]);
  const [batchTtl, setBatchTtl] = useState(3600);
  const [batchReason, setBatchReason] = useState("");
  const [batchConfirmed, setBatchConfirmed] = useState(false);
  const [plan, setPlan] = useState("");
  const [chainCommits, setChainCommits] = useState(false);
  const [batchPlan, setBatchPlan] = useState("");
  const [amendObjective, setAmendObjective] = useState("");
  const [amendCriteria, setAmendCriteria] = useState("");
  const [amendTasks, setAmendTasks] = useState("");
  const [amendDocuments, setAmendDocuments] = useState("");
  const [amendTag, setAmendTag] = useState("");
  const [amendReason, setAmendReason] = useState("");
  const [amendConfirmed, setAmendConfirmed] = useState(false);
  const [abandonReason, setAbandonReason] = useState("");
  const [abandonConfirmed, setAbandonConfirmed] = useState(false);
  const [exportPreview, setExportPreview] = useState<S["DocumentExportPreviewRead"]>();
  const [exportReason, setExportReason] = useState("");
  const [exportConfirmed, setExportConfirmed] = useState(false);
  // Confirmations are only valid for the version and the evidence that were shown.
  useEffect(() => { setAnswerConfirmed(false); setReconcileConfirmed(false); setCloseConfirmed(false); setBatchConfirmed(false); setAmendConfirmed(false); setAbandonConfirmed(false); },
    [phase.version, phase.ready?.binding_sha256, phase.documents.current_sha256]);
  useEffect(() => { setExportConfirmed(false); setExportPreview(undefined); }, [phase.version, phase.documents.current_sha256]);
  // The amendment form starts from the current definition; it only changes when the definition version changes.
  useEffect(() => {
    const d = phase.definition;
    setAmendObjective(String(d.objective)); setAmendCriteria((d.exit_criteria as string[]).join("\n"));
    setAmendTasks((d.tasks as string[]).join("\n")); setAmendDocuments((d.documents as string[]).join("\n"));
    setAmendTag(d.tag ? String(d.tag) : "");
  }, [phase.definition_sha256]);
  const can = (action: S["PhaseRead"]["actions"][number]) => !busy && !stale && phase.actions.includes(action);
  const v = phase.version;
  const open = phase.questions.filter(q => q.status === "OPEN");
  const batch = phase.authorizations.find(a => a.kind === "batch" && a.effective_status === "ACTIVE");
  const criteria = phase.definition.exit_criteria as string[];
  const superseded = phase.successor !== null;
  return <>
    {(!section || section === "phase-definition") && <section className="panel" aria-labelledby="phase-definition">
      <h2 id="phase-definition">{t("phase.definition")}</h2>
      <Fields items={[
        [t("phase.definition.version"), `${phase.definition_number}`],
        [t("phase.observed_version"), `${v}`],
        [t("settings.tag"), phase.definition.tag ? <code>{String(phase.definition.tag)}</code> : <span className="muted">{t("phase.no_tag")}</span>],
        [t("settings.documents"), (phase.definition.documents as string[]).map(d => <code key={d} className="chip">{d}</code>)],
      ]} />
      <h3>{t("phase.criteria")}</h3>
      <ul className="checklist">{criteria.map(c => <li key={c}>{c}</li>)}</ul>
      <Evidence title={t("phase.definition.evidence")} value={{ definition: phase.definition, tasks: phase.tasks }} />
      <Evidence title={t("phase.definition.versions", { count: phase.definitions.length })} value={phase.definitions} />
    </section>}

    {(!section || section === "phase-questions") && <section className="panel" aria-labelledby="phase-questions">
      <h2 id="phase-questions">{t("phase.questions")} <span className="count">{n("phase.questions.pending", open.length)}</span></h2>
      {!phase.questions.length && <p className="hint">{t("phase.questions.empty")}</p>}
      {phase.questions.map(q => <div className={q.status === "OPEN" ? "entry entry-open" : "entry"} key={q.id}>
        <p><strong>{q.status === "OPEN" ? t("phase.question.open") : t("phase.question.answered")}</strong>: {q.text}</p>
        {q.answer && <p>{t("phase.question.answer_value", { answer: String(q.answer.text) })}</p>}
        {q.status === "OPEN" && <div className="form-row"><label>{t("phase.question.answer")}<input value={answers[q.id] ?? ""} maxLength={4000} onChange={e => setAnswers({ ...answers, [q.id]: e.target.value })} /></label>
          <button disabled={busy || stale || !answerConfirmed || !(answers[q.id] ?? "").trim()} onClick={() => void operate(async () => {
            await managed(`/phases/${id}/questions/${q.id}/answer`, { expected_version: v, expected_question_version: q.version, answer: answers[q.id], confirmed: true } satisfies S["PhaseAnswerCreate"]);
          })}>{t("phase.question.reply")}</button></div>}
        <Evidence title={t("phase.question.evidence")} value={q} /></div>)}
      {open.length > 0 && <label className="check"><input type="checkbox" checked={answerConfirmed} onChange={e => setAnswerConfirmed(e.target.checked)} />{t("phase.question.confirm")}</label>}
      <form onSubmit={e => { e.preventDefault(); void operate(async () => {
        await managed(`/phases/${id}/questions`, { expected_version: v, text: question } satisfies S["PhaseQuestionCreate"]); setQuestion("");
      }); }}><div className="form-row"><label>{t("phase.question.new")}<input value={question} maxLength={4000} onChange={e => setQuestion(e.target.value)} /></label>
        <button className="button-quiet" disabled={!can("question") || !question.trim()}>{t("phase.question.register")}</button></div></form>
    </section>}

    {(!section || section === "phase-documents") && <section className="panel" aria-labelledby="phase-documents">
      <h2 id="phase-documents">{t("settings.documents")}</h2>
      {phase.closure ? <ClosureDocuments phase={phase} closure={phase.closure} />
        : phase.documents.drift === null ? <p className="state state-error">{t("phase.documents.unreadable")}</p>
        : phase.documents.drift.length ? (superseded
          // The successor (transition included) changed the documents: there is nothing to decide in this phase.
          ? <p className="hint">{rich("phase.documents.superseded", { phase: <code>{phase.successor}</code> })} {phase.documents.drift.map(d => <code key={d} className="chip">{d}</code>)}</p>
          : <p className="state state-attention">{t("phase.documents.changed")} {phase.documents.drift.map(d => <code key={d} className="chip">{d}</code>)}</p>)
          : <p className="hint">{t("phase.documents.unchanged")}</p>}
      <Evidence title={t("phase.documents.evidence")} value={phase.documents} />
      {!superseded && !phase.closure && <div className="decision">
        <h3>{t("phase.reconcile.title")}</h3>
        <label>{t("phase.reconcile.reason")}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={reconcileConfirmed} onChange={e => setReconcileConfirmed(e.target.checked)} />{t("phase.reconcile.confirm")}</label>
        <div className="actions"><button disabled={!can("reconcile") || !reconcileConfirmed || !reason.trim() || !phase.documents.current_sha256} onClick={() => void operate(async () => {
          await managed(`/phases/${id}/reconcile`, { expected_version: v, documents_sha256: phase.documents.current_sha256!, reason, confirmed: true } satisfies S["PhaseReconcileCreate"]);
        })}>{t("phase.reconcile.title")}</button>
          <button className="button-quiet" disabled={!can("reconcile_task")} onClick={() => void operate(() => send(jobRequest(`/phases/${id}/reconcile-task`, { expected_version: v })))}>{t("phase.reconcile.agent")}</button></div>
        <p className="hint">{t("phase.reconcile.agent_hint")}</p>
      </div>}
      <div className="decision">
        <h3>{t("phase.export.title")}</h3>
        <p className="hint">{superseded ? rich("phase.export.superseded", { phase: <code>{phase.successor}</code> }) : t("phase.export.hint")}</p>
        <button className="button-quiet" disabled={busy || stale || superseded} onClick={() => void operate(async () => {
          const preview = await managed<S["DocumentExportPreviewRead"]>(`/phases/${id}/export`);
          setExportConfirmed(false); setExportPreview(preview);
        })}>{t("phase.export.preview")}</button>
        {exportPreview && <>
          <Fields items={[[t("docs.review.base"), <Hash value={exportPreview.head} />], [t("phase.export.content"), <Hash value={exportPreview.preview_sha256} />]]} />
          {exportPreview.resume_operation_id && <p className="hint">{t("phase.export.resume", { id: exportPreview.resume_operation_id })}</p>}
          <pre className="diff">{exportPreview.diff || t("phase.export.no_diff")}</pre>
          <label>{t("phase.export.reason")}<input value={exportReason} maxLength={2000} onChange={e => { setExportReason(e.target.value); setExportConfirmed(false); }} /></label>
          <label className="check"><input type="checkbox" checked={exportConfirmed} onChange={e => setExportConfirmed(e.target.checked)} />{t("phase.export.confirm")}</label>
          <button disabled={busy || stale || !exportConfirmed || !exportReason.trim() || !exportPreview.mechanical.length || exportPreview.expected_version !== v}
            onClick={() => void operate(() => send(jobRequest(`/phases/${id}/export`, {
              expected_version: exportPreview.expected_version, preview_sha256: exportPreview.preview_sha256,
              resume_operation_id: exportPreview.resume_operation_id, reason: exportReason, confirmed: true,
            } satisfies S["DocumentExportCreate"])))}>{t("phase.export.submit")}</button>
        </>}
      </div>
    </section>}

    {(!section || section === "phase-check") && <section className="panel" aria-labelledby="phase-check">
      <h2 id="phase-check">{t("phase.check.title")}</h2>
      <p className="hint">{t("phase.check.hint")}</p>
      <button disabled={!can("check")} onClick={() => void operate(() => send(jobRequest(`/phases/${id}/actions`, { action: "check", expected_version: v })))}>{t("phase.check.submit")}</button>
      {phase.closure ? <ClosureCheck closure={phase.closure} />
        : phase.ready ? <>
        <Fields items={[[t("phase.ready.on"), <Hash value={String(phase.ready.binding.head)} />], [t("phase.evidence"), <Hash value={phase.ready.binding_sha256} />]]} />
        {phase.ready.stale_reasons.length > 0 && <p className="state state-attention">{t("phase.ready.stale", { reasons: phase.ready.stale_reasons.join("; ") })}</p>}
        <Evidence title={t("phase.ready.evidence")} value={phase.ready} /></> : <p className="hint">{t("phase.ready.none")}</p>}
      {!phase.closure && <div className="decision">
        <h3>{t("phase.close.title")}</h3>
        <p className="hint">{phase.definition.tag ? t(phase.tag_kind === "annotated" ? "phase.close.hint_tag.annotated" : "phase.close.hint_tag.lightweight", { tag: String(phase.definition.tag) }) : t("phase.close.hint")}</p>
        <label>{t("phase.close.reason")}<input value={closeReason} maxLength={2000} onChange={e => setCloseReason(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={closeConfirmed} onChange={e => setCloseConfirmed(e.target.checked)} />{t("phase.close.confirm", { evidence: phase.ready?.binding_sha256.slice(0, 12) ?? "" })}</label>
        <button disabled={!can("close") || !closeConfirmed || !closeReason.trim() || !phase.ready} onClick={() => void operate(() => send(jobRequest(`/phases/${id}/actions`, {
          action: "close", expected_version: v, binding_sha256: phase.ready!.binding_sha256, reason: closeReason, ttl_seconds: 3600, confirmed: true,
        })))}>{t("phase.close.title")}</button>
      </div>}
    </section>}

    {(!section || section === "phase-batch") && <section className="panel" aria-labelledby="phase-batch">
      <h2 id="phase-batch">{t("phase.batch.title")}</h2>
      <p className="hint">{t("phase.batch.hint")}</p>
      <div className="decision">
        {batch ? <>{batch.scope.chain_commits ? <p>{t("phase.batch.unattended")} {(batch.scope.tasks as string[]).map(task => <code key={task} className="chip">{task}</code>)} {rich("phase.batch.plan", { plan: <Hash value={String(batch.scope.plan_sha256)} />, expires: batch.expires_at })}</p>
            : <><p>{t("phase.batch.manual")} {(batch.scope.tasks as string[]).map(task => <code key={task} className="chip">{task}</code>)} {t("phase.batch.expires", { expires: batch.expires_at })}</p>
              <label>{t("phase.batch.next_contract")}<textarea rows={6} value={plan} maxLength={200000} onChange={e => setPlan(e.target.value)} /></label></>}
          <div className="actions">{!batch.scope.chain_commits && <button disabled={!can("batch_next") || !plan.trim()} onClick={() => void operate(() => send(jobRequest(`/phases/${id}/batch/next`, { expected_version: v, authorization_id: batch.id, text: plan })))}>{t("phase.batch.next")}</button>}
            <button className="button-danger" disabled={busy || stale || !batchReason.trim()} onClick={() => void operate(async () => {
              await managed(`/phases/${id}/authorizations/${batch.id}/revoke`, { expected_version: v, reason: batchReason } satisfies S["PhaseRevokeCreate"]);
            })}>{t("phase.batch.revoke")}</button></div></>
          : <>{(phase.definition.tasks as string[]).map(task => <label className="check" key={task}><input type="checkbox" checked={batchTasks.includes(task)}
            onChange={e => setBatchTasks(e.target.checked ? [...batchTasks, task] : batchTasks.filter(item => item !== task))} /><code>{task}</code></label>)}
            <label>{t("permissions.ttl")}<input type="number" min={1} max={86400} value={batchTtl} onChange={e => setBatchTtl(Number(e.target.value))} /></label>
            <label className="check"><input type="checkbox" checked={chainCommits} onChange={e => setChainCommits(e.target.checked)} />{t("phase.batch.chain")}</label>
            {chainCommits && <label>{t("phase.batch.frozen_plan")}<textarea rows={6} value={batchPlan} maxLength={200000} onChange={e => setBatchPlan(e.target.value)} /></label>}</>}
        <label>{t("phase.batch.reason")}<input value={batchReason} maxLength={2000} onChange={e => setBatchReason(e.target.value)} /></label>
        {!batch && <><label className="check"><input type="checkbox" checked={batchConfirmed} onChange={e => setBatchConfirmed(e.target.checked)} />{chainCommits ? t("phase.batch.confirm_chain") : t("phase.batch.confirm")}</label>
          <button disabled={!can("authorize_batch") || !batchConfirmed || !batchReason.trim() || !batchTasks.length || (chainCommits && !batchPlan.trim())} onClick={() => void operate(async () => {
            await managed(`/phases/${id}/authorizations`, { expected_version: v, tasks: batchTasks, ttl_seconds: batchTtl, reason: batchReason, confirmed: true,
              chain_commits: chainCommits, text: chainCommits ? batchPlan : null } satisfies S["PhaseBatchCreate"]);
            setBatchTasks([]);
          })}>{t("phase.batch.authorize")}</button></>}
      </div>
    </section>}

    {!section && <details className="panel panel-collapsible">
      <summary><h2>{t("phase.amend_abandon")}</h2></summary>
      <div className="decision">
        <h3>{t("phase.amend.title")}</h3>
        <p className="hint">{t("phase.amend.hint", { version: phase.definition_number + 1 })}</p>
        <label>{t("phase.field.objective")}<input value={amendObjective} maxLength={4000} onChange={e => setAmendObjective(e.target.value)} /></label>
        <label>{t("phase.field.criteria")}<textarea rows={3} value={amendCriteria} onChange={e => setAmendCriteria(e.target.value)} /></label>
        <label>{t("phase.field.tasks")}<textarea rows={3} value={amendTasks} onChange={e => setAmendTasks(e.target.value)} /></label>
        <label>{t("phase.field.documents")}<textarea rows={2} value={amendDocuments} onChange={e => setAmendDocuments(e.target.value)} /></label>
        <label>{t("phase.field.tag")}<input value={amendTag} maxLength={100} onChange={e => setAmendTag(e.target.value)} /></label>
        <label>{t("phase.amend.reason")}<input value={amendReason} maxLength={2000} onChange={e => setAmendReason(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={amendConfirmed} onChange={e => setAmendConfirmed(e.target.checked)} />{t("phase.amend.confirm")}</label>
        <button disabled={!can("amend") || !amendConfirmed || !amendReason.trim() || !amendObjective.trim() || !lines(amendCriteria).length || !lines(amendDocuments).length} onClick={() => void operate(async () => {
          await managed(`/phases/${id}/amend`, { expected_version: v, objective: amendObjective, exit_criteria: lines(amendCriteria), tasks: lines(amendTasks),
            documents: lines(amendDocuments), tag: amendTag.trim() || null, reason: amendReason, confirmed: true } satisfies S["PhaseAmendCreate"]);
          setAmendReason("");
        })}>{t("phase.amend.title")}</button>
      </div>
      <div className="decision decision-danger">
        <h3>{t("phase.abandon.title")}</h3>
        <p className="hint">{t("phase.abandon.hint")}</p>
        <label>{t("phase.abandon.reason")}<input value={abandonReason} maxLength={2000} onChange={e => setAbandonReason(e.target.value)} /></label>
        <label className="check"><input type="checkbox" checked={abandonConfirmed} onChange={e => setAbandonConfirmed(e.target.checked)} />{t("phase.abandon.confirm")}</label>
        <button className="button-danger" disabled={!can("abandon") || !abandonConfirmed || !abandonReason.trim()} onClick={() => void operate(async () => {
          await managed(`/phases/${id}/abandon`, { expected_version: v, reason: abandonReason, confirmed: true } satisfies S["PhaseAbandonCreate"]);
        })}>{t("phase.abandon.title")}</button>
      </div>
    </details>}

    {(!section || section === "phase-history") && <section className="panel" aria-labelledby="phase-history">
      <h2 id="phase-history">{t("phase.history")}</h2>
      {!phase.operations.length && <p className="hint">{t("phase.history.empty")}</p>}
      {phase.operations.map(o => <div className="entry" key={o.id}><p><strong>{o.kind}</strong> {o.status}</p>
        {Array.isArray(o.result?.reasons) && (o.result!.reasons as string[]).length > 0 && <p>{(o.result!.reasons as string[]).join("; ")}</p>}
        <Evidence title={t("phase.history.evidence")} value={o} /></div>)}
      <Evidence title={t("phase.history.authorizations")} value={phase.authorizations} />
    </section>}
  </>;
}


const chips = (paths: string[]) => paths.map(p => <code key={p} className="chip">{p}</code>);

/** P010-T005: documents of a finished phase against what its closure left; the adopted base is history. */
function ClosureDocuments({ phase, closure }: { phase: S["PhaseRead"]; closure: S["PhaseClosureRead"] }) {
  const { t, n, rich } = useI18n();
  const { project } = useWorkspace();
  const archive = closure.archive;
  return <>
    <Fields items={[
      [t("phase.closure.archive"), archive ? <Link to={{ name: "docs", project, path: archive }}><code>{archive}/</code></Link> : <span className="muted">{t("phase.closure.no_archive")}</span>],
      [t("phase.closure.commit"), closure.commit ? <Hash value={closure.commit} /> : <span className="muted">—</span>],
    ]} />
    {closure.archive_altered === null ? <p className="state state-error">{t("phase.closure.archive_unreadable")}</p>
      : closure.archive_altered.length ? <p className="state state-error">{t("phase.closure.archive_altered")} {chips(closure.archive_altered)}</p>
        : archive && <p className="hint">{n("phase.closure.archive_intact", closure.archive_files.length)}</p>}
    {closure.renewed.length > 0 && <p className="hint">{closure.status === "ABANDONED" ? t("phase.closure.renewed_abandon") : t("phase.closure.renewed_close")} {chips(closure.renewed)}</p>}
    {phase.successor !== null
      ? <p className="hint">{rich("phase.closure.superseded", { phase: <code>{phase.successor}</code> })}</p>
      : closure.changed === null ? <p className="state state-error">{t("phase.documents.unreadable")}</p>
        : closure.changed.length ? <p className="state state-attention">{t("phase.closure.changed")} {chips(closure.changed)}</p>
          : <p className="hint">{t("phase.closure.unchanged")}</p>}
    <Evidence title={t("phase.closure.evidence")} value={{ ...phase.documents, expected: closure.documents }} />
  </>;
}

/** Result and base of the check that authorized the closure: history, never recomputed from today's documents. */
function ClosureCheck({ closure }: { closure: S["PhaseClosureRead"] }) {
  const { t, rich } = useI18n();
  const check = closure.check;
  const abandoned = closure.status === "ABANDONED";
  return <>
    <p className="hint">{closure.finished_at
      ? rich(abandoned ? "phase.closure.abandoned_at" : "phase.closure.closed_at", { date: when(closure.finished_at) })
      : t(abandoned ? "phase.closure.abandoned" : "phase.closure.closed")}{closure.reason ? ` ${t("phase.closure.reason", { reason: closure.reason })}` : ""}</p>
    <Fields items={[
      ...(check ? [[t("stats.column.result"), check.verdict] as [string, string]] : []),
      [t("docs.review.base"), <Hash value={String(closure.binding.head)} />],
      [t("phase.evidence"), <Hash value={closure.binding.binding_sha256 as string} />],
      [t("phase.tag"), closure.tag ? <code>{String(closure.tag.ref)}</code> : <span className="muted">{t("phase.no_tag")}</span>],
    ]} />
    {check?.summary && <p>{check.summary}</p>}
    {!!check?.exit_criteria_results.length && <ul className="checklist">{check.exit_criteria_results.map((item, i) =>
      <li key={i}>{t(item.passed ? "phase.criterion.met" : "phase.criterion.unmet", { criterion: String(item.criterion) })}</li>)}</ul>}
    <Evidence title={t("phase.closure.registered")} value={closure} />
  </>;
}
