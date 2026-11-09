import { useEffect, useRef, useState } from "react";
import { loadElement, resolveElement, saveElement } from "./chat-element";
import { useI18n } from "./Language";
import { message } from "./ui";

export function useChatElement(project: string, conversation: string) {
  const [selection, setSelection] = useState(() => loadElement(project, conversation));
  const [stale, setStale] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState("");
  const epoch = useRef(0);
  useEffect(() => { epoch.current++; setSelection(loadElement(project, conversation)); setStale(false); setLoading(false); setError("");
    return () => { epoch.current++; }; }, [project, conversation]);
  const remove = () => { epoch.current++; saveElement(project, conversation); setSelection(undefined);
    setStale(false); setLoading(false); setError(""); };
  const refresh = async () => {
    if (!selection?.target) return;
    const current = ++epoch.current;
    setLoading(true); setError("");
    try {
      const value = await resolveElement(project, selection.target);
      if (current !== epoch.current) return;
      const next = { target: selection.target, value };
      saveElement(project, conversation, next); setSelection(next); setStale(false);
    } catch (error) { if (current === epoch.current) { setError(message(error)); setStale(true); } }
    finally { if (current === epoch.current) setLoading(false); }
  };
  return { selection, stale, loading, error, remove, refresh, markStale: () => setStale(true),
    reference: selection?.value.reference ?? undefined };
}

export function ChatElement({ state, onRemove, locked = false }: { state: ReturnType<typeof useChatElement>; onRemove?: () => void; locked?: boolean }) {
  const { t } = useI18n();
  const ref = state.reference;
  if (!ref) return state.selection?.value.reason === "legacy" ? <p className="hint">{t("chat.element.legacy")}</p> : null;
  return <section className="chat-element" aria-label={t("chat.element.label")}>
    <p>{t("chat.element.included", { label: `${t(`chat.element.kind.${ref.kind}`)} ${state.selection?.value.label ?? ""}` })} <code>{(ref.revision_id ?? ref.evidence_digest)?.slice(0, 12)}</code></p>
    <div className="actions"><button type="button" className="button-quiet" disabled={locked} onClick={() => { state.remove(); onRemove?.(); }}>{t("chat.element.remove")}</button>
      <button type="button" className="button-quiet" disabled={locked || state.loading} onClick={() => void state.refresh()}>{t("chat.element.refresh")}</button></div>
    <p className="hint">{t("chat.element.evidence")}</p>
    <p role="status" aria-live="polite">{state.stale ? t("chat.element.stale") : state.loading ? t("chat.element.loading") : ""}</p>
    {state.error && <p role="alert">{state.error}</p>}
  </section>;
}
