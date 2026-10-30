import { useEffect, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../Language";
import type { MessageKey } from "../i18n.ts";
import { managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import { Alert, DiffBlock, Evidence, Fields, Loading, PageHeader, Stale, message, usePoll } from "../ui";
import { baseChanged, candidate, change, changeField, efforts, errors, field, initialDraft, modeLabels,
  modelOptions, readAction, readDraft, refusalLine, sendAction, storeDraft, waitingReason } from "../configuration.ts";
import type { Action, Draft, LiveRefusal, Review } from "../configuration.ts";

import { Link } from "../navigation";
import { ConfigurationAssistance } from "./ConfigurationAssistance";
import { AgentFields, CommandsFields, KeyValueField, LinesField, ProfileFields, SaveImpact, ToolCapabilities } from "../ProfileFields";
import { GlobalBilling, ReferenceList } from "../BillingFields";
import { COMMAND_NAME, ENTRY_NAME, domId, emptyCommands, emptyProfile, isObject, nameIssue, texts, without } from "../profile-form.ts";
import type { Issues, Obj } from "../profile-form.ts";

import { JudgeFields } from "../JudgeFields";

const ROOT = "/configuration";
const idFor = (path: string) => domId("configuration", path);
// Never a valid model: MODEL_FORM requires a leading letter or digit.
const OTHER = "_other";

/** Packaged models of the provider; "Other" keeps a hand-written one, and a saved unknown model stays visible. */
function ModelChoice({ id, provider, value, problem, onChange }: {
  id: string; provider: string; value: string; problem?: MessageKey; onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  const known = modelOptions(provider);
  const [other, setOther] = useState(false);
  const custom = other || (!!value && !known.includes(value));
  return <div>
    <label htmlFor={id}>{t("settings.model")}</label>
    <select id={id} value={custom ? OTHER : value} aria-invalid={!!problem} aria-describedby={problem ? `${id}-error` : undefined}
      onChange={event => { const choice = event.target.value; setOther(choice === OTHER); onChange(choice === OTHER ? "" : choice); }}>
      <option value="">{t("configuration.choose_model")}</option>
      {known.map(model => <option key={model} value={model}>{model}</option>)}
      <option value={OTHER}>{t("configuration.other_model")}</option>
    </select>
    {custom && <input id={`${id}-other`} aria-label={t("configuration.custom_model")} value={value} spellCheck={false}
      onChange={event => onChange(event.target.value)} />}
    {problem && <p id={`${id}-error`} className="field-error">{t(problem)}</p>}
  </div>;
}

/** D238: why a confirmed set has not switched yet; each reason is current work that ends or is resolved explicitly. */
function Waiting({ reasons }: { reasons: string[] }) {
  const { t } = useI18n();
  if (!reasons.length) return null;
  return <ul className="configuration-waiting">{reasons.map(reason => {
    const { key, id } = waitingReason(reason);
    return <li key={reason}>{t(key, { id })}</li>;
  })}</ul>;
}

/** Corrections of a refused live candidate: project or role, setting, code and diagnostic. */
function Refusals({ items }: { items: LiveRefusal[] }) {
  const { t } = useI18n();
  return <ul>{items.map((item, index) => <li key={index}>{refusalLine(item)}
    {item.already_failing && <> · {t("configuration.live.already_failing")}</>}</li>)}</ul>;
}

export function ConfigurationFields({ draft, onChange, issues }: {
  draft: Draft; onChange: (draft: Draft) => void; issues: Record<string, MessageKey>;
}) {
  const { t } = useI18n();
  function update(path: string, value: unknown) { onChange({ ...draft, form: changeField(draft.form, path, value) }); }
  function input(path: string, label: MessageKey, type = "text") {
    const id = idFor(path);
    const problem = issues[path];
    return <div key={path}>
      <label htmlFor={id}>{t(label)}</label>
      <input id={id} name={path} type={type} step={type === "number" ? "any" : undefined} value={String(field(draft.form, path) ?? "")}
        aria-invalid={!!problem} aria-describedby={problem ? `${id}-error` : undefined}
        onChange={event => update(path, type === "number" ? (event.target.value === "" ? undefined : Number(event.target.value)) : event.target.value)} />
      {problem && <p id={`${id}-error`} className="field-error">{t(problem)}</p>}
    </div>;
  }
  function flag(path: string, label: MessageKey) {
    return <label className="check"><input type="checkbox" checked={field(draft.form, path) === true}
      onChange={event => update(path, event.target.checked)} />{t(label)}</label>;
  }
  const roots = field(draft.form, "registration.roots");
  return <>
    <fieldset><legend>{t("configuration.git")}</legend><div className="form-row">
      {input("git.executable", "configuration.git_path")}{input("git.author_name", "configuration.author_name")}
      {input("git.author_email", "configuration.author_email")}
    </div></fieldset>
    {(["reviewer", "executor"] as const).map(role => {
      const prefix = `agents.${role}`;
      const provider = String(field(draft.form, `${prefix}.provider`) ?? "");
      const argv = field(draft.form, `${prefix}.executable`);
      return <fieldset key={role}><legend>{t(role === "reviewer" ? "settings.reviewer" : "settings.executor")}</legend>
        <div className="form-row"><div><label htmlFor={idFor(`${prefix}.provider`)}>{t("settings.provider")}</label>
          <select id={idFor(`${prefix}.provider`)} value={provider} aria-invalid={!!issues[`${prefix}.provider`]}
            aria-describedby={issues[`${prefix}.provider`] ? `${idFor(`${prefix}.provider`)}-error` : undefined}
            onChange={event => {
              // A packaged model of the previous provider does not carry over; a hand-written one does.
              const model = String(field(draft.form, `${prefix}.model`) ?? "");
              const form = changeField(draft.form, `${prefix}.provider`, event.target.value);
              onChange({ ...draft, form: role === "reviewer" && modelOptions(provider).includes(model)
                && !modelOptions(event.target.value).includes(model) ? changeField(form, `${prefix}.model`, "") : form });
            }}>
            <option value="">{t("configuration.choose")}</option><option value="codex">Codex</option><option value="claude">Claude</option>
          </select>{issues[`${prefix}.provider`] && <p id={`${idFor(`${prefix}.provider`)}-error`} className="field-error">{t(issues[`${prefix}.provider`])}</p>}
        </div>
          {role === "reviewer" && <><ModelChoice key={provider} id={idFor(`${prefix}.model`)} provider={provider}
            value={String(field(draft.form, `${prefix}.model`) ?? "")} problem={issues[`${prefix}.model`]}
            onChange={value => update(`${prefix}.model`, value)} /><div>
            <label htmlFor={idFor(`${prefix}.effort`)}>{t("settings.effort")}</label>
            <select id={idFor(`${prefix}.effort`)} value={String(field(draft.form, `${prefix}.effort`) ?? "")}
              aria-invalid={!!issues[`${prefix}.effort`]} aria-describedby={issues[`${prefix}.effort`] ? "configuration-effort-error" : undefined}
              onChange={event => update(`${prefix}.effort`, event.target.value)}>
              {[...new Set([String(field(draft.form, `${prefix}.effort`) ?? ""), ...(efforts[provider] ?? [])])].map(value => <option key={value}>{value}</option>)}
            </select>{issues[`${prefix}.effort`] && <p id="configuration-effort-error" className="field-error">{t(issues[`${prefix}.effort`])}</p>}
          </div></>}
          {input(`${prefix}.timeout_seconds`, "configuration.timeout", "number")}
        </div>
        <label htmlFor={idFor(`${prefix}.executable`)}>{t("configuration.cli_path")}</label>
        <input id={idFor(`${prefix}.executable`)} value={Array.isArray(argv) ? String(argv[0] ?? "") : ""}
          aria-invalid={!!issues[`${prefix}.executable`]} aria-describedby={`${idFor(`${prefix}.executable`)}-hint`}
          onChange={event => update(`${prefix}.executable`, event.target.value ? [event.target.value, ...(Array.isArray(argv) ? argv.slice(1) : [])] : undefined)} />
        <p id={`${idFor(`${prefix}.executable`)}-hint`} className={issues[`${prefix}.executable`] ? "field-error" : "hint"}>
          {t(issues[`${prefix}.executable`] ?? "configuration.cli_hint")}</p>
        <div className="form-row">{input(`${prefix}.environment.USER`, "configuration.user")}
          {input(`${prefix}.environment.PATH`, "configuration.path")}{input(`${prefix}.environment.HOME`, "configuration.home")}</div>
        <AgentExtras prefix={prefix} role={role} value={field(draft.form, prefix)} issues={issues} onChange={next => update(prefix, next)} />
      </fieldset>;
    })}
    <JudgeFields scope="configuration" form={draft.form} issues={issues} onChange={form => onChange({ ...draft, form })} />
    <p className="hint">{t("configuration.executor_hint")}</p>
    <fieldset><legend>{t("configuration.storage")}</legend>
      <p className="hint">{t("configuration.storage_hint")}</p>
      {field(draft.form, "service.state_dir") !== undefined && <p><code className="path">{String(field(draft.form, "service.state_dir"))}</code></p>}
      <label htmlFor="configuration-roots">{t("configuration.roots")}</label>
      <textarea id="configuration-roots" rows={3} value={Array.isArray(roots) ? roots.join("\n") : String(roots ?? "")}
        aria-invalid={!!issues["registration.roots"]} aria-describedby="configuration-roots-hint"
        onChange={event => update("registration.roots", event.target.value.split("\n").filter(Boolean))} />
      <p id="configuration-roots-hint" className={issues["registration.roots"] ? "field-error" : "hint"}>
        {t(issues["registration.roots"] ?? "configuration.roots_hint")}</p>
      {flag("registration.bootstrap_enabled", "configuration.bootstrap")}{flag("service.supervisor", "configuration.supervisor")}
      <div className="form-row">{input("service.lease_seconds", "configuration.lease", "number")}
        {input("service.poll_seconds", "configuration.poll", "number")}</div>
    </fieldset>
    <GlobalCatalog form={draft.form} issues={issues} update={update} />
    <GlobalBilling scope="configuration" form={draft.form} issues={issues} onChange={form => onChange({ ...draft, form })} />
    <p className="hint">{t("configuration.advanced_hint")}</p>
  </>;
}

/** Environment beyond USER/PATH/HOME, an optional version pin and the role's tool capabilities (OT004). */
function AgentExtras({ prefix, role, value, issues, onChange }: {
  prefix: string; role: "reviewer" | "executor"; value: unknown; issues: Issues; onChange: (value: Obj) => void;
}) {
  const { t } = useI18n();
  const agent = isObject(value) ? value : {};
  const version = idFor(`${prefix}.cli_version`);
  return <>
    <KeyValueField scope="configuration" prefix={`${prefix}.environment`} issues={issues} legend={t("editor.other_environment")}
      hint="editor.environment_hint" value={agent.environment} exclude={["USER", "PATH", "HOME"]}
      nameLabel="editor.variable" valueLabel="editor.value" onChange={environment => onChange({ ...agent, environment })} />
    <label htmlFor={version}>{t("editor.cli_version")}</label>
    <input id={version} value={String(agent.cli_version ?? "")} spellCheck={false} aria-invalid={!!issues[`${prefix}.cli_version`]}
      aria-describedby={issues[`${prefix}.cli_version`] ? `${version}-hint` : undefined}
      onChange={event => onChange(event.target.value ? { ...agent, cli_version: event.target.value } : without(agent, "cli_version"))} />
    {issues[`${prefix}.cli_version`] && <p id={`${version}-hint`} className="field-error">{t(issues[`${prefix}.cli_version`])}</p>}
    <ToolCapabilities scope="configuration" prefix={prefix} issues={issues} value={agent} roles={[role]} onChange={onChange} />
  </>;
}

/** A new named entry: the name is checked before anything is added; nothing else changes. */
function NewEntry({ id, label, names, pattern, ready = true, onAdd, children }: {
  id: string; label: MessageKey; names: string[]; pattern: RegExp; ready?: boolean; onAdd: (name: string) => void; children?: ReactNode;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<MessageKey>();
  function add() {
    const issue = nameIssue(name, names, pattern);
    setProblem(issue);
    if (!issue && ready) { onAdd(name); setName(""); }
  }
  return <div className="form-row key-value-add">
    <div><label htmlFor={id}>{t(label)}</label>
      <input id={id} value={name} spellCheck={false} aria-invalid={!!problem} aria-describedby={problem ? `${id}-error` : undefined}
        onChange={event => { setName(event.target.value); setProblem(undefined); }}
        onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); add(); } }} /></div>
    {children}
    <button type="button" className="button-quiet" disabled={!ready} aria-label={`${t("editor.add_entry")} · ${t(label)}`} onClick={add}>{t("editor.add_entry")}</button>
    {problem && <p id={`${id}-error`} className="field-error">{t(problem)}</p>}
  </div>;
}

const within = (issues: Issues, prefix: string) => Object.keys(issues).some(key => key === prefix || key.startsWith(`${prefix}.`));

/** Global reusable profiles, compositions and agent presets; projects with their own profile keep their copy. */
function GlobalCatalog({ form, issues, update }: { form: Obj; issues: Issues; update: (path: string, value: unknown) => void }) {
  const { t } = useI18n();
  const profiles: Obj = isObject(form.profiles) ? form.profiles : {};
  const compositions: Obj = isObject(form.compositions) ? form.compositions : {};
  const presets: Obj = isObject(form.agent_presets) ? form.agent_presets : {};
  const [profileChoice, setProfileChoice] = useState("");
  const [providerChoice, setProviderChoice] = useState("");
  const users = (name: string) => Object.entries(compositions).filter(([, item]) => isObject(item) && item.profile === name).map(([key]) => key);
  const profileNames = [...new Set([...Object.keys(profiles), ...Object.values(compositions).map(item => isObject(item) ? String(item.profile ?? "") : "")])].filter(Boolean);
  const set = (table: string, current: Obj, name: string, value: Obj | undefined) =>
    update(table, value === undefined ? without(current, name) : { ...current, [name]: value });
  return <>
    <fieldset id={idFor("profiles")}><legend>{t("editor.profiles")}</legend>
      <p className="hint">{t("editor.profiles_hint")}</p>
      {Object.entries(profiles).map(([name, profile]) => <details key={name} className="catalog-entry" open={within(issues, `profiles.${name}`) || undefined}>
        <summary>{name}</summary>
        {isObject(profile) ? <ProfileFields scope="configuration" prefix={`profiles.${name}`} issues={issues} value={profile}
          onChange={next => set("profiles", profiles, name, next)} /> : <p className="field-error">{t("editor.profile_invalid")}</p>}
        {users(name).length > 0 && <p className="hint">{t("editor.profile_in_use", { names: users(name).join(", ") })}</p>}
        <button type="button" className="button-quiet" disabled={users(name).length > 0}
          onClick={() => set("profiles", profiles, name, undefined)}>{t("editor.remove_named", { name })}</button>
      </details>)}
      <NewEntry id="configuration-new-profile" label="editor.new_profile" names={profileNames} pattern={COMMAND_NAME}
        onAdd={name => set("profiles", profiles, name, emptyProfile())} />
    </fieldset>
    <fieldset id={idFor("compositions")}><legend>{t("editor.compositions")}</legend>
      <p className="hint">{t("editor.compositions_hint")}</p>
      {Object.entries(compositions).map(([name, composition]) => {
        const prefix = `compositions.${name}`;
        const value: Obj = isObject(composition) ? composition : {};
        const choice = idFor(`${prefix}.profile`);
        return <details key={name} className="catalog-entry" open={within(issues, prefix) || undefined}>
          <summary>{name} · {String(value.profile ?? "")}</summary>
          {value.recipe ? <p className="hint">{t("editor.recipe_fixed", { recipe: String(value.recipe) })}</p> : <>
            <label htmlFor={choice}>{t("editor.composition_profile")}</label>
            <select id={choice} value={String(value.profile ?? "")} aria-invalid={!!issues[`${prefix}.profile`]}
              onChange={event => set("compositions", compositions, name, { ...value, profile: event.target.value })}>
              {[...new Set([String(value.profile ?? ""), ...Object.keys(profiles)])].map(option =>
                <option key={option} value={option}>{option || t("editor.choose_profile")}</option>)}
            </select>
            {!(String(value.profile) in profiles) && <p className="hint">{t("editor.builtin_profile")}</p>}
          </>}
          <CommandsFields scope="configuration" prefix={prefix} issues={issues} readOnly={!!value.recipe} value={value}
            profile={profiles[String(value.profile)]} onChange={next => set("compositions", compositions, name, next)} />
          <button type="button" className="button-quiet" onClick={() => set("compositions", compositions, name, undefined)}>
            {t("editor.remove_named", { name })}</button>
        </details>;
      })}
      <NewEntry id="configuration-new-composition" label="editor.new_composition" names={Object.keys(compositions)} pattern={ENTRY_NAME}
        ready={!!profileChoice} onAdd={name => set("compositions", compositions, name, { profile: profileChoice, ...emptyCommands() })}>
        <div><label htmlFor="configuration-new-composition-profile">{t("editor.composition_profile")}</label>
          <select id="configuration-new-composition-profile" value={profileChoice} onChange={event => setProfileChoice(event.target.value)}>
            <option value="">{t("editor.choose_profile")}</option>
            {profileNames.map(option => <option key={option} value={option}>{option}</option>)}
          </select></div>
      </NewEntry>
    </fieldset>
    <fieldset id={idFor("agent_presets")}><legend>{t("editor.presets")}</legend>
      <p className="hint">{t("editor.presets_hint")}</p>
      {Object.entries(presets).map(([name, preset]) => {
        const prefix = `agent_presets.${name}`;
        const value: Obj = isObject(preset) ? preset : {};
        const roles = texts(value.roles);
        const vocabulary = [...new Set([...(efforts[String(value.provider)] ?? []), ...texts(value.efforts)])];
        const change = (next: Obj) => set("agent_presets", presets, name, next);
        return <details key={name} className="catalog-entry" open={within(issues, prefix) || undefined}>
          <summary>{name} · {String(value.provider ?? "")} · {roles.join(", ")}</summary>
          <fieldset id={idFor(`${prefix}.roles`)} tabIndex={-1}><legend>{t("editor.roles")}</legend>
            {(["reviewer", "executor"] as const).map(role => <label key={role} className="check"><input type="checkbox" checked={roles.includes(role)}
              onChange={event => change({ ...value, roles: event.target.checked ? [...roles, role] : roles.filter(item => item !== role) })} />
              {t(role === "reviewer" ? "settings.reviewer" : "settings.executor")}</label>)}
            {issues[`${prefix}.roles`] && <p className="field-error">{t(issues[`${prefix}.roles`])}</p>}
          </fieldset>
          <AgentFields scope="configuration" prefix={prefix} issues={issues} value={value} roles={roles} onChange={change} />
          <LinesField scope="configuration" prefix={`${prefix}.models`} issues={issues} label={t("editor.preset_models")}
            hint="editor.preset_models_hint" value={value.models} onChange={models => change({ ...value, models })} />
          <fieldset id={idFor(`${prefix}.efforts`)} tabIndex={-1} className="effort-list"><legend>{t("settings.efforts")}</legend>
            {vocabulary.map(effort => <label key={effort} className="check"><input type="checkbox" checked={texts(value.efforts).includes(effort)}
              onChange={event => change({ ...value, efforts: event.target.checked ? [...texts(value.efforts), effort] : texts(value.efforts).filter(item => item !== effort) })} />{effort}</label>)}
            {issues[`${prefix}.efforts`] && <p className="field-error">{t(issues[`${prefix}.efforts`])}</p>}
          </fieldset>
          <label className="check"><input type="checkbox" checked={value.allow_open_executor === true}
            onChange={event => change({ ...value, allow_open_executor: event.target.checked })} />{t("editor.allow_open")}</label>
          <button type="button" className="button-quiet" onClick={() => set("agent_presets", presets, name, undefined)}>{t("editor.remove_named", { name })}</button>
        </details>;
      })}
      <NewEntry id="configuration-new-preset" label="editor.new_preset" names={Object.keys(presets)} pattern={ENTRY_NAME}
        ready={!!providerChoice} onAdd={name => set("agent_presets", presets, name, { provider: providerChoice, roles: [], models: [], efforts: [],
          allow_open_executor: false, environment: { USER: "" } })}>
        <div><label htmlFor="configuration-new-preset-provider">{t("settings.provider")}</label>
          <select id="configuration-new-preset-provider" value={providerChoice} onChange={event => setProviderChoice(event.target.value)}>
            <option value="">{t("configuration.choose")}</option><option value="codex">Codex</option><option value="claude">Claude</option>
          </select></div>
      </NewEntry>
    </fieldset>
  </>;
}

export function ConfigurationPage() {
  const { t } = useI18n();
  const [revision, refresh] = useState(0);
  const read = usePoll<S["ConfigurationRead"]>(ROOT, 5000, revision);
  const state = read.data;
  const [draft, setDraft] = useState<Draft | undefined>(readDraft);
  const [action, setAction] = useState<Action | undefined>(readAction);
  const [importReview, setImportReview] = useState<S["ConfigurationPreviewRead"]>();
  const [review, setReview] = useState<Review>();
  const [activation, setActivation] = useState<{ body: S["ConfigurationActivation"]; preview: S["ConfigurationPreviewRead"] }>();
  const [recovery, setRecovery] = useState<S["ConfigurationRecoveryRead"]>();
  const [assistanceRecovery, setAssistanceRecovery] = useState<S["ConfigurationOperationRead"]>();
  const [check, setCheck] = useState<S["ConfigurationClientsRead"]>();
  const [issues, setIssues] = useState<Record<string, MessageKey>>({});
  const [error, setError] = useState<string>();
  const [refusals, setRefusals] = useState<LiveRefusal[]>();
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [confirmed, setConfirmed] = useState(false);
  const [activateConfirmed, setActivateConfirmed] = useState(false);
  const [cancelConfirmed, setCancelConfirmed] = useState(false);
  const [cancelReference, setCancelReference] = useState<{ id: string | null; version: number }>();
  const [discardConfirmed, setDiscardConfirmed] = useState(false);
  const [writersStopped, setWritersStopped] = useState(false);
  const [path, setPath] = useState("/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin");
  const [detection, setDetection] = useState<S["ConfigurationDetectionRead"]>();

  // A fresh GET never overwrites a local candidate or advances its CAS base.
  useEffect(() => { if (state && !draft) setDraft(initialDraft(state)); }, [state, draft]);
  useEffect(() => {
    if (!draft) return;
    try { storeDraft(draft); } catch { setError(t("configuration.storage_failed")); }
  }, [draft, t]);

  function edit(next: Draft) {
    setDraft(next); setReview(undefined); setActivation(undefined); setCheck(undefined);
    setConfirmed(false); setActivateConfirmed(false); setCancelConfirmed(false); setDiscardConfirmed(false); setIssues({}); setError(undefined);
    setRefusals(undefined);
  }
  async function run(work: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError(undefined); setRefusals(undefined);
    try { await work(); }
    catch (error) {
      const live = error instanceof ManagedError && error.status === 409 && error.code === "live_configuration_refused";
      // D263: a billing refusal names its settings (and the projects whose derived selection it would break).
      const billing = error instanceof ManagedError && error.status === 409 && error.code === "billing_configuration_refused";
      setRefusals(live || billing ? (error.details ?? []) as LiveRefusal[] : undefined);
      setError(live ? t("configuration.live.refused") : billing ? t("billing.refused") : error instanceof ManagedError && error.status === 409
        ? `${t("configuration.conflict")} (${error.code ?? "conflict"})` : message(error));
      setReview(undefined); setActivation(undefined); setConfirmed(false); setActivateConfirmed(false);
      refresh(n => n + 1);
    } finally { setAction(readAction()); working.current = false; setBusy(false); }
  }
  async function submit(path: string, body: unknown, previous?: Action) {
    await sendAction(previous ?? { path, body, key: crypto.randomUUID() });
    setReview(undefined); setActivation(undefined); setRecovery(undefined); setConfirmed(false);
    setActivateConfirmed(false); setCancelConfirmed(false); setWritersStopped(false);
    const latest = await managed<S["ConfigurationRead"]>(ROOT);
    setDraft(current => path.endsWith("/import/save") ? initialDraft(latest) : current ? { ...current, base: latest } : initialDraft(latest));
    setImportReview(undefined);
    refresh(n => n + 1);
  }
  function valid() {
    if (!draft) return false;
    const found = errors(draft); setIssues(found);
    const first = Object.keys(found)[0];
    if (first) { document.getElementById?.(idFor(first))?.focus(); return false; }
    return true;
  }

  if (!state) return <><PageHeader title={t("configuration.title")} />{read.error ? <Alert>{read.error}</Alert> : <Loading />}</>;
  if (!draft) return <Loading />;
  const blocked = state.legacy && !state.saved || state.mode === "READ_ONLY_ARCHIVE";
  const stale = baseChanged(draft.base, state);
  const frozen = busy || !!action || blocked;
  const saved = state.saved;
  const activationStale = activation?.body.references[0]?.expected_version !== state.version;
  const cancelStale = cancelReference?.id !== state.pending_activation_id || cancelReference?.version !== state.version;
  const live = state.live_activation;
  return <div className="configuration-editor">
    <PageHeader title={t("configuration.title")}><p>{t("configuration.lede")}</p></PageHeader>
    <Stale error={read.error} />
    <section className="panel" aria-labelledby="configuration-status">
      <h2 id="configuration-status">{t("configuration.status")}</h2>
      <p role="status">{t(modeLabels[state.mode])}</p>
      {state.mode === "RESTART_REQUIRED" && <p>{t("configuration.restart_hint")}</p>}
      {live?.state === "APPLY_PENDING" && <div className="state state-attention">
        <p><strong>{t("configuration.live.when_idle")}</strong> {t("configuration.live.pending_hint")}</p>
        <Waiting reasons={live.waiting ?? []} />
      </div>}
      {live?.state === "FAILED" && <div role="alert" className="state state-error">
        <p>{t("configuration.live.failed", { id: live.activation_id })} ({live.code})</p>
        <Refusals items={live.details ?? []} />
      </div>}
      {state.mode === "INVALID" && <p>{t("configuration.invalid_hint")}</p>}
      <Fields items={(["active", "saved", "pending"] as const).map(key => [t(`configuration.ref.${key}`), state[key]
        ? <span>{t("configuration.revision", { revision: state[key]!.revision })} · <code className="configuration-hash">{state[key]!.sha256}</code> · {t(state[key]!.status === "DRAFT" ? "configuration.draft" : "configuration.validated")}</span>
        : t("common.not_recorded")])} />
      {(blocked || state.legacy) && <p role="status">{t(state.legacy ? "configuration.legacy" : "configuration.archive")}</p>}
    </section>
    {state.legacy && !state.saved && state.legacy_source && <section className="panel">
      <h2>{t("configuration.import")}</h2><p className="path">{state.legacy_source}</p>
      <label>{t("docs.review.reason")}<input value={draft.reason} disabled={busy} onChange={e => {
        edit({ ...draft, reason: e.target.value }); setImportReview(undefined);
      }} /></label>
      <button disabled={busy || !!action || !draft.reason.trim()} onClick={() => void run(async () => {
        setImportReview(await managed<S["ConfigurationPreviewRead"]>(`${ROOT}/import/preview`, {
          source: state.legacy_source, reason: draft.reason })); setConfirmed(false);
      })}>{t("configuration.import_review")}</button>
      {importReview && <><Evidence title={t("configuration.exact_request")} value={importReview} />
        {importReview.changes?.map((item, index) => <DiffBlock key={index} diff={String(item.diff ?? "")} label={String(item.scope)} />)}
        <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("profile.confirm_exact")}</label>
        <button disabled={busy || !!action || !confirmed} onClick={() => void run(() => submit(`${ROOT}/import/save`, {
          source: state.legacy_source, reason: draft.reason, preview_sha256: importReview.sha256,
        }))}>{t("configuration.import")}</button></>}
    </section>}
    {!!state.imported_projects?.length && <section className="panel"><p>{t("configuration.import_prepare")}</p>
      {state.imported_projects.map(project => <p key={project}><Link to={{ name: "project", project }}>{project}</Link></p>)}
    </section>}
    {error && <Alert>{error}{refusals && <Refusals items={refusals} />}</Alert>}
    {action && <section className="panel"><h2>{t("configuration.unacknowledged")}</h2>
      <p>{t("configuration.retry_hint")}</p><Evidence title={t("configuration.exact_request")} value={action} />
      <button type="button" disabled={busy || state.mode === "READ_ONLY_ARCHIVE"} onClick={() => void run(() => submit(action.path, action.body, action))}>{t("configuration.retry")}</button>
    </section>}
    {!blocked && <>
      {state.mode === "READY" && state.active && <ConfigurationAssistance scope="global" state={draft.base} candidate={candidate(draft)}
        disabled={frozen} run={run} apply={text => edit({ ...draft, source: "text", text })} />}
      <section className="panel"><h2>{t("configuration.detect")}</h2><p>{t("configuration.detect_hint")}</p>
        <label htmlFor="configuration-detect-path">{t("configuration.path")}</label>
        <input id="configuration-detect-path" value={path} disabled={frozen} onChange={event => { setPath(event.target.value); setDetection(undefined); }} />
        <button type="button" disabled={frozen} onClick={() => void run(async () => {
          setDetection(await managed<S["ConfigurationDetectionRead"]>(`${ROOT}/detect`, { path }));
        })}>{t("configuration.detect")}</button>
        {detection && <><Fields items={Object.entries(detection.candidates).map(([name, value]) => [name, value ?? t("configuration.not_found")])} />
          <p className="path">{detection.state_dir}</p><button type="button" disabled={frozen || draft.source !== "form"} onClick={() => {
            let form = draft.form;
            for (const role of ["reviewer", "executor"]) {
              const provider = String(field(form, `agents.${role}.provider`));
              const executable = detection.candidates[provider];
              const previous = field(form, `agents.${role}.executable`);
              if (executable) form = changeField(form, `agents.${role}.executable`, [executable, ...(Array.isArray(previous) ? previous.slice(1) : [])]);
              form = changeField(form, `agents.${role}.environment.USER`, detection.user);
              form = changeField(form, `agents.${role}.environment.PATH`, path);
            }
            if (detection.candidates.git) form = changeField(form, "git.executable", detection.candidates.git);
            form = changeField(form, "service.state_dir", detection.state_dir);
            edit({ ...draft, form });
          }}>{t("configuration.use_suggestions")}</button></>}
      </section>
      <section className="panel"><h2>{t("configuration.candidate")}</h2>
        <p className="hint">{t("configuration.no_secrets")}</p>
        {stale && <p role="alert" className="state state-stale">{t("configuration.stale")}</p>}
        <div className="actions">
          <button type="button" disabled={frozen} onClick={() => edit({ ...draft, base: state })}>{t("configuration.rebase")}</button>
          <label className="check"><input type="checkbox" checked={discardConfirmed} disabled={frozen} onChange={event => setDiscardConfirmed(event.target.checked)} />{t("configuration.replace_local")}</label>
          <button type="button" disabled={frozen || !discardConfirmed} onClick={() => edit(initialDraft(state))}>{t("configuration.load_saved")}</button>
        </div>
        <form onSubmit={event => { event.preventDefault(); if (!valid()) return; void run(async () => {
          const body = change(draft);
          setReview({ body, preview: await managed<S["ConfigurationPreviewRead"]>(`${ROOT}/preview`, body) }); setConfirmed(false);
        }); }}>
          <fieldset disabled={frozen}>
            <legend>{t("configuration.candidate")}</legend>
            <div className="actions"><button type="button" aria-pressed={draft.source === "form"} disabled={draft.source === "form"}
              onClick={() => void run(async () => { const parsed = await managed<S["ConfigurationFormRead"]>(`${ROOT}/form`, { text: draft.text, validated: false });
                edit({ ...draft, source: "form", form: parsed.form }); })}>{t("configuration.form")}</button>
              <button type="button" aria-pressed={draft.source === "text"} disabled={draft.source === "text"}
                onClick={() => void run(async () => { const parsed = await managed<S["ConfigurationFormRead"]>(`${ROOT}/form`, { form: draft.form, validated: false });
                  edit({ ...draft, source: "text", text: parsed.text }); })}>{t("configuration.toml")}</button></div>
            {draft.source === "form" ? <ConfigurationFields draft={draft} onChange={edit} issues={issues} /> : <>
              <label htmlFor="configuration-text">{t("configuration.toml")}</label>
              <textarea id="configuration-text" rows={24} spellCheck={false} value={draft.text} aria-invalid={!!issues.text}
                aria-describedby={issues.text ? "configuration-text-error" : undefined}
                onChange={event => edit({ ...draft, text: event.target.value })} />
              {issues.text && <p id="configuration-text-error" className="field-error">{t(issues.text)}</p>}
            </>}
            <label htmlFor="configuration-reason">{t("configuration.reason")}</label>
            <input id="configuration-reason" maxLength={1000} value={draft.reason} aria-invalid={!!issues.reason}
              aria-describedby={issues.reason ? "configuration-reason-error" : undefined} onChange={event => edit({ ...draft, reason: event.target.value })} />
            {issues.reason && <p id="configuration-reason-error" className="field-error">{t(issues.reason)}</p>}
            <label className="check"><input type="checkbox" checked={draft.validated} onChange={event => edit({ ...draft, validated: event.target.checked })} />{t("configuration.validate")}</label>
            <p className="hint">{t("configuration.draft_hint")}</p>
            {state.status === "EXTERNAL_CHANGE" && <label className="check"><input type="checkbox" checked={draft.importExternal}
              onChange={event => edit({ ...draft, importExternal: event.target.checked })} />{t("configuration.import_external")}</label>}
            <div className="actions"><button type="submit">{t("configuration.preview")}</button>
              <button type="button" onClick={() => { if (valid()) void run(async () => {
                setCheck(await managed<S["ConfigurationClientsRead"]>(`${ROOT}/check-clients`, { ...candidate(draft), validated: true }));
              }); }}>{t("configuration.check_clients")}</button></div>
          </fieldset>
        </form>
        {check && <><p role="status">{t("configuration.check_hint")}</p><Evidence title={t("configuration.client_reports")} value={check.reports} /></>}
        {review && <section className="decision" aria-labelledby="configuration-save-review">
          <h3 id="configuration-save-review">{t("configuration.save_review")}</h3>
          <p>{t("configuration.save_hint")}</p><code className="configuration-hash">{review.preview.sha256}</code>
          {review.preview.changes?.map((item, index) => <div key={index}><DiffBlock diff={String(item.diff)} label={t("configuration.diff")} />
            {Array.isArray(item.removed_fields) && item.removed_fields.length > 0 && <p className="state state-attention">
              {t("configuration.removed_fields", { fields: item.removed_fields.join(", ") })}</p>}
            <details><summary>{t("configuration.toml")}</summary><pre>{String(item.text)}</pre></details></div>)}
          <p>{t("configuration.impact")}</p><SaveImpact preview={review.preview} />
          <Evidence title={t("configuration.activation_review")} value={review.preview} />
          <label className="check"><input type="checkbox" checked={confirmed} disabled={frozen || stale} onChange={event => setConfirmed(event.target.checked)} />{t("configuration.confirm_save")}</label>
          <button type="button" disabled={frozen || stale || !confirmed} onClick={() => void run(() => submit(`${ROOT}/save`, { ...review.body, preview_sha256: review.preview.sha256 }))}>{t("configuration.save")}</button>
        </section>}
      </section>
      <ReferenceList editable disabled={frozen} />
      <section className="panel"><h2>{t("configuration.activation")}</h2><p>{t("configuration.activation_hint")}</p>
        <p className="hint">{t("configuration.activation_scope")}</p>
        <button type="button" disabled={frozen || !saved || saved.status !== "VALIDATED" || !!state.pending || state.status === "RECOVERY_REQUIRED" || state.status === "INVALID" || !draft.reason.trim()}
          onClick={() => void run(async () => {
            const body: S["ConfigurationActivation"] = { references: state.activation_references?.length ? state.activation_references : [{ scope: "global", revision: saved!.revision, sha256: saved!.sha256, expected_version: state.version }], reason: draft.reason };
            setActivation({ body, preview: await managed<S["ConfigurationPreviewRead"]>(`${ROOT}/activation/preview`, body) }); setActivateConfirmed(false);
          })}>{t("configuration.activation_preview")}</button>
        {activation && <div className="decision"><code className="configuration-hash">{activation.preview.sha256}</code>
          {activation.preview.apply === "restart"
            ? <p className="state state-attention">{t("configuration.live.restart", { fields: (activation.preview.restart_fields ?? []).join(", ") })}</p>
            : <><p>{t(activation.preview.waiting?.length ? "configuration.live.will_wait" : "configuration.live.now")}</p>
              <Waiting reasons={activation.preview.waiting ?? []} /></>}
          <Evidence title={t("configuration.activation_review")} value={activation.preview} />
          <label className="check"><input type="checkbox" checked={activateConfirmed} disabled={frozen || activationStale}
            onChange={event => setActivateConfirmed(event.target.checked)} />{t("configuration.confirm_activation")}</label>
          <button type="button" disabled={frozen || activationStale || !activateConfirmed}
            onClick={() => void run(() => submit(`${ROOT}/activate`, { ...activation.body, preview_sha256: activation.preview.sha256 }))}>{t("configuration.activate")}</button></div>}
        {state.pending_activation_id && <div className="decision">
          <p>{t("configuration.cancel_hint")}</p><code>{state.pending_activation_id}</code>
          <label className="check"><input type="checkbox" checked={cancelConfirmed && !cancelStale} disabled={frozen} onChange={event => {
            setCancelConfirmed(event.target.checked); setCancelReference({ id: state.pending_activation_id, version: state.version });
          }} />{t("configuration.confirm_cancel")}</label>
          <button type="button" disabled={frozen || !cancelConfirmed || cancelStale || !draft.reason.trim()} onClick={() => void run(() => submit(`${ROOT}/cancel`, {
            activation_id: cancelReference!.id, expected_version: cancelReference!.version, reason: draft.reason,
            expected_versions: state.pending_versions ?? Object.fromEntries((state.activation_references ?? []).map(ref => [ref.scope, ref.expected_version])),
          }))}>{t("configuration.cancel")}</button>
        </div>}
      </section>
      {!!state.recovery_operations.length && <section className="panel"><h2>{t("configuration.recovery")}</h2><p>{t("configuration.recovery_hint")}</p>
        {state.recovery_operations.map(id => <button type="button" key={id} disabled={frozen} onClick={() => void run(async () => {
          const operation = await managed<S["ConfigurationOperationRead"]>(`${ROOT}/operations/${encodeURIComponent(id)}`);
          if (operation.kind === "ASSIST") { setAssistanceRecovery(operation); setRecovery(undefined); setWritersStopped(false); return; }
          setAssistanceRecovery(undefined);
          setRecovery(await managed<S["ConfigurationRecoveryRead"]>(`${ROOT}/operations/${encodeURIComponent(id)}/recovery/preview`, {})); setWritersStopped(false);
        })}>{t("configuration.recovery_preview")} · {id}</button>)}
        {assistanceRecovery && <div className="decision"><Evidence title={t("assistance.result")} value={assistanceRecovery} />
          <label className="check"><input type="checkbox" checked={writersStopped} disabled={frozen} onChange={e => setWritersStopped(e.target.checked)} />{t("configuration.writers_stopped")}</label>
          <button disabled={frozen || !writersStopped} onClick={() => void run(async () => {
            await managed(`${ROOT}/assistance/${assistanceRecovery.id}/recover`, { writers_stopped: true });
            setAssistanceRecovery(undefined); refresh(n => n + 1);
          })}>{t("configuration.recover")}</button>
        </div>}
        {recovery && <div className="decision"><Evidence title={t("configuration.recovery_review")} value={recovery} />
          <label className="check"><input type="checkbox" checked={writersStopped} disabled={frozen} onChange={event => setWritersStopped(event.target.checked)} />{t("configuration.writers_stopped")}</label>
          <button type="button" disabled={frozen || !writersStopped} onClick={() => void run(() => submit(`${ROOT}/operations/${encodeURIComponent(recovery.operation_id)}/recovery/confirm`, {
            preview_sha256: recovery.sha256, writers_stopped: true,
          }))}>{t("configuration.recover")}</button></div>}
      </section>}
    </>}
  </div>;
}
