/** Pure editor operations: changing a candidate never carries an old preview or rebases a CAS. */
import type { MessageKey } from "./i18n.ts";
import { agentIssues, commandsIssues, profileIssues } from "./profile-form.ts";
import { selectionIssues } from "./billing.ts";

export type Form = Record<string, any>;

/**
 * OT004: what the project editor may change at this stage (services/project_configuration.py `check_candidate`).
 * Before the first activation the profile, agents and policy stay those of the adopted proposal and admitted pair,
 * and only installed paths of the proposal's tools are completed. Later, commands and agents are editable; the
 * profile needs the editing base bound to the committed documents (`edit`).
 */
export function projectEditing(state: { active?: unknown }, form: Form) {
  const initial = !state.active && form.provenance?.source !== "legacy-configuration";
  return { stage: initial ? "initial" as const : "later" as const, profile: !initial && !!form.edit, agents: !initial };
}

export function projectIssues(form: Form, editing: ReturnType<typeof projectEditing>, efforts: Record<string, string[]>) {
  const issues: Record<string, MessageKey> = {
    ...(editing.profile ? profileIssues(form.profile, "profile") : {}),
    ...commandsIssues(form.commands, "commands", form.profile),
    // The referenced global revision's profiles are checked by the server preview (D263).
    ...selectionIssues(form, undefined),
  };
  if (editing.agents) for (const role of ["reviewer", "executor"]) {
    Object.assign(issues, agentIssues(form.agents?.[role], `agents.${role}`, [role], efforts));
    if (role === "reviewer" && !(efforts[form.agents?.reviewer?.provider] ?? []).includes(form.agents?.reviewer?.effort))
      issues["agents.reviewer.effort"] = "configuration.effort_invalid";
    if (role === "reviewer" && !String(form.agents?.reviewer?.model ?? "").trim()) issues["agents.reviewer.model"] = "configuration.required";
  }
  return issues;
}
export function configurationChange(state: { version: number; working_sha256?: string | null; active?: { sha256?: string } | null }, text: string, reason: string) {
  return { text, validated: true, expected_version: state.version, base_sha256: state.working_sha256 ?? null,
    active_sha256: state.active?.sha256 ?? null, import_external: false, reason };
}
export function preparationChange(state: { saved: Form | null; proposal_id: string; proposal_sha256: string }, projectVersion: number, mode: "offline" | "network", retry?: { id: string; step?: number }) {
  if (!state.saved) throw new Error("project_configuration_required");
  return { contract: "project-profile-preparation-1" as const, expected_version: projectVersion, mode,
    configuration_revision: state.saved.revision as number, configuration_sha256: state.saved.sha256 as string,
    proposal_id: state.proposal_id, proposal_sha256: state.proposal_sha256,
    ...(retry ? { previous_id: retry.id, retry_step: retry.step } : {}) };
}
