# P001-T006 — Qualification and phase handoff

Status: complete as source qualification; delivered through `chore/p001-t006-qualification` (branched from `develop`
at `3346d97`).
Owner: P001-T006 ([task](../NEXT_STEPS.md#p001-t006--qualification-and-phase-handoff)); release target **0.1.9 at P001
closure** ([D253](../DECISIONS.md#d253--phase-release-targets-after-018)).
Delivery route: topic → `develop`/`origin`, like T001–T005; commit, merge and push were authorized by the owner after
review. Git records the source and merge commit IDs; the local topic branch is removed after the merge. The 0.1.9 release PR to `main`, tag, GitHub Release/archive, P001 closure and the operator's
installation and database migration are separate, later actions (D235/D242); none was performed.

## Result

P001 meets its five exit criteria **with synthetic evidence**: every criterion maps to implemented code and passing
offline checks below, and one integrated journey now exercises capture → records → valuation → aggregates/API/UI →
retention → backup → query-only restore. Qualification found and fixed one UI defect (invocation labels, below). Shared
version metadata is now the **0.1.9 candidate**; the offline distribution built from it passed the installed-wheel
journey. No real CLI emission, account billing or invoice has been validated: valuations are local calculations from
pinned public prices, and their limits remain visible rather than accepted silently.

## Criterion → implementation → evidence

| Exit criterion ([ROADMAP](../ROADMAP.md#p001--metrics-records)) | Implementation | Evidence (synthetic) |
|---|---|---|
| Attempts preserve provider/client versions, requested and reported model/effort, token categories, durations, tools, outcome and provenance, without double counting or missing-as-zero | `adapters/streams.py` (`usage-stream-1`), `core/engine/usage_capture.py` (`usage-capture-1`, launch gate, evidence selection), `storage/accounting.py`, migration `0028_usage_accounting` (D254/D259) | `test_usage_accounting.py` (A15–A19: terminal once, cumulative deltas replace, conflicting ids, model partitions, Codex requested ≠ reported, launch gate, native sources, equal bytes → two captures); `test_metrics*.py` keep `metrics-1`; T006 journey: requested model never an effective group, observed zero vs "no data" on the restored page |
| Each supported billing case has a reproducible valuation or an explicit reason; reported, calculated USD, calculated credits and confirmed billing stay distinct | `core/engine/valuation.py`, `metric_references.py` (D256/D258); `confirmed_billed` reserved with no producer | `test_valuation.py` (A01–A14, A20–A26: C1 0.44, C2 0.47, X1 9.75 credits, tiers, factors, half-even, discrepancies, 28 reason codes); A25 buckets in `test_accounting_views.py`; journey: one USD/API bucket 0.440000000000, admission policy "billing_profile_unknown" ×3 with no amount |
| Versioned references identify provider, model, scheme, units, source, observation date, effective period and conditions; updates never change historical valuations | Packaged `metrics-reference-1` bundle `41d20094709e…` (38 references), previewed import, immutable valuations, cohorts (D255/D257/D265) | `test_valuation.py` (A20/A21 alias drift, periods, old bundle reproduces values); `test_usage_accounting.py` (A27 cohorts reuse immutable valuations, A30 legacy rows byte-identical); `test_billing_controls.py` (stable digest, conflict, archive refusal); journey: legacy `/metrics/*` and attempts answer identically before and after repricing |
| Statistics by provider/model, role, project, phase, task and time with coverage and compatible units; no allowance or invoice inferred from tokens | `storage/accounting_views.py`, `/api/managed/accounting/*` (D262), `pages/Accounting.tsx` (D264), billing controls (D265) | `test_accounting_views.py` (A16/A28/A29: 13 dimensions, UTC bounds, mixed/unknown models, denominators, task indicators); `accounting.test.mjs` (page reads only the accounting API, bases separate, en/es, live/archive); journey reads summary/groups/tasks/invocations/detail/valuations/cohorts/references |
| Synthetic checks cover calculation, capture, aggregation, historical compatibility, retention, backup and query-only consultation; diagrams, flows, OpenAPI/types and en/es UI in parity | Format-3 backup, `backup-upgrade`, unchanged retention (D259); [DDBB](../DDBB-DIAGRAM.md#p001-accounting-records), [accounting flow](../flows/metrics-accounting.md), `frontend/openapi.json`/`api.generated.ts`, en/es catalogs | `test_usage_accounting.py` (A30/A31: snapshot-first migration, retention, verified backup, corrupt reference rejected, older bundle upgrade); **`test_p001_qualification.py`** (whole chain, A30/A31); installed-wheel journey and browser QA below; `scripts/check-docs` (en/es keys, schema head) |

T001's synthetic matrix A01–A32 is covered by the owning tasks' evidence ([T002](P001-T002-reference-calculator.md),
[T003](P001-T003-capture-storage.md), [T004](P001-T004-aggregates-api.md), [T005](P001-T005-metrics-ui.md)); T006
re-ran all of it in the full regression and adds the integrated A30/A31 journey and A32's served-archive check.

## Integrated journeys added by T006

- **`tests/product/test_p001_qualification.py`** (pytest, one case). The real adapter and local CLI probe run a
  Codex planner/reviewer and a Claude executor (three native invocations). Legacy metrics/attempt responses and
  legacy tables are recorded; changed evidence is appended and an explicit previewed repricing cohort prices it
  (CLOSED, one complete valuation). Over HTTP: legacy contracts unchanged; admission policy has no amount and three
  `billing_profile_unknown`; the cohort has one USD/API bucket of 0.440000000000, coverage 1 expected and 2 outside
  the selection, provider groups claude/codex, requested models absent from effective groups, line quantities summing
  to 1030000, no `argv` in the capture, the packaged bundle listed. Reads change no row. Retention removes the
  eligible stream files and leaves every accounting row and HTTP answer identical. A format-3 backup restores into
  a query-only archive served without the artifact root or a managed project: every answer is identical, reference
  import and run actions return 409 `restored_read_only`, the archive file hash and rows are unchanged, the bundle
  still verifies and backfill/repricing previews are refused.
- **`scripts/check_distribution.py`** (installed wheel, scripted ports). After the D088 definition/task/commit
  journey: the accounting summary has no amount and every expected invocation carries an unpriced reason (scripted
  ports have no captures or billing profile), the packaged bundle is listed and `/accounting` and
  `/projects/offline/accounting` serve the UI. The restored archive returns identical summary/invocations/groups/
  references, serves `/accounting` and refuses reference preview with 409.
- **Synthetic browser QA (A32).** The restored archive from the pytest journey (kept under
  `.local/p001-t006/`, synthetic only) was served by the 0.1.9 wheel installed offline in a scratch venv, behind the
  repository's Vite dev proxy (Chrome navigations started by the extension are refused by the service's cross-site
  guard, so the built UI could not be opened directly). Read-only banner, no CLI commands or import controls,
  admission view (3 unpriced with reason), cohort `archive` (1 of 1 fully priced, $0.44, 2 outside the cohort,
  cache hit 88.2%, task spend $0.44 per attempted task, "no data" for reasoning), groups, invocations, detail and the
  packaged references; light and dark themes; no console errors. The archive's SHA-256 was identical before and
  after the session and `backup-verify` passed.

## Defect found and fixed

Invocation IDs are `<source_kind>:<id>` (D259), but the page labelled them with their first eight characters, so
every managed attempt read "Invocation managed_" and all row buttons had the same accessible name. T005's mocked
fixtures used IDs without a kind. `accounting.ts` `invocationLabel` now shows the source id's first eight characters
(heading and button label); the page test uses the real ID shape and a helper test covers kinds and a bare ID.
No API, catalog text or other component changed.

## Release candidate and upgrade notes

Version **0.1.9** in `pyproject.toml`, `uv.lock`, the API (`api/app.py`, exported `frontend/openapi.json`, which
differs only in `info.version`; generated client types unchanged), `frontend/package.json` and its lockfile; README
(en/es) status and download commands; the [changelog](../../CHANGELOG.md#019--2026-10-29) entry, marked as a not yet
published candidate, carries the upgrade notes:

- Stop the service and writers, install with `--upgrade --writers-stopped`, then run the new generation's
  `my-harness migrate` (`0027_profile_proposals` → `0028_usage_accounting`, eight empty tables, verified snapshot
  first). `serve` never migrates; the downgrade is refused once accounting rows exist.
- No new dependency, recipe or `cli-14` change; v1–v9/v1 configuration bytes keep their meaning; billing needs an
  explicit converted save. New backups are format 3; older bundles need `backup-upgrade` (new verified copy).
- Nothing is backfilled or priced by the upgrade; past work is valued only through explicit `accounting-backfill` /
  `accounting-reprice`.

## Remaining limits and unsupported cases (visible, not accepted silently)

- **No real validation.** No installed Claude Code/Codex emission was observed for the new fields; request partitions
  need Claude message ids with a response model; Codex terminals without cache-write counters stay `usage_missing`
  and no Codex response model is established. Real billing, account eligibility and invoices are not compared.
- **Reference validity.** Seed tariffs (bundle `41d20094709e…`, observed 2026-10-27; observation file SHA-256
  `2e7e88f7…baf8` unchanged) have unknown historical effective periods: admission-bound valuations are incomplete with
  a known subtotal; only labelled retrospective scenarios are complete.
- **Unsupported without supplied evidence:** Batch/Flex, partner platforms, unpriced custom models, unknown or
  negotiated agreements, Enterprise USD without terms, unknown server-tool charges, unknown speed/geography,
  nonzero Codex CLI cache writes. No invoice importer, billed-amount editor, quota/allowance inference or
  `confirmed_billed` producer exists in P001.
- **Coverage gaps by design.** Jobs admitted before a v10/v2 profile, legacy-configured projects and scripted ports
  stay unpriced with their reason; cohorts are bounded to 10,000 members per preview.
- **QA scope.** No real mobile device, other browsers or screen readers; Spanish and 390 px layouts rely on T005's
  synthetic QA and the en/es page tests, not on this served-archive session.

## Validation

| Check | Result |
|---|---|
| Baseline before changes (`scripts/check --frontend`, `develop` at `3346d97`) | unittest 10 ran; `alembic check`: no new operations; pytest **2345 passed, 2 skipped, 29 subtests passed** (11 existing warnings); Node **247/247**; build passed. Same as T005b's final result: no pre-existing failure. |
| Focused | `scripts/check tests/product/test_p001_qualification.py -- -n 0`: 1 passed; `node --test frontend/tests/accounting.test.mjs`: 8 passed; `npm --prefix frontend run check`: passed. |
| Final full (`scripts/check --frontend`) | unittest 10 ran; `alembic check`: no new operations; pytest **2346 passed, 2 skipped, 29 subtests passed** (the same 11 warnings: Starlette `httpx` deprecation and the intentional duplicate-ZIP tampering fixture); Node **248/248**; build (`tsc` + Vite) passed. The +1 pytest and +1 Node cases are T006's. |
| OpenAPI/types | `scripts/export_openapi.py` + `npm --prefix frontend run generate:types`: only `info.version` changed; no type diff. |
| Offline distribution | `scripts/build_distribution.py --offline --out-dir .local/p001-t006/distribution` and `scripts/check_distribution.py --dist .local/p001-t006/distribution`, rerun on the final sources: passed (exact members, metadata, licenses, `SHA256SUMS`; isolated wheel UI/assets/API/session, definition/task/commit/restart, accounting reads, errors and restored evidence). Existing large-chunk advisory only; packaging changed no source. |
| Documentation | `scripts/check-docs`: 72 Markdown files, 0 errors; `git diff --check` clean. |

Omissions: no real provider/CLI, private run, configuration or billing data; no operator database, installation,
migration or service restart; no harness operation on this checkout; no release PR, tag, GitHub Release or archive
download verification (those follow the owner's authorization); browser QA limited as stated above.

## P002 handoff

P002 **Continuous Mode** targets **0.2.0** at its closure (D253) and starts after the 0.1.9 release and P001 closure.
Its [roadmap entry](../ROADMAP.md#p002--continuous-mode) holds the objective and exit criteria; design and tasks are
pending and must be planned (like D234) before any code. Starting context:

- Phase lifecycle, closure/archive and READY guarantees: [phase-lifecycle flow](../flows/phase-lifecycle.md),
  [task-run flow](../flows/task-run.md), SPECIFICATION §§ on phases and D156/D233.
- A consumption limit can read the accounting ledger (D262 API, coverage and unpriced reasons) but must not treat
  missing or unpriced usage as zero, nor infer subscription allowances; any budget unit must be one of the existing
  compatible bases or plain token counts.
- Preserve P001 invariants: admission-frozen billing bindings, immutable valuations, read-only archives and the
  `metrics-1` contracts.
