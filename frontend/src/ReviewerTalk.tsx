import { useContext, useEffect, useRef, useState } from "react";
import { useI18n } from "./Language";
import { createOnce } from "./managed-api";
import type { S } from "./managed-api";
import { navigate, RouteBase, withBase } from "./navigation";
import { href } from "./router";
import { message } from "./ui";
import { resolveElement, saveElement } from "./chat-element";
import type { ElementTarget } from "./chat-element";

/** Separate from inbox requests and role circles. No phase/task conversation bindings are created. */
export function ReviewerTalk({ project, target, archive = false, legacy = false }: { project: string; target?: ElementTarget; archive?: boolean; legacy?: boolean }) {
  const { t } = useI18n();
  const base = useContext(RouteBase);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const epoch = useRef(0), pending = useRef(false);
  const identity = JSON.stringify([project, target, archive, legacy]);
  useEffect(() => { epoch.current++; setBusy(false); setError(""); pending.current = false;
    return () => { epoch.current++; }; }, [identity]);
  if (archive) return null;
  return <div className="reviewer-talk"><button type="button" className="button-quiet" disabled={busy} onClick={() => {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    const current = epoch.current;
    void (async () => {
      try {
        const value: S["ChatElementRead"] | undefined = legacy ? { reference: null, label: null, reason: "legacy" }
          : target ? await resolveElement(project, target) : undefined;
        if (epoch.current !== current) return;
        const conversation = await createOnce<S["ChatConversationRead"]>(`/projects/${encodeURIComponent(project)}/conversations`,
          { title: t("chat.element.conversation"), phase_id: null, task_run_id: null } satisfies S["ChatConversationCreate"]);
        if (epoch.current !== current) return;
        if (value) saveElement(project, conversation.id, { target, value });
        navigate(withBase(base, href({ name: "chat", project, conversation: conversation.id })));
      } catch (error) { if (epoch.current === current) setError(message(error)); }
      finally { if (epoch.current === current) { setBusy(false); pending.current = false; } }
    })();
  }}>{t("chat.element.talk")}</button>{error && <p role="alert">{error}</p>}</div>;
}
