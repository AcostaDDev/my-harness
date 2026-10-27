/** Pure editor operations: changing a candidate never carries an old preview or rebases a CAS. */
export type Form = Record<string, any>;
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
