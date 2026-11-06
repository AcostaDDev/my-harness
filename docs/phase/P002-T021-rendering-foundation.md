# P002-T021 — Hand-drawn map rendering foundation

**Status:** source complete; **independent final re-review passed and the owner accepted T021 on 2026-11-06** (§13).
All corrections are applied and re-verified in the browser on the corrected code (§12.7). The owner explicitly
deferred personal visual review until T022 connects the map to real data (D313); this is not a completed visual
review. Source commit and integration are authorized and pending. Decision for the choices
delegated to this task: [D312](../DECISIONS.md#d312--work-map-engine-interaction-conventions-and-development-fixture).

## Ownership and delivery

| Field | Value |
|---|---|
| Owner task | P002-T021 (frontend: dependency adoption and rendering engine); no gates pending (G14 resolved by T018) |
| Branch | `feat/p002-t021-map-rendering` from `develop` at `6ba19eb` (verified clean and equal to the local `origin/develop` on 2026-11-06; ONE_OFF_TASKS empty) |
| Contract | [T018 §§4, 5.1, 10–14](P002-T018-work-map-contract.md#10-rendering-dependency-decision-installation-in-t021), [visual direction](P002-T018-visual-direction.md) read through D303's numbering; D297, D303, D304, D308, D309; D242/D253 for delivery |
| Scope | rough.js 4.6.6 as a direct exact dependency; the two Excalifont v0.18.1 subsets with OFL 1.1 notice, packaged and served offline; orange/violet status tokens; in-house SVG engine (seeded shapes, layered layout, camera, zoom-enter through the existing router and history, keyboard, reduced motion); reproducible synthetic fixture |
| Out of scope | Wiring T020's projections, replacing Home, the map/list toggle, polling, functional circles and bubbles, migrating the shared list `Status`, navigable files, L4, the drawer and contextual chat (T022–T024); no model, migration, API, flow or version change |
| Authorizations (2026-11-06) | Network: only the two Excalifont files at tag v0.18.1 into the session scratchpad. Local server: a frontend-only Vite on 127.0.0.1 for the synthetic fixture and browser measurements, stopped afterwards. No commit, merge, push, publication, installation or harness/agent run |

| D242 stage | Status |
|---|---|
| Local source | Complete on the topic branch (uncommitted; the owner reviews the diff first) |
| Independent technical review and corrections | Final re-review passed on 2026-11-06, including every correction (§13) |
| Owner visual review in the browser | Explicitly deferred by the owner to T022's map with real data (D313); not performed |
| Integration into `develop` | Pending |
| Release 0.2.0 via protected `main` | Pending |
| Distribution/publication | Pending |
| Installation | Pending; recorded installation 0.1.9 |

## 1. Implementation

All engine code is in `frontend/src/map/`. Pure modules carry the behaviour and are tested in Node; the React view is
a thin SVG renderer over them.

| Module | Responsibility |
|---|---|
| `seed.ts` | FNV-1a seed in [1, 2³¹−1] from a stable identity (rough.js treats 0 as random) |
| `status.ts` | The six classes plus `unknown` (§5.1), their label keys and icon outlines; anything outside the contract is drawn as `unknown`, never guessed |
| `layout.ts` | Layered layout: canonical order (sort key, then id), DFS back-edge reversal, longest-path layers, dummy points on long edges, six barycentric sweeps, unconnected nodes packed in a grid below; plus a grid for L0 |
| `camera.ts` | Screen/world transforms, fit (≤ 1.25×), zoom range (half the fitted scale … 4×; the former absolute 0.05 floor is removed, §12.1), zoom about a point, pan clamp (96 px of content stay reachable), reveal, coverage |
| `controller.ts` | `MapController`: pointer drag and pinch, wheel and Safari gestures, keyboard, zoom-enter and zoom-out-leave thresholds, click suppression after a drag, navigation lock; page-wide `GestureGuard` (added in §12.2) |
| `shapes.ts` | rough.js **generator** only (no canvas, no DOM): card, edge with arrowhead, actor circle, rays, bubble and icons as path data, bounded cache (4,000) |
| `labels.ts` | Accessible names and descriptions; visible status text; two-line title wrapping |
| `routes.ts` | Levels and parents over the existing `Route`/`href`/`parse`; `mapNavigation`/`useMapNavigation` through the shared `navigate`; bounded per-path camera/focus memory |
| `motion.ts` | `prefers-reduced-motion` hook, 220 ms enter transition or none |
| `MapView.tsx` | SVG view: toolbar, help text, edges, nodes as SVG links (or labelled images when not enterable), roving tabindex, native wheel/gesture listeners, enter transition, focus restoration |
| `fonts/` | The two unmodified Excalifont subsets and `OFL-1.1.txt` |
| `fixture/` | Development-only synthetic fixture (§5): data, page, texts, measurements |

Outside `map/`: `styles.css` (tokens `--progress`/`--progress-soft`, `--waiting`/`--waiting-soft` in light and both
dark blocks; `@font-face`; `.map*` rules), `i18n/en.json` and `es.json` (37 `map.*` keys each), `Language.tsx`
(`I18nProvider fixed` pins a language without reading or writing preferences, used only by the fixture),
`vite.config.ts` (fixture route in the dev server, licence emission in the build), `map-fixture.html`, and
`NOTICE-THIRD-PARTY.md` (fonts section).

**Product wiring.** Nothing in the product imports the engine yet: T022 renders L0–L3 with T020's projections. The
production bundle therefore contains the tokens, `@font-face` rules, fonts, licence and catalogue strings, but not the
engine code (§8).

## 2. rough.js adoption (D308, T018 §10.1)

- `frontend/package.json` gains exactly `"roughjs": "4.6.6"`. The lock's root entry gains the same line **and**
  `"license": "MIT"`: the offline validation `npm install --offline --package-lock-only --ignore-scripts` (which
  reported "up to date") synchronized the root entry with the licence field `package.json` already declares. No
  package entry, version or integrity changed. *Corrected in the first re-review round: the first version of this
  record said only one line changed and the lock was otherwise untouched (§12.3).*
- `npm ls roughjs --offline`: `roughjs@4.6.6` at the root and `mermaid@11.17.2 → roughjs@4.6.6 deduped`. The lock entry
  keeps integrity `sha512-ZUz/69+…tRfvQ==` and the four MIT dependencies at hachure-fill 0.5.2, path-data-parser 0.1.0,
  points-on-curve 0.2.0 and points-on-path 0.2.1 (tested).
- The engine imports `roughjs` exactly as mermaid does, which resolves to `bundled/rough.esm.js`; the build emits one
  `rough.esm` chunk (27,109 B; 8,785 B gzip) imported by both mermaid's chunks and the engine (§8).
- The existing inventory line "Frontend lock SHA-256: `f7ce4d6e…`" in `NOTICE-THIRD-PARTY.md` already differed from the
  lock before this task (it dates from the 0.1.0 snapshot; the lock was `e1bf8ee7…` at `6ba19eb`). It was not
  regenerated here because the package set is unchanged; see §10.

## 3. Font adoption and packaging (D308, T018 §10.2)

**Download.** With the owner's authorization of 2026-11-06, exactly two files were fetched with `curl` into the
session scratchpad from `raw.githubusercontent.com/excalidraw/excalidraw/v0.18.1/packages/excalidraw/fonts/Excalifont/`.
No local copy existed. Both match the contract and were copied unmodified to `frontend/src/map/fonts/`:

| File | Bytes | SHA-256 |
|---|---|---|
| `Excalifont-Regular-a88b72a24fb54c9f94e3b5fdaa7481c9.woff2` (Latin) | 24,956 | `e4423b318e11432aff2e6e865e300b7ca270f92321a3f56632268fede01c1b48` |
| `Excalifont-Regular-be310b9bcd4f1a43f571c46df7809174.woff2` (Latin Extended-A) | 12,220 | `4fb8ad69be9aeac5664d99e5aa3a68a27ea40c98943b80387f7cd55c034fcc93` |

**Coverage on the incorporated bytes.** A test-only WOFF2 reader (`frontend/tests/helpers/woff2.mjs`, brotli through
`node:zlib`) decodes each file's `cmap`: the Latin subset maps 212 code points and covers all 125 required en/es
characters; the Latin Extended-A subset maps 140; together 352 without overlap. Every character of every `map.*`
catalogue string in both languages is covered.

**CSS.** Two `@font-face` rules in `styles.css` with `font-display: swap`, local `url("./map/fonts/…")` sources and a
`unicode-range` equal to the code points each subset maps (tested against the cmap). The family is named only in the
`.map` scope (`--font-map: "Excalifont", var(--font-ui)`) and used only by `.map-label`; every SVG `<text>` in the view
is a map label, while the toolbar, help text and fixture controls keep the interface font. Characters outside both
ranges (Cyrillic and Japanese titles in the fixture) fall back to the interface font per character.

**Notice.** `frontend/src/map/fonts/OFL-1.1.txt` carries the Excalifont header (files, tag, source path, "shipped
unmodified", attribution "Excalifont by Excalidraw, derived from Virgil", the copyright line) and the SIL OFL 1.1 text.
The licence body was taken from a local copy of the standard text (another font's `OFL.txt` on this machine), compared
line by line: identical apart from CRLF line endings and one trailing space, normalized to LF. A build plugin emits it
as `assets/Excalifont-OFL-1.1.txt` beside the hashed font assets; `NOTICE-THIRD-PARTY.md` gains a **Fonts** section
with the files, hashes and the same text (tested to be identical).

**Finding for the owner (T018 §10.2 versus the bytes).** T018 records the OFL 1.1 licence, the designers and the
trademark note as "embedded in the font's name table". The `name` table of both shipped subsets contains only
records 0–6: copyright "Copyright (c) 2024 by Excalidraw. All rights reserved.", family, style, unique id, full name,
version 1.000 and PostScript name. No licence, licence URL, designer or trademark record is present. The licence
attribution therefore rests on T018's accepted reading and D308, not on metadata inside these files. T018's record is
not rewritten; resolution is requested (§10). **Resolved in the first re-review round (§12.3):** the information is
preserved in the font's source file at the same tag, not in the binary subsets.

## 4. Engine behaviour

- **Seeds and stability.** Shapes are drawn with seeds from identities (`card:<node id>`, `edge:<from>-><to>:<kind>`,
  `circle:<node>:<role>`, `icon:<class>`), never from list positions. Path data lives in world coordinates and does not
  change with the camera; the camera is one `transform` on the world group. Rendering the same level with the input
  reversed produces byte-identical markup; a moved camera changes only the world transform (tested).
- **Layout.** Left-to-right layers for `depends_on`; `replaces` lineage is laid out and drawn dashed with the neutral
  colour, `depends_on` solid in the muted colour; phases and steps use `sequence` edges. Cycles, duplicates,
  self-loops and unknown endpoints are tolerated; a 5,000-node chain lays out in ~17 ms in Node (after replacing an
  O(layers × nodes) refresh found by that test).
- **Camera and input.** Wheel zooms about the pointer (Shift+wheel pans); trackpad pinch arrives as Ctrl+wheel in
  Chromium and as `gesture*` events in Safari; two-finger touch pinches about the moving midpoint; drag pans after 5 px
  (mouse) or 10 px (touch). Pointer capture starts only once a drag starts, so a plain press keeps its click on the
  node, and the click that ends a drag never navigates.
- **Enter and leave.** Click or Enter on a node, or a zoom-in that makes an enterable node cover ≥ 50 % of the
  viewport, enters it; with motion allowed the camera finishes the zoom in 220 ms first, under reduced motion it
  navigates at once. Escape, "Up one level" or accumulated zoom-out of ln-factor ≥ 0.7 beyond the minimum within
  600 ms windows returns to the parent. After reporting a navigation the controller ignores further ones for 1.5 s or
  until the level is reset, and the shared `navigate` ignores the current path. *As corrected in §12.2:* the reset
  released that lock while the same gesture went on, so a page-wide gesture guard now ignores the rest of a navigating
  wheel burst, Safari pinch or key auto-repeat on every level, and a continuous gesture adds one history entry. L3
  task and run views both return to L2.
- **Routes and history.** Enterable nodes are real SVG links to the existing routes (open in a new tab works);
  navigation is `pushState` through `navigation.tsx`, so Back/Forward replay levels. The parent level restores the
  focused node and a camera pulled back below the enter threshold.
- **Keyboard and focus (D312).** One node is in the tab order (roving tabindex); arrows move the focus to the nearest
  node in that direction and the camera follows; Shift+arrows pan; + and − zoom about the focused node; 0 fits;
  Home/End go to the first/last node in reading order; Escape leaves; Ctrl/Cmd/Alt combinations are left to the
  browser. Tab reaches the toolbar. The focus ring is a dedicated SVG rectangle shown on `:focus-visible`. An empty
  level focuses its toolbar instead of dropping the focus to the page.
- **Accessibility text.** Node name: kind, code, title, status text, active actors, request count; description: raw
  status code, `Depends on …`, `Replaces …` (sorted, unique) and "No deeper level" where applicable. `unknown` shows the
  raw code as its visible label. The SVG is a labelled group described by the help text.
- **Reduced motion.** `prefers-reduced-motion` (or the fixture override) sets `data-motion="reduce"`: no enter
  transition, static rays and no level fade (CSS also disables both under the media query).
- **Tokens and contrast.** New pairs: light `--progress #ad4c00`, `--progress-soft #fae6d4`, `--waiting #6a3db0`,
  `--waiting-soft #ece3f8`; dark `#f2a65e`, `#3a2716`, `#c2a5f7`, `#2c2342` (both dark blocks). Status text on the card
  surface: light ok 6.21, progress 5.31, waiting 6.96, danger 6.81, neutral 6.97, muted 5.41; dark ok 8.92, progress 8.23,
  waiting 7.93, danger 7.23, neutral 8.96, muted 6.63; bubble count on its fill ≥ 5.8 (tested ≥ 4.5 from `styles.css`).
- **Primitives only.** R/E/J/H circles, rays and a request-count bubble are drawn from fixture data to review the look;
  they are not interactive and no T017 panel, polling or trace is involved.

## 5. Synthetic fixture and owner visual review

The fixture is `frontend/map-fixture.html` plus `frontend/src/map/fixture/`. The Vite **dev server** serves it for
every path under `/__map-fixture/` (plugin with `apply: "serve"`); it is not an input of the production build and is
absent from the wheel and sdist (verified, §8). It reads no API and needs no session.

Data (`fixture/data.ts`) is deterministic (Mulberry32 with fixed seeds): one deep path project `atlas` → phase `P002`
→ task `P002-T005` with leaf siblings (D309), every class at every level, `depends_on` waves and `replaces` lineage,
titles in English and Spanish with ¿¡«»—…, Latin Extended-A (Łódź, ő, ť) and fallback scripts (Cyrillic, Japanese),
long titles, active actors with rays and request bubbles.

| Scenario | L0 projects | L1 phases | L2 tasks | L3 steps |
|---|---|---|---|---|
| Normal review | 8 | 9 | 14 | 8 |
| Budget (D309 maxima) | 25 | 40 | 80 | 40 |
| Stress | 25 | 40 | 200 | 40 |

**How to open it.** Start the development servers as usual (`scripts/dev`; the first run after this change performs
its offline `npm ci` because the lock changed), or only the frontend with `npm --prefix frontend run dev`. Open
<http://127.0.0.1:5173/__map-fixture/>. The scenario, language, theme and motion selectors are per tab
(sessionStorage); reloads keep the current level.

**Owner review checklist** (not done by this task):

1. Light and dark: switch *Theme* (or follow the system); check card outlines, status colours, edges, labels and
   focus ring at L0, L1 (`atlas`), L2 (`P002`) and L3 (`P002-T005`).
2. Desktop and mobile: a wide window and a phone-width window (or the browser's device emulation); drag, wheel,
   trackpad pinch and, on a touch device, two-finger pinch.
3. English and Spanish: switch *Language*; labels, status texts, toolbar and help text.
4. Navigation: click a card, press Enter on a focused card, zoom far into a card, Escape, "Up one level", the
   breadcrumb, browser Back/Forward; a drag that starts on a card must not open it.
5. Keyboard: Tab into the map, arrows, Shift+arrows, + / − / 0, Home / End, Tab to the toolbar.
6. Motion: *Motion → Reduced* (or the system setting): immediate transitions and static rays.
7. Stress: *Scenario → Stress*, L2 `P002`; the two measurement buttons reproduce §7.

## 6. Tests

| Suite | Result |
|---|---|
| `node --test frontend/tests/map-engine.test.mjs` | 22 passed: seeds (pinned values, 20,000 identities with no collision), shapes independent of order and cache, bounded cache, layering and dummy points, order independence, cycles and duplicates, 5,000-node chain, camera maths, drag/click, keyboard activation after drag, zoom-enter once, no enter on leaves or background, zoom-out leave with fading pressure, top level, keyboard map, reveal, pinch, resize re-fit, reset, reduced-motion duration, en/es labels, title wrapping |
| `node --test frontend/tests/map-view.test.mjs` | 10 passed: server-rendered view with focusable labelled nodes and one tab stop (en/es), links to the existing routes, non-enterable images, every class with icon and text at every level, identical markup under reordering and refresh, camera-only transform change, distinct edges, reduced-motion and animated enter with the lock, levels/parents/paths with and without the base, zoom-enter and leave through `navigate` and `history.pushState` (one entry per gesture, focus memory), fixture sizes/classes/scripts, fixture text parity |
| `node --test frontend/tests/map-assets.test.mjs` | 7 passed: exact pin and single locked copy, font sizes/hashes/name records, cmap coverage, `@font-face` ranges and swap, font limited to map labels, licence/notice/emission, contrast in both themes |
| `scripts/check tests/product/test_ui_routes.py` | 21 passed, including the new static-serving test: real font bytes under hashed names with `font/woff2`, the licence as `text/plain`, a missing font is a 404 and never the shell |
| `scripts/check --frontend` (closure) | See §11 |
| `scripts/check-docs` (closure) | See §11 |

## 7. Browser measurements (D309)

*Historical: measured on the first-round code, before the corrections of §12. They are not carried over; the corrected
code was measured again in §12.7.*

**Environment.** Claude desktop app's built-in browser (Chromium 152.0.7977.167, 60 Hz frames), macOS 27.2 on an Apple
M5 with 24 GiB; Vite 8.3.4 **development** server on 127.0.0.1:5173 (React development build, unminified modules, so
the figures are conservative for production). Fixture only; no API. Each batch was bracketed by a 20-frame cadence
probe (16.6–16.7 ms before and after); a batch run while the pane was hidden or the window throttled frames (one
16.8 s and one 4.4 s sample) was discarded and repeated.

**First render.** Time from the render that starts a level to the second animation frame after its commit (layout,
rough.js generation, React render, style, layout and paint).

| Case | Samples | Result | Budget |
|---|---|---|---|
| L2 80 nodes, empty shape cache ("Redraw with an empty shape cache") | 15 | median 77.2 ms, p90 82.9 ms, max 84.1 ms | ≤ 500 ms ✓ |
| L1 → L2 80 nodes by clicking `P002` (after the 220 ms transition) | 6 | 66.2 ms (cold), then 49.5–49.7 ms | ≤ 500 ms ✓ |
| L2 → L1 40 nodes by Escape | 6 | 36.9–40.1 ms | — |
| L2 200 nodes (stress) by clicking `P002` | 1 | 100.5 ms | — |

**Pan and zoom.** "Run the pan and zoom benchmark (4 s)" fits the level and then sets a new camera through
`MapController.set` on every animation frame (scale 84–100 % of the fitted one, pan within the fit padding, so every
card that starts in view stays in view), recording frame intervals. Stress scenario, L2, viewport 691 × 781 px, all
200 cards fully in view.

| Run | Frames | Mean | 5th percentile | Longest frame |
|---|---|---|---|---|
| 1 | 240 | 59.8 fps | 59.5 fps | 32.4 ms |
| 2 | 240 | 60.0 fps | 59.5 fps | 17.6 ms |
| 3 | 241 | 60.0 fps | 59.5 fps | 17.7 ms |

Budget ≥ 50 fps at 200 visible nodes: met. A first run on the same path showed only 75 cards in view because the
fixture reused the camera remembered from the previous scenario; the fixture now forgets views and remounts on a
scenario change, and the benchmark fits before measuring. Not measured: production bundle, other browsers and
engines (Safari/Firefox), 120 Hz displays, low-end hardware, real touch hardware.

**Real input in the browser.** With real mouse, wheel and keyboard events: a drag from a card moved it exactly with
the pointer and added no history entry; 30 wheel ticks over `P002-T005` entered it with one history entry; Escape
returned to L2 with that task focused; ArrowRight moved focus and the single tab stop; Enter navigated; Back/Forward
replayed the levels; a 375 × 812 phone viewport fitted the level after the resize fix (§10); computed styles showed
no ray or fade animation under reduced motion and the ray animation when allowed. Every request was to
`localhost:5173`; the fonts came from the dev server.

## 8. Packaging, serving and bundle

**Offline distribution build.** `uv run --frozen --offline python scripts/build_distribution.py --offline --out-dir
<scratch>` succeeded, including its exact-member check (`check_checkout_artifacts`). `node_modules` was cloned before
the build's `npm ci` and compared afterwards: identical. Inspection of the real members:

- wheel and sdist both contain `my_harness/web/assets/Excalifont-Regular-a88b…-DBEDukyo.woff2` and
  `…be310…-CwOnC3Ii.woff2` with the pinned sizes and SHA-256 values, and `assets/Excalifont-OFL-1.1.txt` byte-identical
  to the source licence;
- the wheel's `dist-info/licenses/NOTICE-THIRD-PARTY.md` and the sdist's `NOTICE-THIRD-PARTY.md` are the updated file
  with the Fonts section;
- the built CSS references only `/assets/Excalifont-…woff2`; no `http(s)://` URL; one `rough.esm` chunk; no fixture
  page, fixture code or fixture strings.

**Serving.** The existing `SPAStaticFiles` serves `.woff2` as `font/woff2` and `.txt` as `text/plain`, and a missing
asset stays a 404 (test in `test_ui_routes.py`). No server change was needed.

**Bundle delta** against a build of `develop` at `6ba19eb` (same toolchain, scratch worktree removed afterwards):

| Asset | Delta |
|---|---|
| Every JavaScript chunk except `workspace` | 0 bytes (gzip ±11 B from changed hash references) |
| `workspace` chunk (en/es catalogues) | +3,098 B (+1,080 B gzip) |
| `index` CSS (tokens, `@font-face`, map rules) | +3,871 B (+1,087 B gzip) |
| Two font files | +37,176 B (already compressed) |
| `Excalifont-OFL-1.1.txt` | +4,763 B |
| **Total** | **+48,908 B** (+41,577 B gzip) over 4,618,585 B |

The engine itself is not in the product bundle until T022 imports it. A scratch build with an engine-only entry gives
its own chunk: **25,160 B (9,235 B gzip)**, importing the shared `rough.esm-Dy-Kn_BL.js` (27,109 B, the same file the
product already ships for mermaid) rather than a second copy; the fixture chunk (engine + fixture) is 38,823 B.

## 9. Threat controls

- **TM15 (resource exhaustion).** Shape cache bounded at 4,000 entries and view memory at 64 paths (tested); layout is
  iterative (no recursion) and near-linear for chains; the fixture measures the D309 sizes; no polling or history
  decoding exists in T021.
- **TM19 (supply chain).** Exact pin and unchanged lock integrity for rough.js, no download for it; fonts pinned by tag
  and SHA-256 (tested on every run), shipped unmodified with the OFL notice in the package; local `@font-face` only,
  no CDN, no runtime network (build inspection and browser request log).

## 10. Findings, limitations and pending work

- ~~**Requested resolution:** the licence metadata finding of §3.~~ Resolved by the first re-review round without an
  owner decision: the provenance is the font's `index.ts` at the same tag (§12.3).
- **Fixed during measurement:** the canvas did not fill a flexed viewport (SVG fell back to 150 px); a resize after the
  first fit did not re-fit (phone layout); a same-path scenario switch kept the previous camera; an empty level dropped
  the focus. Each fix has a test or a browser re-check.
- **Not product-wired:** levels, `?view`, polling, functional circles and bubbles, the shared `Status` migration, L4 and
  the drawer are T022–T024. No flow document changes: the product navigation flow is unchanged until T022 wires the map.
- **Mobile readability:** a fitted 14-node level on a 375 px phone is drawn at about 18 % zoom; labels need a pinch to
  read. Whether T022 should fit differently on small screens is a design question for the owner review. (Separate
  from the clipping defect of §12.1, which made "fit" itself leave cards out on large levels.)
- **Not done here:** independent technical review, owner visual review, production-bundle measurements, other
  browsers, screen-reader testing with assistive technology, live-region announcements (T022), the stale lock hash line
  in `NOTICE-THIRD-PARTY.md` (pre-existing; regenerating the inventory is outside T021).

## 11. Verification at closure (first round, historical)

- `scripts/check --frontend` (once, 2026-11-06, 5 min 8 s): unittest 10 ran ok; `alembic check` no new upgrade
  operations; pytest 3,234 passed, 3 skipped, 29 subtests passed, 1 warning (`UserWarning: Duplicate name` from the
  existing tampering case `test_install_command.py::…[duplicate]`, which writes a duplicate zip member on purpose);
  Node 319 tests passed; `tsc` and the Vite build passed.
- After that run, `MapView.tsx` gained the expiring focus hand-over (§4); the three map Node suites (39 tests) and
  `tsc --noEmit` were re-run and pass.
- `scripts/check-docs`: 126 Markdown files, 0 errors. `git diff --check` clean, including the new files.
- Reviewed the complete diff (40 files). No model, migration, API, OpenAPI, generated client or flow change; ONE_OFF_TASKS
  unchanged (empty); versions unchanged (0.1.9).
- **Not tested:** production-mode browser timings, browsers other than Chromium 152, real touch hardware, assistive
  technology, the owner's visual review and an independent technical review. Nothing was committed, merged, pushed,
  published or installed; no harness, agent or provider was run.

## 12. Independent technical review, round 1 — corrections

The independent review repeated the 39 map tests, the 21 static-route tests, TypeScript, `scripts/check-docs` and
`git diff --check` successfully, and reported two P2 defects those tests did not cover, the evidence for the licence
question and an inaccurate lock description. All are addressed in this round, within T021 (no T022 scope, no new
dependency).

### 12.1 [P2] "Fit to view" clipped valid levels on a phone

**Defect.** `camera.ts` floored the minimum zoom at an absolute 0.05. On a 375 × 500 viewport the fitted scale of the
budget fixture's L1 (40 phases, 12,064 px wide) is ≈ 0.0231 and of its L3 (40 steps, 11,264 px) ≈ 0.0248, so the
controller clamped "fit" to 0.05 and only 21 and 23 cards were fully in view, on the initial fit and on the fit button.

**Correction.** `limits()` no longer has an absolute floor: the minimum is half the fitted scale (half of 1 when the
content fits at full size), so it is always below the fitted scale, finite and positive for finite bounds. Fit,
pan clamp, leave-by-zoom-out and the remembered-camera settle all use that range unchanged.

**Regressions** (`map-engine.test.mjs`): for the budget L0 (25), L1 (40), L2 (80), L3 (40) and the stress L2 (200)
laid out exactly as the view lays them out, on 375 × 500 and 1000 × 600, the projected corners of **every** card lie
inside the viewport and the content centre is at the viewport centre after the initial fit, after zooming and panning
away and pressing the fit button, after the 0 key, after resizing a fitted desktop view to the phone and after a
reset; the camera is finite and the minimum leaves room below the fit. A second test checks, at the 0.023 scale, that
panning keeps content reachable and zooming out still returns to the parent. With the 0.05 floor restored both tests
fail (counter-check).

### 12.2 [P2] One level change let the same gesture navigate again

**Defect.** `reset()` released the navigation lock when the next level arrived, so the remaining events of the same
wheel burst could cross the threshold again on the new level: with one 200 × 100 card per level, a 1000 × 600 viewport
and a reset on entering, 15 consecutive `deltaY=-120` events entered three levels.

**Correction (D312 updated).** `MapController` keeps the lock behaviour (pending navigation, released on reset so a
deliberate action on the new level is not delayed) and adds a page-wide `GestureGuard` that survives `reset` and a
remounted view (shared module instance `pageGestures`). When a continuous input navigates — a wheel burst, a Safari
`gesture*` pinch, or a key (Escape, + / −, Enter activation) — the rest of that gesture is ignored on any level:
wheel and gesture events closer than `GESTURE_GAP_MS` (300 ms) to the previous one, and key auto-repeats. The gesture
ends with a pause of 300 ms, a `gesturestart`, a key press that is not an auto-repeat or any pointer press
(*round 2, §12.6: the 300 ms pause applies to wheel and pinch only, not to key auto-repeat*); clicks and
pointer pinches are discrete or end with their pointers (which `reset` drops). The view passes `KeyboardEvent.repeat`
and marks Enter activations as keyboard navigations, so holding Enter on a link no longer opens the next level's
focused node.

**Regressions.** `map-engine.test.mjs`: the reviewer's case (15 events, 0 ms and 16 ms apart) enters once and a burst
after a 300 ms pause enters the next level once; the tail of a burst neither zooms nor navigates, while a click right
after navigates at once and a pointer press starts a new gesture; a zoom-out burst leaves once; a controller remounted
with the shared guard ignores the tail and responds after a pause; Escape/Enter/+ auto-repeat never navigates twice
while a fresh press does; a Safari pinch enters once and a new `gesturestart` is a new gesture. New
`map-navigation.test.mjs` drives the real `MapView` across commits (the hook host's new opt-in `lifecycle` runs layout
effects and keeps memoized values; default behaviour of the helper is unchanged and the 319 existing Node tests pass)
with the fixture's router binding and a fake `history.pushState`: under reduced motion one burst adds exactly one
history entry, a burst after a pause adds the next, and a zoom-out burst adds one parent entry; with the transition,
nothing navigates before the 220 ms camera transition ends, then exactly one entry is added and the tail is ignored on
the next level; a view remounted for the next level keeps ignoring the burst; Escape plus its auto-repeat adds one
entry and a fresh Escape the next. Disabling the guard makes the six controller tests and the four view tests fail
(counter-check).

### 12.3 Licence provenance and lock description

The reviewer located the evidence: the official `index.ts` of Excalifont at tag v0.18.1
(<https://github.com/excalidraw/excalidraw/blob/v0.18.1/packages/excalidraw/fonts/Excalifont/index.ts>) imports
exactly the two incorporated files and keeps, under `Origin File Name Table`, the OFL 1.1 declaration, the licence
text, the designers and the trademark. The correct distinction is that this information is preserved in the source
file of the same tag, while the distributed binary subsets carry reduced metadata (copyright only, §3). This is a
clarification after T018's accepted record, which is not rewritten; the owner question of §10 is withdrawn.

This round fetched nothing (no new download was authorized); the file was not re-read here. The incorporated notice
was contrasted with the values T018 §10.2 recorded from that authorized fetch, which the reviewer reports as those in
`index.ts`: copyright "Copyright (c) 2024 by Excalidraw. All rights reserved." (also in the binaries), designers "Your
Own Font Foundry (Virgil); Ján Filípek / DizajnDesign (Excalifont, modifications)", trademark "Excalifont is a
trademark of Excalidraw", OFL 1.1 without a Reserved Font Name. `OFL-1.1.txt` (and so `assets/Excalifont-OFL-1.1.txt`
and the Fonts section of `NOTICE-THIRD-PARTY.md`) now also carries the designers, the trademark and a provenance line
naming `index.ts` at the same tag; the licence body is unchanged. The two binaries and their hashes are untouched
(tests still check sizes and SHA-256). D308's status line, STATE and NEXT_STEPS no longer list an owner decision for this.

The lock description of §2 is corrected: the root entry gained `"license": "MIT"` besides `"roughjs": "4.6.6"`.

### 12.4 Evidence of this round

- Focused Node tests: `map-engine` 30 (22 + 8 new), `map-view` 10, `map-assets` 7 (updated for the credits),
  `map-navigation` 4 (new) — 51 passed; with `i18n` 61; `tsc --noEmit` passes; `test_ui_routes.py` 21 passed.
- Packaging (notices changed): new offline build `scripts/build_distribution.py --offline` into a fresh scratch folder
  succeeded with its exact-member check. Wheel and sdist: the two fonts with the pinned sizes and SHA-256 under the same
  hashed names, `assets/Excalifont-OFL-1.1.txt` identical to the source, `NOTICE-THIRD-PARTY.md` (wheel `dist-info/licenses`
  and sdist root) identical to the repository file; both licence and notice contain the designers, trademark and
  `Origin File Name Table` provenance; CSS references only `/assets/`; one `rough.esm` chunk; no fixture. The
  `node_modules` comparison around the build's `npm ci` showed one difference: Vite's regenerable dev pre-bundle cache
  `node_modules/.vite` (created by the first round's dev server) was removed; every package is intact (`npm ls`).
- **Browser re-verification pending** *(done later, §12.7)*. The first round's local-server authorization covered that measurement session
  and the server was stopped; none was granted for this round, so no server was started. Pending on the corrected code:
  the D309 timings of §7 (80-node first render, 200-node pan/zoom), the real-input checks of §7 and the phone-width fit
  in the browser. The budgets are not relaxed.

### 12.5 Verification at closure of round 1

- `scripts/check --frontend` (once, 2026-11-06): unittest 10 ran ok; `alembic check` no new upgrade operations; pytest
  3,234 passed, 3 skipped, 29 subtests passed, 1 warning (the same deliberate duplicate-member case
  `test_install_command.py::test_self_contained_artifact_verifier_rejects_tampering[duplicate]`); Node 331 tests
  passed (319 before + 12 new); `tsc` and the Vite build passed. No code changed after this run.
- `scripts/check-docs`: 126 Markdown files, 0 errors. `git diff --check` clean for tracked files and for every new
  file (`git diff --no-index --check` against `/dev/null`, without touching the index).
- Reviewed the complete diff and the new files. No model, migration, API, OpenAPI, generated client, flow, version or
  dependency change in this round; ONE_OFF_TASKS unchanged (empty); T018's record unchanged.
- **Not done:** browser re-verification of the corrected code (§12.4), re-review, the owner's visual review,
  integration and delivery. Nothing was committed, merged, pushed, downloaded, published or installed; no server, harness,
  agent or provider was run in this round.

### 12.6 Independent technical review, round 2 — key continuity

**Defect.** The 300 ms gap that ends a wheel or pinch gesture also expired the keyboard guard: Escape (`repeat=false`)
at t = 0 left the level, the level reset, and the first auto-repeat of the same held key at t = 500 ms
(`repeat=true`) left again — two navigations for one press. Browsers commonly wait about 500 ms before the first
auto-repeat, so this was the normal case for a held key.

**Correction.** `GestureGuard.continues` applies `GESTURE_GAP_MS` only to wheel and pinch, which have no end signal.
A held key has one: every auto-repeat belongs to the press that navigated, however late, and only a fresh press
(`repeat=false`) or a pointer press ends it. The timeout was not raised. A new deliberate press therefore works at once,
and an unrelated key cannot be swallowed because it always starts with a fresh press.

**Regressions.** `map-engine.test.mjs`: Escape at t = 0, reset, first repeat at t = 500 ms and five more 500 ms apart
leave once, and a fresh Escape leaves at once; Enter activation, reset, late repeats are consumed (so the next level's
link is not activated) and a fresh Enter activates; holding + zooms until it enters, then late repeats on the new level
neither zoom nor navigate and a fresh + zooms at once; a pointer press still ends a held-key gesture and wheel bursts
still expire after a pause. `map-navigation.test.mjs`: the real view under reduced motion across real level changes
with 500 ms waits (Escape → one parent entry; + held → one entry into `P002`, then a late repeat changes neither camera
nor history; Enter activation → one entry, late repeat consumed; a fresh Escape navigates at once; four entries in
total). The earlier wheel, remount, pinch and fresh-press tests are unchanged and pass. With the old expiry restored,
both new tests fail (counter-check).

**Evidence of this round.** Map Node tests 54 passed (`map-engine` 32, `map-view` 10, `map-assets` 7,
`map-navigation` 5); full Node suite 334 passed; `npm run build` (`tsc --noEmit`, then Vite) passed. Only
`controller.ts`, the two test files and this documentation changed, so the full Python suite and the packaged notices
were not rerun or rebuilt in this round (round 1's `scripts/check --frontend` and offline build stand for the rest of
the diff). The mobile fit and licence clarification of round 1 are kept unchanged. Still pending at that point:
browser re-verification of the corrected code (done in §12.7), re-review, the owner's
visual review, integration and delivery. Nothing was committed, merged, pushed or started.

### 12.7 Browser re-verification of the corrected code

**Authorization and environment.** On 2026-11-06 the owner authorized Vite for these tests. A frontend-only Vite
development server (`npm --prefix frontend run dev`, 127.0.0.1:5173, started through a temporary `.claude/launch.json`
that was removed afterwards) served the synthetic fixture; no API, `scripts/dev`, harness or agent. Browser: the app's
built-in Chromium 152.0.7977.167, 60 Hz, macOS 27.2 on an Apple M5 with 24 GiB; development build of React, so
conservative. The pane was hidden at first (frames ≈ 568 ms apart): nothing was measured until the owner showed it,
and every timing batch was bracketed by a 20-frame cadence probe (16.66–16.71 ms before and after). The code was the
round-2 source, unchanged during the session; the server was stopped and the port freed at the end.

**D309 budgets on the corrected code.**

| Case | Samples | Result | Budget |
|---|---|---|---|
| L2 80 nodes, empty shape cache | 15 | median 71.6 ms, p90 80.4 ms, max 81.4 ms | ≤ 500 ms ✓ |
| L1 → L2 80 nodes by clicking `P002` (after the transition) | 6 | 49.4–50.6 ms | ≤ 500 ms ✓ |
| L2 → L1 40 nodes by Escape | 6 | 33.6–38.7 ms | — |
| L2 200 nodes (stress) by clicking `P002` | 1 | 105.2 ms | — |
| Pan/zoom benchmark, 200 cards fully in view, viewport 1500 × 856 | 3 × 4 s | 60.0 fps mean each; 5th percentile 59.5, 56.8, 59.2 fps; longest frame 17.7 ms | ≥ 50 fps ✓ |

The 12 navigations of the L1 ↔ L2 batch added exactly 12 history entries.

**Fit on a phone (finding 12.1).** Emulated 375 × 812 (map viewport 351 × 503), budget scenario, counting cards whose
drawn rectangle lies inside the viewport rectangle: L1 (40 phases) 40/40 at scale 0.021 after resizing a fitted
desktop view, after the fit button, after zooming and panning away (14/40) and the fit button again, and on a fresh
load at phone size; L3 (40 steps) 40/40 at scale 0.023 on entry and after zooming (12/40) and the 0 key. Both scales are
below the former 0.05 floor.

**One navigation per gesture (findings 12.2 and 12.6).** Normal scenario, desktop size, motion allowed:

- Real mouse drag starting on a card: the card moved exactly with the pointer; no navigation, no history entry.
- Real wheel: a first 10-tick burst over `atlas` zoomed to 237 % without reaching the threshold; a second burst entered
  L1 with exactly one entry (22 → 23), and its remaining ticks neither zoomed nor navigated L1 (it stayed fitted, 53 %).
- 40 native `wheel` events (`deltaY=120`, 16 ms apart) dispatched to the canvas at L2 left exactly one level (28 → 29) to
  L1, which stayed at its remembered 53 %; L0 was never reached.
- Real Enter on the focused `P002` card entered L2 (one entry) with focus on its first task; a `repeat:true` Enter keydown
  500 ms later was consumed (`defaultPrevented`, so a real browser does not activate that link) and nothing navigated.
- Real Escape left to L1 with `P002` focused again; `repeat:true` Escape keydowns 500 ms and 800 ms later were consumed
  and nothing navigated; a fresh real Escape left to L0 at once with `atlas` focused.
- Browser Back and Forward replayed L2 and L1.

Auto-repeat was produced as synthetic `KeyboardEvent`s with `repeat: true` through the view's real handler, because the
automation presses keys without holding them; the first press of each sequence was a real key press.

**Other.** Reduced motion: `data-motion="reduce"`, no ray or level-fade animation; allowed: the ray animation runs. Every
resource came from `127.0.0.1:5173`, including both Excalifont subsets.

**Still pending:** re-review, the owner's visual review in the browser (§5 checklist; these checks are not that review),
integration, release 0.2.0, distribution/publication and installation. Not measured: the production bundle, other
browsers, real touch hardware, assistive technology. Nothing was committed, merged or pushed.

## 13. Independent final re-review and owner acceptance — 2026-11-06

Passed with no outstanding relevant findings. The final inspection covers the accumulated implementation, the
phone-fit correction, gesture continuity across level changes and remounts, delayed keyboard auto-repeat, and the
licence provenance clarification. The browser re-verification in §12.7 covers the corrected source and both D309
budgets; synthetic keyboard repeats are distinguished from real input and native touch qualification is not claimed.

- Independently repeated all four map Node suites on the final product source: **54 passed**. Reproduced the delayed
  Escape case with repeats at 500 ms intervals: one navigation while held, then an immediate second navigation on a
  fresh press. The earlier independent static-route check passed **21 tests** and TypeScript passed.
- Reviewed the implementer's complete-check evidence (§§12.5–12.6): Python **3,234 passed, 3 skipped**, the subsequent
  complete Node suite **334 passed**, and the final TypeScript/Vite build passed. The general Python suite and package
  build were not repeated after the keyboard-only correction; their scope and timing remain explicit above.
- Documentation and whitespace checks passed after the browser evidence. This delivery changes documentation only;
  product source, fixtures, fonts and notices remain the reviewed versions.

The owner explicitly accepted T021 and authorized its source commit, merge into `develop` and push of `develop`.
Personal visual review is deferred to T022, when the map is connected to real data (D313); it is not waived for the
product map and is not recorded as performed. This task does not implement T022 or authorize its work.

Release 0.2.0 through protected `main`, distribution/publication and installation remain pending. No installation,
database migration, service startup, real agent/provider or harness execution was performed in this delivery.
