# P002-T018 — Work-map contract and rendering decision

**Status:** **completed (design); accepted explicitly by the owner on 2026-11-04** with one addition, the source-record
links of §6.4, applied before acceptance. Decisions
[D304](../DECISIONS.md#d304--work-map-levels-cards-navigation-and-status-classes)–[D309](../DECISIONS.md#d309--accessibility-and-realistic-size-budgets-for-the-work-map)
are accepted. Design only: no source, schema, migration, API, OpenAPI, generated client, dependency or lockfile
change; nothing is implemented. Next: P002-T019. Numbering follows plan v0.4
([D303](../DECISIONS.md#d303--t018-split-by-responsibility-and-later-p002-tasks-renumbered)); records written before
D303 use the former numbers and are read through its table.

| Field | Value |
|---|---|
| Owner task | P002-T018 (design; owner gate G14) |
| Branch | `docs/p002-t018-work-map-contract` from `develop` at `eb5bb74` (2026-11-04) |
| Binds | T019 (backend), T020 (backend), T021–T023 (frontend), T024 (full stack) |
| Delivery route | Documentation → develop with the phase; 0.2.0 via protected main (D242/D253). Commit, merge and push only at the owner's request |
| Inputs | [D297](../DECISIONS.md#d297--work-map-visual-direction-and-agent-conversation-entry-points) and the [visual direction](P002-T018-visual-direction.md); D277, D278, D287–D289, D298, D302, D303; D029 (polling); [T001 §11–12](P002-T001-contracts.md#11-trace-knowledge-access-inbox-and-graph), [FL14](P002-T001-flows.md#fl14--observation-projection), [TM13–TM19](P002-T001-threat-model.md); B19–B20 |

## 1. Verification against the current code

The code was read at `eb5bb74` without changing it. These facts constrain the contract.

| Area | Fact in the code | Consequence |
|---|---|---|
| Native stream evidence | `adapters/streams.py` emits one `agent_event` per JSONL record. Records ≤ 16 KiB are stored verbatim as `original` in `managed_events`; larger ones as a byte reference into `stdout.bin`. Each read chunk is a `stream_bytes` event (offset, size, sha256) with `recorded_at` (D252) | The ordered native sequence is not only in retained bytes (inconsistency 1, §2). Chunk receipt times give measured timing |
| Retention | `storage/retention.py` removes only sealed `stdout.bin`/`stderr.bin` files and writes tombstones; history rows are never rewritten | `agent_event` rows survive; oversize records lose their bytes |
| Settlement | `operation_journal.settle_attempt` writes `invocation.observed` (`trace-observation-1`) only when the attempt has a `workflow_operations` row (task graph, phase graph, judge). Chat, definition, planning and bootstrap attempts have none | T019 must not depend on an operation existing |
| Clients | Claude `stream-json`: `assistant` messages (repeated per message id) with `tool_use` blocks, `user` `tool_result` blocks (`is_error`), terminal `result` with `num_turns` and `permission_denials`. Codex `exec --json`: `turn.started`/`turn.completed`/`turn.failed`, `item.started`/`item.completed` (`mcp_tool_call`, command and file items with status), no denials, no reported model, no usage after cancellation ([T002 §4](P002-T002-feasibility.md#4-observation-coverage-g05)) | Per-client derivation and explicit gaps (§6) |
| Trace storage | `trace_events` is insert-only, deduplicated by `dedupe_key`, with nullable `thread_id`/`operation_id`, `invocation_id`, source label and `trace-payload-1` bounds (strings > 1 KiB and payloads > 8 KiB offloaded, masked, to `trace_artifacts`). Indexes: thread, operation, root, kind/root | A natural home for steps; per-invocation keyset reads need an index (T019) |
| Invocation ledger | `usage_invocations` covers `managed_attempt`, `preparation_step` and `configuration_assistance`, with role, purpose, agent client, requested model/effort and frozen versions | Agent identity per invocation without a new source |
| Role → agent | `cli_agents.ROLES`: executor → executor; planner, reviewer, phase, chat, bootstrap, definition, planning, configuration → reviewer; judge → judge | Circle attribution (§5) |
| Receipts | `knowledge_deliveries` → `invocation_contexts` (requires `operation_id` in a graph thread and an accepted-revision snapshot). Envelope entity types are knowledge kinds plus revision, profile, code, result, draft | Chat element context cannot be receipted today (inconsistency 2) |
| Chat | `core/engine/chat.py`, `storage/chat.py`: read-only reviewer turns over a HEAD snapshot, context frozen at queue time (phase, checkout documents, run ids, previous turns), no graph thread | T024 boundary (§9) |
| Documentation view | `frontend/src/pages/Docs.tsx` reads checkout files through `/projects/{p}/documents/*` and carries drift, adoption and edit controls; `KnowledgeDocuments` renders from SQLite (D294) | Drawer source (inconsistency 3) |
| Archives | Query-only mode composes no project; home is a run-id entry; only `/runs/:id` is allowed ([flow](../flows/backup-consultation.md)); `usePoll` disables timers; T017's inbox reads restored files | Archive map (inconsistency 4) |
| Routes | `frontend/src/router.ts`: `/`, `/projects/:p`, `/projects/:p/phases`, `/projects/:p/phases/:code`, `…/tasks/:task`, `…/runs/:run`, `/runs/:id`, inbox, docs and chat routes; no invocation route | §4 |
| Statuses | Run/stage strings in `storage/managed.py`; `PhaseRead` statuses; `GRAPH_THREAD_STATUSES`, `OPERATION_STATUSES`, autonomous check constraints; knowledge `planned`/`withdrawn`; UI tones in `frontend/src/ui.tsx` (`ok`, `active` blue, `attention` amber, `danger`, `neutral`) | §5 |
| Dependencies | `roughjs` 4.6.6 (MIT) is already in `frontend/package-lock.json` as a mermaid 11.17.2 dependency, with its notice in `NOTICE-THIRD-PARTY.md` and a built lazy chunk `rough.esm-*.js` of 27,109 B (8,789 B gzip). No hand-drawn font exists offline | §10 |

## 2. Owner answers (2026-11-04)

Asked in five batches. Each question had options, trade-offs and a recommendation. Batch 1 covered the
inconsistencies between documents and code, which AGENTS requires to be raised before the design changes.

| # | Question | Answer |
|---|---|---|
| Q1 | Inconsistency 1: the T019 premise ("only in the retained stream journal") versus `agent_event` rows that survive retention | **Correct the rationale.** Keep T019: derive at settlement from `agent_event` rows plus stdout bytes while sealed. The corrected premise is recorded in D305; earlier records stay untouched |
| Q2 | Policy for runs settled before T019 | **No backfill.** Counters (when present) plus an explicit "steps not projected" label and a link to the run evidence |
| Q3 | Inconsistency 2: the chat element-context receipt has no T007 boundary | **Canonical chat boundary.** Each chat turn that carries element context is sealed through T007 (single-node chat thread, invocation operation and context). Knowledge receipts use the normal path; run/step evidence uses an additive `run_evidence` entity type. Only knowledge projects offer the tag |
| Q4 | Inconsistency 3: the documentation drawer source | **DB rendering, checkout fallback.** Knowledge projects use the canonical DB rendering, which also works in archives. Legacy projects use the read-only checkout view in ordinary mode only, with every edit/adoption control removed |
| Q5 | Inconsistency 4: archive navigation | **Map home plus run-id entry.** Read-only map L0–L4 from SQLite. Only map routes and their list views are unblocked |
| Q6 | L4 invocation URL | **`/projects/:p/invocations/:i`** for every lane; breadcrumb derived from the owner |
| Q7 | Map/list toggle | **`?view=list` plus a remembered choice** in this browser; map by default |
| Q8 | `/projects/:p` | **Keep the project page**; entering a project card goes to `/projects/:p/phases` |
| Q9 | Card density | **Compact cards plus a side inspector** |
| Q10 | Owner-waiting states | **Sixth class "waiting for you"**, with a hue clearly distinct from in-progress orange, a hand icon and a label. Red keeps the failure states |
| Q11 | Phase opening/check/closure involvement | **Plan · Check · Close slots** on the phase card |
| Q12 | Harness step nodes at L3 | **Validate, format, commit** |
| Q13 | Waiting hue | **Violet**, with lists aligned to the same six classes in T022 |
| Q14 | Bubble attribution | **Accepted mapping** (§5.3); an unresolvable source attaches to H, labelled "origin not attributed" |
| Q15 | Chat lane | **R with rays on the conversation's scope**, labelled "chat"; it coexists with task-lane circles |
| Q16 | Refresh | **Polling as proposed** (2 s active, 10 s idle, paused when hidden, off in archives); no streaming |
| Q17 | rough.js | **Direct dependency at exactly 4.6.6**, same lock integrity, no download |
| Q18 | Font verification | **Fetch authorized** (scratchpad only, nothing installed); results in §10.2 |
| Q19 | Realistic size | **Accepted as per-level maxima along one deep synthetic path**, not a Cartesian product; totals recorded (§12) |
| Q20 | Accessibility | **WCAG 2.2 AA as listed** (§11) |
| Acceptance | Review of the contract and D304–D309 | **Accepted** with one addition: each observed step links to its source `agent_event` record(s) through the existing event routes, so the original content can be read where it still exists, only in the authenticated UI. Oversize records whose bytes retention removed show "unavailable after retention", and the projection stays content-free (§§3, 6.2, 6.4, 7) |

## 3. Levels, cards and inspector (G14)

The map is a read-only projection (D278). It is not a workflow editor, a runtime topology or an executable graph
authority. Edges are data and never commands. A card shows a compact summary. Selecting or focusing a node opens a
side **inspector** with the full fields. On narrow screens the inspector is a bottom sheet. Every counter declares
its meaning and source (`supplied`, `reported`, `derived`, `measured`, `absent`) and shows "not observed" instead of zero
when absent (INV-09).

| Level | Node | Card (compact) | Inspector (full) | Edges |
|---|---|---|---|---|
| L0 | Project (registered; archive mark) | Name, status class, mode badge (manual / autonomous run status), R/E/J/H circles, primary counter **phases closed/total**, error mark, aggregated bubble count | Active phase (code, title, status); autonomous run status and bounds summary; configured agent per role (client, model, effort, judge profile); active invocations; last activity; failure summary | — |
| L1 | Phase (accepted roadmap identity; operational instance when opened) | Code, title, status, **Plan · Check · Close** slots with the actors that actually took part and their latest status, circles on the active phase, primary counter **tasks committed/total**, error mark, bubbles | Objective; criteria count and coverage; latest check verdict and READY state; plan/closure operation history; tag; documents link (drawer) | Roadmap order |
| L2 | Task instance of the phase plan | Code, title, status of the latest run (or pending), circles on the active task, primary counter **attempt n / revision limit**, error mark, bubbles | Problem/expected result; runs count and selector; revision rounds; latest stage; replaced or replacing tasks (D296); acceptance/commit state | `depends_on`; `replaces` dashed |
| L3 | Step of the selected run (latest by default): agent invocation or H stage (validate, format, commit) | Role circle, label (for example "Executor #2"), status, primary counter **duration** (measured), error mark | Frozen agent identity (client and version, requested model and effort, reported model when the client reports one); harness attempt; revision round; termination class; native turns, tool calls by name, denials, deliveries, discovery/schema loads, permission requests, rulings, usage presence (all with source); for H stages, JUnit summary or commit/export state | Step order; run selector for earlier runs |
| L4 | Observed step of one invocation (§6) and related records | Turn node with its tool calls fanned out (name, outcome, duration); message, reasoning and "not observed" nodes; deliveries, discovery, permission requests and rulings in position | Step fields (§6.2); a **source record** link per step to its original `agent_event` record(s) (§6.4); receipt, artifact and ruling links; counters versus steps, each with its own source | Order, causation, parallel group |

Counters at L0–L2 are derived from persisted rows only. "Committed" means a task whose latest run is `COMMITTED`.
Revision limit is the run's `revision_limit` (supplied). The L3 duration is the capture's
`wall_duration_seconds` for invocations and the stage's event times for H stages. Accounting amounts are not shown;
they belong to T025.

## 4. Navigation

| Level | Route | Breadcrumb | List view (`?view=list`) |
|---|---|---|---|
| L0 | `/` (map replaces the home page) | Projects | Existing project list |
| L1 | `/projects/:p/phases` | Projects › *project* | Existing phases page |
| L2 | `/projects/:p/phases/:code` | … › *phase code* | Existing phase page |
| L3 | `/projects/:p/phases/:code/tasks/:task` (latest run) and `…/runs/:run` (selected run) | … › *task* › *run* | Existing task and run pages |
| L4 | **New:** `/projects/:p/invocations/:i` for every lane | Derived from the owner: … › *task* › *run* › *role #n*; chat: Projects › *project* › Chat › *role #n*; phase operation: … › *phase* › Check/Close › *role #n* | Accessible trace list (T023) |

- `/projects/:p` keeps its project page. Entering a project card navigates to L1. Existing links keep their meaning.
- **Entering and leaving:** click or Enter enters a node; wheel or pinch zooms continuously and, past a threshold over
  a node, finishes the zoom and navigates through the router and browser history. Escape, zooming out past the
  minimum or the breadcrumb returns to the parent. Drag or arrow keys pan. Transitions are immediate under
  `prefers-reduced-motion`.
- **Map/list:** the same path renders either view. `?view=list` selects the list and `?view=map` the map. Without
  the parameter, the last choice remembered in this browser applies (local storage wrapped in try/catch, never
  authority), falling back to the map. The eye/list control writes the parameter.
- **Circles open traces:** clicking or zooming into a circle opens L4 for that role's most recent invocation within
  the element in view. A circle without an invocation in scope is labelled and inert. Bubbles open T017's panel over
  the map without navigation. The reviewer's separate talk button opens the chat (§9).
- **Archives (query-only):** the archive home is the read-only map L0 beside the existing run-id entry. Map routes and
  their list views read SQLite only, with no checkout, registry composition or polling. Operational pages stay
  blocked. There are no action bubbles or talk button; an unresolved request shows a static count marker that opens
  T017's read-only item.

## 5. Status, actors and bubbles

### 5.1 Status classes

Six classes plus a fallback. Colour is never the only signal: each node carries an icon and a text label (the
translated status), and the raw code is in the accessible description.

| Class | Colour token (light/dark) | Icon | Meaning |
|---|---|---|---|
| done | green (existing `--ok`) | check | Completed successfully |
| progress | orange (new token pair, T021) | arrow (static) | Work is running or queued |
| waiting | violet (new token pair, T021) | hand | Waiting for the owner; not a failure |
| failed | red (existing `--danger`) | cross | Failed, blocked, interrupted or uncertain |
| pending | neutral (existing `--neutral`) | empty circle | Not started |
| inactive | grey (muted neutral) | dash | Abandoned, superseded, withdrawn, cancelled or stopped |
| unknown | neutral | question mark | A persisted value without a mapping; the label shows the raw code |

T022 moves the shared `Status` component to these classes so lists and map agree (lists' in-progress tone changes
from blue to orange and attention to violet). Contrast is ≥ 4.5:1 for labels in both themes (§11).

### 5.2 Mapping from persisted statuses

| Entity (source) | done | progress | waiting | failed | pending | inactive |
|---|---|---|---|---|---|---|
| Run (`managed_runs.status`) | COMMITTED, COMPLETED, DONE | QUEUED, ACTIVE, PLANNING, PREPARING, EXECUTING, REVIEWING, VALIDATING, COMMITTING, ANSWERING, DISCOVERING, CHECKING, INTENT | ACCEPTANCE_READY | BLOCKED, REVISION_LIMIT, RECOVERY_REQUIRED, INTERRUPTED, FAILED, ABORTED, REFUSED | — | STOPPED |
| Attempt result (stored, upper-cased) and termination class | COMPLETE, COMPLETED; `completed` | running attempt (no result; process PENDING/RUNNING); `pending` | — | PARTIAL, INVALID, FAILED, TIMEOUT, TIMED_OUT, INTERRUPTED, REFUSED; process UNCERTAIN; `failed`, `partial`, `invalid_stream`, `timeout`, `output_guard`, `interrupted`, `refused` | — | CANCELLED; `cancelled`; ledger launch `not_invoked` |
| Phase instance (`managed_phases.status`) | CLOSED | ACTIVE, CHECKING, CLOSING | READY_TO_CLOSE, NEEDS_RECONCILIATION | BLOCKED | — | ABANDONED |
| Phase or task identity (knowledge) | — | — | — | — | `planned` without instance/run | `withdrawn`; task replaced by a successor (D296) |
| Workflow operation | COMPLETED | INTENDED | — | FAILED, UNCERTAIN | — | ABANDONED |
| Graph thread | COMPLETED | RUNNING | WAITING | QUARANTINED, RECOVERY_REQUIRED, FAILED | — | CANCELLED, REVOKED |
| Autonomous run | COMPLETED | RUNNING | WAITING_FOR_OWNER, PAUSED, LIMIT_REACHED | FAILED, RECOVERY_REQUIRED | — | REVOKED |
| Permission request / record | GRANTED | — | PENDING | — | — | DENIED, EXPIRED, REVOKED |
| Judge ruling | VALIDATED | — | ESCALATED | FAILED, UNCERTAIN | — | — |
| H commit step (`managed_commits`) | COMMITTED | INTENT | — | — | — | INVALIDATED |
| H validation / format step | passed | running | — | failed or unreadable report | — | not configured |
| Ledger launch `unknown_execution` | — | — | — | failed ("execution unknown") | — | — |

A project's class is derived: failed if its autonomous run or active phase is failed, or its latest run of any active
task is failed and unresolved; else waiting if any unresolved owner request or waiting state exists; else progress
if any invocation or H stage is active; else done if every roadmap phase is CLOSED; else pending. Phase-operation
slots use their latest operation's status through the same table. T020 and T022 include a parity test that
enumerates the persisted vocabularies (constants, check constraints and the values written in `storage/managed.py`)
and fails when a value lacks a mapping; unmapped values render as `unknown`, never as a guessed class.

### 5.3 Actors and circles

| Circle | Roles (ledger `role`) | Shown |
|---|---|---|
| R | reviewer, planner, phase, chat, bootstrap, definition, planning, configuration | Always |
| E | executor, project preparation steps | Always |
| J | judge | Only when the project has a judge profile, or on an element where a judge invocation actually occurred (honest history) |
| H | Harness deterministic stages: validation, native formatter, commit/export writer, phase deterministic controls, autonomous supervisor | Always; lit only while deterministic work is active |

- Circles sit on the element where work happens at the current level: the project card at L0, the active phase at L1
  (and each Plan · Check · Close slot shows its own actors), the active task at L2, the active step at L3. L4's header
  shows its single actor.
- **Rays** mark every active invocation the data reports: attempt started without a result and process `PENDING` or
  `RUNNING`; for H, an active job in a deterministic stage. Rays animate only when motion is allowed.
- **Chat lane:** an active chat invocation shows R with rays and a "chat" label on its conversation's scope (project,
  phase or task run). It coexists with the task lane, so two active circles can appear at once.
- **Identity:** the inspector shows the current configuration per role and, for an invocation, its frozen identity
  from `usage_invocations`. The client-reported model appears separately with its source; it is never inferred.

**Bubbles** (unresolved T017 items other than notifications) sit beside the circle of the actor that raised them:

| T017 kind | Circle |
|---|---|
| Permission request | Role of the attempt that asked (R, E or J) |
| Task blocking question (T014 gap) | R |
| Autonomous owner question | R |
| Judge escalation | J |
| Lifecycle confirmation (`READY_TO_CLOSE`; autonomous `LIMIT_REACHED`, `RECOVERY_REQUIRED`, `FAILED`) | H |
| Source attempt not resolvable | H, labelled "origin not attributed" |

Ancestors show an aggregated count by kind. A bubble carries only the T017 item identity; the panel re-reads the item,
and a stale item is refreshed instead of applied (D278, TM13).

## 6. Observed-step projection (T019)

### 6.1 Premise and scope

The parsed native sequence already persists as `agent_event` rows, but those rows are verbatim and unsanitized.
Records over 16 KiB exist only as references into `stdout.bin`, whose bytes retention can remove, and reading them
needs per-client parsing on every read. The projection derives once, from the sealed evidence, a **bounded, sanitized,
client-neutral and ordered** step sequence that survives retention, backup and query-only restore (D305). It is
additive: `trace-observation-1`, `invocation.observed`, D287's operation semantics and the `metrics-1` counters are
unchanged. The ledger stays the only source of charges.

Scope: every settled **managed attempt** (task, phase, chat, definition, planning, bootstrap, judge and roadmap
review lanes), whether or not it has a workflow operation. Preparation steps and configuration assistance are not
map elements; their L4 shows "steps not projected for this lane".

### 6.2 Event kinds and fields

Two new `trace_events` kinds, source `measured` unless a field says otherwise, format `observed-step-1`, written
through `trace-payload-1`:

- `invocation.step`: one per step. `dedupe_key = step:{invocation_id}:{seq}`; `invocation_id`, `root` and, when
  present, `thread_id`/`operation_id` set.
- `invocation.steps_sealed`: one per invocation. `dedupe_key = steps:{invocation_id}`. It is the completion marker and
  holds counts per kind and outcome, coverage, step bound hit, derivation version, client and client version, the
  stdout sha256/size and the last `agent_event` record number consumed.

| Field | Meaning |
|---|---|
| `seq` | Dense 0-based position in the invocation, in native record order |
| `kind` | `turn`, `tool_call`, `message`, `reasoning`, `not_observed` |
| `unit` (turn) | `claude_message` (one assistant message id) or `codex_turn` (`turn.started` … `turn.completed`/`turn.failed`); the two are different units and are labelled as such |
| `parent_seq` | Turn that contains the step (tool calls, messages, reasoning) |
| `call_id` | Native tool use or item id; correlates call and result |
| `tool` | Name; for MCP, server and tool; `origin` `native`, `harness_broker` or `other_mcp`. A harness broker call links its logical/broker trace events by id when present (D289) |
| `arguments` | Size and sha256 of the native arguments, plus a summary of at most 256 characters, masked before truncation; never the full input |
| `outcome` | `completed`, `error` (Claude `is_error`; Codex failed status), `denied` (Claude `permission_denials` by tool use id), `cancelled_in_flight`, `not_observed` (no result before the stream ended) or `unclassified` with the raw status code |
| `result` | Size and sha256 only; result content is not stored |
| `message` / `reasoning` | Presence, size, sha256 and `final` for the answer; no text |
| `started_at`, `finished_at`, `duration_ms` | Receipt time of the chunk containing each record's terminating newline (`stream_bytes.recorded_at`), labelled `timing: chunk_receipt`; a client-supplied timestamp, if one ever appears, is recorded separately as `reported` |
| `parallel` | Tool calls of one turn whose intervals overlap share `parent_seq`; the maximum concurrency per turn is counted |
| `reason` (`not_observed`) | `invalid_record`, `partial_tail`, `oversize_record_unavailable`, `cancelled_in_flight`, `unsupported_event`, `unsupported_client`, `no_stream`, `step_bound_reached` |
| `source_record` | The `agent_event` row(s) the step derives from, at most 4 per step (for example a tool call and its result): `{run_id, attempt_id, sequence, record, oversize}`, where `sequence` is the run event sequence, `record` the parser's record number and `oversize` true for a byte reference into `stdout.bin`. References only, never content (§6.4) |

### 6.3 Derivation and recovery

- **When:** the settlement transaction (the one storing the attempt result, or `confirm_stopped`) records a
  `steps_pending` marker. A deterministic projector then derives the steps in its own writer transactions as an
  idempotent, recoverable effect. This keeps settlement bounded and avoids parsing megabytes under the writer lock.
  No inference is repeated.
- **Input:** the attempt's sealed evidence only: `agent_event` rows in record order, `stream_bytes` chunks, the
  `stdout.bin` bytes for oversize records (verified against chunk hashes and the capture's artifact sha256) and the
  process capture (status, permission denials). Nothing from the checkout, a provider or a re-run.
- **Idempotency:** dedupe keys make an identical replay a no-op; a different payload under the same key is an
  integrity failure, reported, never overwritten. A crash restarts derivation from `seq` 0 and converges. The
  sealed marker is written last.
- **Retention guard:** explicit retention refuses to remove an attempt's streams while its projection is pending,
  and names the attempt. After the marker, retention is unchanged and the steps remain.
- **Truthful gaps:** malformed lines, a partial tail, cancellation inside a turn, unsupported events or clients and a
  missing stream become `not_observed` steps at their position. An open turn or call at stream end is never closed
  as completed. Turns are never manufactured. Codex permission denials and per-request turns are absent and labelled.
- **Bounds:** at most 10,000 step events and 4 MiB of payload per invocation. Every event obeys `trace-payload-1`.
  On reaching a bound, one `not_observed` step with reason `step_bound_reached` carries the remaining counts by kind.
- **Sanitization:** `trace-payload-1` key masking and secret patterns apply to names, summaries and reasons;
  argument summaries are masked before truncation; result and message content is excluded. The residual TM17 risk
  (secrets the owner committed into project content) remains.
- **Earlier runs:** attempts settled before T019 are not backfilled (Q2, D287). Their L4 shows the
  `trace-observation-1` counters when present, the pure `observe` evaluation from the sealed capture otherwise
  (labelled `derived`, not persisted), an explicit "steps not projected: settled before observed steps existed"
  label and a link to the existing run evidence.
- **Backups and archives:** steps live in `trace_events`/`trace_artifacts`, which backups already include and verify.
  Query-only reads need no checkout, provider or registry.
- **Parity:** T019 adds an index for keyset reads by invocation if its measurements need it, updates DDBB-DIAGRAM,
  `docs/flows/` (operation journal, task run, backup consultation) and adds en/es keys for the reasons.

### 6.4 Source records (owner addition at acceptance)

Each step links to its original `agent_event` record(s) through the existing event routes. The owner can then read
the original message, reasoning, tool input and result where they still exist, as today and only in the
authenticated UI. The projection itself stays content-free.

- Every managed lane (task, phase operation, chat, definition, planning, bootstrap, judge, roadmap review) is a
  managed run, so a step's records are the run's `managed_events` rows. They are read with the existing
  `GET /api/managed/runs/{run_id}/events?after={sequence - 1}&limit=1`, which pages by run sequence. Phase checks and
  closures also run as managed runs, so their agent records are run events too. The phase event route
  (`/phases/{phase_id}/events`) holds phase facts, not native records; the inspector links it only for the phase
  operation a step belongs to.
- Records of 16 KiB or less show their stored `original` as today. An oversize record (`original_reference`) is read
  as its byte range through the existing `GET /api/managed/runs/{run_id}/attempts/{attempt_id}/logs` bounded view while
  the sealed bytes exist. When the retention audit records the attempt's stdout as removed, it shows **"unavailable
  after retention"** with the reference's size and sha256; nothing is reconstructed or summarised in its place.
- No new route or copy of content is introduced. The links reuse the existing routes and guards, the session and
  Host/Origin checks and query-only archive reads (the restored database keeps the rows; restored stream bytes
  follow the existing backup rules). The existing pages may render the original content, which is today's evidence
  surface and has today's sanitization limits (TM17 residual). Map projections, bubbles and the activity poll never
  carry it.

## 7. Read projections and API (T020)

Versioned, read-only `GET` routes under `/api/managed/map/` with OpenAPI and generated client parity. They are
projections (FL14): rebuildable, never authority, with no mutation route and no execution through edges.

| Route (indicative; T020 fixes the final names) | Content | Page bound |
|---|---|---|
| `map/projects` | L0 cards and inspector fields | 100 projects |
| `map/projects/{p}/phases` | L1 nodes, roadmap edges, Plan · Check · Close slots | 200 phases |
| `map/projects/{p}/phases/{code}/tasks` | L2 nodes, `depends_on` and `replaces` edges | 300 nodes and their edges |
| `map/projects/{p}/phases/{code}/tasks/{task}/runs` | Run selector (latest first) | 50 per page |
| `map/projects/{p}/runs/{run}/steps` | L3 invocations and H stages | 200 per page |
| `map/projects/{p}/invocations/{i}` and `…/steps`, `…/related` | L4 header; observed steps, each with its `source_record` references resolved to existing event-route and attempt-log targets plus availability (`available`, `unavailable_after_retention`) (§6.4); receipts (T007), discovery/schema loads (T008), permission requests (T010), rulings (T009), artifact links | 200 per page |
| `map/activity` | Activity summary for polling: version token per requested scope, active invocations, bubble counts by kind | ≤ 8 KiB idle |

- **Keyset pagination:** an opaque cursor bound to project, level, scope and version. A foreign or malformed cursor
  is refused. Lazy history: earlier runs, older steps and related records load on demand. Nothing decodes full
  run histories; reads use projections and indexed rows.
- **Refresh and gaps:** each level response carries a `version` token (the highest relevant source sequence). The
  activity poll returns current tokens. A changed token reloads that level's first page. A page cursor from a
  superseded version returns `409 cursor_stale`, and the client reloads the snapshot (D029 gap recovery).
- **Isolation:** every query is filtered by the project's root; identifiers of another project return 404 without
  revealing existence. Existing session and Host/Origin guards apply.
- **Bubbles:** aggregation reuses T017's projection (unresolved, non-notification items) with §5.3's attribution.
  It returns item identities and counts only.
- **Archive parity:** the same routes in query-only mode, from SQLite only, with `read_only_archive` in responses and
  no action affordances.
- **Absent telemetry:** every counter and step keeps its source and coverage; missing data is labelled, never inferred.

## 8. Refresh decision

**Polling** (D029, D278; Q16). One activity-summary poll per visible level every 2 s while anything in scope is
active, and every 10 s when idle. It pauses when the tab is hidden and is off in archives. Version changes trigger
level snapshot reloads. Following an autonomous run lags by at most about 2 s, which meets the agreed experience
("follow in real time" at turn granularity). Streaming (SSE/WebSocket) is not chosen: it would add a long-lived
endpoint, reconnection and gap logic and TM18 surface without a measured need. It is reconsidered only with
measured evidence.

## 9. Contextual reviewer conversation (T024)

- The map shows a separate **talk button** for the reviewer only. In knowledge projects, opened from a phase, task,
  run or step, it shows a removable tag ("The context of *Task X* will be included" ×). Removing the tag sends no
  element context. Legacy projects open the chat without a tag and say why. Executor and judge panels have no free
  composer.
- **Reference:** `{kind, project, stable_id or run/invocation id, revision_id (knowledge) or evidence digest (run,
  step)}`. The server refuses foreign references and stale ones (a knowledge revision that is not the current
  accepted revision, or a digest that no longer matches); the client refreshes the tag.
- **Boundary (Q3):** a chat turn carrying element context is sealed through T007: a single-node `chat-turn` graph
  thread, an `agent_invocation` operation and an invocation context over the accepted revision's snapshot. The chat
  keeps its read-only HEAD snapshot and does not take the checkout lock; `managed_jobs` remains the only scheduler.
  Turns without element context keep today's path.
- **Receipt:** the bounded element context (≤ 16 KiB, rendered by the existing canonical renderer for knowledge, or a
  bounded run/step summary from T020's projection, framed as evidence, never instructions; TM01) is an
  `initial_context` delivery with one receipt per delivered reference. Knowledge kinds use the existing entity
  types. Run and step evidence uses an additive envelope version (`knowledge-delivery-3`) with entity type
  `run_evidence`; earlier formats are unchanged. Invocation accounting is the existing ledger row.
- **Guards:** the submission with an element reference keeps session, Host/Origin and CSRF guards. Chat commands
  and proposals still need confirmation. In archives the talk button is absent and the API returns
  `409 restored_read_only`.

## 10. Rendering dependency decision (installation in T021)

### 10.1 rough.js

`roughjs` **4.6.6**, MIT (© 2019 Preet Shihn), becomes a direct frontend dependency pinned exactly (`"roughjs":
"4.6.6"`). The lock entry is already present with integrity
`sha512-ZUz/69+SYpFN/g/lUlo2FXcIjRkSu3nDarreVdGGndHEBJ6cXPdKguS8JGxwj5HA5xIbVKSmLgr5b3AWxtRfvQ==`, together with its MIT
dependencies `hachure-fill` 0.5.2, `path-data-parser` 0.1.0, `points-on-curve` 0.2.0 and `points-on-path` 0.2.1. The
notice is already in `NOTICE-THIRD-PARTY.md`. The built chunk already ships (27,109 B; 8,789 B gzip) and the map
shares it, so the expected bundle delta is about zero apart from the engine code. T021 verifies that mermaid's range
still resolves to the same copy, that the lock is otherwise unchanged, and measures the build delta. No download is
needed.

### 10.2 Hand-drawn font: Excalifont

Fetched on 2026-11-04 with the owner's authorization into the session scratchpad only (nothing installed, committed
or served): the latest `excalidraw/excalidraw` release, the `packages/excalidraw/fonts/Excalifont` listing and files at
that tag (plus the parent `fonts` directory listing, to look for a licence file), and the `excalidraw/virgil` listing,
licence and woff2.

| | Excalifont (accepted) | Virgil (rejected alternative) |
|---|---|---|
| Source | `excalidraw/excalidraw` tag **v0.18.1** (published 2026-04-21), `packages/excalidraw/fonts/Excalifont/` | `excalidraw/virgil` commit `3d4c829dc85b455d4646631ac52bc1517df04217` (2024-09-20) |
| Files | `Excalifont-Regular-a88b72a24fb54c9f94e3b5fdaa7481c9.woff2`: Latin, 24,956 B, sha256 `e4423b318e11432aff2e6e865e300b7ca270f92321a3f56632268fede01c1b48`. `Excalifont-Regular-be310b9bcd4f1a43f571c46df7809174.woff2`: Latin Extended-A, 12,220 B, sha256 `4fb8ad69be9aeac5664d99e5aa3a68a27ea40c98943b80387f7cd55c034fcc93` | `Virgil.woff2`, 61,248 B, sha256 `9976295bfe709bdea64839a4d4e9a1d436dd6eb67538399a5a0e8b8fadbcf1cf` |
| Licence | SIL OFL 1.1, embedded in the font's name table: "Copyright (c) 2024 by Excalidraw. All rights reserved."; designers "Your Own Font Foundry (Virgil); Ján Filípek / DizajnDesign (Excalifont, modifications)"; trademark note "Excalifont is a trademark of Excalidraw". No Reserved Font Name is stated. No separate licence file exists in the directory | SIL OFL 1.1 (`LICENSE.md`, sha256 `a3ac9cdc…`), "© 2021 – Present, Ellinor Rapp, with Reserved Font Name Virgil" |
| en/es coverage | The Latin subset alone maps 212 code points and covers the 125 required ones (Basic Latin, áéíóúüñ ÁÉÍÓÚÜÑ ¿¡ «» · — – … º ª € ‘’ “” •); all seven subsets map 561 | 527 code points; all 125 covered |
| Bundle | 24,956 B always; +12,220 B only when Latin Extended-A characters appear (`unicode-range`) | 61,248 B |

**Decision (D308, accepted):** Excalifont v0.18.1, with only the two Latin subsets shipped unmodified. The browser
falls back to the UI font for other scripts (Cyrillic, Greek, CJK) in user-provided labels. Virgil is rejected: it is
larger, its Reserved Font Name constrains any subset, and Excalidraw's current default is Excalifont.

**Packaging and serving (T021):** with its own explicit network authorization, T021 fetches the same two files at
the same tag and verifies the sha256 values above. It places them in the frontend sources so Vite emits them as
hashed assets in the built UI. It adds an `OFL-1.1` licence text with the Excalifont copyright and attribution: next
to the fonts in the built assets and as a fonts section in `NOTICE-THIRD-PARTY.md`, which is already in the wheel's
`license-files`. It then verifies wheel and sdist members, the `font/woff2` content type from the existing static
handler and offline serving (no CDN, no runtime network). The font is used for map labels only, with
`font-display: swap`. Coverage was checked by reading each file's `cmap` offline with a scratch Node script (zlib
brotli; not committed). T021 repeats the check on the installed bytes.

## 11. Accessibility (T021–T024)

WCAG 2.2 AA for the map and trace:

- Every node is a focusable SVG element with an accessible name: kind, code, title, status text, active actors and
  bubble count. The trace list and the existing list pages are equivalent alternatives.
- Full keyboard operation: arrows move between nodes, Enter enters, Escape leaves, +/− zoom, Tab reaches the toolbar,
  inspector and bubbles. Focus is visible and never trapped.
- Status is never conveyed by colour alone (§5.1). Label contrast is ≥ 4.5:1 in light and dark themes, including the
  new orange and violet tokens.
- No motion under `prefers-reduced-motion`: immediate transitions, static rays.
- A polite live region announces status changes in view, throttled to one summarised announcement at most every 10 s.
- en/es catalogue parity for every label, reason and status.

## 12. Realistic-size budgets (T019–T024)

The synthetic fixture is one deep path with per-level maxima (Q19). Siblings at each level are leaves without
descendants. Each level covers every status class of §5.2 and missing-telemetry cases.

| Level | Rows |
|---|---|
| Projects (L0) | 25 (one deep) |
| Phases of the deep project (L1) | 40 |
| Tasks of the deep phase (L2) | 80 |
| Runs of the deep task | 30 |
| Invocations (managed attempts and ledger rows) of the deep run | 40 |
| Observed steps of the deep invocation | 5,000 (plus one sealed marker per invocation that has steps) |
| Open inbox items | 300 |

Budgets on the development machine, each measured by the owning task. A miss is a finding, not a silent relaxation:

| Budget | Value | Owner task |
|---|---|---|
| Projection page latency | p95 ≤ 150 ms | T020 (and T019 for step pages) |
| Idle activity poll response | ≤ 8 KiB | T020 |
| First L2 map render (80 nodes) | ≤ 500 ms | T021/T022 |
| Pan and zoom | ≥ 50 fps at 200 visible nodes | T021 |
| 5,000-step trace | Usable through lazy pages of ≤ 200 | T019, T020, T023 |

## 13. Threat controls

| Threat | Designed control | Verified by |
|---|---|---|
| TM13 stale or replayed action | Bubbles carry only the T017 item identity; the panel re-reads it; actions use T017's guarded commands with fresh checks; stale items refresh instead of applying; archives have no actions | T022, T024 |
| TM14 misleading telemetry | Source and coverage on every counter and step; explicit `not_observed` steps; units labelled per client; chunk-receipt timing labelled; steps never reconcile or overwrite reported counters; no backfill; receipts mean availability | T019, T020, T023 |
| TM15 resource exhaustion | Step and byte bounds per invocation; `trace-payload-1`; keyset pages ≤ 200 and per-level node caps; small activity poll, paused when hidden; no full-history decoding; derivation outside the settlement transaction | T019, T020, T021 |
| TM17 secrets or private content | `trace-payload-1` masking; argument summaries masked before truncation; no tool result or message content; bubbles and map responses carry codes and identities, not agent text; element context only inside the authenticated chat | T019, T020, T024 |
| TM18 local API misuse | Map routes are read-only `GET` behind session and Host/Origin guards; the only new mutation (chat with element reference) keeps CSRF; foreign projects and cursors are refused; archives return 409 | T020, T024 |
| TM19 dependency supply chain | Exact versions; rough.js already locked with integrity; font files pinned by tag and sha256; OFL notice packaged; offline serving; no CDN or runtime network | T021, T029 |

## 14. Obligations by task

| Task | Must deliver and verify |
|---|---|
| T019 | §6: event kinds, per-client derivation, `source_record` references (§6.4), recoverable projector, retention guard, bounds, sanitization, gaps, no backfill, backup/archive reads; fake-CLI fixtures per client (parallel calls, errors, denials, malformed and truncated streams, cancellation), crash/replay idempotency; DDBB/flow parity |
| T020 | §§5, 7, 8: per-level projections and API, source-record resolution and availability (§6.4), status parity test, attribution, bubbles over T017, refresh tokens and `cursor_stale`, isolation, archive parity, §12 latency and poll budgets; OpenAPI and client types |
| T021 | §§10, 11, 12: dependency adoption and font packaging with notices, new colour tokens, SVG engine, camera, zoom-enter through routes, seeds from stable IDs, reduced motion, fps budget |
| T022 | §§3–5, 8: L0–L3 home map, list toggle and `?view`, shared `Status` classes on lists, circles and rays, chat lane, bubbles and aggregation, polling, archive map home with run-id entry |
| T023 | §§3, 4, 6: L4 trace graph and list, lazy history, related records, source-record links with "unavailable after retention", "not observed" nodes, earlier-run label; documentation drawer per Q4 with default documents per level |
| T024 | §9: talk button and tag, reference validation, canonical chat boundary, `knowledge-delivery-3` receipts, guards; OpenAPI and flow parity |

## 15. Verification and delivery

- **Checked:** contract facts against the code at `eb5bb74` (files named in §1); the router, list pages, documentation
  view, chat context, archive consultation, retention, backup references and status vocabularies; rough.js lock,
  licence, notice and built chunk size; Excalifont and Virgil licences, hashes and en/es `cmap` coverage from the
  authorized fetch. `scripts/check-docs` (result in STATE/NEXT_STEPS after the run).
- **Not checked:** nothing was built, installed, run or rendered; no harness, agent or provider was used; no product
  test ran. Font rendering quality, metrics and the visual look of rough.js shapes are not evaluated (T021's owner
  visual review). Whether newer Claude/Codex versions emit per-event timestamps or other item types is not verified.
  The legal reading of the OFL obligations is a factual summary, not legal advice.
- **Owner acceptance (2026-11-04):** the contract and D304–D309 are accepted with the §6.4 addition.
  `scripts/check-docs` passed again after the addition. Commit and merge are pending until the owner asks.
  T018 is complete; next is **P002-T019**.
