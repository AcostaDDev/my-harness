# P002-T018 — Owner visual direction for the work map

**Status:** owner direction supplied on 2026-11-03 (sketches and description below); the interaction proposal in
§§3–7 was **accepted by the owner on 2026-11-03** with the answers in §8
([D297](../DECISIONS.md#d297--work-map-visual-direction-and-agent-conversation-entry-points)). Design input only: no
source, schema, API or dependency change; T018 and T017 are not started and the implementation order is unchanged
(T015 next). Gates: resolves the owner direction of **G14** (graph visual direction, T018) and supplies the
conversation kinds of **G13** (inbox taxonomy and shortcuts, T017). Constraints already
fixed: [D277](../DECISIONS.md#d277--correlated-traces-operations-and-knowledge-access-receipts),
[D278](../DECISIONS.md#d278--global-inbox-and-task-instance-graph), B19/B20 of the
[design basis](P002-design-basis.md#b20--task-instance-graph-and-trace-inspection), threats TM13, TM14, TM17, TM18.

## 1. Owner direction

The owner wants a very visual, explicit view of how the agents work in each project, usable in manual mode now and
to follow the autonomous mode in real time as it moves from task to task and phase to phase.

- **All projects at once.** The first level shows every project as a card. Above each card, one circle per agent
  role: **R** reviewer, **E** executor, **J** judge. The circle with "rays" is the agent working now; work is
  turn-based, so normally one agent per project is active.
- **Zoom enters.** Zooming in (or clicking) enters an element and reveals its children: project → phases →
  tasks → runs. The agent circles follow the active element at every level.
- **Agent trace.** Zooming into an agent shows, as a graph, the paths that specific agent took: turns, tool calls
  and the rest of the recorded trace.
- **Documentation sheet.** Inside a project, a sheet-shaped button opens the project documentation: a document tree
  on the right, the document in the centre and the map still visible on the left.
- **Hand-drawn style.** Excalidraw-like look, in light and dark themes.
- **Speech bubbles.** When an agent has a request or question, a comic bubble appears next to it; clicking it, at
  any level, opens a conversation with that agent. Conversation kinds include approving permissions, answering a
  blocking question and general chat (asking something, asking it to add a task).

| Sketch | Shows |
|---|---|
| [01](P002-T018-sketches/01-projects.png) | Projects level; R active on Project 1; left sidebar; view toggle (eye / list) top left |
| [02](P002-T018-sketches/02-zoom-project.png) | Continuous zoom towards Project 1; neighbours leave the viewport |
| [03](P002-T018-sketches/03-phases.png) | Phases of a project as a sequence: completed (green), in progress (orange), pending (neutral) |
| [04](P002-T018-sketches/04-zoom-phase.png) | Continuous zoom towards Phase 2; the incoming edge from Phase 1 stays visible |
| [05](P002-T018-sketches/05-tasks.png) | Tasks of a phase as a dependency graph: completed, failed (red), in progress |
| [06](P002-T018-sketches/06-run-steps.png) | Run level: "Run 1 – Reviewer" → "Run 2 – Executor", executor active |
| [07](P002-T018-sketches/07-docs-button.png) | Sheet button at the top right inside a project |
| [08](P002-T018-sketches/08-docs-drawer.png) | Open documentation: `NEXT_STEPS.md` in the centre, tree (`archive/`, `flows/`, `phase/`, …) on the right |

## 2. Fit with accepted design

The direction matches D278 and B20 without changing them: the map is a **read-only projection** of persisted
projects, phases, task instances, runs and invocations with their actual reviewer, executor, judge and Harness
involvement. It is neither a workflow editor nor the LangGraph runtime topology; mutations happen only through the
ordinary guarded commands reached from T017's conversation panel. Polling stays the default refresh (D278).

Two points of the sketches need a precise reading against the data model:

- **"Run" in sketch 06.** In the product a run is one execution of a task (`managed_runs`); inside it the reviewer,
  executor, optional judge and Harness stages take turns as invocations/attempts (D287). The nodes "Run 1 – Reviewer"
  and "Run 2 – Executor" are therefore the **steps** of one run. A task can have several runs (retries, owner-adopted
  replacements, D296).
- **One active agent per project.** Task execution is sequential per checkout, but the project chat has its own lane
  over a read-only snapshot ([chat flow](../flows/chat.md)), so a chat answer can coincide with a task step. The map
  shows every active invocation the data reports instead of assuming exactly one.

## 3. Proposed interaction model

**Levels (semantic zoom).** Each level is an existing URL, so the browser history, breadcrumb and shared links keep
working; the zoom is a camera transition between routes, not a separate navigation model.

| Level | Nodes | Edges | Route |
|---|---|---|---|
| L0 Projects | Registered projects (archives marked read-only) | — | `/` (the map replaces the home page) |
| L1 Phases | Phases of the project, including closed and archived | Phase order | `/projects/:p/phases` |
| L2 Tasks | Task instances of the phase | `depends_on` links; `replaces` lineage (D296) dashed | `/projects/:p/phases/:f` |
| L3 Run steps | Steps of the latest run: reviewer, executor, judge invocations and Harness stages; a selector shows earlier runs | Step order | `/projects/:p/phases/:f/tasks/:t` and `…/runs/:r` |
| L4 Agent trace | Observed turns, tool calls, knowledge deliveries, discovery, permission requests, judge rulings | Order and causation | new invocation route under the run |

- **Entering and leaving.** Click or Enter on a node enters it; the wheel or a pinch zooms continuously and, past a
  threshold over a node, the camera finishes the zoom and enters it (sketches 02/04). Zooming out past the minimum,
  Escape or the breadcrumb returns to the parent. Panning by drag or keyboard. With `prefers-reduced-motion` the
  transition is immediate.
- **Map/list toggle.** The map is the home page. The eye/list control of the sketches switches between the map and
  the existing list pages, which remain the accessible alternative T018 requires.
- **Status.** Completed green, in progress orange, failed or blocked red, pending neutral, abandoned or superseded
  grey. Colour is never the only signal: each node also carries an icon and a text label. The exact mapping from
  persisted statuses is part of the T018 contract.
- **Agent circles.** R, E and J above the node where the work happens at the current level (the project card at L0,
  the active phase at L1, the active task at L2, the active step at L3). The active circle shows the rays, animated
  only when motion is allowed. J appears only when a judge profile is configured. Deterministic stages (validations,
  formatting, commit) light a fourth circle **H** for Harness (D278), so the map never looks idle while Harness works.
  Clicking or zooming into a circle opens that agent's trace (§4); conversations open from bubbles or the reviewer's
  separate talk button (§6).
- **Live view.** A bounded activity projection refreshed by polling drives circles, statuses and bubbles at every
  level. Streaming is chosen only if the agreed experience needs it (existing T018 subtask).
- **Archives.** Query-only copies render the same map read-only, without bubbles that offer actions.

## 4. Agent trace graph (L4)

Clicking or zooming into an agent circle (or a step at L3) opens the trace of that invocation: observed turns, tool calls with name,
outcome (completed, error, denied) and duration, knowledge deliveries (T007 receipts), tool discovery and schema
loads (T008), permission requests (T010) and judge rulings (T009). Parallel tool calls of one turn fan out from it;
retries and failures stay visible as their own nodes. Missing telemetry appears as an explicit "not observed" node or
label; turns are never manufactured (TM14).

**Data gap to resolve in T018.** Today `trace-observation-1` stores per-invocation counters (turns, tool calls by
name, denials) and per-event records for broker tool calls and knowledge deliveries. The ordered sequence of native
turns and tool calls exists only in the retained native stream journal, whose bytes explicit retention can remove.
T018 must therefore define an additive **observed-step projection**: preferably derived once from the sealed stream
when the attempt settles and stored as bounded, sanitized trace events (source `measured`), so the graph survives
stream retention, backups and query-only consultation. That is a new event kind with its own decision, parity and
synthetic evidence; it does not reopen T006's completed contract.

## 5. Hand-drawn style

| Option | How | Trade-off |
|---|---|---|
| **A (accepted)** | Generate shapes at runtime with rough.js, the drawing engine Excalidraw uses, plus a bundled hand-drawn font | Faithful look; any size, colour and language; one small dependency to decide |
| B | Ordinary SVG shapes with an SVG turbulence/displacement filter and the font | No library; less faithful; filters cost rendering time on large maps |
| C | Assets drawn by the owner in Excalidraw and exported as SVG per theme | Personal touch; cards change size, text, language and status, so assets multiply; fits only fixed icons |

Option A details: SVG in the DOM (not a `<canvas>`), so every node is focusable, clickable and readable by assistive
technology; colours come from the existing CSS theme tokens, so light, dark and status colours need no extra assets;
each shape uses a seed derived from its stable entity ID, so lines do not jitter between refreshes. The owner does
not need to draw anything; owner-drawn SVGs remain possible for the fixed icons (sheet, bubble, rays). The hand-drawn
font is used for map labels only; documents, conversation panels and forms keep the normal UI font for legibility.
Embedding the Excalidraw editor itself is not proposed: it is a large editor, and the map is a read-only projection.

Adding rough.js and a font file requires an accepted decision before installation, with exact versions, license and
notice files in the package, offline serving and en/es glyph coverage (AGENTS dependency rule). Candidate fonts:
Excalifont or Virgil, both from Excalidraw under the SIL Open Font License; the licence is verified at decision time.
Pan, zoom and the layered layout of task graphs (tens of nodes per phase) are proposed in-house, without a layout or
zoom library; a dependency is reconsidered only with measured evidence.

## 6. Conversation bubbles and owner input to G13 (T017)

**Bubble.** An unresolved inbox item that needs an owner response and is attributed to an agent shows a comic bubble
next to that agent's circle. Ancestor levels aggregate it (the project card at L0 shows a bubble with a count).
Clicking it opens T017's conversation panel over the map, at any level and without leaving the current view.

Proposed kinds:

| Kind | Origin | Owner actions |
|---|---|---|
| Permission request | T010 | Allow once; grant standing (scoped, revocable); deny |
| Blocking question | T014 typed gap clarification; T016 durable owner question (`WAITING_FOR_OWNER`) | Typed answer, validated as current |
| Judge escalation | T009 duty outcome escalated to the owner | Decide or return with an instruction |
| Lifecycle confirmation | T015 phase awaiting closure/READY; T016 stops `LIMIT_REACHED`, `RECOVERY_REQUIRED`, `FAILED` | Inspect, confirm, resume, confirm stopped |
| Notification | Task completed, phase closed and similar | None: unread mark and inbox list, no bubble |
| Free conversation | Owner-initiated from the reviewer's separate talk button, not a bubble | The existing project chat (D083): questions, deterministic commands, proposals that become tasks only after confirmation |

**Free conversation context.** Only the reviewer offers free conversation, because the reviewer answers the project
chat (read-only); the executor and judge panels show their pending requests and history without a free composer.
Opened from inside the map, the conversation automatically includes the context of the element in view — phase,
task, run or step. A small removable tag states it ("The context of Task X will be included", with an ×); removing
the tag sends no element context. The included context is a bounded reference to the element (stable ID and accepted
revision or run evidence), delivered and recorded like any other knowledge delivery (D277/D288 receipts), never a
silent addition.

Every action is an ordinary guarded command with fresh revision, authority and READY checks; a bubble never carries
an approval and a stale one is refreshed instead of applied (D278, TM13). The panel states truthfully what happens
next: an answer is recorded and the workflow continues at its next boundary; there is no live agent process waiting
unless the data says so. Bubble text carries no sensitive content outside the authenticated UI (TM17); new mutations
keep the session, Host/Origin and CSRF guards (TM18). The global inbox list remains for items without a visible
agent and as the accessible alternative.

## 7. Responsibility split

No new task is proposed: G13 and G14 already belong to T017 and T018, and T018 already depends on T017.

- **T017** owns the taxonomy of §6, inbox items with read and resolved states, the conversation panel for each kind
  and the global list.
- **T018** owns the map (levels, zoom and click, status, agent circles, bubbles that open T017's panel), the
  documentation drawer, the L4 trace graph with the observed-step projection, the hand-drawn style decision, the
  accessible list alternative and archive parity.

**Documentation drawer.** Visible from L1 inward: a side panel with the project's document tree on the right and the
selected document in the centre, while the map stays visible and interactive on the left (sketch 08). It reuses the
existing documentation view read-only; by default it opens the document relevant to the current level (for example
the phase plan at L1–L2). Edits go through the existing documentation and knowledge views (T012/T013), never from the
drawer.

If T018's contract turns out too large when refined, it can be split (for example map and trace) as a recorded plan
revision with stable IDs.

## 8. Owner answers

Asked and answered on 2026-11-03; the answers are applied in §§3–7 and recorded as
[D297](../DECISIONS.md#d297--work-map-visual-direction-and-agent-conversation-entry-points).

| Question | Answer |
|---|---|
| Q1 — Style | **A**: rough.js and a bundled hand-drawn font; exact versions, licences and packaging decided at T018 before adding |
| Q2 — Harness | A fourth circle **H** for deterministic stages |
| Q3 — Level L3 | Steps of the latest run, with a selector for earlier runs |
| Q4 — Home | The map replaces the home page; the list is one toggle away |
| Q5 — Free conversation | Reviewer only, from a separate talk button; clicking or zooming into a circle opens its trace. Opened from a phase, task, run or step, the element's context is included by default behind a removable tag |
| Q6 — Order | Keep T015 → T016 → T017 → T018; no early map slice |
