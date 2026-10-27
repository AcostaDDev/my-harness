// Statistics (H6.2 E6): formatting and scales without React or dependencies, to test them with `node --test`.
// Null is absence ("no data"), never zero; every sum says how many attempts contribute to it (D074).
import type { Language, MessageKey, Plural, Translate } from "./i18n.ts";

export type Sum = { sum: number | null; attempts: number };

/** Provenance of a value: short mark, full title and its name inside a sentence. */
export const PROVENANCE: Record<string, [MessageKey, MessageKey, MessageKey]> = {
  requested: ["metrics.provenance.requested.mark", "metrics.provenance.requested.title", "metrics.provenance.requested.name"],
  reported: ["metrics.provenance.reported.mark", "metrics.provenance.reported.title", "metrics.provenance.reported.name"],
  derived: ["metrics.provenance.derived.mark", "metrics.provenance.derived.title", "metrics.provenance.derived.name"],
  measured: ["metrics.provenance.measured.mark", "metrics.provenance.measured.title", "metrics.provenance.measured.name"],
  absent: ["metrics.provenance.absent.mark", "metrics.provenance.absent.title", "metrics.provenance.absent.name"],
};

export const ROLES: Record<string, MessageKey> = {
  planner: "metrics.role.planner", executor: "metrics.role.executor", reviewer: "metrics.role.reviewer",
  phase: "metrics.role.phase", chat: "metrics.role.chat", bootstrap: "metrics.role.bootstrap",
  definition: "metrics.role.definition", planning: "metrics.role.planning",
};

export type Formats = {
  /** Full integer (`12,345`). Null is "no data". */
  count: (value: number | null | undefined) => string;
  /** Compact for axes and headlines (`12.3K`); below 10 000, the full number. */
  compact: (value: number | null | undefined) => string;
  /** Reported API-equivalent cost: never an invoice or quota. Dollar cents below 1. */
  usd: (value: number | null | undefined) => string;
  /** Human-readable duration from milliseconds or seconds. */
  duration: (value: number | null | undefined, unit?: "ms" | "s") => string;
  percent: (part: number, whole: number) => string;
  coverageText: (value: Sum, attempts: number) => string;
  /** Short name of a project from its root, if no id is registered for it. */
  rootLabel: (root: string | null, projects: { id: string; root: string }[]) => string;
  /** Translated role, or the code itself when it is unknown. */
  role: (code: string) => string;
};

/** Formats of the statistics in one visual language. */
export function formats(language: Language, t: Translate, n: Plural): Formats {
  const integer = new Intl.NumberFormat(language, { maximumFractionDigits: 0 });
  const short = new Intl.NumberFormat(language, { notation: "compact", maximumFractionDigits: 1 });
  const decimal = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
  const none = t("metrics.no_data");
  return {
    count: value => value == null ? none : integer.format(value),
    compact: value => value == null ? none : Math.abs(value) < 10_000 ? integer.format(value) : short.format(value),
    usd: value => {
      if (value == null) return none;
      const digits = value < 1 ? 4 : 2;
      return new Intl.NumberFormat(language, { style: "currency", currency: "USD", minimumFractionDigits: digits,
        maximumFractionDigits: digits }).format(value);
    },
    duration: (value, unit = "s") => {
      if (value == null) return none;
      const seconds = unit === "ms" ? value / 1000 : value;
      if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
      if (seconds < 60) return `${decimal.format(seconds)} s`;
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return `${minutes} min ${Math.round(seconds % 60)} s`;
      const hours = Math.floor(minutes / 60);
      return `${hours} h ${minutes % 60} min`;
    },
    percent: (part, whole) => whole ? t("metrics.percent", { value: Math.round((part / whole) * 100) }) : none,
    coverageText: (value, attempts) => {
      const state = coverage(value, attempts);
      if (state === "absent") return attempts ? n("metrics.coverage.absent", attempts) : t("metrics.coverage.no_attempts");
      if (state === "partial") return t("metrics.coverage.partial", { part: value.attempts, count: attempts });
      return n("metrics.coverage.complete", attempts);
    },
    rootLabel: (root, projects) => {
      if (root == null) return t("metrics.no_root");
      return projects.find(project => project.root === root)?.id ?? root.split("/").filter(Boolean).pop() ?? root;
    },
    role: code => ROLES[code] ? t(ROLES[code]) : code,
  };
}

/**
 * Coverage of a sum: "complete" if every attempt contributes, "partial" if only some do and "absent" if
 * none does. A partial sum is never presented as the total of the scope.
 */
export function coverage(value: Sum, attempts: number): "complete" | "partial" | "absent" {
  if (value.sum == null || value.attempts === 0) return "absent";
  return value.attempts >= attempts ? "complete" : "partial";
}

/** "Round" step (1, 2 or 5 times a power of ten) not below `value`. */
export function niceStep(value: number): number {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) if (value <= step * power * (1 + 1e-9)) return step * power;
  return 10 * power;
}

/**
 * Axis from zero: top and ticks in round steps, about `count` divisions at most. With integer values the
 * ticks are integers (counts never show 2.5).
 */
export function axis(max: number, count = 4, integer = false): { top: number; ticks: number[] } {
  let step = niceStep(max > 0 ? max / count : 1);
  if (integer) step = Math.max(1, Math.round(step));
  const top = Math.max(step, Math.ceil(max / step - 1e-9) * step);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, index) => Math.round(index * step * 1e6) / 1e6);
  return { top, ticks };
}

/** Linear scale from [0, max] to [0, length]; null has no length (it is not drawn as zero). */
export function scale(value: number | null, max: number, length: number): number | null {
  if (value == null) return null;
  return max > 0 ? (Math.max(0, value) / max) * length : 0;
}
