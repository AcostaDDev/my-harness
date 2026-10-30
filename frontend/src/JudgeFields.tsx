import { AgentFields } from "./ProfileFields";
import { useI18n } from "./Language";
import { efforts, modelOptions } from "./configuration";
import { domId, without } from "./profile-form";
import type { Issues, Obj } from "./profile-form";

/** Explicit format opt-in, independent owner selection; editing never invokes a model. */
export function JudgeFields({ form, onChange, issues, readOnly = false, scope }: {
  form: Obj; onChange: (form: Obj) => void; issues: Issues; readOnly?: boolean; scope: string;
}) {
  const { t } = useI18n();
  const judge = form.agents?.judge;
  const update = (value: Obj) => onChange({ ...form, agents: { ...form.agents, judge: value } });
  const model = domId(scope, "agents.judge.model"), effort = domId(scope, "agents.judge.effort");
  return <fieldset><legend>{t("settings.judge")}</legend>
    <p className="hint">{t("judge.configuration_hint")}</p>
    <label className="check"><input type="checkbox" checked={!!judge} disabled={readOnly} onChange={event => onChange(event.target.checked
      ? { ...form, format: scope === "configuration" ? "local-config-11" : "project-config-3", agents: { ...form.agents,
          judge: { provider: "", model: "", effort: "medium", timeout_seconds: 300, environment: { USER: "", PATH: "" } } } }
      : { ...form, agents: without(form.agents, "judge") })} />{t("judge.configure")}</label>
    {judge && <AgentFields scope={scope} prefix="agents.judge" roles={["judge"]} value={judge} issues={issues}
      readOnly={readOnly} onChange={update}>
      <div><label htmlFor={model}>{t("settings.model")}</label>
        <input id={model} list={`${model}-options`} value={String(judge.model ?? "")} readOnly={readOnly}
          aria-invalid={!!issues["agents.judge.model"]} onChange={event => update({ ...judge, model: event.target.value })} />
        <datalist id={`${model}-options`}>{modelOptions(String(judge.provider)).map(value => <option key={value}>{value}</option>)}</datalist>
        {issues["agents.judge.model"] && <p className="field-error">{t(issues["agents.judge.model"])}</p>}
      </div>
      <div><label htmlFor={effort}>{t("settings.effort")}</label>
        <select id={effort} disabled={readOnly} value={String(judge.effort ?? "")} aria-invalid={!!issues["agents.judge.effort"]}
          onChange={event => update({ ...judge, effort: event.target.value })}>
          {[...new Set([String(judge.effort ?? ""), ...(efforts[String(judge.provider)] ?? [])])].map(value => <option key={value}>{value}</option>)}
        </select>{issues["agents.judge.effort"] && <p className="field-error">{t(issues["agents.judge.effort"])}</p>}
      </div>
    </AgentFields>}
  </fieldset>;
}
