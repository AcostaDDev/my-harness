import { useRef, useState } from "react";
import { useI18n } from "./Language";
import { LANGUAGES, LANGUAGE_NAMES } from "./i18n.ts";
import type { Language, MessageKey } from "./i18n.ts";
import { managed } from "./managed-api";
import type { S } from "./managed-api";
import { Alert, Fields, Hash, message } from "./ui";

// Work language per project (P011-T008, D167): chosen once when a project is registered or created, or confirmed
// explicitly for a project without one; afterwards the interface only shows it. The visual language is global.

const SOURCES: Record<S["WorkLanguageRead"]["source"], MessageKey> = {
  registration: "work.source.registration", creation: "work.source.creation", toml: "work.source.toml",
  migration: "work.source.migration",
};

/** Explicit choice, initialized from the global default; the value shown is the value sent. */
export function WorkLanguageChoice({ value, disabled, onChange }: {
  value: Language | undefined; disabled?: boolean; onChange: (value: Language) => void;
}) {
  const { t } = useI18n();
  return <fieldset disabled={disabled}>
    <legend>{t("work.legend")}</legend>
    <p className="hint" id="work-language-hint">{t("work.hint")}</p>
    {LANGUAGES.map(code => <label key={code} className="check">
      <input type="radio" name="work-language" value={code} checked={value === code} required
        onChange={() => onChange(code)} aria-describedby="work-language-hint" />
      <span lang={code}>{LANGUAGE_NAMES[code]}</span>
    </label>)}
  </fieldset>;
}

/** What a preview seals: the chosen value, the default read for provenance and an association that is kept. */
export function WorkLanguagePreview({ preview }: { preview: S["WorkLanguagePreviewRead"] }) {
  const { t } = useI18n();
  return <>
    <p><strong>{t("work.preview.value", { language: LANGUAGE_NAMES[preview.work_language] })}</strong></p>
    <p className="hint">{preview.existing
      ? t("work.preview.existing", { language: LANGUAGE_NAMES[preview.existing.work_language] })
      : t("work.preview.default", { language: LANGUAGE_NAMES[preview.default_work_language] })}</p>
  </>;
}

/** Read-only value of a project, or the explicit confirmation when it has none yet. */
export function WorkLanguageSettings({ project, work, onChanged }: {
  project: string; work: S["WorkLanguageRead"] | null | undefined; onChanged: () => void;
}) {
  const { t, language } = useI18n();
  return <section className="panel" aria-labelledby="settings-work-language">
    <h2 id="settings-work-language">{t("work.settings.title")}</h2>
    {work ? <>
      <p lang={language}>{t("work.settings.value", { language: LANGUAGE_NAMES[work.work_language],
        source: t(SOURCES[work.source]),
        date: new Intl.DateTimeFormat(language, { dateStyle: "medium" }).format(new Date(work.confirmed_at)) })}</p>
      <Fields items={[["SHA-256", <Hash value={work.sha256} />]]} />
    </> : <WorkLanguageConfirmation project={project} onChanged={onChanged} />}
  </section>;
}

function WorkLanguageConfirmation({ project, onChanged }: { project: string; onChanged: () => void }) {
  const { t, preferences } = useI18n();
  const [chosen, setChosen] = useState<Language>();
  const [preview, setPreview] = useState<S["WorkLanguageMigrationPreviewRead"]>();
  const [reason, setReason] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const value = chosen ?? preferences?.default_work_language;
  const pending = preview ? [...preview.unfinished_jobs.map(String), ...preview.configuration_blockers] : [];
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  const path = `/projects/${encodeURIComponent(project)}/work-language`;
  return <>
    <p className="state state-attention" role="status"><strong>{t("work.missing.title")}.</strong> {t("work.missing.body")}</p>
    <form onSubmit={e => { e.preventDefault(); if (value) void run(async () => {
      const current = generation.current;
      const data = await managed<S["WorkLanguageMigrationPreviewRead"]>(`${path}/preview`, { work_language: value });
      if (current === generation.current) { setPreview(data); setAccepted(false); }
    }); }}>
      <WorkLanguageChoice value={value} disabled={busy}
        onChange={next => { generation.current++; setChosen(next); setPreview(undefined); setAccepted(false); }} />
      <div className="actions"><button disabled={busy || !value}>{t("work.missing.review")}</button></div>
    </form>
    {preview && <div className="decision decision-attention">
      <WorkLanguagePreview preview={preview.work_language} />
      <Fields items={[["Checkout", <code className="path">{preview.root}</code>], ["SHA-256", <Hash value={preview.preview_sha256} />]]} />
      {!!pending.length && <Alert>{t("work.missing.blocked", { items: pending.join("; ") })}</Alert>}
      <label>{t("work.missing.reason")}<input value={reason} required maxLength={2000} onChange={e => setReason(e.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={accepted} onChange={e => setAccepted(e.target.checked)} />
        <span>{t("work.missing.check")}</span></label>
      <div className="actions">
        <button type="button" disabled={busy || !accepted || !reason.trim() || !!pending.length} onClick={() => void run(async () => {
          await managed<S["WorkLanguageMigrationApplyRead"]>(path, { change: { work_language: preview.work_language.work_language },
            preview_sha256: preview.preview_sha256, reason: reason.trim() });
          setPreview(undefined); onChanged();
        })}>{t("work.missing.confirm")}</button>
      </div>
    </div>}
    {error && <Alert>{error}</Alert>}
  </>;
}
