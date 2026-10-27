import { createContext, Fragment, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { DEFAULT_LANGUAGE, isLanguage, LocalizedError, plural, segments, translate } from "./i18n.ts";
import type { Language, MessageKey, Params, Plural, Translate } from "./i18n.ts";
import en from "./i18n/en.json";
import es from "./i18n/es.json";
import { managed } from "./managed-api";
import type { S } from "./managed-api";

const CATALOGS = { en, es } satisfies Record<Language, Record<MessageKey, string>>;
// Provisional copy for the next page load only: the service preferences are the authority (D166).
const CACHE = "harness-ui-language";

/** Elements placed at the fields of a message; strings and numbers are replaced as text. */
export type Rich = (key: MessageKey, params: Record<string, ReactNode>) => ReactNode;

type I18nValue = {
  language: Language;
  t: Translate;
  /** Plural variant chosen by the visual language (`key.one` / `key.other`). */
  n: Plural;
  rich: Rich;
  /** Last read of the service; undefined until it answers. */
  preferences?: S["PreferencesRead"];
  unavailable: boolean;
  refresh: () => Promise<void>;
  apply: (preferences: S["PreferencesRead"]) => void;
};

const I18nContext = createContext<I18nValue | null>(null);

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("I18nProvider missing");
  return value;
}

function cached(): Language {
  try { const value = localStorage.getItem(CACHE); return isLanguage(value) ? value : DEFAULT_LANGUAGE; }
  catch { return DEFAULT_LANGUAGE; }
}

// Language of the provider, for text produced outside React (an error caught in a handler).
let active: Language = DEFAULT_LANGUAGE;

/** Message in the current visual language for code without the context; components use `useI18n`. */
export function translateNow(key: MessageKey, params?: Params): string {
  return translate(CATALOGS, active, key, params);
}

/** Text of an error: own errors through the catalog, everything else with its original message. */
export function errorText(error: unknown): string {
  if (error instanceof LocalizedError) return translateNow(error.key, error.params);
  return error instanceof Error ? error.message : String(error);
}

/** Visual language of every window of this service; before the first read, the cached value or English. */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(cached);
  const [preferences, setPreferences] = useState<S["PreferencesRead"]>();
  const [unavailable, setUnavailable] = useState(false);
  active = language;
  useEffect(() => { document.documentElement.lang = language; }, [language]);
  const apply = useCallback((value: S["PreferencesRead"]) => {
    setPreferences(value);
    setLanguage(value.ui_language);
    setUnavailable(false);
    try { localStorage.setItem(CACHE, value.ui_language); } catch { /* no provisional copy */ }
  }, []);
  // A failed read keeps the current language and says so; it never writes the preferences.
  const refresh = useCallback(async () => {
    try { apply(await managed<S["PreferencesRead"]>("/preferences")); }
    catch { setUnavailable(true); }
  }, [apply]);
  const t = useCallback<Translate>((key, params) => translate(CATALOGS, language, key, params), [language]);
  const n = useCallback<Plural>((key, count, params) => plural(CATALOGS, language, key, count, params), [language]);
  // Split before replacing: a value that contains `{name}` is never read as another field.
  const rich = useCallback<Rich>((key, params) => {
    const numbers = new Intl.NumberFormat(language);
    return segments(translate(CATALOGS, language, key)).map((part, index) => {
      if (!("field" in part)) return <Fragment key={index}>{part.text}</Fragment>;
      const value = Object.hasOwn(params, part.field) ? params[part.field] : `{${part.field}}`;
      return <Fragment key={index}>{typeof value === "number" ? numbers.format(value) : value}</Fragment>;
    });
  }, [language]);
  const value = useMemo(() => ({ language, t, n, rich, preferences, unavailable, refresh, apply }),
    [language, t, n, rich, preferences, unavailable, refresh, apply]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
