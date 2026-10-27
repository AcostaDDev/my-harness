import { useRef, useState } from "react";
import type { ReactNode } from "react";
import { managed, confirmOnce, readConfirmation } from "../managed-api";
import type { S } from "../managed-api";
import { Link, navigate } from "../navigation";
import { Alert, Empty, Evidence, Fields, Hash, Loading, PageHeader, Stale, message, usePoll, when } from "../ui";
import { useI18n } from "../Language";
import { LocalizedError } from "../i18n.ts";
import type { Language, MessageKey } from "../i18n.ts";
import { WorkLanguageChoice, WorkLanguagePreview } from "../WorkLanguage";
import { modelOptions } from "../configuration.ts";

// Project registry (H6.2 E2, D054/D076). The operator TOML sets what runs; here only root, composition and
// policy are chosen. Every change goes through a preview bound to its hash and version, and trust in the
// checkout is confirmed separately.

// Fields with a server default are optional when submitting (removal does not carry them).
type Defaulted = "tag_kind" | "documents" | "bootstrap_enabled";
type Change = Omit<S["RegistryChangeInput"], Defaulted> & Partial<Pick<S["RegistryChangeInput"], Defaulted>>;
type Draft = {
  project_id: string; root: string; composition: string; planning_mode: "agent" | "deterministic";
  executor_mode: "catalog" | "open"; executor_models: string[]; executor_efforts: string[]; max_revision_cycles: string;
  tag_kind: "lightweight" | "annotated"; bootstrap_enabled: boolean; permission_authority: string;
  agent_mode: "inherited" | "project"; reviewer_preset: string; reviewer_model: string; reviewer_effort: string; executor_preset: string;
  // D167: chosen once on registration/creation; undefined shows (and sends) the global default.
  work_language?: Language;
};

/** Presets from v5; v6–v8 preserve project agent selection. */
const PRESET_FORMATS = ["local-config-5", "local-config-6", "local-config-7", "local-config-8", "local-config-9"];

const PLANNING: Record<Draft["planning_mode"], MessageKey> = { agent: "settings.planning.agent", deterministic: "settings.planning.deterministic" };
const SELECTION: Record<Draft["executor_mode"], MessageKey> = { catalog: "settings.selection.catalog", open: "settings.selection.open" };
const ACTIONS: Record<Change["action"], MessageKey> = { register: "registry.action.register", update: "registry.action.update", retire: "registry.action.retire" };
const PREVIEW_TITLES: Record<Change["action"], MessageKey> = {
  register: "registry.preview.register", update: "registry.preview.update", retire: "registry.preview.retire",
};
const FIELDS: Record<string, MessageKey> = {
  id: "registry.field.id", root: "registry.field.root", repository_trusted: "registry.field.repository_trusted",
  composition: "registry.field.composition", policy: "registry.field.policy", tag_kind: "settings.tag",
  documents: "settings.documents", bootstrap_enabled: "settings.bootstrap", permission_authority: "registry.field.permission_authority",
  status: "runs.column.status", agent_selection: "registry.field.agent_selection",
};

function emptyDraft(options: S["RegistryRead"]): Draft {
  return { project_id: "", root: options.roots.length === 1 ? `${options.roots[0]}/` : "", composition: options.format === "local-config-9" ? "" : options.compositions[0]?.name ?? "",
    planning_mode: "agent", executor_mode: "catalog", executor_models: [], executor_efforts: [], max_revision_cycles: "",
    tag_kind: "lightweight", bootstrap_enabled: false, permission_authority: "",
    agent_mode: "inherited", reviewer_preset: "", reviewer_model: "", reviewer_effort: "", executor_preset: "" };
}

function draftOf(row: Record<string, unknown>): Draft {
  const policy = (row.policy ?? {}) as Record<string, unknown>;
  const selection = row.agent_selection as S["AgentSelectionInput"] | undefined;
  return { project_id: String(row.id), root: String(row.root), composition: row.composition == null ? "" : String(row.composition),
    planning_mode: policy.planning_mode === "deterministic" ? "deterministic" : "agent",
    executor_mode: policy.executor_mode === "open" ? "open" : "catalog",
    executor_models: (policy.executor_models ?? []) as string[],
    executor_efforts: (policy.executor_efforts ?? []) as string[],
    max_revision_cycles: policy.max_revision_cycles == null ? "" : String(policy.max_revision_cycles),
    tag_kind: row.tag_kind === "annotated" ? "annotated" : "lightweight",
    bootstrap_enabled: row.bootstrap_enabled === true,
    permission_authority: row.permission_authority ? JSON.stringify(row.permission_authority, null, 2) : "",
    agent_mode: selection ? "project" : "inherited", reviewer_preset: selection?.reviewer.preset_id ?? "",
    reviewer_model: selection?.reviewer.model ?? "", reviewer_effort: selection?.reviewer.effort ?? "",
    executor_preset: selection?.executor.preset_id ?? "" };
}

/** Exact change to submit; a permission ceiling that is not JSON is rejected here, without calling the server. */
function changeOf(draft: Draft, action: Change["action"], expected: number, work?: Language): Change {
  if (action === "retire") return { action, project_id: draft.project_id, expected_version: expected };
  let authority: Change["permission_authority"] = null;
  if (draft.permission_authority.trim()) {
    try { authority = JSON.parse(draft.permission_authority); }
    catch { throw new LocalizedError("registry.authority_invalid"); }
  }
  const cycles = draft.max_revision_cycles.trim();
  return {
    action, project_id: draft.project_id.trim(), expected_version: expected,
    ...(action === "register" ? { root: draft.root.trim() } : {}),
    composition: draft.composition || null,
    ...(draft.agent_mode === "project" ? { agent_selection: {
      reviewer: { preset_id: draft.reviewer_preset, model: draft.reviewer_model, effort: draft.reviewer_effort },
      executor: { preset_id: draft.executor_preset } } } : {}),
    policy: { planning_mode: draft.planning_mode, executor_mode: draft.executor_mode,
      executor_models: draft.executor_models,
      executor_efforts: draft.executor_efforts, ...(cycles ? { max_revision_cycles: Number(cycles) } : {}) },
    tag_kind: draft.tag_kind, documents: "v2", bootstrap_enabled: draft.bootstrap_enabled,
    permission_authority: authority,
    ...(action === "register" && work ? { work_language: work } : {}),
  };
}

/** One operation at a time: a second click while the server responds sends nothing. */
function useOperation() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const guard = useRef(false);
  async function run(action: () => Promise<unknown>) {
    if (guard.current) return;
    guard.current = true; setBusy(true); setError("");
    try { await action(); } catch (e) { setError(message(e)); } finally { guard.current = false; setBusy(false); }
  }
  return { busy, error, run, clear: () => setError("") };
}

function Value({ value }: { value: unknown }) {
  const { t } = useI18n();
  return value === undefined || value === null ? <span className="muted">{t("registry.no_value")}</span>
    : typeof value === "object" ? <pre className="inline-json">{JSON.stringify(value, null, 2)}</pre> : <code>{String(value)}</code>;
}

/** Preview and confirmation. `trust` only exists on registration: a confirmation separate from the change. */
function Confirmation({ preview, busy, danger, onConfirm }: {
  preview: S["RegistryPreviewRead"]; busy: boolean; danger?: boolean;
  onConfirm: (trustRoot: string | null, reason: string) => void;
}) {
  const { t, rich } = useI18n();
  const [trusted, setTrusted] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [reason, setReason] = useState("");
  const blocked = preview.unfinished_jobs.length > 0 || (preview.configuration_blockers ?? []).length > 0;
  const creating = preview.action === "register";
  return <section className={`decision ${danger ? "decision-danger" : "decision-attention"}`} aria-labelledby="registry-preview">
    <h3 id="registry-preview">{rich(PREVIEW_TITLES[preview.action], { project: <code>{preview.project_id}</code> })}</h3>
    <p>{rich("settings.checkout", { root: <code className="path">{preview.row.root as string}</code> })}</p>
    <Fields items={[
      [t("registry.version"), preview.expected_version ? `${preview.expected_version} → ${preview.version}` : t("registry.version_new", { version: preview.version })],
      [t("settings.profile"), preview.profile],
      [t("docs.review.preview"), <Hash value={preview.preview_sha256} />],
    ]} />
    {preview.work_language && <WorkLanguagePreview preview={preview.work_language} />}
    <div className="table-scroll" role="region" aria-label={t("registry.changes")} tabIndex={0}>
      <table className="table">
        {/* A registration has no previous value: only the row that will be registered. */}
        <thead><tr><th scope="col">{t("registry.column.field")}</th>{!creating && <th scope="col">{t("registry.column.before")}</th>}<th scope="col">{creating ? t("registry.column.value") : t("registry.column.after")}</th></tr></thead>
        <tbody>{preview.changes.map(c => <tr key={c.field}><th scope="row">{FIELDS[c.field] ? t(FIELDS[c.field]) : c.field}</th>{!creating && <td><Value value={c.before} /></td>}<td><Value value={c.after} /></td></tr>)}</tbody>
      </table>
    </div>
    {preview.versions && <Evidence title={t("registry.versions_evidence")} value={preview.versions} />}
    {!!preview.unfinished_jobs.length && <p className="state state-attention" role="status">{t("registry.unfinished", { jobs: preview.unfinished_jobs.join(", ") })}</p>}
    {!!(preview.configuration_blockers ?? []).length && <Alert>{(preview.configuration_blockers ?? []).join(". ")}</Alert>}
    {preview.trust_required && <fieldset className="trust">
      <legend>{t("registry.trust")}</legend>
      <p>{preview.trust_statement}</p>
      <label className="check"><input type="checkbox" checked={trusted} onChange={e => setTrusted(e.target.checked)} />
        <span>{rich("registry.trust_confirm", { root: <code className="path">{preview.row.root as string}</code> })}</span></label>
    </fieldset>}
    <label>{t("registry.reason")}<input value={reason} maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
    <label className="check"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />
      <span>{preview.action === "retire" ? t("registry.reviewed_retire") : t("registry.reviewed")}</span></label>
    <div className="actions">
      <button type="button" className={danger ? "button-danger" : undefined} disabled={busy || blocked || !reviewed || (preview.trust_required && !trusted)}
        onClick={() => onConfirm(preview.trust_required ? String(preview.row.root) : null, reason.trim())}>
        {preview.action === "register" ? t("home.register") : preview.action === "update" ? t("registry.save") : t("registry.retire")}</button>
    </div>
  </section>;
}

export function DraftFields({ draft, options, action, onChange }: {
  draft: Draft; options: S["RegistryRead"]; action: "register" | "update" | "create"; onChange: (d: Draft) => void;
}) {
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => onChange({ ...draft, [key]: value });
  const { t, preferences } = useI18n();
  const composition = options.compositions.find(c => c.name === draft.composition);
  const reviewer = (options.agent_presets ?? []).find(p => p.id === draft.reviewer_preset && p.roles.includes("reviewer"));
  const executor = (options.agent_presets ?? []).find(p => p.id === draft.executor_preset && p.roles.includes("executor"));
  const projectAgents = draft.agent_mode === "project";
  const efforts = projectAgents ? executor?.efforts ?? [] : options.executor_effort_vocabulary;
  // In catalog mode a project preset bounds the models (checked again by the server); otherwise the packaged
  // suggestions for the executor's provider are offered and any other model can be added.
  const presetBound = projectAgents && draft.executor_mode === "catalog";
  const executorModels = presetBound ? modelOptions(undefined, executor?.models ?? [], draft.executor_models)
    : modelOptions(projectAgents ? executor?.provider : options.executor_provider ?? undefined, executor?.models ?? [], draft.executor_models);
  const [otherModel, setOtherModel] = useState("");
  function addModel() {
    const model = otherModel.trim();
    if (model && !draft.executor_models.includes(model)) set("executor_models", [...draft.executor_models, model]);
    setOtherModel("");
  }
  return <>
    {action === "register" && <div className="form-row">
      <label>{t("registry.project_id")}<input value={draft.project_id} onChange={e => set("project_id", e.target.value)} required maxLength={64}
        pattern="[a-z0-9][a-z0-9._\-]{0,63}" placeholder="my-web" aria-describedby="id-hint" /></label>
      <label>{t("registry.checkout_root")}<input value={draft.root} onChange={e => set("root", e.target.value)} required maxLength={4096}
        className="mono" spellCheck={false} aria-describedby="root-hint" /></label>
    </div>}
    {action === "register" && <p className="hint" id="id-hint">{t("registry.project_id_hint")}</p>}
    {action === "register" && <p className="hint" id="root-hint">{options.roots.length === 1 ? t("registry.root_hint.single") : t("registry.root_hint.multiple")} {options.roots.map(r => <code key={r} className="chip path">{r}</code>)}</p>}
    {action !== "update" && <WorkLanguageChoice value={draft.work_language ?? preferences?.default_work_language}
      onChange={value => set("work_language", value)} />}
    <fieldset>
      <legend>{t("registry.composition_legend")}</legend>
      <label>{t("registry.field.composition")}<select value={draft.composition} onChange={e => set("composition", e.target.value)}>
        {options.format === "local-config-9" && <option value="">{t("profile.from_context")}</option>}
        {options.format !== "local-config-9" && options.compositions.map(c => <option key={c.name} value={c.name}>{c.name} · {c.profile}</option>)}
      </select></label>
      {composition && <Fields items={[
        [t("settings.profile"), composition.profile],
        [t("registry.executables"), composition.executables.map(name => <code key={name} className="chip">{name}</code>)],
        [t("registry.environment"), composition.environment_keys.length ? composition.environment_keys.map(name => <code key={name} className="chip">{name}</code>) : <span className="muted">{t("registry.empty")}</span>],
        [t("registry.commands"), composition.authorize_profile_commands ? t("registry.commands.profile") : t("registry.commands.extra_only")],
        ...(composition.extra_commands.length ? [[t("registry.extra_commands"), composition.extra_commands.map(argv => <code key={argv.join(" ")} className="chip">{argv.join(" ")}</code>)] as [string, ReactNode]] : []),
      ]} />}
      <p className="hint">{t("registry.environment_hint")}</p>
    </fieldset>
    <fieldset>
      <legend>{t("registry.agent_policy")}</legend>
      {PRESET_FORMATS.includes(options.format ?? "") ? <>
        <label>{t("settings.agents")}<select value={draft.agent_mode} onChange={e => onChange({ ...draft,
          agent_mode: e.target.value as Draft["agent_mode"], reviewer_preset: "", reviewer_model: "", reviewer_effort: "",
          executor_preset: "", executor_models: [], executor_efforts: [], executor_mode: "catalog" })}>
          <option value="inherited">{t("registry.agents.inherited")}</option><option value="project">{t("registry.agents.project")}</option>
        </select></label>
        {!projectAgents && <p className="hint">{t("registry.agents.inherited_hint")}</p>}
        {projectAgents && <>
          {!(options.agent_presets ?? []).some(p => p.roles.includes("reviewer")) || !(options.agent_presets ?? []).some(p => p.roles.includes("executor"))
            ? <Alert>{t("registry.presets_missing")}</Alert> : null}
          <div className="form-row">
            <label>{t("registry.reviewer_preset")}<select required value={draft.reviewer_preset} onChange={e => onChange({ ...draft,
              reviewer_preset: e.target.value, reviewer_model: "", reviewer_effort: "" })}>
              <option value="">{t("registry.choose_preset")}</option>
              {(options.agent_presets ?? []).filter(p => p.roles.includes("reviewer")).map(p => <option key={p.id} value={p.id}>{p.provider} · {p.id}</option>)}
            </select></label>
            <label>{t("registry.reviewer_model")}<select required value={draft.reviewer_model} onChange={e => set("reviewer_model", e.target.value)}>
              <option value="">{t("registry.choose_model")}</option>{reviewer?.models.map(model => <option key={model} value={model}>{model}</option>)}
            </select></label>
            <label>{t("registry.reviewer_effort")}<select required value={draft.reviewer_effort} onChange={e => set("reviewer_effort", e.target.value)}>
              <option value="">{t("registry.choose_effort")}</option>{reviewer?.efforts.map(effort => <option key={effort} value={effort}>{effort}</option>)}
            </select></label>
          </div>
          <label>{t("registry.executor_preset")}<select required value={draft.executor_preset} onChange={e => onChange({ ...draft,
            executor_preset: e.target.value, executor_models: [], executor_efforts: [], executor_mode: "catalog" })}>
            <option value="">{t("registry.choose_preset")}</option>
            {(options.agent_presets ?? []).filter(p => p.roles.includes("executor")).map(p => <option key={p.id} value={p.id}>{p.provider} · {p.id}</option>)}
          </select></label>
          {executor && <p className="hint">{t("registry.executor_models", { models: executor.models.join(", ") })} {executor.allow_open_executor ? t("registry.open_allowed") : t("registry.catalog_only")}</p>}
          <p className="hint">{t("registry.reviewer_decides")}</p>
        </>}
      </> : <p className="hint">{t("registry.presets_unsupported")}</p>}
      <div className="form-row">
        <label>{t("settings.planning")}<select value={draft.planning_mode} onChange={e => set("planning_mode", e.target.value as Draft["planning_mode"])}>
          {Object.entries(PLANNING).map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}</select></label>
        <label>{t("registry.executor_selection")}<select value={draft.executor_mode} onChange={e => set("executor_mode", e.target.value as Draft["executor_mode"])}>
          {Object.entries(SELECTION).map(([value, label]) => <option key={value} value={value} disabled={value === "open" && projectAgents && !executor?.allow_open_executor}>{t(label)}</option>)}</select></label>
        <label>{t("registry.revision_cycles")}<input type="number" min={0} max={20} value={draft.max_revision_cycles} placeholder="3"
          onChange={e => set("max_revision_cycles", e.target.value)} /></label>
      </div>
      <p className="legend">{t("registry.executor_catalog", { provider: projectAgents ? executor?.provider ?? t("registry.choose_preset_short") : options.executor_provider ?? t("registry.no_provider") })}</p>
      <div className="effort-list">{executorModels.map(model => <label key={model} className="check">
        <input type="checkbox" checked={draft.executor_models.includes(model)} onChange={e => set("executor_models",
          e.target.checked ? executorModels.filter(v => v === model || draft.executor_models.includes(v)) : draft.executor_models.filter(v => v !== model))} />{model}</label>)}</div>
      {!presetBound && <div className="form-row">
        <label>{t("registry.other_model")}<input value={otherModel} maxLength={128} spellCheck={false} onChange={e => setOtherModel(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addModel(); } }} /></label>
        <div className="actions"><button type="button" className="button-quiet" disabled={!otherModel.trim()} onClick={addModel}>{t("registry.add_model")}</button></div>
      </div>}
      <p className="legend">{t("registry.executor_efforts")}</p>
      <div className="effort-list">{efforts.map(effort => <label key={effort} className="check">
        <input type="checkbox" checked={draft.executor_efforts.includes(effort)} onChange={e => set("executor_efforts",
          e.target.checked ? efforts.filter(v => v === effort || draft.executor_efforts.includes(v)) : draft.executor_efforts.filter(v => v !== effort))} />{effort}</label>)}</div>
      {!projectAgents && <p className="hint">{t("registry.reviewer_toml", { provider: options.reviewer_provider ?? t("registry.no_provider") })}</p>}
    </fieldset>
    <fieldset>
      <legend>{t("settings.project")}</legend>
      <div className="form-row">
        <label>{t("settings.tag")}<select value={draft.tag_kind} onChange={e => set("tag_kind", e.target.value as Draft["tag_kind"])}>
          <option value="lightweight">{t("settings.tag.lightweight")}</option><option value="annotated">{t("settings.tag.annotated")}</option></select></label>
      </div>
      <p className="hint">{t("registry.documents_hint")}</p>
      {action !== "create" && <label className="check"><input type="checkbox" checked={draft.bootstrap_enabled} disabled={!options.bootstrap_enabled}
        onChange={e => set("bootstrap_enabled", e.target.checked)} />
        <span>{options.bootstrap_enabled ? t("registry.bootstrap") : t("registry.bootstrap_forbidden")}</span></label>}
      <label>{t("registry.authority")}
        <textarea rows={3} value={draft.permission_authority} onChange={e => set("permission_authority", e.target.value)} spellCheck={false}
          placeholder={'{"global": {}, "project": {"tools": ["Read"]}, "contract": {}, "provider": {}}'} /></label>
    </fieldset>
  </>;
}

/** Form with preview: any edit invalidates the preview already shown. */
function RegistryForm({ options, action, initial, expected, onApplied }: {
  options: S["RegistryRead"]; action: "register" | "update"; initial: Draft; expected: number;
  onApplied: (result: S["RegistryApplyRead"], change: Change) => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [preview, setPreview] = useState<{ change: Change; data: S["RegistryPreviewRead"] }>();
  const generation = useRef(0);
  const op = useOperation();
  const { t, preferences } = useI18n();
  const work = draft.work_language ?? preferences?.default_work_language;
  function edit(next: Draft) { generation.current += 1; setDraft(next); setPreview(undefined); op.clear(); }
  const ready = (options.format === "local-config-9" || draft.composition) && draft.executor_efforts.length && draft.executor_models.length
    && (action === "update" || (draft.project_id.trim() && draft.root.trim() && work));
  return <form onSubmit={e => {
    e.preventDefault();
    void op.run(async () => {
      const current = generation.current;
      const change = changeOf(draft, action, expected, work);
      const data = await managed<S["RegistryPreviewRead"]>("/registry/preview", change);
      if (current === generation.current) setPreview({ change, data });
    });
  }}>
    <DraftFields draft={draft} options={options} action={action} onChange={edit} />
    {op.error && <Alert>{op.error}</Alert>}
    <div className="actions"><button className={preview ? "button-quiet" : undefined} disabled={op.busy || !ready}>
      {preview ? t("registry.review_again") : action === "register" ? t("registry.review_register") : t("docs.editor.review")}</button></div>
    {preview && <Confirmation key={preview.data.preview_sha256} preview={preview.data} busy={op.busy} onConfirm={(trust, reason) => void op.run(async () => {
      onApplied(await managed<S["RegistryApplyRead"]>("/registry/apply", {
        change: preview.change, preview_sha256: preview.data.preview_sha256, trust_root: trust, reason: reason || null }), preview.change);
      setPreview(undefined);
    })} />}
  </form>;
}

function CreationRootPanel({ root, refresh }: { root: S["CreationRootRead"]; refresh: () => void }) {
  const { t } = useI18n();
  const [path, setPath] = useState("");
  const [preview, setPreview] = useState<{ change: S["CreationRootChangeInput"]; data: S["CreationRootPreviewRead"] }>();
  const [accepted, setAccepted] = useState(false);
  const generation = useRef(0);
  const op = useOperation();
  return <section className="panel" aria-labelledby="creation-root">
    <h2 id="creation-root">{t("creation.root.title")}</h2>
    <p>{root.permission_statement} {t("creation.root.hint")}</p>
    <Fields items={[[t("creation.root.current"), root.status === "ACTIVE" ? <code className="path">{root.path}</code> : t("creation.root.none")],
      [t("creation.root.revision"), root.version]]} />
    {!root.available ? <p>{root.diagnostic}</p> : <form onSubmit={e => {
      e.preventDefault();
      void op.run(async () => {
        const current = generation.current;
        const change: S["CreationRootChangeInput"] = { action: "select", expected_version: root.version, path };
        const data = await managed<S["CreationRootPreviewRead"]>("/project-creation-root/preview", change);
        if (current === generation.current) { setPreview({ change, data }); setAccepted(false); }
      });
    }}>
      <label>{t("creation.root.path")}<input value={path} maxLength={4096} required className="mono" spellCheck={false}
        onChange={e => { generation.current++; setPath(e.target.value); setPreview(undefined); setAccepted(false); }} /></label>
      <p className="hint">{t("creation.root.path_hint")}</p>
      <div className="actions">
        <button disabled={op.busy || !path.trim()}>{t("creation.root.review")}</button>
        {root.status === "ACTIVE" && <button type="button" className="button-quiet" disabled={op.busy} onClick={() => void op.run(async () => {
          const change: S["CreationRootChangeInput"] = { action: "retire", expected_version: root.version };
          setPreview({ change, data: await managed("/project-creation-root/preview", change) }); setAccepted(false);
        })}>{t("creation.root.review_retire")}</button>}
      </div>
      {preview && <div className="decision decision-attention">
        <h3>{preview.change.action === "select" ? t("creation.root.save") : t("creation.root.retire")}</h3>
        {preview.change.action === "select" ? <p className="path"><code>{preview.data.root.path}</code></p>
          : <p>{t("creation.root.retire_hint")}</p>}
        <label className="check"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />
          <span>{preview.change.action === "select" ? t("creation.root.authorize") : t("creation.root.reviewed_retire")}</span></label>
        <button type="button" disabled={op.busy || !accepted} onClick={() => void op.run(async () => {
          await confirmOnce("/project-creation-root/apply", { change: preview.change, preview_sha256: preview.data.preview_sha256,
            confirm_path: preview.data.root.path });
          setPreview(undefined); refresh();
        })}>{preview.change.action === "select" ? t("creation.root.save") : t("creation.root.retire")}</button>
      </div>}
    </form>}
    {op.error && <Alert>{op.error}</Alert>}
    {!!root.history.length && <Evidence title={t("creation.root.history")} value={root.history} />}
  </section>;
}

function CreationOperation({ initial, rootVersion, editable, refresh }: {
  initial: S["CreationOperationRead"]; rootVersion: number; editable: boolean; refresh: () => void;
}) {
  const { t, rich } = useI18n();
  const [operation, setOperation] = useState(initial);
  const [preview, setPreview] = useState<{ change: S["CreationResumeInput"]; data: S["CreationResumePreviewRead"] }>();
  const op = useOperation();
  function saved(value: S["CreationOperationRead"]) { setOperation(value); setPreview(undefined); refresh(); }
  return <article className="decision decision-attention">
    <h3><code>{operation.project_id}</code> · {operation.status}</h3>
    <p><code className="path">{operation.target}</code></p>
    <p>{rich("creation.operation", { id: <code>{operation.id}</code>, version: operation.version })}</p>
    {operation.diagnostic && <p role="status">{operation.diagnostic}</p>}
    {operation.reserved && operation.status !== "REGISTERED" && <p>{t("creation.operation.reserved")}</p>}
    {editable && (operation.status === "REGISTERED" ? <Link to={{ name: "setup", project: operation.project_id }}>{t("creation.operation.continue")}</Link>
      : (operation.status !== "CANCELLED" || operation.reserved) && <div className="actions">
        {operation.status !== "RECOVERY_REQUIRED" && operation.status !== "CANCELLED" && <button type="button" disabled={op.busy} onClick={() => void op.run(async () => {
          const change = { expected_version: operation.version, root_version: rootVersion };
          setPreview({ change, data: await managed(`/project-creations/${operation.id}/resume/preview`, change) });
        })}>{t("creation.operation.review_resume")}</button>}
        <button type="button" className="button-quiet" disabled={op.busy} onClick={() => void op.run(async () => {
          saved(await confirmOnce(`/project-creations/${operation.id}/cancel`, {
            expected_version: operation.version, intent_sha256: operation.intent_sha256 }));
        })}>{operation.status === "CANCELLED" ? t("creation.operation.recheck") : t("creation.operation.cancel")}</button>
      </div>)}
    {preview && <div className="decision">
      <p>{rich("creation.operation.resume", { target: <code className="path">{preview.data.target}</code>, revision: rootVersion })}</p>
      <button type="button" disabled={op.busy} onClick={() => void op.run(async () => {
        saved(await confirmOnce(`/project-creations/${operation.id}/resume/confirm`, {
          change: preview.change, preview_sha256: preview.data.preview_sha256 }));
      })}>{t("creation.operation.confirm_resume")}</button>
    </div>}
    {op.error && <Alert>{op.error}</Alert>}
    <Evidence title={t("creation.operation.evidence")} value={operation} />
  </article>;
}

function NewDirectoryForm({ options, root, refresh }: {
  options: S["RegistryRead"]; root: S["CreationRootRead"]; refresh: () => void;
}) {
  const [draft, setDraft] = useState(() => emptyDraft(options));
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<{ change: S["CreationInput"]; data: S["CreationPreviewRead"] }>();
  const [trusted, setTrusted] = useState(false);
  const generation = useRef(0);
  const op = useOperation();
  const { t, rich, preferences } = useI18n();
  const work = draft.work_language ?? preferences?.default_work_language;
  function invalidate() { generation.current++; setPreview(undefined); setTrusted(false); }
  const ready = draft.project_id.trim() && name && (options.format === "local-config-9" || draft.composition) && draft.executor_models.length && draft.executor_efforts.length && work;
  return <section className="panel" aria-labelledby="new-directory"><h2 id="new-directory">{t("creation.new")}</h2>
    <form onSubmit={e => { e.preventDefault(); void op.run(async () => {
      const current = generation.current;
      const fields = changeOf(draft, "register", 0);
      const change: S["CreationInput"] = { project_id: fields.project_id, directory_name: name, root_version: root.version,
        composition: fields.composition!, policy: fields.policy!, tag_kind: draft.tag_kind, documents: "v2",
        permission_authority: fields.permission_authority, agent_selection: fields.agent_selection, work_language: work! };
      const data = await managed<S["CreationPreviewRead"]>("/project-creations/preview", change);
      if (current === generation.current) setPreview({ change, data });
    }); }}>
      <div className="form-row">
        <label>{t("registry.project_id")}<input value={draft.project_id} required maxLength={64} pattern="[a-z0-9][a-z0-9._\-]{0,63}"
          onChange={e => { invalidate(); setDraft({ ...draft, project_id: e.target.value }); }} /></label>
        <label>{t("creation.directory")}<input value={name} required maxLength={64} pattern="[a-z0-9][a-z0-9._\-]{0,63}"
          onChange={e => { invalidate(); setName(e.target.value); }} /></label>
      </div>
      <p>{rich("creation.target", { target: <code className="path">{root.path}/{name || "…"}</code> })}</p>
      <p className="hint">{t("creation.target_hint")}</p>
      <DraftFields draft={draft} options={options} action="create" onChange={next => { invalidate(); setDraft(next); }} />
      <button disabled={op.busy || !ready}>{t("creation.review")}</button>
      {preview && <div className="decision decision-attention">
        <h3>{rich("creation.preview.title", { project: <code>{preview.change.project_id}</code> })}</h3>
        <p><code className="path">{preview.data.target}</code></p>
        <Fields items={[[t("settings.profile"), preview.data.profile], [t("creation.root_revision"), root.version]]} />
        <WorkLanguagePreview preview={preview.data.work_language} />
        <Fields items={[[t("settings.reviewer"), `${preview.data.agents.reviewer.provider} · ${preview.data.agents.reviewer.model} · ${preview.data.agents.reviewer.effort}`],
          [t("settings.executor"), t("creation.executor_value", { provider: preview.data.agents.executor.provider ?? t("registry.no_provider") })]]} />
        <p>{t("creation.preview.body")}</p>
        <p>{preview.data.trust_statement}</p>
        <Evidence title={t("creation.preview.evidence")} value={preview.data} />
        <label className="check"><input type="checkbox" checked={trusted} onChange={e => setTrusted(e.target.checked)} />
          <span>{rich("creation.preview.trust", { target: <code className="path">{preview.data.target}</code> })}</span></label>
        <button type="button" disabled={op.busy || !trusted} onClick={() => void op.run(async () => {
          const result = await confirmOnce<S["CreationOperationRead"]>("/project-creations/confirm", {
            change: preview.change, preview_sha256: preview.data.preview_sha256, trust_root: preview.data.target });
          setPreview(undefined); refresh();
          if (result.status === "REGISTERED") navigate({ name: "setup", project: result.project_id });
        })}>{t("creation.submit")}</button>
      </div>}
      {op.error && <Alert>{op.error}</Alert>}
    </form>
  </section>;
}

export function RegisterPage() {
  const { t } = useI18n();
  const [revision, setRevision] = useState(0);
  const [mode, setMode] = useState<"create" | "register">("create");
  const read = usePoll<S["RegistryRead"]>("/registry", 0, revision);
  const folder = usePoll<S["CreationRootRead"]>("/project-creation-root", 0, revision);
  const retry = useOperation();
  const pending = readConfirmation();
  const refresh = () => setRevision(n => n + 1);
  const options = read.data;
  return <>
    <PageHeader title={t("nav.new_project")}><p>{t("register.lede")}</p></PageHeader>
    {pending && <section className="decision decision-attention">
      <h2>{t("register.pending.title")}</h2><p>{t("register.pending.body")}</p>
      <Evidence title={t("register.pending.evidence")} value={pending} />
      <button disabled={retry.busy} onClick={() => void retry.run(async () => {
        await confirmOnce(pending.path, pending.body); refresh();
      })}>{t("register.pending.resend")}</button>
      {retry.error && <Alert>{retry.error}</Alert>}
    </section>}
    {folder.data ? <CreationRootPanel key={`root-${folder.data.version}`} root={folder.data} refresh={refresh} />
      : folder.error ? <Alert>{folder.error}</Alert> : <Loading />}
    <div className="actions" role="group" aria-label={t("register.mode")}>
      <button type="button" className={mode === "create" ? undefined : "button-quiet"} aria-pressed={mode === "create"}
        onClick={() => setMode("create")}>{t("creation.new")}</button>
      <button type="button" className={mode === "register" ? undefined : "button-quiet"} aria-pressed={mode === "register"}
        onClick={() => setMode("register")}>{t("register.existing")}</button>
    </div>
    {!options ? read.error ? <Alert>{read.error}</Alert> : <Loading />
      : !options.available ? <Empty title={t("register.unavailable.title")}><p>{t("register.unavailable.body")}</p></Empty>
      : mode === "create" ? !options.creation_available ? <Empty title={t("register.creation_disabled.title")}><p>{t("register.creation_disabled.body")}</p></Empty>
        : folder.data?.status !== "ACTIVE" ? <Empty title={t("register.no_root.title")}><p>{t("register.no_root.body")}</p></Empty>
        : <NewDirectoryForm key={`new-${folder.data.version}`} options={options} root={folder.data} refresh={refresh} />
      : !options.roots.length ? <Empty title={t("register.no_toml_roots.title")}><p>{t("register.no_toml_roots.body")}</p></Empty>
      : <section className="panel"><h2>{t("register.existing")}</h2>
        <RegistryForm options={options} action="register" initial={emptyDraft(options)} expected={0}
          onApplied={(result, change) => navigate(change.bootstrap_enabled
            ? { name: "setup", project: result.project.id } : { name: "project", project: result.project.id })} />
      </section>}
    {!!folder.data?.operations.length && <section className="panel"><h2>{t("register.operations")}</h2>
      {folder.data.operations.map(operation => <CreationOperation key={`${operation.id}-${operation.version}`} initial={operation}
        rootVersion={folder.data!.version} editable={folder.data!.available} refresh={refresh} />)}
    </section>}
  </>;
}

/** Settings of a registered project: version, audit, change and removal. TOML projects are read-only. */
export function RegistrySettings({ project, onChanged }: { project: string; onChanged: () => void }) {
  const { t } = useI18n();
  const [refresh, setRefresh] = useState(0);
  const options = usePoll<S["RegistryRead"]>("/registry", 0, refresh);
  const detail = usePoll<S["RegisteredProjectRead"]>(`/registry/projects/${project}`, 0, refresh);
  const retire = useOperation();
  const [retirement, setRetirement] = useState<{ change: Change; data: S["RegistryPreviewRead"] }>();
  const item = detail.data;
  if (!item || !options.data) return detail.error && !detail.missing ? <Alert>{t("registry.read_failed", { error: detail.error })}</Alert> : <Loading />;
  const change: Change = { action: "retire", project_id: project, expected_version: item.version };
  return <section className="panel" aria-labelledby="settings-registry">
    <h2 id="settings-registry">{t("registry.title")}</h2>
    <Stale error={detail.error ?? options.error} />
    <Fields items={[
      [t("registry.version"), `${item.version} · ${item.status === "ACTIVE" ? t("registry.active") : t("registry.retired")}`],
      [t("registry.trust_short"), item.trust.confirmed && item.trust.root === item.root ? t("registry.trust_confirmed") : t("registry.trust_unconfirmed")],
      [t("registry.row"), <Hash value={item.row_sha256} />],
      [t("registry.unfinished_jobs"), item.unfinished_jobs.length ? item.unfinished_jobs.join(", ") : t("stats.none")],
      [t("registry.blockers"), (item.configuration_blockers ?? []).length ? (item.configuration_blockers ?? []).join(". ") : t("stats.none")],
      [t("settings.agents"), item.row.agent_selection ? t("registry.agents_own") : t("registry.agents_inherited")],
    ]} />
    {!item.available && item.diagnostic && <p className="state state-attention">{t("registry.not_composed", { diagnostic: item.diagnostic })}</p>}
    <h3>{t("registry.audit")}</h3>
    <div className="table-scroll" role="region" aria-label={t("registry.audit_table")} tabIndex={0}>
      <table className="table">
        <thead><tr><th scope="col" className="numeric">{t("registry.version")}</th><th scope="col">{t("registry.column.action")}</th><th scope="col">{t("registry.column.who")}</th><th scope="col">{t("registry.column.when")}</th><th scope="col">{t("registry.row")}</th><th scope="col">{t("stats.column.reason")}</th></tr></thead>
        <tbody>{item.history.map(e => <tr key={e.version}>
          <td className="numeric">{e.version}</td><td>{ACTIONS[e.action] ? t(ACTIONS[e.action]) : e.action}</td><td>{String(e.actor.user ?? e.actor.uid)}</td>
          <td>{when(e.recorded_at)}</td><td><Hash value={e.row_sha256} /></td><td>{e.reason ?? <span className="muted">{t("registry.no_reason")}</span>}</td>
        </tr>)}</tbody>
      </table>
    </div>
    {item.status === "ACTIVE" && options.data.available && <>
      <details className="registry-edit">
        <summary><h3>{t("registry.change")}</h3></summary>
        <p className="hint">{t("registry.change_hint")}</p>
        <RegistryForm key={item.version} options={options.data} action="update" initial={draftOf(item.row)} expected={item.version}
          onApplied={() => { setRefresh(n => n + 1); onChanged(); }} />
      </details>
      <div className="decision decision-danger">
        <h3>{t("registry.retire")}</h3>
        <p>{t("registry.retire_hint")}</p>
        {retire.error && <Alert>{retire.error}</Alert>}
        {!retirement ? <button type="button" className="button-danger" disabled={retire.busy}
          onClick={() => void retire.run(async () => setRetirement({ change, data: await managed<S["RegistryPreviewRead"]>("/registry/preview", change) }))}>{t("registry.review_retire")}</button>
          : <Confirmation preview={retirement.data} busy={retire.busy} danger onConfirm={(_, reason) => void retire.run(async () => {
            await managed<S["RegistryApplyRead"]>("/registry/apply", { change: retirement.change, preview_sha256: retirement.data.preview_sha256, trust_root: null, reason: reason || null });
            navigate({ name: "home" });
          })} />}
      </div>
    </>}
  </section>;
}
