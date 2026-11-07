# P002-T022 — Work-map levels and home page

**Status:** local source complete on `feat/p002-t022-work-map` with synthetic evidence; **nothing committed**. The
first independent technical review (2026-11-06) found seven functional defects and did not approve integration; they
are corrected locally (§9). The re-review reproduced two remaining problems, also corrected locally (§10). Opening the
synthetic frontend afterwards showed two blocking browser defects (status and counter overlapping on cards; a closed
mobile inspector keeping hidden controls in the Tab order), corrected locally with regressions and browser evidence,
including the browser measurements (§11). The next re-review reproduced quadratic label fitting and stale deferred
inspector focus. Both are corrected locally (§12); the diff awaits independent re-review. The owner's visual review (T022's own
plus T021's deferred review, D313), integration, release, distribution and installation are pending and are not
claimed here. Decision for the choices delegated to
this task: [D314](../DECISIONS.md#d314--work-map-levels-on-the-product-routes-refresh-client-and-read-only-archive-map).

## Ownership and delivery

| Field | Value |
|---|---|
| Owner task | P002-T022 (frontend: map levels L0–L3 and home page); no gates pending (G14 resolved by T018) |
| Branch | `feat/p002-t022-work-map` from `develop` at `4535804` (verified clean and equal to the local `origin/develop` on 2026-11-06; ONE_OFF_TASKS empty; no earlier T022 branch or work existed) |
| Dependencies | T017 (inbox and `InboxConversation`), T020 (read projections `GET /api/managed/map/…`, integrated `b30a00c`), T021 (SVG engine and assets, integrated `6b6a0ee`) |
| Contract | [T018 §§3–5, 7–8, 11–14](P002-T018-work-map-contract.md#3-levels-cards-and-inspector-g14); D297, D303, D304, D306, D309, D311–D313; D235/D242/D253 for delivery |
| Scope | L0–L3 map as the product entry; `?view=map\|list` on the same path with a remembered choice; compact cards and inspector (bottom sheet on narrow screens); circles R/E/J/H, rays and the chat lane; T017 bubbles opening `InboxConversation` over the map; activity polling with gap recovery; read-only archive map; shared `Status` on the six classes plus `unknown`; en/es parity |
| Out of scope | L4 trace graph and documentation drawer (T023), contextual talk button and receipts (T024), accounting (T025), qualification (T026–T029). First closure: no model, migration, API contract, OpenAPI, generated-client or dependency change was needed or made. Review corrections: one read extension authorized for them (§9.3); still no model, migration, persistence, authorization or dependency change |
| Authorizations (2026-11-06) | Creation of the topic branch and local implementation, verification and documentation of T022. Not authorized: commit, merge, push, publication, network installation, new dependencies, global changes, starting services or `scripts/dev`, running the harness, real agents or providers |
| Authorizations (review corrections, 2026-11-06) | Local implementation and verification of the seven corrections on the same branch, and only the minimal query extension needed to keep attribution and scope (project isolation, bounded read, archive parity, OpenAPI and generated client). The same exclusions apply |
| Authorizations (re-review corrections, 2026-11-06) | Local implementation and verification of the two corrections and the minimal projection extension for L3's chat lane (bounded, attributable to the project/run shown, versioned, archive parity; OpenAPI, generated client and flows). No commit, merge, push, publication, network install, dependency, persistence, authorization rule, service start, `scripts/dev`, harness run or real agent/provider |

| D242 stage | Status |
|---|---|
| Local source | Complete on `feat/p002-t022-work-map`, uncommitted |
| Independent technical review and corrections | Corrections to the independent reviews and the synthetic browser findings are recorded in §§9–12. Latest diff pending independent re-review |
| Owner visual review in the browser (T022 and T021's deferred review, D313) | Pending (§7); blocks integration, not local work |
| Integration into `develop` | Pending |
| Release 0.2.0 via protected `main` | Pending |
| Distribution/publication | Pending |
| Installation | Pending; recorded installation 0.1.9 |

## 1. Implementation

New modules are in `frontend/src/map/` unless noted. Pure modules carry the behaviour and are tested in Node.

| Module | Responsibility |
|---|---|
| `api.ts` | Paths of the nine T020 reads used here (projects, phases, tasks, runs, steps, invocation header, activity), opaque cursor pass-through, `409 cursor_stale` and 404 classification over the shared `managed()` client |
| `loader.ts` | `LevelLoader`: one level path, one request in flight (a reload asked meanwhile runs once after it), further pages on demand up to five, stale-cursor recovery from the first page, no late answer after `dispose` |
| `refresh.ts` | `ActivityPoller`: one aggregated `map/activity` read for the scopes in view, next read only after the previous settled, 2 s / 10 s from the response's `polling`, paused while hidden, stopped when polling is disabled; `changedScopes` |
| `announce.ts` | Status changes of elements already shown and a 10 s throttled summariser for the polite live region |
| `projection.ts` | T020 responses → engine nodes and edges per level (class, counter text, circles with targets, chat lane, bubbles, error marks, badge, slots); never recomputes a class or counter |
| `view-mode.ts` | `?view=map\|list`, remembered choice with an in-page fallback, history entries |
| `WorkMap.tsx` | Level page: loaders, poll, selection, inspector, requests, run selector, live region, table display for archives; `useLevel` never returns another path's state |
| `Inspector.tsx` | Contract fields per level with their sources and "not observed" reasons; shared `StepFields` |
| `Requests.tsx` | Requests panel over the map: listed identities, inbox fallback for aggregates and truncated lists, T017 `InboxConversation` |
| `LevelSwitch.tsx` | Map/list toggle; list = existing page (ordinary mode) or a table over the same projection (archives) |
| `InvocationPage.tsx` | `/projects/:p/invocations/:i`: T020's existing L4 header read only (circle targets never 404) |
| `fixture/projections.ts`, `fixture/ProductFixture.tsx` | Synthetic T020-shaped projections and T017 reads (tests and development fixture); fixture page of the product map with a fetch shim that refuses every mutation |
| `MapView.tsx`, `labels.ts` (T021, extended) | Optional `selected`/`onSelect`/`onActor`/`onRequests`; counters, error mark, badge and slots inside the card link; circles, bubbles and details as overlay controls outside it; chat label; frame cancellation guarded where no animation frames exist |

Outside `map/`: `navigation.tsx` (`useSearch`, path-and-query deduplication, server snapshots, `RouteBase` and
`withBase` for the fixture), `router.ts` (`invocation` route and trail), `Page.tsx` (map levels and invocation header
in ordinary and archive branches; the archive branch still resolves before any `ProjectWorkspace`), `Shell.tsx`
(`archiveTrail`), `pages/Archive.tsx` (archive home = map L0 + run-id entry), `ui.tsx` (`Status` on the six classes,
`StatusIcon`, `MapStatusBadge`), `status-class.ts` and `status-classes.json` (T020's run/attempt/phase tables),
`styles.css` (status classes, map page, overlays, inspector and bottom sheet), `i18n/en.json` and `es.json`
(228 keys added to each, none changed or removed: map texts and three run status labels), `map/fixture/text.ts` (13 fixture keys each), and
`tests/product/test_frontend_status_parity.py`.

## 2. Behaviour against the contract

- **Levels and fields (T018 §3).** L0 cards: name, derived class, manual/autonomous badge, circles, phases
  closed/total, error mark, aggregated bubble count; inspector: open phase, autonomous run status, reason and bounds,
  configured agents per role (`absent` in archives), active invocations, last activity, errors, identities. L1:
  code, title, status, Plan · Check · Close slots with the actors that took part, tasks committed/total, roadmap order;
  inspector: objective, criteria and coverage, READY, last check, slot history and actor links. L2: latest-run status,
  attempt n / revision limit (or "No runs"), `depends_on` and dashed `replaces`; inspector: problem and expected
  result with source, runs, stage, revision rounds, cycles, acceptance (`absent`/`rejected`/`eligible`, never a
  commit) and commit. L3: invocations and Harness format/validate/commit in T020's order, latest run by default and a
  paged run selector; inspector: frozen identity, requested and reported model (separate, with provenance), harness
  attempt, revision round, native turns, tool calls by name, denials, usage presence, missing signals, deliveries,
  discovery loads, rulings, permission requests and the observed-step state. Counters without evidence read
  "not observed (reason)", never zero.
- **Navigation (§4).** The map is the home page; `?view=list` shows the existing page with every control; the
  remembered choice applies without the parameter; Back/Forward replay toggles and levels; `/projects/:p` stays the
  project page and a project card enters its phases; breadcrumbs are unchanged; `…/check` stays an operational page.
  T021's keyboard, focus, zoom-enter, gesture guard and reduced motion are unchanged.
- **Actors and requests (§5.3).** R/E/J/H come from T020 (J only with a judge profile or judge history), rays mark
  every active circle and the chat lane shows "chat" on R beside the task lane. Bubbles carry T017 identities; the
  conversation re-reads the item and only T017's typed controls exist (no free composer for executor or judge).
  Circles, bubbles, the details control and the run selector never trigger the card's navigation.
- **Refresh (§8).** See D314. Reads stay bounded: first pages at T020's caps, later pages and earlier runs on demand,
  inbox fallback in pages of 30.
- **Archives.** Map L0–L3, their table alternative, the run-id entry and the invocation header read SQLite
  projections only; no poller, announcer, action, talk button or registry/checkout/configuration read; requests are
  read-only; operational pages stay blocked.
- **Status (§5.1).** The shared `Status` uses the six classes plus `unknown` with icon, translated text and raw code;
  lists' in-progress tone is now orange and owner-waiting violet. Inactive chips use the card surface with an outline
  (the muted text on the soft neutral background measured 4.49:1, below 4.5); every pair is ≥ 4.5:1 in both themes
  (light: done 5.37, progress 4.55, waiting 5.82, failed 5.66, pending 5.78, inactive 5.41; dark: 7.23, 7.01, 7.03,
  6.52, 7.36, 6.63).

## 3. Tests

Synthetic only. `map/fixture/projections.ts` produces responses typed by the generated `Map*` client types for one
deep path (`atlas` → `P002` → `P002-T005` → its latest run) with leaf siblings: every class each level can project,
absent telemetry (no capture, Codex without reported model or denials, steps not projected), run permissions and
task questions attributed to E and R, unattributed phase questions on H, a judge step, a chat invocation running beside
the executor, versions that advance on demand, cursors that go stale, and a `budget` scenario at T018 §12's sizes
(25 projects, 40 phases, 80 tasks, 30 runs, 40 steps, 300 open requests).

| Suite | Shows |
|---|---|
| `frontend/tests/work-map.test.mjs` (21) | `?view` parsing, remembered choice, storage failure fallback, history entries and path+query deduplication; invocation route round trip and non-map check route; archive trail; shared `Status` per class in en/es with icon, text and raw code; status table parity with the list merge; adapters at L0–L3 (classes, "not observed", two concurrent actors, J rule, edge direction, all classes at L2, route project per mode); loader (single flight, queued reload, paging, `cursor_stale` recovery, page bound, no late answer, 404); poller (intervals, hidden pause and resume, no overlap, superseded scopes, clean stop, archive stop, changed/vanished scopes); announcer (first snapshot, new elements, 10 s throttle, accumulation, dispose); rendered levels (labelled nodes, one tab stop, overlays out of the tab order, map reads only); L3 latest run, paged selector and selector navigation; inspector fields of executor and Codex steps; circle → invocation without card navigation, Back, bubble → panel without navigation, identity-only item read, T017 confirmation without free composer; a changed request re-read showing its current state with nothing sent; L0 aggregate and truncated lists via bounded inbox pages; polling reload only on version change and first page only, timers cleared on unmount; archive map with no timer, poll, action or operational read; home map default and toggle; Spanish texts; live-region announcement after a version change; `?view=list` mounts the existing page without map reads; invocation header in ordinary and archive modes |
| `frontend/tests/work-map-budget.test.mjs` (1) | 80-node L2 first render from T020-shaped data, cold shape cache, plain React server render (§4) |
| `frontend/tests/archive.test.mjs` (updated, 18) | See §8 |
| Existing map suites (T021) | Unchanged and passing with the extended engine: `map-engine`, `map-view`, `map-navigation`, `map-assets` (fixture text parity now includes the new fixture keys) |
| `tests/product/test_frontend_status_parity.py` (4) | `status-classes.json` equals `wm.STATUS` for run, attempt and phase; every persisted value of those vocabularies (T020's `vocabularies()` over the real writers) has a class; run and attempt never disagree on a shared code; every mapped code has an en/es label. A temporary removal of `REFUSED` from the JSON made two of the four fail; restored |

Focused runs during implementation: `node --test frontend/tests/work-map.test.mjs frontend/tests/work-map-budget.test.mjs`
(21 + 1 passed), the whole Node suite (`node --test frontend/tests/*.test.mjs`, all passing before closure),
`npx tsc --noEmit` clean, and `scripts/check tests/product/test_frontend_status_parity.py` (4 passed). Closing checks:
§5.

## 4. Measurements

| Measurement | Medium | Result | Budget |
|---|---|---|---|
| First L2 render, 80 nodes from T020-shaped data (adapter, layered layout, rough.js shapes with an empty cache, React markup) | Node 24 server render, plain React, Apple M5 development machine, 15 samples | focused runs: first 61–62 ms, median 20.1–20.6 ms, p90 43–45 ms; closing run (inside `scripts/check --frontend`): first 91.2 ms, median 25.8 ms, p90 60.7 ms | ≤ 500 ms (D309) ✓ as a server render |
| First L2 render in a browser, product map | Browser | **Not measured**: starting Vite or `scripts/dev` is not authorized for T022 | ≤ 500 ms; pending (§7) |
| Pan and zoom at 200 visible nodes | Browser | Not re-measured; T022 adds overlay groups per card | ≥ 50 fps; pending (§7) |
| Historical (T021, synthetic engine cards, corrected code) | Built-in Chromium | median 71.6 ms (80 nodes), 60 fps (200 nodes) | Evidence of T021 only, not of the product map |

The server render excludes style, layout and paint, so it is not equivalent to a browser first render and does not
discharge D309's browser measurement for the product map; it shows that the data path and markup add little to it.

## 5. Closing checks

`scripts/check --frontend`, run **once** on the final product source (2026-11-06):

| Suite | Result |
|---|---|
| unittest | 10 ran, ok |
| `alembic check` | ok, no new upgrade operations (no schema change) |
| pytest (parallel) | **3,238 passed, 3 skipped**, 29 subtests; the one warning is the known wheel duplicate-name notice of the deliberately corrupting packaging case. Includes the 4 new parity tests; no socket-restricted failures this time |
| Node | **357 tests, 357 passed** (includes the 21 + 1 new T022 tests and the updated archive suite) |
| Build | `tsc` and Vite build ok |

Bundle (from that build): `dist/` totals 4,771,888 B, +104,395 B over T021's recorded 4,667,493 B. The entry chunk
`index-*.js` is 605,676 B (163.96 kB gzip) and the CSS 48,157 B. Because the map is now the home page, the engine and
rough.js load with the entry chunk: the separate `rough.esm` chunk T021 recorded no longer exists (mermaid's lazy
chunks import it from the entry). The previous entry-chunk size was not recorded, so its own delta is not stated;
splitting the map into a lazy chunk is a reversible option for review.

`scripts/check-docs`: 0 errors on the tracked Markdown files and, given explicitly, on this untracked record and every
edited document (the script lists tracked files only). `git diff --check` is clean, and the new files have no
trailing whitespace. Nothing was committed.

## 6. Limitations, findings and pending verification

- **Pending, not performed:** independent technical review; the owner's visual review in light/dark,
  desktop/mobile and en/es (T022's own and T021's deferred one, §7); browser measurements of the product map (first
  render and pan/zoom); real assistive-technology testing; other browsers; real touch hardware.
- **Not exercised against the real service:** every map, inbox and invocation read in tests is answered by the
  synthetic projection; T020's real responses are verified by T020's own suite, and this task's fixture is typed by
  the generated client. No service, harness, agent, provider or network was used.
- **Reversible choices to confirm in review:** circles are drawn deeper than L0 only where work happens or waits
  (the inspector always lists them); the details control and circle request badges are pointer targets with keyboard
  equivalents in the inspector; the inbox fallback filters each 30-item page client-side to the element, so a page
  can show fewer items than the inbox holds for it (the panel links to the full project inbox); the run selector
  pages 50 runs at a time.
- **Ordinary-mode identity:** a card of a project without a configured id (knowledge-only or run-only) enters the
  map by its key; its list pages, which need a configured project, show their usual missing state.
- **Mobile readability** (carried from T021 §10): a fitted large level on a phone is small; the inspector bottom
  sheet and pinch zoom are the reading aids. Part of the owner's review.
- **Other list vocabularies:** the shared `Status` also shows job, operation and accounting outcome values through
  `kind="run"`. Values outside T020's run and attempt tables now render as `unknown` with their raw code and the
  question-mark icon (before, the raw code in the neutral tone); no class is guessed for them.
- **Invocation header:** `/projects/:p/invocations/:i` shows only T020's existing header read; the trace graph,
  related records and lazy history are T023, not delivered here.

## 7. Owner visual review (pending; carries T021's deferred review, D313)

Nothing here was performed. The review needs a local browser and a service start that this task was not authorized
to do. Two complementary routes:

**A. Product map on synthetic T020 projections (reproducible, no database).** Start only the frontend development
server (`npm --prefix frontend run dev`, 127.0.0.1:5173) and open <http://127.0.0.1:5173/__map-fixture/>. Choose
*Data → Product map on synthetic T020 projections (T022)*. Selectors: *Scenario* (`review`: every state, chat beside
the task, requests; `budget`: D309 maxima), *Archive* (ordinary / read-only), *Language*, *Theme*. *Simulate a change*
advances every version; *Settle the running work* finishes the deep run. Every action button answers "Synthetic
fixture: actions are not applied." Motion follows the system setting (or the browser's emulation).

**B. Product map on the real API (`scripts/dev`).** Shows whatever the development database holds; use it to confirm
the wiring against the real service.

Checklist (both routes where applicable):

1. **Themes (light/dark) and contrast:** cards, status colours with icons and text, edges, focus ring, circles,
   rays, bubbles, error marks, slots, inspector and list `Status` chips (orange progress, violet waiting, outlined
   inactive) at L0, L1 (`atlas`), L2 (`P002`) and L3 (`P002-T005`).
2. **Desktop and mobile (375 px):** inspector as side panel and as bottom sheet (Show/Hide details); readability of
   fitted levels; drag, wheel, trackpad pinch and, on a touch device, two-finger pinch.
3. **English and Spanish:** card counters ("Phases 1/40", "Attempt 2/3", "No runs", "not observed"), inspector
   labels, request panel, run selector, toggle.
4. **Navigation:** click and Enter enter; zoom far in enters; Escape, "Up one level", breadcrumbs, Back/Forward;
   a drag that starts on a card does not open it; the Map/List toggle, reload with `?view=list` and a direct link
   without it (remembered choice).
5. **Circles and bubbles:** the executor and the chat-lane reviewer both lit on `atlas`, `P002` and `P002-T005`;
   clicking a circle opens its invocation header and never the card; bubbles and circle badges open the requests
   over the map; a single request opens directly; the `budget` L0 bubble (300) lists inbox pages; *Settle the running
   work* then shows the permission resolved instead of a stale action.
6. **Refresh and announcements:** *Simulate a change* is picked up within about 2 s while work is active (10 s when
   idle), the tab hidden pauses it, and a screen reader hears one summary at most every 10 s.
7. **Archive:** read-only map and table, run-id entry, read-only requests, no polling; operational pages blocked.
8. **Keyboard and reduced motion (T021):** Tab into the map, arrows, Shift+arrows, + / − / 0, Home / End, Tab to
   the toolbar and inspector; reduced motion makes transitions immediate and rays static.
9. **T021's deferred items:** the engine-card fixture (*Data → Engine cards*) checklist in
   [T021 §5](P002-T021-rendering-foundation.md#5-synthetic-fixture-and-owner-visual-review), including the stress
   scenario and its two measurement buttons.
10. **Measurements to record (browser):** with *Scenario → Budget*, L2 `P002` first render (route change to the
    second animation frame; the engine fixture's *Redraw* button measures the engine path) and the pan/zoom benchmark
    at 200 visible nodes on *Data → Engine cards → Stress*.

Added for the review corrections (§9; same routes, nothing performed):

11. **First run:** open `P002` → `P002-T004` ("This task has no runs yet."), press *Start the first run of
    P002-T004* and confirm the run's steps appear within about 2–10 s without navigating or reloading.
12. **Concurrent R lanes:** *Task reviewer beside the chat → On*; on `atlas`, `P002` and `P002-T005` two lit R
    circles (one labelled "chat") open different invocations; at L3 (`P002-T005`, *Off*) the chat is a separate lane
    node with no sequence edge; reduced motion keeps every ray static.
13. **Request lists:** with *Scenario → Budget*, the L0 E circle badge lists only "Task permission request" items
    (75, *Load more* after 50); the running executor step's bubble lists its own permissions.
14. **Archive table and evidence:** *Archive → Read-only*, list view of `P002-T005`: each row's *Details of …* fills
    the inspector, actor links open invocations, request buttons open read-only lists. On route B (the fixture has
    no run page), "Run evidence" opens the run page with the map remembered, a reload of that link keeps it, and
    breadcrumbs still enter the map.

## 8. Existing tests changed by the contract

- `archive.test.mjs`: the archive home now reads the map projection (T018 Q5, D304), so "no request" became "map
  projection reads only"; the run route under `/projects/…` is a map route in archives and moved from the blocked
  list to a new test of L1–L3 archive levels (map reads only, no workspace, pending read, timer or action), replaced
  in the blocked list by `…/phases/P001/check`; the supervisor-signal test keeps the supervisor read first and allows
  only map reads after it, still with no timer; the ordinary run-page test opens `?view=list` (the run page is the
  list view now) with every original assertion; the run-id entry test asserts the submission itself makes no request.
- No other existing test changed. The T021 engine suites pass unchanged on the extended `MapView`.

## 9. Independent technical review and corrections (2026-11-06)

Sections 1–8 are the first closure and stay as recorded; where this section supersedes a behaviour, the corrected
behaviour is in D314 and the current flows. The review repeated the 22 new Node tests, 85 regression tests, the four
Python parity tests, the documentation checks and `git diff --check` successfully, and found seven functional defects;
integration was not approved. The corrections were made on the same uncommitted branch, keeping every existing file.
The review's own results are the reviewer's; nothing below is an independent or visual approval.

### 9.1 Defects and corrections

| # | Defect found | Correction |
|---|---|---|
| 1 | A task without runs started no poll (activity depended on the steps head), so a first run was never discovered; a failed first read could not be retried and poll failures were silenced (`useActivity` did not connect `ActivityPoller`'s failure callback) | The poll follows every scope known in view, the run selector's included; a changed selector rereads it and the first run's steps load in place. A failed first read shows the error with "Read again"; a failed poll shows "may be out of date" until a read succeeds (one timer, retried at 10 s). Archives still poll nothing |
| 2 | The inbox fallback dropped `target.role` and filtered only by project/phase/task/run, so the L0 E bubble listed R clarifications and a truncated step list could include other invocations of the run | The panel reads the new element request list (§9.3) with the element's exact scope (L0 none, L1 phase, L2 phase and task, a step its run and attempt) and the circle, on every page; the listed identities are used only when complete. T017 stays the authority: `InboxConversation` re-reads by identity with its version and confirmation controls |
| 3 | The archive table could not select rows or open their requests or invocations; L3 rows were plain text | Each row has a "Details of …" button (fills the inspector, steps included, `aria-pressed`, the row marked `aria-current`), links to each actor's invocation and buttons for the element's and each circle's requests; still no workspace, action, write or timer |
| 4 | `actorsOf` reduced each circle to one actor, hiding a task reviewer behind a concurrent chat on R; L3 never showed the chat | One actor per active invocation from T020's `active_invocations`, each with its persisted invocation as target and its chat flag (the request count on the first); H stays one actor and J follows T020. At L3 an active chat attached to the run shown (activity `chat` and `scope.run_id`) is its own lane node with no sequence edge, and its inspector lists the invocation. The engine keys and seeds repeated roles separately (`R#2`) |
| 5 | `canLoadMore` was false after five pages even with a `next_cursor`, cutting the history silently | A window of five held pages: loading past it drops the oldest pages, counts them ("N earlier pages are not held here", "Back to the first page") and keeps the first page apart for head fields (latest run). `cursor_stale` returns to the first page past the threshold too |
| 6 | "Run evidence" pointed to the run route without its view, so with the map remembered it returned to the map (the L3 summary pointed to the current path) | `EvidenceLink`: the run page with `?view=list` in ordinary mode (the short `/runs/:id` and the run page's canonical correction keep the query), the run consultation `/runs/:id` in archives. A parameter no longer becomes the remembered choice, so cards and breadcrumbs keep entering the map |
| 7 | `rememberedView` preferred an old stored value after a failed write of a new choice | The choice made in this page wins over the stored one; the explicit parameter still wins over both |

### 9.2 Files

Changed by the corrections: `frontend/src/map/WorkMap.tsx`, `loader.ts`, new `use-level.ts` (the `useLevel` hook
moved out of `WorkMap.tsx` and shared with the requests panel), `projection.ts`, `Requests.tsx`, `Inspector.tsx`
(chat-lane inspector, `EvidenceLink`), `InvocationPage.tsx`, `view-mode.ts`, `api.ts`, `MapView.tsx` and `labels.ts`
(repeated roles), `fixture/projections.ts` (item scopes, the request list, `startRun`, the `reviewer` option),
`fixture/ProductFixture.tsx` and `fixture/text.ts` (two controls, four fixture keys each), `frontend/src/pages/Run.tsx`
(query kept by `RunRedirect` and the canonical correction), `styles.css`, `i18n/en.json` and `es.json` (11 keys added
to each; `map.table.steps_hint` and `map.requests.none_listed` reworded in both), and on the backend
`src/my_harness/core/engine/work_map.py`, `storage/work_map.py`, `api/schemas.py`, `api/work_map.py`, with
`frontend/openapi.json` and `frontend/src/api.generated.ts` regenerated by `scripts/export_openapi.py` and
`npm --prefix frontend run generate:types`.

### 9.3 Contract change: element request list

The existing reads could not keep the actor: T017's inbox items carry no circle or attempt, and the projections list
at most 20 identities. Under the owner's authorization for the minimal extension, `GET
/api/managed/map/projects/{p}/bubbles` (`map_bubbles`, `MapBubblesRead`) returns T020's own attributed set (the
`_bubbles` list every counter is computed from, never re-attributed) filtered exactly by `phase`, `task`, `run`,
`attempt` and optionally `circle`: items (id, kind, topic, circle, attribution, phase, task, run), the counts of the
whole filtered set, 50 per page keyset by item id (`LIMITS['bubbles']`). Its scope token encodes the filters (`=value`
or `~`, so a filter is at most 199 characters), its version digests the filtered ids: a cursor is bound to project and
filters (422 otherwise) and a changed set answers `409 cursor_stale`; another circle's list is not superseded. The
activity poll accepts the scope. Project isolation is the root of every map read (unknown project 404, foreign project
empty, cursor of another project refused); archives read it from SQLite with identical results. No schema, persistence,
authorization or dependency change; DDBB diagram unchanged. OpenAPI and the generated client are updated in this task.

### 9.4 Regressions

Each new test fails on the original behaviour: a mutation run re-introduced each defect alone (the original line of
code restored in place, then reverted) and every one was detected by its test (10 of 10 mutations: two for defects 1, 2
and 4, one each for 3, 5, 6 and 7).

| Test | Defect | Shows |
|---|---|---|
| `a task without runs keeps following its run selector…` (Node) | 1 | Connected `WorkMap`: "no runs" with one poll timer on the selector scope; `startRun` → one selector reread, one steps read, the step drawn, no navigation, one timer, then one aggregated read of both scopes; no timer after unmount |
| `a failed first read can be retried…` (Node) | 1 | 503 on the first level read: error and "Read again", no timer; retry → one more read, nodes, one timer; poll failure → "may be out of date", one timer at 10 s; recovery clears it with no duplicate poll, timer or level read |
| `a circle request bubble keeps its own actor on every page…` (Node) | 2 | Budget L0 E badge: 75 counted, 50 + 25 listed after *Load more*, all E permissions, `circle=E` on both pages; L3 running step: `run` and `attempt` filters, only its own permissions |
| `L0 aggregates and truncated lists read the element list…` (updated) | 2 | L0 aggregate reads the project list unscoped (50 per page, no inbox page); a truncated L2 node reads `phase` and `task` and replaces the 20 identities instead of adding to them |
| `the archive table reaches every step's details…` (Node) | 3 | Archive L3 table, no SVG: one Details control per row, invocation links for every actor, the inspector filled for a step, the step's requests read-only; no timer, GET map/inbox reads only |
| `concurrent invocations stay separate circles…` (Node) | 4 | Reviewer + chat: two R actors with their own targets (L0 and L2), one J, one H, requests on one actor; drawn hrefs to both invocations and the chat label; L3: no chat before the activity read, then its own lane node opening the chat invocation, no sequence edge, no extra step, its inspector; another run shows none |
| `the loader window keeps memory bounded…` (Node) | 5 | Default `MAX_PAGES`: seven further pages reached, five held, three counted, the first kept, a cursor still usable; `cursor_stale` past the threshold → first page at once, then reread at the new version. The first-closure loader test now checks the window instead of the cap |
| `evidence links open the run page…` (Node) | 6 | Remembered map: the summary link is `…/runs/:run?view=list`, following it mounts the list page and its run read, the stored choice stays `map`; a reload of the link mounts the list; the invocation header links there (ordinary) and to `/runs/:run` (archive); `/runs/:id?view=list` resolves keeping the query |
| `a stored choice never overrides the last choice of this page…` (Node) | 7 | Storage that reads `map` and throws on write: `rememberView('list')` → `viewOf('')` is `list`; `?view=map` still wins |
| `test_element_requests_keep_exact_circle_and_scope_on_every_page_isolated_and_archived` (pytest) | 2 | Real writers plus synthetic in-flight executor and reviewer attempts with five pending permissions: complete disjoint keyset pages; per-circle and per-attempt sets equal the card, node and step counters; filters and limits validated; unknown and foreign projects; cursors bound to filters and project; activity version and `409 cursor_stale` on a new item (another circle unaffected); nothing written by reads; secrets absent; identical in a restored query-only archive |

Focused runs while correcting: `scripts/check tests/product/test_work_map.py tests/product/test_storage_api.py`
(30 passed, 1 skipped; includes OpenAPI parity), `node --test` over the work-map, archive, map-engine and budget suites
(102 passed), and `npx tsc --noEmit` clean.

### 9.5 Closing checks of the corrections

`scripts/check --frontend`, run **once** on the corrected source (2026-11-06):

| Suite | Result |
|---|---|
| unittest | 10 ran, ok |
| `alembic check` | ok, no new upgrade operations (no schema change) |
| pytest (parallel) | **3,239 passed, 3 skipped**, 29 subtests (one more than the first closure: the new request-list test); the one warning is the known wheel duplicate-name notice |
| Node | **365 tests, 364 passed, 1 failed**: `map-view.test.mjs` requires every fixture text to differ between English and Spanish, and the new `fixture.reviewer.off` was "No" in both |
| Build | `tsc` and Vite build ok |

The failure was corrected after that run (English `Off`/`On` for the fixture selector; text values only) and the
whole Node suite was rerun alone: `node --test frontend/tests/*.test.mjs`, **365 passed**. The wrapper was not run a
second time; its other suites cover source that did not change afterwards, and TypeScript is unaffected by the two
string values.

Bundle (from that build): `dist/` totals 4,777,909 B (+6,021 B over the first closure's 4,771,888 B); the entry chunk
`index-*.js` is 610,166 B (163.76 kB gzip; +4,490 B) and the CSS 48,330 B (+173 B). No bundle optimization was
attempted (out of scope).

`scripts/check-docs` (127 tracked Markdown files, 0 errors), `scripts/check-docs docs/phase/P002-T022-work-map.md`
for this untracked record (0 errors) and `git diff --check` (clean; the untracked files have no trailing whitespace).
Nothing was committed.

### 9.6 Still pending, not performed

- Independent technical re-review of the corrected diff.
- The owner's visual review in the browser (T022's own and T021's deferred one, D313), with the scenarios of §7
  (items 11–14 added for the corrections), and the browser measurements (first L2 render, pan/zoom at 200 visible
  nodes). They block integration. Nothing visual was checked here.
- The element request list is exercised against the real service only by its pytest; the panel's tests use the
  synthetic fixture. No service, `scripts/dev`, harness, agent, provider or network was used.
- Integration, release 0.2.0, distribution/publication and installation.

## 10. Independent re-review and second corrections (2026-11-06)

Section 9 is the first round of corrections and stays as recorded (its figures and results are historical). The
independent re-review of that diff repeated 115 focused Node tests and 31 backend tests (work map and OpenAPI parity
included), both documentation checks and `git diff --check`, all successfully, and reproduced two remaining problems
related to defects 1 and 4 of §9.1. Integration was not approved. Both are corrected on the same uncommitted branch
from `develop` `4535804`, keeping every change and untracked file; the first round's corrections (exact actor and
scope of request lists, inspectable table, concurrent circles, page window, evidence links, view memory) are
unchanged. These results are the implementer's; nothing below is an independent or visual approval.

### 10.1 Problems and corrections

| # | Problem reproduced | Correction |
|---|---|---|
| 1 (defect 1) | After a valid empty run-selector read (`P002-T004`), a first run announced by activity and a selector reread answering `503 Synthetic outage`: `noRuns` stayed true and was evaluated before the error, and the outer notice required step pages, so the view kept "This task has no runs yet." with no error and no "Read again" | A failed reread over a snapshot still shown, including an empty run selector, shows the error ("Not updated: … The last read is shown.") and a mounted "Read again"; the empty read stays as possibly out of date. The retry reads the selector once and the first run's steps once, in place. Archives still poll nothing |
| 2 (defect 4) | L3's chat lane came only from `activity.active_invocations`: a response truncated at 50 invocations of other projects (`active_invocations_truncated: true`, ignored) dropped a chat still active, with no coverage notice; in archives there is no poll, so a persisted active chat of the run was never drawn | The run's steps read carries its own lane (§10.2): `chats`, the active chat invocations whose conversation is attached to the run, oldest first, at most 20, with `chats_truncated` (a hint says the list is cut). The client reads it from the steps head only, never from the global activity list; it is reread with the steps when their version changes, and an archive's single read shows it |

### 10.2 Read extension: the run's chat lane in the steps read

The owner authorized the minimal extension of the projection needed for the accepted contract (T018 §5 chat lane,
§§7–8 refresh and archive). `GET /api/managed/map/projects/{p}/runs/{run}/steps` (`MapStepsRead`) gains `chats`
(`MapActiveInvocation` items, the same shape and identities as activity's, with `project_id` the map key) and
`chats_truncated`. The source is T020's own `_active` read for the run's root, filtered to `chat` invocations whose
conversation's task run is this run (`scope.run_id`; the conversation's task run must share the root, so another
project's chat naming the run id never appears); its order is activity's (`started_at`, id). The list is the same on
every page and is part of the steps version (attempt id and process of every attached chat, not only the 20 listed),
so a chat that starts, changes process or ends changes the token the poll compares, and a cursor issued before is
`409 cursor_stale`. The activity poll computes the steps version from the active set it already read (no extra
query). Archives read it from SQLite with identical content and version. No schema, persistence, authorization or
dependency change; DDBB diagram unchanged; `frontend/openapi.json` and `frontend/src/api.generated.ts` regenerated
by `scripts/export_openapi.py` and `npm --prefix frontend run generate:types`.

### 10.3 Files

`src/my_harness/storage/work_map.py` (`_run_chats`, steps response and version, activity's steps version),
`src/my_harness/api/schemas.py` (`MapStepsRead.chats`, `chats_truncated`), `frontend/openapi.json`,
`frontend/src/api.generated.ts`, `frontend/src/map/WorkMap.tsx` (stale notice and retry over an empty selector;
chat lane from the steps head; coverage hint; the activity handler only clears the poll notice),
`frontend/src/map/fixture/projections.ts` (`chats` in the steps read, `endChat`), `frontend/src/i18n/en.json` and
`es.json` (`map.chat.truncated`, one key each), `tests/product/test_work_map.py`, `frontend/tests/work-map.test.mjs`,
`docs/DECISIONS.md` (D314), `docs/flows/work-map.md`, `docs/STATE.md`, `docs/NEXT_STEPS.md` and this record.

### 10.4 Regressions

| Test | Problem | Shows |
|---|---|---|
| `a failed run selector reread after a valid empty read is shown with a mounted "Read again"…` (Node) | 1 | Connected `WorkMap` on `P002-T004`: empty read with no retry rendered; `startRun` and a poll → one selector reread answering 503; the rendered HTML (not `host.elements`) has the stale notice with "Synthetic outage" and a `<button>Read again</button>`; retry → one selector read, one steps read, the first run drawn, notice and button gone, no navigation, one poll timer and no other timer; the next poll is one aggregated read with nothing reread. Archive: failed first read rendered with its retry, retry → "The archive records no run of this task.", no poll, no activity read, no timer, GET only |
| `L3 takes its chat lane from the run's steps read…` (Node) | 2 | Ordinary L3: the chat drawn from the first steps read; an activity response with 50 other-project chats (one naming the same run id) and `active_invocations_truncated` keeps it, draws none of them and rereads nothing; `endChat` → one steps reread and the lane is empty, steps kept, one timer, no navigation; another run of the task shows no chat; a cut list (20 listed, `chats_truncated`) shows the coverage hint and never draws a listed chat of another project or run |
| `an archive's L3 shows the persisted chat from its single steps read…` (Node) | 2 | Archive L3, map and table: the chat node (or row) and its invocation link from one steps read; no activity read, no poll or timer, GET map reads only |
| `test_l3_chat_lane_is_a_bounded_snapshot_of_the_runs_own_chats_versioned_isolated_and_archived` (pytest) | 2 | Real writers plus synthetic chats: a phase chat, a chat on another run, another project's chat naming the run and 50 earlier foreign invocations never reach the run's lane; the activity list is truncated and omits the chat while the steps read lists it; versions change on start (old cursor 409), process change and end, and the poll's version equals the shown one; the lane is identical on every page; 21 chats → 20 listed oldest first with `chats_truncated`; reads write nothing; a restored query-only archive (checkout removed) lists the same chat with the same version, polling disabled, file unchanged |
| `L3 shows the latest run by default…` (updated) | 2 | The latest run's 40 steps plus its chat lane node from the same read (previously the lane appeared only after an activity read) |
| `concurrent invocations stay separate circles…` (updated) | 2 | The chat lane is drawn before any activity read; its invocation link is checked in the rendered HTML |

Mutation check: restoring the original stale condition fails the first test; restoring the activity-sourced chats
fails the second and third; removing the chats from the steps version fails the pytest ("a chat that starts changes
the run version"). Each mutation was reverted.

Focused runs while correcting: `scripts/check tests/product/test_work_map.py tests/product/test_storage_api.py
tests/product/test_frontend_status_parity.py` (35 passed, 1 skipped; includes OpenAPI parity), `node --test` over the
work-map, budget, archive and map-* suites (105 passed) and `npx tsc --noEmit` clean.

### 10.5 Closing checks of the second corrections

`scripts/check --frontend`, run **once** on the final source (2026-11-06):

| Suite | Result |
|---|---|
| unittest | 10 ran, ok |
| `alembic check` | ok, no new upgrade operations (no schema change) |
| pytest (parallel) | **3,240 passed, 3 skipped**, 29 subtests (one more than §9.5: the new chat-lane test); the one warning is the known wheel duplicate-name notice |
| Node | **368 tests, 368 passed** (three more than §9.5: the new connected regressions) |
| Build | `tsc` and Vite build ok |

Bundle (from that build): `dist/` totals 4,778,177 B (+268 B over §9.5's 4,777,909 B); the entry chunk `index-*.js`
is 610,204 B (165.03 kB gzip; +38 B) and the CSS 48,330 B (unchanged). No bundle optimization was attempted.

`scripts/check-docs` (127 tracked Markdown files, 0 errors), `scripts/check-docs docs/phase/P002-T022-work-map.md`
for this untracked record (0 errors; rerun after this paragraph was written) and `git diff --check` (clean; the
untracked files have no trailing whitespace). Nothing was committed.

### 10.6 Still pending, not performed

- Independent technical re-review of this diff.
- The owner's visual review in the browser (T022's own and T021's deferred one, D313), with the scenarios of §7
  (item 15 added below), and the browser measurements (first L2 render, pan/zoom at 200 visible nodes). They block
  integration. Nothing visual was checked here.
- The chat lane and the request list are exercised against the real service only by their pytest; the Node tests and
  the fixture page use synthetic projections. No service, `scripts/dev`, harness, agent, provider or network was used.
- Integration, release 0.2.0, distribution/publication and installation.

Added to the §7 checklist (same routes, nothing performed):

15. **Chat lane and selector failure:** at L3 `P002-T005` the chat lane node is drawn on the first read, ordinary and
    *Archive → Read-only* (map and table); *Settle the running work* removes it within about 2–10 s. With the
    browser's network tools blocking the runs read after *Start the first run of P002-T004*, the stale notice and
    "Read again" appear under the run selector and the retry shows the first run.

## 11. Browser corrections after the synthetic frontend review (2026-11-07)

Sections 9 and 10 stay as recorded; their figures and results are historical. **Reviewer's results (not repeated
here):** the last functional re-review passed 118 Node and 36 backend tests with no functional finding pending. The
reviewer then opened the synthetic frontend (`/__map-fixture/`, product data, *Review* scenario) and found two
blocking browser defects; those functional results were neither visual acceptance nor authorization to integrate.
The owner then authorized starting **only** the frontend development server and reviewing the synthetic view (no API,
`scripts/dev`, harness, agents or providers). Both defects are corrected on the same uncommitted branch from `develop`
`4535804`, keeping every earlier change and untracked file. Everything below §11.1's first column is the implementer's
work; nothing here is an independent review or the owner's visual acceptance.

### 11.1 Findings and corrections

| # | Finding (reviewer's reproduction) | Cause | Correction |
|---|---|---|---|
| 1 | On `atlas` → `P002` the status and the counter overlapped: `Desconocido: MYSTERY` / `Intento 1/3` (P002-T007), `Te espera` / `Intentos: no observado` (P002-T009), the same with `Waiting for you` in English, at L1 and on L3 steps with `Duration: not observed`; zooming did not help | `MapView` drew both texts on the last line of the card (`height − 13`), status from the left and counter right-aligned, with no space reserved between them | Every card has five rows: code (with the L0 badge), two title lines, the **status** and the **counter** (both from `x = 14`, baselines `height − 29` and `height − 11`); all card heights are 128 (widths unchanged). Every label is fitted to its row by `text-fit.ts`, a per-character width table (the larger of Excalifont and the interface fallback font at 12–16 px, plus 2 % and 1 px for kerning) used identically by the server render and the browser, so the first frame and the frame after the font loads lay out the same lines; a line that does not fit is cut at a character with "…". The code row stops 26 px from the right edge (the details control), the badge keeps at most half of it, title lines stop 2 px short of the error mark, and slot labels and actors fit their third of the card. An unknown status whose "Unknown: CODE" does not fit shows **its raw code** beside the card's question-mark icon (T018 §5.1); the accessible name keeps the full status text and counter, the description the raw code, and the inspector every field |
| 2 | At 375 × 840 px on L2, after *Hide details* on P002-T007, Tab from *Show details* focused the run link with `aria-expanded="false"`; the closed sheet kept ≈ 403 px of scroll, the link was off screen and the heading out of view | The closed sheet was the whole aside clipped to `max-height: 3.4rem` with `overflow: hidden`: its body was still rendered, so its controls stayed in the Tab order and the accessibility tree, and focusing one scrolled the clipped aside | On narrow screens the closed sheet's body is `display: none` (out of the Tab order and the accessibility tree); open, the aside is a column whose **body** scrolls, so the heading and the *Show/Hide details* control never leave view; the heading is one line with an ellipsis while closed and up to three lines open, and the toggle keeps its size. The toggle names the body with `aria-controls`. Wide screens always show the body, whatever the mobile state. Found while verifying: narrowing the window with the focus in the inspector and the sheet closed dropped the focus to `<body>`; `sheet-focus.ts` now opens the sheet and keeps that focus (or restores it when the browser dropped it before reporting the media change), reveals it again after the 160 ms opening, and never takes the focus from a control outside the inspector |

No model, persistence, API, dependency or catalogue change: the corrections reuse existing texts (no new message).

### 11.2 Files

`frontend/src/map/MapView.tsx` (card rows, `CARD_FONT`, `CARD_ROWS`, `cardText`, fitted slots and badge),
`frontend/src/map/text-fit.ts` (new: width table), `frontend/src/map/labels.ts` (`wrapTitle` takes a character budget
or a width predicate; `fitLine`), `frontend/src/map/sheet-focus.ts` (new: `SHEET_MEDIA`, `keepSheetFocus`),
`frontend/src/map/WorkMap.tsx` (`aria-controls`, body ref, the focus hook), `frontend/src/styles.css` (bottom sheet),
`frontend/tests/work-map-layout.test.mjs` (new), `frontend/tests/work-map.test.mjs` (one test),
`frontend/tests/map-view.test.mjs` (one assertion, §11.3), `docs/DECISIONS.md` (D314), `docs/flows/work-map.md`,
`docs/STATE.md`, `docs/NEXT_STEPS.md` and this record.

### 11.3 Regressions

| Test | Finding | Shows |
|---|---|---|
| `status and counter have rows of their own and every label fits its card at L0–L3, review and budget, en/es` | 1 | Every card of L0–L3 built from the synthetic T020 reads (both scenarios, both languages): status and counter start at `x = 14`, the counter is not right-aligned and its baseline is ≥ 16 px below the status, ≥ 20 px between title and status, counter inside the card; status, counter, title, code (beside its badge) and slot labels fit their rows by the width table; a cut label is whole in the accessible name |
| `the reported overlaps are drawn on separate rows: P002-T007 and P002-T009 in Spanish and English` | 1 | The exact reported texts, unchanged and on separate rows; "not observed" stays visible |
| `long codes, counters, titles, badges and slots are cut to their row and stay whole in the accessible name` | 1 | Long project name beside a badge, uppercase title, long slot label and actors, long step code; the unknown status keeps the raw code first; full status text and counter in the name and raw code in the description |
| `line fitting: …` | 1 | The character-budget wrapping of T021 is unchanged; width predicates cut at the longest prefix that fits |
| `card font sizes and the sheet breakpoint equal styles.css; a closed sheet hides its body only on narrow screens` | 1, 2 | Font sizes of the card labels equal `CARD_FONT`; in the `(max-width: 880px)` block the closed body is `display: none`, only the body scrolls, the toggle keeps its size, the closed heading ellipsizes; outside it nothing hides the body |
| `narrowing the window keeps the focus in the inspector: …` and `narrowing never takes the focus from elsewhere, …` | 2 | `keepSheetFocus` with fakes: focus kept (no move) or restored after being dropped, revealed at once and after the transition, listeners removed on unmount; no action when widening, when the focus is elsewhere (also without a focus event), after a click on the page, or for a removed control |
| `the bottom-sheet toggle controls the inspector body it shows or hides, on the map and in the table` (connected `WorkMap`) | 2 | `aria-expanded="false"` and `aria-controls` naming the body's id, before the body in document order |
| `the six classes and unknown are drawn …` (T021, `map-view.test.mjs`, changed) | 1 | Now accepts the raw code with or without the translated prefix: the engine fixture's `Desconocido: X_FUTURE_STATE` (≈ 247 px) is wider than any card row and overflowed the card before; the raw code stays visible |

Mutation check (each reverted): the counter back on the status line right-aligned, the status not fitted, the closed
body not hidden, the dropped focus not restored, and the focus taken from a control outside the inspector each make
the new tests fail. Focused runs while correcting: the work-map, layout, budget, archive, map-engine, map-view,
map-navigation, map-assets and router suites (**128 passed**) and `npx tsc --noEmit` clean.

### 11.4 Browser evidence (implementer)

**Environment.** Claude desktop app's built-in browser (Chromium 152.0.7977.167, 60 Hz; device pixel ratio 2, 10
logical cores reported), macOS on the Apple M5 development machine; Vite 8.3.4 **development** server on
127.0.0.1:5173 (React development build, so timings are conservative). The server left open earlier was not running;
it was started with `npm --prefix frontend run dev` as authorized. Fixture only: every `/api/managed/…` read is
answered by the page from synthetic T020 projections (60 ms synthetic latency per read); no API, service, agent or
provider. Page scripts only read and timestamp; no product or fixture code was added for the measurements.

**Card geometry (finding 1).** In the page, after `document.fonts.ready` and with Excalifont reported loaded, each
label's box was taken with `getBBox`/`getCTM` in card-local SVG units, with the camera transform set to scale 1 for the
measurement and restored (at a fitted 6 % zoom Chromium reports inflated text boxes, 24.6 px for 14–16 px labels, a
measuring artifact). Checked: every pair of labels of a card, labels inside the card (2 px inset), labels against the
error mark, details control, bubbles, circles and chat label, and slots and overlays against every other card.
Before the correction, *Review*/English L2 had 3 overlaps (P002-T002, P002-T007, P002-T009). The check was validated
by moving the counter back onto the status line in the DOM: 20 overlaps in *Review*/Spanish L2, then 0 when restored.

| Data (L0, L1 `atlas`, L2 `P002`, L3 `P002-T005`; *Review* ordinary also every L3 `P002-T001`…`T012`) | en | es |
|---|---|---|
| Product, *Review*, ordinary / read-only archive | 0 / 0 issues (49 / 39 cards) | 0 / 0 (49 / 39) |
| Product, *Budget*, ordinary / read-only archive | 0 / 0 (186 / 186 cards, 1,080 labels) | 0 / 0 (186 / 186, 1,081) |
| Engine cards, *Normal* / *Budget* / *Stress* (200 cards at L2) | 0 / 0 / 0 (39 / 185 / 305 cards) | 0 / 0 / 0 |
| Labels forced to the fallback font (before Excalifont loads): product *Budget* es, *Review* en, engine *Stress* | 0 | 0 |

The width table was checked against canvas measurements in the same browser: 200,040 combinations (10,008 strings of
the card alphabet including accented letters, "¿", "¡" and "…", at 12–16 px, in Excalifont and the fallback font):
none drawn wider than its estimate (mean drawn/estimated 0.83). Screenshots (light, Spanish: P002-T007 and P002-T009
at 86 % zoom; dark, English: the same cards and L1 slots) show status and counter on separate rows.

**Inspector (finding 2)**, with real keyboard and mouse events:

- 375 × 840 px (phone emulation), L2, P002-T007 selected: open, the body scrolled to its end (880 px) and the heading
  and *Hide details* stayed in view. A real click on *Hide details*: `aria-expanded="false"`, body `display: none`,
  aside scroll 0, height 54 px, focus on *Show details*; a real Tab left the inspector (to the next control of the page),
  never the run link; the run link could not be focused even from script and `checkVisibility()` was false. Enter on
  *Show details* reopened it and Tab, Tab, Tab, Shift+Tab walked the run link and both actor links, each inside the
  visible body and the viewport, with the toggle always in view and the selection kept.
- The same at 375 px for the **requests panel** (bubble of P002-T005; closed and reopened with real clicks, the panel
  kept) and the **archive table** (*Archive → Read-only*, list view of P002-T005: Enter on *Details of Executor #1*
  opened the sheet; Enter on *Hide details* closed it; Tab left the inspector, Shift+Tab ×2 reached the table's last
  *Details* button, never the hidden body).
- Desktop ↔ narrow: at 1280 px with the mobile state closed the inspector body was shown (sticky side panel) with
  P002-T007 kept; back to 800 px it was the closed sheet again with the same selection. Narrowing with the focus on an
  inspector link opened the sheet and kept the focus on that link, visible in the body (after the fix; before it the
  focus fell to `<body>`); narrowing with the focus outside the inspector left the sheet closed and the focus where
  it was.
- Reduced motion: the tools cannot emulate `prefers-reduced-motion`; its CSS branch (no sheet transition) was
  simulated by overriding the transition: closing, reopening and the narrowing case behaved the same two frames later.

**Measurements (D309).**

| Measurement | Method | Samples | Result | Budget |
|---|---|---|---|---|
| First L2 render of the product map, 80 tasks (*Budget*, English, 1280 × 900 px), empty shape cache | From L1 `atlas` (40 cards settled), a page script records the time, changes the route through the History API and `popstate` (the router's own path), checks every animation frame until the 80 cards of `P002` are in the DOM, and stops at the next frame (the second frame with the map: React render, layout, rough.js shapes, style, layout and paint). The page's reads were timestamped by wrapping the fixture's fetch | 15 cold + 5 warm; 60 Hz cadence probes 14.6–18.7 ms before and after | cold: **median 165.8 ms, p90 170.9 ms, max 171.6 ms** (all 157.7–171.6); the read answered at 67–74 ms (60 ms of it synthetic latency); cards first present in a frame at 141–155 ms. Warm cache: 141.6–154.9 ms | ≤ 500 ms ✓ |
| Engine pan/zoom, 200 visible cards (*Engine cards → Stress*, L2, map viewport 1248 × 612 px) | The fixture's existing *Run the pan and zoom benchmark (4 s)* | 3 runs; cadence probes before and after each | 240 frames each, **mean 60.0 fps**; 5th percentile **53.8, 56.5, 58.1 fps**; longest frame 18.8, 18.8, 18.7 ms; `visible: 200` each | ≥ 50 fps ✓ |
| Engine redraw, 200 cards, empty shape cache (reference, not the budget) | The fixture's *Redraw with an empty shape cache* | 5 | 134.5–179.8 ms | — |

Reviewer's reference before these corrections (not repeated): 236 frames, mean 58.8 fps, 5th percentile 53.5 fps,
longest frame 50 ms; engine 200-card render 258 ms. These are the engine's numbers; the product first render above is
the connected map's.

Screenshots (local only, git-ignored): `.local/evidence/p002-t022-browser-corrections/` (L2 before the correction at
800 px; Spanish light and English dark cards; L1 slots; the 375 px sheet open, scrolled, reopened, the requests
panel open and closed; the 800 px narrowing case).

**Not verified here:** the owner's visual acceptance; real assistive technology (the tools read the DOM rather than
the browser's accessibility tree, so its absence is inferred from `display: none`, `checkVisibility()` and refused
focus); a real `prefers-reduced-motion` setting; Safari and Firefox; production bundle; real touch hardware; the 375
px case in the light theme (the 375 px screenshots used the system theme, which was dark).

### 11.5 Closing checks of the browser corrections

`scripts/check --frontend`, run **once** on the final source (2026-11-07):

| Suite | Result |
|---|---|
| unittest | 10 ran, ok |
| `alembic check` | ok, no new upgrade operations (no schema change) |
| pytest (parallel) | **3,240 passed, 3 skipped**, 29 subtests (as §10.5: no backend change); the one warning is the known wheel duplicate-name notice |
| Node | **376 tests, 376 passed** (eight more than §10.5: the seven layout and focus tests and the toggle test) |
| Build | `tsc` and Vite build ok |

Bundle (from that build): `dist/` totals 4,780,984 B (+2,807 B over §10.5's 4,778,177 B); the entry chunk
`index-*.js` is 612,555 B (166.06 kB gzip; +2,351 B, mostly the width table and the fitting) and the CSS 48,786 B
(+456 B).

`scripts/check-docs` (127 tracked Markdown files, 0 errors), `scripts/check-docs docs/phase/P002-T022-work-map.md` for
this untracked record (0 errors; rerun after this paragraph was written) and `git diff --check` (clean; the untracked
files have no trailing whitespace). Nothing was committed.

### 11.6 Still pending, not performed

- Independent technical re-review of this diff.
- The owner's visual review (T022's own and T021's deferred one, D313) with the §7 checklist (item 16 below). The
  implementer's browser checks in §11.4 do not replace it. It blocks integration.
- Integration into `develop`, release 0.2.0, distribution/publication and installation. Nothing was committed.

Added to the §7 checklist (route A):

16. **Card rows and the closed sheet:** on `P002` (*Review*, both languages and themes, zoomed in) every card shows
    the status and the counter on separate rows (P002-T007 `Desconocido: MYSTERY` / `Intento 1/3`, P002-T009
    `Te espera` / `Intentos: no observado`); at 375 px *Hide details* followed by Tab never focuses anything hidden,
    and *Show details* brings the same selection back with the heading and the control in view while scrolling.

## 12. Bounded label fitting and current inspector focus (2026-11-07)

On the §11 source, independent re-review passed 126 Node tests, the documentation checks and
`git diff --check`. Chromium confirmed the separated status and counter on P002-T007 and P002-T009 in English and
Spanish, the closed sheet's Tab order and retained selection at 375 px, and focus restoration on ordinary narrowing.
The independent engine run averaged 60.3 fps at 200 visible nodes. The earlier 80-task browser result in §11.4 is
implementer evidence.

### 12.1 Reproductions and corrections

- **Long titles.** Calling `cardText` at the task-card width with `"W".repeat(n)` took 62, 247, 982 and 3,839 ms
  for 4,000, 8,000, 16,000 and 32,000 characters respectively in re-review. The knowledge contract permits 65,536
  characters and the projection supplies the entire title. Repeated width scans of successively shorter prefixes
  caused the quadratic cost. Fitting now uses additive glyph advances, stops measuring when the row budget runs
  out, and consumes words only as needed to lay out the visible rows and detect overflow. Truncation reserves the
  ellipsis and retreats to a grapheme boundary. The card retains five rows, and the accessible name and inspector
  continue to use the full title.
- **Deferred inspector focus.** Focus the run link, deliver the narrow media change, focus the toolbar and dispatch
  its `focusin`, then drain the queued frame. Previously the frame returned focus to the link. Restoration now
  checks the current focus, panel identity and membership, connection and narrow layout at execution. Focus events,
  subsequent media changes and cleanup invalidate queued work. The transition reveal also requires the same visible,
  focused control. When hiding the inspector dropped focus to the document body, reopening still restores the link.

The focused layout regressions exercise a 65,536-character title through `cardText` with a deterministic cap of
twice the input length in glyph visits, verify that words beyond the visible rows are not measured, and check
surrogate pairs, combining marks and a joined emoji. The focus host separates resize delivery from the animation
frame and checks new focus, stale transition reveal, widening, panel replacement and cleanup. The legitimate
body-focus fallback remains covered. Scope is local label and focus behavior under D309/D314, with the delivery
route in the ownership table.

### 12.2 Browser evidence (implementer)

Headless Chrome 156.0.8078.75 on the development Mac, using the existing Vite process for this workspace.
Only the synthetic fixture was exercised. At 1280 × 900, *Product map → Review → P002*, the P002-T007 run link
was focused before resizing to 800 px. After the transition the sheet was expanded and the same link was
visible and focused. At 375 × 840, closing the sheet gave the body `display: none`; a Tab keypress skipped it,
and reopening still showed P002-T007.

| Browser measurement | Method | Result |
|---|---|---|
| Product L2, 80 tasks | *Budget*, English, 1280 × 900. From L1 with 40 cards settled, time the router's History API and `popstate` path through the frame after all 80 L2 cards first appear. Includes the fixture's synthetic read latency. Clear the shape cache before each of 15 cold samples, then take five warm samples. | Cold median **159.3 ms**, p90 168.0 ms, range 146.9–185.1 ms. Warm range 118.6–128.2 ms. Budget ≤ 500 ms. |
| Engine pan/zoom, 200 visible nodes | *Engine cards → Stress*, L2, 1280 × 900. Three runs of the fixture's four-second benchmark. | Mean **57.8 / 60.0 / 60.0 fps**; fifth percentile 59.5 / 59.9 / 59.9 fps; longest interval 66.6 / 16.8 / 16.8 ms; 200 visible in each run. Budget ≥ 50 fps. |

### 12.3 SSR and closing checks

The Node SSR test ran 15 samples for 80 tasks with a cold shape cache. In the closing Node suite it recorded
**181.8 ms first, 42.3 ms median, 129.1 ms p90 and 181.8 ms maximum**. This measures projection adaptation,
layout, shapes and static markup. Browser rendering is reported separately in §12.2. Two exploratory SSR runs
concurrent with pytest exceeded the existing first-sample limit; the closing Node suite ran after pytest and passed.

The initial focused selection passed 69 tests before the corrections. The single closing `scripts/check --frontend`
run passed unittest (10), Alembic, Node (380/380) and the TypeScript/Vite build. Its pytest result was **3,117 passed,
97 failed, 26 setup errors, 3 skipped and 29 subtests passed**, with the known wheel warning. The 123 failures and
errors were confined to `test_tool_bridge`, `test_judge`, `test_start_command` and `test_cli_diagnostics`, the four
socket-restricted files documented in T020. The full pytest report is preserved in
`.local/check/t022-bounded-full-pytest.log`.
Repeating those exact cases with local socket access and synthetic fixtures passed **123/123**. The full wrapper
was run once, and its original result remains recorded separately.

`scripts/check-docs` passed for 127 tracked Markdown files. The explicit check of this untracked record also passed.
`git diff --check` and the whitespace check of the untracked record were clean. The 23 untracked paths present
at the start were all retained. The branch remains at `4535804` with the local diff ready for independent re-review.

Independent re-review and owner visual acceptance, including T021's deferred acceptance (D313), remain pending.
Integration into `develop`, release 0.2.0, distribution and installation remain separate pending stages.
