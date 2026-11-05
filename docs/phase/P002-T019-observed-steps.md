# P002-T019 — Observed-step projection

**Status:** source complete with synthetic evidence; **independent final re-review passed** on 2026-11-05 (§8).
The owner authorized source commit, integration into develop and push after successful review. Integration is
pending. Decisions: [D305](../DECISIONS.md#d305--observed-step-projection-from-sealed-native-evidence)
(contract) and [D310](../DECISIONS.md#d310--observed-step-pending-marker-projector-and-reads) (choices delegated to
this task).

## Ownership and delivery

| Field | Value |
|---|---|
| Owner task | P002-T019 (backend: engine, storage and recovery); no gates pending (G14 resolved by T018) |
| Branch | `feat/p002-t019-observed-steps` from `develop` at `ce244e4` (verified clean and equal to the local `origin/develop` on 2026-11-04) |
| Schema | From `0039_inbox_read_marks` (94 tables) to `0040_observed_step_reads` (index only, 94 tables) |
| Contract | [T018 §§6, 12–14](P002-T018-work-map-contract.md#6-observed-step-projection-t019), D305, [D309](../DECISIONS.md#d309--accessibility-and-realistic-size-budgets-for-the-work-map); boundaries D287, D289, [T002 §4](P002-T002-feasibility.md#4-observation-coverage-g05) |
| Scope | Durable observed steps of every settled managed attempt (task, phase, chat, definition, planning, bootstrap, judge and roadmap review lanes), with or without a `workflow_operation` |
| Out of scope | Preparation steps and configuration assistance (lane excluded); map API, source-record resolution and availability (T020); rendering, inspector and contextual chat (T021–T024); L4 treatment of earlier runs (T020/T023 consume the counters this task leaves available) |
| Delivery route | P002 → `develop` with the phase; 0.2.0 via protected `main` (D242/D253). Commit, merge and push only at the owner's request |

| D242 stage | Status |
|---|---|
| Source | Complete after two rounds of corrections; source commit authorized |
| Technical review | Independent final re-review passed on 2026-11-05, including both rounds of corrections (§8) |
| Integration | Pending into `develop` |
| Release | Pending 0.2.0 via protected `main` |
| Distribution/publication | Pending |
| Installation | Pending; recorded installation 0.1.9 |

## 1. Implementation

| Part | Where | What |
|---|---|---|
| Capture boundary | `core/engine/metrics.py` (`StreamMetrics.event`), `adapters/cli_agents.py` (read loop) | The live `metrics-1` counters read a non-list Claude `content` as no blocks, so a malformed record is journaled with its chunk and the capture goes on; if an unforeseen failure still interrupts the read, the chunk already written and the records read from it are flushed to the journal (best effort) before the interrupted capture is written (§7) |
| Pending marker | `storage/managed.py` (`_history`, `confirm_stopped`), `storage/observed_steps.py::mark_pending` | `invocation.steps_pending` in the transaction that stores the attempt result or the interruption; the session records the invocation id and `_write` calls `steps_notify` after the commit |
| Derivation | `core/engine/observed_steps.py` (pure, derivation 1) | Claude `claude_message` turns by message id; `tool_use`/`tool_result` by id; `is_error` → `error`; terminal `permission_denials` → `denied`; thinking → reasoning; terminal result → final message. Codex `codex_turn` from `turn.started`/`turn.completed`/`turn.failed`; items by id (`completed`, `failed` → `error`, other statuses `unclassified` with the raw code); reasoning and agent messages (the last one before a completed turn is final). Record-order overlap → `parallel` and the turn's `max_concurrency`. Harness broker calls link `broker.called`/`broker.result`/`tool.called`/`tool.result` by name and argument digest only when that pair is unique in the whole invocation (calls past the step bound counted too; an ambiguous call keeps `link_absent`), and `tool.discovered` only when exactly one call can own it. Codex call fields first carried by a later record (MCP server, tool, arguments; a file-change list) are incorporated, never replaced; a call first seen at `item.updated` has no start or duration; a final message without text is an absent final answer (`message_text_absent`) |
| Gaps | same | `invalid_record`, `partial_tail`, `oversize_record_unavailable` (with code, size, digest), `unsupported_event` (with type), `unsupported_client`, `no_stream`, `cancelled_in_flight`, `step_bound_reached` (with remaining counts by kind). Open turns and calls end `cancelled_in_flight` after a supervisor stop and `not_observed` otherwise; a Codex turn end without its start is labelled `start_observed: false`, never manufactured |
| Privacy | same | Arguments: size and sha256 of the native canonical JSON plus a summary masked (secret patterns and sensitive keys) **before** truncation to 256 characters; results, messages and reasoning: presence, size and sha256 only. Names and codes masked and bounded. `trace-payload-1` applies on write |
| Source records | same | Up to four `{run_id, attempt_id, sequence, record, oversize}` per step (first three and the latest), with `source_record_count` |
| Timing | `storage/observed_steps.py::_inputs` | Receipt time of the latest stdout `stream_bytes` chunk before each record in run order (the chunk carrying its newline, D252), labelled `chunk_receipt` |
| Oversize records | `storage/observed_steps.py::StdoutRanges`, `storage/backup.py::opened` | Only when present and only with the sealed capture artifact (else `capture_absent`): no-follow open of every path component (regular file, one link, ≤ 256 MiB), one read against every chunk digest and the capture's digest and size, then each range at its offset, one at a time (≤ 4 MiB + 1 byte), against its own digest |
| Projector | `storage/observed_steps.py::ObservedStepProjector` | Reads in plain sessions, writes batches of 250 under the writer lock, each first checking that no terminal marker exists; the seal also requires the persisted step keys to equal the derived sequence; identical replay is a no-op; a divergent payload or step set writes `invocation.steps_failed` once. `run_pending` is the recovery pass, a keyset over marker ids with a stop check before each invocation; `project` checks the same stop before each batch and before the seal, and a stopped projection stays pending |
| Runtime | `services/observed_steps.py`, `services/managed_runtime.py` | `observed-steps` thread started with the supervisor; woken by the repository hook; one pass over every pending marker at start and on each wake or after 10 s idle; stopped with the runtime, and the stop reaches a projection in progress |
| Thread traces | `storage/operation_journal.py` (`events`, `artifact`) | The T006 thread queries never serve `invocation.step` rows |
| Retention | `storage/retention.py::_eligible` | An unsealed projection (pending or failed) makes both streams ineligible with a diagnostic naming the attempt, in preview, apply and the revalidation between intent and effect |
| Reads | `storage/observed_steps.py::ObservedSteps` | `state` and `page` (keyset after the step event id, ≤ 200); states `sealed`, `pending`, `integrity_failed`, `not_settled`, `not_projected` (with persisted or derived `trace-observation-1` counters and the run evidence), `lane_excluded`; optional root scope; works on `query_only` restores |
| Index | `migrations/versions/0040_observed_step_reads.py`, `storage/models.py` | `ix_trace_events_invocation` (invocation_id, kind, id) |
| Catalogs | `i18n/en.json`, `i18n/es.json` | `retention.steps_pending`, `observed_steps.*` states, reasons and read errors |

Unchanged: `invocation.observed`, `trace-observation-1`, the `metrics-1` semantics (its counters read a malformed
`content` as no blocks instead of raising; every record that did not raise counts exactly as before), the accounting
ledger, operation statuses and
T006 semantics; no HTTP contract, OpenAPI, generated client, frontend, dependency or lockfile change.

## 2. Evidence

Synthetic only: fake CLIs (`tests/product/cli_process_probe.py`, new `scripted` mode, and the existing modes)
through the real adapter, supervisor journal and repository on temporary SQLite. Tests in
`tests/product/test_observed_steps.py`:

| Test | Shows | Threats |
|---|---|---|
| `test_claude_steps_keep_order_correlation_parallelism_errors_denials_and_sources` | Ordinary path after commit, no operation; order, call/result correlation, repeated records, parallel calls, error and denial, final message, timing, resolvable source records, no content stored | TM14, TM17 |
| `test_codex_turns_items_failures_parallelism_and_broker_links_with_an_operation` | Codex turn and items, failed and unclassified statuses, broker links from synthetic broker events, absent denials/request turns, thread and operation links | TM14 |
| `test_settlement_records_only_the_pending_marker_in_its_transaction` (Claude executor, Codex planner and reviewer) | Settlement writes only the marker; projection after it; nothing owed afterwards | TM15 |
| `test_malformed_truncated_and_unsupported_records_become_gaps_without_closing_open_work` | Invalid record, unsupported event, partial tail; open turn and call stay `not_observed` | TM14 |
| `test_supervisor_cancellation_leaves_the_turn_and_call_in_flight` | Codex SIGTERM exit 0 classified as cancellation; `cancelled_in_flight` | TM12, TM14 |
| `test_confirm_stopped_settles_an_interrupted_attempt_with_its_pending_projection` | Marker written by `confirm_stopped`; T006 FAILED unchanged | TM12 |
| `test_oversize_records_are_verified_against_the_capture_and_every_chunk` (none, missing, corrupt range, corrupt elsewhere) and `test_oversize_ranges_need_the_sealed_capture_and_a_path_without_links` | Large ranges verified or explicitly unavailable; results without a derivable call are counted, never guessed; links refused | TM14 |
| `test_arguments_are_masked_before_truncation_and_only_digests_are_kept` | A secret straddling the 256-character cut and a sensitive key are masked; no secret or result text anywhere in the projection | TM17 |
| `test_bounds_cut_at_ten_thousand_events_or_four_mib_with_remaining_counts` | Both bounds with the closing marker and remaining counts | TM15 |
| `test_missing_evidence_and_unsupported_clients_are_explicit` | `no_stream`, `unsupported_client` | TM14 |
| `test_a_crash_mid_projection_stays_pending_and_the_recovery_pass_converges` | Partial write stays pending (no partial truth); a restarted worker's first pass converges to the clean derivation; replay writes nothing | TM12 |
| `test_a_divergent_replay_is_an_integrity_failure_and_nothing_is_overwritten` | Changed evidence after a partial write → `steps_failed`, rows unchanged, not retried, retention still protects | TM12, TM14 |
| `test_attempts_settled_before_t019_are_not_backfilled` | No marker → `not_projected` with persisted (operation) or derived counters and run evidence; nothing written | TM14 |
| `test_excluded_lanes_and_foreign_roots_are_explicit` | Preparation lane excluded; foreign root and unknown ids not revealed; invalid cursor refused | TM15 |
| `test_retention_keeps_pending_streams_and_steps_survive_retention_backup_and_query_only_restore` | Preview, apply and revalidation keep pending streams naming the attempt; archive with a pending projection reads `pending` and writes nothing; after sealing, retention removes the bytes, steps stay readable, backup/restore `query_only` pages them identically | TM12, TM15 |
| `test_keyset_pages_of_a_5000_step_trace_meet_the_150_ms_p95_budget` | 5,001-step trace through the real CLI path, pages ≤ 200, dense order, p95 within budget | TM15 |
| `test_every_managed_lane_owes_and_seals_its_projection` | Task (executor, reviewer), chat and phase-check lanes with scripted agents (`no_stream`) | TM14 |
| `test_0040_round_trip_keeps_steps_and_older_downgrades_refuse_while_they_exist` | Index-only downgrade keeps rows; below 0032 refused (D287) | — |
| `test_the_runtime_projects_settled_attempts_in_the_background` | Composed service: supervisor settles, hook wakes the thread, every attempt sealed | TM12 |

Adjusted existing tests (same intent, new reality): `test_retention.py` fixture, `test_metrics.py` retention and
`test_p001_qualification.py` retention run the projection pass the runtime performs before retention;
`conftest.clear_accounting` also removes synthetic step rows (lifting and restoring the trace triggers) because
downgrades below 0032 now refuse with them, exactly like the accounting rows it already removed; `test_chat.py` and
`test_metrics.py` expect 0032's refusal before 0028's.

## 3. Measurements (development machine, 2026-11-04)

| Measurement | Result | Budget |
|---|---|---|
| Step pages over the 5,001-step trace, 208 page reads (8 full passes of ≤ 200), with the index | p95 1.8–4.4 ms (two runs) | ≤ 150 ms (D309) |
| Same, before the index existed (trace alone in the database) | p95 3.1 ms | — |
| Scratch scale check (not committed): same trace beside 150,000 / 600,000 other step events | 7.3 / 20.7 ms without the index (plan: `(kind, root)` index plus a temporary sort); 1.6 / 1.7 ms with it | — |
| Projection of the 5,001-step trace (read, derive, write, seal) | 1.4–1.5 s, outside the settlement transaction | — |
| Payload of the 5,001-step trace | under 4 MiB, no bound reached | 4 MiB |

The budget is met with a wide margin. The index is justified by the growth of the unindexed plan with the
installation's projected history, not by the §12 fixture alone (D310).

## 4. Checks

- Focused: `scripts/check tests/product/test_observed_steps.py` and the affected suites (operation journal, trace
  observation, retention, backup, managed, CLI agents, chat, metrics, usage accounting, phases, permissions,
  project preparation, Git, P001 qualification, storage API, dev command): pass.
- Closure before the review: `scripts/check` — unittest 10 ok; `alembic check` ok; pytest 3191 passed, 2 skipped.
- Closure after the review corrections (final diff): `scripts/check` — unittest 10 ok; `alembic check` ok; pytest
  **3207 passed, 2 skipped**, 29 subtests; `scripts/check-docs` 0 errors; `git diff --check` clean (and the new
  untracked files checked the same way). The one warning is the wheel duplicate-name notice that the
  deliberately corrupting `[duplicate]` packaging case produces, as the reviewer confirmed.
- Focused runs during the corrections: the 41 T019 tests, and the operation journal, backup (shared `opened`
  helper), configuration backup, retention, trace observation, CLI agents, metrics, P001 qualification, usage
  accounting and tool bridge suites (316 passed).
- `scripts/check-docs`: 0 errors (links, anchors, fences, en/es keys, DDBB head and table count).
- Not run: `scripts/check --frontend` (no frontend or frontend catalog change); no OpenAPI export or client
  regeneration (no HTTP contract change).
- After the second review's corrections: see §7.

## 5. Not verified and residual risks

- The capture failure that §6 deferred (a Claude `assistant` record with a non-list `content` raised in
  `StreamMetrics.event` before its chunk was journaled) is resolved through the ordinary path in §7: the live
  capture journals the chunk and the record, settles normally and the projector marks the record in place.
- The best-effort flush on an unforeseen capture failure (§7) cannot record anything when the journal itself is
  what failed (for example lost ownership); the bytes then remain only in `stdout.bin`, as before.

- No real agent, provider, installed CLI, network or harness run on this repository. Stream shapes follow T002's
  characterization and the fake CLI; newer Claude Code or Codex versions (other item types, per-event timestamps) are
  not verified. Unknown types become explicit gaps.
- Broker links were exercised with synthetic `broker.*`/`tool.*` events, not through a live scoped bridge.
- Chunk-receipt timing is the persisted `recorded_at` of the chunk journal transaction; it is a supervisor
  measurement, not a client timestamp. For records completed at stream end without a newline, it is the last chunk.
- Argument and result digests are kept as the contract requires; a digest of a short, guessable argument could
  confirm a guess (residual TM17, with the masking of the summary). Secrets committed into project content remain
  the TM17 residual noted by T018.
- The projector runs only with the supervisor; a database used without a supervisor keeps markers pending (retention
  protects them) until a service with the supervisor starts.
- An integrity failure keeps the attempt's streams protected from retention until the owner investigates; there is
  no owner command to re-derive or release it yet.
- Downgrades below 0032 are refused for any database with settled attempts after 0040 (D287's rule, D310).

## 6. Review corrections (2026-11-04)

The first independent technical review passed the 25 original tests, `scripts/check-docs` and `git diff --check`,
and found five defect groups with additional synthetic cases. All are corrected on the same branch; derivation
version 2. Findings, corrections and the regressions in `tests/product/test_observed_steps.py`:

| # | Finding | Correction | Regressions | Result |
|---|---|---|---|---|
| 1 | Malformed nested shapes raised `TypeError` (Claude `content: 1`, `tool_use_id: []`; Codex `status: []`); an unknown Codex item became a call whose `output` text reached `arguments.summary` | Each record is validated against the shape it is read with before any step changes (`claude_valid`, `codex_valid`); invalid → `invalid_record` gap at its position; unknown item types → one `unsupported_event` gap (`item:<type>`); supported Codex tools read explicit fields only; a residual exception still becomes a gap | `test_malformed_claude_shapes_become_gaps_and_later_records_still_derive`, `test_malformed_and_unknown_codex_items_keep_no_fields_and_later_records_still_derive` (sealed; the private text is absent from projection events and artifacts) | Corrected |
| 2 | A later turn's completion made an earlier message final and coverage `complete`; a completed turn followed by an open one was `complete`; end-only items carried a start and a 0 ms duration; broker links matched the first name and digest | A Codex final is bound to the completion of its own turn; coverage is `complete` only when nothing is missing, else `partial` with `coverage_reasons`; end-only steps carry the end with start and duration absent; broker links only when name and digest single out one native call and one broker call | `test_a_codex_final_answer_is_bound_to_the_completion_of_its_own_turn`, `test_an_item_seen_only_at_its_end_records_that_end_without_start_or_duration`, `test_identical_parallel_broker_calls_are_never_cross_linked` | Corrected |
| 3 | A shorter replay over three persisted steps sealed with `steps: 2`; two projectors could leave sealed and failed markers; the T006 thread query paged partial steps | Batches and seal check terminal markers under the writer lock (the first one stands); the seal requires the persisted step keys to equal the derived sequence (`integrity_step_set`); thread event/artifact queries never serve `invocation.step` rows, so cursors stay gap-free | `test_a_shorter_replay_over_more_persisted_steps_is_an_integrity_failure`, `test_two_projectors_never_leave_both_terminal_markers` (identical, divergent, after a failure), `test_thread_trace_queries_never_serve_step_rows_or_skip_later_rows` | Corrected |
| 4 | All steps and payloads built before cutting, large native objects kept, pairwise overlap (0.10 / 0.40 / 1.62 s at 2,000 / 4,000 / 8,000 calls), quadratic broker and range matching; the worker re-selected the 20 oldest failing markers forever | At most 10,000 steps materialized, later ones counted by kind while their calls absorb results; no native arguments kept (the broker digest is the arguments digest); O(n log n) overlap sweep, linear broker grouping and single-pass discovery; ranges read one at a time; recovery is a keyset over marker ids past failures with a stop check before each invocation | `test_overlap_and_derivation_scale_linearly_with_sequential_calls`, `test_steps_past_the_bound_are_counted_not_materialized_and_still_absorb_their_results`, `test_the_worker_reaches_a_healthy_marker_behind_persistent_failures` | Corrected |
| 5 | Oversize ranges were accepted without the sealed capture, and opened without the repository's no-follow walk; `source_record` accepted `stream_diagnostic` rows | Without the capture's path, size and digest every range is `capture_absent`; the file is opened through `backup.opened` (no link in any component, regular, one link, bounded) and read bounded by the capture size; `source_record` only references `agent_event` rows, a diagnostic gap keeps its position and `stream_record` | `test_oversize_ranges_need_the_sealed_capture_and_a_path_without_links` (missing capture, last-component and intermediate links), `test_oversize_ranges_without_sealed_proof_or_behind_a_link_are_unavailable` (through the projector), `check_sources` now requires `agent_event` in every test | Corrected |

Also added: `test_reasons_states_and_coverage_codes_have_english_and_spanish_messages` (catalog parity for reasons,
states and the new `observed_steps.coverage.*` keys). Kept: no backfill, `query_only` reads, the internal read
scope, D287's refusal of downgrades below 0032 with trace rows, retention protection of failed projections (manual
intervention stays outside T019), no HTTP contract change.

Measurements after the corrections (development machine):

| Measurement | Result |
|---|---|
| Overlap sweep alone, sequential calls in one turn: 2,000 / 4,000 / 8,000 | 0.8 / 1.4–1.6 / 3.1–3.2 ms (was 0.10 / 0.40 / 1.62 s) |
| Full derivation (validate, derive, bound, size every payload): 2,000 / 4,000 / 8,000 calls | 0.15 / 0.31 / 0.62–0.65 s (linear) |
| 12,001 derived steps past the bound | at most 10,000 materialized during the feed; results of omitted calls correlated; payload ≤ 4 MiB |
| Step pages over the 5,001-step trace, 208 page reads | p95 1.81–1.87 ms (budget 150 ms) |
| Projection of the 5,001-step trace | 1.49 s, outside the settlement transaction |

## 7. Second review corrections (2026-11-05)

The second independent technical review repeated 61 focused tests and `scripts/check-docs` successfully and found
four defects. All are corrected on the same branch; derivation version 3 (the derived payloads of the affected shapes
change; nothing derived by version 2 was ever integrated or installed). Regressions in
`tests/product/test_observed_steps.py`; every one fails without its correction.

| # | Finding | Correction | Regressions | Result |
|---|---|---|---|---|
| 1 | A real capture of a Claude `assistant` with `message.content: 1` raised `TypeError` in `StreamMetrics.event` after the bytes were written: the batch was not saved, the capture ended interrupted and the journal lacked that chunk's `stream_bytes` and `agent_event`. The §6 regression injected the record after that point | The `metrics-1` counter reads a non-list `content` as no blocks (D305: the projection's evidence must reach the journal); every other record counts as before, and charges and the agent-result validation are unchanged. The read loop also flushes, best effort, the chunk and records already read when an unforeseen failure interrupts the capture, without masking it | `test_a_malformed_claude_record_is_journaled_by_the_live_capture_and_later_records_still_derive` (fake CLI, ordinary settlement, no injected rows: result `complete`, capture `stream_metrics` equal to the sealed re-read, chunks covering the whole `stdout.bin`, records 1–6 journaled, no interrupted capture, `invalid_record` at record 2 and the later turn, call and final message derived); `test_an_unexpected_capture_failure_still_journals_the_chunk_already_written` | Corrected; replaces the §5 deferral |
| 2 | Codex: an in-progress `file_change` with `changes: null` raised in `codex_valid` and left the projection pending; an `agent_message` without `text` before `turn.completed` gave `present: false`, `final: true` and coverage `complete`; an MCP call first seen at `item.updated` got an invented start and duration and lost server, tool and arguments first carried by `item.completed` | Nested shapes are validated with `changes` optional while in progress; the final message of a completed turn without text is not final (`absent` reason `message_text_absent`, coverage `partial` with `final_answer_absent`); fields not carried by a call's first records are taken from the first later record that carries them (never replacing one already observed), so the broker attribution sees them; without `item.started` start and duration stay absent, and the end is recorded only when observed | `test_an_in_progress_file_change_without_changes_derives_and_takes_them_from_its_completion` (fake CLI, sealed, complete), `test_a_codex_final_message_without_text_is_an_explicit_absent_final_answer`, `test_an_mcp_call_first_seen_updating_has_no_start_and_takes_its_fields_from_its_completion` (linked; never completed: nothing invented; observed fields never replaced) | Corrected |
| 3 | With a reduced step bound, two identical native harness calls (one before the cut, one after) and one broker event, `_brokers` linked the visible call because it only examined materialized steps | Calls past the bound keep compact metadata (tool and argument digest only) and are counted per name and digest across the whole invocation; an ambiguous call keeps no link and records `tool.link_absent: ambiguous_broker_calls` plus the `ambiguous_broker_calls` counter and coverage reason; a single call past the bound owns its broker call (neither linked to a visible step nor reported as unlinked) | `test_a_broker_link_needs_a_unique_native_call_across_the_whole_invocation` (duplicate past the bound: no link, reason; different late call: linked; a late call with its own broker event: both owned) | Corrected |
| 4 | The worker checked the stop before each invocation, but `project` could keep starting batches and seal after the service's `join` expired | `project(stop=)` checks the stop before each batch and before the seal; a stopped projection returns `pending` with `stopped: true`, writes nothing more and ends the pass; the marker stays pending, retention keeps the streams and the next start replays the written batches as no-ops and seals once | `test_a_stop_between_batches_leaves_the_projection_pending_and_the_next_start_converges` (worker stopped after the first committed batch; a pass stopped before the seal; a new worker converges to the clean derivation with one seal) | Corrected |

Kept: idempotent sealing and the terminal checks under the writer lock, retention protection while unsealed,
`query_only` reads, no backfill, no HTTP contract, schema, dependency or catalog change.

Checks for this round:

- Focused: `scripts/check tests/product/test_observed_steps.py` (48 passed) and the capture, metrics and observation
  suites with it (`test_observed_steps`, `test_cli_agents`, `test_metrics`, `test_trace_observation`,
  `test_operation_journal`, `test_retention`, `test_usage_accounting`, `test_tool_bridge`,
  `test_p001_qualification`, `test_managed`): 334 passed before the last regression was added.
- Closure (final code): `scripts/check` — unittest 10 ok; `alembic check` ok; pytest **3214 passed, 2 skipped**,
  29 subtests (the one warning is the known wheel duplicate-name notice); `scripts/check-docs` 0 errors;
  `git diff --check` clean, and the untracked files checked the same way.
- Not run: `scripts/check --frontend` (no frontend change); no OpenAPI export or client regeneration (no HTTP
  contract change); no real agent, provider or harness run.

## 8. Independent final re-review — 2026-11-05

The final re-review inspected the actual diff and the four corrections in §7. It found no outstanding relevant
defects. The live capture now preserves malformed Claude evidence through the ordinary settlement path. Codex
records with null in-progress changes derive safely, an absent message stays absent, and calls first seen updating
incorporate later fields while retaining unknown start and duration. Broker attribution counts calls beyond the
step bound, and a stop between batches or before the seal leaves recoverable pending work.

- Independently repeated `scripts/check` over `test_observed_steps.py`, `test_cli_agents.py`, `test_metrics.py`,
  `test_trace_observation.py` and `test_backup.py`: **192 passed**. The prior capture and Codex reproductions also
  passed against the final code.
- Independently repeated `scripts/check-docs`: 123 Markdown files, 0 errors. `git diff --check` passed.
- The implementation's final general check in §7 recorded **3214 passed, 2 skipped**, unittest 10 ok and
  `alembic check` ok. The re-review did not repeat the general suite after the focused checks passed. Subsequent
  edits record review and integration status only.
- No real agents, providers, installed CLI qualification, network installation or harness execution was used.
  The synthetic qualification limits in §5 remain.

The owner authorized source commit, merge into develop and push of develop after successful review in this task's
review session. This authorization covers T019. Release 0.2.0 through protected main, distribution/publication and
installation remain pending. T020 is the next implementation task after integration.
