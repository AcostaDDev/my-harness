import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { useI18n } from "../Language";
import type { MessageKey, Translate } from "../i18n.ts";
import { jobRequest, managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import { blockBody, decisionHref, renderMarkdown, splitBlocks } from "../markdown.ts";
import type { BlockError, BlockedReason, Segment } from "../markdown.ts";
import { prefersDark, renderDiagram } from "../mermaid-view.ts";
import { Link, navigate } from "../navigation";
import { Alert, DiffBlock, Empty, Fields, Hash, Loading, PageHeader, Stale, Status, message, usePoll } from "../ui";
import type { Poll } from "../ui";
import { useWorkspace } from "../workspace";

// Documentation of a project with the v2 contract (H6.2 E3): tree, safe viewer and confirmed editing (D072 §6).
// Every write is a `document_edit` job on the exact diff shown; nothing is written while typing.

type DocsStatus = S["DocumentsStatusRead"];
type Tree = S["DocumentTreeRead"];
type Preview = S["DocumentEditPreviewRead"];
type PhaseView = { id: string; code: string; status: S["PhaseRead"]["status"] };
/** P010-T005: after closing or abandoning, the reference is what the closure left, not the check base. */
const terminal = (phase: PhaseView | null | undefined) => phase?.status === "CLOSED" || phase?.status === "ABANDONED";
type Draft = { base: string | null; texts: string[]; run?: string };

const q = encodeURIComponent;
const KIND: Record<S["DocumentTreeEntryRead"]["kind"], MessageKey> = {
  instructions: "docs.kind.instructions", diagram: "docs.kind.diagram", flow: "docs.kind.flow", phase_work: "docs.kind.phase_work",
  phase: "docs.kind.phase", product: "docs.kind.product", archive: "docs.kind.archive", other: "docs.kind.other",
};
const BLOCK_LABELS: Record<string, MessageKey> = { state: "docs.block.state", roadmap: "docs.block.roadmap", decisions: "docs.block.decisions" };
const BLOCKED: Record<BlockedReason, MessageKey> = {
  empty: "docs.blocked.empty", no_scheme: "docs.blocked.no_scheme", scheme: "docs.blocked.scheme",
  external_image: "docs.blocked.external_image", encoding: "docs.blocked.encoding", image_path: "docs.blocked.image_path",
  path: "docs.blocked.path", outside: "docs.blocked.outside", image_format: "docs.blocked.image_format",
  not_markdown: "docs.blocked.not_markdown",
};
const BLOCK_ERRORS: Record<BlockError["code"], MessageKey> = {
  incomplete: "docs.markers.incomplete", own_lines: "docs.markers.own_lines", unknown: "docs.markers.unknown", overlap: "docs.markers.overlap",
};
const blockError = (error: BlockError, t: Translate) => t(BLOCK_ERRORS[error.code], { block: error.name ?? "" });

/** Server rule (`Layout.editable`): README or Markdown under the documentation folder, never the archive. */
function editablePath(path: string, docs: string) {
  if (["README.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md"].includes(path)) return true;
  const parts = path.split("/");
  return path.endsWith(".md") && path.startsWith(`${docs}/`) && !path.startsWith(`${docs}/archive/`)
    && !parts.includes("..") && !parts.includes(".") && !parts.includes("");
}

/** Reason why editing from the interface is not possible now; undefined if it is. */
function editBlocker(status: DocsStatus | undefined, t: Translate): string | undefined {
  if (!status) return t("docs.blocker.loading");
  const phase = status.phase as PhaseView | null;
  if (status.git_error) return t("docs.blocker.git");
  if (!phase) return t("docs.blocker.no_phase");
  if (phase.status === "CHECKING") return t("docs.blocker.checking", { phase: phase.code });
  if (phase.status === "CLOSING") return t("docs.blocker.closing", { phase: phase.code });
  if (status.unresolved_intent) return t("docs.blocker.intent");
  if (status.uncommitted?.length) return t("docs.blocker.uncommitted");
  return undefined;
}

export function DocsPage({ path }: { path?: string }) {
  const { t } = useI18n();
  const { project, refresh } = useWorkspace();
  const info = usePoll<S["ManagedProjectRead"]>(`/projects/${project}`, 0);
  const v2 = info.data?.documents === "v2";
  const status = usePoll<DocsStatus>(v2 ? `/projects/${project}/documents` : null, 4000, refresh);
  const tree = usePoll<Tree>(v2 ? `/projects/${project}/documents/tree` : null, 10000, refresh);
  if (!info.data) return info.error ? <Alert>{info.error}</Alert> : <Loading />;
  if (!v2) return <>
    <PageHeader title={t("nav.docs")} />
    <Empty title={t("docs.legacy.title")}>
      <p>{t("docs.legacy.body")}</p>
    </Empty>
  </>;
  return <div className="docs-layout">
    <DocsTree tree={tree.data} status={status.data} current={path} error={tree.error} />
    <div className="docs-main">
      {path ? <DocumentView key={path} path={path} status={status} tree={tree.data} />
        : <DocsOverview status={status} tree={tree.data} />}
    </div>
  </div>;
}

// --- tree ---------------------------------------------------------------------------------------

type Node = { name: string; path: string; children: Map<string, Node>; file?: S["DocumentTreeEntryRead"] };

function buildTree(files: S["DocumentTreeEntryRead"][]): Node {
  const root: Node = { name: "", path: "", children: new Map() };
  for (const file of files) {
    let node = root;
    file.path.split("/").forEach((part, index, parts) => {
      const path = parts.slice(0, index + 1).join("/");
      if (!node.children.has(part)) node.children.set(part, { name: part, path, children: new Map() });
      node = node.children.get(part)!;
      if (index === parts.length - 1) node.file = file;
    });
  }
  return root;
}

function DocsTree({ tree, status, current, error }: { tree?: Tree; status?: DocsStatus; current?: string; error?: string }) {
  const { t, n } = useI18n();
  const { project } = useWorkspace();
  const root = useMemo(() => tree ? buildTree(tree.files) : undefined, [tree]);
  const drift = new Set(status?.documents.filter(d => d.drift).map(d => d.path));
  const local = new Set(status?.uncommitted?.map(c => c.path));
  const missing = status?.documents.filter(d => !d.exists) ?? [];
  function branch(node: Node, depth: number): ReactNode {
    const entries = [...node.children.values()].sort((a, b) => Number(!!b.file && !b.children.size) - Number(!!a.file && !a.children.size) || a.name.localeCompare(b.name));
    return <ul className="docs-tree-list">{entries.map(child => child.file && !child.children.size
      ? <li key={child.path}><Link to={{ name: "docs", project, path: child.path }} current={child.path === current} className="docs-tree-file">
          <span className="docs-tree-name">{child.name}</span>
          {local.has(child.path) && <span className="docs-flag docs-flag-local" title={t("docs.flag.local_hint")}>{t("docs.flag.local")}</span>}
          {drift.has(child.path) && !local.has(child.path) && <span className="docs-flag docs-flag-drift" title={t("docs.flag.drift_hint")}>{t("docs.flag.drift")}</span>}
          {child.file.archived && <span className="docs-flag" title={t("docs.flag.archive_hint")}>{t("docs.flag.archive")}</span>}
        </Link></li>
      : <li key={child.path}><details open={depth < 1 || (!!current && current.startsWith(`${child.path}/`)) || !child.path.includes("archive")}>
          <summary className="docs-tree-folder">{child.name}/</summary>{branch(child, depth + 1)}</details></li>)}</ul>;
  }
  return <nav className="docs-tree" aria-label={t("docs.tree")}>
    <p className="docs-tree-title"><Link to={{ name: "docs", project }} current={!current}>{t("nav.docs")}</Link></p>
    {!root ? (error ? <Alert>{error}</Alert> : <Loading />) : branch(root, 0)}
    {missing.length > 0 && <div className="docs-tree-missing">
      <p className="hint">{t("docs.tree.missing")}</p>
      <ul className="docs-tree-list">{missing.map(d => <li key={d.path}><Link to={{ name: "docs", project, path: d.path }} current={d.path === current} className="docs-tree-file">
        <span className="docs-tree-name muted">{d.path.split("/").pop()}</span><span className="docs-flag">{t("docs.flag.missing")}</span></Link></li>)}</ul>
    </div>}
    {tree?.truncated && <p className="hint">{t("docs.tree.truncated")}</p>}
    {!!tree?.skipped.length && <p className="hint" title={tree.skipped.join("\n")}>{n("docs.tree.skipped", tree.skipped.length)}</p>}
  </nav>;
}

// --- summary ------------------------------------------------------------------------------------

function DocsOverview({ status, tree }: { status: Poll<DocsStatus>; tree?: Tree }) {
  const { t, rich } = useI18n();
  const { project } = useWorkspace();
  const s = status.data;
  const phase = s?.phase as PhaseView | null | undefined;
  // The local changes panel disappears with the commit; its result is still shown here.
  const [run, setRun] = useState<string>();
  return <>
    <PageHeader title={t("nav.docs")}>
      <p>{t("docs.lede")}</p>
    </PageHeader>
    <Stale error={s ? status.error : undefined} />
    {!s ? (status.error ? <Alert>{status.error}</Alert> : <Loading />) : <>
      {s.git_error && <Alert>{t("docs.git_error", { error: s.git_error })}</Alert>}
      {s.unresolved_intent && <div className="decision decision-attention" role="status">
        <h2>{t("docs.intent.title")}</h2>
        <p>{t("docs.intent.body")}</p>
        {phase && <p><Link to={{ name: "phase", project, phase: phase.code }}>{t("docs.see_phase", { phase: phase.code })}</Link></p>}
      </div>}
      {!!s.uncommitted?.length ? <LocalChanges status={s} onQueued={setRun} />
        : run && <section className="decision"><EditProgress run={run} /></section>}
      <Drift status={s} />
      {!!s.warnings.length && <div className="state state-attention" role="status"><p className="state-title">{t("docs.budgets")}</p>
        <ul>{s.warnings.map(w => <li key={w}>{w}</li>)}</ul></div>}
      <section className="panel" aria-labelledby="docs-set">
        <h2 id="docs-set">{t("docs.set")} {phase && <span className="count">{t("docs.set.phase", { phase: phase.code })} · <Status value={phase.status} kind="phase" /></span>}</h2>
        <div className="table-scroll" role="region" aria-label={t("docs.set")} tabIndex={0}>
          <table className="table">
            <thead><tr><th scope="col">{t("docs.column.document")}</th><th scope="col">{t("runs.column.type")}</th><th scope="col">{t("runs.column.status")}</th><th scope="col">{t("docs.column.blocks")}</th></tr></thead>
            <tbody>{s.documents.map(d => <tr key={d.path}>
              <td><Link to={{ name: "docs", project, path: d.path }}><code className="path">{d.path}</code></Link></td>
              <td>{t(KIND[d.kind])}</td>
              <td>{d.error ? <span className="status status-danger" title={d.error}><span className="status-mark" aria-hidden="true" />{t("docs.state.unreadable")}</span>
                : !d.exists ? <span className="status status-neutral"><span className="status-mark" aria-hidden="true" />{t("docs.state.missing")}</span>
                : d.drift ? <span className="status status-attention" title={t("docs.state.drift_hint")}><span className="status-mark" aria-hidden="true" />{t("docs.state.drift")}</span>
                : <span className="status status-ok"><span className="status-mark" aria-hidden="true" />{t("docs.state.current")}</span>}</td>
              <td>{d.blocks.length ? d.blocks.map(b => <code key={b} className="chip">{b}</code>) : <span className="muted">{t("stats.none")}</span>}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <p className="hint">{t("docs.folders")} {s.folders.map(f => <span key={f.path}><code className="chip">{f.path}/</code>{!f.exists && <span className="muted">{t("docs.folder_missing")} </span>}</span>)}</p>
      </section>
      <section className="panel" aria-labelledby="docs-decisions">
        <h2 id="docs-decisions">{t("docs.decisions")} <span className="count">{s.decisions.length}</span></h2>
        {!s.decisions.length ? <Empty title={t("docs.decisions.empty")}><p>{rich("docs.decisions.hint", { heading: <code>## DNNN — title</code>, file: <code>DECISIONS.md</code> })}</p></Empty>
          : <div className="table-scroll" role="region" aria-label={t("docs.decisions")} tabIndex={0}><table className="table">
            <thead><tr><th scope="col">{t("docs.column.id")}</th><th scope="col" className="wide">{t("docs.column.title")}</th><th scope="col">{t("runs.column.status")}</th></tr></thead>
            <tbody>{s.decisions.map(d => <tr key={d.id}>
              <td><Link className="mono" to={decisionHref(project, tree?.docs ?? "docs", d.id, d.title)}>{d.id}</Link></td>
              <td>{d.title ?? <span className="muted">{t("docs.untitled")}</span>}</td><td>{d.status ?? "—"}</td>
            </tr>)}</tbody></table></div>}
      </section>
      <section className="panel" aria-labelledby="docs-archive">
        <h2 id="docs-archive">{t("docs.archive")}</h2>
        {!s.archive.length ? <p className="hint">{t("docs.archive.empty")}</p>
          : <ul className="docs-archive">{s.archive.map(a => <li key={a.path}><code className="path">{a.path}/</code>{" "}
            {a.files.filter(f => f.endsWith(".md")).map(f => <Link key={f} className="chip" to={{ name: "docs", project, path: `${a.path}/${f}` }}>{f}</Link>)}</li>)}</ul>}
      </section>
      <NewDocument docs={tree?.docs ?? "docs"} existing={new Set(tree?.files.map(f => f.path))} blocked={editBlocker(s, t)} />
    </>}
  </>;
}

function NewDocument({ docs, existing, blocked }: { docs: string; existing: Set<string>; blocked?: string }) {
  const { t, rich } = useI18n();
  const { project } = useWorkspace();
  const [name, setName] = useState("");
  const path = `${docs}/${name.trim().replace(/^\/+/, "")}`;
  const valid = name.trim() !== "" && editablePath(path, docs);
  return <section className="panel" aria-labelledby="docs-new">
    <h2 id="docs-new">{t("docs.new")}</h2>
    <p className="hint">{rich("docs.new.hint", { docs: <code>{docs}/</code>, archive: <code>archive/</code>, file: <code>DECISIONS.md</code> })}</p>
    <form className="docs-new" onSubmit={e => { e.preventDefault(); if (valid && !existing.has(path)) navigate({ name: "docs", project, path }); }}>
      <label>{t("docs.new.path")}<span className="docs-prefix"><code>{docs}/</code><input value={name} onChange={e => setName(e.target.value)} placeholder="flows/tareas.md" maxLength={400} /></span></label>
      <button disabled={!valid || existing.has(path) || !!blocked}>{t("docs.new.create")}</button>
    </form>
    {existing.has(path) && <p className="hint">{t("docs.new.exists")}</p>}
    {name.trim() && !valid && <p className="hint">{rich("docs.new.invalid", { extension: <code>.md</code> })}</p>}
    {blocked && <p className="hint">{blocked}</p>}
  </section>;
}

// --- drift --------------------------------------------------------------------------------------

/** Committed documents that differ from the base adopted by the phase: resolved by adopting them in the phase. */
function Drift({ status }: { status: DocsStatus }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const local = new Set(status.uncommitted?.map(c => c.path));
  const drift = status.documents.filter(d => d.drift && !local.has(d.path));
  const phase = status.phase as PhaseView | null;
  if (!drift.length || !phase) return null;
  if (terminal(phase)) return <div className="decision decision-attention" role="status">
    <h2>{t("docs.drift.closed.title", { phase: phase.code })}</h2>
    <p>{drift.map(d => <code key={d.path} className="chip">{d.path}</code>)}</p>
    <p>{t("docs.drift.closed.body", { phase: phase.code })}</p>
    <p><Link to={{ name: "phase", project, phase: phase.code }}>{t("docs.drift.closed.link", { phase: phase.code })}</Link></p>
  </div>;
  return <div className="decision decision-attention" role="status">
    <h2>{t("docs.drift.title")}</h2>
    <p>{drift.map(d => <code key={d.path} className="chip">{d.path}</code>)}</p>
    <p>{t("docs.drift.body")}</p>
    <p><Link to={{ name: "phase", project, phase: phase.code }}>{t("docs.drift.link", { phase: phase.code })}</Link></p>
  </div>;
}

/** Uncommitted changes from the code editor: confirm their exact bytes or regenerate the blocks they touch. */
function LocalChanges({ status, onQueued }: { status: DocsStatus; onQueued: (run: string) => void }) {
  const { t } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const [review, setReview] = useState<{ body: S["DocumentEditInput"]; preview: Preview }>();
  const [refused, setRefused] = useState<{ text: string; blocks: boolean }>();
  const changes = status.uncommitted ?? [];
  const outside = changes.filter(c => !c.editable);
  async function load(regenerate: boolean) {
    const body: S["DocumentEditInput"] = { source: "worktree", regenerate_blocks: regenerate };
    setRefused(undefined); setReview(undefined);
    try { setReview({ body, preview: await managed<Preview>(`/projects/${project}/documents/edit/preview`, body) }); }
    catch (e) {
      if (e instanceof ManagedError && e.status === 409) setRefused({ text: message(e), blocks: e.code === "managed_blocks_generated" });
      else throw e;
    }
  }
  const blockRefusal = refused?.blocks;
  return <section className="decision decision-attention" id="local-changes" aria-labelledby="local-changes-title">
    <h2 id="local-changes-title">{t("docs.local.title")}</h2>
    <ul className="docs-changes">{changes.map(c => <li key={c.path}>
      {c.editable ? <Link to={{ name: "docs", project, path: c.path }}><code className="path">{c.path}</code></Link> : <code className="path">{c.path}</code>}
      {!c.editable && <span className="muted"> · {t("docs.local.outside")}</span>}</li>)}</ul>
    <p>{t("docs.local.body")}</p>
    {outside.length > 0 ? <p className="hint">{t("docs.local.outside_hint")}</p> : <>
      <p className="hint">{t("docs.local.confirm_hint")}</p>
      <div className="actions">
        <button type="button" disabled={busy} onClick={() => void operate(() => load(false))}>{t("docs.local.review")}</button>
        {blockRefusal && <button type="button" className="button-quiet" disabled={busy} onClick={() => void operate(() => load(true))}>{t("docs.local.regenerate")}</button>}
      </div>
    </>}
    {refused && <p role="alert" className="state state-error">{blockRefusal ? t("docs.local.block_refusal") : refused.text}</p>}
    {review && <EditReview body={review.body} preview={review.preview} onCancel={() => setReview(undefined)} onQueued={onQueued} />}
  </section>;
}

// --- shared confirmation ------------------------------------------------------------------------

/** Exact diff, reason and confirmation; enqueues `document_edit` with an idempotency key and follows its run. */
function EditReview({ body, preview, onCancel, onQueued, done }: {
  body: S["DocumentEditInput"]; preview: Preview; onCancel: () => void; onQueued?: (run: string) => void; done?: ReactNode;
}) {
  const { t, rich } = useI18n();
  const { project, busy, operate, send } = useWorkspace();
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [run, setRun] = useState<string>();
  const users = new Set(body.changes?.map(c => c.path) ?? []);
  if (run) return <EditProgress run={run} done={done} />;
  return <div className="docs-review">
    <h3>{t("docs.review.title")}</h3>
    {preview.resume_operation_id && <p className="state state-attention">{t("docs.review.resume", { id: preview.resume_operation_id.slice(0, 8) })}</p>}
    <ul className="docs-changes">{preview.documents.map(d => <li key={d.path}>
      <code className="path">{d.path}</code>{" "}
      <span className="muted">{d.before_sha256 === null ? rich("docs.review.new", { after: <Hash value={d.after_sha256} length={8} /> })
        : rich("docs.review.change", { before: <Hash value={d.before_sha256} length={8} />, after: <Hash value={d.after_sha256} length={8} /> })}
        {body.source === "content" && !users.has(d.path) && ` · ${t("docs.review.index")}`}</span></li>)}</ul>
    {!!preview.regenerated?.length && <div className="state state-attention">
      <p className="state-title">{t("docs.review.discarded")}</p>
      <p>{t("docs.review.discarded_body")}</p>
      {preview.regenerated.map(r => <DiffBlock key={r.path} diff={r.diff} label={t("docs.review.discarded_label", { path: r.path })} />)}
    </div>}
    <DiffBlock diff={preview.diff} label={t("docs.review.diff")} />
    <Fields items={[[t("docs.review.base"), <Hash value={preview.head} />], [t("docs.review.preview"), <Hash value={preview.preview_sha256} />]]} />
    <label>{t("docs.review.reason")}<input value={reason} maxLength={2000} onChange={e => { setReason(e.target.value); setConfirmed(false); }} placeholder={t("docs.review.reason_placeholder")} /></label>
    <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{preview.regenerated?.length ? t("docs.review.confirm_regenerate") : t("docs.review.confirm")}</label>
    <div className="actions">
      <button type="button" disabled={busy || !confirmed || !reason.trim()} onClick={() => void operate(async () => {
        const job = await send(jobRequest(`/projects/${project}/documents/edit`, {
          ...body, preview_sha256: preview.preview_sha256, resume_operation_id: preview.resume_operation_id ?? null,
          reason, confirmed: true,
        } satisfies S["DocumentEditCreate"]));
        setRun(job.run_id); onQueued?.(job.run_id);
      })}>{t("docs.review.commit")}</button>
      <button type="button" className="button-quiet" disabled={busy} onClick={onCancel}>{t("common.back")}</button>
    </div>
  </div>;
}

const FINAL = new Set(["COMMITTED", "STOPPED", "FAILED", "ABORTED", "INTERRUPTED", "RECOVERY_REQUIRED"]);

export function EditProgress({ run, done, onBack, title }: { run: string; done?: ReactNode; onBack?: () => void; title?: string }) {
  const { t } = useI18n();
  const read = usePoll<S["ManagedRunRead"]>(`/runs/${run}`, 1500);
  const r = read.data;
  const finished = r && FINAL.has(r.status);
  const route = r && r.project_id ? { name: "run" as const, project: r.project_id, phase: r.phase_id, task: r.task_id, run: r.id } : undefined;
  return <div className="docs-review" role="status">
    <h3>{title ?? t("docs.progress.title")}</h3>
    <p>{r ? <Status value={r.status} /> : t("docs.progress.reading")} {route && <Link to={route} className="mono">{t("trail.run", { id: run.slice(0, 8) })}</Link>}</p>
    {r?.status === "COMMITTED" && (done ?? <p>{t("docs.progress.committed")}</p>)}
    {finished && r?.status !== "COMMITTED" && <>
      <p className="state state-error">{r.history.stop ? t("docs.progress.not_committed_stop", { stage: r.history.stop.stage, reason: r.history.stop.reason }) : t("docs.progress.not_committed")}</p>
      {onBack && <button type="button" className="button-quiet" onClick={onBack}>{t("docs.progress.back")}</button>}
    </>}
  </div>;
}

// --- document -----------------------------------------------------------------------------------

function DocumentView({ path, status, tree }: { path: string; status: Poll<DocsStatus>; tree?: Tree }) {
  const { t, rich } = useI18n();
  const { project } = useWorkspace();
  const read = usePoll<S["DocumentRead"]>(`/projects/${project}/documents/content?path=${q(path)}`, 8000);
  const draftKey = `harness-doc-draft-v1:${project}:${path}`;
  const [editing, setEditing] = useState(() => !!loadDraft(draftKey));
  const s = status.data;
  const docs = tree?.docs ?? "docs";
  const doc = read.data;
  const entry = s?.documents.find(d => d.path === path);
  const local = s?.uncommitted?.some(c => c.path === path);
  const archived = path.startsWith(`${docs}/archive/`);
  const canEdit = editablePath(path, docs);
  const blocker = editBlocker(s, t);
  const name = path.split("/").pop()!;
  const kind = tree?.files.find(f => f.path === path)?.kind ?? (entry?.kind as S["DocumentTreeEntryRead"]["kind"] | undefined);
  if (read.missing && !editing) return <>
    <PageHeader title={name} code><p><code className="path">{path}</code></p></PageHeader>
    <Empty title={t("docs.document.missing")}>
      {canEdit ? <><p>{t("docs.document.create_hint")}</p>
        {blocker ? <p className="hint">{blocker}</p> : <button type="button" onClick={() => setEditing(true)}>{t("docs.document.create")}</button>}</>
        : <p>{rich("docs.document.shown", { docs: <code>{docs}/</code> })} <Link to={{ name: "docs", project }}>{t("docs.document.back")}</Link></p>}
    </Empty>
  </>;
  if (!doc && !read.missing) return read.error ? <Alert>{read.error}</Alert> : <Loading />;
  return <>
    <PageHeader title={name} code aside={!editing && doc?.editable && <button type="button" disabled={!!blocker} title={blocker} onClick={() => setEditing(true)}>{t("docs.document.edit")}</button>}>
      <p><code className="path">{path}</code> · {t(kind ? KIND[kind] : "docs.kind.other")}{doc && <> · <Hash value={doc.sha256} /></>}</p>
    </PageHeader>
    <Stale error={doc ? read.error : undefined} />
    {archived && <p className="state state-neutral docs-readonly">{t("docs.document.archived")}</p>}
    {local && <p className="state state-attention" role="status">{t("docs.document.local")} <Link to={{ name: "docs", project }}>{t("docs.document.local_link")}</Link></p>}
    {entry?.drift && !local && <p className="state state-attention" role="status">{terminal(s?.phase as PhaseView | null) ? t("docs.document.drift_closed") : t("docs.document.drift")} <Link to={{ name: "docs", project }}>{t("docs.document.drift_link")}</Link></p>}
    {entry?.error && <Alert>{entry.error}</Alert>}
    {editing ? <Editor path={path} doc={read.missing ? null : doc!} draftKey={draftKey} blocker={blocker} onClose={() => setEditing(false)} />
      : doc && <article className="doc-reader"><MarkdownView source={doc.content} path={path} /></article>}
  </>;
}

/** Rendered Markdown (markdown.ts) with internal navigation and isolated diagrams (mermaid-view.ts). */
export function MarkdownView({ source, path }: { source: string; path: string }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const rendered = useMemo(() => renderMarkdown(source, { project, path }), [source, project, path]);
  const container = useRef<HTMLDivElement>(null);
  const [dark, setDark] = useState(prefersDark);
  useEffect(() => {
    const update = () => setDark(prefersDark());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener("change", update);
    return () => { observer.disconnect(); media?.removeEventListener("change", update); };
  }, []);
  // Own texts of the rendered HTML, as text: block labels and the reason a link or an image does not navigate.
  useLayoutEffect(() => {
    const root = container.current;
    if (!root) return;
    root.querySelectorAll<HTMLElement>("section.doc-managed").forEach(section => {
      const name = section.dataset.block ?? "";
      const label = section.querySelector(":scope > .doc-managed-label");
      if (label) label.textContent = t("docs.block.label", { block: BLOCK_LABELS[name] ? t(BLOCK_LABELS[name]) : name });
      const empty = section.querySelector(":scope > .doc-managed-empty");
      if (empty) empty.textContent = t("docs.block.empty");
    });
    root.querySelectorAll<HTMLElement>("[data-blocked]").forEach(element => {
      const key = BLOCKED[element.dataset.blocked as BlockedReason];
      const reason = key ? t(key) : element.dataset.blocked ?? "";
      element.title = reason;
      if (element.classList.contains("doc-image-blocked"))
        element.textContent = t("docs.image_blocked", { alt: element.dataset.alt || t("docs.image"), reason });
    });
  }, [rendered, t]);
  useEffect(() => {
    const root = container.current;
    if (!root || !rendered.mermaid.length) return;
    let active = true;
    const urls: string[] = [];
    root.querySelectorAll<HTMLElement>("figure[data-mermaid]").forEach(figure => {
      const source = rendered.mermaid[Number(figure.dataset.mermaid)];
      figure.querySelector("img, .doc-mermaid-error")?.remove();
      figure.classList.add("doc-mermaid-loading");
      renderDiagram(source, dark).then(url => {
        if (!active) { URL.revokeObjectURL(url); return; }
        urls.push(url);
        const img = document.createElement("img");
        img.src = url; img.alt = t("docs.mermaid.alt");
        figure.prepend(img);
      }).catch(error => {
        if (!active) return;
        const note = document.createElement("p");
        note.className = "doc-mermaid-error";
        note.textContent = t("docs.mermaid.error", { error: message(error).slice(0, 300) });
        figure.prepend(note);
      }).finally(() => figure.classList.remove("doc-mermaid-loading"));
    });
    return () => { active = false; urls.forEach(url => URL.revokeObjectURL(url)); };
  }, [rendered, dark, t]);
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id.startsWith("doc-")) document.getElementById(id)?.scrollIntoView();
  }, [rendered]);
  function follow(event: MouseEvent<HTMLDivElement>) {
    const link = (event.target as HTMLElement).closest<HTMLAnchorElement>("a[data-internal]");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(link.getAttribute("href")!);
  }
  return <>
    {rendered.error && <p className="state state-attention">{t("docs.markers.malformed", { error: blockError(rendered.error, t) })}</p>}
    <div ref={container} className="doc-prose" onClick={follow} dangerouslySetInnerHTML={{ __html: rendered.html }} />
  </>;
}

// --- editor -------------------------------------------------------------------------------------

function loadDraft(key: string): Draft | undefined {
  try { return JSON.parse(sessionStorage.getItem(key) ?? "null") ?? undefined; } catch { return undefined; }
}
function saveDraft(key: string, draft?: Draft) {
  try { if (draft) sessionStorage.setItem(key, JSON.stringify(draft)); else sessionStorage.removeItem(key); } catch { /* no saved draft */ }
}

/**
 * Editable prose and locked managed blocks. The draft survives a reload (sessionStorage) with its base hash;
 * the preview compares that hash (CAS) and the commit carries the exact confirmed diff.
 */
function Editor({ path, doc, draftKey, blocker, onClose }: { path: string; doc: S["DocumentRead"] | null; draftKey: string; blocker?: string; onClose: () => void }) {
  const { t, rich } = useI18n();
  const { project, busy, operate } = useWorkspace();
  const original = doc?.content ?? "";
  const { segments, error } = useMemo(() => splitBlocks(original), [original]);
  const [draft, setDraft] = useState<Draft>(() => loadDraft(draftKey) ?? { base: doc?.sha256 ?? null, texts: segments.map(s => s.text) });
  const [view, setView] = useState<"edit" | "preview">("edit");
  const [review, setReview] = useState<{ body: S["DocumentEditInput"]; preview: Preview }>();
  const [conflict, setConflict] = useState<string>();
  useEffect(() => { saveDraft(draftKey, draft); }, [draftKey, draft]);
  // The draft was written over other segments (another version): it is kept, but cannot be rebuilt here.
  const shape = draft.texts.length === segments.length && segments.every((s, i) => s.kind === "prose" || draft.texts[i] === s.text);
  const content = draft.texts.join("");
  const changed = draft.base !== (doc?.sha256 ?? null) || content !== original;
  const stale = draft.base !== (doc?.sha256 ?? null);
  function discard() { saveDraft(draftKey); onClose(); }
  if (draft.run) return <EditProgress run={draft.run} onBack={() => setDraft({ ...draft, run: undefined })}
    done={<p>{t("docs.progress.committed")} <button type="button" className="button-quiet" onClick={discard}>{t("docs.editor.back")}</button></p>} />;
  if (error) return <Alert>{t("docs.editor.unsafe", { error: blockError(error, t) })}</Alert>;
  async function check() {
    setConflict(undefined); setReview(undefined);
    const body: S["DocumentEditInput"] = { source: "content", changes: [{ path, content, base_sha256: draft.base }], regenerate_blocks: false };
    try { setReview({ body, preview: await managed<Preview>(`/projects/${project}/documents/edit/preview`, body) }); }
    catch (e) { if (e instanceof ManagedError && e.status === 409) setConflict(e.code === "document_changed" ? "document_changed" : message(e)); else throw e; }
  }
  return <section className="docs-editor" aria-label={t("docs.editor.label", { path })}>
    {stale && <p className="state state-attention" role="status">{rich("docs.editor.stale", { base: <Hash value={draft.base} length={8} />, current: <Hash value={doc?.sha256} length={8} /> })}</p>}
    {!shape ? <Alert>{t("docs.editor.shape")}</Alert> : review ? null : <>
      <div className="docs-editor-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={view === "edit"} className={view === "edit" ? "" : "button-quiet"} onClick={() => setView("edit")}>{t("docs.editor.write")}</button>
        <button type="button" role="tab" aria-selected={view === "preview"} className={view === "preview" ? "" : "button-quiet"} onClick={() => setView("preview")}>{t("docs.review.preview")}</button>
      </div>
      {view === "preview" ? <article className="doc-reader"><MarkdownView source={content} path={path} /></article>
        : segments.map((segment, index) => segment.kind === "block"
          ? <LockedBlock key={index} segment={segment} />
          : <label key={index} className="docs-editor-prose"><span className="visually-hidden">{index ? t("docs.editor.after_block") : t("docs.editor.text")}</span>
            <textarea value={draft.texts[index]} spellCheck rows={Math.min(30, Math.max(segments.length > 1 ? 4 : 16, draft.texts[index].split("\n").length + 1))}
              onChange={e => { const texts = [...draft.texts]; texts[index] = e.target.value; setDraft({ ...draft, texts }); }} /></label>)}
    </>}
    {conflict && <p role="alert" className="state state-error">{conflict === "document_changed" ? t("docs.editor.conflict") : conflict}</p>}
    {review ? <EditReview body={review.body} preview={review.preview} onCancel={() => setReview(undefined)}
        onQueued={run => setDraft({ ...draft, run })} />
      : <div className="actions">
        <button type="button" disabled={busy || !changed || !shape || !!blocker} title={blocker} onClick={() => void operate(check)}>{t("docs.editor.review")}</button>
        <button type="button" className="button-quiet" disabled={busy} onClick={discard}>{changed ? t("docs.editor.discard") : t("docs.editor.close")}</button>
        {blocker && <span className="hint">{blocker}</span>}
      </div>}
  </section>;
}

function LockedBlock({ segment }: { segment: Extract<Segment, { kind: "block" }> }) {
  const { t, rich } = useI18n();
  return <details className="docs-locked">
    <summary><span className="docs-lock" aria-hidden="true" />{rich("docs.locked", { block: <code>{segment.name}</code> })}</summary>
    <pre>{blockBody(segment) || t("docs.block.empty")}</pre>
  </details>;
}
