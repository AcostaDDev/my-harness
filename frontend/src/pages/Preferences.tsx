import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useI18n } from "../Language";
import { LANGUAGES, LANGUAGE_NAMES } from "../i18n.ts";
import type { Language, MessageKey } from "../i18n.ts";
import { managed, ManagedError } from "../managed-api";
import type { S } from "../managed-api";
import { Loading, PageHeader, message } from "../ui";

type Draft = { ui_language: Language; default_work_language: Language };
type Notice = { tone: "ok" | "error"; key?: MessageKey; text?: string };

function Choice({ name, legend, hint, value, disabled, onChange }: {
  name: string; legend: string; hint: string; value: Language; disabled: boolean; onChange: (value: Language) => void;
}) {
  return <fieldset disabled={disabled}>
    <legend>{legend}</legend>
    <p className="hint" id={`${name}-hint`}>{hint}</p>
    {LANGUAGES.map(code => <label key={code} className="check">
      <input type="radio" name={name} value={code} checked={value === code} onChange={() => onChange(code)} aria-describedby={`${name}-hint`} />
      <span lang={code}>{LANGUAGE_NAMES[code]}</span>
    </label>)}
  </fieldset>;
}

/** Global languages of this installation (D166): one row in the service, saved with its expected version. */
export function PreferencesPage() {
  const { t, language, preferences, refresh, apply } = useI18n();
  const [draft, setDraft] = useState<Draft>();
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>();
  // The same change keeps its idempotency key until the service answers, so a lost response is not saved twice.
  const pending = useRef<{ body: string; key: string }>(undefined);
  useEffect(() => { void refresh(); }, [refresh]);
  if (!preferences) return <><PageHeader title={t("preferences.title")} /><Loading>{t("preferences.loading")}</Loading></>;
  const shown: Draft = draft ?? { ui_language: preferences.ui_language, default_work_language: preferences.default_work_language };
  const changed = shown.ui_language !== preferences.ui_language || shown.default_work_language !== preferences.default_work_language;
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !preferences) return;
    const body: S["PreferencesUpdate"] = { expected_version: preferences.version, ...shown };
    const text = JSON.stringify(body);
    const key = pending.current?.body === text ? pending.current.key : crypto.randomUUID();
    pending.current = { body: text, key };
    setBusy(true); setNotice(undefined);
    try {
      apply(await managed<S["PreferencesUpdateRead"]>("/preferences", body, key, "PUT"));
      pending.current = undefined;
      setDraft(undefined);
      setNotice({ tone: "ok", key: "preferences.saved" });
    } catch (e) {
      if (e instanceof ManagedError && e.status !== 401) pending.current = undefined;
      if (e instanceof ManagedError && e.code === "preferences_conflict") {
        setDraft(undefined);
        await refresh();
        setNotice({ tone: "error", key: "preferences.conflict" });
      } else setNotice({ tone: "error", text: message(e) });
    } finally { setBusy(false); }
  }
  const saved = preferences.updated_at
    ? t("preferences.meta", { version: preferences.version, date: new Intl.DateTimeFormat(language, { dateStyle: "medium", timeStyle: "short" }).format(new Date(preferences.updated_at)) })
    : t("preferences.meta_default");
  return <>
    <PageHeader title={t("preferences.title")}><p>{t("preferences.lede")}</p></PageHeader>
    {preferences.status === "invalid" && <p role="alert" className="state state-error">{t("preferences.invalid")}</p>}
    <form className="panel" onSubmit={save}>
      <Choice name="ui-language" legend={t("preferences.ui.legend")} hint={t("preferences.ui.hint")} value={shown.ui_language} disabled={busy}
        onChange={value => setDraft({ ...shown, ui_language: value })} />
      <Choice name="work-language" legend={t("preferences.work.legend")} hint={t("preferences.work.hint")} value={shown.default_work_language} disabled={busy}
        onChange={value => setDraft({ ...shown, default_work_language: value })} />
      <p className="hint">{saved}</p>
      <div className="actions">
        <button className="button-primary" disabled={busy || (!changed && preferences.status !== "invalid")}>{busy ? t("preferences.saving") : t("preferences.save")}</button>
      </div>
      {notice && <p role={notice.tone === "ok" ? "status" : "alert"} className={`state state-${notice.tone === "ok" ? "ok" : "error"}`}>{notice.key ? t(notice.key) : notice.text}</p>}
    </form>
  </>;
}
