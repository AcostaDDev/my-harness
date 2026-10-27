import { useEffect, useRef, useState } from "react";
import { useI18n } from "./Language";
import { managed } from "./managed-api";
import type { S } from "./managed-api";
import { message } from "./ui";

type Scope = S["PromptDetailRead"]["scope"];
type Detail = S["PromptDetailRead"];

export function Prompts({ project }: { project: string }) {
  const { t } = useI18n();
  const [scope, setScope] = useState<Scope>("project");
  const [name, setName] = useState("execute-task");
  const [names, setNames] = useState<string[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    managed<Detail[]>(`/projects/${project}/prompts`).then(items => {
      if (active) setNames(items.map(item => item.name));
    }).catch(e => { if (active) setError(message(e)); });
    return () => { active = false; };
  }, [project]);
  return <section className="panel" aria-labelledby="prompts-title"><h2 id="prompts-title">{t("prompts.title")}</h2>
    <p className="hint">{t("prompts.hint")}</p>
    {error && <p role="alert" className="state state-error">{error}</p>}
    <div className="form-row">
    <label>{t("prompts.scope")}<select value={scope} onChange={e => setScope(e.target.value as Scope)}>
      <option value="project">{t("prompts.scope.project")}</option><option value="profile">{t("prompts.scope.profile")}</option><option value="core">{t("prompts.scope.core")}</option>
    </select></label>
    <label>{t("prompts.template")}<select value={name} onChange={e => setName(e.target.value)}>{names.map(n => <option key={n}>{n}</option>)}</select></label>
    </div>
    <Editor key={`${project}:${scope}:${name}`} project={project} scope={scope} name={name} />
  </section>;
}

function Editor({ project, scope, name }: { project: string; scope: Scope; name: string }) {
  const { t } = useI18n();
  const base = `/projects/${project}/prompts/${name}`;
  const [detail, setDetail] = useState<Detail>();
  const [selected, setSelected] = useState("");
  const [before, setBefore] = useState("");
  const [text, setText] = useState("");
  const [diff, setDiff] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const guard = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    managed<Detail>(`${base}?scope=${scope}`).then(d => {
      if (alive.current) { setDetail(d); setSelected(d.effective.id); setBefore(d.effective.id); setText(d.effective.template); }
    }).catch(e => { if (alive.current) setError(message(e)); });
    return () => { alive.current = false; };
  }, [base, scope]);
  useEffect(() => { setConfirmed(false); setDiff(""); setStatus(""); }, [selected, before, text, detail?.generation]);
  const version = detail?.versions.find(v => v.id === selected);
  const flowHelp = name === "bootstrap-project" ? t("prompts.flow.bootstrap")
    : name === "reconcile-phase" ? t("prompts.flow.reconcile")
      : name === "close-phase" ? t("prompts.flow.close") : "";
  async function operate(action: () => Promise<void>) {
    if (guard.current) return;
    guard.current = true; setBusy(true); setError("");
    try { await action(); }
    catch (e) { if (alive.current) setError(message(e)); }
    finally { guard.current = false; if (alive.current) setBusy(false); }
  }
  async function reload() {
    const d = await managed<Detail>(`${base}?scope=${scope}`);
    if (alive.current) { setDetail(d); setConfirmed(false); }
    return d;
  }
  async function draft(rollback: boolean) {
    if (!detail) return;
    const body: S["PromptDraftCreate"] = { expected_version: detail.generation,
      ...(rollback ? { from_version: selected } : { template: text }) };
    const v = await managed<S["PromptVersionRead"]>(`${base}/versions?scope=${scope}`, body);
    await reload();
    if (alive.current) { setSelected(v.id); setText(v.template); }
  }
  return <section>
    {flowHelp && <p>{flowHelp} {t("prompts.flow.activation")}</p>}
    {scope !== "project" && <p>{scope === "core" ? t("prompts.inherit.core") : t("prompts.inherit.profile")}</p>}
    {error && <p role="alert" className="state state-error">{error}</p>}
    {status && <p role="status" className="state state-ok">{status}</p>}
    {detail && <>
      <p>{t("prompts.generation", { generation: detail.generation, active: detail.active_id ?? t("prompts.inherited") })}</p>
      <p>{t("prompts.effective", { scope: detail.effective.scope, id: detail.effective.id })}</p>
      <p>{t("prompts.variables", { variables: detail.variables.map(v => `{{${v}}}`).join(", ") })}</p>
      <label>{t("prompts.selected")}<select disabled={busy} value={selected} onChange={e => {
        const v = detail.versions.find(v => v.id === e.target.value)!; setSelected(v.id); setText(v.template);
      }}>{detail.versions.map(v => <option key={v.id} value={v.id}>{v.id === detail.active_id ? t("prompts.version.active", { scope: v.scope, id: v.id }) : `${v.scope} · ${v.id}`}</option>)}</select></label>
      <p>{t("prompts.provenance", { source: version?.source ?? "", sha: version?.sha256 ?? "" })}</p>
      <label>{t("prompts.draft")}<textarea rows={16} disabled={busy} value={text} onChange={e => setText(e.target.value)} maxLength={100000} /></label>
      <div className="actions">
        <button disabled={busy} onClick={() => void operate(async () => {
          await managed<S["PromptValidationRead"]>(`${base}/validate`, { template: text } satisfies S["PromptValidateCreate"]);
          if (alive.current) setStatus(t("prompts.valid"));
        })}>{t("prompts.validate")}</button>
        <button disabled={busy} onClick={() => void operate(() => draft(false))}>{t("prompts.save_draft")}</button>
        <button disabled={busy || !version} onClick={() => void operate(() => draft(true))}>{t("prompts.rollback")}</button>
        <button disabled={busy} onClick={() => void operate(async () => { await reload(); })}>{t("prompts.reload")}</button>
      </div>
      <label>{t("prompts.compare_from")}<select disabled={busy} value={before} onChange={e => setBefore(e.target.value)}>
        {detail.versions.map(v => <option key={v.id} value={v.id}>{v.scope} · {v.id}</option>)}
      </select></label>
      <button disabled={busy || !version} onClick={() => void operate(async () => {
        const d = await managed<S["PromptDiffRead"]>(`${base}/diff?before=${encodeURIComponent(before)}&after=${encodeURIComponent(selected)}`);
        if (alive.current) setDiff(d.diff || t("prompts.no_diff"));
      })}>{t("prompts.compare")}</button>
      {diff && <pre className="diff" aria-label={t("prompts.diff")}>{diff}</pre>}
      <label>{t("prompts.reason")}<input disabled={busy} value={reason} onChange={e => setReason(e.target.value)} maxLength={2000} /></label>
      <label className="check"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
        {t("prompts.confirm", { scope })}</label>
      <button className="button-primary" disabled={busy || !confirmed || !reason.trim() || version?.scope !== scope || version?.owner !== detail.owner || selected.startsWith("builtin-") || text !== version?.template}
        onClick={() => void operate(async () => {
          const body: S["PromptActivateCreate"] = { expected_version: detail.generation, version_id: selected, reason, confirmed: true };
          const d = await managed<Detail>(`${base}/activate?scope=${scope}`, body);
          if (alive.current) { setDetail(d); setConfirmed(false); setReason(""); }
        })}>{t("prompts.activate")}</button>
      <details className="evidence"><summary>{t("prompts.history")}</summary><pre>{JSON.stringify(detail.activations, null, 2)}</pre></details>
    </>}
  </section>;
}
