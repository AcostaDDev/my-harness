import { useState } from "react";
import { confirmOnce, createOnce, managed } from "../managed-api";
import type { S } from "../managed-api";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { isTypeScriptRecipe, pendingPreparationStep, preparationStatus, preparationStepLabel, recipeModes, recipeText } from "../preparation.ts";
import { DiffBlock, Evidence, Hash, Stale, usePoll } from "../ui";
import { preparationChange } from "../project-profile";
import { useWorkspace } from "../workspace";

type Plan = S["PreparationPlanRead"];
type Change = S["PreparationChangeInput"] | S["ProfilePreparationChangeInput"];

const STEP_STATUS: Record<string, MessageKey> = { DONE: "preparation.step_status.done", PENDING: "preparation.step_status.pending" };

/** A started step is only in progress while the operation works; otherwise its result is not accredited. */
function stepStatus(status: string, working: boolean, t: (key: MessageKey) => string): string {
  if (status === "STARTED") return t(working ? "preparation.step_status.started" : "preparation.step_status.unaccredited");
  return STEP_STATUS[status] ? t(STEP_STATUS[status]) : status;
}

export function Preparation({ configuration }: { configuration?: S["ProjectConfigurationRead"] } = {}) {
  const { project, refresh, busy, operate } = useWorkspace();
  const { t, rich } = useI18n();
  const read = usePoll<S["PreparationRead"]>(`/projects/${project}/preparation`, 1500, refresh);
  const [mode, setMode] = useState<"offline" | "network">("offline");
  const [preview, setPreview] = useState<{ plan: Plan; change: Change }>();
  const [journal, setJournal] = useState<S["PreparationOperationRead"]>();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const data = read.data;
  if (!data?.available) return null;
  const text = (named: MessageKey, generic: MessageKey) => recipeText(data.recipe, t, named, generic);
  const modes = recipeModes(data.recipe, t);
  const typescript = isTypeScriptRecipe(data.recipe);
  const op = data.operation;
  const working = op?.status === "QUEUED" || op?.status === "ACTIVE";
  const retry = op && ["FAILED", "RECOVERY_REQUIRED", "CANCELLED"].includes(op.status);
  const next = op ? pendingPreparationStep(op.steps as { number: number; status: string }[]) : undefined;
  async function show() {
    const change: Change = configuration ? preparationChange(configuration, data!.project_version, mode,
      retry ? { id: op!.id, step: next } : undefined) : { expected_version: data!.project_version, mode,
      ...(retry ? { previous_id: op!.id, retry_step: next } : {}) };
    const plan = await managed<Plan>(`/projects/${project}/preparation/preview`, change);
    setPreview({ plan, change }); setConfirmed(false);
  }
  const control = (action: string) => operate(async () => {
    await createOnce(`/preparations/${op!.id}/${action}`, {
      expected_version: op!.version, plan_sha256: op!.plan_sha256,
    } satisfies S["PreparationControlInput"]);
    setPreview(undefined); setConfirmed(false);
  });
  return <section className="panel" aria-labelledby="recipe-preparation">
    <h2 id="recipe-preparation">{text("preparation.title", "preparation.title_generic")}</h2>
    <Stale error={read.error} />
    <p>{configuration ? t("profile.prepare_hint") : typescript ? t("preparation.lede.typescript") : t("preparation.lede.django")}</p>
    {data.prepared && <p className="state state-ok" role="status">{text("preparation.prepared", "preparation.prepared_generic")}</p>}
    {data.diagnostic && <p className="state state-attention">{data.diagnostic}</p>}
    {op && <>
      <p role="status">{rich("preparation.operation", { status: <strong>{preparationStatus(op.status, data.recipe, t)}</strong>, id: <code>{op.id}</code> })}</p>
      <progress max={op.steps.length} value={op.steps.filter(s => s.status === "DONE").length} aria-label={t("preparation.progress")} />
      <ol>{op.steps.map(s => <li key={String(s.id)}>{preparationStepLabel(data.recipe, (s.spec ?? {}) as Record<string, unknown>, t)} · {stepStatus(String(s.status), working, t)}</li>)}</ol>
      {op.diagnostic && <p className="state state-attention">{op.diagnostic}</p>}
      <button className="button-quiet" disabled={busy} onClick={() => void operate(async () => {
        setJournal(await managed<S["PreparationOperationRead"]>(`/preparations/${op.id}`));
      })}>{t("preparation.journal")}</button>
      {journal?.id === op.id && <Evidence title={t("preparation.journal_evidence")} value={journal} />}
      {working && <button className="button-quiet" disabled={busy || op.cancel_requested} onClick={() => void control("cancel")}>{t("preparation.cancel")}</button>}
      {retry && <button className="button-quiet" disabled={busy} onClick={() => void control("confirm-stopped")}>{t("preparation.confirm_stopped")}</button>}
    </>}
    {!data.prepared && !working && <>
      <label>{t("preparation.mode")}<select value={mode} onChange={e => { setMode(e.target.value as "offline" | "network"); setPreview(undefined); setConfirmed(false); }}>
        <option value="offline">{modes.offline}</option>
        <option value="network">{modes.network}</option>
      </select></label>
      <p className="hint">{modes.hint}</p>
      <button disabled={busy || !!op && !retry} onClick={() => void operate(show)}>{retry ? next === undefined ? t("preparation.review_retry_pending") : t("preparation.review_retry", { step: next }) : t("preparation.review")}</button>
    </>}
    {preview && <div className="decision">
      <p>{rich("preparation.preview", { root: <code>{preview.plan.root}</code>, mode: preview.plan.mode })}{preview.plan.work_language && ` · ${t("preparation.work_language", { language: preview.plan.work_language })}`} · {rich("preparation.preview_hash", { hash: <Hash value={preview.plan.preview_sha256} /> })}</p>
      <h3>{t("preparation.files")}</h3>
      {preview.plan.files.map(file => <details key={String(file.path)}><summary><code>{String(file.path)}</code> · <Hash value={String(file.sha256)} /></summary><DiffBlock diff={String(file.diff ?? "")} label={t("preparation.new_file", { path: String(file.path) })} /><details><summary>{t("preparation.full_content")}</summary><pre>{String(file.content)}</pre></details></details>)}
      <h3>{t("preparation.commands")}</h3>
      <ol>{preview.plan.steps.map((step, n) => <li key={n}><strong>{preparationStepLabel(preview.plan.recipe, step, t)}</strong>{Array.isArray(step.argv) && <pre>{JSON.stringify(step.argv)}</pre>}</li>)}</ol>
      <Evidence title={t("preparation.plan_evidence")} value={preview.plan} />
      {configuration && <label>{t("docs.review.reason")}<input value={reason} onChange={e => setReason(e.target.value)} maxLength={1000} /></label>}
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("preparation.authorize")}</label>
      <button disabled={busy || !confirmed || !!configuration && !reason.trim()} onClick={() => void operate(async () => {
        await (configuration ? confirmOnce : createOnce)(`/projects/${project}/preparation/confirm`, {
          change: preview.change, preview_sha256: preview.plan.preview_sha256,
          ...(configuration ? { confirmed: true, reason } : {}),
        });
        setPreview(undefined); setConfirmed(false);
      })}>{text("preparation.confirm", "preparation.confirm_generic")}</button>
    </div>}
  </section>;
}
