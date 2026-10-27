import { useState } from "react";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { jobRequest } from "../managed-api";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { runRoute } from "../router.ts";
import { Empty, Status, when, usePoll } from "../ui";
import { useWorkspace } from "../workspace";
import { runBody, sourcePhases, sourceTasks } from "../task-sources.ts";
import { recipeText } from "../preparation.ts";

export const PURPOSES: Record<S["ManagedRunSummaryRead"]["purpose"], MessageKey> = {
  task: "purpose.task", phase_check: "purpose.phase_check", phase_close: "purpose.phase_close", chat: "purpose.chat",
  document_export: "purpose.document_export", bootstrap: "purpose.bootstrap", bootstrap_discovery: "purpose.bootstrap_discovery",
  definition: "purpose.definition", phase_planning: "purpose.phase_planning", project_import: "purpose.project_import",
  onboarding: "purpose.onboarding", import_commit: "purpose.import_commit", document_edit: "purpose.document_edit",
  phase_transition: "purpose.phase_transition",
};

/** Runs as rows linked to their canonical URL; the task and the phase link to their pages. */
export function RunTable({ runs, project, show = ["task", "phase"] }: { runs: S["ManagedRunSummaryRead"][]; project: string; show?: ("task" | "phase")[] }) {
  const { t } = useI18n();
  if (!runs.length) return <Empty title={t("runs.empty.title")}>
    <p>{t("runs.empty.body")}</p></Empty>;
  return <div className="table-scroll" role="region" aria-label={t("runs.table")} tabIndex={0}>
    <table className="table">
      <thead><tr><th scope="col">{t("runs.column.run")}</th>{show.includes("task") && <th scope="col">{t("runs.column.task")}</th>}{show.includes("phase") && <th scope="col">{t("runs.column.phase")}</th>}
        <th scope="col">{t("runs.column.status")}</th><th scope="col">{t("runs.column.type")}</th><th scope="col" className="numeric">{t("runs.column.revisions")}</th><th scope="col">{t("runs.column.updated")}</th></tr></thead>
      <tbody>{runs.map(run => {
        const route = runRoute({ ...run, project_id: run.project_id ?? project });
        return <tr key={run.id}>
          <td>{route ? <Link to={route} className="mono">{run.id.slice(0, 8)}</Link> : <code>{run.id.slice(0, 8)}</code>}</td>
          {show.includes("task") && <td><Link className="mono" to={{ name: "task", project, phase: run.phase_id, task: run.task_id }}>{run.task_id}</Link></td>}
          {show.includes("phase") && <td><Link className="mono" to={{ name: "phase", project, phase: run.phase_id }}>{run.phase_id}</Link></td>}
          <td><Status value={run.status} /></td>
          <td>{PURPOSES[run.purpose] ? t(PURPOSES[run.purpose]) : run.purpose}</td>
          <td className="numeric">{t("runs.revisions", { count: run.revisions, limit: run.revision_limit })}</td>
          <td>{when(run.updated_at)}</td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

/**
 * Enqueue a task. By default it is chosen from the live NEXT_STEPS and the contract is its literal section, with
 * its hash so the server rejects a changed document (P009-T020); manual mode is for what is not in it.
 * The phase or the task can be fixed by the page.
 */
export function TaskForm({ phase, task, title }: { phase?: string; task?: string; title?: string }) {
  const { t, rich } = useI18n();
  const { project, busy, operate, send } = useWorkspace();
  const preparation = usePoll<S["PreparationRead"]>(`/projects/${project}/preparation`, 2000);
  const info = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 2000);
  const configurationRequired = info.data?.versions.local_config === "local-config-9" && info.data.configuration_state !== "ACTIVE";
  const preparationRequired = !info.data || configurationRequired || !info.data.versions.project_configuration && preparation.data?.available && !preparation.data.prepared;
  const sources = usePoll<S["TaskSourcesRead"]>(`/projects/${project}/task-sources`, 5000);
  const items = sources.data?.items ?? [];
  const phases = sourcePhases(items, phase);
  const [manual, setManual] = useState(false);
  const [chosenPhase, setChosenPhase] = useState(phase ?? "");
  const [chosenTask, setChosenTask] = useState(task ?? "");
  const [taskId, setTaskId] = useState(task ?? "");
  const [phaseId, setPhaseId] = useState(phase ?? "");
  const [text, setText] = useState("");
  const [notes, setNotes] = useState("");
  const selectedPhase = chosenPhase || (phases.length === 1 ? phases[0] : "");
  const tasks = sourceTasks(items, selectedPhase, task);
  const source = tasks.find(item => item.task_id === (chosenTask || (task ?? ""))) ?? null;
  const offered = phases.length > 0 && (!task || tasks.length > 0);
  const fromDocuments = !manual && offered;
  const body = runBody(fromDocuments ? source : null, { task: taskId, phase: phaseId, text }, notes);
  const ready = fromDocuments ? source !== null : !!(text.trim() && taskId.trim() && phaseId.trim());
  return <section className="panel" aria-labelledby="task-form">
    <h2 id="task-form">{title ?? t("task_form.title")}</h2>
    <p className="hint">{t("task_form.hint")}</p>
    {configurationRequired && <p className="state state-attention">{t("profile.order")}</p>}
    {!configurationRequired && preparationRequired && <p className="state state-attention">{recipeText(preparation.data?.recipe, t, "task_form.preparation_required", "task_form.preparation_required_generic")}</p>}
    <form onSubmit={e => { e.preventDefault(); if (!busy && !preparationRequired && ready) void operate(() => send(jobRequest(`/projects/${project}/runs`, body))); }}>
      {fromDocuments ? <>
        <div className="form-row">
          <label>{t("task_form.phase")}<select value={selectedPhase} onChange={e => { setChosenPhase(e.target.value); setChosenTask(""); }} disabled={!!phase} required>
            {!selectedPhase && <option value="">{t("task_form.choose_phase")}</option>}
            {phases.map(code => <option key={code} value={code}>{code}</option>)}
          </select></label>
          <label>{t("task_form.task")}<select value={source?.task_id ?? ""} onChange={e => setChosenTask(e.target.value)} disabled={!!task} required>
            {!source && <option value="">{t("task_form.choose_task")}</option>}
            {tasks.map(item => <option key={item.task_id} value={item.task_id}>{item.task_id} — {item.title}</option>)}
          </select></label>
        </div>
        {source && <label>{t("task_form.contract")}<textarea value={source.text} readOnly rows={8} /></label>}
        {source && <p className="hint">{rich("task_form.source", { path: <code>{sources.data?.path}</code>, sha: <code>{source.sha256.slice(0, 12)}</code> })}</p>}
      </> : <>
        {(!task || !phase) && <div className="form-row">
          {!task && <label>{t("task_form.task")}<input value={taskId} onChange={e => setTaskId(e.target.value)} required maxLength={120} placeholder={phase ? `${phase}-T001` : "P001-T001"} /></label>}
          {!phase && <label>{t("task_form.phase")}<input value={phaseId} onChange={e => setPhaseId(e.target.value)} required maxLength={120} placeholder="P001" /></label>}
        </div>}
        <label>{t("task_form.contract")}<textarea value={text} onChange={e => setText(e.target.value)} required maxLength={200000} rows={8} /></label>
      </>}
      {sources.data?.diagnostics.map(item => <p key={item} className="hint">{item}</p>)}
      {offered && <label className="check"><input type="checkbox" checked={manual} onChange={e => setManual(e.target.checked)} />{t("task_form.manual")}</label>}
      {items.length > 0 && !offered && <p className="hint">{rich("task_form.not_in_source", { id: task ?? phase, path: <code>{sources.data?.path}</code> })}</p>}
      <label>{t("task_form.notes")}<textarea value={notes} onChange={e => setNotes(e.target.value)} maxLength={4000} rows={3} /></label>
      <p className="hint">{t("task_form.notes_hint")}</p>
      <button disabled={busy || preparationRequired || !ready}>{t("task_form.submit")}</button>
    </form>
  </section>;
}
