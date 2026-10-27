import { useState, type KeyboardEvent, type ReactNode } from "react";
import { useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";
import { COMMAND_NAME, PATH_KEYS, TOOL_KEYS, domId, fromLines, hasTools, isObject, moved, multiline, nameIssue,
  profileTools, texts, toLines, toolsSupported, unmappedTools, withoutBlank, without } from "./profile-form.ts";
import type { Issues, Obj } from "./profile-form.ts";

// OT004: guided editors over the existing profile/commands/agent tables. Each control replaces only its own key,
// so values without a control (and unknown future keys) are carried over unchanged into the exact preview.
type Base = { scope: string; prefix: string; issues: Issues; readOnly?: boolean };

function Problem({ id, problem, hint }: { id: string; problem?: MessageKey; hint?: MessageKey }) {
  const { t } = useI18n();
  if (!problem && !hint) return null;
  return <p id={`${id}-hint`} className={problem ? "field-error" : "hint"}>{t(problem ?? hint!)}</p>;
}

/** One exact value per line; blank lines left while typing go away when the field loses focus. */
export function LinesField({ scope, prefix, issues, readOnly, label, hint, value, onChange }: Base & {
  label: string; hint?: MessageKey; value: unknown; onChange: (value: string[]) => void;
}) {
  const id = domId(scope, prefix);
  const values = texts(value);
  const locked = readOnly || multiline(value);
  return <div className="lines-field">
    <label htmlFor={id}>{label}</label>
    <textarea id={id} rows={Math.min(8, Math.max(2, values.length + 1))} spellCheck={false} readOnly={locked}
      value={toLines(values)} aria-invalid={!!issues[prefix]} aria-describedby={`${id}-hint`}
      onChange={event => onChange(fromLines(event.target.value))}
      onBlur={() => { if (!locked && values.includes("")) onChange(withoutBlank(values)); }} />
    <Problem id={id} problem={issues[prefix]} hint={multiline(value) ? "editor.multiline" : hint ?? "editor.lines_hint"} />
  </div>;
}

function NumberField({ scope, prefix, issues, readOnly, label, value, onChange }: Base & {
  label: MessageKey; value: unknown; onChange: (value: number | undefined) => void;
}) {
  const { t } = useI18n();
  const id = domId(scope, prefix);
  return <div>
    <label htmlFor={id}>{t(label)}</label>
    <input id={id} type="number" step="any" readOnly={readOnly} value={value === undefined ? "" : String(value)}
      aria-invalid={!!issues[prefix]} aria-describedby={issues[prefix] ? `${id}-hint` : undefined}
      onChange={event => onChange(event.target.value === "" ? undefined : Number(event.target.value))} />
    <Problem id={id} problem={issues[prefix]} />
  </div>;
}

/** Named text values (environment, executables). Existing names stay fixed; renaming is remove + add. */
export function KeyValueField({ scope, prefix, issues, readOnly, legend, hint, value, onChange, nameLabel, valueLabel,
  fixed, namePattern, exclude = [], children }: Base & {
  legend: string; hint?: MessageKey; value: unknown; onChange: (value: Obj) => void; nameLabel: MessageKey;
  valueLabel: MessageKey; fixed?: boolean; namePattern?: RegExp; exclude?: string[]; children?: ReactNode;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [item, setItem] = useState("");
  const [problem, setProblem] = useState<MessageKey>();
  const current = isObject(value) ? value : {};
  const entries = Object.entries(current).filter(([key]) => !exclude.includes(key));
  const id = domId(scope, prefix);
  function add() {
    const issue = nameIssue(name, Object.keys(current), namePattern);
    setProblem(issue);
    if (issue) return;
    onChange({ ...current, [name]: item }); setName(""); setItem("");
  }
  const enter = (event: KeyboardEvent) => { if (event.key === "Enter") { event.preventDefault(); add(); } };
  return <fieldset id={id} tabIndex={-1} className="key-values" aria-describedby={`${id}-hint`}>
    <legend>{legend}</legend>
    <Problem id={id} problem={issues[prefix]} hint={hint} />
    {entries.length > 0 && <ul className="entry-list">{entries.map(([key, text]) => {
      const field = domId(scope, `${prefix}.${key}`);
      const issue = issues[`${prefix}.${key}`];
      return <li key={key} className="key-value">
        <label htmlFor={field}><code>{key}</code></label>
        <input id={field} value={typeof text === "string" ? text : JSON.stringify(text)} spellCheck={false}
          readOnly={readOnly || typeof text !== "string"} aria-invalid={!!issue} aria-describedby={issue ? `${field}-hint` : undefined}
          onChange={event => onChange({ ...current, [key]: event.target.value })} />
        {!readOnly && !fixed && <button type="button" className="button-quiet" aria-label={t("editor.remove_named", { name: key })}
          onClick={() => onChange(without(current, key))}>{t("editor.remove")}</button>}
        <Problem id={field} problem={issue} />
      </li>;
    })}</ul>}
    {children}
    {!readOnly && !fixed && <div className="form-row key-value-add">
      <div><label htmlFor={`${id}-new-name`}>{t(nameLabel)}</label>
        <input id={`${id}-new-name`} value={name} spellCheck={false} aria-invalid={!!problem}
          aria-describedby={problem ? `${id}-new-error` : undefined}
          onChange={event => { setName(event.target.value); setProblem(undefined); }} onKeyDown={enter} /></div>
      <div><label htmlFor={`${id}-new-value`}>{t(valueLabel)}</label>
        <input id={`${id}-new-value`} value={item} spellCheck={false} onChange={event => setItem(event.target.value)} onKeyDown={enter} /></div>
      <button type="button" className="button-quiet" aria-label={`${t("editor.add_entry")} · ${legend}`} onClick={add}>{t("editor.add_entry")}</button>
      {problem && <p id={`${id}-new-error`} className="field-error">{t(problem)}</p>}
    </div>}
    {!readOnly && !fixed && namePattern === COMMAND_NAME && <p className="hint">{t("editor.name_hint")}</p>}
  </fieldset>;
}

/** Order, removal and addition of list items with plain buttons, reachable by keyboard. */
function ItemActions({ index, count, label, onChange }: { index: number; count: number; label: string;
  onChange: (offset: number | "remove") => void }) {
  const { t } = useI18n();
  return <div className="actions item-actions">
    <button type="button" className="button-quiet" disabled={index === 0} aria-label={`${t("editor.move_up")} · ${label}`}
      onClick={() => onChange(-1)}>{t("editor.move_up")}</button>
    <button type="button" className="button-quiet" disabled={index === count - 1} aria-label={`${t("editor.move_down")} · ${label}`}
      onClick={() => onChange(1)}>{t("editor.move_down")}</button>
    <button type="button" className="button-quiet" aria-label={t("editor.remove_named", { name: label })}
      onClick={() => onChange("remove")}>{t("editor.remove")}</button>
  </div>;
}

function CommandFields({ scope, prefix, issues, readOnly, value, onChange, junit, title, actions }: Base & {
  value: Obj; onChange: (value: Obj) => void; junit?: boolean; title: string; actions?: ReactNode;
}) {
  const { t } = useI18n();
  const id = domId(scope, prefix);
  const cwd = domId(scope, `${prefix}.cwd`);
  const report = isObject(value.junit) ? value.junit : undefined;
  const reportField = (key: "path" | "coverage", label: MessageKey) => {
    const field = domId(scope, `${prefix}.junit.${key}`);
    const issue = issues[`${prefix}.junit.${key}`];
    return <div><label htmlFor={field}>{t(label)}</label>
      <input id={field} value={String(report?.[key] ?? "")} readOnly={readOnly} spellCheck={false} aria-invalid={!!issue}
        aria-describedby={issue ? `${field}-hint` : undefined}
        onChange={event => onChange({ ...value, junit: { ...report, [key]: event.target.value } })} />
      <Problem id={field} problem={issue} /></div>;
  };
  return <fieldset id={id} tabIndex={-1} className="command-entry">
    <legend>{title}</legend>
    <Problem id={id} problem={issues[prefix]} />
    <LinesField scope={scope} prefix={`${prefix}.argv`} issues={issues} readOnly={readOnly} label={t("editor.argv")}
      hint="editor.argv_hint" value={value.argv} onChange={argv => onChange({ ...value, argv })} />
    <div className="form-row">
      <div><label htmlFor={cwd}>{t("editor.cwd")}</label>
        <input id={cwd} value={typeof value.cwd === "string" ? value.cwd : ""} placeholder="." readOnly={readOnly} spellCheck={false}
          aria-invalid={!!issues[`${prefix}.cwd`]} aria-describedby={issues[`${prefix}.cwd`] ? `${cwd}-hint` : undefined}
          onChange={event => onChange(event.target.value === "" ? without(value, "cwd") : { ...value, cwd: event.target.value })} />
        <Problem id={cwd} problem={issues[`${prefix}.cwd`]} /></div>
      <NumberField scope={scope} prefix={`${prefix}.timeout_seconds`} issues={issues} readOnly={readOnly} label="editor.command_timeout"
        value={value.timeout_seconds} onChange={timeout => onChange(timeout === undefined ? without(value, "timeout_seconds") : { ...value, timeout_seconds: timeout })} />
    </div>
    <KeyValueField scope={scope} prefix={`${prefix}.environment`} issues={issues} readOnly={readOnly}
      legend={t("editor.command_environment")} value={value.environment} nameLabel="editor.variable" valueLabel="editor.value"
      onChange={environment => onChange(Object.keys(environment).length || "environment" in value ? { ...value, environment } : value)} />
    {junit && <>
      <label className="check"><input type="checkbox" checked={value.junit !== undefined} disabled={readOnly}
        onChange={event => onChange(event.target.checked ? { ...value, junit: { path: "", coverage: "" } } : without(value, "junit"))} />
        {t("editor.junit")}</label>
      {value.junit !== undefined && <div className="form-row">{reportField("path", "editor.junit_path_label")}
        {reportField("coverage", "editor.junit_coverage")}</div>}
    </>}
    {actions}
  </fieldset>;
}

export function CommandList({ scope, prefix, issues, readOnly, legend, hint, value, onChange, junit }: Base & {
  legend: MessageKey; hint: MessageKey; value: unknown; onChange: (value: unknown[]) => void; junit?: boolean;
}) {
  const { t } = useI18n();
  const items: unknown[] = Array.isArray(value) ? value : [];
  const id = domId(scope, prefix);
  return <fieldset id={id} tabIndex={-1} className="command-sequence">
    <legend>{t(legend)}</legend>
    <Problem id={id} problem={issues[prefix]} hint={hint} />
    {items.map((command, index) => {
      const title = t("editor.command_number", { number: index + 1 });
      return isObject(command)
        ? <CommandFields key={index} scope={scope} prefix={`${prefix}.${index}`} issues={issues} readOnly={readOnly} title={title}
            value={command} junit={junit} onChange={next => onChange(items.map((item, at) => at === index ? next : item))}
            actions={!readOnly && <ItemActions index={index} count={items.length} label={title}
              onChange={change => onChange(change === "remove" ? items.filter((_, at) => at !== index) : moved(items, index, change))} />} />
        : <p key={index} className="field-error">{title} · {t("editor.command_invalid")}</p>;
    })}
    {!readOnly && <button type="button" className="button-quiet" aria-label={`${t("editor.add_command")} · ${t(legend)}`}
      onClick={() => onChange([...items, { argv: [] }])}>{t("editor.add_command")}</button>}
  </fieldset>;
}

function PrefixList({ scope, prefix, issues, readOnly, value, onChange }: Base & { value: unknown; onChange: (value: unknown[]) => void }) {
  const { t } = useI18n();
  const items: unknown[] = Array.isArray(value) ? value : [];
  const id = domId(scope, prefix);
  return <fieldset id={id} tabIndex={-1}>
    <legend>{t("editor.prefixes")}</legend>
    <Problem id={id} problem={issues[prefix]} hint="editor.prefixes_hint" />
    {items.map((argv, index) => {
      const label = t("editor.prefix_number", { number: index + 1 });
      return <div key={index} className="command-entry">
        <LinesField scope={scope} prefix={`${prefix}.${index}`} issues={issues} readOnly={readOnly} label={label}
          hint="editor.argv_hint" value={argv} onChange={next => onChange(items.map((item, at) => at === index ? next : item))} />
        {!readOnly && <ItemActions index={index} count={items.length} label={label}
          onChange={change => onChange(change === "remove" ? items.filter((_, at) => at !== index) : moved(items, index, change))} />}
      </div>;
    })}
    {!readOnly && <button type="button" className="button-quiet" onClick={() => onChange([...items, []])}>{t("editor.add_prefix")}</button>}
  </fieldset>;
}

const PATH_LABELS: Record<typeof PATH_KEYS[number], [MessageKey, MessageKey]> = {
  protected_paths: ["editor.protected_paths", "editor.protected_hint"],
  sensitive_paths: ["editor.sensitive_paths", "editor.sensitive_hint"],
  sensitive_allowlist: ["editor.sensitive_allowlist", "editor.allowlist_hint"],
  data_model_paths: ["editor.data_model_paths", "editor.data_model_hint"],
};

/** Profile: executor instructions, ordered commands, prefixes, path policies and the optional formatter pair. */
export function ProfileFields({ scope, prefix, issues, readOnly, value, onChange }: Base & {
  value: Obj; onChange: (value: Obj) => void;
}) {
  const { t } = useI18n();
  const set = (key: string, item: unknown) => onChange({ ...value, [key]: item });
  const instructions = domId(scope, `${prefix}.executor_instructions`);
  const formatter = value.formatter_argv !== undefined || value.formatter_paths !== undefined;
  const tools = profileTools(value);
  return <div className="profile-fields">
    <label htmlFor={instructions}>{t("profile.instructions")}</label>
    <textarea id={instructions} rows={4} readOnly={readOnly} value={String(value.executor_instructions ?? "")}
      aria-invalid={!!issues[`${prefix}.executor_instructions`]} aria-describedby={`${instructions}-hint`}
      onChange={event => set("executor_instructions", event.target.value)} />
    <Problem id={instructions} problem={issues[`${prefix}.executor_instructions`]} hint="editor.instructions_hint" />
    <CommandList scope={scope} prefix={`${prefix}.preparation`} issues={issues} readOnly={readOnly} legend="editor.preparation"
      hint="editor.preparation_hint" value={value.preparation} onChange={items => set("preparation", items)} />
    <CommandList scope={scope} prefix={`${prefix}.validations`} issues={issues} readOnly={readOnly} legend="editor.validations"
      hint="editor.validations_hint" value={value.validations} junit onChange={items => set("validations", items)} />
    {tools.length > 0 && <p className="hint">{t("editor.tools_used", { names: tools.join(", ") })}</p>}
    <PrefixList scope={scope} prefix={`${prefix}.allowed_command_prefixes`} issues={issues} readOnly={readOnly}
      value={value.allowed_command_prefixes} onChange={items => set("allowed_command_prefixes", items)} />
    <fieldset><legend>{t("editor.paths")}</legend>
      {PATH_KEYS.map(key => <LinesField key={key} scope={scope} prefix={`${prefix}.${key}`} issues={issues} readOnly={readOnly}
        label={t(PATH_LABELS[key][0])} hint={PATH_LABELS[key][1]} value={value[key]}
        onChange={items => onChange(key === "sensitive_allowlist" && !items.length && !(key in value) ? value : { ...value, [key]: items })} />)}
    </fieldset>
    <fieldset><legend>{t("editor.formatter")}</legend>
      <p className="hint">{t("editor.formatter_hint")}</p>
      <label className="check"><input type="checkbox" checked={formatter} disabled={readOnly} onChange={event => onChange(event.target.checked
        ? { ...value, formatter_argv: value.formatter_argv ?? [], formatter_paths: value.formatter_paths ?? [] }
        : without(without(value, "formatter_argv"), "formatter_paths"))} />{t("editor.formatter_enable")}</label>
      {formatter && <>
        <LinesField scope={scope} prefix={`${prefix}.formatter_argv`} issues={issues} readOnly={readOnly} label={t("editor.formatter_argv")}
          hint="editor.formatter_argv_hint" value={value.formatter_argv} onChange={items => set("formatter_argv", items)} />
        <LinesField scope={scope} prefix={`${prefix}.formatter_paths`} issues={issues} readOnly={readOnly} label={t("editor.formatter_paths")}
          hint="editor.patterns_hint" value={value.formatter_paths} onChange={items => set("formatter_paths", items)} />
      </>}
    </fieldset>
  </div>;
}

/** Commands table: logical names → installed paths, command environment, authorization and limits. */
export function CommandsFields({ scope, prefix, issues, readOnly, value, onChange, profile, fixedNames }: Base & {
  value: Obj; onChange: (value: Obj) => void; profile?: unknown; fixedNames?: boolean;
}) {
  const { t } = useI18n();
  const set = (key: string, item: unknown) => onChange(item === undefined ? without(value, key) : { ...value, [key]: item });
  const missing = profile ? unmappedTools(profile, value) : [];
  const executables = isObject(value.executables) ? value.executables : {};
  return <div className="commands-fields">
    <KeyValueField scope={scope} prefix={`${prefix}.executables`} issues={issues} readOnly={readOnly} fixed={fixedNames}
      legend={t("editor.executables")} hint={fixedNames ? "editor.fixed_names" : "editor.executables_hint"} value={value.executables}
      nameLabel="editor.logical_name" valueLabel="editor.installed_path" namePattern={COMMAND_NAME}
      onChange={next => set("executables", next)}>
      {missing.length > 0 && <div className="state state-attention">
        <p>{t("editor.unmapped_names", { names: missing.join(", ") })}</p>
        {!readOnly && !fixedNames && <button type="button" className="button-quiet" onClick={() =>
          set("executables", { ...executables, ...Object.fromEntries(missing.map(name => [name, ""])) })}>{t("editor.add_unmapped")}</button>}
      </div>}
    </KeyValueField>
    <KeyValueField scope={scope} prefix={`${prefix}.environment`} issues={issues} readOnly={readOnly}
      legend={t("editor.command_env")} hint="editor.command_env_hint" value={value.environment}
      nameLabel="editor.variable" valueLabel="editor.value" onChange={next => set("environment", next)} />
    <fieldset id={domId(scope, `${prefix}.authorize_profile_commands`)} tabIndex={-1}>
      <legend>{t("editor.authorization")}</legend>
      <label className="check"><input type="checkbox" checked={value.authorize_profile_commands === true} disabled={readOnly}
        onChange={event => set("authorize_profile_commands", event.target.checked)} />{t("editor.authorize")}</label>
      <Problem id={domId(scope, `${prefix}.authorize_profile_commands`)} problem={issues[`${prefix}.authorize_profile_commands`]} hint="editor.authorize_hint" />
      <CommandList scope={scope} prefix={`${prefix}.authorized`} issues={issues} readOnly={readOnly} legend="editor.authorized_extra"
        hint="editor.authorized_hint" value={value.authorized ?? []}
        onChange={items => set("authorized", items.length || "authorized" in value ? items : undefined)} />
      <div className="form-row">
        <NumberField scope={scope} prefix={`${prefix}.max_timeout_seconds`} issues={issues} readOnly={readOnly}
          label="editor.max_timeout_label" value={value.max_timeout_seconds} onChange={item => set("max_timeout_seconds", item)} />
        <NumberField scope={scope} prefix={`${prefix}.max_output_bytes`} issues={issues} readOnly={readOnly}
          label="editor.max_output_label" value={value.max_output_bytes} onChange={item => set("max_output_bytes", item)} />
      </div>
    </fieldset>
  </div>;
}

/** Tool capabilities exist only for a Claude Code executor; elsewhere they are explained, never offered. */
export function ToolCapabilities({ scope, prefix, issues, readOnly, value, onChange, roles }: Base & {
  value: Obj; onChange: (value: Obj) => void; roles: string[];
}) {
  const { t } = useI18n();
  const supported = toolsSupported(value.provider, roles);
  // The `.tools` issue focuses the inventory field when it exists, otherwise this group.
  const id = domId(scope, `${prefix}.${supported ? "tool_capabilities" : "tools"}`);
  const labels: Record<typeof TOOL_KEYS[number], MessageKey> = {
    tools: "editor.tools", allowed_tools: "editor.allowed_tools", grantable_tools: "editor.grantable_tools" };
  return <fieldset id={id} tabIndex={-1} className="tool-capabilities">
    <legend>{t("editor.tools_for")}</legend>
    {roles.includes("reviewer") && <p className="hint">{t("editor.reviewer_fixed")}</p>}
    {value.provider === "codex" && <p className="hint">{t("editor.codex_fixed")}</p>}
    {supported ? <>
      <p className="hint">{t("editor.tools_hint")}</p>
      {TOOL_KEYS.map(key => <LinesField key={key} scope={scope} prefix={`${prefix}.${key}`} issues={issues} readOnly={readOnly}
        label={t(labels[key])} hint={key === "grantable_tools" ? "editor.grantable_hint" : undefined} value={value[key]}
        onChange={items => onChange(items.length || key in value ? { ...value, [key]: items } : value)} />)}
    </> : hasTools(value) && <div className="state state-attention">
      <p className={issues[`${prefix}.tools`] ? "field-error" : undefined}>{t("editor.tools_unsupported")}</p>
      <ul>{TOOL_KEYS.filter(key => texts(value[key]).length).map(key => <li key={key}>{t(labels[key])}: <code>{texts(value[key]).join(", ")}</code></li>)}</ul>
      {!readOnly && <button type="button" className="button-quiet" onClick={() => onChange(TOOL_KEYS.reduce(without, value))}>{t("editor.remove_tools")}</button>}
    </div>}
  </fieldset>;
}

/** An agent declaration (project copy or preset): client, limits, environment and tool capabilities. */
export function AgentFields({ scope, prefix, issues, readOnly, value, onChange, roles, providerFixed, children }: Base & {
  value: Obj; onChange: (value: Obj) => void; roles: string[]; providerFixed?: boolean; children?: ReactNode;
}) {
  const { t } = useI18n();
  const provider = domId(scope, `${prefix}.provider`);
  const executable = domId(scope, `${prefix}.executable`);
  const version = domId(scope, `${prefix}.cli_version`);
  const argv = texts(value.executable);
  return <div className="agent-fields">
    <div className="form-row">
      <div><label htmlFor={provider}>{t(providerFixed ? "editor.provider_fixed" : "settings.provider")}</label>
        {providerFixed || readOnly
          ? <input id={provider} readOnly value={String(value.provider ?? "")} />
          : <select id={provider} value={String(value.provider ?? "")} aria-invalid={!!issues[`${prefix}.provider`]}
              onChange={event => onChange({ ...value, provider: event.target.value })}>
              <option value="">{t("configuration.choose")}</option><option value="codex">Codex</option><option value="claude">Claude</option>
            </select>}
        <Problem id={provider} problem={issues[`${prefix}.provider`]} /></div>
      {children}
      <NumberField scope={scope} prefix={`${prefix}.timeout_seconds`} issues={issues} readOnly={readOnly} label="configuration.timeout"
        value={value.timeout_seconds} onChange={item => onChange(item === undefined ? without(value, "timeout_seconds") : { ...value, timeout_seconds: item })} />
    </div>
    <div className="form-row">
      <div><label htmlFor={executable}>{t("configuration.cli_path")}</label>
        <input id={executable} value={argv[0] ?? ""} readOnly={readOnly} spellCheck={false} aria-invalid={!!issues[`${prefix}.executable`]}
          aria-describedby={`${executable}-hint`}
          onChange={event => onChange(event.target.value ? { ...value, executable: [event.target.value, ...argv.slice(1)] } : without(value, "executable"))} />
        <Problem id={executable} problem={issues[`${prefix}.executable`]} hint="configuration.cli_hint" /></div>
      <div><label htmlFor={version}>{t("editor.cli_version")}</label>
        <input id={version} value={String(value.cli_version ?? "")} readOnly={readOnly} spellCheck={false}
          aria-invalid={!!issues[`${prefix}.cli_version`]} aria-describedby={issues[`${prefix}.cli_version`] ? `${version}-hint` : undefined}
          onChange={event => onChange(event.target.value ? { ...value, cli_version: event.target.value } : without(value, "cli_version"))} />
        <Problem id={version} problem={issues[`${prefix}.cli_version`]} /></div>
    </div>
    <KeyValueField scope={scope} prefix={`${prefix}.environment`} issues={issues} readOnly={readOnly}
      legend={t("editor.environment")} hint="editor.environment_hint" value={value.environment}
      nameLabel="editor.variable" valueLabel="editor.value" onChange={environment => onChange({ ...value, environment })} />
    <ToolCapabilities scope={scope} prefix={prefix} issues={issues} readOnly={readOnly} value={value} onChange={onChange} roles={roles} />
  </div>;
}

/** What a reviewed save changes: per project, whether a new preparation is needed, and derived global copies. */
export function SaveImpact({ preview }: { preview: { impact?: string[]; changes?: Obj[] | null; effects?: Obj | null } }) {
  const { t } = useI18n();
  const effects = preview.effects;
  if (!isObject(effects)) return null;
  const projects: Obj[] = Array.isArray(effects.projects) ? effects.projects.filter(isObject) : [];
  const jobs = Array.isArray(effects.jobs) ? effects.jobs.length : 0;
  const global = (preview.impact ?? []).includes("global");
  const derived = (preview.changes ?? []).map(change => change.scope).filter((scope): scope is string => typeof scope === "string" && scope !== "global");
  return <div className="save-impact">
    <h4>{t("editor.impact_title")}</h4>
    <ul>
      {global && <li>{t(derived.length ? "editor.impact_derived" : "editor.impact_global_only", { scopes: derived.join(", ") })}</li>}
      {projects.filter(project => !global || project.preparation_required).map(project => <li key={String(project.scope)}>
        <code>{String(project.scope)}</code> · {t(project.preparation_required ? "editor.impact_preparation" : "editor.impact_reuse")}</li>)}
      <li>{t("editor.impact_frozen", { count: jobs })}</li>
    </ul>
  </div>;
}
