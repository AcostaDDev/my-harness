# One-off tasks

**Queue:** two pending tasks; no implementation has started. Work in order: OT001, then OT002.
**Next: OT001 — Apply agent configuration without restarting the service.**

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

## OT001 — Apply agent configuration without restarting the service

**Status:** pending; next one-off task.
**Depends on:** D221–D227 and committed D236 (`ef77229`); no Metrics Records dependency.
**Objective:** apply ordinary agent configuration changes from the UI while the
service and authenticated session remain available, preserving frozen work and
recoverable configuration authority.

**Problem and current behavior:** global activation always records RESTART_REQUIRED;
ConfigurationSetup loads the active revision only at startup, and ManagedRuntime
and its workers hold the resulting clients/factories. Changing a timeout, model,
executable or PATH therefore requires a manual restart and login. Saving an invalid
client path can also leave a registered project uncomposed after activation.
D236 already fixes the independent deadlock caused by empty failed intake turns;
it must remain a completed prerequisite, not a new implementation task.

**Requested behavior / design gate:**

- Normal agent settings (timeouts, provider/model/effort, executable, explicit
  environment/PATH and affected client presets) can be reviewed and applied
  without reinstalling, restarting the HTTP service or replacing the login key.
- When idle, a confirmed candidate is validated and prepared before being made
  active. If validation/composition fails, the previous configuration and usable
  projects remain active; show the affected project/setting and correction.
- When affected work is executing or waiting, present an explicit pending state
  such as **Apply when current work finishes**, with the reason. A confirmed
  application may wait for a safe boundary; it must not terminate calls, retry
  failed work, advance phases, rewrite frozen jobs or start a model invocation.
- Already admitted jobs keep their exact configuration/versions and receipt
  bindings. Later jobs/turns use the new active configuration only after the
  switch. An executing call keeps its original timeout. Do not rebind queued work
  silently or require successful phase/intake completion to correct client settings.
- Classify fields that genuinely need process restart (service/storage/listener
  settings, where applicable) separately and explain them before confirmation.
  Do not implement a general HTTP restart endpoint or automatic software update.

Before changing runtime code, document the concrete switching/recovery design and
field classification in the task artifact and accepted decisions, explicitly
superseding only the affected restart rules of D222/D223/D227. Address both writer
and chat lanes, preparation/configuration assistance, admitted queued jobs, joint
global/project references and receipt compatibility. Do not infer that replacing
a single runtime field updates all captured factories or background workers.
The requested behavior above is the work scope, not a claim of an implemented or
fully settled technical design. Surface contradictions requiring a user decision.

**Implementation scope / allowed paths:** configuration setup/editing/activation,
project composition and managed runtime/supervisor services; affected configuration,
registry and job-admission storage helpers; configuration API and UI/catalogs; focused
synthetic tests; current docs and parity artifacts. Start with:
`src/my_harness/services/configuration_setup.py`, `configuration_editing.py`,
`managed_runtime.py`, `local_config.py`, `project_configuration.py`, `managed.py`;
`src/my_harness/storage/configuration.py`, `registry.py` and necessary admission
helpers; `src/my_harness/api/configuration.py`; `frontend/src/pages/Configuration.tsx`,
`frontend/src/configuration.ts` and affected project configuration controls.
Regenerate OpenAPI/client types for API changes. A justified additive model change
must include its migration/data diagram; do not assume one is required in advance.

**Forbidden scope:** Metrics Records, Continuous Mode, provider/model capability
expansion, modifying provider credentials or machine-wide configuration, automatic
package upgrades, new dependencies without a decision, migrations of operational
databases, live production/provider validation, weakening writer-recovery or
preparation gates, history/receipt/catalog rewrites and unconfirmed work execution.
The prior authorization to install/restart the earlier fix does not carry over to
installing or operating this new change.

**Acceptance criteria:**

- A valid timeout/model/client-path change can be saved, reviewed, confirmed and
  applied while the same server process and browser session remain valid. Later
  calls demonstrably use the new settings; no reinstall or new access key is needed.
- The candidate checks all affected registered project compositions, selected
  clients and exact executable/PATH/environment before switching. Missing client,
  missing Node for a launcher, incompatible CLI, invalid profile or a project
  composition failure leaves the complete previous authority usable. Editing a
  timeout alone preserves all unrelated fields, including advanced TOML fields;
  distinguish missing values from an explicitly requested removal in the diff.
- In-flight and queued work retain their frozen settings; both execution lanes
  and technical preparation obey the chosen safe-boundary policy. Empty failed
  intake is not resurrected as pending work. Uncertain writers are still resolved
  explicitly, and substantive proposals/receipts are preserved or revalidated by
  their existing confirmed lifecycle rather than silently rebound.
- Concurrent saves/confirmations, a changed candidate, cancellation and crashes
  before/during/after the switch have bounded, deterministic recovery. SQLite's
  active references and the clients actually used cannot disagree while new work
  is admitted. Failure cannot strand the installation on an unusable candidate.
- The UI shows saved/active/pending/failed states and actual impact in English and
  Spanish, with a clear distinction between applying configuration, preparing a
  technical profile and updating software. No generic stale-preview message hides
  a known missing client or pending-work reason. Query-only archives remain inert.
- Specification, architecture, affected flows and API/types match the implemented
  behavior and compatibility policy. Old revisions, failed attempts and snapshots
  remain unchanged. State/phase progress is reported honestly.

**Validation:** offline synthetic tests covering idle application, active/queued
writer and chat work, preparation/assistance, invalid client/PATH/Node/project,
field preservation, concurrent requests, pending cancellation, failure injection,
recovery and old configuration/backup/query-only behavior. Run the affected
configuration, registry, planning/admission and runtime suites; expand where the
implementation changes behavior. Run `node --test frontend/tests/*.test.mjs`,
`npm --prefix frontend run check` and `npm --prefix frontend run build` for UI/API
changes. Perform synthetic en/es functional/browser QA of applying while signed in;
record tested surfaces and omissions. No real providers, network installation or
user installation changes are required or authorized by this task entry.

**Expected deliverables:** reviewed switching/recovery design, implementation,
focused regressions, API/types and documentation parity, and
`docs/phase/OT001-live-agent-configuration.md` with exact evidence and limitations.
Remove this task only after its acceptance is satisfied; then handle any remaining
one-off entries. Resume P001-T001 in NEXT_STEPS only when this queue is empty,
without changing the Metrics Records plan or phase numbering.

**References:** AGENTS; D221–D227 and D236; specification §12; architecture §11;
`docs/flows/configuration-setup.md`; `docs/phase/failed-intake-activation.md`;
`tests/product/test_configuration*.py`, `test_project_registry.py`, `test_managed.py`,
`test_managed_api.py`, `test_chat_global.py`, `test_cli_discovery.py` and existing
planning/onboarding/preparation fixtures.


## OT002 — Answer pending reviewer questions individually or in one batch

**Status:** pending; after OT001 in queue order.
**Depends on:** D075/D102 conversational planning/onboarding and D237 queue rules;
no technical dependency on OT001. Use the existing question, version and message contracts.
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
