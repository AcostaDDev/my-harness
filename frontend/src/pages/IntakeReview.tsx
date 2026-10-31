import { useEffect, useState } from "react";
import { useI18n } from "../Language";
import { createOnce, managed } from "../managed-api";
import type { S } from "../managed-api";
import { Alert, Evidence, Hash, message } from "../ui";
import { MarkdownView } from "./Docs";
import { KnowledgeDocuments } from "./KnowledgeDocuments";
import { ProfileProposal } from "./ProjectProfile";
import { QuestionAnswers } from "./Answers";
import { useWorkspace } from "../workspace";

type Member = { kind: string; code: string; provenance: string; source: unknown;
  content: { title?: string; statement?: string; objective?: string; expected_result?: string; body?: string } };
type Preview = { preview_sha256: string; members: Member[]; links: unknown[]; changes: unknown; gaps: string[] };

export function IntakeReview({ conversation: c, base }: { conversation: S["PlanningConversationRead"]; base: string }) {
  const { t } = useI18n();
  const { project } = useWorkspace();
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [adopted, setAdopted] = useState(false);
  const [knowledgeHead, setKnowledgeHead] = useState<string | null>(null);
  useEffect(() => { if (c.created || adopted) void managed<S["KnowledgeHeadRead"]>(`/projects/${project}/knowledge`).then(h => setKnowledgeHead(h.revision?.id ?? null)).catch(e => setError(message(e))); }, [project, c.created, adopted]);
  useEffect(() => setPreview(undefined), [c.version]);
  const latest = c.turns.at(-1);
  const result = latest?.result?.result as { answer?: string; knowledge_sha256?: string } | undefined;
  const staged = c.log.some(e => e.action === "structured-intake-1" && e.turn_id === latest?.id);
  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError(undefined);
    try { await action(); } catch (e) { setError(message(e)); setPreview(undefined); }
    finally { setBusy(false); }
  }
  const args = { conversation_id: c.id, expected_version: c.version };
  return <main><h1>{c.title}</h1><p>{t("intake.lede")}</p>
    {error && <Alert>{error}</Alert>}
    <p className="state state-attention">{t("intake.continuation")}</p>
    <QuestionAnswers conversation={c} base={base} />
    {c.turns.map(turn => <section className="panel" key={turn.id}>
      <p>{turn.message}</p><Evidence title={turn.status} value={turn.result} />
    </section>)}
    {!c.created && !adopted && c.actions.includes("message") && <form onSubmit={e => {
      e.preventDefault(); void act(async () => { await createOnce(`${base}/messages`, { expected_version: c.version, text }); setText(""); });
    }}><label>{t("intake.message")}<textarea value={text} onChange={e => setText(e.target.value)} /></label>
      <button disabled={busy || !text.trim()}>{t("intake.send")}</button></form>}
    {!staged && latest?.status === "ANSWERED" && result?.knowledge_sha256 && <button disabled={busy} onClick={() => void act(async () => {
      await createOnce(`/projects/${project}/intake/stage`, { ...args, turn_id: latest.id, proposal_sha256: result.knowledge_sha256 });
    })}>{t("intake.stage")}</button>}
    {staged && !c.created && !adopted && <button disabled={busy} onClick={() => void act(async () => {
      setPreview(await managed<Preview>(`/projects/${project}/intake/preview`, args));
    })}>{t("intake.preview")}</button>}
    {preview && <section className="panel"><h2>{t("intake.preview")}</h2>
      {preview.members.map(m => <article key={`${m.kind}:${m.code}`}><h3>{m.code} — {m.content.title}</h3>
        <p>{m.provenance}</p><MarkdownView path="" source={m.content.body ?? m.content.statement ?? m.content.objective ?? m.content.expected_result ?? ""} />
        <Evidence title={t("intake.source")} value={m.source} /><Evidence title={m.code} value={m.content} /></article>)}
      <Evidence title={t("intake.relations")} value={preview.links} />
      <Evidence title={t("intake.changes")} value={preview.changes} />
      <Evidence title={t("intake.gaps")} value={preview.gaps} /><Hash value={preview.preview_sha256} />
      <label>{t("intake.reason")}<textarea value={reason} onChange={e => setReason(e.target.value)} /></label>
      <button disabled={busy || !reason.trim()} onClick={() => void act(async () => {
        await createOnce(`/projects/${project}/intake/adopt`, { ...args, preview_sha256: preview.preview_sha256, reason });
        setAdopted(true); setPreview(undefined);
      })}>{t("intake.adopt")}</button>
    </section>}
    {c.proposals.filter(p => p.kind === "profile" && (p.status === "PROPOSED" || p.status === "ACCEPTED")).map(p =>
      <ProfileProposal key={p.id} conversation={c} proposal={p} base={base} />)}
    {knowledgeHead && <KnowledgeDocuments project={project} head={knowledgeHead} />}
    {(adopted || c.created) && <p className="state state-ok">{t("intake.adopted")}</p>}
  </main>;
}
