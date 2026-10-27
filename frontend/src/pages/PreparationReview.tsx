import type { S } from "../managed-api";
import { useI18n } from "../Language";
import { preparationCommand, preparationStepLabel } from "../preparation.ts";
import { DiffBlock, Evidence, Hash } from "../ui";

export const isGenericPreparation = (plan: S["PreparationPlanRead"]) => plan.contract === "project-profile-preparation-1";
const record = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value)
  ? value as Record<string, unknown> : {};

function Paths({ value }: { value: unknown }) {
  return Array.isArray(value) ? <ul>{value.map((path, n) => <li key={n}><code>{String(path)}</code></li>)}</ul> : null;
}

/** Render the two existing contracts without inventing recipe bytes for a generic write scope. */
export function PreparationReview({ plan }: { plan: S["PreparationPlanRead"] }) {
  const { t } = useI18n();
  const generic = isGenericPreparation(plan), technical = record(plan.technical);
  const missing = t("common.not_recorded_null");
  return <>
    <h3>{t(generic ? "preparation.write_scope" : "preparation.files")}</h3>
    {generic ? <>
      <p className="hint">{t("preparation.write_scope_hint")}</p>
      <ul>{plan.files.map((file, n) => <li key={n}><code>{String(file.path ?? missing)}</code> · {file.effect === "may create or modify"
        ? t("preparation.effect.write") : String(file.effect ?? missing)}</li>)}</ul>
      <p>{t("preparation.network_scope")} {Array.isArray(technical.network)
        ? technical.network.length ? technical.network.map(String).join(", ") : t("preparation.network_none") : missing}</p>
      <p>{t("preparation.scripts", { value: technical.scripts === true ? t("common.yes") : technical.scripts === false ? t("common.no") : missing })}</p>
    </> : plan.files.map(file => <details key={String(file.path)}><summary><code>{String(file.path)}</code> · <Hash value={String(file.sha256)} /></summary>
      <DiffBlock diff={String(file.diff ?? "")} label={t("preparation.new_file", { path: String(file.path) })} />
      <details><summary>{t("preparation.full_content")}</summary><pre>{String(file.content)}</pre></details></details>)}
    <h3>{t("preparation.commands")}</h3>
    <ol>{plan.steps.map((step, n) => {
      const command = preparationCommand(step), selection = record(step.selection);
      return <li key={n}>
        <strong>{preparationStepLabel(plan.recipe, step, t)}</strong>
        {generic && step.kind === "directories" && <Paths value={step.paths} />}
        {generic && step.kind === "executor" && <>
          <p>{t("preparation.executor_selection", { model: String(selection.model ?? missing), effort: String(selection.effort ?? missing) })}</p>
          {typeof selection.reason === "string" && <p>{selection.reason}</p>}
          <pre>{String(step.instructions ?? missing)}</pre>
          <p>{t("preparation.executor_scope")}</p><Paths value={step.write_paths} />
        </>}
        {Array.isArray(command.argv) && <pre>{JSON.stringify(command.argv)}</pre>}
        {generic && step.kind === "command" && <>
          <p>{t("preparation.command_context", { cwd: String(command.cwd ?? missing), seconds: String(command.timeout_seconds ?? missing) })}</p>
          <Evidence title={t("preparation.command_evidence")} value={{ executables: step.executables, environment: step.environment,
            command_environment: command.environment, max_timeout_seconds: step.max_timeout_seconds,
            max_output_bytes: step.max_output_bytes, network: step.network, scripts: step.scripts }} />
        </>}
        {generic && step.kind === "commit" && <>
          <p>{t("preparation.commit_hint")}</p>
          <Evidence title={t("preparation.commit_evidence")} value={plan.commit} />
        </>}
      </li>;
    })}</ol>
  </>;
}
