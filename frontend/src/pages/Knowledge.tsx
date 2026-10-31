import { useEffect, useRef, useState } from "react";
import { useI18n } from "../Language";
import { managed, confirmOnce, readConfirmation } from "../managed-api";
import type { S } from "../managed-api";
import { Link } from "../navigation";
import { Alert, Loading, when, message } from "../ui";
import { knowledgeLabel } from "../knowledge-labels";
import { RichMarkdown } from "./Docs";

type Member = S["KnowledgeMember"];
type Relation = S["KnowledgeLinkRead"];
type Manifest = { members: Member[]; links: Relation[] };
type Revision = S["KnowledgeRevisionSummary"] & { actor: unknown; reason: string | null };
type Inspection = Manifest & { revision: Revision; contexts: { invocation_id: string; attempt_id: string; operation_id: string; run_id: string }[]; contexts_truncated: boolean };
type History = { revisions: Revision[]; drafts: { id: string; created_at: string }[]; total: number };
type Preview = S["KnowledgePreviewRead"] & { impact: Pick<Inspection, "contexts" | "contexts_truncated">; comparison: { items: { before: Member | null; after: Member | null }[]; added_links: Relation[]; removed_links: Relation[] } };
const kinds = ["requirement", "criterion", "phase", "task", "decision", "section"] as const;
const documents = ["specification", "architecture", "data_model", "flows", "instructions"] as const;
const fields: Record<string, string[]> = {
  requirement: ["title", "statement"], criterion: ["statement"], phase: ["title", "objective", "tag"],
  task: ["title", "problem", "expected_result", "evidence", "subtasks"],
  decision: ["title", "context", "decision", "alternatives", "consequences"], section: ["title", "body"],
};
const statuses: Record<string, string[]> = { requirement: ["active", "retired"], criterion: ["active", "retired"],
  phase: ["planned", "withdrawn"], task: ["planned", "withdrawn"], decision: ["accepted", "rejected", "proposed"], section: ["active", "retired"] };
function initial(kind: string): Record<string, unknown> {
  return { ...Object.fromEntries(fields[kind].map(f => [f, f === "subtasks" ? [] : f === "tag" ? null : ""])),
    status: statuses[kind][0], ...(kind === "section" ? { format: "markdown", target: "agents" } : {}),
    ...(kind === "decision" ? { historical_status: null } : {}) };
}

export function KnowledgePage({ project }: { project?: string }) {
  const { t } = useI18n();
  const text = (group: string, value: unknown) => knowledgeLabel(t, group, value);
  const [projects, setProjects] = useState<S["KnowledgeProjectRead"][]>([]);
  const [projectOffset, setProjectOffset] = useState(0);
  const [id, setId] = useState("");
  const viewId = useRef(id);
  viewId.current = id;
  const [boundId, setBoundId] = useState("");
  const generation = useRef(0);
  const [head, setHead] = useState<S["KnowledgeRevisionSummary"] | null>(null);
  const [rulings, setRulings] = useState<S["JudgeRequestRead"][]>([]);
  const [history, setHistory] = useState<History>();
  const [offset, setOffset] = useState(0);
  const [inspection, setInspection] = useState<Inspection>();
  const [draft, setDraft] = useState<S["KnowledgeDraftRead"]>();
  const [preview, setPreview] = useState<Preview>();
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);
  const [loading, setLoading] = useState(false);
  const busy = working || loading;
  const searchGeneration = useRef(0);
  const lock = useRef(false);
  const [reason, setReason] = useState("");
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<string[]>();
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState<Member>();
  const [kind, setKind] = useState<string>("requirement");
  const [code, setCode] = useState("");
  const [document, setDocument] = useState<string>("specification");
  const [content, setContent] = useState<Record<string, unknown>>(initial("requirement"));
  const [position, setPosition] = useState("");
  const [relationKind, setRelationKind] = useState<Relation["kind"]>("part_of");
  const [source, setSource] = useState(""); const [target, setTarget] = useState("");
  const [order, setOrder] = useState("0"); const [qualifier, setQualifier] = useState<"full" | "partial">("full");
  const base = `/knowledge/projects/${encodeURIComponent(id)}`;
  const writeBase = `/projects/${encodeURIComponent(project ?? "")}/knowledge/drafts`;
  const writable = !!project && id === boundId;
  async function act(action: () => Promise<void>) {
    if (lock.current) return;
    const actingProject = id;
    lock.current = true; setWorking(true); setError("");
    try { await action(); } catch (e) { if (viewId.current === actingProject) { setError(message(e)); setPreview(undefined); } }
    finally { lock.current = false; setWorking(false); }
  }
  function resetSearch() {
    ++searchGeneration.current; setMatches(undefined); setCursor(undefined);
  }
  // Initial load and explicit recovery share the same path, including project resolution.
  // A newer read owns all results; late reads never mix one selection with another.
  async function refresh() {
    const ticket = ++generation.current;
    resetSearch(); setPreview(undefined); setLoading(true); setError("");
    try {
      const p = await managed<S["KnowledgeProjectsRead"]>(`/knowledge/projects?offset=${projectOffset}`);
      const h = project ? await managed<S["KnowledgeHeadRead"]>(`/projects/${encodeURIComponent(project)}/knowledge`) : undefined;
      const knowledgeId = h?.knowledge_project_id ?? (project ? "" : id);
      const b = `/knowledge/projects/${encodeURIComponent(knowledgeId)}`;
      const head = h ?? (knowledgeId ? await managed<S["KnowledgeHeadRead"]>(b) : undefined);
      const [hist, rulings, inspected] = knowledgeId ? await Promise.all([
        managed<History>(`${b}/history?offset=${offset}`),
        managed<S["JudgeRequestsRead"]>(`${b}/judge/requests?offset=${offset}`),
        head?.revision ? managed<Inspection>(`${b}/revisions/${head.revision.number}`) : Promise.resolve(undefined),
      ]) : [undefined, undefined, undefined];
      if (ticket !== generation.current) return;
      setProjects(p.items);
      if (project) { setBoundId(knowledgeId); setId(knowledgeId); }
      setHead(head?.revision ?? null); setHistory(hist); setRulings(rulings?.items ?? []); setInspection(inspected);
    } catch (e) { if (ticket === generation.current) setError(message(e)); }
    finally { if (ticket === generation.current) setLoading(false); }
  }
  useEffect(() => {
    setPreview(undefined); void refresh();
    return () => { ++generation.current; ++searchGeneration.current; };
  }, [project, projectOffset, id, offset]);
  const inputKey = `knowledge-input-v1/${project ?? "read"}`;
  useEffect(() => {
    if (!project) return;
    try {
      const saved = JSON.parse(sessionStorage.getItem(inputKey) ?? "null");
      if (saved) { setCode(saved.code); setKind(saved.kind); setContent(saved.content); setDocument(saved.document); setPosition(saved.position); setSelected(saved.selected); }
    } catch { /* Corrupt local input never changes canonical records. */ }
  }, [inputKey]);
  useEffect(() => {
    setPreview(undefined);
    if (project) { try { sessionStorage.setItem(inputKey, JSON.stringify({ code, kind, content, document, position, selected })); } catch { /* Editing remains available without browser persistence. */ } }
  }, [content, code, kind, document, position, source, target, relationKind, order, qualifier]);
  function edit(m?: Member) {
    setSelected(m); setKind(m?.kind ?? "requirement"); setCode(m?.code ?? "");
    setContent(m?.content ?? initial("requirement")); setDocument(m?.document ?? "specification");
    setPosition(m?.root_position == null ? "" : String(m.root_position)); setPreview(undefined);
  }
  async function loadDraft(d: string) {
    const ticket = ++generation.current; resetSearch();
    const loaded = await managed<S["KnowledgeDraftRead"]>(`${base}/drafts/${encodeURIComponent(d)}`);
    if (ticket === generation.current) { setDraft(loaded); setPreview(undefined); }
  }
  async function change(changes: S["KnowledgeDraftChangesCreate"]["changes"]) {
    if (!draft) return;
    setPreview(undefined);
    await confirmOnce(`${writeBase}/${draft.draft_id}/changes`, { expected_draft_sha256: draft.draft_sha256, changes });
    await loadDraft(draft.draft_id);
  }
  function memberView(m: Member, previewSide?: string) {
    return <article id={previewSide ? undefined : `item-${m.item_id}`} key={m.item_id} className="panel"><h3>{m.code} — {String(m.content.title ?? "")}</h3>
      <p>{text("kind", m.kind)} · {text("document", m.document)} · {text("target", m.content.target)} · {text("format", m.content.format)} · {text("status", m.content.status)} · {text("provenance", m.provenance)} · v{m.version} · {m.root_position}</p>
      {m.kind === "decision" && !previewSide && <p>{(draft ?? inspection)?.links.some(l => l.kind === "supersedes" && l.target_item_id === m.item_id) ? t((draft ?? inspection)?.links.some(l => l.kind === "supersedes" && l.target_item_id === m.item_id && l.qualifier === "full") ? "knowledge.superseded" : "knowledge.partially_superseded") : ""} · {(draft ?? inspection)?.links.filter(l => l.kind === "supersedes" && l.target_item_id === m.item_id).map(l => `${text("qualifier", l.qualifier)}: ${label(l.source_item_id)}`).join(" · ")}</p>}
      {Object.entries(m.content).filter(([f]) => !["title", "status", "format", "target"].includes(f)).map(([f, value]) => <section key={f}><h4>{text("field", f)}</h4>
        <RichMarkdown source={m.content.format === "mermaid" && f === "body" ? `\u0060\u0060\u0060mermaid\n${value}\n\u0060\u0060\u0060` : Array.isArray(value) ? value.join("\n") : String(value ?? "")} /></section>)}
      {m.source && <p>{Object.entries(m.source).map(([k, v]) => `${text("field", k)}: ${v}`).join(" · ")}</p>}
      {draft && writable && !previewSide && !(m.kind === "decision" && inspection?.members.some(old => old.item_id === m.item_id && old.content.status !== "proposed")) && <button disabled={busy} onClick={() => edit(m)}>{t("knowledge.edit")}</button>}
    </article>;
  }
  const manifest = draft ?? inspection;
  const savedInput = draft?.members.find(m => m.kind === kind && m.code === code && m.document === (kind === "section" ? document : null));
  const dirtyInput = !!code && (!savedInput || Object.keys(content).some(key => JSON.stringify(savedInput.content[key]) !== JSON.stringify(content[key]))
    || savedInput.root_position !== (kind === "section" && position !== "" ? Number(position) : null));
  function label(item: string) { return manifest?.members.find(m => m.item_id === item)?.code ?? item; }
  function relation(l: Relation) { return <p key={`${l.kind}/${l.source_item_id}/${l.target_item_id}`}><a href={`#item-${l.source_item_id}`}>{label(l.source_item_id)}</a> → {text("relation", l.kind)} → <a href={`#item-${l.target_item_id}`}>{label(l.target_item_id)}</a> {l.position} {text("qualifier", l.qualifier)}</p>; }
  return <main><h1 id="page-title" tabIndex={-1}>{t("knowledge.title")}</h1><p>{t("knowledge.lede")}</p>
    {error && <Alert>{error}<p>{t("knowledge.conflict")}</p></Alert>}{busy && <Loading />}
    <button disabled={busy} onClick={() => void act(() => refresh())}>{t("knowledge.reload")}</button>
    {!project && <label>{t("knowledge.project")}<select value={id} onChange={e => { ++generation.current; resetSearch(); setDraft(undefined); setInspection(undefined); setHistory(undefined); setHead(null); setRulings([]); setOffset(0); setId(e.target.value); }}><option value="">—</option>{projects.map(p => <option key={p.id} value={p.id}>{p.root}</option>)}</select></label>}
    {!project && <><button aria-label={t("common.previous_page")} disabled={!projectOffset || busy} onClick={() => setProjectOffset(n => n - 50)}>←</button><button aria-label={t("common.next_page")} disabled={projects.length < 50 || busy} onClick={() => setProjectOffset(n => n + 50)}>→</button></>}
    {!head && <p>{t("knowledge.absent")}</p>}
    {id && <section><h2>{t("knowledge.history")}</h2>{history?.revisions.map(r => <button key={r.id} disabled={busy} onClick={() => void act(async () => {
      const ticket = ++generation.current; resetSearch(); setDraft(undefined); setPreview(undefined);
      const loaded = await managed<Inspection>(`${base}/revisions/${r.number}`);
      if (ticket === generation.current) setInspection(loaded);
    })}>#{r.number} · {when(r.accepted_at)} · {text("origin", r.origin)}</button>)}
      <button aria-label={t("common.previous_page")} disabled={!offset || busy} onClick={() => setOffset(n => n - 50)}>←</button><button aria-label={t("common.next_page")} disabled={busy || (history?.revisions.length ?? 0) < 50 && (history?.drafts.length ?? 0) < 50} onClick={() => setOffset(n => n + 50)}>→</button>
      {history?.drafts.map(d => <button disabled={busy} key={d.id} onClick={() => void act(() => loadDraft(d.id))}>{t("knowledge.draft")} · {when(d.created_at)} · {d.id.slice(0, 8)}</button>)}
    </section>}
    {inspection && !draft && <><p>#{inspection.revision.number} · {when(inspection.revision.accepted_at)} · {text("origin", inspection.revision.origin)} · {inspection.revision.reason}</p>
      <p>{Object.entries(inspection.revision.actor ?? {}).map(([k,v]) => `${text("field", k)}: ${v}`).join(" · ")}</p>
      <form onSubmit={e => { e.preventDefault(); void act(async () => {
        const ticket = ++searchGeneration.current;
        try {
        const result = await managed<{ exposures: { identity: { item_id: string } }[]; page: { next_cursor?: string } }>(`${base}/revisions/${inspection.revision.number}/search?query=${encodeURIComponent(query)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
        if (ticket !== searchGeneration.current) return;
        setMatches(result.exposures.map(e => e.identity.item_id)); setCursor(result.page.next_cursor);
        } catch (e) { if (ticket === searchGeneration.current) throw e; }
      }); }}><label>{t("knowledge.search")}<input maxLength={200} value={query} onChange={e => { resetSearch(); setQuery(e.target.value); }} /></label><button disabled={busy || !query}>{t(cursor ? "knowledge.more" : "knowledge.search")}</button></form></>}
    {writable && !draft && <button disabled={busy} onClick={() => void act(async () => {
      const opened = await confirmOnce<S["KnowledgeDraftOpenRead"]>(writeBase, { expected_revision_id: head?.id ?? null });
      setBoundId(opened.knowledge_project_id); setId(opened.knowledge_project_id); setDraft(await managed<S["KnowledgeDraftRead"]>(`/knowledge/projects/${opened.knowledge_project_id}/drafts/${opened.draft_id}`));
    })}>{t("knowledge.open")}</button>}
    {draft && <p role="status">{t("knowledge.draft")} · {text("status", draft.status)} · {draft.draft_id} · {draft.base_revision_id ?? "—"}</p>}
    {manifest?.members.filter(m => draft || !matches || matches.includes(m.item_id)).map(m => memberView(m))}
    {manifest && <section><h2>{t("knowledge.relations")}</h2>{manifest.links.map(relation)}</section>}
    {draft && writable && <fieldset disabled={busy}><legend>{t("knowledge.draft")}</legend>
      <button onClick={() => void act(() => loadDraft(draft.draft_id))}>{t("knowledge.reload_draft")}</button>
      <button onClick={() => void act(async () => { await confirmOnce(`${writeBase}/${draft.draft_id}/discard`, {}); setDraft(undefined); setPreview(undefined); await refresh(); })}>{t("knowledge.discard")}</button>
      <button onClick={() => edit()}>{t("knowledge.new")}</button>
      <label>{t("knowledge.kind")}<select value={kind} disabled={!!selected} onChange={e => { setKind(e.target.value); setContent(initial(e.target.value)); }}>{kinds.map(k => <option key={k} value={k}>{text("kind", k)}</option>)}</select></label>
      <label>{t("knowledge.code")}<input value={code} disabled={!!selected} onChange={e => setCode(e.target.value)} /></label>
      {kind === "section" && <><label>{t("knowledge.document")}<select value={document} disabled={!!selected} onChange={e => setDocument(e.target.value)}>{documents.map(d => <option key={d} value={d}>{text("document", d)}</option>)}</select></label>
        <label>{t("knowledge.format")}<select value={String(content.format)} onChange={e => setContent({ ...content, format: e.target.value })}><option value="markdown">{text("format", "markdown")}</option><option value="mermaid">{text("format", "mermaid")}</option></select></label>
        <label>{t("knowledge.target")}<select value={String(content.target)} onChange={e => setContent({ ...content, target: e.target.value })}>{(document === "instructions" ? ["agents", "claude", "gemini"] : ["agents"]).map(v => <option key={v} value={v}>{text("target", v)}</option>)}</select></label>
        <label>{t("knowledge.position")}<input type="number" min="0" value={position} onChange={e => setPosition(e.target.value)} /></label></>}
      {fields[kind].map(f => <label key={f}>{text("field", f)}<textarea value={Array.isArray(content[f]) ? (content[f] as string[]).join("\n") : String(content[f] ?? "")} onChange={e => { setPreview(undefined); setContent(current => ({ ...current, [f]: f === "subtasks" ? e.target.value.split("\n") : f === "tag" && !e.target.value ? null : e.target.value })); }} /></label>)}
      <label>{t("knowledge.status")}<select value={String(content.status)} onChange={e => setContent({ ...content, status: e.target.value })}>{statuses[kind].map(s => <option key={s} value={s}>{text("status", s)}</option>)}</select></label>
      <button disabled={!code} onClick={() => void act(() => change([{ op: "put", kind: kind as Member["kind"], code, content, document: kind === "section" ? document as Member["document"] : null,
        provenance: selected?.provenance ?? "known", source: selected?.source ?? null, root_position: kind === "section" && position !== "" ? Number(position) : null }]))}>{t("knowledge.save")}</button>
      {selected && <button onClick={() => void act(() => change([{ op: "remove", item_id: selected.item_id }]))}>{t("knowledge.remove")}</button>}
      <h2>{t("knowledge.relations")}</h2><label>{t("knowledge.kind")}<select value={relationKind} onChange={e => setRelationKind(e.target.value as Relation["kind"])}>{["part_of", "criterion_of", "depends_on", "addresses", "supersedes"].map(v => <option key={v} value={v}>{text("relation", v)}</option>)}</select></label>
      {[{ value: source, set: setSource, key: "knowledge.source" as const }, { value: target, set: setTarget, key: "knowledge.target" as const }].map(s => <label key={s.key}>{t(s.key)}<select value={s.value} onChange={e => s.set(e.target.value)}><option value="">—</option>{draft.members.map(m => <option key={m.item_id} value={m.item_id}>{m.code} · {text("document", m.document)}</option>)}</select></label>)}
      <label>{t("knowledge.position")}<input type="number" min="0" value={order} onChange={e => setOrder(e.target.value)} /></label>
      {relationKind === "supersedes" && <label>{t("knowledge.supersession")}<select value={qualifier} onChange={e => setQualifier(e.target.value as "full" | "partial")}><option value="full">{text("qualifier", "full")}</option><option value="partial">{text("qualifier", "partial")}</option></select></label>}
      <button disabled={!source || !target} onClick={() => void act(() => change([{ op: "link", kind: relationKind, source_item_id: source, target_item_id: target,
        position: ["part_of", "criterion_of"].includes(relationKind) ? Number(order) : null, qualifier: relationKind === "supersedes" ? qualifier : null }]))}>{t("knowledge.link")}</button>
      <button disabled={!source || !target} onClick={() => void act(() => change([{ op: "unlink", kind: relationKind, source_item_id: source, target_item_id: target }]))}>{t("knowledge.unlink")}</button>
      <p>{dirtyInput ? t("knowledge.unsaved") : ""}</p>
      <button disabled={dirtyInput} onClick={() => void act(async () => { setPreview(await managed<Preview>(`${writeBase}/${draft.draft_id}/adoption/preview`, {})); })}>{t("knowledge.preview")}</button>
    </fieldset>}
    {preview && draft && writable && <section><h2>{t("knowledge.preview")}</h2>
      {preview.classification.map((c, i) => <p key={i}>{c.code} · {text("change", c.change)} · {text("class", c.class)} · {c.sensitive ? t("knowledge.sensitive") : ""}</p>)}
      {preview.comparison.items.map((c, i) => <section key={i}><h3>{t("knowledge.before")}</h3>{c.before ? memberView(c.before, "before") : "—"}<h3>{t("knowledge.after")}</h3>{c.after ? memberView(c.after, "after") : "—"}</section>)}
      <h3>{t("knowledge.before")}</h3>{preview.comparison.removed_links.map(relation)}<h3>{t("knowledge.after")}</h3>{preview.comparison.added_links.map(relation)}
      <p>{t("knowledge.impact")}</p>{preview.impact?.contexts.map(c => <p key={c.invocation_id}>{c.attempt_id} · <Link to={{ name: "run-short", run: c.run_id }}>{c.run_id}</Link></p>)}<p>{t("knowledge.unassociated")}</p>{preview.impact?.contexts_truncated && <p>{t("knowledge.truncated")}</p>}<label>{t("knowledge.reason")}<textarea maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button disabled={busy || preview.reason_required && !reason.trim()} onClick={() => void act(async () => {
        await confirmOnce(`${writeBase}/${draft.draft_id}/adopt`, { expected_revision_id: preview.base_revision_id, preview_sha256: preview.preview_sha256, reason });
        setDraft(undefined); setPreview(undefined); await refresh();
      })}>{t("knowledge.adopt")}</button>
    </section>}
    {project && readConfirmation()?.path.startsWith(writeBase) && <button disabled={busy} onClick={() => void act(async () => {
      const pending = readConfirmation()!; const result = await confirmOnce<S["KnowledgeDraftOpenRead"]>(pending.path, pending.body);
      if (result.knowledge_project_id) { setBoundId(result.knowledge_project_id); setId(result.knowledge_project_id); }
      if (pending.path.endsWith("/adopt") || pending.path.endsWith("/discard")) setDraft(undefined);
      else if (result.draft_id) setDraft(await managed<S["KnowledgeDraftRead"]>(`/knowledge/projects/${result.knowledge_project_id ?? id}/drafts/${result.draft_id}`));
      setPreview(undefined); await refresh();
    })}>{t("knowledge.retry")}</button>}
    {rulings.length > 0 && <section><h2>{t("knowledge.rulings")}</h2>{rulings.map(r => <article key={r.id}><h3>{r.duty} · {r.id}</h3><p>{r.ruling?.status as string} · {r.continuation}</p><RichMarkdown source={String((r.ruling?.candidate as { rationale?: string } | undefined)?.rationale ?? r.ruling?.reason ?? "")} />{r.decision_links.map((l, i) => <p key={i}>{manifest?.members.some(m => m.item_id === l.decision_id) ? <a href={`#item-${l.decision_id}`}>{label(l.decision_id)}</a> : l.decision_id} · {l.revision_id}</p>)}</article>)}</section>}
    {inspection && !draft && <section><h2>{t("knowledge.context")}</h2><p>{t("knowledge.impact")}</p>{inspection.contexts.map(c => <p key={c.invocation_id}>{t("knowledge.invocation")}: {c.invocation_id} · {t("knowledge.attempt")}: {c.attempt_id} · {c.operation_id} · <Link to={{ name: "run-short", run: c.run_id }}>{c.run_id}</Link></p>)}{inspection.contexts_truncated && <p>{t("knowledge.truncated")}</p>}<p>{t("knowledge.unassociated")}</p></section>}
  </main>;
}
