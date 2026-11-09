# P002-T024 — Contextual reviewer conversation

Owner: P002-T024. Implementation and local synthetic verification authorized by the
owner on 2026-11-09. Branch `feat/p002-t024-contextual-chat`, from clean `develop`
at `dcef8ee` (also local `origin/develop`; no fetch). One-off queue empty.

## Delivery and authority

Checked source → independent technical review and owner visual review → integration
into `develop` → release 0.2.0 through protected `main` → distribution/publication
→ installation. The no-run correction and the fixture fixes passed independent technical re-review.
The owner authorized Vite with the synthetic T024 fixture and confirmed visual acceptance on 2026-11-09.
The owner authorized the source commit, merge into `develop` and push of `develop` after those reviews.
Release, distribution/publication and installation remain pending. Installed version remains 0.1.9.

Scope: D307 and T018 §9, using T007, T017, T020 and T022. No T025–T029 work.

## Implementation and verification

Implementation is complete locally, including the no-run task correction and the two synthetic fixture fixes.
Independent technical re-review passed for the no-run correction and both fixture fixes. The owner accepted
the visual review and authorized integration into `develop`.

## Implemented source

- Authenticated reference read and strict message reference validation. The persisted knowledge-project identity
  scopes phase/task stable IDs and accepted revisions; run IDs plus optional stable L3 step keys scope evidence
  digests. Membership/freshness, canonical preparation and enqueue share the managed write transaction. Replay
  returns the admitted job without another snapshot, invocation or receipt. Stale selections return
  `409 element_stale`, without inference admission.
- Canonical phase/task Markdown uses the document renderer's shared entity implementation (identical existing
  export bytes). Run/step summaries read T020 projections directly, one selected attempt/round/tail member, without
  full histories or native originals. Reference, label and evidence framing count towards 16 KiB of UTF-8; complete scalars,
  codepoint ranges, source/exposure digests, byte limit and truncation are recorded. Element authority is capture,
  never instructions, permissions or judge resolution.
- Tagged turns prepare T007's existing accepted snapshot format and use `chat-turn@1` (one node). The managed job
  remains the only scheduler. Native attempt, invocation operation, canonical boundary and existing accounting row
  seal together. The read-only HEAD export remains the execution directory; original request/project, operation
  and ledger root remain unchanged. No checkout lock is taken.
- Only completed-input observation writes ordinary T007 initial exposures plus one element exposure. Phase/task
  receipts retain existing types/v2; run/step receipts alone add `knowledge-delivery-3` / `run_evidence`. Intent,
  queueing and a model answer never manufacture a receipt. Pre-GO refusal, actual partial pipe write, receipt/event
  rollback, commit failure and lost results retain unknown/failure semantics; inference is never retried
  automatically. Initial readers and backup verify the saved prompt/selection/source, exposures, hashes and events.
  Existing v1/v2 records and snapshot formats are unchanged; no migration or dependency was added.
- A separate map/L4 reviewer talk entry opens an unbound conversation. Tag removal clears the reference and
  refresh locator, sends no element through another field, and returns focus to the composer. Explicit refresh
  changes the visible revision/digest; stale turns are blocked and late responses cannot reattach a tag or navigate
  from a newer selection. Legacy has an explanation without a tag; restored maps expose no talk button. Executor
  and judge retain no composer. Untagged chat, deterministic commands and confirmed proposals retain their paths.
- OpenAPI and TypeScript types regenerated with the README commands. en/es catalogues, chat/context/map flows,
  current state/plan, architecture/specification and JSON-contract documentation are updated. D307 is now locally
  implemented; D317 records implementation choices. ONE_OFF_TASKS remains empty.

## Verification record

Only temporary synthetic SQLite/Git, fake native CLI processes and in-process HTTP clients were used. No listening
service, real provider, real project harness run, network download, installation or global change.

Focused checks during implementation:

- Existing chat, chat lane, T007 and canonical document tests: **109 passed**.
- New full managed contextual journey: phase/task/run/step; actual fake-CLI input observation; one existing ledger
  row; tag removal; strict/foreign/missing/stale references; UTF-8 truncation and injected instructions; adoption
  after enqueue; replay; no lock; backup/restore and query-only/no-checkout reads; HTTP session/Host/Origin/CSRF and
  archive refusal. T020's real task fixture also checks invocation and deterministic Harness step keys.
- Delivery-fault subset: **6 passed**, including pre-GO refusal, actual partial pipe write, receipt/event rollback,
  receipt commit failure, observed delivery with lost result, and forged saved source refusal before launch.
- Targeted Node regression set: **75 passed**; dedicated contextual checks before closing: **8 passed**. They exercise the
  real talk button, composer, tag state, stale refresh, removal/focus, delayed responses, en/es, legacy, archives,
  route-base preservation and the in-memory visual fixture. TypeScript check passed before the closing run.
- Earlier focused failures were corrected using their logs: test adapter reuse, fixture column/import/label
  assumptions, and fixture TypeScript fields. No general suite was rerun during those corrections.

Closing verification on 2026-11-09:

| Command/suite | Exact result |
|---|---|
| `scripts/check --frontend` — executed **once** | Exit 1: the two architecture-guard failures below; remaining suites completed |
| unittest | **10 ran, passed** (0.0 s) |
| Alembic | **No new upgrade operations** (0.7 s) |
| full pytest | **2 failed, 3,269 passed, 3 skipped, 29 subtests passed**, 1 warning (343.7 s) |
| Node, same closing command | **418 tests, 418 passed** (9.5 s) |
| frontend build, same closing command | **TypeScript + Vite passed** (3.7 s; Vite 291 ms) |
| affected Python suites after corrections (command below) | **204 passed, 1 skipped** (23.3 s) |
| actual foreign accepted-entity case added to the isolation test; focused recheck | **1 passed** (3.0 s) |
| `scripts/check-docs` | **129 Markdown files, 0 errors** |
| `git diff --check` | **Passed**, no output |

The full run found two existing architecture guards, which were preserved:

- `tests/product/test_orchestration.py::test_import_boundary_confines_langgraph_to_the_orchestration_package`:
  the new graph is now loaded only through the established lazy `managed_runtime.run_chat_graph` interface.
- `tests/product/test_domain_operations.py::test_only_the_service_mutates_knowledge_in_product_code`:
  chat now uses T007's shared, transaction-scoped accepted-revision reader and snapshot preparer, exposing no
  knowledge mutation methods. No guard allowlist was expanded.

Final diff inspection also tightened the delivery byte boundary: the reference, label and evidence frame all
count towards 16 KiB. Exactly one literal block enters the prompt, outside its ordinary context JSON; the digest
covers those exact bytes. Tests check literal occurrence once, UTF-8 bounds and no duplicated JSON element.
Run evidence also stays frozen after a later source version change. The isolation case additionally uses real
accepted stable IDs from a second synthetic project, both with its foreign project reference and with a forged
current-project reference; both are refused without a chat job.

Only the affected tests were repeated after these corrections:

```sh
scripts/check tests/product/test_chat_context.py tests/product/test_work_map.py tests/product/test_chat.py tests/product/test_chat_global.py tests/product/test_frozen_context.py tests/product/test_knowledge_documents.py tests/product/test_domain_operations.py tests/product/test_orchestration.py
```

That run includes both previously failing guards, the new full managed journey, backup/read consumers and the
canonical-renderer/untagged-chat regression tests. The general suite was **not** repeated. Its warning is the
existing intentional duplicate-ZIP-member tampering test (`test_install_command`), not a provider warning. The
skipped checks retain their existing opt-in conditions; no new skip was added. Independent technical review and
browser visual acceptance are not claimed.

## Technical-review correction — task before its first run (2026-11-09)

The independent review reported **204 Python tests passed, 1 skipped; 71 Node tests passed**, documentation
without errors and a clean `git diff --check`. It did not repeat the general suite or start services. It found
one P2: the real `WorkMap` hid reviewer talk on `atlas / P002 / P002-T004` (no runs), although its selector had
successfully resolved the project; `P002-T005` (with runs) showed the button. Integration was not approved.

The owner authorized this bounded local correction under T024's existing delivery route, on the same branch and
base, preserving all uncommitted implementation. No design change, backend change or new dependency is involved:

- `WorkMap` now resolves the chat project from the steps/level read, falling back to the valid run-selector read.
  The registered identity and canonical/legacy distinction come from the server response, never the route alias.
  The explicit archive prop and `read_only_archive` on either read suppress the button, even if a registered
  identity is present.
- Without a run, the existing target resolver selects the task. Opening talk resolves its accepted reference and
  opens a conversation with `phase_id: null` and `task_run_id: null`; no execution run is created. The real chat
  destination displays the removable task tag. Legacy opens untagged with its existing explanation. The first
  run's arrival through polling switches the target to that run, and selecting a step switches it to that step.
- Four regressions in `frontend/tests/chat-context.test.mjs` mount the real `WorkMap`, reusing `hookHost`, the
  existing test setup, `syntheticMap` and `chatFixture`. They cover canonical no-run task opening and tag removal
  in the real `Chat`, server-resolved identities, legacy without runs, missing registration, independent archive
  guards with and without runs, and the task → first run → selected step transition. All writes are inspected;
  only unbound conversation creation is allowed in the opening cases, with no context read or mutation in archives.

Verification for this correction (local synthetic checks only):

| Command/check | Exact result |
|---|---|
| Initial `node --test frontend/tests/chat-context.test.mjs frontend/tests/work-map.test.mjs` | **42 passed**, 0 failed |
| Same command with the four regressions, before the product fix | **43 passed, 3 failed**; missing button reproduced |
| Same command after the fix and final regression refinements | **46 passed**, 0 failed, 0 skipped |
| `node --test frontend/tests/*.test.mjs` | **422 passed**, 0 failed, 0 skipped (7.6 s) |
| `npm --prefix frontend run build` | **Passed**, TypeScript + Vite; Vite 274 ms, nonblocking chunk-size warning |
| `scripts/check-docs` | **129 Markdown files, 0 errors** |
| `git diff --check` | **Passed**, no output |

The correction diff was inspected, including the new untracked tests and this evidence; all previous uncommitted
implementation and new files remain in place. Python and the general mixed suite were not repeated: this
correction changes frontend source/tests and current documentation only. No service, Vite dev server, browser,
real agent/provider, harness, installation, download,
commit, merge, push or publication was started. Local correction is complete; technical re-review and owner visual
acceptance remain pending. Integration is not approved; release 0.2.0, distribution and installation remain pending,
and the recorded installation stays at 0.1.9.

## Independent re-review and visual findings (2026-11-09)

The independent technical re-review passed the no-run task correction with **46 focused Node tests passed**,
documentation without errors and a clean `git diff --check`. The backend matched the previously reviewed source.

After the owner authorized Vite with the synthetic fixture, the browser review covered desktop (1366×900)
and mobile (390×844) in both themes and languages. It verified opening talk before the first run, tag removal
and focus return, stale-context rejection and explicit refresh, and the absence of talk controls in restored
archives. Vite was stopped. The eight reference captures record that review. Owner acceptance remains pending.

- **P2 — Stale canonical reads after enabling legacy.** After `atlas / P002 / P002-T004` loaded, checking
  legacy replaced the synthetic map and chat simulator while the mounted map kept the earlier read.
  Talk still attached a canonical task tag. The map and L4 invocation now share a key derived from the
  synthetic projection settings. Changing legacy remounts those readers before talk is available.
  Theme and language remain outside that key and preserve the conversation simulator.
- **P3 — Conversation list returned detail objects.** After one synthetic answer, the list rendered
  `[object Object] turnos` because `turns` was an array. The fixture now projects the generated
  `ChatConversationSummaryRead` fields with a numeric turn count. Detail reads retain the full turn array.
  Production contracts and backend source were unchanged in this correction.

The Node regression mounts `ProductFixture`, loads canonical data, then toggles the control in both L3 and L4.
It checks that opening talk skips canonical context resolution, displays the legacy explanation and preserves
the conversation across theme and language changes. The turn-count regression checks exact summary fields,
detail messages and the real `Chat` list at zero, one and three turns.

| Check | Result |
|---|---|
| Focused chat-context regressions before the fixes | **13 passed, 4 failed** (L3 and L4 plus their parent test, and the summary test) |
| `node --test frontend/tests/chat-context.test.mjs frontend/tests/work-map.test.mjs` | **50 passed, 0 failed, 0 skipped** |
| `node --test frontend/tests/*.test.mjs` | **426 passed, 0 failed, 0 skipped** |
| `npm --prefix frontend run build` | **Passed**, TypeScript and Vite. Vite 267 ms, with a nonblocking chunk-size warning |
| `scripts/check-docs` | **129 Markdown files, 0 errors** |
| `git diff --check` | **Passed**, no output |

Targeted browser verification with Vite alone confirmed the legacy explanation and absence of a context tag
after toggling on the loaded L3 task and loaded L4 invocation. The L3 conversation showed **0, 1, 2 and 3 turns**
as three synthetic messages received answers. Switching to dark and Spanish preserved all three messages
and showed **3 turnos**. The test tab was closed and Vite was stopped. Python and the mixed suite were not
repeated for this fixture-only correction.

## Final technical re-review and owner visual acceptance — 2026-11-09

Independent re-review of the fixture fixes passed with no outstanding findings. The reviewer repeated 50 focused
Node tests, `scripts/check-docs` (129 Markdown files, zero errors) and `git diff --check`. The backend matched
the previously reviewed source. The reviewer could not reopen the corrected fixture because local browser use
was disabled in Work settings and stopped Vite. The corrected browser evidence above comes from the implementer's
synthetic verification. The owner explicitly confirmed visual acceptance on 2026-11-09.

## Visual review procedure

Prepared fixture: the development-only `/__map-fixture` page, **Data → Product map**, **Review** scenario. It mounts
the real `WorkMap`, `InvocationPage`, `ReviewerTalk`, `ChatElement`, `Chat` and project workspace. The fetch shim
handles only the synthetic conversation in memory; other mutations remain refused. No provider runs. Refreshing
the browser discards simulated conversations; theme and language changes preserve them.

For fixture review, start Vite alone with `npm --prefix frontend run dev` and open the fixture at
`http://127.0.0.1:5173/__map-fixture/`. Use the deep atlas project and stop Vite after review.

Review **light/dark × desktop (about 1366×900)/mobile (about 390×844) × en/es**, recording all eight combinations:

1. Select a phase at L1, a task at L2, a run at L3 without a selected step, and an invocation or Harness stage in the
   L3 inspector. Each separate **Talk to the reviewer** action opens a fresh conversation with the named context tag
   and visible revision/digest. L4's separate talk entry selects its owning invocation step. Actor circles and
   request bubbles retain their separate routes/panels. Also open `atlas / P002 / P002-T004` before any run: the
   empty-run message and talk button must coexist, and talk must open with the removable task tag.
2. Use only Tab/Enter/Space to reach talk, tag refresh/removal and composer. Remove the tag; focus returns to the
   message field and the next synthetic answer's turn has no selected element. Verify that actions wrap and long
   labels do not overflow on mobile, with visible focus and readable light/dark contrast.
3. Keep a tag and typed question, then choose **Simulate a change**. Sending refuses stale context and preserves
   the message. Explicit **Refresh context tag** changes the displayed revision/digest and enables sending again.
   Remove the tag during a refresh; a delayed response must not bring it back. A command with a tag asks for removal
   and keeps the existing preview/confirmation flow.
4. Return to a map route, enable **Legacy conversation (no canonical context)**, and open talk: no tag, with the
   explanation in the selected language. Return to the map and choose **Read-only archive**: no talk button and no
   free compositor. Executor and judge details have none in ordinary mode either.
5. Check Back/Forward, owner breadcrumb, graph/list navigation and the unchanged inbox bubble interaction. Record
   any finding, correct it on this branch, and obtain owner acceptance before integration.

## Delivery status

Reviewed source is complete on `feat/p002-t024-contextual-chat`. Technical re-review and owner visual acceptance
passed. Integration into `develop` and its push are authorized. Release 0.2.0 through protected `main`,
distribution/publication and installation remain pending. The recorded installation remains 0.1.9.
