# One-off tasks

**Queue:** one pending task; its implementation has not started.
**Next: OT002 — Answer pending reviewer questions individually or in one batch.**

Read after [STATE](STATE.md), before [NEXT_STEPS](NEXT_STEPS.md). This queue is for
bounded fixes, improvements and design changes outside a complete roadmap phase.
It belongs to development of this repository; the harness does not execute this
file or use it as a new project-document contract.

## Queue rules

- Normally there are no task sections. When empty, retain this introduction/rules,
  set Queue to **empty** and Next to **continue with NEXT_STEPS.md**.
- Pending/in-progress tasks take precedence over phase work. Work on one bounded
  task at a time, in the stated dependency/order. An explicit user instruction can
  override the order. A blocked task stays visible with its missing prerequisite;
  do not silently skip it or resume the roadmap as if it were complete.
- Use stable, phase-independent IDs `OTNNN` and the contract fields below. Allocate
  the next unused ID from retained work artifacts/Git history; never reuse an ID.
  Do not assign these tasks phase numbers or mark a phase task complete for them.
- Before removing a completed task, satisfy its acceptance, review the diff, run
  relevant checks and record results/omissions in `docs/phase/OTNNN-<topic>.md`.
  Record durable choices in DECISIONS and update affected current docs/parity.
  Then remove the entire task section and update Queue/Next. Completed tasks and
  their history do not accumulate here. Commit only when the user requests it.
- Keep scope proportional. If work needs multiple independently planned tasks or
  a full phase, surface that before implementation instead of growing this queue
  into a second roadmap. Follow AGENTS and its authorization/data rules throughout.

## OT002 — Answer pending reviewer questions individually or in one batch

**Status:** pending; next one-off task (OT001 completed in `0.1.2`).
**Depends on:** D075/D102 conversational planning/onboarding and D237 queue rules;
no technical dependency on OT001 (completed). Use the existing question, version and message contracts.
**Objective:** make pending questions the primary next action in documentary
conversations, with per-question answers that can be sent individually, as a
selected batch or all together in one explicit reviewer turn.

**Problem and current behavior:** onboarding renders the free-message form before
the latest questions. Each blocking question offers only a deferral reason/action;
actual answers must be composed manually in the generic message box. The existing
endpoint accepts one text message per turn; questions are derived from the latest
ANSWERED turn, not marked resolved merely because text was submitted. The interface
does not explain that several answers can be sent in one message.

**Implementation scope / allowed paths:** `frontend/src/pages/Planning.tsx`,
focused question/answer state and UI helpers, shared styles and en/es catalogs;
focused frontend tests; current documentation/flows. Cover onboarding and the shared
new-project definition workspace consistently. Keep unrelated page redesign out of
scope. Start with the existing `Questions`, `MessageForm`, conversation version and
workspace request/idempotency handling. Extend backend/API only if the requested
behavior cannot preserve existing contracts; then update storage/flow documentation
and regenerate OpenAPI/client types in the same task.

**Design tooling:** use Claude Code's frontend-design plugin/skill for this UI work
(the expected invocation is `frontend-design:frontend-design`; verify its actual
availability in that session). Record the real invocation and resulting design work.
If unavailable/denied, report that blocker; do not claim use, install it over the
network, change global plugin permissions or launch Claude/provider calls merely
because this task names the tool. The owner will use that plugin in the implementation
session; this entry does not execute it or authorize paid/real-provider tests here.

**Acceptance criteria:**

- Pending blocking questions appear before the generic reviewer-message composer,
  with informative questions and declared pending items clearly distinguished.
  The visual and keyboard reading order agree. No questions disappear merely
  because a message failed or a newer turn is still running.
- Each question has an accessible answer field. Users can prepare answers one by
  one without triggering a model call. They can explicitly send one answer, a
  selected set, or all prepared answers in one batch; each accepted submission creates
  exactly one turn, never one hidden call per question.
- A reviewable composed message preserves each selected question's identity/text
  and its answer, with optional additional context. Empty/unselected answers are
  not submitted or treated as deferrals. Partial submission leaves unanswered
  questions and unsent drafts visible. Enforce the aggregate message limit without
  silent truncation or automatic splitting into extra turns.
- Show distinct draft, submitted/awaiting-review and reviewer-resolved states.
  Sending an answer does not itself close a blocker or make adoption available;
  retain the existing successful-review/explicit-deferral rules. Deferral remains
  a separate intentional action requiring a reason, not a substitute answer box.
- Preserve answer drafts across polling, refresh/navigation and request errors;
  isolate them by conversation and question/source turn. A new question set or
  stale version must not silently overwrite text, attach an answer to a different
  question or resend it. Offer an explicit review/reconciliation path. Prevent
  duplicate submissions while a turn is queued; keep CAS/idempotency semantics.
- Keep free conversation available for follow-up and general context, without
  competing answer entry points that send the same text twice. Use English and
  Spanish text, clear labels, focus/error handling and responsive layouts in both
  themes. Read-only/archive and completed conversations offer no mutation controls.

**Forbidden scope:** changing question resolution or adoption rules, automatically
answering/deferring questions, automatic provider calls, removing blockers to bypass
profile requirements, a new chat engine, global redesign, new dependencies without
a recorded decision, and implementing any Metrics Records/Continuous Mode work.

**Validation:** synthetic frontend/component/request tests for ordering, individual,
selected/all batch submission, partial answers, aggregate limit, draft persistence,
question/version changes, failures, queued/double clicks and explicit deferral.
Run `node --test frontend/tests/*.test.mjs`, `npm --prefix frontend run check` and
`npm --prefix frontend run build`. Run focused planning/onboarding API tests if
contracts change. Perform synthetic visual/functional QA in en/es, light/dark,
desktop/mobile and keyboard-only navigation; record actual checks and omissions.
Do not copy the user's project, screenshots, runs or private answers into fixtures.

**Expected deliverables:** the question-first UI and batch workflow, meaningful
regressions, catalogs and any required contract/flow parity, plus
`docs/phase/OT002-question-answers.md` with design-plugin evidence, checks and limits.
After acceptance, record evidence and remove this entry. Resume the phase plan
only when no one-off tasks remain.

**References:** `frontend/src/pages/Planning.tsx` (`Questions`, `MessageForm`,
`Definition`/`ImportConversation`), `frontend/src/workspace.tsx`,
`src/my_harness/storage/planning.py` (`current_questions`, message submission and
explicit deferral), `docs/flows/project-onboarding.md`, D075/D102/D237;
`tests/product/test_onboarding_conversation.py` and existing frontend request/render fixtures.
