# P001-T004 — Aggregates and API

Status: complete; source delivered through `feat/p001-t004-aggregates-api` (branched from `develop` at `e2aec3f`).
Owner: P001-T004; accepted D254–D257/T001 §8 contract over the T003 ledger (D259) and implementation detail
[D262](../../DECISIONS.md#d262--bounded-accounting-aggregates-and-the-read-only-accounting-api).
Delivery route: topic → `develop`/`origin`, as for T001–T003; commit, merge and push were authorized by the owner after
review. Git records the source and merge commit IDs; the local topic branch is removed after the merge. No task release or version bump: 0.1.9 qualification/publication stays at P001 closure (T006).
Distribution, operator installation and service restart are outside T004.

## Implemented boundary

| Area | Implementation |
|---|---|
| Queries | `storage/accounting_views.py` (`accounting-aggregate-1`): one SQL row per invocation with its latest capture, derived provider/effective model/work class/UTC day and the valuation(s) of the selection policy; Python accumulates coverage, token sums, cache hit, wall throughput and exact decimal amount buckets per scope or group. |
| Selection | Original admission-bound valuation (earliest `admission` row) by default, or one named cohort (id or name): non-members only counted as `outside_selection`, `BUILDING` cohorts give known subtotals and no full amount. |
| API | `GET /api/managed/accounting/summary`, `/groups` (13 dimensions, order by invocations or key), `/tasks`, `/invocations` (+ `/{id}` detail and `/{id}/valuations`), `/cohorts`; shared filters and the existing project/phase/task scope. Pydantic schemas in `api/schemas.py`. |
| Contracts | `frontend/openapi.json` re-exported (7 new paths, 32 new schemas; every existing path and schema byte-equal as JSON) and `frontend/src/api.generated.ts` regenerated with the pinned `openapi-typescript`. |
| Texts | en/es catalog keys `accounting.cohort_unknown`, `accounting.filter`, `accounting.invocation_unknown`. |

No schema, migration, configuration format, capture/valuation code, existing endpoint, `metrics-1` value, phase
summary/export or frontend component changed. The T001 allowlist's documentary-consumption modules needed no change:
frozen phase summaries keep their `metrics-1` totals.

## Acceptance coverage

All cases use synthetic ledger rows or the T003 synthetic probe flow, temporary SQLite and the packaged pinned
bundle; run histories in the synthetic ledger are invalid JSON on purpose. Tests: `tests/product/test_accounting_views.py` (11).

| Criterion / T001 case | Evidence |
|---|---|
| Details, reference identity, line items, discrepancies with limits | Invocation list (offset pages over UTC start/id), detail (binding, latest allowlisted capture, alternative components, capture count) and paginated valuations with lines, referenced tariff/identity rows, discrepancy and cohort memberships; bucket discrepancy counts. Real-ledger test checks lines/references and that no `argv` reaches the capture document. |
| Provider, effective and requested model as distinct dimensions (A16/A20) | Effective model groups `reported`/`mixed`/`unknown`; a two-model disjoint partition is one `mixed` invocation whose tokens are added once; requested model never becomes effective. Every dimension paged one group at a time preserves invocation and token totals. |
| Role, project, phase, task, purpose, time (A29) | Phase/task groups keyed within root (and phase); start `[from,to)` filter with an invocation at `23:59:59.999999` and one at `00:00`; day groups by UTC start; HTTP converts an aware `+02:00` bound to UTC and refuses a naive one. |
| Units/bases, coverage and reasons (A25/A28/A18/A19) | Three expected calls (complete .44, incomplete .10 subtotal, no capture) plus one not invoked: `amount` null, `known_subtotal` 0.540000000000, coverage 1 complete / 1 incomplete / 1 unpriced (`capture_unavailable`) of 3 expected, not-invoked excluded. USD API, Codex credits and a subscription-equivalent counterfactual stay three buckets. Unbound, legacy-metrics and global-assistance invocations name their unpriced reasons; assistance is `setup` with no root/phase. |
| Accepted work, retries/revisions, conversations; denominators | Work classes: first pass vs. rework (second execution of a run onward, or a later run of the task), phase, conversation, setup. Phase scope excludes chat/setup by default. Cost per committed task 1.700000000000 (failed retries included as overhead), per attempted task 0.850000000000, committed-only work separate; an `INTENT`-only commit makes acceptance unknown and nulls the committed indicator; an unpriced call nulls every exact indicator. Cache hit 900000/1020000 and wall throughput 5000 tokens/s over complete pairs only, with excluded counts. |
| Read-only, immutable summaries, restored archives (A30/A31) | Every query leaves all table rows byte-identical; histories are never decoded. The T003 priced history gives the same cohort amounts and coverage after format-3 backup/restore with the artifact root removed. Admission policy keeps the original valuation over a later repricing. |
| Old payloads | Existing `/metrics/*` routes and schemas unchanged (OpenAPI comparison) and their suites pass in the full regression. |

## Supported limits

- Amounts are only those already persisted by T003 (admission, backfill or repricing valuations); reads never price.
  Seed tariffs have unknown historical validity, so admission valuations remain incomplete with known subtotals.
- Unpriced invocations with an unknown profile could belong to any bucket, so any unpriced expected invocation in the
  scope or group nulls every bucket's full `amount` (known subtotals remain).
- The latest capture supplies usage; if an invocation ever gains changed evidence after its admission valuation, the
  original valuation still stays selected (its `capture_id` is in the valuation detail).
- Time filters compare the stored UTC microsecond ISO strings that every native source writes.
- Aggregates read every ledger row in scope (bounded memory per group); responses are paginated. Task indicators are
  totals of the scope, not per-task pages; per-task totals come from the `task` group dimension.
- No UI consumes these routes yet (T005), and no new phase export field was added.

## Validation

| Check | Result |
|---|---|
| Focused | `scripts/check tests/product/test_accounting_views.py -- -n 0`: 11 passed. |
| OpenAPI/types | `scripts/export_openapi.py` and `npm --prefix frontend run generate:types`; JSON comparison against `HEAD`: only additions. |
| Full (`scripts/check --frontend`) | unittest 10 ran; `alembic check` on a temporary SQLite: no new operations; pytest **2339 passed, 2 skipped, 29 subtests passed** (11 warnings: the existing Starlette `httpx` deprecation and the intentional duplicate-ZIP tampering fixture); Node 230/230; frontend build (`tsc` + Vite) passed with the regenerated types. |
| Documentation | `scripts/check-docs`: 70 Markdown files, 0 errors; `git diff --check` clean. |

Omissions: no real CLI/provider, private run or billing data, operator database, installation, service restart,
distribution build/check, browser QA (no UI change) or harness operation on this checkout.
