# P001-T003 — Capture, storage and historical compatibility

Status: complete; source delivered through `feat/p001-t003-capture-storage` (branched from `develop` at `1cebe03`).
Owner: P001-T003; accepted D254–D257/T001 contract, T002 boundary (D258) and implementation detail
[D259](../DECISIONS.md#d259--native-accounting-capture-frozen-revision-binding-and-format-3-archives).
Delivery route: topic → `develop`/`origin`, as for T001/T002; commit, merge and push were authorized by the owner after
review. Git records the source and merge commit IDs; the local topic branch is removed after the merge. No task release or version bump: 0.1.9 qualification/publication stays at P001 closure (T006).
Distribution, operator installation, migration of the operator's database and service restart are outside T003.

## Implemented boundary

| Area | Implementation |
|---|---|
| Stream retention | `core/engine/metrics.py`: additive `usage-stream-1` section in the existing summary (ID-keyed Claude requests, conflicts, unidentified count, exact terminal cost lexemes); `adapters/streams.py` and `replay` feed it. `cli-14`, `terminal-2` and every `metrics-1` value are unchanged. |
| Capture/reconciliation | `core/engine/usage_capture.py` (pure): allowlisted, float-free `usage-capture-1`; launch gate; terminal/model/request views with inclusion relations; one reconciled `usage-accounting-1` selection with stable reasons. |
| Ledger | `storage/accounting.py`; migration `0028_usage_accounting` (eight tables, 62 product tables). Intents and settlements run inside the native transactions of `storage/managed.py`, `storage/preparation.py` and `services/configuration_assistance.py`. |
| Billing | `services/configuration.py` accepts explicit `local-config-10`/`project-config-2` billing metadata, validated separately and stripped by `runtime()`; `storage/billing.py` dereferences the revision frozen at admission into `billing-binding-1`. `local_config.compose_profile` records the actual project format. |
| Operations | `storage/accounting_operations.py`: previewed reference import, accounting backfill and repricing cohorts; CLI `accounting-references`, `accounting-backfill`, `accounting-reprice`. |
| Archives | `storage/accounting_backup.py`; backup format 3 in `storage/backup.py`; `backup-upgrade` (`upgrade_bundle`). Retention code is unchanged: it removes stream bytes only. |

No API route, OpenAPI document, generated client type or frontend file changed: configuration forms are untyped
dictionaries, and accounting reads are T004. en/es catalogs gained the new CLI help, backup and billing messages.

## Acceptance coverage

All cases use synthetic streams, the local CLI probe, temporary Git/SQLite and the packaged pinned bundle
(`41d20094…`). Tests: `tests/product/test_usage_accounting.py` (27), plus one in `test_profile_preparation.py`.

| T001 cases | Evidence |
|---|---|
| A15 | Terminal counted once; replayed message starts ignored, deltas replace counters; a request partition summing to C1 prices to USD 0.440000000000 (retrospective, `effective_period_unknown` warning). A conflicting duplicate id invalidates only the request partition. The exact lexeme `0.4400000000000000000001` is kept. |
| A16 | Reconciled `modelUsage` partition is selected once; a mismatching split falls back to the terminal with `model_partition_conflict`. |
| A03/A06/A07/A13/A14 at capture | Missing lifetime stays unknown; Codex requested model never becomes reported (`model_unreported`); delegation tools and server-tool activity leave `delegation_boundary_unknown` / `tool_charge_unknown` with a known subtotal only. |
| A17 | Equal capture bytes in two invocations are two rows; re-settling an attempt appends nothing. |
| A18 | Launch gate: refused/identity-changed → `not_invoked` (no valuation); missing process row or identity without capture → `unknown_execution`; interrupted closing-owner capture → `partial_capture`; missing terminal → partial subtotal or `usage_missing`. Scripted ports without process rows keep visible invocations without captures. |
| A19 | Managed attempts (planner/executor/reviewer), a preparation executor step (`preparation_step`, no run/attempt) and global configuration assistance (`configuration_assistance`, no attempt) each record one native invocation. |
| A22/A23 | Bindings dereference only the frozen global/project revision; a later billing-only activation does not change an earlier binding; a tampered revision digest yields `configuration_unavailable`; a profile whose provider differs from its agent is unknown. v9 with billing is refused, v9/v1 bytes keep their meaning, `runtime()` strips billing and `technical()` is unchanged by billing edits. |
| A21 (admission) | Seed references have unknown effective periods: admission-bound valuations are incomplete with a known subtotal; only an explicit retrospective scenario can be complete. |
| A27 | Backfill/repricing require the exact preview digest and an idempotency key; replay returns the same report; a reused key with another preview is refused; an interrupted build stays `BUILDING` with its cursor and resumes from its frozen selection; a second cohort reuses the identical valuation through its own membership. |
| A30 | Migration from `0027` takes the snapshot first, creates empty accounting tables and leaves legacy rows identical; backfill/repricing leave attempts, metrics, runs and projections byte-identical; old downgrades refuse while accounting rows exist. |
| A31 | Retention leaves every accounting row; a format-3 backup verifies, restores and stays consultable after the original artifact root is removed; accounting operations refuse on the restored archive; a corrupted reference row fails verification; an older format-2/schema-0027 bundle is refused with a `backup-upgrade` pointer, and the upgraded copy verifies/restores while the original bytes stay unchanged. |

A01–A14/A20–A26 calculator semantics remain covered by T002's tests. A28/A29 (aggregation) and A32 (UI) belong to
T004/T005.

## Supported limits

- No CLI emission was observed in this task. Fields are captured only when present; the synthetic probe establishes
  parsing behavior, not that an installed client emits a field. Request partitions need Claude message ids and a
  response model on each `message_start`; otherwise the model or terminal view is used.
- Codex terminals without `cache_write_input_tokens` stay `usage_missing` for valuation (never zero), and no Codex
  response model is established. Claude per-model cache lifetimes are unknown unless a single model wrote cache.
- Admission valuations exist only with a frozen v10/v2 profile; earlier jobs and legacy-configured projects stay
  unpriced with `billing_profile_unknown`. A project selection naming a missing profile is detected when the binding
  is resolved, not at save time (T005 adds editing controls).
- Seed tariffs have unknown historical validity; contemporaneous valuations are therefore incomplete.
- Cohorts are bounded to 10,000 frozen members per preview; selections beyond that must be narrowed.

## Validation

| Check | Result |
|---|---|
| Migration on a temporary database | `alembic upgrade head`, `alembic check` (no new operations), `downgrade 0027_profile_proposals` and re-upgrade, against a scratch SQLite only. |
| Focused accounting | `pytest -q -n 4 tests/product/test_usage_accounting.py …::test_preparation_executor_step_is_its_own_accounting_source`: 28 passed (stable on repeated runs). |
| Standard-library unittest | `python3 -m unittest discover -s tests -p 'test_*.py'`: 10 passed. |
| Complete Python regression | `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q -n 4`: **2311 passed, 2 skipped, 29 subtests passed** in 292 s; five warnings (existing Starlette deprecation and intentional duplicate-ZIP tampering fixture). |
| Documentation | Local Markdown targets/anchors and fences of every changed document checked with a standard-library script; `git diff --check` clean. |

The first complete regression (before the last corrections) found six failures: the service-text catalog lacked the
seven new invariant texts, and five round-trip tests of older revisions downgraded while accounting rows existed.
The catalog now lists them; those tests clear their synthetic accounting rows first (as the 0021 test already did
for work languages), and the chat test additionally asserts the new accounting refusal.

Omissions: no real CLI/provider, private run or billing data, operator database migration, installation, service
restart, distribution build/check, frontend suite/typecheck/build (no frontend file changed), browser QA, OpenAPI
regeneration (no contract change) or harness operation on this checkout.
