import { useEffect, useState } from "react";
import { confirmOnce, managed, readConfirmation } from "../managed-api";
import type { S } from "../managed-api";
import type { MessageKey } from "../i18n.ts";
import { useI18n } from "../Language";
import { useWorkspace } from "../workspace";
import { DiffBlock, Evidence, Hash, Stale, usePoll } from "../ui";
import { configurationChange } from "../project-profile";
import type { Form } from "../project-profile";
import { ConfigurationAssistance } from "./ConfigurationAssistance";
import { Preparation } from "./Preparation";

type Candidate = S["ConfigurationCandidate"];
const STAGES: Record<string, MessageKey> = {
  PROFILE_REQUIRED: "profile.stage.required", PROFILE_PROPOSED: "profile.stage.proposed",
  DOCUMENTS_COMMITTED: "profile.stage.documents", PREPARATION_REQUIRED: "profile.stage.preparation",
  READY_TO_ACTIVATE: "profile.stage.ready", ACTIVE: "profile.stage.active",
};

/** Preserve the exact draft in the tab; polling never replaces edits after a concurrent save. */
function useTabState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try { return JSON.parse(sessionStorage.getItem(key) ?? "null") ?? initial; } catch { return initial; }
  });
  useEffect(() => { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ } }, [key, value]);
  return [value, setValue] as const;
}
const useEditor = (key: string, initial: Form) => useTabState(key, initial);

export function ProfileReplay() {
  const { t } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const pending = readConfirmation();
  if (!pending?.path.startsWith(`/projects/${project}/`) || !/\/(configuration|profile|preparation)\//.test(pending.path)) return null;
  return <section className="decision decision-attention"><p>{t("profile.pending")}</p>
    <Evidence title={t("profile.evidence")} value={pending} />
    <button disabled={busy} onClick={() => void operate(() => confirmOnce(pending.path, pending.body))}>{t("workspace.pending.repeat")}</button>
  </section>;
}

export function ProfileProposal({ conversation, proposal, base }: {
  conversation: S["PlanningConversationRead"]; proposal: S["PlanningProposalRead"]; base: string;
}) {
  const { t } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const initial = JSON.parse(proposal.content).candidate as Form;
  const [form, setForm] = useEditor(`harness-profile-proposal:${project}:${proposal.id}`, initial);
  const editorKey = `harness-profile-proposal:${project}:${proposal.id}`;
  const [text, setText] = useTabState(editorKey + ":text", "");
  const [mode, setMode] = useTabState<"form" | "toml">(editorKey + ":mode", "form");
  const [advanced, setAdvanced] = useTabState(editorKey + ":advanced", JSON.stringify(form, null, 2));
  const [reason, setReason] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [preview, setPreview] = useState<S["ProfileProposalPreviewRead"]>();
  const templates = usePoll<S["RegistryRead"]>("/registry", 0);
  const [template, setTemplate] = useState("");
  useEffect(() => { setPreview(undefined); setReviewed(false); }, [conversation.version]);
  const edit = (next: Form) => { setForm(next); setAdvanced(JSON.stringify(next, null, 2)); setPreview(undefined); setReviewed(false); };
  const adopted = proposal.status === "ACCEPTED";
  const dirty = mode === "toml" || JSON.stringify(form) !== JSON.stringify(initial) || advanced !== JSON.stringify(form, null, 2);
  const candidate: Candidate = mode === "toml" ? { text, validated: false } : { form, validated: false };
  return <section className="panel">
    <h3>{t("profile.proposal")}</h3>{adopted && <p role="status">{t("profile.adopted")}</p>}<p>{t("profile.proposal_hint")}</p>
    <label>{t("profile.name")}<input value={String(form.name)} disabled={mode === "toml"} onChange={e => edit({ ...form, name: e.target.value })} /></label>
    <label>{t("profile.instructions")}<textarea rows={4} disabled={mode === "toml"} value={form.profile.executor_instructions} onChange={e => edit({ ...form, profile: { ...form.profile, executor_instructions: e.target.value } })} /></label>
    {!!templates.data?.compositions.length && <div className="form-row">
      <label>{t("profile.template")}<select value={template} onChange={e => setTemplate(e.target.value)}><option value="">{t("profile.choose_template")}</option>
        {templates.data.compositions.map(c => <option key={c.name} value={c.name}>{c.name} · {c.profile}</option>)}</select></label>
      <button disabled={busy || !template} onClick={() => void operate(async () => {
        const copy = await managed<Form>(`/projects/${project}/profile-templates/${encodeURIComponent(template)}`);
        edit({ ...form, name: copy.name, profile: copy.profile });
      })}>{t("profile.copy_template")}</button>
    </div>}
    <div className="actions"><button disabled={busy} onClick={() => void operate(async () => {
      const converted = await managed<S["ConfigurationFormRead"]>(`${base}/profile/form`, candidate);
      setText(converted.text); edit(converted.form); setMode(mode === "form" ? "toml" : "form");
    })}>{mode === "form" ? t("profile.toml") : t("profile.form")}</button></div>
    {mode === "toml" ? <label>{t("profile.toml")}<textarea id="profile-proposal-toml" rows={18} value={text} spellCheck={false} onChange={e => { setText(e.target.value); setPreview(undefined); }} /></label>
      : <details><summary>{t("profile.advanced")}</summary><label>{t("profile.candidate_json")}<textarea rows={20} spellCheck={false} value={advanced} onChange={e => { setAdvanced(e.target.value); setPreview(undefined); }} /></label>
        <button disabled={busy} onClick={() => void operate(async () => {
          const converted = await managed<S["ConfigurationFormRead"]>(`${base}/profile/form`, { form: JSON.parse(advanced), validated: false });
          edit(converted.form);
        })}>{t("profile.apply_fields")}</button></details>}
    <Evidence title={t("profile.evidence")} value={JSON.parse(proposal.content)} />
    <label>{t("docs.review.reason")}<input value={reason} onChange={e => { setReason(e.target.value); setPreview(undefined); }} maxLength={1000} /></label>
    <button disabled={busy || !reason.trim() || mode === "form" && advanced !== JSON.stringify(form, null, 2)} onClick={() => void operate(async () => {
      await confirmOnce(`${base}/profile/edit`, { proposal_id: proposal.id, proposal_sha256: proposal.proposal_sha256,
        expected_version: conversation.version, candidate, reason } satisfies S["ProfileEdit"]);
    })}>{t("profile.save_draft")}</button>
    <p className="hint">{t("profile.adopt_hint")}</p>
    <button disabled={busy || adopted || dirty || !reason.trim()} onClick={() => void operate(async () => {
      setPreview(await managed<S["ProfileProposalPreviewRead"]>(`${base}/profile/preview`, {
        proposal_id: proposal.id, proposal_sha256: proposal.proposal_sha256, expected_version: conversation.version,
      })); setReviewed(false);
    })}>{t("profile.review_adoption")}</button>
    {preview && <div className="decision">
      <Evidence title={t("profile.evidence")} value={preview} />
      {preview.blockers.map(b => <p className="state state-attention" key={b}>{b}</p>)}
      <Hash value={preview.preview_sha256} />
      <label className="check"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />{t("profile.confirm_exact")}</label>
      <button disabled={busy || !reviewed || !preview.ready || !reason.trim()} onClick={() => void operate(async () => {
        await confirmOnce(`${base}/profile/confirm`, { proposal_id: proposal.id, proposal_sha256: proposal.proposal_sha256,
          expected_version: preview.expected_version, preview_sha256: preview.preview_sha256, confirmed: true, reason,
        } satisfies S["ProfileProposalConfirmCreate"]); setPreview(undefined);
      })}>{t("profile.adopt")}</button>
    </div>}
  </section>;
}

export function ProjectProfile() {
  const { project, refresh } = useWorkspace();
  const info = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 2000, refresh);
  const eligible = info.data?.versions.local_config === "local-config-9" || info.data?.configuration_state === "PREPARATION_REQUIRED" || info.data?.configuration_state === "READY_TO_ACTIVATE";
  const read = usePoll<S["ProjectConfigurationRead"]>(eligible ? `/projects/${project}/configuration` : null, 2000, refresh);
  if (!eligible || !read.data) return <Stale error={eligible ? read.error : undefined} />;
  return <ProjectProfileEditor key={project} state={read.data} error={read.error} />;
}

function ProjectProfileEditor({ state, error }: { state: S["ProjectConfigurationRead"]; error?: string }) {
  const { t } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const base = `/projects/${project}/configuration`;
  const [form, setForm] = useEditor(`harness-project-configuration:${project}`, state.form);
  const editorKey = `harness-project-configuration:${project}`;
  const [cas, setCas] = useTabState(editorKey + ":base", state);
  const [text, setText] = useTabState(editorKey + ":text", state.text ?? "");
  const [mode, setMode] = useTabState<"form" | "toml">(editorKey + ":mode", "form");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<{ kind: "save" | "activate"; body: Form; shown: S["ConfigurationPreviewRead"] }>();
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { setPreview(undefined); setConfirmed(false); }, [state.version, state.status]);
  const edit = (next: Form) => { setForm(next); setPreview(undefined); setConfirmed(false); };
  const activation = { revision: state.saved?.revision as number, sha256: state.saved?.sha256 as string,
    expected_version: state.version, reason };
  const tools = form.commands.executables as Record<string, string>;
  return <section className="panel">
    <h2>{t("profile.configuration")}</h2><p role="status">{t("profile.stage")} <strong>{STAGES[state.configuration_state] ? t(STAGES[state.configuration_state]) : state.configuration_state}</strong> · {state.status}</p>
    {state.candidate_state && state.candidate_state !== state.configuration_state && <p role="status">{t("configuration.candidate")} · {STAGES[state.candidate_state] ? t(STAGES[state.candidate_state]) : state.candidate_state}</p>}
    <Stale error={error} /><ProfileReplay />
    <p>{t("profile.order")}</p>
    {state.version !== cas.version && <p role="alert" className="state state-attention">{t("profile.conflict")}</p>}
    <>
      {(state.active || form.provenance?.source === "legacy-configuration") && <><p>{t("assistance.profile_hint")}</p>
        <button disabled={busy} onClick={() => void operate(async () => {
          const current = await managed<S["ConfigurationFormRead"]>(`${base}/edit-base`, {});
          edit(current.form); setText(current.text); setCas(state); setMode("form");
        })}>{t("assistance.edit_base")}</button>
        {state.active && <ConfigurationAssistance scope={`project:${project}`} state={cas} candidate={mode === "toml" ? { text, validated: false } : { form, validated: false }}
          disabled={busy} run={operate} contextPaths={state.assistance_documents}
          apply={next => { setText(next); setMode("toml"); setPreview(undefined); setConfirmed(false); }} />}
      </>}
      <label>{t("profile.name")}<input readOnly value={String(form.profile_name)} /></label>
      <label>{t("profile.instructions")}<textarea rows={4} value={form.profile.executor_instructions} disabled={mode === "toml"} onChange={e => edit({ ...form, profile: { ...form.profile, executor_instructions: e.target.value } })} /></label>
      {Object.entries(tools).map(([name, path]) => <label key={name}>{t("profile.tool", { name })}<input value={path} disabled={mode === "toml"} spellCheck={false} onChange={e => edit({ ...form, commands: { ...form.commands, executables: { ...tools, [name]: e.target.value } } })} /></label>)}
      {Object.entries(form.commands.environment as Record<string, string>).map(([name, value]) => <label key={name}>{name}<input value={value} disabled={mode === "toml"} spellCheck={false} onChange={e => edit({ ...form, commands: { ...form.commands, environment: { ...form.commands.environment, [name]: e.target.value } } })} /></label>)}
      <button disabled={busy} onClick={() => void operate(async () => {
        const converted = await managed<S["ConfigurationFormRead"]>(`${base}/form`, mode === "form" ? { form, validated: false } : { text, validated: false });
        edit(converted.form); setText(converted.text); setMode(mode === "form" ? "toml" : "form");
      })}>{mode === "form" ? t("profile.toml") : t("profile.form")}</button>
      {mode === "toml" && <label>{t("profile.toml")}<textarea id="project-profile-toml" rows={22} value={text} spellCheck={false} onChange={e => { setText(e.target.value); setPreview(undefined); setConfirmed(false); }} /></label>}
      <label>{t("docs.review.reason")}<input value={reason} maxLength={1000} onChange={e => { setReason(e.target.value); setPreview(undefined); setConfirmed(false); }} /></label>
      <div className="actions"><button disabled={busy || !reason.trim()} onClick={() => void operate(async () => {
        const converted = await managed<S["ConfigurationFormRead"]>(`${base}/form`, mode === "form" ? { form, validated: true } : { text, validated: true });
        const body = configurationChange(cas, converted.text, reason);
        const shown = await managed<S["ConfigurationPreviewRead"]>(`${base}/preview`, body);
        setPreview({ kind: "save", body, shown }); setConfirmed(false);
      })}>{t("profile.review_save")}</button>
      <button className="button-quiet" disabled={busy} onClick={() => { edit(state.form); setText(state.text ?? ""); setCas(state); }}>{t("profile.reload_base")}</button></div>
    </>
    <Evidence title={t("profile.references")} value={{ saved: state.saved, active: state.active, profile: state.profile }} />
    <Preparation configuration={state} />
    {form.provenance?.source === "legacy-configuration" && !state.active && <p>{t("configuration.import_prepare")}</p>}
    {state.saved && (form.provenance?.source !== "legacy-configuration" || state.active) && state.saved.sha256 !== state.active?.sha256 && <button disabled={busy || !reason.trim()} onClick={() => void operate(async () => {
      const shown = await managed<S["ConfigurationPreviewRead"]>(`${base}/activation/preview`, activation);
      setPreview({ kind: "activate", body: activation, shown }); setConfirmed(false);
    })}>{t("profile.review_activation")}</button>}
    {preview && <div className="decision">
      <Hash value={preview.shown.sha256} />
      {preview.shown.changes?.map((change, index) => <DiffBlock key={index} diff={String(change.diff ?? "")} label={t("profile.diff")} />)}
      <Evidence title={t("profile.evidence")} value={preview.shown} />
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("profile.confirm_exact")}</label>
      <button disabled={busy || !confirmed} onClick={() => void operate(async () => {
        await confirmOnce(`${base}/${preview.kind === "save" ? "save" : "activate"}`, { ...preview.body, preview_sha256: preview.shown.sha256 });
        if (preview.kind === "save") {
          const latest = await managed<S["ProjectConfigurationRead"]>(base); setCas(latest);
        }
        setPreview(undefined); setConfirmed(false);
      })}>{preview.kind === "save" ? t("registry.save") : t("profile.activate")}</button>
    </div>}
  </section>;
}
