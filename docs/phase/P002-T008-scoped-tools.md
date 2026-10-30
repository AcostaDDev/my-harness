# P002-T008 — Scoped tool bridge and lazy discovery

## 1. Minimum contract and delivery

Owner: P002-T008, explicitly authorized for local implementation and verification on 2026-10-30.
Branch: `feat/p002-t008-scoped-tools` from clean `develop` `3ad54b5` (also local `origin/develop`, no fetch).
T002/T005/T006/T007 are integrated; one-off queue is empty. Schema baseline: `0033_frozen_context`, 79 tables.

Agreed route (D235/D242/D253): **verified source → integration in develop → release 0.2.0 through protected main
→ distribution/publication → installation**. Only topic creation, implementation and local synthetic checks are
authorized here. No commit, merge, push, publication, product installation, service start, real provider/agent,
network installation or harness execution on this repository. Operator installation remains 0.1.9.

Implement D275/D281 and the T008 part of G04: one invocation-bound MCP stdio broker with exactly `search_tools`,
`describe_tool`, `invoke_tool`. Discovery is bounded and scoped by persisted project, role, operation and frozen
tool policy. Description loads exact schemas on demand. Every logical invocation goes through
`DomainOperations.execute`, including its current authority, revision, closed arguments, digest and idempotency
checks. Session identity comes only from trusted launch infrastructure and is reverified against persisted
invocation/attempt/operation/context/policy. No model argument selects authority.

Claude/Codex injection and independent guards must preserve existing role restrictions; admission requires explicit
MC1–MC7 evidence per client/version/role, distinguishing simulated tests from native qualification. The supervisor
owns bridge identification/termination even across process groups; EOF, parent loss and cancellation stop it.
Discovery/schema/call/result events and tool-result knowledge receipts use existing transactional stores and
envelopes. No new inference or accounting ledger is created. Unknown telemetry stays unknown.

T010's production permission provider remains absent and denies by default; positive and revocation paths use
synthetic permission fixtures only. T009 judge configuration, grant lifecycle, product graphs, UI, automatic project
migration and an OpenCode adapter are excluded. Preserve frozen history, historical launches and archive reads.
No new dependency is planned. Schema/HTTP parity applies only if those contracts change.

## 2. Implemented boundary

- `core/engine/tool_bridge.py`: closed `scoped-tools-1` selection, broker surface digest, three static MCP schemas,
  exact qualification cells, bounded descriptors and canonical serialization measurement. Trusted `policy(...)`
  assembles the selection before `agent_started`; `selection(...)` validates it again in that fenced transaction.
  Historical snapshots/catalogues are unchanged. Only explicit canonical requests opt in.
- `services/tool_bridge.py`: `InvocationResolver`, `Broker`, `BridgeFactory`. The resolver reconstructs the caller
  from persisted native attempt/ledger/operation/context rows; every field is reverified, including project/root,
  revision, actual role, operation key, exact tool refs, client/version, live job/owner token/lease and checkout lock.
  Model arguments cannot choose any of these. `ManagedRuntime.domain_operations()` now supplies this resolver;
  `tool_bridges()` supplies a separate tool-result composition with the production unavailable permission provider.
- `adapters/tool_bridge_transport.py` owns a private per-invocation Unix endpoint (directory 0700, socket 0600);
  `adapters/tool_bridge_stdio.py` is the packaged MCP executable. The stdio process relays to the existing service
  instance in its supervisor and never opens a database or supplies caller authority. No new dependency or grant
  store. This is cooperative same-user containment (D064), not OS isolation.
  Review corrections require isolated Python `-I -m` import resolution and a persisted protocol/surface readiness
  round trip; a connected process alone does not establish availability ([§7](#7-technical-review-corrections)).
- `CLIProcessAdapter.bind_tool_bridges(...)` explicitly binds the factory. Per-invocation launch injects only the
  harness server. The independent guard checks the executable/module/environment/socket shape as well as exact
  configuration, allowlists and approval. Claude keeps strict MCP config, restricted read tools and typed results;
  Codex keeps its file/network sandbox, fresh sessions, disabled memory and typed output. Historical requests retain
  the empty Claude MCP and previous Codex path. Product graphs are not changed.

See the implemented [flow](../flows/tool-bridge.md), D289 and the current domain/context/journal flows.

## 3. Scope, validation, persistence and recovery

Search matches literal casefolded ID/summary, sorted by ID/version, default 20/max 50 descriptors; each summary is
at most 240 characters. Cursor binds the exact query/limit/scoped refs and invocation. Only frozen scoped entries
are searchable/describable, including exact versions and digests; discovery never authorizes execution. Descriptor
and schema results have a 128 KiB canonical serialized ceiling. Knowledge results retain T007's 64 KiB ceiling;
input frames are bounded to 2 MiB plus 8192 bytes of envelope overhead. MCP initialization supports the three
explicit protocol revisions `2024-11-05`, `2025-03-26`, `2025-06-18`; unknown/duplicate initialization and malformed
requests are refused. The T002-observed pre-initialize `server/discover` receives method-not-found.

Every selected logical operation goes through `DomainOperations.execute` with its unchanged catalogue entry,
closed arguments, exact schema digest, frozen revision/project ownership, effective current authority and stable
key. No SQL, arbitrary code, full-catalogue, other model/provider or API path exists. T008 also closes the mutation
replay authority gap: an existing command outcome is returned only after re-evaluating its original capability
targets against current permissions. Query replay already had that check. Positive grants and revocation exist
only in test fixtures; no old permission ledger becomes domain authority.

`broker.called/result` and `tool.called/result` distinguish the broker boundary from the logical operation under
the existing invocation operation. Mutation events retain their domain command ID, and domain command audit events
link to the invocation. `tool.discovered` uses the unchanged `tool-discovery-1` search/describe envelope; the scoped
catalogue digest is the digest of disclosed refs, not a leak of unrelated catalogue entries. Exact descriptor/schema
bytes are stored as response evidence with `knowledge-delivery-2` receipts on `tool_result`, independent of native
knowledge content receipts. Queries retain exact entity exposures and response receipts through T007's sink.

Discovery keys deduplicate within `broker:`; read keys within `tool_result:`. Same key/changed payload conflicts.
Mutations commit their effect/outcome in the existing domain transaction and then commit a stable response receipt
before return. A crash between these commits re-enters execute, rechecks authority and never repeats the effect;
the mutation response receipt has its own hashed-key namespace. Query response/receipts and discovery response/
envelope/receipts commit together. An event/receipt failure returns no unrecorded content. This does not make the
transport acknowledgement atomic. Receipts show availability at the service boundary, never model comprehension.
Each actual broker retry can create a call event without another receipt, effect, inference or usage invocation.

The relay registers PID, parent and process group, then persists `bridge.ready` (protocol and exact surface digest)
before acknowledging MCP initialization. Its identity/readiness are retained in the existing managed process spec
and correlated trace; normal EOF, supervisor disconnect and parent loss terminate it even while a call
is pending. Cancellation/CLI exit closes the independent connection, including for a detached process group; the
supervisor records observed stopped liveness, and recovery also refuses potentially live recorded bridge identities.
No persisted PID is signalled. A deterministic domain transaction in flight may settle after disconnection; its
outcome is reconciled. Missing native inference outcome becomes UNCERTAIN, never an automatic rerun or success
deduced from exit 0. Existing ledger accounting and absent model/usage telemetry are preserved.

## 4. Evidence and qualification limits

`tests/product/test_tool_bridge.py` uses the real domain/context/journal/SQLite/stdio/adapter implementations,
temporary synthetic projects, `tool_bridge_client.py` and the existing test-only permission tables. No provider,
authentication, network, operator state or product graph is used.

| Automated evidence | Contract / threats |
|---|---|
| Both Claude/Codex, simulated reviewer/executor, search → describe → invoke through the actual stdio executable; exact domain knowledge and receipts; normal exit, intentionally detached orphan, auth/quota errors without fallback | MC1–MC7 exercised with fake clients, TM11/TM16; one existing usage invocation, unknown telemetry retained |
| Scoped deterministic pagination, exact refs/digests, unknown versions, stale schema, forged caller/authority fields, generic-invoke SQL/code/owner-only bypasses, malformed values and duplicate JSON keys | TM01–TM04; no disclosure outside scope |
| Mutation/read replay, changed payload, grant revocation/current-ceiling change, cross-project missing-equivalence, later adoption with frozen old revision | TM01/TM03/TM04; no repeated effect or receipt |
| Receipt failure rolls back return/exposure; schema replay deduplicates; deterministic race with a concurrent process-journal writer | FL08; no returned unrecorded knowledge or SQLite WAL snapshot upgrade |
| Cancellation mid-call with client exit 0 and detached relay; EOF, supervisor loss and actual launcher-parent loss during calls; no native result reconciles to UNCERTAIN | FL13, MC7; no automatic inference retry |
| Each missing MC1–MC7 item, unknown client/version/role, poisoned launch command/module/environment, extra server/tool, wrong server-local approval and changed frozen surface rejected | TM02/TM11/TM16; no broadening of the independent guard |
| Direct third synthetic JSON-RPC client completes all three broker operations | Portable protocol only; no OpenCode adapter or qualification |
| Backup/restore retains exact tool receipts/traces without checkout; archive reads emit no writes and broker execution is refused | Read-only consultation and existing backup verification |

Product admission retains only T002's exact historical native readonly `reviewer` cells (Claude Code 2.1.312,
Codex 0.165.0, evidence `P002-T002-stdio-readonly`). Their source is the T002 transport characterization, not a new
native run of this code. Current T008 evidence is **simulated**, using separately labelled cells; it is not inherited
by the production factory. No native executor, judge, other role alias, later version or third client is qualified.
Unsupported/missing capability cells block; the historical adapter minimum version alone cannot admit the bridge.
T009 owns judge setup; broader authorized native qualification and audit remain T021, with performance aggregation
in T019. Usage/provider/requested/reported model identities remain in their existing accounting contracts.

**G04:** D281 already selected transport and MC1–MC7. T008's implementation is available locally with the synthetic
evidence above; no feasibility choice remains open. Technical review/integration and native qualification of this
implementation remain distinct pending work. The accepted T001/T002 historical gate records are not rewritten.

## 5. Reproducible context-loading measurements

Run offline: `.venv/bin/python scripts/measure_tool_context.py`. Exact output:
[`P002-T008-context-measurements.json`](P002-T008-context-measurements.json).
Counts are canonical JSON **UTF-8 bytes**, never measured native tokens. Synthetic entries have deterministic IDs,
bounded query/limit fields, repeated descriptive text, output schema, roles and capabilities; five schemas are loaded.
The product sample loads lookup/search (two schemas).

| Catalogue | Initial broker surface | Selected descriptors | Loaded schema documents | Describe responses including digests | Full catalogue documents |
|---|---:|---:|---:|---:|---:|
| Synthetic 40 | 1,331 | 1,811 | 6,501 | 6,916 | 52,001 |
| Synthetic 200 | 1,331 | 1,811 | 6,501 | 6,916 | 260,001 |
| Synthetic 1,000 | 1,331 | 1,811 | 6,501 | 6,916 | 1,300,001 |
| Product 12 / select 2 | 1,331 | 401 | 1,878 | 2,044 | 10,077 |

A single search → describe → invoke journey is **3 logical request/response exchanges**, plus initialize/tools-list
(2 setup exchanges) in the fixture. Loading all five selected synthetic schemas then invoking one needs 7 logical
exchanges; the two-schema product sample needs 4. Notifications have no response. The fragments exclude JSON-RPC/
content wrappers, transport escaping, prompt history, tools' returned knowledge and CLI overhead. Full catalogue
documents exclude the added digest fields, which are shown separately for description responses. These synthetic
sizes show only what was serialized; they imply no provider context budget, native token savings, model quality,
latency or billing result. Native ToolSearch is not enabled as an optimization here.
The review correction adds an internal supervisor readiness round trip during initialization; it does not add a
client MCP exchange or alter the measured public schemas/fragments.

## 6. Verification and delivery

Focused baseline: domain, CLI, frozen context, operation journal and T008 suites, **179 passed** serially.
The first general check ran unittest (10), Alembic (no new operations), then pytest: 2538 passed, 5 failed,
2 skipped, 1 existing duplicate-zip warning and 29 subtests. The failures exposed a real WAL read-snapshot upgrade
race in new trace transactions and uncatalogued protocol diagnostics. Correction: acquire the existing write lock
before reading event/context chains, including mutation response receipts; catalogue all own protocol messages.
The deterministic concurrent-writer regression covers that boundary. Post-correction parallel focused checks:
107 passed; final bridge/text checks with the additional reviewer/executor matrix and regressions: **46 passed**.

Diff review additionally tightened the independent guard against a poisoned expected command/module/environment,
requires the owned private socket shape, and freezes/verifies the broker surface digest. No unrelated fixes.
General closure check after the trace/message corrections: `scripts/check` — unittest **10 ran OK**;
Alembic **no new upgrade operations**; pytest **2553 passed, 2 skipped, 29 subtests passed** (259.7 s).
Two warnings: the existing duplicate zip-member fixture and a concurrent refusal-journal snapshot upgrade in
`test_domain_operations.py`. The latter was corrected by taking the same write lock before refusal project/audit
reads. This final incremental correction and two added stdio refusal cases were checked with **195 passed** across
T008/domain/journal/CLI/context/text suites (parallel, 19.2 s, no warnings), then the concurrent-adoption test with
`PytestUnhandledThreadExceptionWarning` treated as an error: **1 passed, 38 deselected**. The whole suite was not
repeated after that focused correction. General evidence is retained in `.local/check/p002-t008-general-pytest.log`.

`scripts/check-docs`: **97 Markdown files, 0 errors**; `git diff --check` clean; complete tracked/new source and
documentation diff reviewed locally. `measure_tool_context.py` reproduced the task evidence JSON bytes exactly.

Offline build and isolated wheel verification both passed on the final source through
`scripts/build_distribution.py --offline` and `scripts/check_distribution.py`:
`.local/p002-t008-reviewed-dist/`, logs `.local/p002-t008-reviewed-build.log` and
`.local/p002-t008-reviewed-distribution-check.log`. Exact wheel/sdist membership, metadata, licences and checksums
are verified by the existing machinery. The added installed-wheel check starts the packaged stdio module outside
the checkout, with no PYTHONPATH or Node, and exercises initialize/list and all three broker relays against a
synthetic supervisor. The remaining existing installed journeys also passed. These are disposable test environments,
not installation of this branch for the operator. The distribution retains the existing package version 0.1.9;
it is a local verification artifact, not a new release. The ordinary packaging build ran tsc/Vite; Node frontend
tests were not requested/run (no frontend source change). No real CLI/provider probe or product graph was run.

No database model/migration change: schema remains `0033_frozen_context`, 79 tables. Existing stores, backup readers
and exported HTTP/client contracts are unchanged; applicable parity is flows, current architecture/specification,
English/Spanish messages and source/packaged executable checks. ONE_OFF_TASKS remains empty.

Delivery: **local source, no commit**, pending technical review. Integration in develop, 0.2.0 release through
protected main, distribution/publication and operator installation remain pending and separately authorized.
Operator installation is still 0.1.9. T009/T010 and later product graphs/UI/import/export/migration are not absorbed.

## 7. Technical review corrections

Owner-authorized local corrections on the same uncommitted branch `feat/p002-t008-scoped-tools`, base `3ad54b5`.
The three review reproductions were read from `/private/tmp/t008_review_probes.py`; maintained regression tests
now live in the repository and do not depend on that temporary file. Delivery remains verified source → develop
→ release 0.2.0 → distribution/publication → installation, each pending and separately authorized.

The review reported 210 focused passes and one cancellation failure, plus three reproductions of the findings
below; it did not repeat the full suite or packaging. Those are reviewer-reported results, not newly executed
baseline tests. Earlier local verification above is retained as history; the corrections below supersede its
readiness claim for the current source. Production permission denial, native qualification limits and all
historical paths remain unchanged.

### 7.1 Findings and corrections

| Finding | Correction | Maintained evidence |
|---|---|---|
| P1: `python -m` imported a project-owned `my_harness` package from the MCP launch cwd, executing code outside the reviewer scope | Constructor and independent guard require the supervisor's Python executable with `-I -m my_harness.adapters.tool_bridge_stdio`. Isolated mode excludes cwd, inherited Python import variables and user-site paths; module resolution uses the trusted installed interpreter environment. Removing `-I` is refused independently. | `test_relay_imports_are_isolated_from_checkout_and_inherited_python_environment`: both simulated clients, shadow package/module/stdlib and inherited PYTHONPATH/PYTHONHOME/PYTHONSTARTUP. A sentinel outside the checkout is never written, while the complete domain journey succeeds. `check_installed_bridge` now runs the installed wheel from a hostile synthetic checkout with all those import traps and poisoned Python variables, and also requires successful protocol/tool relays and sentinel absence. |
| P1: a client could omit MCP and still return a valid typed answer, accepted as `complete` without bridge identity | The relay's successful initialize performs a control round trip with the exact protocol and broker surface digest. `bridge.ready` is committed to the existing process spec and trace before acknowledgement; the adapter requires that availability evidence for completion. Missing connection, failed child startup or registration without initialization yields a persisted `failed` result with `bridge_unavailable` and no accepted answer. Native launch/telemetry is retained; it is not labelled a before-GO refusal or no inference. Cleanup alone cannot assert completion. | `test_bridge_availability_is_required_but_logical_calls_are_optional`: both clients omit the bridge, observe a failed child, register without initialize, or initialize/list without any broker/logical calls. Only the last can complete; all have one usage invocation, the failed paths are persisted and never `not_invoked`. `test_closing_without_availability_cannot_establish_completion` checks the default close contract. Historical non-scoped CLI tests remain in the affected suite. |
| P2: relay EOF followed by service settlement made `sendall` raise BrokenPipeError before supervisor close, replacing cancellation with a transport RuntimeError | Peer EOF/reset/closed socket is handled specifically at socket read/write boundaries. `bridge.disconnected` records the reason and lost response, then ordinary PID stop evidence remains required. Service/receipt/journal errors propagate even after cancellation starts; their exception type is never enough to suppress them. The supervisor's cancellation classification and uncertain-inference reconciliation are preserved. | `test_peer_eof_then_service_settlement_then_supervisor_close_is_an_expected_disconnect` enforces call entered → peer EOF/exit → released service → thread settled → supervisor close using Events and joins. It checks the lost-response event, settled service receipt and UNCERTAIN inference, without a probabilistic loop. Existing detached-relay cancellation/exit-0 tests are retained. `test_cancellation_does_not_suppress_a_real_receipt_failure` injects RuntimeError and BrokenPipeError from the receipt sink while stopped: both remain real failures and no knowledge receipt is committed. |

The synthetic environment-inheritance fixture poisons variables at the MCP launch boundary, leaving unrelated
trusted supervisor/gate startup outside that probe. Python isolation is not a claim of OS confinement or protection
against modification of the installed harness/interpreter/site-packages by the same user. Readiness proves the
relay prepared the supported protocol and exact broker surface, not ingestion, understanding or a required logical
call by the model. Logical call count may be zero. A domain transaction already in flight can commit after EOF;
its service-boundary receipt is not a transport acknowledgement. No inference is relaunched automatically. If a
native failed result is persisted, its operation settles from that native failure; without a native outcome the
existing journal reconciles UNCERTAIN. No extra ledger, grant store, schema/migration, dependency or HTTP change.

### 7.2 Correction verification and delivery

First new regression subset: **21 passed, 42 deselected**. Affected bridge/CLI/context/domain/journal/trace/text
suites: **236 passed** (parallel, 19.8 s). After strengthening the registration-only fixture and adding a real
service-side BrokenPipeError case: **11 passed, 55 deselected**. No native providers/agents or product graphs.
Closure, once on the corrected source: `scripts/check` — unittest **10 ran OK**; Alembic **no new upgrade
operations**; pytest **2577 passed, 2 skipped, 29 subtests passed**, one existing duplicate-zip-member warning
(239.0 s). No cancellation failure or unhandled thread exception. General output is retained in
`.local/check/p002-t008-review-corrections-general-pytest.log`.

Offline packaging and isolated installed-wheel verification both passed using the existing build/check scripts.
Artifacts: `.local/p002-t008-review-corrections-dist/`; logs:
`.local/p002-t008-review-corrections-build.log` and `.local/p002-t008-review-corrections-distribution-check.log`.
The installed module initialized, listed and relayed all three broker operations from the hostile synthetic
checkout with inherited poisoned Python variables; no attack sentinel was created outside it. Exact package
members, metadata, licences, SHA256SUMS and the existing synthetic installed journeys also passed. These are
disposable verification environments, not operator installation or release publication; package version remains
0.1.9. The offline build ran tsc/Vite; no frontend source changed and Node frontend tests were not separately run.

`scripts/check-docs`: **97 Markdown files, 0 errors**. `git diff --check` and whitespace checks on all new files:
clean. Complete current diff reviewed locally, retaining the original uncommitted T008 work. No new dependency,
model/migration or HTTP contract; flows, current specification/architecture, D289 and English/Spanish messages
are in parity. No real CLI/provider qualification, installed operator change, commit, merge, push or publication.

Source is corrected locally on the same branch, still uncommitted and pending a new technical review/integration.
G04's implementation remains local; native qualification is not expanded and all delivery stages above remain
pending. The one-off queue is still empty.

## 8. Authorized source delivery

After the correction checks above, the owner explicitly authorized committing T008, merging it into `develop`
and pushing `develop`. This authorization does not assert a separate technical re-review or extend native
qualification. The integration record accompanies the merge. Release 0.2.0 through protected `main`,
distribution/publication and operator installation remain pending and are not authorized by this source delivery.
