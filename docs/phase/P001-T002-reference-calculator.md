# P001-T002 — Versioned references and pure calculator

Status: complete (pure library/references and checked source delivery; operational integration remains T003–T005).
Owner: P001-T002; accepted D254–D257/T001 contract and implementation detail D258.
Delivery: `feat/p001-t002-reference-calculator` → `develop`/`origin`, with commit, necessary merge and push authorized
by the owner for this task. No task release/version bump; 0.1.9 qualification/publication remains at P001 closure.
Distribution publication and operator installation are outside this task. Local qualification packages retain 0.1.8
metadata and are not a release; the published package and operator installation are not replaced.

## Implemented boundary

- `metric_references.py`: separate immutable model-identity and tariff JSON, canonical UTF-8 content IDs,
  source/observation/period metadata, declarative condition/rate cases, strict decimal/unit/factor validation,
  digest/duplicate/overlap rejection and explicit offline packaged loading. Returned documents are fresh copies;
  reference bytes and bundle contents are immutable. Canonical arrays use IDs, URLs, case/factor keys or sorted
  strings. A changed reference is a new content ID and bundle; unknown-period versions cannot ambiguously coexist.
- `valuation.py`: pure `usage-accounting-1` normalization and `valuation-1` calculation with an explicit
  `valuation-scenario-1` input. No CLI parser, configuration activation, database, network, clock or file access.
  Decimal precision 160 traps line-arithmetic rounding; exact lines are summed before one half-even rounding to
  12 places. Results retain exact sum, adjustment, input/profile/reference-set digests, quantities, rate cases,
  identity/tariff IDs, factors, selected components, unit/basis/scheme and complete/incomplete/unsupported reasons.
- A separate `compare_estimate` leaves the original estimate untouched. Matching scope/model/condition digest,
  unit, basis and scheme are prerequisites. It keeps signed descriptive deltas; a documented rounding quantum
  supplies half its quantum plus 0.0000000000005 tolerance. Unknown precision and legacy floats cannot certify
  agreement. Inputs exceeding exact supported comparison precision are explicitly not comparable.

No adapter or operational caller uses this boundary yet. T003 owns native capture reconciliation, frozen operational
billing-profile binding, persistence/import, cohorts and backup. T004/T005 own queries/UI. Original metrics-1,
configuration bytes, schema 0027, API/OpenAPI/types, dependency locks, recipe fingerprints and archived evidence
remain unchanged. The planned flow only gains an implementation-status annotation; no operational flow is activated.

## Pinned reference provenance

The runtime file is `core/engine/references/metrics-2026-10-27-v1.json`, separate from the unchanged T001 research
artifact. It contains **19 model identities and 19 tariffs** for the four Claude suggestions and four Codex
suggestions plus the additionally researched Terra. The three Codex products (API, Work/Codex credits, Enterprise
USD) have separate identities/tariffs. All **165 rate cells**, including the explicitly unavailable Sol 12h write
rate, were compared directly with the T001 extraction. Its official URLs/locale, observation timestamp and source
file digest are carried by the runtime references. No new live-source observation is claimed.

- T001 observation SHA-256: `2e7e88f759e206f40ceb641668d104fbe788fae37e75ecb117de6f71e790baf8`.
- Canonical runtime bundle ID: `41d20094709ebe26c0ff5787d4de00f573f27e2e2ffabd26c5279ca688fdd5bc`.
- Pretty-printed runtime file SHA-256: `3e10879848a193d927d87f6f1737d10def3d1fc5f933b25e2fec800c40891287`.

All seed effective periods are explicitly unknown. A historical valuation stays incomplete with a known token
subtotal; an explicit retrospective scenario can be complete but retains `effective_period_unknown` and its
retrospective label. Source dates are not effective dates, account eligibility or proof that these are current
rates. Sources are never refreshed during loading/calculation. Later observations require another immutable file.
The existing build includes JSON recursively; no packaging metadata change was necessary. Exact member/byte checks
and an isolated installed-wheel import/calculation verify inclusion.

## Pure input contract for T003

These are internal library inputs, not operational configuration, persistence or HTTP contracts:

| Input | Required evidence |
|---|---|
| Evidence envelope | `format=usage-accounting-1`; `coverage=complete/partial/absent`; `partition=single/disjoint`; `delegation=none/disjoint/included`; explicit `charges_complete`; component and charged-tool arrays. Optional stable `reasons` preserve capture gaps. The caller reconciles the selected partition against authoritative capture totals before declaring completeness. |
| Selected component | Unique `key`; homogeneous `grain=invocation_total/model_total/request`; exact `reported_model`; `model_source=response/model_usage`; explicit coverage and semantics; nonnegative integer input/read/write/output quantities. Requested or initialization model strings never establish a response model. Selected inclusive parents/children, duplicate model totals and terminal/constituent mixtures are rejected. |
| Claude semantics | `claude-cli-1`: raw input excludes reads/writes; `write_5m/write_1h` partition the aggregate write count. Explicit zero aggregate establishes zero writes; positive writes with absent lifetime are incomplete. |
| Codex semantics | `codex-cli-1`: uncached input is input minus reads, only with explicitly zero writes. Nonzero CLI writes remain unsupported. `responses-api-1` separately subtracts reads plus aggregate writes and requires `write_30m/write_12h` evidence; no inference of CLI capability. |
| Scenario | `format=valuation-scenario-1`; provider/platform/product/scheme/unit/basis; UTC `at`; explicit boolean `retrospective`; conditions mapping each name to `{value, provenance: reported/asserted, source}`. Missing/null/unknown speed/geography stays unknown. Source-backed overrides create another tariff reference. The scenario digest becomes part of valuation identity; it is not an active billing-profile ID. |
| Tier selection | Complete request components for Haiku/API thresholds. An invocation/model sum, even below a threshold, does not establish a request tier. Request prompt includes all input/cache categories. |
| Charged tools | Unique charge key, category, independently evidenced quantity, pinned tariff ID, `reported_billable/asserted_billable` provenance/source and independent conditions. Tools use their own rate unit and denominator; client shell/file activity is rejected as billable evidence. |
| Estimate comparison | Caller-established common `comparison_key` digest covering scope, model partition and applied conditions, plus identical unit/basis/scheme. Optional source-backed `rounding_quantum`; an exact decimal lexeme alone is insufficient precision evidence. |

Token rates use one million tokens. Charged-tool denominators are bounded powers of ten from 1 through 10^12.
Reference rates/factors/quantities use T001's bounds, with no floats/exponent-form monetary values or executable
expressions. Supported valuation bases are API USD, Enterprise USD, token credit and explicit subscription equivalent;
there is no conversion, subscription allowance calculation or invoice producer.

## Acceptance and supported limits

A01–A14 and A20–A26's calculator boundary are exercised by synthetic offline tests. A22/A23 test only immutable
scenario/digest behavior here; queued-job binding and configuration CAS/activation remain T003, as assigned by T001.
Capture reconciliation/deduplication (A15 onward), durable accounting, backfill/cohorts, aggregation and UI are not
implemented or claimed by this task.

| Cases | Evidence/result |
|---|---|
| A01/A02/A07 | C1 0.44 USD, C2 0.47, mixed TTL 0.455; five disjoint lines; reasoning remains within output. |
| A03/A06/A13/A14 | Explicit missing TTL/model/reference/profile/scheme/speed/geography/tool-charge reasons; invalid/negative/bool/nonfinite/oversized quantities and inconsistent partitions rejected; observed zero differs from absent. |
| A04/A05/A25 | X1 9.75 credits; eligible Fast 19.5/Ultrafast 58.5. API, Enterprise USD, credits and equivalent bases remain separate. No included-allowance multiplier or conversion. |
| A08/A09/A12 | Haiku 100000/100001 and two 60000-token requests; API 272000/272001 full-request boundaries; no threshold inferred from invocation sums or inherited by sign-in tariffs. |
| A10/A11 | Synthetic sourced regional 1.1 and category-specific contract factors; adjusted rates cannot reapply a factor. Separate Responses API write partition gives input subtotal 0.01515, while the same nonzero-write Codex CLI case remains unsupported. |
| A20/A21 | Version-pinned alias drift, custom/unreported models, known half-open periods, future/expired/unknown validity, corrupt/duplicate IDs/keys and ambiguous overlaps; old bundle bytes still reproduce original values. |
| A22–A26 | Scenario edits yield a different digest; 0.5/1.5 picounit half-even ties and multiple sub-quantum lines; exact maximum-bound arithmetic checked against independent integer rational arithmetic; signed -0.01 discrepancy and 0.0050000000005 tolerance. |
| Additional | Mixed-model disjoint partition, inclusive-parent rejection, partial/capture reasons, independent charged-tool tariff, immutable inputs, global Decimal-context independence and forbidden I/O during calculation. |

Seed Claude speed is Standard/global only. Other speed/geography/contract conditions require separately sourced
references. OpenAI API seed speed is Standard/global; missing lifetime rates stay unavailable. Credit/Enterprise
Fast/Ultrafast require explicit scheme/speed eligibility; Enterprise published terms require an explicit agreement
assertion. These assertions are not provider billing evidence. Batch/Flex, partner platforms, unpriced custom IDs,
unknown/negotiated agreements without supplied terms and unknown server-tool charges cannot fall back to seed rates.
Charged-tool/region/contract machinery is qualified with synthetic references, not extra researched live tariffs.

## Validation and delivery

Exact checks, corrected regression failures and delivery are recorded below.

| Check | Result |
|---|---|
| Focused calculator + core architecture | `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q -n 0 tests/product/test_core.py tests/product/test_valuation.py`: **102 passed** (98 calculator cases + four core cases). |
| Final complete Python regression | `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q -n 4`: **2283 passed, 2 skipped, 29 subtests passed** in 475.93 seconds; five warnings (existing Starlette deprecation and intentional duplicate-ZIP tampering fixture). |
| Standard-library unittest | `python3 -m unittest discover -s tests -p 'test_*.py'`: **10 passed**. |
| Frontend regression | `node --test frontend/tests/*.test.mjs`: **230 passed**, after packaging finished. An earlier overlapping run failed two test files when `npm ci` temporarily removed their dependencies; the clean rerun is the qualification result. |
| Types/UI build and offline package | `scripts/build_distribution.py --offline --out-dir .local/p001-t002/verified-distribution` through frozen/offline uv: passed; existing large-chunk advisory only. Existing recursive package-data inclusion carries the new JSON without metadata edits. |
| Distribution / isolated wheel | `scripts/check_distribution.py --dist .local/p001-t002/verified-distribution`: exact member bytes, metadata/licenses/checksums and installed synthetic UI/API/task/restart/restore journeys passed. Separate `python -I` from `/tmp` in an isolated wheel-only venv loads the 38-reference bundle/digest and reproduces five C1 lines / USD 0.440000000000 without checkout imports. |
| Source/reference/docs review | All 165 seed rate cells match the pinned observation, including null; original research SHA-256 unchanged. New/current diff reviewed, `git diff --check` clean; 215 local documentation targets/anchors valid and fences paired. No frozen artifact modified. |

The first complete Python regression run found the new relative core import, failing the architecture guard:
2259 passed, one failed, two skipped, 29 subtests. It was corrected to an absolute core import and the focused
architecture/calculator check passed. The final full rerun above passed with the corrected import and all 98 new cases.

Omissions/limits: no live source refresh, real CLI/provider, private billing/run data, current account eligibility,
invoice reconciliation, harness run on this checkout, operational configuration/activation, operator installation,
service restart, new migration/standalone Alembic check, API regeneration or browser visual QA. Full Python/package
checks use synthetic temporary repositories/databases/fake clients; they do not qualify real billing/capture.

Delivery: source/review/checks complete, integrated through the D235 topic → `develop` merge and pushed to
`origin/develop` as this task's source delivery. Git records source/merge commit IDs; final session verification
checks the remote ref and clean checkout, then removes the merged local topic branch. No main release/tag/publication.
Phase release **0.1.9** remains at T006/closure;
operator installation is outside T002. ONE_OFF_TASKS remains empty; next task is **P001-T003**.
