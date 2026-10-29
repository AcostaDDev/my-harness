// Accounting (P001-T005a, D262/D263): queries and exact formats without React or dependencies, to test them with
// `node --test`. Amounts are exact decimal strings and never pass through a binary float; null is "no data".
import type { Language, MessageKey, Translate } from "./i18n.ts";
import type { Scope } from "./metrics-query.ts";

export const WORK = ["task_first_pass", "task_rework", "phase", "conversation", "setup", "other"] as const;
export type Work = typeof WORK[number];

/** Filters of the D262 API besides the project scope; days are UTC dates (`YYYY-MM-DD`), both inclusive. */
export type Filters = {
  phase?: string; task?: string; provider?: string; role?: string; purpose?: string; source_kind?: string;
  outcome?: string; launch?: string; requested_model?: string; effective_model?: string; effective_model_kind?: string;
  work?: Work[]; from_day?: string; until_day?: string;
};

const TEXT = ["provider", "role", "purpose", "source_kind", "outcome", "launch", "requested_model", "effective_model",
  "effective_model_kind"] as const;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The UTC day after `day`, or undefined when it is not a valid date. */
export function nextDay(day: string): string | undefined {
  if (!DAY.test(day)) return undefined;
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== day) return undefined;
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/**
 * Query of an accounting read: scope, filters, then the selection (`cohort`) and the page. The inclusive last
 * day becomes the exclusive `started_before` of the next UTC midnight; empty values are not sent.
 */
export function accountingQuery(scope: Scope, filters: Filters = {}, cohort?: string, extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams();
  if (scope.project) params.set("project_id", scope.project);
  if (scope.project && filters.phase) params.set("phase", filters.phase);
  if (scope.project && filters.phase && filters.task) params.set("task", filters.task);
  for (const name of TEXT) {
    const value = filters[name]?.trim();
    if (value) params.set(name, value);
  }
  for (const work of filters.work ?? []) params.append("work", work);
  if (filters.from_day && DAY.test(filters.from_day) && nextDay(filters.from_day)) params.set("started_from", `${filters.from_day}T00:00:00Z`);
  const before = filters.until_day ? nextDay(filters.until_day) : undefined;
  if (before) params.set("started_before", `${before}T00:00:00Z`);
  if (cohort) params.set("cohort", cohort);
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Number of filters in use, to say that a view is filtered. */
export function activeFilters(filters: Filters): number {
  return Object.entries(filters).filter(([, value]) => Array.isArray(value) ? value.length > 0 : !!value?.trim()).length;
}

export type GroupKey = { key: string | null; key_kind: string; phase_code: string | null };

/**
 * Filters that narrow the view to one group, or undefined when the API cannot select it (an unknown value, a
 * root, or a phase/task outside a project scope). Mixed and unknown effective models filter by their kind.
 */
export function groupFilter(dimension: string, group: GroupKey, project?: string): Filters | undefined {
  const { key, key_kind: kind } = group;
  if (dimension === "effective_model") {
    if (kind === "mixed" || kind === "unknown") return { effective_model_kind: kind };
    return key == null ? undefined : { effective_model: key };
  }
  if (key == null || kind === "unknown") return undefined;
  switch (dimension) {
    case "provider": case "requested_model": case "role": case "purpose": case "outcome": case "launch": case "source_kind":
      return { [dimension]: key };
    case "work": return (WORK as readonly string[]).includes(key) ? { work: [key as Work] } : undefined;
    case "day": return DAY.test(key) ? { from_day: key, until_day: key } : undefined;
    case "phase": return project ? { phase: key } : undefined;
    case "task": return project && group.phase_code ? { phase: group.phase_code, task: key } : undefined;
    default: return undefined;
  }
}

const EXACT = /^(-?)(\d+)(?:\.(\d+))?$/;

/**
 * Exact decimal string in the visual language: digits are regrouped, never rounded, and zeros after the last
 * significant decimal are dropped down to `min` decimals. A value that is not a plain decimal is returned as is.
 */
export function decimal(value: string, language: Language, min = 0): string {
  const match = EXACT.exec(value);
  if (!match) return value;
  const [, sign, whole, fraction = ""] = match;
  const point = new Intl.NumberFormat(language).formatToParts(1.5).find(part => part.type === "decimal")?.value ?? ".";
  const digits = fraction.replace(/0+$/, "").padEnd(min, "0");
  const negative = sign && /[1-9]/.test(whole + fraction);
  return `${negative ? "-" : ""}${new Intl.NumberFormat(language).format(BigInt(whole))}${digits ? point + digits : ""}`;
}

/** Units without an ISO currency code that the interface names in words. */
export const UNITS: Record<string, MessageKey> = { chatgpt_work_codex_credit: "accounting.unit.credit" };

/**
 * Exact amount with its unit: an ISO currency keeps the language's symbol and position (two decimals at least);
 * other units are written after the number. Null is "no data".
 */
export function money(value: string | null | undefined, unit: string, language: Language, t: Translate): string {
  if (value == null) return t("metrics.no_data");
  if (!EXACT.test(value)) return value;
  if (/^[A-Z]{3}$/.test(unit)) {
    const number = decimal(value.replace(/^-/, ""), language, 2);
    const negative = decimal(value, language, 2).startsWith("-");
    let parts: Intl.NumberFormatPart[];
    try { parts = new Intl.NumberFormat(language, { style: "currency", currency: unit }).formatToParts(negative ? -1 : 1); }
    catch { return `${decimal(value, language, 2)} ${unit}`; }
    let placed = false;
    return parts.map(part => {
      if (part.type === "currency" || part.type === "literal") return part.value;
      if (part.type === "minusSign") return "-";
      if (placed) return "";
      placed = true;
      return number;
    }).join("");
  }
  return `${decimal(value, language)} ${UNITS[unit] ? t(UNITS[unit]) : unit}`;
}

/** Name of a valuation basis; subscription equivalents are counterfactual by definition (D254). */
export const BASES: Record<string, MessageKey> = {
  api_usd: "accounting.basis.api_usd", enterprise_usd: "accounting.basis.enterprise_usd",
  token_credit: "accounting.basis.token_credit", subscription_equivalent: "accounting.basis.subscription_equivalent",
};

export type Bucket = { amount: string | null; known_subtotal: string | null };

/**
 * What a bucket can claim: the full `amount` only when the API gives one, otherwise the known subtotal marked
 * partial, otherwise nothing. A partial subtotal is never presented as the cost of the whole scope.
 */
export function bucketState(bucket: Bucket): { state: "full" | "partial" | "absent"; value: string | null } {
  if (bucket.amount != null) return { state: "full", value: bucket.amount };
  if (bucket.known_subtotal != null) return { state: "partial", value: bucket.known_subtotal };
  return { state: "absent", value: null };
}

/**
 * Effective-period state of a valuation's references, from the calculator's codes (D258): out of period or an
 * unknown period (a blocking reason) make it incomplete; a retrospective scenario carries the unknown period as a
 * warning. Without those codes and with referenced rows the period applied; without references it is unknown.
 */
export function periodState(valuation: { reasons: string[]; warnings: string[] }, references: number): "out_of_period" | "unknown" | "retrospective" | "applies" | "no_reference" {
  if (valuation.reasons.includes("reference_out_of_period")) return "out_of_period";
  if (valuation.reasons.includes("effective_period_unknown")) return "unknown";
  if (valuation.warnings.includes("effective_period_unknown")) return "retrospective";
  return references ? "applies" : "no_reference";
}

/** Whole days between an observation date and now; null when the date is absent or unreadable. */
export function ageDays(observed: string | null | undefined, now: Date): number | null {
  if (!observed) return null;
  const time = new Date(observed).getTime();
  if (Number.isNaN(time)) return null;
  return Math.max(0, Math.floor((now.getTime() - time) / 86_400_000));
}

/** Short label of an invocation: its `<source_kind>:<id>` source id (D259), not the kind every row shares. */
export function invocationLabel(id: string): string {
  return id.slice(id.indexOf(":") + 1).slice(0, 8);
}

/** Explained codes of the calculator, capture and selection; any other code is shown as is. */
export const REASONS = new Set(["usage_missing", "terminal_missing", "partial_capture", "capture_unavailable", "model_unreported",
  "model_partition_unknown", "model_partition_conflict", "delegation_boundary_unknown", "billing_profile_unknown",
  "scheme_unsupported", "reference_missing", "reference_conflict", "effective_period_unknown", "reference_out_of_period",
  "cache_lifetime_unknown", "cache_write_semantics_unknown", "request_tier_unknown", "speed_unknown", "geography_unknown",
  "tool_charge_unknown", "unsupported_modifier", "invalid_quantity", "invalid_rate", "inconsistent_usage", "legacy_evidence",
  "comparison_basis_unknown_or_different", "legacy_float", "reporting_precision_invalid"]);

/** Catalog key of a code's explanation, or undefined for a code the interface does not know. */
export function reasonKey(code: string): MessageKey | undefined {
  return REASONS.has(code) ? `accounting.reason.${code}` as MessageKey : undefined;
}

/** Code → count pairs, most frequent first, then by code; zero counts are omitted. */
export function counted(counts: Record<string, number> | null | undefined): [string, number][] {
  return Object.entries(counts ?? {}).filter(([, count]) => count > 0)
    .sort(([a, x], [b, y]) => y - x || (a < b ? -1 : a > b ? 1 : 0));
}

type Json = Record<string, unknown>;
const object = (value: unknown): Json | undefined => value && typeof value === "object" && !Array.isArray(value) ? value as Json : undefined;
const count = (value: unknown): number | null => typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
const text = (value: unknown): string | null => typeof value === "string" && value ? value : null;

/** Counts by name of an allowlisted capture map (tools, stream items); other values are left out. */
function tally(value: unknown): [string, number][] | null {
  const map = object(value);
  if (!map) return null;
  return Object.entries(map).flatMap(([name, number]) => count(number) == null ? [] : [[name, count(number)!] as [string, number]])
    .sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
}

export type CaptureFacts = {
  cli_version: string | null; native_status: string | null; exit_code: number | null;
  wall_ms: number | null; duration_ms: number | null; api_duration_ms: number | null;
  turns: number | null; permission_denials: number | null;
  tools: [string, number][] | null; items: [string, number][] | null;
  reported_model: string | null; response_models: string[] | null;
  reported_cost: { value: string; legacy: boolean } | null;
};

/**
 * Facts of the allowlisted capture document (`usage-capture-1`) the detail shows; anything absent or of another
 * shape is null ("not reported"), never zero. The reported cost is the client's estimate, not a valuation.
 */
export function captureFacts(document: unknown): CaptureFacts {
  const root = object(document) ?? {};
  const client = object(root.client) ?? {}, timing = object(root.timing) ?? {}, activity = object(root.activity) ?? {};
  const cost = object(object(root.reported_amounts)?.total_cost_usd);
  const models = Array.isArray(root.response_models) ? root.response_models.filter((m): m is string => typeof m === "string") : null;
  return {
    cli_version: text(client.cli_version), native_status: text(root.native_status),
    exit_code: typeof root.exit_code === "number" && Number.isInteger(root.exit_code) ? root.exit_code : null,
    wall_ms: count(timing.wall_ms), duration_ms: count(timing.duration_ms), api_duration_ms: count(timing.api_duration_ms),
    turns: count(activity.turns), permission_denials: count(activity.permission_denials),
    tools: tally(activity.tools), items: tally(activity.items),
    reported_model: text(object(root.reported_selection)?.model), response_models: models,
    reported_cost: cost && text(cost.value) ? { value: cost.value as string, legacy: cost.representation === "legacy_float" } : null,
  };
}

/** Rate of a valuation line (`{amount, quantity, unit}`) as "amount per quantity"; another shape is null. */
export function rateParts(rate: unknown): { amount: string; quantity: number; unit: string } | null {
  const value = object(rate);
  if (!value || typeof value.amount !== "string" || !EXACT.test(value.amount) || count(value.quantity) == null) return null;
  return { amount: value.amount, quantity: value.quantity as number, unit: text(value.unit) ?? "" };
}
