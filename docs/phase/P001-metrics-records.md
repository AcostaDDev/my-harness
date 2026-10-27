# P001 — Metrics Records

Status: active documentation phase; initialized on 2026-10-27, no implementation started. Target release: `0.1.2`.
Authority: [D232](../DECISIONS.md#d232--metrics-records-phase-and-accounting-boundaries) for accounting scope;
[D233](../DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020) for phase order and version.
The task plan and statuses live in [NEXT_STEPS](../NEXT_STEPS.md), as recorded by
[D234](../DECISIONS.md#d234--p001-task-plan-in-next_steps); all six tasks are pending, starting with P001-T001.
This handoff is intended to let an agent start without the conversation that motivated it.

## Purpose and reading order

The user wants detailed metrics for each provider and model, cost analysis and reference data sufficient to explain
and reproduce each calculation. Today's expense display captures reported amounts but cannot independently price
Codex tokens or select a billing scheme. The desired outcome is trustworthy accounting with visible limits, rather
than an unconditional promise of invoice accuracy from incomplete CLI output.

Read, in order:

1. [AGENTS](../../AGENTS.md), [STATE](../STATE.md), [NEXT_STEPS](../NEXT_STEPS.md) and
   [the P001 roadmap entry](../ROADMAP.md#p001--metrics-records).
2. [SPECIFICATION](../SPECIFICATION.md), especially §1 (subscriptions; API access not assumed), F13 and §9;
   [ARCHITECTURE](../ARCHITECTURE.md), especially persistence, provenance, configuration and API/UI conventions.
3. [DECISIONS](../DECISIONS.md): D074 (metrics), D144 (projection), D150 (migration), D173/D174 (client
   compatibility), D216–D228 (configuration lifecycle), D231 (suggestions are not verified models), D232/D233.
4. [DDBB-DIAGRAM](../DDBB-DIAGRAM.md), [task flow](../flows/task-run.md),
   [configuration flow](../flows/configuration-setup.md), [migration flow](../flows/database-migration.md) and
   [archive consultation](../flows/backup-consultation.md).
5. [Reference notes](P001-metrics-records-references.md), then the source files below. Recheck live sources at
   implementation time; a retrieval date is not a tariff's effective date.

This repository is edited by hand, not by running My Harness on itself. Work in English, one bounded task at a time;
inspect concurrent changes before editing. Do not launch real clients/providers, install dependencies over the
network, access private usage records, alter global configuration, commit or publish under this phase plan.

## Implemented baseline and code map

This section describes inspected code, not the proposed additions. Reconfirm it against HEAD when work begins.

| Area | Entry points and current behavior |
|---|---|
| Capture | `src/my_harness/adapters/streams.py`, `adapters/cli_agents.py`: JSONL events and sealed result metadata; observed selection is distinct from requested selection. |
| Normalization | `src/my_harness/core/engine/metrics.py`: `metrics-1`, `terminal-2`, per-field requested/reported/derived/measured/absent provenance. |
| Storage | `src/my_harness/storage/models.py`: `AttemptMetricRow`, `AttemptModelMetricRow`; migration `0014_attempt_metrics.py`. Current schema head is `0027_profile_proposals`. |
| Recording and queries | `src/my_harness/storage/metrics.py`: result-time recording, explicit idempotent backfill, scoped/paginated summaries and groups. `storage/managed.py` records with the attempt result. |
| API | `src/my_harness/api/managed.py`, `api/schemas.py`: `/api/managed/metrics/{summary,attempts,groups,models,tasks,validations}`. |
| UI | `frontend/src/pages/Stats.tsx`, `pages/AttemptMetrics.tsx`, `metrics.ts`, `metrics-query.ts`: coverage, null handling, statistics and attempt details. |
| Existing model suggestions | `frontend/src/configuration.ts`; D231 lists editable suggestions, not a pricing or capability catalog. |
| Documentary summaries | `src/my_harness/core/engine/documents.py`, `document_text.py`, `storage/documents.py`: frozen phase consumption summaries. |
| Backup and restore | `src/my_harness/storage/backup.py`, `retention.py`; restore is query-only and metrics survive stream removal. |
| Checks | `tests/product/test_metrics.py`, `test_metrics_projection.py`, `frontend/tests/metrics.test.mjs`; related API, backup, retention, migration and configuration suites. |

Current invariants to preserve:

- One accounting per attempt: use terminal usage, otherwise Claude message usage where available. Do not add the
  terminal total to its constituent messages. Claude cumulative message deltas replace previous values.
- Claude input excludes cache; Codex input includes cache reads. Normalized uncached input is Claude input, or
  Codex input minus cache reads when both values are known and consistent. Never add raw provider input across
  incompatible semantics. Reasoning is a subset of output, not another billable output category to add again.
- Fields include cache reads/writes, output/reasoning, total, turns, tools, permission denials, wall/API duration,
  provider/client version, requested/reported model/effort, status and provenance. Availability varies by client.
- `cost_usd` is copied from terminal `total_cost_usd`; Claude model rows use `modelUsage.*.costUSD`.
  There is no price lookup, credit calculation or fallback tariff. Missing values stay null.
- The baseline Codex stream does not supply the Claude-style per-model breakdown. A requested Codex model is
  not proof of the actual model. Existing model aggregates are based on Claude `modelUsage` rows.
- SQL sums carry the number of contributing attempts; UI marks partial coverage. Failed or interrupted work is
  not presumed free. Result-less attempts and missing metric rows need an explicit coverage policy.
- Stored metrics are not rewritten by normal recording or backfill; retention preserves them. Frozen phase
  summaries and run histories cannot be repriced in place.

## Required scope

### Provider and model records

Account for Claude Code and Codex independently, including their different token semantics. Identify the client
provider separately from the model vendor, billing platform and billing product. A model on an API tariff is not
the same billing case as the same model through a ChatGPT credit plan. Future providers should fit the concepts;
implementing Gemini or another execution adapter is outside P001.

Every captured or derived value must identify its invocation scope and evidence source. Preserve the exact
requested identifier and the exact reported identifier(s); make any alias resolution explicit and versioned.
An unverified identifier or unpriced custom model remains visible with a reason, not silently mapped to a similar
name. Multi-model or delegated activity requires per-model usage and a documented parent/child accounting boundary
before its costs may be combined. Do not invent a split from an invocation total.

Cover all supported invocation purposes and roles, not just successful executor tasks: planning, revision, review,
phase checks/closure, chat, definition, onboarding/bootstrap and configuration assistance where applicable. Inventory
their persistence paths first; assistance may not have a managed attempt. Capture that gap explicitly before choosing
whether to link it to a shared record or introduce a separate supported source. Deterministic operations without a
model must not appear as unknown paid model calls.

### Valuation and cost analysis

Maintain distinct concepts for client-reported amounts, locally calculated valuations and provider-confirmed billed
amounts. Calculations need a known billing profile: first-party API USD, applicable ChatGPT credit scheme, included
subscription usage with an equivalent valuation, or a documented unsupported/unknown case. API credentials or a paid
integration are not prerequisites for metrics. A profile describes billing; it must not alter CLI authentication.

Requirements for the calculation contract:

- Use disjoint input/cache/output categories, splitting Claude cache writes by lifetime when pricing needs it.
  Store pricing conditions such as service speed, region, request-size tiers and negotiated rates when applicable.
  Use request-level evidence where conditions cannot be determined from invocation totals.
- Define decimal precision and rounding explicitly; do not build new monetary arithmetic on binary floats.
  Existing `cost_usd` float records retain their original representation and meaning.
- Keep USD, other monetary currencies if supported later, and provider-specific credits in separate units. Any
  monetary conversion needs an explicit price/currency/basis; do not assume a universal credit-to-dollar rate.
- Missing usage, unresolved model, ambiguous scheme, unknown modifier or missing reference produces a reasoned
  incomplete/unsupported result. Do not choose Standard, a cache TTL or the cheapest tariff without evidence.
- Return line items with quantities, rates, modifiers, reference identity and coverage. An exact arithmetic result
  under a known tariff is still a valuation, not invoice confirmation. Show discrepancies from reported amounts.
- Cost analysis should separate total attempted work from accepted task work, retries/revisions and conversational
  work, with provider/model, role, project/phase/task and time filters. Compute cache ratios, cost per accepted task
  and duration/throughput only with documented denominators and sufficient coverage; avoid misleading model-quality
  rankings from workload-dependent costs. No synthetic benchmark can establish real model quality or performance.
- A subscription fee cannot be divided into an exact task charge without an explicit allocation policy. Do not
  infer allowance balance, quota/reset windows or whether a run spent purchased credits from tokens alone.

### Reference data and historical integrity

The reference registry must distinguish model identity metadata from tariff records. Candidate tariff metadata:
provider/platform/product, exact model or explicit alias rule, billing scheme, unit per quantity, rate categories,
conditions, known validity interval, observation timestamp, official source URL, source/version digest and any
documented override. Unknown validity dates remain unknown. A translated page's retrieval time does not establish
when a price took effect. Resolve conflicting sources explicitly before treating them as an applicable tariff.

Reference updates are explicit and versioned, usable offline after packaging, and never required to view history.
Keep the selected reference bytes or a sufficient immutable representation and its digest with each valuation so
updates cannot change its result. Later corrections/repricing create identifiable additional records; they do not
replace original captures, catalogs, frozen summaries or valuation provenance. Backfill must retain its evidence
basis and distinguish contemporaneous tariffs from retrospective estimates. Do not fetch prices during capture,
aggregation, archive consultation or ordinary page rendering.

The dated tables in the companion notes are research seeds, not an operational catalog or a declaration of model
availability. The initial implementation should cover the repository's suggested models and add selected historical
models only with a recorded source; arbitrary configured models remain valid but may be unpriced.

### Persistence, API and UI

Decide the additive storage design and format-version boundaries before changing code. Preserve old payloads and
catalog semantics; plan idempotent migration/backfill, deduplication, record identity and cross-source aggregation.
Calculation records must survive retention and be included in verified backup/restore without original paths,
clients, configuration authority or external services. Merely viewing an archive cannot trigger recalculation.

Expose bounded queries and details for raw consumption, references, valuation line items, coverage and discrepancies.
Group by verified effective model separately from requested model; group costs only within compatible units and
billing bases. A partially priced scope must show numerator/denominator coverage and unpriced reasons. English and
Spanish UI should make the billing basis, observation date, tariff applicability and any staleness understandable.

Keep `docs/DDBB-DIAGRAM.md`, affected `docs/flows/`, `frontend/openapi.json` and the generated
`frontend/src/api.generated.ts` in parity with actual changes. Do not predeclare schema fields or routes as shipped.

## Decisions to resolve in P001-T001

These are open design questions, not blockers to reading the handoff or established implementation choices:

| Question | Required decision/evidence |
|---|---|
| Record boundaries | Attempt/model/request grain; assistance sources; optional delegated calls; stable deduplication keys and coverage denominators. |
| Evidence availability | What each supported CLI version actually emits for model, billing/speed, cache TTL, request size, tool charges and failure/interruption; unsupported inputs must be enumerated. |
| Billing profile ownership | Where the operator selects scheme/contract/overrides, activation and frozen version binding; preserve legacy configuration hashes. |
| Reference lifecycle | Storage/package format, explicit update/import/activation, provenance/digests, unknown effective dates, alias resolution and conflict policy. |
| Amount policy | Decimal representation, precision/rounding, formula/modifier ordering, compatible aggregate bases and reported-versus-calculated discrepancies. |
| Compatibility | Additive tables/format versions; old API fields; safe migration, explicit backfill, immutable repricing and backup contents. |
| Product scope | Whether invoice reconciliation is manual evidence or a separately authorized future integration; no billing API connection is implied. |
| Release execution | Target `0.1.2` is fixed by D233 as a specific exception to D231's patch scope. Define upgrade notes and compatibility checks; this is not an interface-only patch. Do not change runtime version strings during planning. |

Use local code and synthetic streams to settle reversible details. If evidence conflicts with the specification or
an accepted decision, ask before changing design, as AGENTS requires. Record accepted technical choices in new
DECISIONS sections; do not silently turn these candidate fields into a contract.

## Task plan entry points

The full task sections, dependencies, acceptance criteria, validation and deliverables are maintained in
[NEXT_STEPS](../NEXT_STEPS.md). Complete one task and its checks before the next; this handoff is supporting context,
not another task-status record. These identifiers belong to the current phase, not the pre-release H6.4 milestones.

1. [P001-T001 — Accounting contract and evidence inventory](../NEXT_STEPS.md#p001-t001--accounting-contract-and-evidence-inventory).
2. [P001-T002 — Versioned references and pure calculator](../NEXT_STEPS.md#p001-t002--versioned-references-and-pure-calculator).
3. [P001-T003 — Capture, storage and historical compatibility](../NEXT_STEPS.md#p001-t003--capture-storage-and-historical-compatibility).
4. [P001-T004 — Aggregates and API](../NEXT_STEPS.md#p001-t004--aggregates-and-api).
5. [P001-T005 — Billing/reference controls and metrics UI](../NEXT_STEPS.md#p001-t005--billingreference-controls-and-metrics-ui).
6. [P001-T006 — Qualification and phase handoff](../NEXT_STEPS.md#p001-t006--qualification-and-phase-handoff).

## Verification matrix and completion evidence

Use synthetic identifiers/records for fixtures. Calculations in the companion reference notes may validate
arithmetic, but their live rates must not make tests depend on the network. Prefer hand-calculated expected values
to tests that repeat the calculator implementation.

| Area | Required cases |
|---|---|
| Tokens | Claude/Codex input semantics; cumulative deltas; terminal versus messages; zero versus absent; inconsistent cache/input; reasoning subset; mixed/missing model usage. |
| Pricing | Distinct billing schemes/units; mixed TTL writes; request-size tier boundaries; applicable speed/region/contract conditions; unsupported charge categories; decimal sums and rounding. |
| Identity and references | Requested/reported mismatch, alias drift, custom model with no tariff, future/expired/unknown applicability, conflicting references, new version without historical mutation. |
| Reliability | Failed/partial/interrupted calls, result-less attempts, retries, delegated totals, assistance records, deterministic no-model operations, idempotent capture and backfill. |
| Aggregates | Missing rows and partial pricing, per-provider/model rollups, mixed units/bases, task acceptance/revisions, denominators, time boundaries and multi-model double counting. |
| History and operations | Old database/API compatibility; snapshot-before-migration; sealed histories and phase summaries unchanged; retention; backup consistency; query-only restore without network or original roots. |
| UI/API | Paginated contracts; references/line items/reasons; English/Spanish, light/dark, desktop/mobile; offline archive; no writes or recalculation on a read. |

Commands available today from the repository root (choose the relevant subset per task; no installation implied):

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q tests/product/test_metrics.py tests/product/test_metrics_projection.py
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline alembic check
node --test frontend/tests/*.test.mjs
npm --prefix frontend run check
npm --prefix frontend run build
```

Migration checks need an appropriately prepared temporary database; do not create/migrate the user's instance just
to run a check. See README for the actual type-regeneration and distribution commands rather than inventing new ones.
The 40 Python failures first recorded in the [v0.1.1 notes](v0.1.1-model-selectors.md) came from an unfilled
`.local/npm-cache` ([npm cache baseline](test-npm-cache-baseline.md)); with the README's development setup the full
suite passed (2048 passed, 2 skipped). Establish the current baseline and report failures honestly; do not treat
them as an automatic waiver or claim the suite is clean without running it.

At closure, record exact checks and counts, remaining unsupported billing cases, source/reference versions, changed
contracts and any real evidence separately from synthetic checks. Update STATE/NEXT_STEPS and roadmap status only
to the extent implemented. No benchmark, quota inference, billing integration or new provider is implied.

## Documentation initialization evidence

This initial task changes documentation only. It adds the roadmap phase, this handoff, reference notes and D232,
and links them from STATE/NEXT_STEPS. Validation: reviewed diff, whitespace checks, 41 local Markdown targets/anchors
across six documents (no errors), and independent decimal verification of the four worked example totals.
No application behavior, models, migrations, flows or API contracts changed. Application suites, browser QA,
provider calls, installation, commit and publication were not run for this initialization.

## Phase order and release target update

At the user's direction, D233 makes Metrics Records P001 for `0.1.2` and Continuous Mode P002 for `0.2.0`.
This handoff, its reference notes and proposed task IDs were renamed accordingly; ROADMAP, STATE, NEXT_STEPS and
the changelog's versioning policy were reconciled. The released package version and frozen runtime records were
not changed. Validation for this documentation update: diff/whitespace review and local link/anchor and phase-order
consistency checks; application suites and browser/provider validation were not run.

## NEXT_STEPS task-plan update

The user requested explicit next-phase steps using the base project's archive as a structural example. Read-only
inspection of `/Users/acosta/Documents/projects/my_harness/docs/archive/phase-013/NEXT_STEPS.md` and the P012 example
informed the English task sections now in NEXT_STEPS; no source archive was edited or copied as runtime evidence.
D234 records the plan placement. STATE/ROADMAP now identify six pending tasks and P001-T001 as next. Validation:
reviewed diff/whitespace, 68 local links/anchors across seven documents and six unique ordered task headings using
the production heading pattern, with required fields and dependencies. Only static documentation checks were run;
application suites, provider calls, runtime phase operations, commit and publication were not run.
