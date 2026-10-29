# P002-T003 — LangGraph runtime and continuation foundation

Status: **completed (2026-10-29); committed, merged into `develop` and pushed at the owner's authorization.** The owner accepted the
contract refinement, the resolutions in §3 (recorded as
[D282](../DECISIONS.md#d282--harness-checkpoint-saver-and-continuationjournal-consistency-contract) and
[D283](../DECISIONS.md#d283--durable-segments-graph-version-stamping-and-quarantine)), the delivery route and one
networked lock of the D280 set. The runtime exists and is exercised by synthetic graphs only; no product graph, API,
UI or agent path uses it, so operator-visible behavior is unchanged from 0.1.9 apart from the new empty tables.

Owner/delivery: P002-T003, branch `feat/p002-t003-langgraph-runtime` from local `develop` at `591ba78` (T002 merge).
Accepted route: topic → `develop` at the owner's authorization, then part of the **0.2.0** phase release (D253/D242).
T003 has no individual release, publication or installation. Binding design:
[D280](../DECISIONS.md#d280--langgraph-1218-dependency-set-placement-and-runtime-hygiene),
[T002 feasibility §2](P002-T002-feasibility.md#2-langgraph-feasibility-g01-g02-feasibility),
[T001 contracts](P002-T001-contracts.md) §3 (INV-01, INV-02, INV-05, INV-06) and §10, gates G02/G03,
threats TM12/TM20, basis B02, B12–B13, B18.

## 1. Scope

In scope:

- Add `langgraph==1.2.18` with exactly the D280 lock delta (27 additions, no pin change), the offline `pylock.toml`
  route unchanged and `NOTICE-THIRD-PARTY.md` regenerated.
- One orchestration package, `my_harness.orchestration`, the only importer of `langgraph`/`langsmith`; the core never
  imports it; only the supervisor-owned runtime composition imports the package. Import-boundary test.
- A harness checkpoint saver over Alembic-managed tables (D280 option B), a graph registry with identity/version
  stamping, a segment runner with per-segment limits, explicit cancellation/revocation and quarantine.
- An operation-port interface for deterministic operation identities, with a **synthetic** journal used only by
  tests; the production operation journal is T006.

Out of scope (owning task): production operations/invocations/events (T006), any real graph that launches agents,
touches Git or exports (T014–T016), API/UI for runs, waits or the inbox (T016–T017), owner re-authorization of a
quarantined continuation (T016/T020), installed-data migration qualification (T020). No OpenAPI change is expected;
if one becomes necessary it is surfaced first.

## 2. Components

| Component | Responsibility |
|---|---|
| `orchestration/hygiene.py` | Remove inherited `LANGSMITH_*`/`LANGCHAIN_*` variables before import; run every graph call inside `langsmith.tracing_context(enabled=False)` |
| `orchestration/saver.py` | `HarnessCheckpointSaver(BaseCheckpointSaver)`, synchronous, strict serializer (`allowed_msgpack_modules=None`), SQLAlchemy over the harness engine; async variants raise |
| `orchestration/registry.py` | Graph definitions keyed by `graph_id` + declared `graph_version` + structural fingerprint (sorted nodes/edges/interrupt points) |
| `orchestration/runner.py` | `start`, `resume`, `recover`, `cancel`, `revoke`, `status`; stamps and checks versions; runs segments with `durability="sync"`; `wait_for` typed waits |
| `orchestration/operations.py` | `OperationPort` protocol, `run_operation` and deterministic `operation_key(config, name, references)` |
| `storage/graph_continuations.py`, migration `0029_graph_continuations` | Thread stamps and compare-and-set transitions; tables, `require_schema`, backup and query-only parity |
| `services/managed_runtime.py` | `ManagedRuntime.graph_runner(registry)`: supervisor ownership, imports LangGraph on first use only |

Graph state holds only primitives, identities and revision references (D269); the saver rejects other values.

## 3. Resolutions (accepted as D282/D283)

**G02 — continuation persistence (D282).** Option B from D280. Three tables in the harness database:
`graph_threads` (thread id, graph id, stamped version and fingerprint, status, segment count, reason, timestamps),
`graph_checkpoints` (thread, namespace, checkpoint id, parent, serialized checkpoint and metadata, type) and
`graph_checkpoint_writes` (pending writes per task/index). Consistency contract: the domain journal is the authority
and the checkpoint is routing progress only; no atomicity between them is assumed; a node performs effects only
through `OperationPort` with a deterministic operation key whose intent is journaled before the effect, so a node
replayed from its start (resume or crash) reconciles the same operation and creates no second effect (INV-02,
INV-05); a checkpoint behind the journal replays, never the reverse. Uncertain operations are reported, never
re-issued (INV-06). Checkpoints are never edited or rewritten; deletion only by explicit thread removal.

**G03 — limits and version drift (D283).** A *durable segment* is one runner call from a start/resume
until the graph waits, ends or reaches the segment limit. LangGraph's `recursion_limit` bounds each segment
(default 50 supersteps, configurable per graph definition); reaching it ends the segment at the last synchronous
checkpoint and the runner continues with a new segment, so total length is bounded only by domain bounds (T016),
never by graph recursion. Before every continue/resume the runner compares the thread's stamped `graph_id`,
`graph_version` and fingerprint with the registered definition; any difference, or an unknown graph, sets the thread
`QUARANTINED` with the observed/expected values and runs no node. Releasing a quarantine is a later explicit owner
action (T016/T020); T003 provides no automatic migration of continuations.

**Thread statuses.** `RUNNING` (a segment is active), `WAITING` (interrupt pending; no process, lease or transaction
held), `COMPLETED`, `CANCELLED`, `REVOKED`, `QUARANTINED`, `RECOVERY_REQUIRED` (a sealed operation without outcome;
added during implementation, matching the contracts' stop vocabulary), `FAILED`. Cancel/revoke is recorded before the next segment;
a waiting thread is cancelled without running any node; an active segment observes it at the next node boundary.

## 4. Evidence required

Deterministic synthetic tests (no network, no CLI, no real provider):

- Saver contract: put/get/list/writes round-trip, parent chains, strict serializer refuses non-primitive state.
- Interrupt/resume with typed payload; resumed node re-entry from its start performs the synthetic effect once.
- Crash between effect and checkpoint (subprocess `os._exit`): restart replays the node; journaled effect once.
- Version mismatch, fingerprint mismatch and unknown graph quarantine before any node runs.
- A graph longer than the segment limit completes across segments; the limit never caps total length.
- Cancel/revoke of waiting and running threads; query-only (restored) database refuses runner writes.
- Hygiene: inherited tracing variables removed; outbound sockets blocked during graph runs.
- Import boundary: only `my_harness.orchestration` imports `langgraph`/`langsmith`; `core` imports neither.
- Migration `0029` upgrade/downgrade, `alembic check`, DDBB-DIAGRAM parity, `scripts/check`, `scripts/check-docs`,
  and distribution checks for the larger lock.

Threats: TM12 (replay duplicates effects) and TM20 (graph-version drift) controlled by the cases above.

## 5. Implementation notes

- **Segment limit probe.** With `recursion_limit=5`, a 23-pass loop raised `GraphRecursionError` three times and
  completed in four segments from `invoke(None)`, confirming that the limit is per segment (scratch probe, then the
  `test_segment_limit_never_caps_the_length_of_a_run` case).
- **Operation key inputs.** `langgraph_step`, `langgraph_node` and `langgraph_path` are identical before and after a
  resume of the interrupted node (scratch probe), and the step distinguishes loop iterations.
- **Concurrent saver writes.** LangGraph calls `put` and `put_writes` from its background executor; a SQLite
  read-then-write transaction whose WAL snapshot another connection advanced fails immediately with
  `database is locked`. The saver serializes its own writes with a lock (found by the first test run).
- **Catalogue coverage.** `orchestration/` joined the layers of the service-text catalogue test; operator-visible
  refusals use `tr()` (11 `orchestration.*` keys, en/es). Persisted `reason` values are codes.

## 6. Verification and delivery

**Delivery status.** Source complete on `feat/p002-t003-langgraph-runtime`; committed, merged into `develop` and
`develop` pushed at the owner's authorization (2026-10-29); Git history records the identities. Part of 0.2.0
(D253/D242). No release,
publication or installation applies to T003.

### Evidence

- **Dependency.** One networked `uv add langgraph==1.2.18` into `.local/uv-cache` (owner-authorized). Lock delta
  compared with the previous `uv.lock`: exactly the 27 D280 additions, no existing package changed or removed.
- **Focused tests.** `tests/product/test_orchestration.py` (18 cases, synthetic graphs from
  `orchestration_probe.py`, stdlib journal, outbound sockets blocked): wait/resume re-entry with one effect (TM12);
  crash after outcome replays and reconciles, crash before outcome stops `RECOVERY_REQUIRED` without reissue (TM12,
  subprocess `os._exit`); version, fingerprint and unknown-graph quarantine before any node (TM20); 23-pass run across
  segments with 23 distinct operations; cancel/revoke of waiting threads and of an active segment; primitive-only state;
  saver round trip, parent chain, `before`/`limit`, immutable checkpoints and unstamped-thread refusal; operation-key
  distinctness; backup → restore keeps the rows and refuses runner writes; tracing variables scrubbed (also before the
  first LangGraph import) and no outbound connection; import boundary; downgrade refused with rows and clean
  downgrade/upgrade without them; supervisor runtime ownership.
- **Suites.** See the closure note in [NEXT_STEPS](../NEXT_STEPS.md#p002-t003--langgraph-runtime-and-continuation-foundation).
- **Distribution.** Offline `build_distribution.py --offline` into the session scratchpad and
  `check_distribution.py --cache-dir .local/uv-cache` passed (49 `pylock.toml` entries, isolated wheel checks).
  Without `--cache-dir` the check looks in the global uv cache and fails offline; that is an invocation detail, not a
  product change.
- **Not performed.** No real agent, provider, CLI or harness run; no network beyond the authorized lock; no OpenAPI or
  client change (none needed); no frontend change; no installed-database migration; no release, publication or installation.
- **Additional fix.** The pre-existing `test_valuation` failure (path moved by `112a31a`) was fixed at the owner's
  request; see the closure note in NEXT_STEPS.
