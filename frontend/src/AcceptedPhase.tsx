import { useEffect, useState } from "react";
import { managed, jobRequest } from "./managed-api";
import type { S } from "./managed-api";
import { useI18n } from "./Language";
import { useWorkspace } from "./workspace";
import { Evidence, Hash } from "./ui";
import { Link, navigate } from "./navigation";

/** Shared owner confirmation for accepted-roadmap activation and plan revisions. */
export function AcceptedPhase({ phase }: { phase?: S["PhaseRead"] }) {
  const { t } = useI18n();
  const { project, busy, operate, send } = useWorkspace();
  const [code, setCode] = useState(phase?.code ?? "P001");
  const [coverage, setCoverage] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<S["AcceptedPhasePreviewRead"]>();
  const [draftId, setDraftId] = useState<string>();
  const [input, setInput] = useState<S["AcceptedPhasePreviewCreate"]>();
  useEffect(() => { setPreview(undefined); setConfirmed(false); setDraftId(phase?.operations.filter(op => op.kind === "plan" && op.status === "PROPOSED").at(-1)?.result?.draft_id as string | undefined); }, [phase?.version]);
  useEffect(() => {
    const knowledge = phase?.definition.knowledge as { criteria?: Record<string, unknown>; coverage?: Record<string, string[]> } | undefined;
    setCoverage(Object.keys(knowledge?.criteria ?? {}).map(c => `${c}: ${(knowledge?.coverage?.[c] ?? []).join(", ")}`).join("\n"));
  }, [phase?.definition_sha256]);
  const args = (): S["AcceptedPhasePreviewCreate"] => ({ code, phase_id: phase?.id ?? null,
    expected_version: phase?.version ?? null, draft_id: draftId ?? null,
    coverage: phase ? Object.fromEntries(coverage.split("\n").filter(line => line.trim()).map(line => {
      const [criterion, tasks = ""] = line.split(":");
      return [criterion.trim(), tasks.split(",").map(t => t.trim()).filter(Boolean)];
    })) : {} });
  const proposed = phase?.operations.filter(op => op.kind === "plan" && op.status === "PROPOSED").at(-1);
  return <section className="panel" aria-labelledby="accepted-phase">
    <h2 id="accepted-phase">{t(phase ? "phase.accepted.plan" : "phase.accepted.activate")}</h2>
    <p className="hint">{t("phase.accepted.hint")}</p>
    <p><Link to={{ name: "project-knowledge", project }}>{t("knowledge.title")}</Link></p>
    {!phase && <label>{t("phase.field.code")}<input value={code} pattern="P[0-9]{3}" onChange={e => { setCode(e.target.value); setPreview(undefined); }} /></label>}
    {phase && <>
      <label>{t("phase.accepted.coverage")}<textarea rows={4} value={coverage} placeholder="C001: P001-T001, P001-T002" onChange={e => { setCoverage(e.target.value); setPreview(undefined); }} /></label>
      <button disabled={busy || !phase.actions.includes("plan")} onClick={() => void operate(() => send(jobRequest(`/phases/${phase.id}/plan/propose`, { expected_version: phase.version })))}>{t("phase.accepted.propose")}</button>
      {proposed && <div className="decision">
        <Evidence title={t("phase.accepted.proposal")} value={proposed.result} />
        <button disabled={busy} onClick={() => void operate(async () => {
          const staged = await managed<S["PhaseProposalStageRead"]>(`/phases/${phase.id}/plan/stage`, {
            expected_version: phase.version, operation_id: proposed.id,
            proposal_sha256: proposed.result?.proposal_sha256,
          });
          setDraftId(staged.draft_id ?? undefined);
          setCoverage(Object.entries(staged.coverage).map(([c, tasks]) => `${c}: ${tasks.join(", ")}`).join("\n"));
          // Stage changes the phase version; refresh through operate before previewing its candidate.
        })}>{t("phase.accepted.stage")}</button>
      </div>}
    </>}
    <button disabled={busy || !code || (phase && !phase.actions.includes("plan"))} onClick={() => void operate(async () => {
      const body = args();
      setInput(body); setPreview(await managed<S["AcceptedPhasePreviewRead"]>(`/projects/${project}/phases/accepted/preview`, body)); setConfirmed(false);
    })}>{t("phase.accepted.preview")}</button>
    {preview && <div className="decision">
      <Evidence title={t("phase.accepted.preview")} value={preview.definition} />
      <p>{t("phase.accepted.hash")}: <Hash value={preview.preview_sha256} /></p>
      <label>{t("phase.reconcile.reason")}<input value={reason} onChange={e => setReason(e.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("phase.accepted.confirm")}</label>
      <button disabled={busy || !confirmed || !reason.trim()} onClick={() => void operate(async () => {
        const body = { ...(input ?? args()), preview_sha256: preview.preview_sha256, confirmed: true, reason } satisfies S["AcceptedPhaseAdoptCreate"];
        const path = `/projects/${project}/phases/accepted/adopt`;
        const request = jobRequest(path, body);
        const result = await managed<S["PhaseRead"]>(path, body, request.key);
        setPreview(undefined); setConfirmed(false);
        navigate({ name: "phase", project, phase: result.code });
      })}>{t("phase.accepted.adopt")}</button>
    </div>}
  </section>;
}
