// P001-T005b (D263): pure helpers for billing profiles, defaults and project selections. They mirror
// services/configuration.py `billing_profiles`/`selection` to point at the field to correct; the server stays
// authoritative and also refuses, at save, bundles that are not available and selections a global revision lacks.
// Billing metadata only exists in an explicitly converted format; controls replace only their own keys (D250).
import type { MessageKey } from "./i18n.ts";
import type { S } from "./managed-api";
import { isObject } from "./profile-form.ts";
import type { Issues, Obj } from "./profile-form.ts";

export const BILLING_GLOBAL = "local-config-10";
export const BILLING_PROJECT = "project-config-2";
export const PROVIDERS = ["claude", "codex"] as const;
export const BASES = ["api_usd", "enterprise_usd", "token_credit", "subscription_equivalent"] as const;
export const ROLES = ["reviewer", "executor"] as const;
export const PROFILE_NAME = /^[a-z0-9][a-z0-9_-]{0,63}$/;
export const IDENTITY = ["provider", "platform", "product", "scheme", "unit"] as const;
const IDENTIFIER = /^[A-Za-z0-9_.-]{1,80}$/;
export const CONDITION = /^[a-z][a-z0-9_]{0,39}$/;
export const CONDITION_VALUE = /^[a-z0-9_.-]{1,80}$/;
const DIGEST = /^[a-f0-9]{64}$/;
export const MAX_PROFILES = 32;
export const MAX_CONDITIONS = 8;
const MAX_SOURCE = 500;

export type Scheme = S["ReferenceSchemeRead"];
export type Bundle = S["ReferenceBundleRead"];

/** Explicit conversion: only `format` changes; nothing else is added or dropped. Loading never converts. */
export const converted = (form: Obj, format: string): Obj => ({ ...form, format });
export const billingGlobal = (form: Obj) => [BILLING_GLOBAL, "local-config-11"].includes(String(form.format));
export const billingProject = (form: Obj) => [BILLING_PROJECT, "project-config-3"].includes(String(form.format));

export function profilesOf(form: unknown): Obj {
  const billing = isObject(form) && isObject(form.billing) ? form.billing : {};
  return isObject(billing.profiles) ? billing.profiles : {};
}
export function defaultsOf(form: unknown): Obj {
  const billing = isObject(form) && isObject(form.billing) ? form.billing : {};
  return isObject(billing.defaults) ? billing.defaults : {};
}
/** Roles whose global default names this profile: it cannot be removed while they do. */
export const defaultUsers = (form: Obj, name: string) => ROLES.filter(role => defaultsOf(form)[role] === name);

/** A profile's identity filled from one reference scheme; conditions and other keys are kept as they are. */
export function fromScheme(profile: Obj, scheme: Scheme, bundle: string): Obj {
  const basis = (scheme.bases as string[]).includes(String(profile.basis)) ? profile.basis : scheme.bases[0];
  return { ...profile, ...Object.fromEntries(IDENTITY.map(key => [key, scheme[key]])), basis, references: bundle };
}
/** The scheme of the pinned bundle that matches the profile identity, if that bundle is listed. */
export function schemeOf(profile: Obj, bundles: Bundle[]): Scheme | undefined {
  const bundle = bundles.find(item => item.id === profile.references);
  return bundle?.schemes.find(item => IDENTITY.every(key => item[key] === profile[key]));
}
/** Conditions a matching tariff requires that the profile does not assert: valuation would stay incomplete. */
export function missingConditions(profile: Obj, scheme?: Scheme): string[] {
  const asserted = isObject(profile.conditions) ? profile.conditions : {};
  return scheme ? Object.keys(scheme.conditions).filter(name => !(name in asserted)) : [];
}

export function profileIssues(profile: unknown, prefix: string): Issues {
  const issues: Issues = {};
  if (!isObject(profile)) return { [prefix]: "billing.profile_invalid" };
  for (const key of IDENTITY.slice(1))
    if (typeof profile[key] !== "string" || !IDENTIFIER.test(profile[key])) issues[`${prefix}.${key}`] = "billing.identifier";
  if (!(PROVIDERS as readonly unknown[]).includes(profile.provider)) issues[`${prefix}.provider`] = "configuration.required";
  if (!(BASES as readonly unknown[]).includes(profile.basis)) issues[`${prefix}.basis`] = "configuration.required";
  if (typeof profile.references !== "string" || !DIGEST.test(profile.references)) issues[`${prefix}.references`] = "billing.references_required";
  const conditions = profile.conditions ?? {};
  if (!isObject(conditions) || Object.keys(conditions).length > MAX_CONDITIONS) issues[`${prefix}.conditions`] = "billing.conditions_limit";
  else for (const [name, item] of Object.entries(conditions)) {
    const where = `${prefix}.conditions.${name}`;
    if (!CONDITION.test(name)) issues[where] = "billing.condition_name";
    else if (!isObject(item) || typeof item.value !== "string" || !CONDITION_VALUE.test(item.value)) issues[`${where}.value`] = "billing.condition_value";
    else if (typeof item.source !== "string" || !item.source.trim() || item.source.length > MAX_SOURCE) issues[`${where}.source`] = "billing.condition_source";
  }
  return issues;
}

/** Global `billing` table: profiles and per-role defaults whose provider matches that role's agent. */
export function globalIssues(form: Obj): Issues {
  if (!billingGlobal(form)) return isObject(form.billing) ? { billing: "billing.format_required" } : {};
  const issues: Issues = {};
  const profiles = profilesOf(form);
  if (Object.keys(profiles).length > MAX_PROFILES) issues["billing.profiles"] = "billing.profiles_limit";
  for (const [name, profile] of Object.entries(profiles)) {
    if (!PROFILE_NAME.test(name)) issues[`billing.profiles.${name}`] = "billing.profile_name";
    Object.assign(issues, profileIssues(profile, `billing.profiles.${name}`));
  }
  for (const [role, name] of Object.entries(defaultsOf(form))) {
    const profile = profiles[String(name)];
    if (!isObject(profile)) issues[`billing.defaults.${role}`] = "billing.profile_missing";
    else if (profile.provider !== form.agents?.[role]?.provider) issues[`billing.defaults.${role}`] = "billing.provider_mismatch";
  }
  return issues;
}

/** Project selections: names of the referenced global revision whose provider matches the project's agent. */
export function selectionIssues(form: Obj, globalProfiles: Obj | undefined): Issues {
  if (!billingProject(form)) return isObject(form.billing) ? { billing: "billing.format_required" } : {};
  const issues: Issues = {};
  const selection = isObject(form.billing) ? form.billing : {};
  for (const [role, name] of Object.entries(selection)) {
    if (typeof name !== "string" || !PROFILE_NAME.test(name)) { issues[`billing.${role}`] = "billing.profile_name"; continue; }
    if (!globalProfiles) continue;  // the server checks it against the referenced revision
    const profile = globalProfiles[name];
    if (!isObject(profile)) issues[`billing.${role}`] = "billing.profile_missing";
    else if (profile.provider !== form.agents?.[role]?.provider) issues[`billing.${role}`] = "billing.provider_mismatch";
  }
  return issues;
}

/** What one role resolves to (D259 binding): explicit selection, else the global default, else unknown. */
export function resolution(role: string, selection: Obj, defaults: Obj, profiles: Obj, provider: unknown):
  { name?: string; origin: "selected" | "default" | "none"; known: boolean } {
  const name = typeof selection[role] === "string" && selection[role] ? selection[role] as string
    : typeof defaults[role] === "string" ? defaults[role] as string : undefined;
  const origin = selection[role] ? "selected" : name ? "default" : "none";
  const profile = name ? profiles[name] : undefined;
  return { name, origin, known: isObject(profile) && (provider === undefined || profile.provider === provider) };
}

export const EFFECTIVE: Record<Bundle["effective_period"], MessageKey> = {
  unknown: "billing.effective.unknown", known: "billing.effective.known", mixed: "billing.effective.mixed",
};
