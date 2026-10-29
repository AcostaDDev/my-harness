# P001 — Metrics Records (target: 0.1.9 at phase closure)

**Status:** active phase; T001 design, T002 calculator/references and T003 capture/storage complete; T004 aggregates/API
complete and delivered through `feat/p001-t004-aggregates-api` → `develop`/`origin`; T005a accounting UI complete as
source and delivered through `feat/p001-t005a-accounting-ui` → `develop`/`origin`; T005b controls complete and delivered
through `feat/p001-t005b-billing-controls` → `develop`/`origin` (D265), completing T005; T006 complete as source
qualification on `chore/p001-t006-qualification` ([evidence](phase/P001-T006-qualification.md)), with the 0.1.9
candidate metadata, delivered through that topic → `develop`/`origin`. T005 is split
into T005a (accounting UI) and T005b (billing/reference controls) by
[D263](DECISIONS.md#d263--p001-t005-split-accounting-page-and-billingreference-control-contracts).
**Next: the separately authorized 0.1.9 release and P001 closure**, then P002 planning. Every P001 task is complete as source.

Read [ONE_OFF_TASKS](ONE_OFF_TASKS.md) first. Pending one-off work takes precedence;
resume this unchanged phase plan when that queue is empty. The queue is **empty**: OT008 (development checks, D260) was
delivered source-only into `develop` and did not change this plan.

Objective and exit criteria: [ROADMAP](ROADMAP.md#p001--metrics-records).
Scope and code map: [phase handoff](phase/P001-metrics-records.md).
Pricing research: [reference notes](phase/P001-metrics-records-references.md).
Decisions: [D232](DECISIONS.md#d232--metrics-records-phase-and-accounting-boundaries),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020) and
[D234](DECISIONS.md#d234--p001-task-plan-in-next_steps).

The completed intake/configuration fix is documented in
[failed-intake-activation](phase/failed-intake-activation.md) and committed as
`ef77229`. It does not complete or reorder any Metrics Records task.

The [one-off queue](ONE_OFF_TASKS.md) is **empty**. OT007 was released and installed as **0.1.8** through
[PR #7](https://github.com/AcostaDDev/my-harness/pull/7), merge/tag **`c005298` / `v0.1.8`**
([D252](DECISIONS.md#d252--managed-run-lease-renewal-chunk-journals-and-interrupted-process-evidence),
[evidence](phase/OT007-task-run-lease.md)). Its draft/public archive and checksum downloads were verified byte for
byte; the offline operator installation is READY with the service stopped and data/configuration unchanged.
**Next: 0.1.9 release and P001 closure.** Earlier one-off releases remain documented in STATE and their evidence; those releases did not
complete a Metrics Records task. T001 is complete as accepted design/inventory (D254–D257).

The sections below retain each task's contract and distinguish completed work from pending integration. T001 settled
the technical contract; T002 implements the isolated pure calculator/references, without operational integration.
The owner confirmed **P001 → 0.1.9** and **P002 → 0.2.0**, published at each
phase closure ([D253](DECISIONS.md#d253--phase-release-targets-after-018)); `0.1.8` is already the OT007 release.
T001 was delivered through `docs/p001-t001-accounting-contract` → `develop`.
There is no task release or runtime version bump; release qualification/publication remains at P001 closure.
T002 uses `feat/p001-t002-reference-calculator` → `develop`/`origin` with the same explicit task delivery authorization;
its [evidence](phase/P001-T002-reference-calculator.md) separates source integration from future distribution.
T003 used `feat/p001-t003-capture-storage` → `develop`/`origin` with the same explicit owner authorization
([evidence](phase/P001-T003-capture-storage.md)). T004 used `feat/p001-t004-aggregates-api` → `develop`/`origin` with
the same explicit owner authorization ([evidence](phase/P001-T004-aggregates-api.md)). The T005 split and its
contracts (D263) were recorded through `docs/p001-t005-split` → `develop`/`origin` before any T005 code. T005a used
`feat/p001-t005a-accounting-ui` → `develop`/`origin` with the same explicit owner authorization
([evidence](phase/P001-T005-metrics-ui.md#t005a--accounting-ui)). T005b used `feat/p001-t005b-billing-controls` →
`develop`/`origin` with the same authorization. T006 used `chore/p001-t006-qualification` → `develop`/`origin` with the
same authorization; the release PR/tag/publication and closure are later, separately authorized actions.

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

**Status:** complete (accepted design/inventory only; no runtime implementation).
**Depends on:** D232–D234 and the implemented D074 baseline.
**Evidence:** [accounting contract](phase/P001-T001-accounting-contract.md), source observation/digest and synthetic
acceptance matrix; D253–D257. Topic delivery: `docs/p001-t001-accounting-contract` → `develop`; exact verification
and delivery status are in the evidence artifact. The criteria below are retained as the completed task contract.
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

**Status:** complete (pure library and packaged references; operational integration remains T003–T005).
**Evidence:** [reference/calculator checks and delivery](phase/P001-T002-reference-calculator.md), D258.
**Depends on:** completed T001, D254–D257 and its [accounting/reference contract](phase/P001-T001-accounting-contract.md).
**Objective:** implement an offline, reproducible calculator and the approved model/tariff reference representation.
**Allowed paths:** `src/my_harness/core/engine/**`, packaged reference files and packaging metadata identified by
T001 (`core/engine/` packaged JSON and existing package-data metadata), focused `tests/**`, and current
documentation. No execution-adapter or operational database change here. The T001 observation file is immutable
research evidence, not an already implemented catalog; construct runtime references separately.
**Acceptance criteria:**

- Implement separate model identity and tariff references with immutable identity/content digest, source,
  observation date, known effective period or explicit unknown, billing unit and applicable conditions. Cover the
  initial suggested models with sourced references; custom/unpriced identifiers stay visible and unresolved.
- Calculate line items from disjoint uncached input, cache read, applicable cache-write lifetime and output
  categories. Apply D256/T001 precision 160, exact lines and once-per-invocation half-even rounding to 12 places;
  reasoning already included in output is not added. Cover T001 A01–A14/A20–A26 with pinned evidence, including
  Responses-API write semantics as a separate evidence contract, never an assumed Codex CLI capability.
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

**Status:** complete (native capture, additive records, frozen billing binding, explicit cohorts and format-3 archives;
queries/API remain T004 and controls/UI T005). **Evidence:** [capture/storage checks](phase/P001-T003-capture-storage.md),
D259. The criteria below are retained as the completed task contract.
**Depends on:** completed T002; record/billing-profile contracts accepted in T001.
**Objective:** persist detailed usage and immutable valuations with the evidence required to reproduce them.
**Allowed paths:** relevant `src/my_harness/adapters/**`, `src/my_harness/core/engine/**`,
`src/my_harness/storage/**`, `src/my_harness/services/**`, `src/my_harness/migrations/**` and
`src/my_harness/cli.py`; relevant configuration/accounting backend routes in `src/my_harness/api/**` when needed;
focused `tests/**`; current docs and parity artifacts if a contract changes. This T001 refinement puts the native
preparation/assistance ledger, v10/v2 billing binding, reference import backend, explicit accounting cohorts and
format-3 backup in T003, before T004 query contracts and T005 controls; it does not start those implementations.
**Acceptance criteria:**

- Capture only fields supported by the evidence matrix, preserving exact requested/reported identities, source
  provenance and provider token semantics. Handle missing terminal, cumulative deltas, partial/failing/interrupted
  work, multiple models/delegation and assistance records according to T001 without double counting.
- Add the approved usage/valuation/reference records and frozen billing-profile binding through the existing
  configuration authority. Never change authentication or overwrite previous metric/history/configuration bytes.
  Define deduplication and transaction/recovery behavior so retries cannot duplicate consumption or amounts.
- Provide the explicit idempotent backfill/repricing policy adopted in T001. Keep new interpretations identifiable,
  leave original `metrics-1` values and phase snapshots intact, and report incomplete historical evidence.
- Preserve `metrics-backfill`; new accounting backfill/repricing needs explicit preview/confirmation and named
  closed cohorts, with original admission-bound totals remaining the default (D257).
- Include new records/references in retention and verified backup/restore. T003 owns format 3 and the documented
  schema-scoped legacy-bundle/explicit archive-copy upgrade path. Query-only consultation works without
  original roots, clients, network, executable configuration or mutations; reading cannot backfill or recalculate.
- Update the data diagram and affected capture/configuration/migration/backup flows in the same task. If an API
  contract is touched, export OpenAPI and regenerate types as required by shared constraints.

**Validation:** synthetic stream/parser and persistence cases; idempotence, injected failure/recovery, old/new
database fixtures, snapshot-before-migration, retention and backup/restore. Run relevant metrics, configuration,
backup/retention and migration tests; run `alembic check` only against a prepared temporary database.
**Deliverables:** capture/storage/configuration changes, additive migration if needed, parity docs/tests and
`docs/phase/P001-T003-capture-storage.md` with compatibility and coverage evidence.

## P001-T004 — Aggregates and API

**Status:** complete as source (bounded read-only `accounting-aggregate-1` queries and `GET /api/managed/accounting/*`;
OpenAPI/types regenerated; delivered through its topic → `develop`/`origin` merge). **Evidence:** [aggregates/API checks](phase/P001-T004-aggregates-api.md),
D262. The criteria below are retained as the completed task contract.
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

**Status:** complete (T005a and T005b delivered); split into two sequential deliveries by
[D263](DECISIONS.md#d263--p001-t005-split-accounting-page-and-billingreference-control-contracts). T005 is complete
when T005a and T005b are both delivered; their combined criteria below are the task contract.
**Depends on:** completed T004 and T001's configuration/reference workflow.
**Objective:** let the operator select the billing basis and inspect detailed consumption, valuations and evidence.
**Acceptance criteria (whole task):**

- Expose the approved billing-profile/reference workflow through the existing configuration system, with validation,
  exact preview/confirmation, version/conflict handling and frozen jobs preserved. Saving billing metadata must not
  log in to a provider, change its credentials or affect machine-wide settings. (T005b)
- Show provider/model token breakdowns, cache categories, durations, tools, outcomes and provenance where available;
  identify requested versus verified model and explain missing details without inventing data. (T005a)
- Distinguish client-reported estimates, calculated monetary values, credits and any confirmed billing evidence.
  Show tariff applicability/source, line items, discrepancy, staleness/unknowns and priced/unpriced coverage.
  Do not present subscription-equivalent valuation as an actual extra charge. (T005a)
- Keep filters, tables and details bounded, navigable and localized in English/Spanish. Offline archive pages show
  historical references/values without configuration mutation controls, automatic recalculation or operational
  polling. (both)

**Deliverables:** configuration/metrics UI, catalogs and relevant parity/tests, plus
`docs/phase/P001-T005-metrics-ui.md` (one section per delivery) with visual and functional evidence.

### P001-T005a — Accounting UI

**Status:** complete as source (D264, [evidence](phase/P001-T005-metrics-ui.md#t005a--accounting-ui)) and delivered
through `feat/p001-t005a-accounting-ui` → `develop`/`origin` with explicit owner authorization. No release or version bump. The criteria below are retained as the task contract.
**Depends on:** completed T004 (D262) and D263.
**Objective:** a read-only accounting page over `/api/managed/accounting/*`, without API, schema or backend change.
**Allowed paths:** `frontend/src/**`, `frontend/tests/**`, en/es catalogs and current documentation.
**Acceptance criteria:**

- A new page, global and per project, linked from Statistics and the project; Statistics keeps its `metrics-1`
  panels and wording. Available on a query-only archive without mutation controls or polling.
- Summary with coverage (expected, not invoked, launch states, captures, complete/partial/absent usage,
  priced/unpriced with grouped reasons) and one amount per compatible bucket: `amount` only when the API gives it,
  otherwise the known subtotal labelled partial. Bases (API USD, Enterprise USD, credits, subscription equivalent,
  reported estimates) stay separate; subscription equivalents are labelled counterfactual, never a charge.
- Token categories with contributor/partial counts, cache-hit and wall-throughput indicators with their excluded
  counts, and task indicators with their denominators; null is "no data", never zero.
- Paginated groups over the D262 dimensions and a filtered, paginated invocation list; the invocation detail shows
  requested versus effective model and its kind, provider/client, provenance, durations, tools, outcome and the
  paginated valuations with line items, tariff/identity reference (source, observation age, effective-period state),
  discrepancy and unknown reasons.
- Selection policy: the original admission valuation by default or one named cohort; a `BUILDING` cohort is shown as
  incomplete. Backfill/repricing are named as CLI commands only (D263).

**Validation:** focused Node tests for the new formatting/query helpers, `node --test frontend/tests/*.test.mjs`,
`npm --prefix frontend run check` and `npm --prefix frontend run build`; synthetic visual QA in en/es, light/dark,
desktop/mobile, keyboard navigation and a query-only archive. Record tested surfaces and omissions.

### P001-T005b — Billing-profile and reference controls

**Status:** complete as source (D265, [evidence](phase/P001-T005-metrics-ui.md#t005b--billing-profile-and-reference-controls))
and delivered through `feat/p001-t005b-billing-controls` (branched from `develop` at `0d51449`) → `develop`/`origin`
with explicit owner authorization. No release or version bump.
The criteria below are retained as the task contract.
**Depends on:** completed T005a and D263.
**Objective:** edit billing profiles/selections and import references through the existing configuration system.
**Allowed paths:** `frontend/src/**`, `frontend/tests/**`, `src/my_harness/api/configuration.py`,
`src/my_harness/api/project_configuration.py`, `src/my_harness/api/schemas.py`, `src/my_harness/services/**`,
`src/my_harness/storage/accounting_operations.py` and related storage modules, focused `tests/**`,
`frontend/openapi.json`, `frontend/src/api.generated.ts` and current documentation (flows/diagram if affected).
**Acceptance criteria:**

- Explicit, previewed conversion to `local-config-10`/`project-config-2`; guided controls for global profiles
  (add/edit/remove, conditions with their source) and per-role defaults, and for per-role project selections, under
  the D250 form rules. The TOML editor stays complete; loading never converts.
- Server save-time validation of D263: unavailable reference bundle, missing or provider-mismatched explicit
  project selection and removal/provider change of a profile still selected by a derived project copy are refused
  with named fields/projects; inherited defaults that would resolve unknown are reported in the preview effects.
- `GET /api/managed/configuration/references`, `POST …/references/preview` and `POST …/references/import` over the
  T003 backend, with the idempotent preview digest of D263; bundle size limit, conflicts and the restored-archive
  refusal kept; the list also works on an archive. OpenAPI exported and client types regenerated.
- Billing-only saves keep technical receipts; frozen jobs keep their binding; no authentication, credentials or
  machine-wide settings change.

**Validation:** focused pytest for configuration/billing validation and the reference routes (synthetic bundles,
temporary SQLite), the full `scripts/check --frontend`, `scripts/check-docs`; synthetic visual QA of the controls in
en/es, light/dark, desktop/mobile and keyboard, and their absence on a query-only archive.

## P001-T006 — Qualification and phase handoff

**Status:** complete as source qualification ([evidence](phase/P001-T006-qualification.md)): criterion/evidence
matrix, integrated synthetic journey (`tests/product/test_p001_qualification.py`), installed-wheel accounting reads,
served-archive browser QA, invocation-label fix, 0.1.9 candidate metadata and changelog/upgrade notes, P002 handoff.
Release, publication, P001 closure and installation were not performed.
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
guarantees. Its design and task plan remain pending; start from the
[T006 handoff](phase/P001-T006-qualification.md#p002-handoff).
