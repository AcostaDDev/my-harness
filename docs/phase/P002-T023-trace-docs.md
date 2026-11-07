# P002-T023 — Agent trace graph and documentation drawer

## Ownership and delivery

Owner-authorized local implementation on `feat/p002-t023-trace-docs`, from clean `develop` at `e831a67`
(2026-11-07), under D235/D242. The one-off queue is empty. Scope: T018's L4 trace and L1–L4 read-only
documentation drawer, with synthetic local verification only. No schema or dependency change is planned.

The authorized source and technical review corrections are implemented and locally verified as detailed below.
The prior frontend source passed independent technical re-review, and the owner accepted the visual review
on 2026-11-07. The exact-original continuation is self-reviewed and locally verified. The diff remains
source-complete and uncommitted pending its authorized source commit. The owner authorized commit, merge and push after successful
checks and has now accepted the visual review. Delivery remains
topic branch → `develop` → release 0.2.0 through protected `main` → distribution/publication → installation;
each later stage is pending and separately authorized. The operator installation remains 0.1.9.

## Initial source-record contract discrepancy

At the first handoff, T018 §6.4 assumed a byte-range log read absent from the existing GET logs route. Event
originals, log metadata and retention were delivered then, with new large-original exposure awaiting the owner.
The continuation authorization below resolves this boundary.

**Continuation authorized on 2026-11-07.** After technical re-review passed, the owner instructed this session to
complete the remaining work here. This authorizes the proposed optional single-record read and local visual
verification on the existing branch. The record ceiling reuses T019's 4 MiB plus one JSONL newline. An explicit
`sequence` returns an envelope with exact UTF-8 text, reference identity/digest and availability; the ordinary
metadata read retains its existing response. Source completion and integration/release/installation remain
separate. Owner visual acceptance was subsequently given explicitly after the browser view and screenshots.

## Implemented source

- `InvocationPage` now reads the T020 header, observed steps and both related groups through `LevelLoader`.
  The shared SVG engine, inspector, view preference, router/history and owner breadcrumbs are retained. L4 has
  the same selection/details in `?view=list`. Task, phase-operation, chat and the other managed/excluded lanes use
  the persisted owner; archive returns avoid operational chat/check pages and run evidence uses `/runs/:id`.
- Trace nodes keep native sequence identities. Turn membership fans out tool calls without serializing siblings.
  Persisted turn sequence, turn membership, recorded event parentage and explicit causation have distinct edge
  styles. Overlap flags come from the stored
  projection. Retries, errors and explicit gaps remain separate. Message/reasoning events contain presence and
  digests, never text. The inspector preserves native units, masked argument summaries, chunk-receipt timing,
  sources, coverage, missing fields, original references and related artifact identities. A historical grant and
  its current effective/expired/ended/invalid authority are separate fields.
- All evidence combines one fresh page per unfinished group into a bounded read batch, never a temporal window.
  Native steps keep `seq` order. Exact persisted `tool.links` event IDs associate related records with their step
  when the anchor is unambiguous in the batch. Correlation uses a labelled link without an arrowhead, distinct
  from parentage and causation. All other records, including permissions and evidence whose anchor is outside
  the batch, appear in a separate **Related evidence — position undetermined** section in both graph and list.
  Receipt clocks, native/broker call IDs and cursor boundaries never establish a native position. Related group
  read order is retained within that section; later reads do not move records out of already published windows.
  The loader holds at most five batches plus its first batch (up to 1,200 items per group) and requests at most
  200 items per page using opaque cursors. Only 200 nodes/rows render at once. The next batch is reachable after
  the last window, and reversing across the boundary restores the preceding batch's last window. The first-page
  control restores discarded history. Selecting a group filter starts that history at its first page.
  `409 cursor_stale` restarts the batch history from all of its first pages. Disposed loaders ignore late answers.
  Ordinary mode uses one D306 activity poll across the header and active evidence scopes. Archives have
  no poll, announcement timer, mutation control or operational workspace.
- Originals are explicit authenticated GET reads. A source event must match its run route, attempt and sequence
  before its stored original/reference is displayed. Related events, permission items and stored artifacts use
  the existing trace/inbox reads. Large originals retain their source event, byte reference, size, SHA-256,
  retention state and log-metadata read. The D316 continuation adds exact UTF-8 originals through a separate
  explicit request, with identity checks and escaped text rendering.
- `MapWithDocs` adds the L1–L4 drawer: map on the left, protected Markdown/Mermaid in the centre and the shared
  documentation tree on the right when the drawer has room. The tree follows the document in narrower drawers,
  and the drawer follows the map on mobile. Its URL-owned `doc` and
  `doc_anchor` selection preserves `view` and Back/Forward. Escape closes it, returns focus to the opener and does
  not leave the map; it is non-modal. A delayed document does not steal focus after the user returns to the map.
  Paths are keyed so a late response cannot replace a newly selected document. Documentation code remains lazy,
  and real internal-link hrefs also address the drawer query so modified clicks never open blocked archive Docs
  routes. The initial document is ROADMAP for
  project/phase context, NEXT_STEPS for task context, SPECIFICATION otherwise, then a deterministic available-file
  fallback. A matching persisted phase/task heading is revealed when present.
- New owner-session/Host/Origin-guarded read-only `GET /api/managed/map/projects/{p}/documents[?path=…]` resolves
  the same persisted root identities as the map. It verifies the accepted knowledge revision and reuses the
  canonical D294 renderer via `services/knowledge_exchange.rendered_documents`. Without `path`, it returns only
  the tree/revision; an exact Markdown path returns one document. No transfer JSON, adoption, ownership or export
  payload is exposed. Canonical failures remain failures. The legacy checkout viewer is offered only for a root
  without structured knowledge in ordinary mode and with a configured registered project. Its persisted registered
  ID, rather than a historical `run:` map key, addresses the existing checkout viewer. Archives never compose
  `runtime.project()` or access checkout
  documents/images. Canonical Markdown blocks checkout images; Mermaid retains the existing strict renderer and
  isolated image output. OpenAPI and generated TypeScript were regenerated with the README commands.

No model, migration, dependency, authority, provider, accounting or frozen-history change. The schema remains
`0041_work_map_reads`, 94 tables. T024 contextual chat, T025 aggregation and later qualification remain outside scope.

## TM14 and TM17

**TM14:** the graph does not reconcile step counts against reported counters. It labels chunk receipt timing,
client-native units and unknowns; exposes coverage/observation separately; distinguishes pending projection,
integrity failure, excluded lane and pre-T019 settlement; earlier runs retain their available counters and run
reference with no backfill. Membership, record order and persisted causation are distinct. Receipts prove delivery
availability only. Permission history does not grant current authority. No action is inferred from an edge.

**TM17:** graph/list nodes and activity use bounded projection fields only. Message/reasoning/result bodies are
absent. Original reads occur on an explicit request through existing authenticated routes and are rendered as
escaped text. The residual risk of owner-stored secrets in canonical documents and original evidence is unchanged;
the existing safe Markdown/link and strict Mermaid boundaries apply. New canonical consultation does not expose
transfer metadata, checkout images or document mutation controls.

## Pending owner decision: one large source record

**Initial handoff proposal, subsequently implemented under the continuation authorization (D316).** Add an optional `sequence` query parameter to the existing
`GET /api/managed/runs/{run}/attempts/{attempt}/logs`. With no parameter, retain the current `ManagedLogRead[]`
metadata response byte-for-byte. With `sequence`, return a separate typed envelope for exactly one persisted
`agent_event` original (not an arbitrary user-chosen byte range). Verify that the run owns the attempt, the event
belongs to that attempt and has `original_reference`, its stream/offset/size are valid and within the verified
sealed capture, and the retained bytes match both capture and record digests. Apply a fixed record-size ceiling
before allocation; choose the ceiling and JSON/text encoding in the owner's contract acceptance. Return explicit
retained/purged/missing/unverified states and never reconstruct removed bytes. Use the same session/Host/Origin,
read-only restore and filesystem containment checks; qualify archive reads both with and without restored streams.
Reject a foreign sequence identically to an absent one. A union response selected by the optional parameter needs
OpenAPI/client parity and compatibility tests for current metadata consumers. No polling or operational route is
added. A separate proposal review should settle the response shape, bound and verification rules before coding.

At the initial handoff the logs contract stayed unchanged and this exposure waited on the owner. The later
continuation below implements it under D316. This proposal records the earlier boundary; current completion
and delivery status are tracked separately.

## Synthetic verification

Focused checks passed: 130 Node tests across trace/docs, work-map, map-view/assets/layout, Markdown and i18n;
70 Python tests across map documents, work-map and knowledge document rendering/exchange. The initial two new
canonical-document tests also passed separately. A later self-review correction binds legacy checkout fallback to
the persisted registered-project ID (a stable `run:` map identity is not an operational project ID); the 20 T023
Node tests were repeated successfully after that correction. A post-review Python fixture failure came from a
missing synthetic legacy checkout directory; the fixture now creates it before registering the context.

Closure checks on 2026-11-07:

| Check | Result |
|---|---|
| Focused Node suites | 130 passed; later corrections repeated over 92 affected Node tests, all passed |
| Focused Python map/document/exchange suites | 70 passed; canonical restored consultation also passed with the checkout physically renamed away and runtime composition made to fail |
| `scripts/check --frontend` (one complete run) | unittest: 10 passed; Alembic: no new operations; Node: 400 passed; TypeScript + Vite: passed. Python: 3,118 passed, 3 skipped, 29 subtests passed, 1 warning; 98 failed and 26 errored: 123 cases were blocked by sandbox socket/`/bin/ps` restrictions in synthetic bridge/process/start-command fixtures; one existing observed-step scaling-ratio assertion missed its timing threshold under parallel load |
| `scripts/check -- --lf --last-failed-no-failures=none -n 0` (approved outside the sandbox) | 125 passed, 144 deselected; includes all 124 full-run failures/errors and the corrected legacy-directory fixture. unittest: 10 passed; Alembic: no new operations |
| Final `scripts/check --suite node --suite build` | 400 passed; TypeScript + Vite passed (build 634 ms) after the registered-identity, lazy-code and internal-href corrections |
| OpenAPI + generated client | Regenerated with the two README commands; only the read-only document contract is added |
| `scripts/check-docs` | 128 Markdown files, 0 errors; the new task record also checked explicitly, 0 errors |
| `git diff --check` and new-file whitespace review | Clean; the final tracked and newly created source/doc diff was reviewed locally |

The complete command was not represented as an all-green sandbox run: its platform restrictions and parallel-load timing outlier are preserved in
this record. The directed approved repetition resolves every reported case; no unresolved test failure remains.
The three skipped cases are not asserted as tested successfully. The full suite's warning was the expected
duplicate ZIP-member warning in a synthetic installer tampering test. Local full
logs are `.local/t023-full-sandbox-python.log`, `.local/t023-focused-python.log`,
`.local/t023-focused-node.log`, `.local/t023-correction-node.log` and `.local/check/` (untracked).

No product/development server, harness run over this repository or real agent/provider was started. The full
checks used temporary synthetic subprocess/socket stubs; the failed cases were repeated serially under the
approved local verification escalation. No network installation, global configuration change, source commit,
merge, push, publication or operator installation was performed during initial verification.

The fixture extends T022's development-only product fixture with 5,000 steps, parallel native calls, a separate
failed call/retry, message/reasoning presence, gaps, large retained/removed records, deliveries, search/describe
schema evidence, judge resolutions, an expired historical grant, authenticated original-read substitutes and
canonical Markdown/Mermaid. It generates trace pages on demand. Nothing in it calls a provider or mutates a project.

## Technical review corrections

The reviewer reproduced the two trace findings, identified the drawer sizing conflict in the application shell
and reported 63 focused Node tests, both Python document API tests, the docs check and the whitespace check passing.
The correction pass adds frontend regressions and leaves the existing document endpoint and its generated contract intact.

- **Combined history.** The D309 regression visits all 5,000 steps and seven related entries exactly once in the
  real All evidence list, verifies that `#199` remains reachable before `#200`, compares the last window of the
  first batch in map and list, and restores exact windows in both directions. The remaining placement correction
  below separates unrelated evidence from native order. Unequal group sizes, empty steps,
  steps ending first, a partial read failure, stale cursor recovery and opaque cursor round trips are covered.
  The Observed steps filter separately reaches `#4999` and returns to held and first pages.
- **Trace relationships.** Regressions invert receipt clocks, omit a receipt time, and distinguish a parent-only
  event from an event with explicit causation. When the same pair carries both fields, the arrow shows the explicit
  cause and the inspector retains both fields. Parallel sibling fan-out is preserved.
- **Drawer width and keyboard.** Headless Chrome rendered a static bundle with the real `Shell`, sidebar, L4
  map, inspector and drawer, using synthetic fetch responses and local files. At 885 px the original drawer
  extended 47 px past the 589 px content area. The corrected drawer fits at 390, 879, 880, 881, 885, 1100 and
  1440 px, with the map hit-testable at every width and three adjacent panels at 1440 px. Keyboard zoom and
  focus access to a document link, tree and inspector passed at 390, 879, 885 and 1440 px. Inspector focus
  survived resizing from 885 to 879 px with the mobile sheet initially closed.

Focused Node checks passed 58 tests. `scripts/check --suite node --suite build` passed 405 Node tests and the
TypeScript/Vite build. `scripts/check-docs` and `git diff --check` passed. The correction pass did not rerun
Python or regenerate the contract because its changes are confined to the frontend and documentation. Local
logs are in `.local/t023-rereview-focused.log`, `.local/t023-rereview-browser.log` and `.local/check/`.

## Remaining P2: evidence placement across windows

The owner's re-review confirmed the previous navigation, sequence-arrow and drawer-width corrections within
their scope: 68 focused Node tests, docs and whitespace checks passed; geometry and keyboard were contrasted
with the implementer's Chrome record. That round did not repeat Python or owner visual acceptance. One P2
remained: receipt-time sorting inside each independently paged batch could place a receipt received near `#4500`
between `#199` and `#200`. Local correction of that finding is authorized under T023's existing delivery route;
the source stays uncommitted on the same branch and base.

The regression was run first with the trace/map/navigation/view suites: it failed against the previous placement
while the other 73 tests passed (`.local/t023-position-baseline.log`). The corrected real `InvocationPage`
regression visits all 25 D309 step pages in both graph and list with the late receipt in the first records page.
It checks native `seq` order, an explicitly separate unpositioned section, exact backward-window restoration,
5,007 identities reached once, at most 200 rendered items, exactly the existing 25 step reads plus two related
reads, and zero archive timers. The development fixture now includes that late first-page receipt too.

A second real-view regression in English and Spanish anchors a discovery event using T019's persisted
`tool.links.discovery_event_id`, compares graph/list placement and held windows, and checks the correlation link
has no arrowhead. Adapter checks cover inverted/missing clocks, repeated/ambiguous event links, native versus
broker call IDs and an anchor outside the read batch. Parentage and causation do not transfer a step position.
Existing unequal-group, partial-failure, `409 cursor_stale`, retention, lazy-original and archive regressions remain
in the focused run. Exact links are used only when both identities are available in the batch; otherwise the
record remains explicitly unpositioned and its persisted references remain available through the inspector and
group filters. Subsequent pages cannot silently reposition held evidence.

No API change is needed for this honest bounded presentation: the existing step projection already exports
persisted event links. General native positions for receipts, permissions or rulings are not exposed by the
current related reads and are not inferred. No new read, logs-contract change, generated-client regeneration,
schema or dependency change is part of this correction.

Focused trace/map/navigation/view verification passed 76 Node tests before closure. Final
`scripts/check --suite node --suite build` passed all 408 Node tests and TypeScript/Vite; `scripts/check-docs`
passed (128 Markdown files, zero errors), and `git diff --check` was clean. The changed source, tests and current
STATE/NEXT_STEPS/ONE_OFF_TASKS were reviewed locally. Python, fresh browser geometry/performance,
screen-reader checks and owner visual review were not repeated in this correction; the earlier Chrome record remains scoped to its
previous geometry/keyboard checks. No service, harness, real agent/provider or delivery action was started.
Local focused output: `.local/t023-position-focused.log`; closure output: `.local/check/`.

## Authorized exact-original continuation

The owner instructed this reviewer session to complete the remaining work here after the prior source's
independent technical re-review passed (76 focused Node tests plus documentation and whitespace checks).
D316 records the additive optional-sequence read, exact UTF-8 envelope and reuse of T019's record ceiling.
`StdoutRanges.read` extracts its existing verified-byte path; the projector's `get` keeps the same JSON result.
The existing metadata consumer retains its response. The L4 inspector adds an explicit large-original read,
checks the envelope's run/attempt/sequence/range/digest identity and renders content as escaped text.

Focused synthetic API/storage checks cover exact bytes/digests, metadata compatibility, session/Origin guards,
foreign or absent sequences, malformed references, missing/altered/symlink streams, corrupt record/chunk hashes,
range bounds before stream reads, a capture without a seal, retention and restored copies with the original
checkout and stream gone. Node regressions cover explicit reads, escaped content, unavailable bytes and a
mismatched response identity. OpenAPI and the generated client are regenerated.

Final verification on 2026-11-07 passed:

- Focused original/retention/observed-step checks: **103 Python tests passed**, including 12 new original-read cases.
- Focused trace UI checks: **29 Node tests passed** after the exact-original read was added.
- `scripts/check --frontend`: **10 unittest tests**, Alembic without new operations, **3,254 pytest tests passed,
  3 skipped, 29 subtests passed**, **409 Node tests passed**, and TypeScript/Vite built successfully.
  The one pytest warning is the existing synthetic duplicate-ZIP-member warning. The build retains its existing
  chunk-size warning. The three skipped tests are not counted as executed successfully.
- `scripts/check-docs`, including this new task record explicitly, and `git diff --check`: passed.
- Source and final diff reviewed locally; no outstanding technical finding was identified in the continuation.

Logs are `.local/t023-original-focused-python.log` and `.local/check/`. The final complete run has no socket
restriction or unresolved timing failure. Browser evidence and the owner's acceptance are below.

## Owner visual review and acceptance

The continuation reused the already running local Vite fixture at `127.0.0.1:5173/__map-fixture/` without
starting the API or touching the development database. For repetition, choose **Product projections** and
**D309 realistic sizes**, then open
`/__map-fixture/projects/atlas/invocations/inv-atlas-executor-2?view=map&doc=`. These are synthetic browser reads.

1. Review at desktop 1440 × 900 and mobile 390 × 844, light and dark, English and Spanish. Check the open drawer
   shows map/document/tree in the intended order without horizontal page overflow, and the map still pans/zooms.
   Repeat across the shell breakpoint at 879 and 885 px.
2. Close the drawer with Escape, verify focus returns to Documentation, reopen by keyboard and verify Close is
   focused. Navigate the tree and document links, then use Back/Forward. A link stays inside the drawer and keeps
   the map/list choice. Narrow the viewport while focusing an inspector or document link; focus stays reachable.
3. Tab to a trace node; use arrows, Enter, Tab to details, Escape and zoom-out. Check the owner return is the correct
   map level. Select the failed call, parallel sibling, retry, message/reasoning and not-observed gap; compare every
   detail in list view. Verify status icons/text, readable labels and 4.5:1 contrast in both themes. Enable reduced
   motion and verify immediate transitions/static marks.
4. In All evidence, move through render windows and group histories. Load all 25 step pages, verify the last step
   is #4999, move among held pages, then return to the first page. Node count stays at most 200. Original event/log
   buttons remain explicit, and the exact-large-original read and retention text are visible. Check related receipts,
   schema loads, judge records/artifacts and historical response versus expired authority. The first receipt has
   a reception time near #4500 but appears only in the separate position-undetermined section, never as a step
   between #199 and #200. Exact persisted event correlations, when available in a batch, are labelled step links
   without causal arrowheads. Check both sections in graph and list and return to the same held window.
5. Enable archive mode and repeat on the `kp-atlas` project key. Check no activity requests/timers, actions or
   operational chat/check links; canonical docs still work. For refresh testing in ordinary mode, advance the
   fixture version and observe the first-page reload through the activity read. Use browser throttling for route
   changes during reads and for returning focus to the map before a delayed document arrives.

The owner accepted the visual review on 2026-11-07 after inspecting the visible synthetic browser and the
desktop/mobile screenshots. This continuation verified the exact-original read in English/light desktop
(1440 × 1000) and Spanish/dark mobile (390 × 844), no mobile horizontal overflow, keyboard focus in the original,
and a purged record in archive mode. Saved screenshots are in
`.local/evidence/p002-t023-exact-original/` (local, synthetic, untracked). No fresh screen-reader or performance
measurement is claimed. The earlier browser geometry record keeps its original scope.


## Delivery disposition at handoff

| Stage | Actual status |
|---|---|
| Authorized local source | Complete and verified; source commit pending on `feat/p002-t023-trace-docs` |
| Large-original byte read | Implemented locally under the continuation authorization and D316; verification above |
| Independent technical re-review | Prior frontend source passed with no relevant findings; the subsequent original-read addition is verified and self-reviewed in this session |
| Owner desktop/mobile visual review | Accepted explicitly on 2026-11-07 after the visible synthetic view and captures |
| Integration into `develop` | Commit, merge and push authorized after successful final checks and visual acceptance; currently pending |
| Release `0.2.0` via protected `main` | Pending; separately authorized release path |
| Distribution/publication | Pending and unauthorized |
| Operator installation | Pending; remains `0.1.9`; no installation performed |

`STATE` and `NEXT_STEPS` retain the source/integration distinction, D316 and the recorded visual acceptance.
`ONE_OFF_TASKS` was checked and remains empty. No historical/frozen evidence or recipe artifact was rewritten.
