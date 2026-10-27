# P001 — Metrics Records (target: next patch after the one-off queue)

**Status:** active phase; six tasks pending, implementation not started.
**Next phase task: P001-T001 — Accounting contract and evidence inventory.**

Read [ONE_OFF_TASKS](ONE_OFF_TASKS.md) first. Pending one-off work takes precedence;
resume this unchanged phase plan when that queue is empty.

Objective and exit criteria: [ROADMAP](ROADMAP.md#p001--metrics-records).
Scope and code map: [phase handoff](phase/P001-metrics-records.md).
Pricing research: [reference notes](phase/P001-metrics-records-references.md).
Decisions: [D232](DECISIONS.md#d232--metrics-records-phase-and-accounting-boundaries),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020) and
[D234](DECISIONS.md#d234--p001-task-plan-in-next_steps).

The completed intake/configuration fix is documented in
[failed-intake-activation](phase/failed-intake-activation.md) and committed as
`ef77229`. It does not complete or reorder any Metrics Records task.

[ONE_OFF_TASKS](ONE_OFF_TASKS.md) currently takes precedence: **OT005 preparation tool links hotfix → 0.1.5**,
then **OT004 visual profile/agent editor → 0.1.6** (D246 supersedes D243's target/order). OT005 source is implemented
and qualified on `fix/ot005-preparation-tool-links`; integration and separate 0.1.5 delivery remain pending. OT004
is unimplemented. Resume from [OT005's evidence/delivery status](phase/OT005-preparation-tool-links.md) before
starting the next one-off. Source commit `e2d62fe` is installed after an authorized offline reinstall/restart;
the owner will test manually. Their success report authorizes the separate 0.1.5 archive/release PR/GitHub publication.
[OT003](phase/OT003-intake-profile-diagnostics.md), including adoption and joint review (D244/D245), was released
as **0.1.4** through PR #3 and its archive/checksum were verified after download.
Resume P001-T001 after these one-offs are completed or explicitly rerouted. No phase task is completed by them.

The sections below are the current task plan, not implemented features. T001 settles the technical contract before
T002–T005 change runtime behavior. The target release is the patch version that follows the one-off releases
([D239](DECISIONS.md#d239--one-off-tasks-released-as-patch-versions)); OT001 shipped `0.1.2` and OT002 `0.1.3`.

## Shared constraints

- One bounded task at a time, developed manually; do not operate this repository with the harness. Preserve
  concurrent edits. No commits unless requested; no push, tag or publication under this plan.
- Real clients/providers, paid calls, network installation and private billing data need separate authorization.
  Use synthetic fixtures, temporary Git/SQLite and fake clients; do not change machine-wide configuration or add
  a dependency without a recorded decision. Inspect sources without copying credentials, logs or private runs.
- Claude Code and Codex are the execution clients in scope. New provider adapters, automatic phase transitions
  (P002), billing-account integrations and inferred subscription quotas are outside P001.
- Preserve `metrics-1`, old configuration hashes, histories, frozen summaries/catalogs and recipe fingerprints.
  Missing is not zero; requested model is not verified effective model; terminal and constituent usage are not added.
  USD, credits, reported estimates, local valuations and confirmed billed amounts remain distinguishable.
- A model/migration change updates `docs/DDBB-DIAGRAM.md`; a flow change updates the affected `docs/flows/`;
  API contracts update `frontend/openapi.json` and generated client types in the same task. Keep en/es text in parity.
- Record durable choices in [DECISIONS](DECISIONS.md), and task evidence in `docs/phase/`, with checks, omissions
  and limitations. Complete each task's acceptance and relevant checks before the next; update STATE/NEXT_STEPS.
- [AGENTS](../AGENTS.md) and [README](../README.md#development) list existing offline commands. Establish the current
  baseline: with `.local/npm-cache` filled as in the README the full Python suite passed (2048 passed, 2 skipped;
  [npm cache baseline](phase/test-npm-cache-baseline.md)). Report current failures; do not assume they are waived
  or caused by P001. Each task uses its own topic branch from `develop`
  ([D235](DECISIONS.md#d235--release-branch-integration-branch-and-topic-branches)).

## P001-T001 — Accounting contract and evidence inventory

**Status:** pending; next task.
**Depends on:** D232–D234 and the implemented D074 baseline.
**Objective:** define the accounting contract and supported billing cases before changing capture, storage or API.
**Allowed paths:** current `docs/**`; archived histories and frozen sources are read-only.
**Acceptance criteria:**

- Inventory every invocation lane and persistence path: planning, execution/revision, review, phase work, chat,
  definition/onboarding/bootstrap and configuration assistance. Identify deterministic no-model operations and
  unsupported sources instead of manufacturing managed attempts.
- Produce a Claude/Codex capability matrix for exact reported model, token semantics, reasoning, cache lifetimes,
  speed, request-size tiers, tool charges, failures and interruptions. Distinguish captured fields, available but
  uncaptured fields and data not established by supported CLI evidence; no real invocation is required.
- Revalidate the official sources in the reference notes, including conflicting pages, applicability and model
  identity. Define API USD, applicable credit schemes and subscription-equivalent valuation without assuming API
  credentials, universal credit conversion, invoice accuracy or allowance balances.
- Decide record grain/identity, billing-profile ownership/activation, reference versioning and binding, decimal
  precision/rounding, modifiers, coverage, discrepancy handling and unknown reasons. Resolve the open questions in
  the handoff, including compatibility, additive persistence, explicit backfill/repricing and backup/restore.
- Record technical decisions and a synthetic acceptance matrix; update specification/architecture and any planned
  data/flow design with explicit implementation status. Refine later task boundaries only through an explained
  documentation change. Ask about inconsistencies with accepted design rather than silently changing it.

**Validation:** read-only comparison with code, D074/D144/D150/D173–D174/D216–D228/D231–D234 and official sources;
check links, task dependencies, formulas and missing-evidence cases. No migration, product change or provider call.
**Deliverables:** `docs/phase/P001-T001-accounting-contract.md`, capability/acceptance matrices in that artifact,
accepted decisions and updated current design documentation.

## P001-T002 — Versioned references and pure calculator

**Status:** pending.
**Depends on:** completed T001 and its accounting/reference contract.
**Objective:** implement an offline, reproducible calculator and the approved model/tariff reference representation.
**Allowed paths:** `src/my_harness/core/engine/**`, packaged reference files and packaging metadata identified by
T001, focused `tests/**`, and current documentation. No execution-adapter or operational database change here.
**Acceptance criteria:**

- Implement separate model identity and tariff references with immutable identity/content digest, source,
  observation date, known effective period or explicit unknown, billing unit and applicable conditions. Cover the
  initial suggested models with sourced references; custom/unpriced identifiers stay visible and unresolved.
- Calculate line items from disjoint uncached input, cache read, applicable cache-write lifetime and output
  categories. Apply T001's decimal/rounding and modifier policy; reasoning already included in output is not added.
- Return quantity/rate/reference evidence and complete/incomplete/unsupported status with reasons. Unknown model,
  scheme, TTL, tier or modifier cannot silently become Standard pricing or zero cost. Keep units and bases separate.
- Pin source data for offline use; a new reference never edits an earlier version. Keep source refresh outside
  ordinary calculation and reads. Do not claim current research tables establish historical tariff validity.

**Validation:** focused offline tests with pinned synthetic references and hand-calculated expectations, covering
the companion examples, TTL/tier boundaries, speed/region/contract cases, rounding, alias drift, invalid quantities,
missing/conflicting references and preservation of old reference versions. No network-dependent test or live model.
**Deliverables:** calculator/reference implementation, focused tests and `docs/phase/P001-T002-reference-calculator.md`
with exact checks and supported/unsupported cases.

## P001-T003 — Capture, storage and historical compatibility

**Status:** pending.
**Depends on:** completed T002; record/billing-profile contracts accepted in T001.
**Objective:** persist detailed usage and immutable valuations with the evidence required to reproduce them.
**Allowed paths:** relevant `src/my_harness/adapters/**`, `src/my_harness/core/engine/**`,
`src/my_harness/storage/**`, `src/my_harness/services/**`, `src/my_harness/migrations/**` and
`src/my_harness/cli.py`; focused `tests/**`; current docs and parity artifacts if a contract changes.
**Acceptance criteria:**

- Capture only fields supported by the evidence matrix, preserving exact requested/reported identities, source
  provenance and provider token semantics. Handle missing terminal, cumulative deltas, partial/failing/interrupted
  work, multiple models/delegation and assistance records according to T001 without double counting.
- Add the approved usage/valuation/reference records and frozen billing-profile binding through the existing
  configuration authority. Never change authentication or overwrite previous metric/history/configuration bytes.
  Define deduplication and transaction/recovery behavior so retries cannot duplicate consumption or amounts.
- Provide the explicit idempotent backfill/repricing policy adopted in T001. Keep new interpretations identifiable,
  leave original `metrics-1` values and phase snapshots intact, and report incomplete historical evidence.
- Include new records/references in retention and verified backup/restore. Query-only consultation works without
  original roots, clients, network, executable configuration or mutations; reading cannot backfill or recalculate.
- Update the data diagram and affected capture/configuration/migration/backup flows in the same task. If an API
  contract is touched, export OpenAPI and regenerate types as required by shared constraints.

**Validation:** synthetic stream/parser and persistence cases; idempotence, injected failure/recovery, old/new
database fixtures, snapshot-before-migration, retention and backup/restore. Run relevant metrics, configuration,
backup/retention and migration tests; run `alembic check` only against a prepared temporary database.
**Deliverables:** capture/storage/configuration changes, additive migration if needed, parity docs/tests and
`docs/phase/P001-T003-capture-storage.md` with compatibility and coverage evidence.

## P001-T004 — Aggregates and API

**Status:** pending.
**Depends on:** completed T003 and its stable records.
**Objective:** expose bounded, explainable usage and cost analysis by provider/model and work context.
**Allowed paths:** `src/my_harness/storage/metrics.py`, relevant projection/query modules in
`src/my_harness/storage/**`, `src/my_harness/api/**`, affected documentary-consumption modules in
`src/my_harness/core/engine/**`, focused tests, `frontend/openapi.json`, generated
`frontend/src/api.generated.ts` and current documentation.
**Acceptance criteria:**

- Query details, reference identity, line items and discrepancies with explicit limits/pagination. Preserve
  existing consumers according to T001; do not decode whole histories, reprice records or invoke clients on reads.
- Support provider, effective model and requested model as distinct dimensions, plus role, project, phase, task,
  purpose and time. Define mixed-model/parent-child totals without adding the same usage or cost twice.
- Separate compatible units/bases and expose priced/unpriced and missing-row coverage with reasons. Report
  zero distinctly from absent; incomplete amounts cannot be labelled as the full scope cost.
- Distinguish accepted-task work, retries/revisions and conversational consumption. Cache ratios, cost per accepted
  task and duration/throughput use explicit denominators and sufficient evidence, without model-quality claims.
- Preserve immutable phase summaries and restored read-only behavior. Update API descriptions, export OpenAPI
  and regenerate client types; document the actual query/aggregation behavior.

**Validation:** focused metrics/API/projection tests with synthetic mixed providers/models, purposes, outcomes,
units, missing records, historical references and page boundaries. Verify read-only/offline behavior, old payload
compatibility and no full-history reads; check generated types using the existing README commands.
**Deliverables:** query/API implementation, OpenAPI/types and tests, affected docs and
`docs/phase/P001-T004-aggregates-api.md` with coverage and compatibility results.

## P001-T005 — Billing/reference controls and metrics UI

**Status:** pending.
**Depends on:** completed T004 and T001's configuration/reference workflow.
**Objective:** let the operator select the billing basis and inspect detailed consumption, valuations and evidence.
**Allowed paths:** `frontend/src/**`, `frontend/tests/**`, relevant configuration/API/service/storage modules to
complete the approved workflow, tests and current documentation; diagram/flows/OpenAPI/types when affected.
**Acceptance criteria:**

- Expose the approved billing-profile/reference workflow through the existing configuration system, with validation,
  exact preview/confirmation, version/conflict handling and frozen jobs preserved. Saving billing metadata must not
  log in to a provider, change its credentials or affect machine-wide settings.
- Show provider/model token breakdowns, cache categories, durations, tools, outcomes and provenance where available;
  identify requested versus verified model and explain missing details without inventing data.
- Distinguish client-reported estimates, calculated monetary values, credits and any confirmed billing evidence.
  Show tariff applicability/source, line items, discrepancy, staleness/unknowns and priced/unpriced coverage.
  Do not present subscription-equivalent valuation as an actual extra charge.
- Keep filters, tables and details bounded, navigable and localized in English/Spanish. Offline archive pages show
  historical references/values without configuration mutation controls, automatic recalculation or operational polling.

**Validation:** focused frontend/configuration/API checks, `node --test frontend/tests/*.test.mjs`,
`npm --prefix frontend run check` and `npm --prefix frontend run build`; synthetic visual QA in en/es, light/dark,
desktop/mobile, keyboard navigation and query-only archive. Record tested surfaces and omissions.
**Deliverables:** configuration/metrics UI, catalogs and relevant parity/tests, plus
`docs/phase/P001-T005-metrics-ui.md` with visual and functional evidence.

## P001-T006 — Qualification and phase handoff

**Status:** pending.
**Depends on:** completed T001–T005 and their evidence.
**Objective:** qualify P001 against its exit criteria and prepare the documented release result and P002 handoff.
**Allowed paths:** current docs, focused qualification tests/scripts and, when preparing the release candidate,
the existing shared package/API/UI version locations and lockfiles. Product fixes remain bounded, documented work.
**Acceptance criteria:**

- Map every roadmap criterion to implementation and check evidence. Exercise synthetic capture → records →
  valuation → aggregates/API/UI → retention → backup/query-only restore without real account data or calls.
- Run relevant regression and compatibility checks, record exact results and compare any existing failures with
  the baseline; unresolved failures/unsupported billing cases remain visible rather than silently accepted.
- Prepare upgrade notes and consistent candidate version metadata for the target patch only after the implemented result is
  qualified. Use existing local build/check procedures if offline dependencies are available; otherwise state what
  remains unverified. Building does not authorize network installation, commit, tag, push or publication.
- Reconcile specification, architecture, data/flows, API/types, operator documentation, source/reference versions
  and limits. Distinguish synthetic evidence from real validation, and valuation from invoice reconciliation.
- Update STATE/NEXT_STEPS honestly and provide the P002 Continuous Mode starting context for `0.2.0`. Do not close
  a phase, launch the harness or publish merely to complete this documentation checklist.

**Validation:** offline unittest/pytest suites, temporary-database migration/schema checks, frontend tests/types/build
and synthetic integrated journeys; local package verification when available, using AGENTS/README commands.
No real provider/billing validation is implied; report every skipped check and unresolved failure.
**Deliverables:** `docs/phase/P001-T006-qualification.md`, criterion/evidence matrix, upgrade/release-candidate notes
and current phase/P002 handoff documentation. Publication remains a separately authorized action.

## Upcoming phase — P002 Continuous Mode (target 0.2.0)

After P001, [Continuous Mode](ROADMAP.md#p002--continuous-mode) will automate phase closure/archive and opening/planning
of the next phase under an explicit bounded authorization, with stop conditions and existing READY/recovery
guarantees. Its design and task plan remain pending.
