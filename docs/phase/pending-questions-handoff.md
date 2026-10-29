# Pending reviewer questions — documentation handoff

**Status:** OT002 specified, not implemented. No design plugin or provider invoked.
**Request:** show pending questions before the free-message form; provide answers
per question and an explicit individual/selected/all batch submission workflow.
**Queue:** completed; see [OT002 evidence](OT002-question-answers.md).

## Current evidence

- `frontend/src/pages/Planning.tsx` places MessageForm inside the conversation panel
  before Questions in onboarding and the shared definition workspace.
- MessageForm submits a single text message with the current conversation version
  through the existing workspace request/idempotency path; the current interface
  therefore accepts several question answers in one message.
- Questions renders the question text and, for open blocking questions, a deferral
  reason/action. That reason is not an answer field.
- `storage/planning.py:current_questions` selects the last ANSWERED turn's questions;
  ordinary messages do not deterministically resolve them. A follow-up reviewer
  response or the explicit deferral path governs the subsequent blockers.

## Intended change and boundaries

OT002 requests the question-first layout, accessible individual drafts, one-turn
batch composition, preserved unsent answers, explicit review state and unchanged
adoption/deferral semantics. It includes a requirement to use and report Claude
Code's actual frontend-design skill, not just claim a design review. The next
session must inspect the available plugin and respect its real permissions.

No frontend/backend/API or managed flow changed in this documentation extension.
OT001 remains first, OT002 follows without a technical dependency, and the existing
P001 Metrics Records task plan/ROADMAP are untouched. OT001's removal instructions
now correctly return to remaining queue entries rather than skipping to phase work.

## Verification

The completing session records static link/path, queue/order and unchanged product/
phase checks below before committing. No runtime tests or visual QA are required
for this documentation-only handoff, and no user screenshots/data were copied into
repository fixtures. This file is a work artifact; implementation evidence belongs
in `docs/phase/OT002-question-answers.md` when that task is actually completed.


Static verification: **PASS** for local Markdown links and existing code/test
references, queue order OT001 → OT002 and required contract/design-tooling fields.
**PASS** for unchanged product code, dependencies, NEXT_STEPS and ROADMAP, and
`git diff --check`. Diff reviewed; runtime tests and browser/plugin execution were
not performed because this change only specifies future work.
