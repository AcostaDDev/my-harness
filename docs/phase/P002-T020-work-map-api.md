# P002-T020 — Work-map and trace read projections

**Status:** source complete with synthetic evidence; **independent final re-review passed** on 2026-11-05 (§10),
including all corrections in §§6, 8–9. Reviewed source `b30a00c` is integrated into develop by the accompanying merge
(§11). The owner authorized source commit, merge and push of develop.
Decision for the choices delegated to this task:
[D311](../DECISIONS.md#d311--work-map-read-projections-tokens-and-indexes); flow: [work-map reads](../flows/work-map.md).

## Ownership and delivery

| Field | Value |
|---|---|
| Owner task | P002-T020 (backend: projections and API); no gates pending (G14 resolved by T018) |
| Branch | `feat/p002-t020-work-map-api` from `develop` at `c993564` (verified clean and equal to the local `origin/develop` on 2026-11-05) |
| Schema | From `0040_observed_step_reads` (94 tables) to `0041_work_map_reads` (seven indexes only, 94 tables) |
| Contract | [T018 §§3–8, 12–14](P002-T018-work-map-contract.md#7-read-projections-and-api-t020), D304–D306, D309, D310; background D277–D278, D287–D289, D296, D298, D302; D303 for numbering (former T020 references belong to T026) |
| Out of scope | T021–T024 (SVG engine, rough.js/font, styles, components, home replacement, UI navigation, polling timers, drawer, contextual chat), T025 (economic aggregation), T026–T029 (qualification); no change to T019, execution, authorization, accounting or inbox resolution |
| Delivery route | Local source → independent technical review → integration into `develop` → release 0.2.0 via protected `main` (D242/D253) → distribution/publication → installation. Commit, merge and push only at the owner's or reviewer's request |

| D242 stage | Status |
|---|---|
| Source | Reviewed commit `b30a00c` on `feat/p002-t020-work-map-api` |
| Technical review | Independent final re-review passed on 2026-11-05, including all corrections (§10) |
| Integration | Source `b30a00c` integrated into develop by the accompanying merge; push authorized |
| Release | Pending 0.2.0 via protected `main` |
| Distribution/publication | Pending |
| Installation | Pending; recorded installation 0.1.9 |

## 1. Implementation

| Part | Where | What |
|---|---|---|
| Pure tables and tokens | `core/engine/work_map.py` | T018 §5.2 status tables per entity with `unknown` fallback (raw code kept); R/E/J circle from the CLI role table (passed in, so `core` imports no adapter); bubble attribution per T017 topic; counters `{value, source, reason}`; opaque scope ids (`s1.`), version tokens (`v1.`, digest of source watermarks) and digest-checked keyset cursors (`c1.`) bound to scope and version; page caps (100/200/300/50/200/200/200) |
| Projections | `storage/work_map.py::WorkMap` | One plain connection per read; every query and secondary reference root-scoped; no `history_json`; reused sources: T017 `FACTS` (unresolved, non-notification items, unchanged), T019 `ObservedSteps` (`state`, `page`), T006 `observe()` (pure counters when no `invocation.observed` row exists), run projection `cycle_tests` |
| L0 | `projects` | Project cards: T017 identity and aliases, derived class (§5.2 order), mode and autonomous run with bounds, open phase, phases closed/total, circles (J only with a judge profile or a judge invocation), every active invocation including chat, last activity, errors, bubble counters, configured agents (ordinary mode; `absent` in archives) |
| L1 | `phases` | Accepted roadmap identities merged with instances and run-only codes; roadmap-order edges; tasks committed/total; READY and last check; Plan · Check · Close slots with actors from the operation run's attempts, J from judge requests bound to the check, H from commits or validation cycles |
| L2 | `tasks`, `runs` | Plan tasks, accepted identities of the phase and run-only tasks; latest run (status, stage, executor attempts / revision limit, cycles, acceptance, commit); `depends_on` and `replaces` edges (D296: a replaced task is inactive, its run status kept); run selector latest first |
| L3 | `steps` | Invocations in attempt order with the cycle (format, validate) after its executor round and commit records last; per invocation: role and ordinal label, status (attempt, or process for one in flight), harness attempt, revision round, measured duration, frozen identity (agent, client, versions, requested model/effort), reported model with provenance, launch and termination, `trace-observation-1` counters with sources, deliveries, discovery loads, rulings and permission requests, observed-step state, bubbles |
| L4 | `invocation`, `trace`, `related` | Header with owner context and breadcrumb for every lane (task, phase operation, chat, other lanes, lanes without a run); T019 steps with `source_records` resolved to the existing run-event and attempt-log routes and availability; related `records` (allowlisted identity, code and digest fields of receipt, discovery, broker, tool, ruling, context and observation events, artifact links to the existing thread route) and `permissions` (legacy and T010 requests with T017 item ids) |
| Activity | `activity` | Versions per requested scope (≤ 10; unknown or foreign → `not_found`), up to 50 active invocations, deterministic work, bubble counters, polling metadata (2 s / 10 s, paused when hidden, disabled in archives) |
| API | `api/work_map.py`, `api/app.py`, `api/schemas.py` (`Map*`) | Nine `GET` routes under `/api/managed/map/` behind the existing session and Host/Origin guards; 404 `map_not_found`, 422 `cursor_invalid`, 409 `cursor_stale`; no mutation route |
| Indexes | `migrations/versions/0041_work_map_reads.py`, `storage/models.py`, `storage/schema.py` | `ix_managed_runs_scope`, `ix_managed_attempts_open` (partial), `ix_phase_operations_phase` (§3) and the three circle-target indexes on `usage_invocations` (§6) |
| Catalogs | `i18n/en.json`, `i18n/es.json` | `work_map.not_found`, `cursor_invalid`, `cursor_stale`, `group_invalid` |
| Parity | `frontend/openapi.json`, `frontend/src/api.generated.ts` | Regenerated with the documented commands; no hand edits |

Unchanged: T019's projector and reader, execution, authorization, accounting and inbox resolution; no frontend
component, dependency, lockfile or product version change.

## 2. Evidence

Synthetic only, in `tests/product/test_work_map.py`: the real writers (knowledge adoption, structured phase plan,
executor/reviewer task run with validation and commit, phase check, owner questions, fake-CLI streams through the real
adapter, real retention, real backup and restore) plus synthetic rows where a real process would be needed (an attempt
in flight with a RUNNING/PENDING process and its ledger row, a chat turn's run) and the §12 fixture.

| Test | Shows | Threats |
|---|---|---|
| `test_levels_project_real_sources_with_attribution_concurrency_and_parity` | L0–L4 against the source rows (phase and task counters, slots and their actors, run selector, step order executor → format → validate → reviewer → commit, owner contexts for task and check lanes); absent telemetry stays absent; idle poll ≤ 8 KiB; concurrent executor and chat invocations light E and R (chat) at once on the project, phase and task; tokens change; an owner question blocks the phase (failed, unattributed H bubble); no question, chat, agent text, root or `history_json` in any response | TM14, TM17 |
| `test_guards_isolation_cursors_and_restored_query_only_archive` | 401 without session; Host, Origin and cross-site 403; no mutation route; aliases share a scope; foreign project, run, invocation, phase and task identifiers 404 alike; group and limit validation; complete, disjoint pages; cursors of another level, scope or project and forged ones 422; reads write nothing; a change makes the cursor 409 and a snapshot reload recovers; a sealed trace keeps its token; a real backup restored `query_only` with the checkout moved away serves the same projections, `read_only_archive`, no configuration, polling disabled and an unchanged file | TM15, TM18 |
| `test_every_persisted_status_vocabulary_has_a_class_and_unmapped_values_stay_unknown` | Vocabularies read from the real writers (AST of `.status` assignments, row constructors and status calls), constants and check constraints, plus values written by the real flows: all mapped; a value without mapping is detected and renders `unknown` with its raw code through the API | TM14 |
| `test_trace_states_source_records_retention_and_lazy_pages` | `sealed`, `pending`, `integrity_failed`, `not_projected` (counters and evidence links, no backfill) and `lane_excluded`; no partial pages; lazy pages complete; source records reach the existing event route; oversize records link the log view with size and digest; after real retention they are `unavailable_after_retention` and steps are unchanged; no native content | TM14, TM17 |
| `test_realistic_size_pages_meet_the_poll_and_trace_budgets` | §12 fixture totals; status classes per level; small pages equal the full page at every paged level; idle poll ≤ 8 KiB; 25 trace pages of 200 (§3); runs in every suite | TM15 |
| `test_realistic_size_pages_meet_the_latency_budget_when_measured_serially` | The same reads with the p95 ≤ 150 ms assertion; skipped, with its reason, when other xdist workers share the machine (§4 finding) | TM15 |
| `test_map_reads_use_indexed_bounded_queries_and_never_select_histories` | Every statement the nine routes execute (T017's reused `FACTS` excepted), checked with `EXPLAIN QUERY PLAN`: no full scan of runs, attempts, events, trace events, ledger, processes, metrics, phase events or knowledge links/members; no statement selects `history_json` | TM15 |
| `test_0041_round_trip_adds_and_drops_only_the_map_indexes` | Downgrade to 0040 drops the seven indexes and keeps every row; upgrade and `alembic check` restore them; reads equal | — |

## 3. Measurements (development machine: Apple M5, Python 3.14.4; 2026-11-05)

Method: the §12 fixture is one deep path with per-level maxima and leaf siblings (25 projects, 40 phases of the deep
project, 80 tasks of its active phase, 30 runs of its deep task, 40 invocations of the deep run, 5,000 observed steps
of one invocation plus its sealed marker, 300 open inbox items: 150 owner questions and 150 pending run permissions).
Each route is read 20 times through the authenticated test client after one warm read; p95 is the 19th 20-quantile.
The trace is paged once completely with pages of 200.

| Read | p95 (two runs) | Budget |
|---|---|---|
| L0 projects (25 cards) | 16.8 / 16.9 ms | ≤ 150 ms |
| L1 phases (40) | 24.0 / 24.3 ms | ≤ 150 ms |
| L2 tasks (80 nodes, 79 edges) | 9.0 / 8.9 ms | ≤ 150 ms |
| Run selector (30) | 3.0 / 3.1 ms | ≤ 150 ms |
| L3 steps (40 invocations) | 26.1 / 25.1 ms | ≤ 150 ms |
| L4 header | 2.8 / 2.6 ms | ≤ 150 ms |
| L4 related (permissions) | 1.6 / 1.6 ms | ≤ 150 ms |
| L4 trace, 25 pages of 200 over 5,000 steps | 18.1 / 17.9 ms | ≤ 150 ms; pages ≤ 200 |
| Activity poll (7 scopes, idle) | 11.9 / 11.9 ms; **1,526 bytes** | ≤ 8 KiB idle |

Earlier serial runs measured at most 21.0 ms (L0) and 49.2 ms (L3); every serial run stayed within budget. Under the
full parallel suite (`-n auto`, every core busy with other tests) the same reads measured p95 118 ms (L0), 190 ms (L1)
and 159 ms (L2), see §4.

Index justification (scratch script, not committed): the same reads with and without the 0041 indexes, on the fixture
alone and beside 20,000 extra runs and attempts in 200 other projects (L0 then pages 100 cards):

| p95 (ms) | L0 | L1 | L2 | Runs | L3 | Activity |
|---|---|---|---|---|---|---|
| Fixture, indexes | 12.5 | 8.1 | 9.2 | 3.3 | 41.5 | 11.5 |
| Fixture, no indexes | 13.0 | 8.2 | 8.8 | 3.0 | 42.0 | 11.8 |
| +20,000 runs, indexes | 51.6 | 8.7 | 12.1 | 3.3 | 44.3 | 23.9 |
| +20,000 runs, no indexes | **340.2** | 14.3 | 14.5 | 5.2 | 43.0 | **199.4** |

Without the indexes the L0 page and the poll exceed their budget as the history grows; with them they stay well inside.

## 4. Checks

- Focused during implementation: `scripts/check tests/product/test_work_map.py` and the affected suites
  (`test_storage_api`, `test_observed_steps`, `test_inbox`, `test_backup`, `test_installed_migration`,
  `test_development_checks`, `test_dev_command`, `test_start_command`, `test_usage_accounting`): 220 passed.
- Closing `scripts/check --frontend` (once): unittest 10 ok; `alembic check` ok (no new upgrade operations); pytest
  **3,220 passed, 2 skipped, 1 failed**, 29 subtests (the one warning is the known wheel duplicate-name notice of the
  deliberately corrupting packaging case); Node 280/280; `tsc` and Vite build ok.
- **Finding from the closing run (first round; this full run is not a passed suite):** the only failure was the latency assertion of the §12 test inside the parallel
  suite (p95 L1 190 ms, L2 159 ms) while the same reads take ≈ 9–25 ms serially. The suite runs `-n auto` on every
  core (D125), so in-suite wall time measures worker contention, not D309's development-machine condition. The
  150 ms budget is unchanged: the latency assertion moved to its own test, asserted in serial runs and skipped with an
  explicit reason under parallel workers; sizes, totals, statuses, poll size and paging stay asserted in every suite.
  After that test-only change: `scripts/check tests/product/test_work_map.py` 7 passed, 1 skipped (parallel), and
  `scripts/check tests/product/test_work_map.py -- -n 0` 8 passed (serial, budget met: worst p95 35.4 ms). The full
  suite was not repeated after this change, which touched only `tests/product/test_work_map.py`.
- `scripts/check-docs`: 124 Markdown files, 0 errors. `git diff --check` clean; untracked files checked the same way.
- OpenAPI and client types regenerated with `scripts/export_openapi.py` and `npm --prefix frontend run generate:types`;
  the generated diff is additions only.

## 5. Not verified and residual risks

- No real agent, provider, installed CLI, network or harness run; no service start or `scripts/dev`. In-flight
  attempts and chat turns are synthetic rows shaped as the supervisor writes them; fake ports spawn no process, so
  their duration and termination are absent (and shown so).
- No UI consumes the routes yet (T021–T023): the polling timers, rendering and navigation are not exercised. The
  frontend build and type check run over the regenerated types only.
- Version tokens are digests of watermarks that every relevant writer advances (row versions, insert-only
  sequences); a writer that changed a displayed field without advancing its row version would not change a token.
  The current writers do (each run, phase and autonomous event increments its row's version); process status
  changes and time-based inbox resolution are folded in directly.
- The run-only tasks of L2 are found by a skip scan that must step over plan and identity tasks that also have runs;
  that work is bounded by the phase's own task set, not by run history.
- Source-record availability is derived from the persisted retention audit; a file lost without a tombstone shows
  `available` until the log route, which verifies bytes on read, reports it missing.
- The T017 `FACTS` projection is reused unchanged, including its own scans of the inbox source tables; it is read once
  per request and bounded by unresolved owner items, not by history; at the §12 size it costs a few milliseconds and
  its scaling is T017's.
- Measurements are from one development machine and synthetic data. Under full CPU contention (the parallel suite)
  pages can exceed 150 ms; the reviewer accepted asserting the budget in a serial run that is part of every closing
  (§6), without presenting the first-round full suite as passed.
- Preparation and configuration-assistance lanes are exercised with rows written as their journals persist them, not
  through a live preparation or assistance; a global assistance has no project and stays unscoped by design.


## 6. First technical review corrections (2026-11-05)

The review repeated `scripts/check tests/product/test_work_map.py -- -n 0` (8 passed), `scripts/check-docs` and
`git diff --check`, and confirmed by semantic comparison that OpenAPI kept every earlier route and schema and added
nine routes and 49 schemas. It found six defects that block integration. All are corrected in
`storage/work_map.py` (and `core/engine/work_map.py`, the schemas and the router) with the regressions below in
`tests/product/test_work_map.py`; each fails against the first-round code.

| # | Finding | Correction | Regressions |
|---|---|---|---|
| 1 (P1) | `tasks()` and `steps()` paged by position after building every node or step (`steps(limit=1)` called `ObservedSteps.state()` for all 40 invocations); L0 loaded every identity; permission pages loaded every request; L1 and the selector rebuilt whole sets to check existence | Keyset over stable keys (L0 last project key over checkout roots by skip scan; L1 phase code over instances, identities and a run skip scan; L2 group and plan position or code; L3 attempt number and sub-step, then the tail; runs and permissions creation time and id). Only the page's rows are selected and only they are enriched; whole-scope counters are SQL aggregates (`PHASE_COUNTS`, `TASK_COUNTS`); existence checks are bounded lookups of one code | `test_pages_read_and_enrich_only_their_rows_however_long_the_history`: first pages of every level read the same rows, detail calls (`_invocation_step`, `ObservedSteps.state`, `_project_card`) and statements after 60 projects, 300 runs, 40 attempts, 50 tasks, 100 permission requests and 30 phases are added; full walks stay complete and duplicate-free (85 projects, 70 phases, 130 tasks in node order, 330 runs, every step, 104 requests); the L1 counter equals its L2 nodes |
| 2 (P1) | A step going `pending → sealed` kept the L3 version; changing the configured model kept the L0 version | Per-scope sources (D311): L3 and the L4 header add the latest step marker, observation and related event per invocation, delivery counts and the permission sequence; L0 and L1/L2 add the configured agents; the trace token adds its own attempt's retention removals and nothing else | `test_tokens_follow_every_displayed_source_and_ignore_foreign_changes`: the real projector seals a step without changing the run version and the L3, L4 and poll tokens move while another trace's stays; `409 cursor_stale` for that trace's old cursor; retention of one attempt's stdout moves its trace token (stale cursor, reloaded pages show `unavailable_after_retention`) and not the other's; a run in another project moves L0 only; a different configured model is a different L0 and L1 version |
| 3 (P2) | `acceptance_json IS NOT NULL AS accepted` reported a negative evaluation as accepted | `acceptance` from the projection: `absent`, `rejected` (with its deterministic reasons), `eligible` or `unknown`, separate from the commit, on L2 nodes and in the run selector | `test_a_rejected_acceptance_is_projected_as_rejected_not_accepted`: a failing validation command (real JUnit run) is `rejected`, equal to the run projection, with no commit; absent and eligible stay distinct |
| 4 (P2) | T010 requests ignored the authorization chain and its end records (a request with an expired parent showed `PENDING`) | `PermissionLifecycle.active` for validity and the request's own and ancestors' expiry and end records for the reason, as T017 resolves the item: unanswered requests become EXPIRED or REVOKED and not `answerable`; answered ones keep the historical answer and report the grant's current `authority` | `test_standing_permission_validity_follows_t010_ancestry_and_matches_the_inbox`: pending, expired and ended ancestors; effective, expired and revoked grants; equal to `active()` and to T017's unresolved set; time alone moves the related token and the inbox resolves the same request |
| 5 (P2) | L2 lacked `problem` and `expected_result`; `_active()` saw only managed attempts; J and circle targets were missing at L1/L2 | Bounded accepted texts with source or `absent`; active preparation executor steps and project-scoped configuration assistance from their own ledgers (preparation commands are H work; a global assistance is `unscoped_invocations`); circles carry `shown`, `latest_invocation` (L4 target) or `inert`, and `waiting`; J from a judge profile or judge history in the element; slot actors name their invocation | `test_other_lanes_judge_history_circle_targets_and_waiting` and the extended level test: preparation and assistance lanes with `lane_excluded` L4 and no manufactured attempt; a global assistance stays unscoped and 404 through the project; J appears where a judge ran and with a profile only; targets open L4; H waits on the READY confirmation with nothing running; L2 inspector texts |
| 6 (P2) | `read_scope()` indexed `data[0]` before checking its type: `s1.` + base64url of `[[]]` gave HTTP 500 on `/activity` | Types, level and arity are checked before use; decoding errors map to the caller's token kind; scopes answer 422 `scope_invalid`, cursors 422 `cursor_invalid` (also for non-string scope or version fields and foreign alphabets) | `test_malformed_scopes_and_cursors_are_contract_errors_never_500`: nested lists and objects, wrong types, wrong arities, unknown levels, bad alphabets and prefixes; foreign but well-formed scopes still answer `not_found` without revealing anything |

Accepted by the reviewer: the latency budget is asserted in a serial run with the 150 ms threshold unchanged, part
of every closing; under several workers that assertion is skipped with its reason while the functional, size and
paging assertions run.

Measurements after the corrections (serial, development machine): L0 18.2 ms, L1 30.9 ms, L2 21.4 ms, runs 1.9 ms,
L3 25.5 ms, L4 header 2.5 ms, related 1.6 ms, trace pages 17.7 ms (25 pages of 200), activity 11.2 ms; idle poll
1,552 bytes. All within D309's budgets; L1 grew by the circle-target seeks (one per role and element).

Checks for this round:

- Focused: `scripts/check tests/product/test_work_map.py` 13 passed, 1 skipped (parallel; the serial latency test);
  `scripts/check tests/product/test_work_map.py -- -n 0` 14 passed (serial, budget asserted); with the affected
  suites (`test_storage_api`, `test_observed_steps`, `test_inbox`, `test_backup`, `test_permission_lifecycle`,
  `test_installed_migration`, `test_development_checks`, `test_dev_command`, `test_start_command`,
  `test_usage_accounting`): 266 passed, 1 skipped.
- Schema: the circle targets of finding 5 first read the element's ledger range and sorted it (`EXPLAIN`: a search on
  `ix_usage_invocations_scope` plus a temporary B-tree). `0041_work_map_reads`, not yet integrated, now also adds
  `ix_usage_invocations_circle_root`, `…_circle_phase` and `…_circle_task`, so each is one seek per role; the plan test
  asserts index seeks with no sort beside them, and the 0041 round trip covers the six indexes (still 94 tables).
- OpenAPI and client types regenerated with the documented commands.
- Closing results: see §7.

## 7. Closing checks after the corrections (2026-11-05)

- `scripts/check --frontend` (once, on the final code): unittest 10 ok; `alembic check` ok; pytest **3,227 passed,
  3 skipped**, 29 subtests (the skips include the serial latency test under parallel workers; the one warning is the
  known wheel duplicate-name notice); Node 280/280; `tsc` and Vite build ok.
- Mandatory serial measurement: `scripts/check tests/product/test_work_map.py -- -n 0`: 14 passed, budget asserted
  (worst p95 L1 31.0 ms; idle poll 1,552 bytes).
- `scripts/check-docs`: 124 Markdown files, 0 errors; `git diff --check` clean.
- Independent re-review, integration, release 0.2.0, distribution and installation remain pending.


## 8. Three independent re-review remnants (2026-11-05)

The independent re-review passed the 14 serial focused tests, documentation and diff checks, but reproduced three
remaining defects. These corrections are local source, not an approval of the independent review. Delivery remains
local source → further independent review → authorized integration → release 0.2.0 → distribution → installation.

- **L2 exhaustion and group transitions:** run-only exclusion no longer calls `_identity_tasks(codes=None)`.
  SQL excludes plan codes and accepted phase membership with `NOT EXISTS`; key selection reads codes only, and
  inspector texts and run details are enriched for the displayed page. The new middle/final-page regression repeats
  79 then 1, adds 40 accepted identities outside the plan and 50 run-only tasks, checks bounded identity
  materialization and per-node circle detail calls, compares intermediate reads before/after off-page growth, and
  walks all 170 tasks in pages of 1, 7 and 79 without omissions or duplicates, across both group transitions.
- **Grant expiry:** the permission dependency CTE seeds both requests and their answer grants before following
  parents. The clock-only regression keeps the request parent permanent, expires only the grant at 11:00 (10:00 →
  12:00), and separately covers a grant with its own expiring parent. Historical GRANTED/response stays intact;
  authority becomes expired, direct and activity tokens agree and move, and the old paginated cursor answers
  `409 cursor_stale`. Run version and immutable record counts remain unchanged.
- **Circle ownership:** regular lanes retain their element indexes; chat candidates resolve the conversation's
  phase or associated task run, and project assistance resolves its registered project and persisted ASSIST
  operation even after completion. Each branch returns its latest `(started_at, id)` candidate, merged across
  lanes. L4 task-chat ownership now includes the associated run's phase and task, matching activity. Tests cover
  phase/task chat active and settled, chronology, correct L4, foreign phase isolation, project assistance active
  and settled, newer foreign/global assistance exclusion and L4 project isolation. No ledger or frozen context is
  rewritten. The additive 0041 migration now has seven indexes (94 tables): the seventh is
  `ix_usage_invocations_circle_project (project_id, role, started_at, id)`.

Access-plan evidence: the captured-query EXPLAIN regression covers the new branches. Regular lanes use their
root/phase/task circle indexes; chats use the root/role ordered range plus indexed conversation/turn references;
assistance uses the project/role ordered range and a primary-key fetch of the selected invocation. There is no
history sort beside a ledger seek and no full scan of the large source tables. Chat scope filtering can visit
candidates from other conversations within the same root/role range; SQL returns only the selected row. Schema
round-trip verifies all seven indexes and unchanged persisted rows. Public routes/types are unchanged by this
round, so the existing OpenAPI/client artifacts need no regeneration.

Closing evidence for this round:

- `scripts/check tests/product/test_work_map.py -- -n 0`: **19 passed**, including the mandatory serial
  latency assertion at the unchanged 150 ms budget, the grant-only and grant-parent clock crossings and both chat
  scopes. The original 14 regressions remain in the suite.
- `scripts/check --frontend` executed **once**: unittest 10 ok; Alembic check ok; pytest **3,109 passed,
  97 failed, 26 errors, 3 skipped**, 29 subtests, one known packaging warning; Node **280/280** and tsc/Vite build ok.
  This full run is **not** a passed suite. Failures/errors are confined to `test_tool_bridge`, `test_judge`,
  `test_start_command` and `test_cli_diagnostics`: the restricted environment refuses AF_UNIX or loopback socket
  binding (`PermissionError: [Errno 1] Operation not permitted`), including setup errors and downstream admission
  failures. Its complete report is preserved in `.local/check/t020-full-pytest.log`.
- Focused recovery with local-socket permission: `scripts/check tests/product/test_tool_bridge.py
  tests/product/test_judge.py tests/product/test_start_command.py tests/product/test_cli_diagnostics.py -- --lf`:
  **123 passed** (11.0 s), exactly the 97 failures and 26 setup errors above. No product change was needed to clear
  them; all use synthetic fixtures/fake CLIs, without a real agent/provider or operational service. The full suite
  was not repeated and its original result remains reported separately.
- `scripts/check-docs`: **124 Markdown files, 0 errors**. Reviewed tracked diff and all seven new files;
  `git diff --check` and the equivalent check for new files are clean. STATE/NEXT_STEPS reflect local corrections
  and pending review/delivery; ONE_OFF_TASKS remains empty.

No UI, network, real agent/provider, operational
service start, harness run, release, distribution or installation is exercised.


## 9. Historical assistance after logical registry retirement (2026-11-05)

Independent review confirmed the three preceding corrections and all 19 serial focused tests (including latency),
documentation and diff checks. It reproduced one remaining P2: both the assistance branch of `_latest()` and
`_invocation()` required an ACTIVE registered project. Retiring that registration erased the circle target and
made L4 and its scopes unavailable although the knowledge project and immutable evidence remained in SQLite.
This section records the local correction; independent review is not declared approved.

Historical circle selection and invocation ownership now resolve the persisted registration without an ACTIVE
predicate. Retirement still governs operational admission; the active-lane queries and existing guards are
unchanged. No registration is reactivated, no project is composed and no ledger or frozen context is rewritten.
The seven-index migration is unchanged; ARCHITECTURE's stale six-index count is corrected to seven. Each historical
registry candidate still selects at most one ledger row per role through the project circle index, and L4 resolves
its registration by primary key. The small registry metadata lookup now includes retired rows; no invocation
history is materialized. Public routes/types are unchanged, so OpenAPI/client regeneration is unnecessary.

`test_retired_registry_preserves_settled_assistance_history_and_archive` uses a knowledge-only project with no
pending operations, an ASSIST/APPLIED operation and a settled root-NULL ledger invocation. It fails on the preceding
code when the target disappears after retirement. It verifies the same historical target, L4 header, excluded
steps, a persisted receipt, both related groups and activity-scope versions before and after retirement. Foreign
project invocations and global assistance remain refused. Backup/restore repeats these checks in query_only mode
with no composed project and the checkout removed; the restored database hash remains unchanged. The original
ledger rows remain unchanged and the registration remains RETIRED.

Closing evidence:

- `scripts/check tests/product/test_work_map.py -- -n 0`: **20 passed** (31.7 s), including the mandatory serial
  150 ms budget and all 19 earlier regressions. The new retirement/archive regression also passed on its own;
  it failed against the preceding implementation when the historical target disappeared.
- `scripts/check --frontend` executed once for this correction: unittest **10 ok**; Alembic check ok;
  pytest **3,109 passed, 98 failed, 26 errors, 3 skipped**, 29 subtests, one known packaging warning;
  Node **280/280**, tsc and Vite build ok. This full run is **not** a passed suite. Its original report is preserved
  separately at `.local/check/t020-retired-registry-full-pytest.log`; the preceding round's report remains at
  `.local/check/t020-full-pytest.log`.
- Of those results, the same **123 socket-restricted cases** are in the four files documented in §8 (97 failures,
  26 setup errors); focused recovery with local-socket permission using the four paths documented in §8 and
  `--lf`: **123 passed** (10.7 s), without another general suite.
- The additional failure is `test_managed_lease::test_stream_survives_real_sqlite_busy_during_one_renewal`:
  heartbeat evidence counted two transient OperationalError failures rather than the expected one under the
  parallel run. Its isolated serial check, `scripts/check
  tests/product/test_managed_lease.py::test_stream_survives_real_sqlite_busy_during_one_renewal -- -n 0`,
  **passed** (5.8 s), without any lease/product/test change. Serial recovery is consistent with contention;
  the full-run failure remains recorded and is not presented as a clean full suite.
- `scripts/check-docs`: **124 Markdown files, 0 errors**. Reviewed tracked diff and all seven untracked source/
  documentation files; `git diff --check` and the equivalent new-file whitespace checks are clean. Current STATE
  and NEXT_STEPS retain pending independent review and delivery; ONE_OFF_TASKS is still empty.

Source stays uncommitted on
`feat/p002-t020-work-map-api` from `c993564`; further independent review, integration into develop, release 0.2.0,
distribution and installation remain pending. Evidence remains synthetic only, with no operational service,
harness, real agent/provider, network installation or global configuration change.


## 10. Independent final re-review — 2026-11-05

Passed with no outstanding relevant findings. The final inspection covers the accumulated implementation and all
corrections, including L2 group transitions, grant-only and grant-parent expiry, effective chat/assistance owners
and historical assistance after logical registry retirement. Reads preserve project isolation and query-only
consultation; the retirement correction changes no operational admission guard or immutable record.

- Independently repeated `scripts/check tests/product/test_work_map.py -- -n 0`: **20 passed** (41.02 s in pytest),
  including the unchanged 150 ms serial budget and all prior regressions. Report: `.local/check/t020-review-focused.log`.
- Parsed the original final full-suite report in §9: **124 distinct failed/error node IDs**, exactly 123 cases in
  the four socket-restricted files plus the SQLite lease-contention case. Re-ran those exact node IDs serially with
  permission for local sockets: **124 passed** (45.16 s), without any product or test change. Selection and report:
  `.local/check/t020-review-recovery-ids.json` and `.local/check/t020-review-recovery.log`.
- The original general run remains **3,109 passed, 98 failed, 26 errors, 3 skipped**, not a clean general run.
  The independent recovery accounts for every failed/error node. Its separate result does not rewrite §9's
  evidence. The general suite was not repeated after these focused checks passed.
- Inspected the recorded successful unittest (10), Alembic, Node (280/280) and TypeScript/Vite checks from the
  final implementation. Semantic OpenAPI comparison adds nine paths and 52 schemas, with no changed prior path
  or schema. Documentation and whitespace checks passed and are repeated for these status-only edits.
- No real agent/provider, operational service, harness execution, network installation or global configuration
  change was used. Native qualification, UI rendering and installed behavior remain outside this evidence.

The owner authorized source commit, merge into develop and push of develop after successful review in this
review session. This authorization covers P002-T020 only. Release 0.2.0 via protected main,
distribution/publication and installation remain pending; the recorded installation stays 0.1.9.


## 11. Source integration — 2026-11-05

Reviewed source commit `b30a00c` on `feat/p002-t020-work-map-api` from `c993564` is integrated into develop by the
accompanying merge. The merge adds the source identity and updates current delivery status only; product source,
OpenAPI/client artifacts and tests are identical to the reviewed commit. `scripts/check-docs` checked all 126
tracked Markdown files with 0 errors after the status updates; whitespace checks passed. The one-off queue remains
empty and P002-T021 is next.

The owner authorized source commit, merge into develop and push of develop after successful review. Release 0.2.0
through protected main, distribution/publication and installation remain pending. Installed behavior remains 0.1.9.
