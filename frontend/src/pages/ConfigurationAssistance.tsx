import { useEffect, useState } from "react";
import { managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import { useI18n } from "../Language";
import { Evidence, Hash } from "../ui";

type RecordData = Record<string, any>;
type Pending = { body: S["AssistanceConfirm"]; key: string };
const ROOT = "/configuration/assistance";

/** The exact turn is kept until acknowledged. Only a button can send or repeat it. */
export function ConfigurationAssistance({ scope, state, candidate, disabled, run, apply, contextPaths = [] }: {
  scope: string; state: { version: number; active?: RecordData | null; working_sha256?: string | null };
  candidate: S["ConfigurationCandidate"]; disabled: boolean; run: (work: () => Promise<void>) => unknown;
  apply: (text: string) => void;
  contextPaths?: string[];
}) {
  const { t } = useI18n();
  const [message, setMessage] = useState("");
  const [role, setRole] = useState<"reviewer" | "executor">("reviewer");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("medium");
  const [documents, setDocuments] = useState(false);
  const [preview, setPreview] = useState<{ shown: RecordData; body: S["AssistanceRequest"] }>();
  const [confirmed, setConfirmed] = useState(false);
  const storageKey = `harness-configuration-assistance:${scope}`;
  const [pending, setPending] = useState<Pending | undefined>(() => {
    try { return JSON.parse(sessionStorage.getItem(storageKey) ?? "null") ?? undefined; } catch { return undefined; }
  });
  const [result, setResult] = useState<S["ConfigurationOperationRead"]>();
  const [stopped, setStopped] = useState(false);
  useEffect(() => { setPreview(undefined); setConfirmed(false); },
    [JSON.stringify(candidate), state.version, state.active?.sha256, message, role, model, effort, documents]);
  if (!state.active) return null;
  async function send(action: Pending) {
    sessionStorage.setItem(storageKey, JSON.stringify(action)); setPending(action);
    try {
      setResult(await managed<S["ConfigurationOperationRead"]>(`${ROOT}/confirm`, action.body, action.key));
      sessionStorage.removeItem(storageKey); setPending(undefined); setPreview(undefined); setConfirmed(false);
    } catch (error) {
      if (error instanceof ManagedError && error.status >= 400 && error.status < 500 && error.status !== 401) {
        sessionStorage.removeItem(storageKey); setPending(undefined);
      }
      throw error;
    }
  }
  const proposal = result?.result?.proposal as RecordData | undefined;
  return <section className="panel">
    <h3>{t("assistance.title")}</h3><p>{t("assistance.hint")}</p>
    <fieldset disabled={disabled || !!pending}>
      <label>{t("assistance.role")}<select value={role} onChange={e => setRole(e.target.value as typeof role)}>
        <option value="reviewer">{t("assistance.reviewer")}</option><option value="executor">{t("assistance.executor")}</option>
      </select></label>
      {role === "executor" && <div className="form-row">
        <label>{t("settings.model")}<input value={model} onChange={e => setModel(e.target.value)} /></label>
        <label>{t("settings.effort")}<input value={effort} onChange={e => setEffort(e.target.value)} /></label>
      </div>}
      {scope !== "global" && <label className="check"><input type="checkbox" checked={documents} onChange={e => setDocuments(e.target.checked)} />{t("assistance.documents")}</label>}
      <label>{t("assistance.request")}<textarea id="configuration-assistance-message" rows={3} maxLength={8000} value={message} onChange={e => setMessage(e.target.value)} /></label>
      <button disabled={!message.trim() || role === "executor" && !model.trim()} onClick={() => void run(async () => {
        const body: S["AssistanceRequest"] = { scope, candidate, expected_version: state.version,
          active_sha256: String(state.active!.sha256), base_sha256: state.working_sha256!, role, message,
          documents: documents ? contextPaths : [],
          ...(role === "executor" ? { selection: { model, effort } } : {}) };
        setPreview({ body, shown: await managed<RecordData>(`${ROOT}/preview`, body) }); setConfirmed(false);
      })}>{t("assistance.preview")}</button>
    </fieldset>
    {preview && <div className="decision">
      <p>{t(preview.body.role === "executor" ? "assistance.scope_write" : "assistance.scope_read")}</p>
      <Evidence title={t("assistance.context")} value={preview.shown} /><Hash value={preview.shown.sha256} />
      <label className="check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />{t("assistance.authorize")}</label>
      <button disabled={disabled || !confirmed || !!pending} onClick={() => void run(() => send({
        body: { ...preview.body, preview_sha256: preview.shown.sha256, confirmed: true }, key: crypto.randomUUID(),
      }))}>{t("assistance.confirm")}</button>
      <button disabled={disabled} onClick={() => { setPreview(undefined); setConfirmed(false); }}>{t("assistance.cancel")}</button>
    </div>}
    {pending && <div className="decision"><p>{t("assistance.pending")}</p>
      <button disabled={disabled} onClick={() => void run(() => send(pending))}>{t("workspace.pending.repeat")}</button>
    </div>}
    {result && <>
      {proposal?.diagnostic && <p role="status">{t("assistance.failed")}</p>}
      <Evidence title={t("assistance.result")} value={result} />
      {typeof proposal?.text === "string" && <button disabled={disabled} onClick={() => apply(proposal.text)}>{t("assistance.apply")}</button>}
      {(result.status === "RECOVERY_REQUIRED" || result.status === "INTENDED") && <>
        <label className="check"><input type="checkbox" checked={stopped} onChange={e => setStopped(e.target.checked)} />{t("configuration.writers_stopped")}</label>
        <button disabled={disabled || !stopped} onClick={() => void run(async () => {
          setResult(await managed<S["ConfigurationOperationRead"]>(`${ROOT}/${result.id}/recover`, { writers_stopped: true }));
        })}>{t("configuration.recover")}</button>
      </>}
    </>}
  </section>;
}
