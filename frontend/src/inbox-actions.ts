import type { S } from "./managed-api";

type Item = S["InboxItemDetail"];
type Inputs = { answers: string[]; reason: string; scope: "once" | "task"; confirmed: boolean; ttl: number };
const e = encodeURIComponent;

/** The selected origin supplies every identity and version. The form supplies owner input only. */
export function inboxResponse(item: Item, values: Inputs, decision?: "grant" | "deny") {
  const response = item.response;
  if (item.resolved || !response || !item.request_id || !item.registered_project_id || !values.confirmed) return;
  const { target_id, version, request_version, proof } = response;
  const id = e(target_id), request = e(item.request_id);
  switch (item.topic) {
    case "run_permission":
      if (!decision || !proof || !values.reason.trim()) return;
      return {
        path: `/runs/${id}/permissions/${request}/decision`, once: false,
        body: { expected_version: version, expected_request_version: request_version, fingerprint: proof,
          reason: values.reason, scope: values.scope, decision, confirmed: true } satisfies S["PermissionDecisionCreate"],
      };
    case "task_gap":
      if (!proof || !response.prompts.length || values.answers.length !== response.prompts.length
          || values.answers.some(value => !value.trim()) || !Number.isInteger(values.ttl) || values.ttl < 1 || values.ttl > 86400) return;
      return {
        path: `/runs/${id}/gap-resolutions`, once: true,
        body: { expected_version: version, gap_event_id: request_version, request_sha256: proof,
          answers: values.answers, ttl_seconds: values.ttl, confirmed: true } satisfies S["TaskGapResolutionCreate"],
      };
    case "phase_question":
      if (!values.answers[0]?.trim()) return;
      return {
        path: `/phases/${id}/questions/${request}/answer`, once: false,
        body: { expected_version: version, expected_question_version: request_version,
          answer: values.answers[0], confirmed: true } satisfies S["PhaseAnswerCreate"],
      };
    case "autonomous_question":
      if (!values.answers[0]?.trim()) return;
      return {
        path: `/projects/${e(item.registered_project_id)}/autonomous/runs/${id}/questions/${request}/answer`, once: true,
        body: { expected_version: request_version, text: values.answers[0] } satisfies S["AutonomousAnswerCreate"],
      };
  }
}
