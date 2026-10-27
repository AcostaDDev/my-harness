# One-off tasks

**Queue:** one pending task; no implementation has started.
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
Remove this task only after its acceptance is satisfied; then resume P001-T001 in
NEXT_STEPS without changing the Metrics Records plan or phase numbering.

**References:** AGENTS; D221–D227 and D236; specification §12; architecture §11;
`docs/flows/configuration-setup.md`; `docs/phase/failed-intake-activation.md`;
`tests/product/test_configuration*.py`, `test_project_registry.py`, `test_managed.py`,
`test_managed_api.py`, `test_chat_global.py`, `test_cli_discovery.py` and existing
planning/onboarding/preparation fixtures.
