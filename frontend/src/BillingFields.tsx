import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { useI18n } from "./Language";
import type { MessageKey } from "./i18n.ts";
import { managed } from "./managed-api";
import type { S } from "./managed-api";
import { Alert, Evidence, Fields, Hash, Loading, Pagination, Stale, message, usePoll, when } from "./ui";
import { BASES as BASIS_LABELS } from "./accounting.ts";
import { BASES, BILLING_GLOBAL, BILLING_PROJECT, CONDITION, EFFECTIVE, PROFILE_NAME, PROVIDERS, ROLES, billingGlobal,
  billingProject, converted, defaultUsers, defaultsOf, fromScheme, missingConditions, profilesOf, resolution,
  schemeOf } from "./billing.ts";
import type { Bundle } from "./billing.ts";
import { domId, isObject, nameIssue, without } from "./profile-form.ts";
import type { Issues, Obj } from "./profile-form.ts";

const PAGE = 10;
const ROLE: Record<string, MessageKey> = { reviewer: "settings.reviewer", executor: "settings.executor" };
const basisLabel = (basis: string, t: (key: MessageKey) => string) => BASIS_LABELS[basis] ? t(BASIS_LABELS[basis]) : basis;

/** Bundles a profile may pin: the first page is enough for the form (packaged first, then the newest imports). */
function useBundles(enabled = true) {
  const read = usePoll<S["Page_ReferenceBundleRead_"]>(enabled ? "/configuration/references?limit=50" : null, 0);
  return { bundles: read.data?.items ?? [], error: read.error };
}

function Problem({ id, issue }: { id: string; issue?: MessageKey }) {
  const { t } = useI18n();
  return issue ? <p id={`${id}-error`} className="field-error">{t(issue)}</p> : null;
}

function TextField({ scope, path, label, value, issues, onChange, list }: {
  scope: string; path: string; label: MessageKey; value: unknown; issues: Issues; onChange: (value: string) => void; list?: string;
}) {
  const { t } = useI18n();
  const id = domId(scope, path);
  return <div><label htmlFor={id}>{t(label)}</label>
    <input id={id} value={String(value ?? "")} spellCheck={false} list={list} aria-invalid={!!issues[path]}
      aria-describedby={issues[path] ? `${id}-error` : undefined} onChange={event => onChange(event.target.value)} />
    <Problem id={id} issue={issues[path]} /></div>;
}

function bundleLabel(bundle: Bundle, t: (key: MessageKey, params?: Record<string, string | number>) => string) {
  return `${bundle.id.slice(0, 12)} · ${t(bundle.source === "packaged" ? "accounting.references.packaged" : "accounting.references.imported")}`
    + (bundle.observed_to ? ` · ${bundle.observed_to.slice(0, 10)}` : "");
}

// --- global profiles and defaults ---------------------------------------------------------------

/** D263: billing profiles and per-role defaults of `local-config-10`; before conversion only the explanation. */
export function GlobalBilling({ scope, form, issues, onChange }: { scope: string; form: Obj; issues: Issues; onChange: (form: Obj) => void }) {
  const { t } = useI18n();
  const { bundles, error } = useBundles(billingGlobal(form));
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("");
  const [problem, setProblem] = useState<MessageKey>();
  const profiles = profilesOf(form);
  const defaults = defaultsOf(form);
  const billing: Obj = isObject(form.billing) ? form.billing : {};
  const set = (next: Obj) => onChange({ ...form, billing: next });
  const setProfile = (key: string, value: Obj | undefined) =>
    set({ ...billing, profiles: value === undefined ? without(profiles, key) : { ...profiles, [key]: value } });
  const id = domId(scope, "billing");
  if (!billingGlobal(form)) return <fieldset id={id} tabIndex={-1}><legend>{t("billing.title")}</legend>
    <p className="hint">{t("billing.hint")}</p>
    <p>{t("billing.convert_hint", { format: BILLING_GLOBAL, current: String(form.format ?? "local-config-9") })}</p>
    <Problem id={id} issue={issues.billing} />
    <button type="button" onClick={() => onChange(converted(form, BILLING_GLOBAL))}>{t("billing.convert", { format: BILLING_GLOBAL })}</button>
  </fieldset>;
  function add() {
    const issue = nameIssue(name, Object.keys(profiles), PROFILE_NAME) ?? (provider ? undefined : "billing.provider_required");
    setProblem(issue);
    if (issue) return;
    setProfile(name, { provider, platform: "", product: "", scheme: "", unit: "", basis: "", references: "" });
    setName("");
  }
  return <fieldset id={id} tabIndex={-1}><legend>{t("billing.title")}</legend>
    <p className="hint">{t("billing.hint")}</p>
    <p className="hint">{t("billing.converted", { format: BILLING_GLOBAL })}</p>
    <Stale error={error} />
    {Object.entries(profiles).map(([key, profile]) => {
      const users = defaultUsers(form, key);
      const prefix = `billing.profiles.${key}`;
      return <details key={key} className="catalog-entry" open={Object.keys(issues).some(issue => issue.startsWith(`${prefix}.`) || issue === prefix) || undefined}>
        <summary>{key} · {String(isObject(profile) ? profile.provider ?? "" : "")} · {isObject(profile) ? basisLabel(String(profile.basis ?? ""), t) : ""}</summary>
        {isObject(profile) ? <ProfileEditor scope={scope} prefix={prefix} profile={profile} bundles={bundles} issues={issues}
          onChange={next => setProfile(key, next)} /> : <p className="field-error">{t("billing.profile_invalid")}</p>}
        {users.length > 0 && <p className="hint">{t("billing.profile_in_use", { roles: users.map(role => t(ROLE[role])).join(", ") })}</p>}
        <button type="button" className="button-quiet" disabled={users.length > 0} onClick={() => setProfile(key, undefined)}>
          {t("editor.remove_named", { name: key })}</button>
      </details>;
    })}
    <Problem id={domId(scope, "billing.profiles")} issue={issues["billing.profiles"]} />
    <div className="form-row key-value-add">
      <div><label htmlFor={`${id}-new`}>{t("billing.new_profile")}</label>
        <input id={`${id}-new`} value={name} spellCheck={false} aria-invalid={!!problem} aria-describedby={problem ? `${id}-new-error` : `${id}-new-hint`}
          onChange={event => { setName(event.target.value); setProblem(undefined); }}
          onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); add(); } }} /></div>
      <div><label htmlFor={`${id}-new-provider`}>{t("settings.provider")}</label>
        <select id={`${id}-new-provider`} value={provider} onChange={event => { setProvider(event.target.value); setProblem(undefined); }}>
          <option value="">{t("configuration.choose")}</option>{PROVIDERS.map(item => <option key={item} value={item}>{item}</option>)}
        </select></div>
      <button type="button" className="button-quiet" aria-label={`${t("editor.add_entry")} · ${t("billing.new_profile")}`} onClick={add}>{t("editor.add_entry")}</button>
      {problem ? <p id={`${id}-new-error`} className="field-error">{t(problem)}</p> : <p id={`${id}-new-hint`} className="hint">{t("billing.name_hint")}</p>}
    </div>
    <h4>{t("billing.defaults")}</h4>
    <p className="hint">{t("billing.defaults_hint")}</p>
    <div className="form-row">{ROLES.map(role => {
      const path = `billing.defaults.${role}`;
      const field = domId(scope, path);
      const agent = String(form.agents?.[role]?.provider ?? "");
      const current = typeof defaults[role] === "string" ? defaults[role] as string : "";
      const options = Object.entries(profiles).filter(([, item]) => isObject(item) && item.provider === agent).map(([key]) => key);
      return <div key={role}><label htmlFor={field}>{t(ROLE[role])} · {agent || t("common.not_recorded")}</label>
        <select id={field} value={current} aria-invalid={!!issues[path]} aria-describedby={issues[path] ? `${field}-error` : undefined}
          onChange={event => set({ ...billing, defaults: event.target.value ? { ...defaults, [role]: event.target.value } : without(defaults, role) })}>
          <option value="">{t("billing.no_default")}</option>
          {[...new Set([...(current ? [current] : []), ...options])].map(option => <option key={option} value={option}>{option}</option>)}
        </select><Problem id={field} issue={issues[path]} /></div>;
    })}</div>
  </fieldset>;
}

/** One profile: identity (optionally filled from a listed scheme), basis, pinned bundle and asserted conditions. */
function ProfileEditor({ scope, prefix, profile, bundles, issues, onChange }: {
  scope: string; prefix: string; profile: Obj; bundles: Bundle[]; issues: Issues; onChange: (profile: Obj) => void;
}) {
  const { t } = useI18n();
  const [condition, setCondition] = useState("");
  const [problem, setProblem] = useState<MessageKey>();
  const schemes = bundles.flatMap(bundle => bundle.schemes.filter(item => !profile.provider || item.provider === profile.provider)
    .map(item => ({ bundle, scheme: item, key: [bundle.id, item.platform, item.product, item.scheme, item.unit].join("|") })));
  const scheme = schemeOf(profile, bundles);
  const missing = missingConditions(profile, scheme);
  const conditions: Obj = isObject(profile.conditions) ? profile.conditions : {};
  const setConditions = (next: Obj) => onChange(Object.keys(next).length ? { ...profile, conditions: next } : without(profile, "conditions"));
  const id = (path: string) => domId(scope, `${prefix}.${path}`);
  const listed = bundles.some(bundle => bundle.id === profile.references);
  function addCondition() {
    const issue = nameIssue(condition, Object.keys(conditions), CONDITION);
    setProblem(issue);
    if (issue) return;
    setConditions({ ...conditions, [condition]: { value: "", source: "" } }); setCondition("");
  }
  return <>
    {schemes.length > 0 && <div><label htmlFor={id("scheme-choice")}>{t("billing.fill_scheme")}</label>
      <select id={id("scheme-choice")} value="" onChange={event => {
        const chosen = schemes.find(item => item.key === event.target.value);
        if (chosen) onChange(fromScheme(profile, chosen.scheme, chosen.bundle.id));
      }}>
        <option value="">{t("billing.choose_scheme")}</option>
        {schemes.map(item => <option key={item.key} value={item.key}>
          {item.scheme.product} · {item.scheme.scheme} · {item.scheme.unit} · {bundleLabel(item.bundle, t)}</option>)}
      </select><p className="hint">{t("billing.fill_scheme_hint")}</p></div>}
    <div className="form-row">
      <div><label htmlFor={id("provider")}>{t("settings.provider")}</label>
        <select id={id("provider")} value={String(profile.provider ?? "")} aria-invalid={!!issues[`${prefix}.provider`]}
          onChange={event => onChange({ ...profile, provider: event.target.value })}>
          {[...new Set([String(profile.provider ?? ""), ...PROVIDERS])].map(item => <option key={item} value={item}>{item || t("configuration.choose")}</option>)}
        </select><Problem id={id("provider")} issue={issues[`${prefix}.provider`]} /></div>
      {(["platform", "product", "scheme", "unit"] as const).map(key => <TextField key={key} scope={scope} path={`${prefix}.${key}`}
        label={`billing.${key}`} value={profile[key]} issues={issues} onChange={value => onChange({ ...profile, [key]: value })} />)}
    </div>
    <div className="form-row">
      <div><label htmlFor={id("basis")}>{t("accounting.basis")}</label>
        <select id={id("basis")} value={String(profile.basis ?? "")} aria-invalid={!!issues[`${prefix}.basis`]}
          aria-describedby={`${id("basis")}-hint`} onChange={event => onChange({ ...profile, basis: event.target.value })}>
          <option value="">{t("billing.choose_basis")}</option>
          {BASES.map(basis => <option key={basis} value={basis} disabled={!!scheme && !scheme.bases.includes(basis)}>{basisLabel(basis, t)}</option>)}
        </select>
        <p id={`${id("basis")}-hint`} className={issues[`${prefix}.basis`] ? "field-error" : "hint"}>
          {t(issues[`${prefix}.basis`] ?? (profile.basis === "subscription_equivalent" ? "billing.counterfactual" : "billing.basis_hint"))}</p></div>
      <div><label htmlFor={id("references")}>{t("billing.references")}</label>
        <select id={id("references")} value={String(profile.references ?? "")} aria-invalid={!!issues[`${prefix}.references`]}
          aria-describedby={issues[`${prefix}.references`] ? `${id("references")}-error` : undefined}
          onChange={event => onChange({ ...profile, references: event.target.value })}>
          <option value="">{t("billing.choose_references")}</option>
          {profile.references && !listed && <option value={String(profile.references)}>{String(profile.references).slice(0, 12)} · {t("billing.not_listed")}</option>}
          {bundles.map(bundle => <option key={bundle.id} value={bundle.id} disabled={!bundle.available}>{bundleLabel(bundle, t)}</option>)}
        </select><Problem id={id("references")} issue={issues[`${prefix}.references`]} /></div>
    </div>
    {profile.references && !listed && <p className="state state-attention">{t("billing.references_unlisted")}</p>}
    {profile.references && listed && !scheme && <p className="state state-attention">{t("billing.scheme_unmatched")}</p>}
    <fieldset id={id("conditions")} tabIndex={-1} className="key-values"><legend>{t("billing.conditions")}</legend>
      <p className="hint">{t("billing.conditions_hint")}</p>
      <Problem id={id("conditions")} issue={issues[`${prefix}.conditions`]} />
      {Object.entries(conditions).map(([key, item]) => {
        const value: Obj = isObject(item) ? item : {};
        const path = `${prefix}.conditions.${key}`;
        const options = scheme?.conditions[key] ?? [];
        return <div key={key} className="form-row condition">
          <p><code>{key}</code></p>
          <TextField scope={scope} path={`${path}.value`} label="billing.condition_value_label" value={value.value} issues={issues}
            list={options.length ? `${id(`conditions.${key}`)}-options` : undefined}
            onChange={text => setConditions({ ...conditions, [key]: { ...value, value: text } })} />
          {options.length > 0 && <datalist id={`${id(`conditions.${key}`)}-options`}>{options.map(option => <option key={option} value={option} />)}</datalist>}
          <TextField scope={scope} path={`${path}.source`} label="billing.condition_source_label" value={value.source} issues={issues}
            onChange={text => setConditions({ ...conditions, [key]: { ...value, source: text } })} />
          <Problem id={domId(scope, path)} issue={issues[path]} />
          <button type="button" className="button-quiet" onClick={() => setConditions(without(conditions, key))}>{t("editor.remove_named", { name: key })}</button>
        </div>;
      })}
      <div className="form-row key-value-add">
        <div><label htmlFor={id("conditions-new")}>{t("billing.new_condition")}</label>
          <input id={id("conditions-new")} value={condition} spellCheck={false} list={missing.length ? `${id("conditions-new")}-options` : undefined}
            aria-invalid={!!problem} aria-describedby={problem ? `${id("conditions-new")}-error` : undefined}
            onChange={event => { setCondition(event.target.value); setProblem(undefined); }}
            onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); addCondition(); } }} />
          {missing.length > 0 && <datalist id={`${id("conditions-new")}-options`}>{missing.map(option => <option key={option} value={option} />)}</datalist>}</div>
        <button type="button" className="button-quiet" aria-label={`${t("editor.add_entry")} · ${t("billing.new_condition")}`} onClick={addCondition}>{t("editor.add_entry")}</button>
        {problem && <p id={`${id("conditions-new")}-error`} className="field-error">{t(problem)}</p>}
      </div>
      {missing.length > 0 && <p className="state state-attention">{t("billing.conditions_missing", { names: missing.join(", ") })}</p>}
    </fieldset>
  </>;
}

// --- project selections ---------------------------------------------------------------------------

/** D263: per-role selections of `project-config-2` among the profiles of the referenced global revision. */
export function ProjectBilling({ scope, form, issues, onChange }: { scope: string; form: Obj; issues: Issues; onChange: (form: Obj) => void }) {
  const { t } = useI18n();
  const revision = Number(form.global?.revision);
  const read = usePoll<S["ConfigurationFormRead"]>(revision > 0 ? `/configuration/revisions/global/${revision}` : null, 0);
  const global: Obj = read.data?.form ?? {};
  const profiles = billingGlobal(global) ? profilesOf(global) : {};
  const defaults = billingGlobal(global) ? defaultsOf(global) : {};
  const selection: Obj = billingProject(form) && isObject(form.billing) ? form.billing : {};
  const id = domId(scope, "billing");
  return <fieldset id={id} tabIndex={-1}><legend>{t("billing.title")}</legend>
    <p className="hint">{t("billing.project_hint", { revision: String(form.global?.revision ?? "—") })}</p>
    <Stale error={read.error} />
    {!read.data && !read.error && revision > 0 ? <Loading /> : !billingGlobal(global) && <p className="hint">{t("billing.global_without")}</p>}
    <Problem id={id} issue={issues.billing} />
    {!billingProject(form) ? <>
      <p>{t("billing.convert_hint", { format: BILLING_PROJECT, current: String(form.format ?? "project-config-1") })}</p>
      <button type="button" onClick={() => onChange(converted(form, BILLING_PROJECT))}>{t("billing.convert", { format: BILLING_PROJECT })}</button>
    </> : <div className="form-row">{ROLES.map(role => {
      const path = `billing.${role}`;
      const field = domId(scope, path);
      const agent = String(form.agents?.[role]?.provider ?? "");
      const current = typeof selection[role] === "string" ? selection[role] as string : "";
      const options = Object.entries(profiles).filter(([, item]) => isObject(item) && item.provider === agent).map(([key]) => key);
      const resolved = resolution(role, selection, defaults, profiles, agent || undefined);
      return <div key={role}><label htmlFor={field}>{t(ROLE[role])} · {agent || t("common.not_recorded")}</label>
        <select id={field} value={current} aria-invalid={!!issues[path]} aria-describedby={`${field}-hint`}
          onChange={event => onChange({ ...form, billing: event.target.value ? { ...selection, [role]: event.target.value } : without(selection, role) })}>
          <option value="">{defaults[role] ? t("billing.inherit_named", { name: String(defaults[role]) }) : t("billing.inherit_none")}</option>
          {[...new Set([...(current ? [current] : []), ...options])].map(option => <option key={option} value={option}>{option}</option>)}
        </select>
        <p id={`${field}-hint`} className={issues[path] ? "field-error" : resolved.known ? "hint" : "state state-attention"}>
          {t(issues[path] ?? (resolved.known ? "billing.resolves" : "billing.resolves_unknown"), { name: resolved.name ?? "" })}</p>
      </div>;
    })}</div>}
  </fieldset>;
}

// --- reference bundles ------------------------------------------------------------------------------

/** Available bundles (D263). Read-only everywhere; `editable` adds the explicit preview → confirm import. */
export function ReferenceList({ editable = false, disabled = false }: { editable?: boolean; disabled?: boolean }) {
  const { t, n } = useI18n();
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const read = usePoll<S["Page_ReferenceBundleRead_"]>(`/configuration/references?offset=${offset}&limit=${PAGE}`, 0, revision);
  return <section className="panel" aria-labelledby="references-title">
    <h2 id="references-title">{t("billing.references_title")}</h2>
    <p className="hint">{t("billing.references_lede")}</p>
    <Stale error={read.data ? read.error : undefined} />
    {!read.data ? read.error ? <Alert>{read.error}</Alert> : <Loading /> : <ul className="reference-bundles">
      {read.data.items.map(bundle => <li key={bundle.id} className="catalog-entry">
        <p><Hash value={bundle.id} /> · {t(bundle.source === "packaged" ? "accounting.references.packaged" : "accounting.references.imported")}
          {!bundle.available && <> · <strong>{t("billing.unavailable")}</strong></>}</p>
        <Fields items={[
          [t("billing.bundle_references"), String(bundle.references)],
          [t("billing.providers"), bundle.providers.join(", ") || t("common.not_recorded")],
          [t("accounting.references.observed"), bundle.observed_from ? bundle.observed_from === bundle.observed_to ? when(bundle.observed_from)
            : <>{when(bundle.observed_from)} – {when(bundle.observed_to ?? bundle.observed_from)}</> : t("common.not_recorded")],
          [t("billing.effective"), t(EFFECTIVE[bundle.effective_period])],
          [t("billing.recorded"), bundle.recorded_at ? when(bundle.recorded_at) : t("billing.not_stored")],
        ]} />
        {bundle.schemes.length > 0 && <details><summary>{n("billing.schemes", bundle.schemes.length)}</summary>
          <ul>{bundle.schemes.map(item => <li key={[item.provider, item.platform, item.product, item.scheme, item.unit].join("|")}>
            <code>{item.provider} · {item.platform} · {item.product} · {item.scheme} · {item.unit}</code>
            {" "}· {item.bases.map(basis => basisLabel(basis, t)).join(", ")} · {n("billing.models", item.models.length)}
            {Object.keys(item.conditions).length > 0 && <> · {t("billing.requires", { names: Object.keys(item.conditions).join(", ") })}</>}
          </li>)}</ul></details>}
      </li>)}</ul>}
    <Pagination offset={offset} next={read.data?.next_offset} onChange={setOffset} size={PAGE} label={t("billing.references_title")} />
    {editable && <ReferenceImport disabled={disabled} onImported={() => { setOffset(0); setRevision(n => n + 1); }} />}
  </section>;
}

function ReferenceImport({ disabled, onImported }: { disabled: boolean; onImported: () => void }) {
  const { t, n } = useI18n();
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<S["ReferenceImportRead"]>();
  const [result, setResult] = useState<S["ReferenceImportRead"]>();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const working = useRef(false);
  const edit = (text: string) => { setContent(text); setPreview(undefined); setConfirmed(false); setResult(undefined); setError(undefined); };
  async function run(work: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError(undefined);
    try { await work(); } catch (e) { setError(message(e)); setPreview(undefined); setConfirmed(false); }
    finally { working.current = false; setBusy(false); }
  }
  const frozen = disabled || busy;
  const facts = (report: S["ReferenceImportRead"]): [string, ReactNode][] => [
    [t("billing.bundle"), <code key="bundle" className="configuration-hash">{report.bundle}</code>],
    [t("billing.bundle_references"), String(report.references)],
    [t("billing.rows"), t("billing.rows_value", { created: report.new_rows, existing: report.existing_rows })],
    [t("billing.conflicts"), report.conflicts.length ? report.conflicts.join(", ") : t("billing.no_conflicts")],
  ];
  return <div className="decision">
    <h3>{t("billing.import")}</h3>
    <p className="hint">{t("billing.import_hint")}</p>
    <label htmlFor="references-file">{t("billing.import_file")}</label>
    <input id="references-file" type="file" accept="application/json,.json" disabled={frozen}
      onChange={event => { const file = event.target.files?.[0]; if (file) void file.text().then(edit).catch(e => setError(message(e))); }} />
    <label htmlFor="references-content">{t("billing.import_content")}</label>
    <textarea id="references-content" rows={6} spellCheck={false} value={content} disabled={frozen} onChange={event => edit(event.target.value)} />
    <div className="actions"><button type="button" disabled={frozen || !content.trim()} onClick={() => void run(async () => {
      setPreview(await managed<S["ReferenceImportRead"]>("/configuration/references/preview", { content })); setConfirmed(false);
    })}>{t("billing.import_preview")}</button></div>
    {error && <Alert>{error}</Alert>}
    {preview && <div>
      <code className="configuration-hash">{preview.sha256}</code>
      <Fields items={facts(preview)} />
      <Evidence title={t("configuration.exact_request")} value={preview} />
      <label className="check"><input type="checkbox" checked={confirmed} disabled={frozen || preview.conflicts.length > 0}
        onChange={event => setConfirmed(event.target.checked)} />{t("billing.import_confirm")}</label>
      <button type="button" disabled={frozen || !confirmed || preview.conflicts.length > 0} onClick={() => void run(async () => {
        setResult(await managed<S["ReferenceImportRead"]>("/configuration/references/import", { content, preview_sha256: preview.sha256 }));
        setPreview(undefined); setConfirmed(false); onImported();
      })}>{t("billing.import_apply")}</button>
    </div>}
    {result && <p role="status" className="state state-ok">{n("billing.imported", result.inserted_rows ?? 0, { bundle: result.bundle.slice(0, 12) })}</p>}
  </div>;
}
