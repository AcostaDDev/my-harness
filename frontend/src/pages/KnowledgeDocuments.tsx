import { useEffect, useRef, useState } from "react";
import { managed, confirmOnce, readConfirmation } from "../managed-api";
import { useI18n } from "../Language";
import { Alert, message } from "../ui";
import { RichMarkdown } from "./Docs";
import { knowledgeLabel } from "../knowledge-labels";

type Member = { root_position?: number | null; item_id: string; code: string; kind: string; content: Record<string, unknown>; provenance?: string; source?: unknown };
type Report = { code: string; detail?: string; blocking: boolean; item?: string; path?: string; report_sha256?: string[] };
type Relation = { kind: string; source_item_id: string; target_item_id: string; position?: number | null; qualifier?: string | null };
type Result = { record_id?: string; draft_id?: string; preview_sha256?: string; base_revision_id?: string | null; revision_id?: string;
  files?: Record<string, string> | null; baseline?: { targets: Record<string, string | null> }; portable?: string | null; render_error?: string | null; portable_error?: string | null; report?: Report[]; members?: Member[];
  mapping?: Record<string, string>; comparison?: { items: { before: Member | null; after: Member | null }[]; added_links: Relation[]; removed_links: Relation[] };
  manifest?: unknown; status?: string; pending?: boolean; outcomes?: unknown[]; ownership_adopted?: boolean; ownership_id?: string; intent?: Result; kind?: string; };
type Choice = { action: string; target: string; code: string };
const paths: Record<string, string> = { "AGENTS.md": "AGENTS.md", "CLAUDE.md": "CLAUDE.md", "GEMINI.md": "GEMINI.md",
  "SPECIFICATION.md": "docs/SPECIFICATION.md", "ARCHITECTURE.md": "docs/ARCHITECTURE.md", "DDBB-DIAGRAM.md": "docs/DDBB-DIAGRAM.md",
  "ROADMAP.md": "docs/ROADMAP.md", "NEXT_STEPS.md": "docs/NEXT_STEPS.md", "DECISIONS.md": "docs/DECISIONS.md", "STATE.md": "docs/STATE.md",
  "knowledge.md": "docs/flows/knowledge.md", "knowledge.json": "docs/.harness/knowledge.json" };

export function KnowledgeDocuments({ project, head, onAdopt, destinations = [] }: { project: string; head: string | null; onAdopt?: () => void; destinations?: Member[] }) {
  const { t } = useI18n();
  const base = `/projects/${encodeURIComponent(project)}/knowledge/documents`;
  const [files, setFiles] = useState<Record<string, string>>({});
  const [portable, setPortable] = useState("");
  const [mode, setMode] = useState(head ? "update" : "new");
  const [preserve, setPreserve] = useState<{ path: string; document: string; code: string }[]>([]);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [acknowledged, setAcknowledged] = useState<string[]>([]);
  const [stage, setStage] = useState<Result>();
  const [preview, setPreview] = useState<Result>();
  const [ownership, setOwnership] = useState<Result>();
  const [exportPreview, setExportPreview] = useState<Result>();
  const [bundle, setBundle] = useState<Result>();
  const [wrappers, setWrappers] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [stopped, setStopped] = useState(false);
  const [record, setRecord] = useState(() => { try { return sessionStorage.getItem(`documents-delivery/${project}`) ?? ""; } catch { return ""; } });
  useEffect(() => { try { if (record) sessionStorage.setItem(`documents-delivery/${project}`, record); } catch { /* Server receipts remain recoverable. */ } }, [project, record]);
  const [recovery, setRecovery] = useState(readConfirmation());
  const lock = useRef(false);
  const generation = useRef(0);
  useEffect(() => { ++generation.current; setMode(head ? "update" : "new"); setPreview(undefined); setStage(undefined); setOwnership(undefined); setExportPreview(undefined); setBundle(undefined); }, [project, head]);
  const invalidate = () => { setPreview(undefined); setStage(undefined); };
  async function act(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); const ticket = generation.current;
    try { await action(); } catch (e) { if (ticket === generation.current) { setError(message(e)); setPreview(undefined); } }
    finally { lock.current = false; setBusy(false); setRecovery(readConfirmation()); }
  }
  async function request(path: string, body?: unknown, confirm = false): Promise<Result> {
    const ticket = generation.current;
    const response = confirm ? await confirmOnce<{ result: Result }>(base + path, body) : await managed<{ result: Result }>(base + path, body);
    if (ticket !== generation.current) throw new Error(t("documents.changed"));
    return response.result;
  }
  function download(name: string, text: string) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url);
  }
  function member(m: Member | null) {
    return m ? <article className="panel"><h4>{m.code} · {String(m.content.title ?? "")}</h4>{m.root_position != null && <p>{t("knowledge.position")}: {m.root_position}</p>}
      {Object.entries(m.content).map(([key, value]) => <div key={key}><strong>{knowledgeLabel(t, "field", key)}</strong>
        {typeof value === "string" ? <><RichMarkdown source={value} /><pre>{value}</pre></> : <p>{Array.isArray(value) ? value.join("\n") : String(value ?? "—")}</p>}</div>)}
      <p>{knowledgeLabel(t, "provenance", m.provenance)}</p><pre>{JSON.stringify(m.source)}</pre></article> : <p>—</p>;
  }
  function reportText(code: string) {
    const keys = { retained_unselected: "documents.retained", import_directive: "documents.directive", heading_level: "documents.headings", heading_normalized: "documents.headings", source_language_differs: "documents.language_differs", source_version_differs: "documents.version_differs", identity_choice_required: "documents.identity", report_acknowledgement_required: "documents.acknowledge", uncontained_or_changed_decoration: "documents.uncontained", explicit_exclusion: "documents.exclusion", document_preserved_as_section: "documents.preserved", instruction_identity_mapping: "documents.identity", input_invalid: "documents.invalid" } as const;
    return t(keys[code as keyof typeof keys] ?? "documents.invalid");
  }
  const memberLabel = (ident: string) => {
    const found = [...(stage?.members ?? []), ...destinations, ...(preview?.comparison?.items.flatMap(item => item.after ? [item.after] : []) ?? [])].find(m => m.item_id === ident);
    return found ? `${found.code} · ${String(found.content.title ?? found.content.statement ?? "")}` : ident;
  };
  const relation = (r: Relation, i: number) => <p key={i}>{memberLabel(r.source_item_id)} → {knowledgeLabel(t, "relation", r.kind)} → {memberLabel(r.target_item_id)} {r.position ?? ""} {r.qualifier ? knowledgeLabel(t, "qualifier", r.qualifier) : ""}</p>;
  const consent = (value: Result) => ({ record_id: value.record_id, preview_sha256: value.preview_sha256,
    expected_revision_id: value.base_revision_id ?? value.revision_id ?? null, reason });
  return <section className="panel"><h2>{t("documents.title")}</h2><p>{t("documents.lede")}</p>
    {error && <Alert>{error}</Alert>}{status && <p role="status">{status}</p>}
    <label>{t("documents.select")}<input type="file" multiple disabled={busy} accept=".md,.json" onChange={e => {
      const selected = [...(e.target.files ?? [])]; invalidate(); setAcknowledged([]); setChoices({}); setPreserve([]);
      void act(async () => {
        const captured: Record<string, string> = {}; let transfer = "";
        if (selected.reduce((sum, f) => sum + f.size, 0) > 4 * 1024 * 1024) throw new Error(t("documents.size"));
        for (const f of selected) {
          const text = new TextDecoder("utf-8", { fatal: true }).decode(await f.arrayBuffer());
          if (!paths[f.name] && f.name.endsWith(".json")) { if (transfer) throw new Error(t("documents.duplicate")); transfer = text; }
          else { const path = paths[f.name]; if (!path || path in captured) throw new Error(t("documents.duplicate")); captured[path] = text; }
        }
        setFiles(captured); setPortable(transfer);
      });
    }} /></label>
    <label>{t("documents.mode")}<select value={mode} disabled={busy} onChange={e => { setMode(e.target.value); invalidate(); }}>
      <option value="update">{t("documents.update")}</option><option value="new">{t("documents.new")}</option></select></label>
    <button disabled={busy || !portable && !Object.keys(files).length} onClick={() => void act(async () => {
      setPreview(undefined); setStage(await request("/stage", { payload: JSON.stringify({ files, portable, mode, choices, acknowledged, preserve, expected_revision_id: head }) }, true));
    })}>{t("documents.stage")}</button>
    {Object.keys(files).filter(path => path.endsWith(".md")).map(path => <fieldset key={path}>
      <label><input type="checkbox" disabled={busy} checked={preserve.some(r => r.path === path)} onChange={e => { invalidate(); setAcknowledged([]); setPreserve(e.target.checked ? [...preserve, { path, document: "architecture", code: "imported-document" }] : preserve.filter(r => r.path !== path)); }} />{t("documents.preserve")} · {path}</label>
      {preserve.some(r => r.path === path) && <><label>{t("documents.logical_document")}<select disabled={busy} value={preserve.find(r => r.path === path)!.document} onChange={e => { invalidate(); setPreserve(preserve.map(r => r.path === path ? { ...r, document: e.target.value } : r)); }}>
        {["specification", "architecture", "data_model", "flows"].map(d => <option key={d} value={d}>{knowledgeLabel(t, "document", d)}</option>)}</select></label>
        <label>{t("documents.code")}<input disabled={busy} value={preserve.find(r => r.path === path)!.code} onChange={e => { invalidate(); setPreserve(preserve.map(r => r.path === path ? { ...r, code: e.target.value } : r)); }} /></label></>}
    </fieldset>)}
    {stage?.report?.map((r, i) => <p key={i} role={r.blocking ? "alert" : undefined}>{t("documents.report")} · {reportText(r.code)} · {r.path ?? r.item ?? ""}</p>)}
    {stage?.report?.filter(r => r.code === "identity_choice_required").map(r => <fieldset key={r.item}><legend>{memberLabel(r.item!)}</legend>
      <label>{t("documents.identity")}<select disabled={busy} value={choices[r.item!]?.action ?? ""} onChange={e => {
        setPreview(undefined); setChoices({ ...choices, [r.item!]: { action: e.target.value, code: stage.members?.find(m => m.item_id === r.item)?.code ?? "", target: "" } });
      }}><option value="">—</option><option value="create">{t("documents.create")}</option><option value="map">{t("documents.map")}</option><option value="exclude">{t("documents.exclude")}</option></select></label>
      {choices[r.item!]?.action === "map" && <label>{t("documents.destination")}<select disabled={busy} value={choices[r.item!].target} onChange={e => { setPreview(undefined); setChoices({ ...choices, [r.item!]: { ...choices[r.item!], target: e.target.value } }); }}><option value="">—</option>{destinations.filter(m => m.kind === stage.members?.find(s => s.item_id === r.item)?.kind).map(m => <option key={m.item_id} value={m.item_id}>{memberLabel(m.item_id)}</option>)}</select></label>}
      {choices[r.item!]?.action === "create" && <label>{t("documents.code")}<input disabled={busy} value={choices[r.item!].code} onChange={e => { setPreview(undefined); setChoices({ ...choices, [r.item!]: { ...choices[r.item!], code: e.target.value } }); }} /></label>}
    </fieldset>)}
    {stage?.report?.filter(r => r.code === "report_acknowledgement_required").flatMap(r => r.report_sha256 ?? []).map(hash => <label key={hash}>
      <input type="checkbox" disabled={busy} checked={acknowledged.includes(hash)} onChange={e => { setPreview(undefined); setAcknowledged(e.target.checked ? [...acknowledged, hash] : acknowledged.filter(h => h !== hash)); }} />{t("documents.acknowledge")} · {hash.slice(0, 12)}</label>)}
    {stage?.draft_id && <button disabled={busy} onClick={() => void act(async () => setPreview(await request("/preview", { record_id: stage.record_id })))}>{t("documents.preview")}</button>}
    {preview && <section><h3>{t("documents.preview")}</h3>{preview.comparison?.items.map((item, i) => <section key={i}><h4>{t("knowledge.before")}</h4>{member(item.before)}<h4>{t("knowledge.after")}</h4>{member(item.after)}</section>)}
      <p>{t("documents.relations")}</p><p>{t("knowledge.after")}</p>{preview.comparison?.added_links.map(relation)}<p>{t("knowledge.before")}</p>{preview.comparison?.removed_links.map(relation)}
      <p>{t("documents.mapping")}</p>{Object.entries(preview.mapping ?? {}).map(([from, to]) => <p key={from}>{memberLabel(from)} → {memberLabel(to)}</p>)}
      <button disabled={busy || !reason.trim()} onClick={() => void act(async () => { await request("/adopt", consent(preview), true); setPreview(undefined); setStage(undefined); setStatus(t("documents.adopted")); onAdopt?.(); })}>{t("documents.adopt")}</button></section>}
    <label>{t("intake.reason")}<textarea maxLength={2000} disabled={busy} value={reason} onChange={e => setReason(e.target.value)} /></label>
    {head && <>
      <button disabled={busy} onClick={() => void act(async () => { const result = await request("/bundle"); setBundle(result); if (result.ownership_id) setOwnership({ ownership_id: result.ownership_id }); })}>{t("documents.download")}</button>
      {bundle?.render_error && <Alert>{t("documents.render_unavailable")} · {t(bundle.render_error === "unselected_instruction_wrapper" ? "documents.wrapper_required" : bundle.render_error === "instruction_budget" ? "documents.instruction_budget" : "documents.invalid")}</Alert>}
      {bundle?.portable_error && <Alert>{t("documents.portable_unavailable")}</Alert>}
      {bundle?.files && Object.entries(bundle.files).map(([path, value]) => <button disabled={busy} key={path} onClick={() => download(path.split("/").at(-1)!, value)}>{path}</button>)}
      {bundle?.portable && <button disabled={busy} onClick={() => download("project.harness.json", bundle.portable!)}>{t("documents.portable")}</button>}
      <h3>{t("documents.ownership")}</h3><p>{t("documents.takeover")}</p>
      {["claude", "gemini"].map(w => <label key={w}><input type="checkbox" checked={wrappers.includes(w)} disabled={busy} onChange={e => { setOwnership(undefined); setWrappers(e.target.checked ? [...wrappers, w] : wrappers.filter(v => v !== w)); }} />{w}</label>)}
      <button disabled={busy} onClick={() => void act(async () => setOwnership(await request("/ownership/preview", { wrappers }, true)))}>{t("documents.ownership_preview")}</button>
      {ownership?.files && !ownership.ownership_id && <><details><summary>{t("documents.replacements")}</summary>{Object.entries(ownership.files).map(([path, value]) => <section key={path}><h4>{path}</h4><p>{t("knowledge.before")}</p><pre>{ownership.baseline?.targets[path] ?? "—"}</pre><p>{t("knowledge.after")}</p><pre>{value}</pre></section>)}</details>
        <button disabled={busy || !reason.trim()} onClick={() => void act(async () => { const result = await request("/ownership/adopt", consent(ownership), true); setOwnership({ ...ownership, ownership_id: result.record_id }); })}>{t("documents.own")}</button></>}
      {ownership?.ownership_id && <button disabled={busy} onClick={() => void act(async () => { const result = await request("/export/preview", { record_id: ownership.ownership_id }, true); setExportPreview(result); setRecord(result.record_id!); })}>{t("documents.regenerate")}</button>}
      {exportPreview && <><details><summary>{t("documents.replacements")}</summary>{Object.entries(exportPreview.files ?? {}).map(([path, value]) => <section key={path}><h4>{path}</h4><pre>{value}</pre></section>)}</details>
        <label><input type="checkbox" checked={stopped} disabled={busy} onChange={e => setStopped(e.target.checked)} />{t("documents.stopped")}</label>
        <button disabled={busy} onClick={() => void act(async () => { const result = await request("/export", { record_id: exportPreview.record_id, preview_sha256: exportPreview.preview_sha256, writer_stopped: stopped }, true); setStatus(t(result.status === "COMPLETED" ? "documents.completed" : "documents.pending")); })}>{t("documents.deliver")}</button></>}
    </>}
    <label>{t("documents.record")}<input value={record} onChange={e => setRecord(e.target.value)} /></label>
    <button disabled={busy || !record} onClick={() => void act(async () => { const result = await request(`/records/${encodeURIComponent(record)}`); setStatus(t(result.pending ? "documents.pending" : "documents.completed")); if (result.kind === "export_intent" && result.pending) setExportPreview({ ...result.intent, record_id: record, preview_sha256: result.preview_sha256 }); })}>{t("documents.status")}</button>
    {recovery?.path.startsWith(base + "/") && <button disabled={busy} onClick={() => void act(async () => {
      const result = await confirmOnce<{ result: Result }>(recovery.path, recovery.body);
      setStatus(t("documents.recovered"));
      if (recovery.path.endsWith("/stage")) setStage(result.result);
      else if (recovery.path.endsWith("/ownership/preview")) setOwnership(result.result);
      else if (recovery.path.endsWith("/export/preview")) { setExportPreview(result.result); setRecord(result.result.record_id!); }
      else if (recovery.path.endsWith("/ownership/adopt")) setOwnership({ ownership_id: result.result.record_id });
      else if (recovery.path.endsWith("/adopt")) onAdopt?.();
    })}>{t("documents.recover")}</button>}
  </section>;
}
