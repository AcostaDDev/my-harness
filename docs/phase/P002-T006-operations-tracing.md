# P002-T006 — Operations, invocations and correlated events

Status: **completed (2026-10-29), with the review findings corrected ([§9](#9-review-findings-and-corrections));
committed, merged into `develop` and pushed at the owner's authorization.** G05 was
accepted in T002 (D281) and this task implements its records. G08 was resolved during the task: the recommended
contract of [§3](#3-g08-contract-accepted-as-d287) was recorded as proposed and the owner accepted it as
[D287](../DECISIONS.md#d287--operation-journal-granularity-and-recovery-contract). §4 was done before the acceptance
on accepted contracts only; §5 implements D287.

Owner/delivery: P002-T006 on `feat/p002-t006-operations-tracing`, created from local `develop` at `59b9c80` (T005
merge, equal to the local `origin/develop` ref; no fetch; clean tree). Route (D242/D253): verified source on the topic
branch → integration into `develop` → **0.2.0** phase release through protected `main` → verified
distribution/publication → local installation. Every stage after the source needs its own authorization; T006 has no
individual release. The operator installation stays 0.1.9 and its database is not migrated; development schema
moves from `0031_domain_commands` (73 tables) to `0032_operation_journal` (75 tables at first delivery, 76 after
the review corrections).

Binding design: [T001 contracts](P002-T001-contracts.md) §3 (INV-01, INV-02, INV-05, INV-06, INV-09), §11–12; flows
[FL08](P002-T001-flows.md#fl08--context-assembly-and-knowledge-receipts),
[FL09](P002-T001-flows.md#fl09--portable-tool-discovery-and-invocation),
[FL13](P002-T001-flows.md#fl13--crash-recovery-across-graph-and-domain-operations),
[FL14](P002-T001-flows.md#fl14--observation-projection); threats TM12, TM14, TM15, TM17
([threat model](P002-T001-threat-model.md)); [T002 §4–7](P002-T002-feasibility.md#4-observation-coverage-g05) and
D281; D282–D283; [T005 §7, §11](P002-T005-domain-operations.md#7-transaction-and-audit) and D286; D254, D259, D269,
D277; basis B05, B10–B13, B19–B23.

## 1. Scope

In scope: the operation journal behind `OperationPort`; ordered, deduplicated events with rebuildable projections;
expected-invocation linkage to the existing ledger; effect intents, owner fencing and conservative recovery; counters
with declared meaning and source; bounded envelopes for T007 knowledge-delivery and T008 discovery events (no
receipts or transport); bounded, project-isolated trace queries that also run on a restored query-only copy.

Out of scope (owner task): context assembly and receipts (T007), broker transport, bridge reaping and MCP (T008),
judge (T009), grants (T010), UI, inbox and graph views (T017–T018), autonomy (T016), task-stage refactoring (T014),
aggregation across the new hierarchy (T019), installed conversion and integrated recovery (T020), integrated audit
(T021). Agent calls and delegated adoption stay refused (D286); no permissive provisional provider is added.

## 2. Baseline observed in the code

| Concept | Existing record | Identity, lifecycle and recovery today |
|---|---|---|
| Request | `managed_jobs.idempotency_key`/`request_json`, `domain_commands`, `phase_authorizations` | Per source; no shared request identity |
| Project task | `knowledge_items` (kind `task`, T004); legacy `managed_runs.task_id`/`phase_id` strings | Accepted revisions (D284) |
| Workflow run | `graph_threads` (T003) | Stamp, CAS status, `RECOVERY_REQUIRED` on an uncertain operation |
| Engine run | `managed_runs` (`history_json`, `revisions`, `revision_limit`, `purpose`) | Frozen task contract; append-only history |
| Scheduling | `managed_jobs` (FIFO, `owner_token`, lease, `checkout_locks`) | Only queue and writer exclusion; `recover_expired` → `RECOVERY_REQUIRED`, `confirm_stopped` explicit |
| Attempt | `managed_attempts` (number per run, one launch, `result_json`) | Intent before launch (`agent_started`); `INTERRUPTED` only after confirm-stopped |
| Process | `managed_processes` (spec, identity, `PENDING`/`RUNNING`/`STOPPED`/`UNCERTAIN`, capture) | `process_intent` before spawn; D252 closing owner settles |
| Invocation (ledger) | `usage_invocations` keyed `<source_kind>:<source_id>` (`managed_attempt`, `preparation_step`, `configuration_assistance`) | Intent with the native source; capture/valuation append-only; `operation_id` → `configuration_operations` |
| Other effect intents | `managed_commits` (`INTENT`/`COMMITTED`), `phase_operations`, `project_preparation_*`, `configuration_operations` | Their own journals |
| Run events | `managed_events` (per run, `sequence`), `phase_events`, preparation/creation events | Ordered per owner record |
| Domain outcome | `domain_commands` (T005) | Committed or absent; refusals in their own transaction |
| Graph effects | `OperationPort` (`seal`/`complete`), `run_operation`, `operation_key`; synthetic journal in tests only | D282 contract; no production journal |

The adapter already classifies cancellation from the supervisor's own flag (`status_override = "cancelled"` before
`stop_group`), not from the exit status; `metrics-1` keeps its historical counters (Codex "turns" derived from
completed items), which T006 does not rewrite.

## 3. G08 contract (accepted as D287)

Proposed as D287 and accepted by the owner on 2026-10-29 without changes; names are reversible details, the
acceptance concerns the granularity and recovery contract.

### 3.1 Correspondence

| Concept | Representation | New? |
|---|---|---|
| Request | Reference to the originating record, `(origin_kind, origin_id)`: owner command, job submission, phase authorization; later autonomous authorization (T016) and inbox action (T017) | No table |
| Project task | Knowledge item at an accepted revision, carried as a reference | Existing |
| Workflow run | `graph_threads` row | Existing |
| **Operation** | `workflow_operations`: one row per `OperationPort` key inside one thread; the recoverable unit | **New** |
| Invocation | The existing `usage_invocations` row: the only record of a model call and the only source of charges | Existing |
| Attempt | The existing native source (`managed_attempts`; preparation step, assistance operation); one launch, never retried | Existing |
| Job | `managed_jobs`: queue, lease and fencing token; the only scheduler | Existing |
| Turn, tool call, delivery, discovery | Events and normalized observations inside an invocation; never rows for unobserved activity | Events |

Operations exist only under a graph thread. 0.1.9 engine runs keep their own journals and are not given synthetic
operations or a backfill; T014 moves task stages onto threads and thereby onto operations.

### 3.2 Units with identity and recovery

Only the operation gains a new identity and lifecycle. The attempt/process journal already provides intent before
launch, fencing and confirm-stopped; it is reused, not duplicated. Turns, tool calls, receipts and discovery are
events without their own recovery (B12).

Operation: `id`, `thread_id`, `key` (unique per thread), project scope (knowledge project and/or root), `kind`
(`domain_command`, `agent_invocation`; `git_commit`, `git_tag`, `export`, `notification` registered by their owning
tasks), `parent_operation_id`, `causation_event_id`, origin reference, bounded references (task, phase, revision,
input digests), `request_sha256` over kind and references, status, writer (`job_id`, `owner_token`) for agent
invocations, result links (`command_id`, `invocation_id`, `attempt_id`), bounded `result` (≤16 KiB) or `error`
(`code`, reference), timestamps.

| Status | Meaning | Reached from |
|---|---|---|
| `INTENDED` | Sealed and committed before the effect | Seal |
| `COMPLETED` | Effect outcome recorded with its result link | `INTENDED`, `UNCERTAIN` (reconciled) |
| `FAILED` | Recorded known failure (CLI failed, cancelled, timeout, interrupted result); terminal | `INTENDED`, `UNCERTAIN` (reconciled) |
| `UNCERTAIN` | Recovery found no native outcome and the evidence cannot settle it | `INTENDED` |
| `ABANDONED` | Explicit owner decision with reason; no effect is claimed and nothing is reissued | `UNCERTAIN` |

Domain-command operations are inserted directly as `COMPLETED` in the command's transaction (committed or absent);
a refused command creates no operation, only a refusal event in the refusal transaction. A new try after `FAILED`
or `ABANDONED` needs a new key, i.e. a new explicit decision or bound-consuming attempt (FL13).

### 3.3 Port, outcomes, writer and ledger

- `seal(key, kind, references)`: a different kind or `request_sha256` under the same key is a conflict;
  `COMPLETED`/`FAILED` return the stored outcome (the node reconciles); `INTENDED`/`UNCERTAIN` raise
  `OperationUncertain` and the thread stops `RECOVERY_REQUIRED` (D282 unchanged).
- T005 outcomes: the existing `audit_sinks` hook writes the operation and its event in the command's session;
  `domain_command` keeps the node's key as idempotency key.
- Writer: an `agent_invocation` is sealed inside the fenced `agent_started` write (owned job, token, live lease,
  checkout lock), together with the attempt row and the ledger intent, before `process_intent` and launch. Completion
  happens only in the fenced `_history` write that stores the attempt result; a stale owner fails `_owned` and changes
  nothing.
- Ledger: `workflow_operations.invocation_id` references `usage_invocations.id`; the ledger is written only by the
  existing `intend`/`settle`; operations hold no usage counters. `usage_invocations.operation_id` keeps its meaning.

### 3.4 Transactions, re-entry and uncertainty

| Boundary | Transaction |
|---|---|
| Seal | Committed before the effect; for agent invocations the same transaction as attempt row, ledger intent and event |
| Outcome | The native outcome's transaction (command row, attempt result, later commit/tag/export results) plus the event |
| Refusal | T005's separate refusal transaction plus the refusal event |
| Recovery | One classification transaction per operation |

Recovery classifies non-terminal operations by evidence, not by status: a native outcome present → `COMPLETED` or
`FAILED`; otherwise `UNCERTAIN`. An expired lease only moves the job to `RECOVERY_REQUIRED` (existing); it never
completes an operation or proves a stopped writer. After the owner's existing confirm-stopped writes the
`INTERRUPTED` attempt result, the operation reconciles to `FAILED` (`interrupted_outcome_unknown`). Uncertain
inference is never relaunched automatically. Every transition is compare-and-set and writes its event in the same
transaction; the status column is a projection rebuildable from the events.

### 3.5 Events and queries

`trace_events`: global autoincrement order, `event_id`, unique `dedupe_key` (an identical replay is a no-op, a
different payload under the same key is a conflict), project scope, `thread_id`, `operation_id`, `invocation_id`,
`parent_event_id`, `causation_id`, `kind`, `source` (supplied, reported, derived, measured, absent), bounded sanitized
payload (§4) and artifact references. Trace queries require a project scope, return at most 200 events per page with
a cursor, read nothing outside the scope, and run without checkout, registry or providers on a query-only restore.
Backup and query-only restore include both tables. Schema change: `0032_operation_journal` (75 tables); read-only
owner API for a thread's trace with OpenAPI and generated client parity.

### 3.6 Owner request

One request: accept D287 as above (operations only under graph threads, invocation = ledger row, attempt = existing
native source, no backfill of 0.1.9 runs, five statuses with owner-only `ABANDONED`, two new tables). **Answered
2026-10-29: accepted**; the implementation continued without another plan approval.

## 4. Independent work (accepted contracts only)

Pure core modules, no schema, no storage, no product composition change:

| Module | Contract | Content |
|---|---|---|
| `core/engine/observation.py` | G05/D281, D277, INV-09, D254 | `trace-observation-1`: normalized signals of one settled invocation from sealed evidence; distinct counters with meaning, source and coverage; cancellation classified from the supervisor record only |
| `core/engine/trace_payload.py` | TM15, TM17, D024, B10 | Bounded, sanitized event payloads; sensitive keys lose their values and secret-like substrings are masked, without digests; large content becomes digest references |
| `core/engine/trace_envelopes.py` | §11, FL08, FL09, D275 | `knowledge-delivery-1` and `tool-discovery-1` envelopes that T007/T008 will emit; validation only |

Counters (`trace-observation-1`):

| Counter | Meaning | Source |
|---|---|---|
| `harness_attempt` | Position of the attempt in its run (`managed_attempts.number`) | supplied |
| `revision_round` | Executor rounds of the run up to this attempt | derived |
| `native_turns` | Turns the client reports (Claude `num_turns`); Codex `turn.completed` events of a complete stream | reported / measured; else absent |
| `tool_calls` | Tool uses observed in the stream, by name, once per id | measured; absent without stream metrics |
| `permission_denials` | Denials the client reports | reported; absent for Codex (no event) |
| `usage` | Whether terminal usage exists; never summed with per-message views | reported / absent |
| `reported_model` | Models the client reports | reported; absent for Codex |

## 5. Implementation of D287

§5 and §6 record the first delivery for review. The review found six defects, corrected in
[§9](#9-review-findings-and-corrections), which takes precedence where they differ (generic completion, result
storage, root checks, artifact retention, `refs`/`origin` bounds, Codex turns).

| Area | Implementation |
|---|---|
| Schema | `0032_operation_journal`: `workflow_operations` (unique thread/key, checks for writer and command links, unique attempt), `trace_events` (global id order, unique `event_id`/`dedupe_key`, three insert-only triggers; digest now over 27 triggers); downgrade refused while rows exist |
| Journal | `storage/operation_journal.py`: `record_event` (sanitized, deduplicated), `record_envelope` (validated T007/T008 envelopes), compare-and-set `transition` with its event, `seal`/`complete` for `JournalPort`, `recover`, `abandon`, bounded `thread`/`operations`/`events` and `projection` |
| Port | `orchestration/operations.py`: `JournalPort(journal, thread, root)`; `run_operation` returns COMPLETED, FAILED and ABANDONED records without performing the effect; INTENDED/UNCERTAIN still raise `OperationUncertain` (D282) |
| Domain commands | `command_sink` composed in `ManagedRuntime.domain_operations()`; `DomainOperations` now calls its audit sinks in the separate refusal transaction too. Accepted: `domain.command_accepted` event, or for a graph caller the `domain_command` operation (COMPLETED) with its event; refused: `domain.command_refused` |
| Invocations | `agent_started(..., operation=InvocationOperation)` seals in the fenced transaction after the attempt row and the ledger intent; `_history` and `confirm_stopped` call `settle_attempt` after `settle_usage`, which writes `invocation.observed` (`trace-observation-1`) and COMPLETED or FAILED. No caller in the product supplies an operation yet (T014) |
| API | `api/traces.py`: `GET /api/managed/knowledge/projects/{k}/traces/{thread}`, `/operations`, `/events`; 404 `trace_unknown` for foreign or missing threads; exported OpenAPI and `frontend/src/api.generated.ts` regenerated (additions only: three paths, five schemas) |
| Texts | 10 `journal.*` keys in English and Spanish |

Choices within the contract: the thread's project is fixed by its first operation's root (a later operation with
another root is refused), and the API addresses traces by the persisted knowledge project, so a root without a
knowledge project has no API trace yet; payload strings over 1 KiB and payloads over 8 KiB are replaced by digest
references whose bytes are not retained (large content keeps living in its existing evidence store); recovery leaves
an `agent_invocation` untouched while its job holds a live lease and a `sealed_effect` untouched while its thread is
`RUNNING` without confirmation; `CallerResolver` stays unavailable in the product, since no agent caller exists until
T008 binds broker sessions to these invocation identities.

**Fix in a T003 component.** The first closure run failed once
(`test_a_resumed_node_reconciles_its_completed_operation_without_a_second_effect`: thread `FAILED` instead of
`COMPLETED`, not reproduced in 30 isolated or concurrent reruns). Cause found by inspection and confirmed by a scratch
stress (200–400 concurrent writes): `HarnessCheckpointSaver.put`/`put_writes` were read-then-write transactions
serialized only among themselves, so a journal commit from the node thread advanced their snapshot and 376 of 400
checkpoint writes failed with `database is locked`. The saver now takes the database write lock first (as the managed
repository does); the stress then had 0 failures and
`test_checkpoint_writes_wait_for_concurrent_journal_writes` covers it. D282's contract is unchanged.

## 6. Evidence

Synthetic only: temporary SQLite migrated to head, synthetic graphs and knowledge, fake CLIs
(`cli_process_probe.py`, new `term_exit0` mode with the shape T002 characterized for Codex) through the real adapter
and supervisor journal. No installed agent, provider, network, harness run on this repository or operator data.

| Risk | Test (`tests/product/…`) | Threat |
|---|---|---|
| Order and deduplication; immutability; sanitizing | `test_operation_journal.py::test_events_are_ordered_deduplicated_immutable_and_sanitized` | TM14, TM17 |
| Joint rollback of outcome and event; refusal in its own transaction | `::test_command_outcomes_and_refusals_carry_their_events_in_their_own_transactions`, `::test_joint_rollback_leaves_no_attempt_ledger_or_operation` | TM12, TM14 |
| Re-entry after an outcome | `::test_a_resumed_node_reconciles_its_completed_operation_without_a_second_effect`; second seal of an invocation key refused | TM12 |
| Crash without outcome (child process `os._exit` after the seal); never reissued; owner abandon | `::test_a_crash_after_the_seal_stops_the_thread_and_is_never_reissued` | TM12 |
| Stale writer and expired lease; confirm-stopped reconciliation | `::test_expired_lease_and_stale_writer_leave_the_invocation_uncertain_until_confirmed_stopped` | TM12 |
| Cancellation with exit 0 (supervisor) vs external SIGTERM with exit 0 | `test_trace_observation.py::test_supervisor_cancellation_with_exit_zero_…`, `::test_external_termination_with_exit_zero_…`, `test_operation_journal.py::test_a_supervisor_cancellation_with_exit_zero_settles_as_failed_cancelled` | TM12, TM14 |
| Missing signals (Codex model, denials, usage after cancel; closing-owner interruption) | `test_trace_observation.py` (7 observation cases) | TM14 |
| Double accounting | `::test_an_invocation_is_sealed_with_its_attempt_and_ledger_and_settles_once`: one ledger row, one capture, no amounts in the trace, `metrics-1` unchanged | TM14 |
| Bounded queries and project separation | `::test_trace_queries_are_bounded_and_isolated_by_project` (260 events, 200 cap, cursor; foreign root refused) | TM15, TM17 |
| Restored archive: API reads equal, no writes, no checkout or provider | `::test_restored_archives_serve_traces_without_writes_or_checkout` | TM15, TM17 |
| Payload bounds and secret patterns; envelopes | `test_trace_observation.py` (payload and envelope cases), `::test_envelopes_are_validated_before_they_become_events` | TM15, TM17 |
| Concurrent checkpoint and journal writes | `::test_checkpoint_writes_wait_for_concurrent_journal_writes` | TM12 |

- **Focused runs.** `scripts/check` over the new files: 19 (`test_trace_observation.py`, three runs before G08) and
  30 with the journal tests (four runs), all passed; related suites (domain operations, orchestration, knowledge API,
  managed, accounting, storage API, configuration, core, catalogue, backup, CLI agents) passed after the expected
  updates: schema head in `test_storage_api`/`test_usage_accounting`, table count 76 in `test_configuration`.
- **Closure.** First `scripts/check --frontend`: one failure (above). After the saver fix, `scripts/check --frontend`:
  unittest 10 ran ok; `alembic check` no new operations; pytest 2467 passed, 2 skipped, 1 pre-existing warning
  (duplicate zip member `my_harness/web/index.html`); node 248 passed; build (tsc + vite) ok. `scripts/check-docs`: 93
  documents, 0 errors (the two new documents also explicitly, 0 errors); `git diff --check` clean and no trailing
  whitespace in untracked files.
- **Mermaid.** All 69 Mermaid blocks of the repository's Markdown (66 before, three new) pass `mermaid.parse` with the
  installed mermaid 11.17.2 under Node (DOM and DOMPurify stubbed); layout and browser rendering not exercised.
- **Parity.** DDBB-DIAGRAM (head, 75 tables, new section, trigger count), flows
  [operation journal](../flows/operation-journal.md) (new), [domain operations](../flows/domain-operations.md),
  [graph continuation](../flows/graph-continuation.md), [accounting](../flows/metrics-accounting.md); exported
  OpenAPI and `frontend/src/api.generated.ts` regenerated with the repository commands (additions only); 10
  `journal.*` keys en/es; SPECIFICATION §14, ARCHITECTURE §§1, 3, 7, 13; ROADMAP, STATE, NEXT_STEPS; D287.
- **Not performed or not qualified.** No real CLI, provider, broker, bridge reaping or MCP; no product graph launches
  agents; no UI; no installed-database migration (operator stays 0.1.9); no real-size history beyond 260 synthetic
  events; Linux and other platforms not run. The sanitizer recognizes common secret shapes only (TM17 residual:
  project content can still contain secrets the owner committed).

## 7. Boundaries with later tasks

| Task | Uses from T006 | Not done here |
|---|---|---|
| T007 | `record_envelope('knowledge.delivered', …)`, invocation identities | Context assembly, receipts sink, D094 replacement |
| T008 | `record_envelope('tool.discovered', …)`, invocation and operation identities for caller binding | Broker transport, bridge reaping (Codex orphan), `CallerResolver` |
| T013–T016 | `JournalPort`, new kinds with their reconcilers (Git, export, notification) | Those effects and their sealed intents |
| T014 | `InvocationOperation` on `agent_started` from task-stage graphs | Moving task stages onto graphs |
| T016, T017 | `abandon` as the owner action behind a guarded command; trace events as inbox sources | Owner UI/API for recovery, inbox |
| T018, T019 | Trace queries, `trace-observation-1` counters, ledger links | Views, aggregation across the hierarchy |
| T020 | Recovery classification and archive parity | Installed conversion and the integrated fault matrix |

## 8. Verification and delivery

**Delivery status.** Source complete on `feat/p002-t006-operations-tracing` from `develop` `59b9c80`, including the
review corrections of §9. After the follow-up correction the owner authorized commit, merge into `develop` (D235) and
push of `develop` (2026-10-29); Git history records the identities. Pending, each with its own authorization: the
0.2.0 phase release through `main`, distribution/publication and local installation (D242/D253). No individual
release applies to T006. The one-off queue stays empty.

## 9. Review findings and corrections

The owner's review of the first delivery (2026-10-29) reproduced six defects with synthetic data while the 88 focused
tests of that delivery still passed. All six are corrected on the same branch without changing the D287 contract.
Each regression below reproduces the reviewed case and asserts the corrected behavior; they were not rerun against
the first delivery's code, which exists only as the earlier state of this uncommitted tree.

| # | Defect | Correction | Regression (`tests/product/…`) |
|---|---|---|---|
| 1 | `OperationJournal.complete` finished any INTENDED operation, so an invocation with an expired lease, no attempt result and a `pending` ledger row could become COMPLETED | The generic port seals and completes only `GENERIC_KINDS` (`sealed_effect`); invocations and commands settle from their fenced native outcome or by evidence-based reconciliation (`journal.kind_not_generic`) | `test_operation_journal.py::test_generic_completion_cannot_fabricate_an_invocation_success`: `complete`, `JournalPort.complete`, a forged `agent_invocation`/`domain_command` seal and `run_operation` are refused; the operation, attempt and ledger stay unchanged; recovery still says UNCERTAIN |
| 2 | `_bounded()` applied the event sanitizer to results and replaced a whole 2013-byte result with `omitted/sha256` when any string exceeded 1 KiB | Results and errors are stored verbatim when they are JSON objects within 16 KiB and 16 levels; credential keys, secret-looking values, non-JSON values and larger results are refused before writing, leaving the operation INTENDED instead of completing with a digest | `::test_results_within_the_contract_are_kept_for_the_replay`: a 2013-byte result with a 1680-character string is stored, returned by the first run and by the replay (effect once); 16000 characters kept; 17000, secret and NaN refused |
| 3 | `seal()` returned an existing operation without checking its root; `complete()` took no root | `_scoped` checks the root before any read, reconciliation or change; `complete` and `JournalPort.complete` take the port's root | `::test_another_root_cannot_replay_read_reconcile_or_complete`: another root cannot replay, read a completed result, complete, or reconcile a settled invocation; the legitimate replay is unchanged |
| 4 | `record_event()` kept the references but discarded the offloaded bytes; a valid 50-descriptor discovery envelope (~14 KB) became an unrecoverable reference | New insert-only `trace_artifacts` (event, digest, size, media, masked content) written with the event; at most 1 MiB per event (refused, not truncated); a supplied reference-shaped value without stored bytes is refused; digest and size verified on read and by backup verification, which also requires every payload reference to have its row; `OperationJournal.artifact` and `GET …/traces/{thread}/artifacts/{sha256}` read it within the project | `::test_offloaded_event_content_is_stored_verified_and_survives_restart_and_restore`: the envelope is rebuilt exactly from the stored bytes, after a new engine and from a restored backup; another root cannot read it; triggers refuse update/delete; forged and over-1-MiB events refused. `::test_restored_archives_serve_traces_without_writes_or_checkout` reads a masked artifact through the API, identically on the archive |
| 5 | `refs` and `origin` were stored unbounded (36 KB reference, `api_key` in `origin`) | `validated_refs` (≤ 32 lowercase keys, printable string values ≤ 200 characters, no credential names or secret-looking values, never coerced) and `validated_origin` (exactly `{kind, id}` with a known kind) run before any write and when an `InvocationOperation` is created | `::test_refs_and_origin_are_bounded_and_refused_before_any_write`: oversize, credential, secret, non-string, malformed and too-many refs and five bad origins are refused with no operation or event written; the 32×200 limit is kept unchanged |
| 6 | Codex `native_turns` depended on the `completed` termination, so a real `turn.completed` with an invalid answer gave `null`/`no_terminal` | `StreamMetrics` gains an additive `terminals` count by native terminal type; `trace-observation-1` counts Codex turns from `turn.completed`/`turn.failed`, independent of payload validity and termination; captures without the counter keep the earlier conservative rule | `test_trace_observation.py::test_a_codex_turn_is_observed_from_its_terminal_whatever_the_payload_validity` through `AgentStream`: invalid answer → one measured turn, `invalid_stream` termination, terminal usage; `turn.failed` → one turn; a cut stream → `no_terminal`; `metrics-1` turns unchanged |

Changes for parity: migration `0032_operation_journal` gains `trace_artifacts` and three triggers (76 tables, trigger
digest over 30; still unreleased, so the uncommitted migration was amended rather than followed by another); DDBB
diagram, [operation journal flow](../flows/operation-journal.md), ARCHITECTURE §7, the D287 implementation note,
exported OpenAPI and regenerated client (additions only: one path, one schema), 7 new keys (`journal.*`,
`backup.trace_artifact`) in English and Spanish. Existing tests changed only where the contract now refuses their
input: the synthetic invocation origin became `{kind: managed_job, id}`, and the archive test moved its secret from a
result (now refused) to an offloaded event (masked and stored); the table count became 77.

**Evidence.** Focused: `scripts/check tests/product/test_operation_journal.py` 17 passed;
`tests/product/test_trace_observation.py` 20 passed; affected suites (journal, observation, orchestration, domain
operations, knowledge API, metrics, accounting and accounting views, backup, CLI agents, managed, storage API,
configuration, catalogue, core, installed migration) 390 passed. Closure, once: `scripts/check --frontend` — unittest
10 ran ok; `alembic check` no new operations; pytest 2473 passed, 2 skipped, 1 pre-existing warning (duplicate zip
member); node 248 passed; build (tsc + vite) ok. `scripts/check-docs`: 93 documents, 0 errors (the record and
the flow also explicitly); `git diff --check` clean, no trailing whitespace in untracked files; the 69 Mermaid blocks
of the repository parse with the installed mermaid 11.17.2 (DOM stubbed).

**Follow-up review finding (P2).** `record_event()` checked only the references of the stored payload; when the
whole payload went to one `application/json` artifact, the references inside it were not checked, so a forged
reference inside a payload over 8 KiB was accepted and passed backup/restore without its bytes. Correction:
`trace_payload.contained_references` yields the payload's references and, recursively, those inside the event's JSON
artifacts (an unparseable JSON artifact fails); `record_event` refuses any of them without stored bytes, and backup
verification applies the same check per event. Regression:
`test_operation_journal.py::test_references_inside_an_offloaded_payload_are_checked_on_write_and_in_backups` — a
12-key payload of about 11 KiB with a nested forged reference is refused and writes nothing; a legitimate payload
with an offloaded 2.4 KB string inside an offloaded payload is accepted, both artifacts are read back and the backup
verifies; a forged event and artifact inserted around the journal make `create_backup` fail on that reference.
Focused: the journal, observation, backup, orchestration and domain-operation suites, 139 passed. Closure, once:
`scripts/check --frontend` — unittest 10 ran ok; `alembic check` no new operations; pytest 2474 passed, 2 skipped,
1 pre-existing warning; node 248 passed; build ok. `scripts/check-docs` 0 errors; `git diff --check` clean.

**Limits.** The sanitizer and the result/reference checks recognize common secret shapes only; a secret in an
unknown format can still reach a result or a reference (TM17 residual). Artifact content is text (UTF-8) only;
binary evidence keeps its existing stores. `recover` and `abandon` remain owner-level calls addressed by thread or
operation id without a root parameter; their API and guarded commands are T016/T017. No real CLI, provider or
product graph was used.
