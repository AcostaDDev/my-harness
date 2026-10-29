# P002-T007 — Frozen context and knowledge-access receipts

Owner: P002-T007, authorized locally by the owner on 2026-10-29. Branch:
`feat/p002-t007-frozen-context`, from clean `develop` at `c0ffc85` (also local
`origin/develop`; no fetch). One-off queue empty. No pre-existing changes.

## 1. Minimum contract and delivery

Implement D270/D277/D285 and FL08 on the T004–T006 foundations: bounded deterministic
context from an accepted revision, canonical instructions and explicit profile/code
evidence; an immutable invocation boundary; bounded knowledge lookup/search; exact
exposure receipts committed before query results are returned. Preparation and launch
intent do not claim observed delivery. Receipt means availability, never comprehension;
unobserved native reads remain unknown. No generated-file fallback on the new path.
Historical prompts and existing project paths retain D094 until explicitly migrated.

Delivery route (D235/D242/D253): checked source → integration into `develop` →
release 0.2.0 through protected `main` → distribution/publication → installation.
Local implementation and verification were authorized first. Following successful re-review, the owner authorized
commit, merge into `develop` and push of `develop` (§9). Integration, release, distribution/publication and installation
remain pending. Operator installation
remains 0.1.9. No real providers, service startup or harness execution on this repository.

References: [T001 contracts §§3/5/11](P002-T001-contracts.md),
[FL08](P002-T001-flows.md#fl08--context-assembly-and-knowledge-receipts),
[threats TM01/TM14/TM15](P002-T001-threat-model.md),
[T004](P002-T004-knowledge.md), [T005](P002-T005-domain-operations.md),
[T006](P002-T006-operations-tracing.md). G07 is resolved by accepted D285.

## 2. Implemented interfaces

| Surface | Implementation and contract |
|---|---|
| Pure context | `core/engine/frozen_context.py`: deterministic explicit selection, accepted instruction preorder/targets, canonical-vs-capture attribution, independent source/exposure hashes, Unicode range exposures |
| Preparation and readers | `ManagedRuntime.frozen_contexts()` → `ContextRepository.prepare_for` (captures the actual frozen profile), `prepare`, `snapshot`, `render`, `invocation`, `deliveries`. Reads use persisted knowledge-project IDs; no registry, checkout or supervisor is needed |
| Prompt integration | `render_attempt(..., canonical=...)` receives a verified selection through the repository. Mandatory instructions enter the real template slot; templates without one (including definition) receive them outside the template. The captured profile must match the frozen project context; its executor instructions replace `PROFILE_INSTRUCTIONS` where present; other frozen sources enter a sealed context tail |
| Native invocation boundary | Existing `SQLiteManagedRepository.agent_started(request, InvocationOperation)` recognizes the canonical marker and seals the snapshot with the fenced native attempt, accounting invocation and operation. Actual prompt bytes/hash, snapshot/root and source inclusion are checked before commit |
| Initial observation | The existing CLI adapter first checks the frozen instruction target against the actual client, then reports completed stdin write/close with transport and rendered digests; the fenced managed repository persists initial receipts. This additive canonical-path observation changes no tool transport, discovery, CLI flags, historical prompt template or adapter version |
| Shared-domain reads | New additive `knowledge.lookup@1` and `knowledge.search@1`; historical entries/digests and HTTP contracts stay unchanged. All use `DomainOperations.execute`, its closed schema, caller/tool policy, current capabilities, project checks and frozen revision rule |
| Query/tool receipt sink | Product `ReceiptSink` is wired in `ManagedRuntime.domain_operations`. `ReceiptSink(channel='tool_result')` is also available to a trusted later consumer. Caller resolver and permissions still fail closed; test doubles remain only in tests |
| Stored evidence | `context_snapshots` (prepared bytes); `invocation_contexts` (immutable boundary); `knowledge_deliveries` (exact response/exposures and receipts). `knowledge-delivery-2` events through `record_envelope('knowledge.receipt', …)`; v1 unchanged |
| Backup/restore | Backup verifies source assembly, hashes, boundary links, stored exposure/receipt digests and correspondence with journal events. The archive service interface reads identical evidence and exact saved prompt without checkout or writes |

The original T005 `delivery.items` pairs continue to describe **source content hashes**, for historical API
compatibility. They are never copied into receipt delivery digests. The sink hashes each actual metadata/excerpt/full
exposure and the exact result wrapper. A delivery record's SHA-256 covers its serialized payload **and** receipt
array. Events contain digest/locator metadata, never prompt or source text; the existing trace sanitizer is unchanged.

## 3. Determinism, authority and bounds

- One accepted revision per prepared snapshot, verified through T004's hash chain on service reads. Initial
  instructions are mandatory active sections, in root/child preorder, `agents` first and then `claude`/`gemini` for
  that selected client; Codex receives `agents`. Individual retired sections stay historical. No inferred policy,
  wrapper import or generated-file fallback is introduced.
- Explicit relevance selection uses at most 50 stable IDs (sorted, deduplicated by refusal); instruction sections
  are automatically included and cannot be bypassed through that list. Context has at most 100 sources and
  256 KiB of canonical UTF-8 JSON. Oversize mandatory context fails without truncation. The canonical rendered
  prompt has a 1 MiB ceiling; old rendering is unchanged. Profile and at most 48 code captures require short stable
  identity/version, provenance and matching bytes/hash. Rendering and attempt sealing verify the actual frozen profile; credential-shaped identifiers are refused before rendering.
  Captures are trusted consumer inputs, not an automatic filesystem/Git crawler or permission source.
- Lookup addresses a stable entity (a section is itself an entity). Metadata is canonical JSON of bounded identity,
  version, source hash, title/status; titles have a 200-character preview and explicit `title_truncated`. Excerpt/full
  data is canonical JSON of that member's content. Ranges use **Unicode code points**, end exclusive; digests use
  exact delivered **UTF-8 bytes**. Lookup accepts `start`, `length` 1–32768 (default 2048 for excerpt), `max_bytes`
  1024–32768 (default 8192) and exposure metadata/excerpt/full. A bounded full request becomes an excerpt with an
  explicit range and truncation marker. Consecutive ranges reconstruct the canonical content exactly.
- Search is literal casefolded matching over codes and canonical content within the verified accepted revision.
  Query length 1–200, page limit 1–50 (default 20), byte budget 1024–32768 (default 8192), optional kind/document
  filter and the same exposures. Stable order is kind/document/code. Cursor is position plus a digest of the exact
  arguments (excluding cursor) and revision ID; changed arguments, another project/revision or malformed cursor
  fail without existence diagnostics. No cross-revision/global index is used. Scanning the verified revision is
  linear; there is no FTS dependency or claim of indexed large-dataset performance.
- Every new lookup/search response has a hard 64 KiB serialized ceiling, including JSON escaping and metadata;
  source byte budgets are ceilings rather than guaranteed fill. Bounds/page continuation and individual exposure
  truncation are returned and receipted. Legacy agent reads above 64 KiB fail `delivery_over_limit` and direct the
  consumer to bounded reads. Legacy owner HTTP result shapes remain unchanged.
- `deliveries` uses offset pagination with a 1–100 page limit (default 50), each record already bounded at write.
  `snapshot` and `invocation` expose the complete bounded prepared context and exact saved prompt. These are trusted
  service interfaces for later UI/trace consumers, not new HTTP routes or frontend work.

## 4. FL08 atomicity and recovery

1. Preparation commits source bytes only. Selection errors emit a bounded `context.preparation_failed` event with
   a code, not selected text. No invocation or receipt is manufactured.
2. Fenced attempt start commits native attempt + ledger intent + invocation operation + context boundary and
   `context.intended` together. Failure rolls them all back. The prepared snapshot may remain: it proves selection.
3. The adapter observes completed input write/close. A successful fenced write then records exact initial exposures
   and receipt events atomically. A known refusal before GO records `launch_refused` with no delivery digest. A crash
   before launch has only intent. A partial input or lost observation remains unknown. A receipt-write failure stops
   or fails the adapter result; it cannot report successful observed delivery. No inference is retried.
4. Agent queries take the T005 write lock, reverify caller/boundary and current capabilities, read the frozen revision,
   then commit exact response/exposures/receipts/events before returning. Failure at receipt/event/commit returns no
   content. Owner/harness reads continue to work without writes in archives.
5. Stable keys (1–180 characters) deduplicate within invocation/channel. Identical replay returns stored response
   bytes without another receipt and still rechecks current capabilities. A changed request conflicts. Recorded
   post-validation read failures reserve the key and replay that failure. Input/schema/caller/capability refusals
   remain in the ordinary domain refusal audit. A new key denotes another actual service return. This transaction
   is not atomic with transport acknowledgement, graph checkpoints or model ingestion.

Later adoption never changes the invocation's snapshot, search hits/counts, cursors, metadata or refusals. Another
explicit preparation and native invocation/attempt form the new boundary. A later adoption of that invocation's
own draft also cannot bypass freezing through `draft.get`; an open proposal is receipted as a noncanonical capture.
Receipts prove availability at the recorded service/pipe boundary, not comprehension. Unobserved native file reads
remain unknown. A missing observation is never backfilled from a successful model answer.

## 5. D094 transition and compatibility

D285 already resolved G07; no further authority approval was requested. T007 implements its replacement through
the **explicit canonical-context marker** and real prompt/attempt/adapter integration described above. This path
does not read `AGENTS.md`, `CLAUDE.md` or `GEMINI.md`, even when canonical instructions are missing. Existing projects
are not automatically converted and product graph migration is not advanced. Calls without the canonical selection
keep the exact historical renderer, including the D094 checkout rules and historical no-layout behavior. Prompt
templates/catalogues, previous snapshots, accepted knowledge, receipts and historical evidence were not rewritten.
T013 still owns generated files and T011/T014–T016/T020 their explicit adoption/migration paths.

## 6. Synthetic evidence

`tests/product/test_frozen_context.py` exercises real implementations with temporary SQLite/Git and synthetic
knowledge. The caller/permission providers are test-only doubles; the fake CLI is the existing process probe.

| Evidence | Threats/guard |
|---|---|
| Equal source bytes/hash under reordered explicit selection; instruction tree/targets; profile/code provenance and Git blob identity; exact prompt rendering and braces kept as data | TM01, TM14; canonical vs capture authority |
| D094 v2 checkout read remains unchanged; canonical path works without checkout instructions; missing canonical instructions refuses a generated fallback; definition templates get accepted instructions | TM01; D285 replacement and historical compatibility |
| Invocation N remains N after owner adoption N+1; lookup/search/head/list/get and identical missing/later revision refusals; new native attempt explicitly receives N+1 | TM01, TM14; no later IDs/hashes/counts/content |
| Own proposal reads are noncanonical; subsequent adoption cannot leak later accepted metadata through draft lookup | TM01; frozen-domain read surface |
| 1,200 synthetic matches, page uniqueness/completion, changed-query cursors, foreign/missing entities, large Unicode sections and exact consecutive-range reconstruction; heavily escaped content and serialized ceilings | TM15; bounded result/count/range semantics |
| Real fake-CLI complete input observation, reentry deduplication, separate query/tool channel, receipt digests differ from full-source hashes, no context text in events | TM14; availability only |
| Query/event persistence failure rolls back response and receipts; retry once with same identity; fenced seal failure rolls back attempt/ledger/boundary; reopened prelaunch crash has no delivered receipt or new inference | FL08, TM14; no false delivery or duplicate effect |
| Known prelaunch refusal has failure envelopes without delivered digest; initial receipt persistence failure makes fake-CLI invocation unsuccessful | FL08; observed vs intended delivery |
| Actual frozen profile and instruction/client target checked before launch; missing instructions, retired rules and escaped-result budgets | TM01, TM15; no silent substitution |
| Receipt sink independently checks invocation/attempt/revision/thread/role linkage even with a trusting test resolver | TM01; caller binding defense |
| Insert-only update/delete/REPLACE guards, backup tamper verification; exact snapshot/prompt/query/exposure evidence on a restored marked query-only copy after removing checkout, only SELECT/PRAGMA reads | FL08, archive extension; no recreated execution authority |

## 7. Checks and delivery status

Focused checks begun from the repository root, offline:

- First focused run: 121 passed, 4 failed; inspected `.local/check/pytest.log`. Failures were test expectations:
  legacy no-layout instructions, reinjected permission snapshot in a new test attempt, product refusal precedence
  now that a real receipt sink exists, and prefix counting including the three new delivery triggers. Corrected
  those fixtures/assertions without changing historical contracts.
- Expanded knowledge/prompt/domain/journal/backup set: **177 passed**.
- Expanded affected set including CLI, observation, configuration, storage API, accounting and installed migration:
  **372 passed**. Additional boundary/integrity cases were then added during diff review.
- Follow-up boundary/domain/CLI/observation/backup set: **180 passed**. Final focused T007 suite after the commit
  rollback guard and profile-identity refinement: **25 passed** (`scripts/check tests/product/test_frozen_context.py -- -n 0`).
- Closure, once: `scripts/check` — unittest **10 ran OK**; Alembic **no new upgrade operations**; pytest
  **2471 passed, 2 skipped, 2 failed, 26 setup errors, 29 subtests passed**. Both failures require `/bin/ps`; all
  26 setup errors are temporary loopback socket binding refused by the execution environment. The full log is
  preserved in `.local/check/p002-t007-general-pytest.log`. One known duplicate-ZIP warning and one concurrent
  SQLite refusal-audit lock warning occurred; the latter is rechecked explicitly with thread warnings as errors.
  No source assertion failed in the general run. Only the affected synthetic cases are rerun with the needed
  local process/socket permissions, not the complete general suite.
- `scripts/check-docs` over all tracked Markdown plus both new documents: **97 files, 0 errors**, after preserving
  historical section anchors for updated current-status headings. `git diff --check` and whitespace checks of all
  six untracked files are clean.
- Affected-case disposition: after inspecting the general log and confirming the launcher fixture uses only a
  temporary synthetic interpreter (never the real service), reran exactly the two blocked diagnostics cases,
  `test_start_command.py` and the concurrent-adoption test with local socket/process permissions:
  `scripts/check 'tests/product/test_cli_diagnostics.py::test_bounded_failures_no_retry[child-timeout-version]'
  'tests/product/test_cli_diagnostics.py::test_bounded_failures_no_retry[child-timeout-help]'
  tests/product/test_start_command.py
  tests/product/test_domain_operations.py::test_concurrent_adoptions_applies_and_keys_have_one_winner
  -- -n 0 -W error::pytest.PytestUnhandledThreadExceptionWarning` — **30 passed**, no warning.
  No product change was needed for the environment refusals or the parallel-load SQLite warning; the complete
  general suite was not repeated. Its two skips remain skips; the intentional duplicate-ZIP warning remains.
- Reviewed the final tracked diff and all six new files; source, schema, messages, flows and delivery/status
  documentation agree. General checks ran once, no frontend/build rerun because no HTTP/client/frontend contract
  changed. The product code did not change after that general check; only the evidence/current-status docs did.

Source is locally implemented; technical review is pending. No commit, merge, push, release, publication, network
installation, installed migration, service startup, provider run or harness execution on this repository was done.
No new dependency, HTTP/OpenAPI/generated-client/frontend contract, product graph, broker/CallerResolver, judge,
permission store, project onboarding/conversion, generated exporter/importer, UI/view or aggregation was added.
Real-provider and installed-conversion evidence remains outside this task; the default product resolver and
permissions still refuse agent access. One-off queue remains empty. The outstanding agreed 0.2.0 delivery route is
retained in STATE/NEXT_STEPS and §1 above, with source/review/integration/release/distribution/installation separate.

## 8. Technical review corrections

The owner authorized these three local corrections within T007. The branch is still
`feat/p002-t007-frozen-context` at `c0ffc85`; the existing uncommitted implementation and six new files were
preserved. No new task, branch, integration or delivery stage is authorized. The review's 207 focused passes and
three reproduced failures describe the preceding diff, not the corrections below. G07 remains resolved by D285.

The delivery route remains that of §1; technical re-review is pending. The temporary review reproductions were
available and inspected as guidance; maintained tests have no dependency on that file.

### 8.1 Findings and corrections

| Finding | Correction | Maintained regression in `test_frozen_context.py` |
|---|---|---|
| Instruction bodies omitted accepted headings, including rules expressed only in titles and titles scoping child commands | New preparations use `frozen-context-2`. Each instruction exposure contains its full title as a deterministic heading at accepted tree depth, then one LF and its verbatim body; a titleless preamble stays verbatim. The prompt uses those exact exposures in canonical target/preorder. Digests bind that delivered text, not a title-free body | `test_staged_instruction_headings_structure_and_exact_delivered_bytes` uses real `stage_instructions`, real hierarchical adoption, canonical render and initial receipts for Codex/Claude/Gemini; covers a title-only prohibition, a title-only parent constraining a child, preamble, wrappers/targets and exact exposure/prompt/receipt digest equality |
| `context_client` rejection had no artifact locations, but backup unconditionally required them | Client/preflight/guard refusals share `_refuse_before_spawn`; intent/capture positively identify no target launch and promise no prompt/stream files. Backup exempts only consistent known refusals, checking native identity/status and contradictory stream/agent/input events. Ordinary launched-process artifact checks remain mandatory; no paths, files or hashes are fabricated | `test_client_target_refusal_closes_and_survives_backup_and_query_only_restore` closes the failed invocation/owner, backs up/restores without artifact roots, removes the checkout and consults unchanged failure evidence/prompt in the marked query-only copy; ledger is `not_invoked`, no execution or delivered digest |
| Executable identity changed while the gate waited, but the ordinary intent prevented a known context failure receipt | The adapter supplies `launch_permitted=false, launch_boundary=before_go` with the refusal before sending GO. The additive `usage_capture.refusal_boundary` helper is shared by the fenced receipt recorder and backup; the historical accounting classifier is unchanged. A real gate identity is retained, while no target launch/context delivery is claimed | `test_executable_identity_change_before_go_records_known_failure_without_execution` changes the final identity check, verifies no fake CLI work, persists failure receipts without digests, closes the invocation and verifies backup/restore. Only the actual prepared prompt is referenced; no target streams are invented |

`frozen-context-1` snapshots retain their original body-only bytes, hashes and receipts. Readers and backup rebuild
them with that format, never rewriting history. They cannot be selected for a new canonical launch: prepare a new
v2 snapshot at an explicit invocation boundary. `test_historical_body_only_context_stays_readable_without_rewriting_or_new_launch`
qualifies exact legacy consultation and backup/restore; existing D094 rendering tests still pass. No schema, HTTP,
generated-client, frontend, prompt-template, catalogue, dependency or project-conversion change is needed.

Additional negative evidence: `test_backup_does_not_exempt_launched_process_artifacts` rejects missing ordinary
artifact metadata and forged before-spawn/before-GO exemptions after actual observed output.
`test_stop_or_refusal_without_positive_boundary_does_not_claim_nondelivery` leaves cancelled/partial/stopped or
diagnostic-only refusals unknown. Neither stopped process state nor an identity-change diagnostic alone proves
that GO stayed closed. Receipt persistence failure remains fail-closed and no inference retry is added.

### 8.2 Correction checks and remaining delivery

- New maintained regressions reproduced the three reported defects on the preceding code (three heading target
  cases, unavailable client-refusal backup, absent identity-change receipt); logs were inspected before repairs.
- First affected run: `scripts/check tests/product/test_frozen_context.py tests/product/test_backup.py
  tests/product/test_cli_agents.py tests/product/test_prompts.py tests/product/test_knowledge.py
  tests/product/test_trace_observation.py -- -n 0` — **209 passed**.
- After additional compatibility/negative-artifact cases: `scripts/check tests/product/test_frozen_context.py
  tests/product/test_usage_accounting.py tests/product/test_backup.py tests/product/test_cli_agents.py
  tests/product/test_trace_observation.py -- -n 0` — **181 passed**. A preceding command used the nonexistent
  `test_usage_capture.py` path: no tests ran; the log was inspected and the actual accounting suite selected.
- Correction closure, once: `scripts/check` — unittest **10 ran OK**; Alembic **no new upgrade operations**;
  pytest **2511 passed, 2 skipped, 29 subtests passed**, with only the intentional pre-existing duplicate-ZIP
  warning. The command used the local socket/process permissions required by the already-reviewed synthetic
  fixtures; no real service or provider ran. The full pytest log is retained at
  `.local/check/p002-t007-review-general-pytest.log`. No general rerun was needed.
- `scripts/check-docs` over all tracked Markdown plus the two new T007 documents: **97 files, 0 errors**.
  `git diff --check` and whitespace inspection of all six new files are clean. Reviewed the complete correction
  delta against preserved pre-correction file contents; the other initial changes remain intact. No product
  source changed after the general check. API/client/frontend and dependencies are unchanged, so no frontend
  build, generated-client regeneration, package release or installed conversion was performed.
- The earlier §7 general results and the review's 207 passes remain historical evidence of the previous diff.
  This section records the correction results separately: 12 additional maintained regression cases now qualify
  the three fixes, their negative boundaries and historical snapshot compatibility.

Only synthetic knowledge, temporary SQLite/Git, the existing fake CLI and query-only restores are used. Source
corrections are local, re-review is pending, integration and the 0.2.0 delivery stages of §1 remain pending and
separately authorized. The one-off queue is still empty. No real service, provider, global configuration, network
installation, commit, merge, push or publication was performed.

## 9. Technical re-review and authorized integration

On 2026-10-29 the owner requested another technical review and authorized commit, merge into `develop` and push
if no relevant defects remained. Re-review found the three reported defects corrected, with maintained regressions
for staged headings, exact receipt bytes, refused-launch backup/restore and positive before-GO evidence. The
negative artifact and uncertain-delivery boundaries remain enforced. No outstanding technical finding remains.

Independent focused verification: `scripts/check tests/product/test_frozen_context.py
tests/product/test_cli_agents.py tests/product/test_backup.py tests/product/test_usage_accounting.py -- -n 0`:
**161 passed**. The full correction-closure log from §8.2 was inspected: **2511 passed, 2 skipped, 29 subtests passed**,
with the intentional duplicate-ZIP warning. The general suite was not repeated: no product source changed after
that closure; this re-review adds delivery/status documentation only. No frontend build, real provider, service
startup, installed conversion or harness execution was performed.

The remote `develop` head was checked and equals the reviewed base `c0ffc85`. Source commit and integration are
authorized and pending; Git history records their identities when performed. The release through protected `main`,
0.2.0 distribution/publication and local installation remain pending and require separate authorization. T008 is
the next phase task after integration; no T008 implementation is included here.
