// UI catalogs (P011-T007, D166): pure functions without React or dependencies, also used by the Node tests.
// English is the base and the fallback. A key names a complete message; parameters are plain `{name}` fields,
// replaced as text: never HTML, expressions or fragments of another message.
import type en from "./i18n/en.json";

export const LANGUAGES = ["en", "es"] as const;
export type Language = typeof LANGUAGES[number];
export const DEFAULT_LANGUAGE: Language = "en";
/** Each language is named in itself so that it can be found from any interface language. */
export const LANGUAGE_NAMES: Record<Language, string> = { en: "English", es: "Español" };

export type MessageKey = keyof typeof en;
/** Base of a plural message: the catalog holds `base.one` and `base.other`. */
export type PluralKey = MessageKey extends infer K ? K extends `${infer B}.one` ? B : never : never;
export type Params = Record<string, string | number>;
export type Translate = (key: MessageKey, params?: Params) => string;
export type Plural = (key: PluralKey, count: number, params?: Params) => string;
export type Catalogs = Record<Language, Readonly<Record<string, string>>>;

export const FIELD = /\{([a-z_][a-z0-9_]*)\}/g;

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);
}

/**
 * Localized text. A missing translation falls back to English; a missing key returns the key itself so that
 * it is visible and the coverage tests catch it. An absent parameter keeps its `{name}` field.
 */
export function translate(catalogs: Catalogs, language: Language, key: string, params: Params = {}): string {
  const text = catalogs[language][key] ?? catalogs[DEFAULT_LANGUAGE][key];
  if (text === undefined) return key;
  const numbers = new Intl.NumberFormat(language);
  return text.replace(FIELD, (field, name: string) => {
    if (!Object.hasOwn(params, name)) return field;
    const value = params[name];
    return typeof value === "number" ? numbers.format(value) : value;
  });
}

/** Plural variant `key.one` or `key.other` chosen by Intl.PluralRules; `count` is also a parameter. */
export function plural(catalogs: Catalogs, language: Language, key: string, count: number, params: Params = {}): string {
  const form = new Intl.PluralRules(language).select(count) === "one" ? "one" : "other";
  return translate(catalogs, language, `${key}.${form}`, { ...params, count });
}

/**
 * A message split at its fields, for rendering values that are elements (a code span, a link to an id).
 * Text parts keep their order; a field is named so the caller places its element there.
 */
export function segments(text: string): ({ text: string } | { field: string })[] {
  const parts: ({ text: string } | { field: string })[] = [];
  let last = 0;
  for (const match of text.matchAll(FIELD)) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) });
    parts.push({ field: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last) });
  return parts;
}

/** Error raised outside React with a catalog key; it is rendered in the visual language when shown. */
export class LocalizedError extends Error {
  readonly key: MessageKey;
  readonly params: Params;
  constructor(key: MessageKey, params: Params = {}) { super(key); this.key = key; this.params = params; }
}
