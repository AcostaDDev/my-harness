# P002-T001 — Scope adoption and authority contracts

Status: **accepted design**, 2026-10-29, formalized at the owner's explicit authorization of P002-T001 against
`a000e03` (`develop`; released and installed code `v0.1.9`). Implementation belongs to T002–T023. No runtime, schema,
API, dependency, prompt, configuration, catalogue or UI change exists; the product behaves as 0.1.9.
Authority: [D268–D279](../DECISIONS.md#d268--p002-scope-complete-roadmap-autonomy-and-evolving-plan-baseline).
Companion records: [flows, guards and recovery](P002-T001-flows.md) and [threat model](P002-T001-threat-model.md).
Basis: [design basis](P002-design-basis.md) B01–B24 and the [discussion](P002-autonomous-mode-discussion.md); where they
differ, the owner's later instructions prevail over earlier recommendations.

Owner/delivery: P002-T001, branch `docs/p002-t001-contracts` from `develop` at `a000e03`; documentation only. Route:
topic → `develop` when authorized, then part of the **0.2.0** phase release (D253). T001 has no individual release,
tag, publication or installation. Delivery status is recorded in [§16](#16-verification-and-delivery).

## 1. Adoption and status vocabulary

The owner adopted the draft v0.2 plan and design basis as the **evolving baseline** of P002 and authorized their
documentary formalization in this task. With the refinements in [§14](#14-plan-refinements-v03) the plan becomes
**v0.3**. This adoption does not authorize source work, T002, dependency installation, harness or agent execution.

| Label | Meaning |
|---|---|
| **Implemented (0.1.9)** | SPECIFICATION §§1–13, ARCHITECTURE §§1–12, `docs/flows/`, DDBB-DIAGRAM and the decisions they cite. They stay in force until the owning task implements the replacement and updates them with parity. |
| **Accepted design** | Owner direction, or a T001 resolution, recorded in D268–D279 and this document. Binding on the implementing tasks; it is not behavior and is never reported as implemented. |
| **T001 resolution** | A detail the owner had not decided separately, resolved here from the owner's directions and preserved guarantees. Listed in [§13](#13-t001-resolutions-for-owner-review) for owner review before integration. |
| **Open gate** | A question assigned to a named task in [§12](#12-open-gate-register). Resolving it with an unrecorded assumption is a defect. |

Recommendations in the basis or discussion that are not restated here or in the decisions are not adopted. The
contracts describe projects managed by the product; this repository remains hand-developed with Markdown authority.

## 2. Supersession map

"Takes effect" means when the owning task implements the change and updates the implemented documents. Only D156 and
D233's Continuous Mode description are superseded immediately, because they were reservations without behavior.

| Current contract | P002 accepted design | Takes effect | Owner |
|---|---|---|---|
| D156: continuous mode with scope and budget; stops on any question or out-of-scope change | D268/D276: complete authorized roadmap, delegated judge duties, local bounds, optional caps | Now (decision); behavior T016 | T016 |
| D233: Continuous Mode description | D268; the 0.2.0 target is retained (D253) | Now | — |
| SPEC §1: the user accepts requirements, architecture, sensitive permissions and results | Manual mode unchanged; autonomous mode delegates bounded classes at start with recorded origin (D272) | T010, T016 | T016 |
| SPEC §2: Phase as a ROADMAP milestone; Managed document as Markdown with SQLite blocks | Structured records with immutable accepted revisions; Markdown is a generated view (D270/D271) | T004, T013 | T004 |
| SPEC §3: reviewer and executor; user accepts by hash | Adds the judge; separates read-only code access from mediated domain capabilities (D273/D275) | T005, T008, T009 | T009 |
| SPEC §5 rule 6: five separate decisions | Retained; adds durations, standing grants, delegation ceilings, revocation (D274) | T010 | T010 |
| SPEC §5 rule 8: confirmed document writes with CAS | Retained for every other harness write; owned generated targets follow D271 | T013 | T013 |
| SPEC §5 rule 9: closure needs current READY and its own authorization | READY retained; the authorization may be an owner-confirmed or delegated child authorization (D272); the batch still never closes | T015, T016 | T015 |
| SPEC §6 / D088–D090: Markdown documentation contract and authors | Knowledge authority in SQLite; layout produced by exports; generated targets protected from agents; instruction files open (G07) | T004, T011, T013, T014 | T013 |
| SPEC §7 / D091: archive Markdown snapshots | Archive accepted domain snapshots with generated exports; tag/commit intents and terminal semantics retained | T015 | T015 |
| SPEC §8 / D102: two entries with private Markdown drafts | Database drafts; reverse engineering retained; explicit import and installed migration are separate paths | T011, T013, T020 | T011 |
| ARCHITECTURE §2: standard-library-only core | Placement of the LangGraph integration is gate G01 | T002 | T002 |
| ARCHITECTURE §5: "Markdown keeps the intent" | SQLite keeps the intent; Git keeps code and generated views | T004 | T004 |
| D034: unattended batch with `chain_commits` | Retained in manual mode; autonomous mode uses an enclosing authorization with child operations and never widens old batches | T016 | T016 |
| D052: owner selects reviewer; reviewer selects executor | Retained; the owner also selects the judge (D273) | T009 | T009 |
| D094: `AGENTS.md` injected from the checkout | Retained until G07 is resolved | T004, T007 | T007 |
| D029: polling | Retained; streaming only if it improves the agreed experience | T018 | T018 |
| D254–D259: invocation accounting | Retained; every new inference path participates from its introduction | T009, T019 | T019 |
| D064/D065: cooperative containment | Unchanged; no isolation is claimed | — | T021 |

## 3. Authority model

Responsibilities (D269):

| Concern | Authority | Explicitly not authority |
|---|---|---|
| Next workflow stage, branches and resumable waits | LangGraph, with a versioned graph definition and a persisted continuation (mechanism: G02) | Graph state is not a copy of tasks, grants or policy; it holds identities and revision references |
| Project knowledge, accepted revisions, product decisions, grants, rulings, operation outcomes, inbox items | SQLite domain records | Generated Markdown, IDE edits, model output |
| Validation, authorization and effects | Trusted application services behind typed commands; the supervisor is the only process launcher; one writer per checkout | Graph callbacks, tools or UI code that bypass the services |
| Code and committed files | Git, observed through content-bound captures | Database copies of code |
| Choices inside typed contracts | Reviewer, executor and judge propose or select | Models never authorize, adopt or validate their own output |

Invariants binding every implementing task:

| ID | Invariant |
|---|---|
| INV-01 | One writer per checkout; the supervisor alone launches processes; graph nodes reach CLIs, Git and exports only through services. |
| INV-02 | A replayed graph node reconciles the same operation identity; running a node again never creates a new effect or charge. |
| INV-03 | Acceptance binds exact code content, the accepted domain revision and the required generated documentation. |
| INV-04 | READY binds exact content and the domain revision; no model or delegation waives or overrides it. |
| INV-05 | Intent before every external effect (CLI launch, Git commit/tag, export publication, notification delivery); recovery reconciles. |
| INV-06 | An expired lease does not prove a stopped writer; uncertain inference is never reissued automatically. |
| INV-07 | No hidden fallback (provider, model, full catalogue, API billing) and no hidden retry; quota/auth/environment errors stop. |
| INV-08 | Frozen histories, snapshots, catalogues, fingerprints, accepted revisions and accepted decisions are never rewritten. |
| INV-09 | Missing evidence is unknown, never zero, success or approval. |
| INV-10 | Manual mode keeps explicit confirmations; both modes use the same domain commands. |
| INV-11 | Agents never receive direct database access, a SQL tool or a caller identity they can choose. |
| INV-12 | A delegated approval is never labelled or displayed as an owner approval. |

## 4. Authorization origins, decisions and rulings

Origins (D272), recorded on every authorization, adoption, grant and effect:

| Origin | Produced by | Requirements |
|---|---|---|
| `owner_confirmed` | The owner in the UI or an inbox action | Exact preview hash, reason where required, Idempotency-Key, fresh guards. All manual-mode confirmations and owner answers. |
| `owner_delegated` | The harness, from an active autonomous authorization | A concrete sealed preview, the parent authorization ID and revision, the policy rule applied and any judge ruling. Never exceeds the parent's scope. |
| `harness_deterministic` | The harness alone | A mechanical effect already covered by an existing authorization: managed projection, generated export, archive move, commit of accepted content. |

A parent authorization never confirms hashes of content that does not exist yet. Each child authorization is sealed
when its content exists; revoking the parent prevents new children and new attempts.

Product decisions and operational rulings are distinct records:

| | Product decision | Operational ruling |
|---|---|---|
| Content | Durable product or architecture choice, with rationale, alternatives and consequences | Permission grant/deny/escalate, planning choice, gap resolution, blocked-check classification, owner answer |
| Record | Canonical versioned domain record with stable project code, status, origin and supersession | Workflow audit record with request, evidence references, outcome, rationale, actor and origin |
| Visibility | Exported to the project's `DECISIONS.md` | Inspectable in traces, inbox and run views; not exported to DECISIONS |
| Change | Propose → adopt with review or delegation and an expected revision; supersede, never rewrite | Append-only; a later ruling supersedes an earlier one |

When a ruling establishes a durable product choice, the decision is proposed and adopted through the decision path
and linked to the ruling; a ruling never creates an accepted decision implicitly.

## 5. Knowledge, revisions and context boundaries

D270. Structured concepts: requirements and criteria, roadmap phases, tasks and dependencies, product decisions, and
supporting rich content (specification/architecture sections, Mermaid source). Normalize what needs identity,
constraints, querying or history; keep versioned rich text for descriptive content. Exact entities are G06.

- **Drafts and accepted revisions.** Drafts are mutable proposals. Adoption validates an expected revision and creates
  an immutable accepted revision identifying the complete knowledge set; history is never rewritten.
- **Context boundary.** Each invocation freezes the accepted revision it receives; its tool reads default to that
  revision. A later revision becomes visible only at a new invocation or attempt, recorded as a context boundary.
- **Evidence binding.** Validation, review, acceptance, READY and closure bind the revision together with code
  content, effective capabilities and prompt/client versions.
- **Instruction files.** `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` keep D094 until G07 decides whether they are
  generated from knowledge or remain project-owned files.

## 6. Generated documentation and explicit import

D271. The database is authoritative. Exported Markdown is a generated view for the IDE. There is no comparison of
exported files with the database, no drift warning, no conflict item and no automatic disk-to-database path.

**Generated-target replacement policy (T001 resolution).**

1. **Ownership.** Each project has a versioned ownership manifest of generated targets and renderer version, defined by
   the adopted export format (G09). Only declared targets are owned; never arbitrary files under `docs/`, README or
   ordinary product documents. Ownership is established by an adoption (creation, onboarding, migration, import or an
   export-format revision), never by the presence of a file.
2. **Replacement.** At a declared boundary — task commit, phase closure/archive, owner-requested regeneration, or a
   knowledge adoption in manual mode — the harness renders the selected accepted revision and replaces the owned
   targets without reading their current content as input.
3. **Safety guards (not drift detection).** The write runs in a writer-locked operation with a sealed intent, inside the
   root, on regular files or absent paths, refusing links, traversal and collisions with unowned paths. Uncommitted
   changes to an owned target leave the checkout dirty, so the existing clean-baseline guard refuses the operation;
   uncommitted bytes are never discarded. A committed IDE edit is superseded by the next generated commit, stays in
   Git history and is not imported.
4. **Rule 8 for owned targets.** The expected prior state is HEAD's committed bytes (or absence) for that path under a
   clean worktree/index, and the written state is the sealed rendering. Every other harness write keeps CAS against
   its previous hash or sealed bytes.
5. **Journal and commit.** The export intent records revision, renderer version, manifest digest and targets;
   per-target outcomes and a generation manifest make partial exports recoverable without rerunning inference. Code
   success and export success are separate facts. A task commit requires its required generated documentation from
   the accepted revision; an export failure blocks the commit, keeps the acceptance evidence and retries only the
   deterministic export.
6. **Agents.** Owned targets are protected paths for every agent role; agents change knowledge only through domain
   tools.

**Explicit import.** UI only: select files of a supported format version → parse → stage proposals → validation report
(unsupported, missing or lossy content) → canonical-change preview with hash → explicit `owner_confirmed` adoption,
creating a new revision. Identity maps through stable IDs in the export metadata; unknown IDs become new entities only
by explicit choice. Imported prose never creates runs, approvals, grants, rulings, usage, costs or execution states.
Document import, project-portable transfer and evidence-bearing backup/restore are separately labelled capabilities.

## 7. Roles and judge duties

D273. Reviewer, executor and judge each have provider, model and effort. The owner selects reviewer and judge per
project; the reviewer keeps D052's executor selection. Each invocation freezes selection, prompt version, tool policy
and context revision. Provider diversity is optional; there is no fallback.

The judge is a fresh invocation per request with request-specific evidence, without a persistent conversation. It has
read-only code/filesystem access and may call only its duty's query tools and ruling command; the service validates
and applies or refuses the ruling. It may abstain. It never overrides integrity, acceptance, READY or an owner-only
boundary, never edits its own policy and never turns a denial into a broader equivalent.

| Duty | Input | Outcomes | Service validation |
|---|---|---|---|
| `permission` | Typed request: dimension, targets, purpose, blocker, requested duration; effective grants; delegation policy | `grant` within the delegable tier and duration ceiling; `deny` with a concrete permitted alternative or "none"; `escalate` | Tier, ceilings, compound authority, request equivalence |
| `planning_choice` | Reviewer-supplied admissible options with trade-offs and criterion references | One supplied option ID; `escalate` | The option was supplied and is admissible; goal and criteria unchanged |
| `spec_gap` | Gap statement, requirement references, delegated intent | A grounded interpretation/proposal within delegated intent; `escalate` | Proposal enters propose/adopt as `owner_delegated`; a change of meaning goes to the owner |
| `blocked_check` | BLOCKED check evidence after deterministic classification | Eligible remediation proposal; `escalate` | Only for planning ambiguity; authentication, environment, integrity, writer uncertainty and authority gaps never reach the judge |

Failure routes, per duty: malformed output stops the request with the output preserved and creates an owner item;
refusal or unavailable evidence escalates; timeout, provider, quota or authentication errors are operational stops
without retry; an equivalent request without new evidence reuses the earlier ruling or stops for no progress; an
unsupported mandatory capability blocks admission. Prompts and evaluation corpus are G16.

**Owner-only** (never delegable or judge-grantable): secrets and credentials, global or user configuration, writes
outside the registered root, policy/instruction/prompt changes, destructive Git (history rewrite, force, tag move,
branch deletion), push/publication/release/deployment, network installation to undelegated destinations, changes to
roadmap objectives, phase set or requirement meaning, weakening acceptance criteria, and the judge's own policy.

## 8. Permissions and standing grants

D274. Five separate dimensions stay: file scope, tools/commands, network, product/architecture and acceptance.

- **Tiers at authorization.** *Active* (granted at start), *delegable* (the judge may grant, with a maximum duration
  class) and *owner-only*. Manual mode has no delegable tier: requests go to the owner.
- **Durations.** Per-operation, time-limited and **permanent** (no time expiry, revocable). Permanence does not widen
  scope.
- **Binding.** Project, role, dimension, exact targets (root-relative paths, executable identity and argv prefix,
  network destination), purpose, origin and ruling, parent authorization, policy version.
- **Effective authority.** Evaluated on every mediated command and attempt admission as the grants intersected with
  current ceilings and owner-only exclusions. A combination of grants never yields an owner-only capability.
- **Application.** A grant applies at a new attempt or context boundary through a frozen permission snapshot; it never
  mutates a live attempt. The executor attempt that requested it is settled and its work captured first.
- **Revocation.** Owner action; immediate for mediated commands and new admissions. An active native writer is stopped
  through process control, its effects settled as uncertain where needed. Historical snapshots stay unchanged.
- **Equivalence.** Requests are fingerprinted by dimension, normalized targets and purpose class plus evidence digest;
  an equivalent request without new evidence does not invoke the judge again.

Cascade on authorization end, permanent grants in manual mode and target normalization are G10.

## 9. Portable tool contract

D275. A harness-owned, versioned logical catalogue lists each tool's ID and version, kind (query, propose, adopt,
effect), input/output schemas and digest, required capability dimension, allowed roles and description. Deterministic
graph nodes call application services directly; the broker is for model-selected calls.

| Operation (illustrative) | Contract |
|---|---|
| `search_tools` | Bounded descriptors (ID, version, summary, digest) from the catalogue scoped to role, project and operation. Tools outside that scope are not disclosed. |
| `describe_tool` | The selected tool's schema and digest. |
| `invoke_tool` | Tool ID, version, schema digest, arguments and idempotency key → typed result or typed refusal. |

Every invocation binds the caller (project, role, invocation, attempt) from the transport session, never from
arguments, and validates schema digest, effective authority, expected revision and idempotency. Discovery is not a
grant. There is no SQL, arbitrary code or full-catalogue fallback. Both the broker call and the logical tool are
traced. The transport is an existing suitable one (a small static MCP surface or a characterized CLI wrapper), chosen
per client in G04; native deferred loading/Tool Search may optimize the same semantics but is never required.

Client kind, inference provider and model are separate dimensions in admission and accounting. Claude Code and Codex
are the 0.2.0 clients. OpenCode is future work: P002 provides the extension point and a synthetic conformance fixture,
not an adapter. A client must meet the minimum capability contract defined in T002, or admission is blocked.

## 10. Autonomous run

D276.

- **Start.** A readiness preview combines deterministic structural checks and a reviewer gap report (G12), then the
  owner confirms: accepted roadmap/requirements revision, phases in scope (the remaining authorized roadmap), delegation
  policy (enabled judge duties, delegable tiers and duration ceilings), local bounds, optional caps and the risk
  acknowledgement version (G17). Existing standing grants that will apply are shown.
- **Scope.** No phase-count cap. Planning tasks inside authorized phases is delegated; adding phases or changing
  objectives, criteria meaning or requirements is an owner amendment and needs a new authorization revision. Graph
  recursion limits apply per durable segment and never cap valid roadmap length (G03).
- **Local bounds.** Finite and saved with the authorization: task attempts across task lineage, judge reconsiderations
  per equivalent request, replacement plans per phase, remediation tasks per failure cause and no-progress detection
  by fingerprint. Counters survive resume, phase change, split and rename. Default values are G11.
- **Optional caps (T001 resolution).** Wall-clock deadline, invocation count, observed tokens, and valuation on one
  compatible basis. Checked before admitting each new inference. With a token or valuation cap set, unknown usage stops
  the run. They are thresholds that an in-flight invocation can exceed, never spend or quota ceilings.
- **Stops.** `WAITING_FOR_OWNER`, `PAUSED`, `LIMIT_REACHED`, `FAILED` (operational or policy), `RECOVERY_REQUIRED`,
  `REVOKED`, `COMPLETED`. Each persists reason, evidence and an inbox item. Waiting stops inference and holds no
  process, lease or transaction.
- **Resume.** Explicit owner action. It revalidates repository, authority, versions and remaining bounds, reuses only
  valid content-bound evidence, and requires recovery first when anything is uncertain. Quota/auth stops are not
  polled.
- **Completion.** All authorized phases CLOSED with criterion evidence and final requirement coverage. An ABANDONED
  phase ends the run without success. Completion never pushes, releases, publishes or deploys.

## 11. Trace, knowledge access, inbox and graph

**Trace (D277).** Request (owner action, autonomous authorization, inbox action, chat) → workflow run (graph thread
and version) → operation (recoverable domain unit) → agent invocation/attempt → observed turn and tool call (native)
or broker/logical tool call, with ordered events carrying parent and causation IDs, sequence, timestamps and source
(supplied, reported, derived, measured, absent). Project task, operation and invocation are distinct; naming and
granularity relative to existing jobs/runs/attempts are G08. A harness attempt, a revision round and a
provider-reported turn are different counters; unobserved turns are never manufactured. Commands persist outcome
and event in one transaction; large payloads are hashed artifacts.

**Knowledge receipts.** One per delivery: invocation, channel (initial context, query result, tool result), entity
type, stable ID, revision, sections or ranges, exposure (metadata, excerpt, full), digest, truncation/pagination, and
failure. Delivery shows availability, not comprehension. Native file reads are recorded only when observed. Tool
discovery and schema delivery are separate events.

**Inbox (D278).** Items have a stable ID and dedupe key, project and optional phase/task/run/operation/request
references, kind, origin events, separate read and resolved states, requested action and evidence links. They are
derived from committed events in both modes and survive restarts. Actions invoke ordinary guarded commands with fresh
checks; an item never carries an approval. Archives are read-only; OS notifications are optional and carry no
sensitive content. Taxonomy and shortcuts are G13.

**Graph (D278).** A read-only projection of persisted phases and tasks, with their operations and invocations; actors
are reviewer, executor, judge and Harness (deterministic stages). Phase opening, check and closure show the actual
agents. It is not a workflow editor nor the runtime topology. Polling stays the default. Visual direction is G14.

## 12. Open gate register

| Gate | Question | Owner task | Constraint already fixed |
|---|---|---|---|
| G01 | LangGraph exact version, locked dependency set, offline packaging, placement relative to the standard-library-only core | T002 | D269; recorded decision before adding; a blocker returns to the owner, no silent alternative runtime |
| G02 | Continuation persistence (checkpointer, custom saver or none) and its consistency contract with the operation journal | T002 feasibility, T003 | INV-02, INV-05, INV-06 |
| G03 | Graph limits per durable segment; graph-version drift for in-flight continuations | T003 | No roadmap-length cap; quarantine incompatible continuations |
| G04 | Tool transport and loading per client/profile; native discovery comparison; read-only roles with mediated tools; minimum client capability contract | T002, T008 | D275 semantics; no global configuration edits |
| G05 | Observable turns, tool calls, cancellation and usage per client | T002, T006 | Missing coverage stays explicit |
| G06 | Entity boundaries, revision representation, criterion granularity, product-level one-off entity | T004 | D270 |
| G07 | Authority of `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`: generated or project-owned | T004, T007 with owner confirmation | D094 until resolved |
| G08 | Operation/invocation naming (`agentic_task`) and granularity versus jobs, runs and attempts | T006 | No second scheduler |
| G09 | Export format and version, ownership manifest, renderer, import identity mapping, new-project versus update imports, loss reporting | T013 | D271 policy |
| G10 | Standing-grant cascade on authorization end/revocation; permanent grants in manual mode; target normalization | T010 | Revocable, project-scoped, visible at start |
| G11 | Default local-bound values and no-progress fingerprints | T016 | Finite, persistent, lineage-aware |
| G12 | Readiness criteria over structured knowledge | T016 with T011 | Deterministic structure plus cited reviewer gaps |
| G13 | Inbox taxonomy and shortcuts | T017, owner | Guarded commands only |
| G14 | Graph visual direction | T018, owner | Read-only projection |
| G15 | Measurable qualification thresholds; any real-provider qualification | T021, T022, owner authorization | Synthetic first; truthful labels |
| G16 | Judge prompts and evaluation corpus | T009 | Duty contracts in §7 |
| G17 | Risk acknowledgement text | T016 | Plain language: autonomy, containment limits, caps semantics |

## 13. T001 resolutions for owner review

These details complete the owner's directions without new scope. The owner reviewed the T001 diff and authorized its
integration on 2026-10-29, accepting them; a later change reopens the item through a new decision.

1. Generated-target replacement: HEAD-relative expected state, clean-baseline refusal of uncommitted edits, ownership
   manifest, and required exports before task commit ([§6](#6-generated-documentation-and-explicit-import)).
2. Optional caps as thresholds checked before each inference, stopping on unknown usage when set
   ([§10](#10-autonomous-run)).
3. Authorization origins and derived child authorizations ([§4](#4-authorization-origins-decisions-and-rulings)).
4. Owner-only capability list and per-duty failure routes ([§7](#7-roles-and-judge-duties)).
5. Run stop classes and completion rule ([§10](#10-autonomous-run)).

## 14. Plan refinements (v0.3)

No task ID is added, removed, merged or renumbered; no acceptance or pending delivery is dropped. Changes, with reasons:

- **T001** completed as design/documentation (this record); its integration remains pending.
- **T002–T018, T021** receive the gate assignments of [§12](#12-open-gate-register) and threat references, so each
  open question has one owner. T002 adds the LangGraph placement question (G01) and states that a feasibility blocker
  returns to the owner instead of a silent alternative runtime.
- **T013** implements the adopted replacement policy instead of resolving it.
- **T021** uses the [threat model](P002-T001-threat-model.md) as its audit checklist.

## 15. Requirement coverage

Owner directions of the T001 request (R01–R10) and the proposed phase exit criteria (EC1–EC9, NEXT_STEPS order):

| Req. | Requirement | Design | Implementing tasks | Qualifying tasks |
|---|---|---|---|---|
| R01 | LangGraph orchestrates; SQLite owns structured knowledge | D269, D270 | T002, T003, T004, T005 | T020, T021, T022 |
| R02 | Generated Markdown without drift detection; explicit UI import | D271 | T013, T014, T015 | T020, T022 |
| R03 | Definition and reverse-engineering onboarding into database knowledge | D270 | T011 | T020, T022 |
| R04 | Portable discovery/description/invocation, OpenCode-ready, no native Tool Search dependency | D275 | T002, T005, T008 | T019, T021, T022 |
| R05 | Judge configurable by provider/model/effort with duty-specific prompts, capabilities, results and failures | D273 | T009 | T021, T022 |
| R06 | Revocable permanent grants; product decisions separate from operational rulings | D272, D274 | T004, T009, T010, T012 | T021, T022 |
| R07 | Traceability of requests, operations, agents, turns, tools and delivered knowledge, with exact revisions and explicit coverage | D277 | T006, T007, T008 | T018, T019, T020, T022 |
| R08 | Whole authorized roadmap without a phase cap; bounded task attempts and no-progress cycles | D276 | T014, T015, T016 | T021, T022 |
| R09 | Global inbox for both modes; task-instance graph; visual design later | D278 | T017, T018 | T022 |
| R10 | Content acceptance, READY, single writer, intent before effect, conservative recovery | D269 INV-01–INV-06 | T003, T006, T014, T015, T016 | T020, T021, T022 |
| EC1 | Structured revisioned knowledge; attributable access; shared domain model | D270, D277 | T004, T005, T007, T011 | T022 |
| EC2 | Scoped on-demand tools; qualified or blocked capabilities; client-neutral contract | D275 | T002, T008 | T021, T022 |
| EC3 | Explicit role configuration and judge contracts; enforced permissions outside the model | D273, D274 | T005, T009, T010 | T021 |
| EC4 | Roadmap completion with local bounds, exact evidence, READY and recoverable effects | D276 | T014, T015, T016 | T020, T022 |
| EC5 | Correlated events; explicit missing telemetry | D277 | T006, T008, T009 | T019, T022 |
| EC6 | Generated documents at boundaries; explicit import with provenance | D271 | T013 | T022 |
| EC7 | Global inbox and graph with owner's visual direction | D278 | T017, T018 | T022 |
| EC8 | Migration, backup/restore, accounting, query-only and normal mode qualified; audits recorded | D277, D279 | T019, T020, T021 | T022 |
| EC9 | 0.2.0 distribution and delivery tracked truthfully | D268 | T023 | T023 |

Every task T002–T023 implements or qualifies at least one row; every row has implementing and qualifying tasks.
Threat-to-task coverage is in the [threat model](P002-T001-threat-model.md#threats-controls-and-owning-tasks).

## 16. Verification and delivery

**Delivery status.** Source (documentation) complete on `docs/p002-t001-contracts`, branched from `develop` at
`a000e03`, which matched the local `origin/develop` tracking ref (no fetch). After reviewing the diff, the owner
authorized commit and integration into the local `develop` (2026-10-29); Git history records the commit and merge
identities. Push to origin was not part of that authorization; it happened with the P002-T002 integration at the owner's
authorization (2026-10-29). No release, publication or
installation applies to T001; the phase route remains 0.2.0 at P002 closure (D253/D242).

### Evidence

- **Discovery.** AGENTS discovery read; one-off queue empty; working tree clean at the start; no later changes to
  preserve. The design basis was read in full and the discussion consulted for §§6.1–6.6, 7 and 8–9.
- **Documentation checks.** `scripts/check-docs` passes over all 86 Markdown files (83 tracked plus the three new T001
  records passed explicitly), including links, anchors, fences, catalogue keys and the DDBB head/table count;
  `git diff --check` is clean.
- **Mermaid.** The 15 new blocks (FL01–FL14 and ARCHITECTURE §13) pass `mermaid.parse` and diagram construction with
  the installed mermaid 11.17.2 under Node, with DOMPurify stubbed because Node has no DOM. Layout, browser rendering
  and HTML sanitization were not exercised.
- **Plan integrity.** 23 unique task IDs and sections; 69 subtasks unchanged; index dependencies unchanged except
  T001's wording, with no cycles or forward prerequisites; all 17 gates assigned to tasks in NEXT_STEPS; the owning
  tasks of TM01–TM20 match the tasks' **Threats** lines (T021 audits all); every task T002–T023 appears in the coverage
  matrix and every requirement row has implementing and qualifying tasks.
- **Preservation.** No change under `docs/archive/`, to the discussion record, the narrower continuous-mode proposal,
  the portable-tools/archive maintenance record, `docs/flows/`, DDBB-DIAGRAM, AGENTS or CLAUDE. Existing decisions are
  untouched except the status lines of D156 and D233, which record their supersession by D268.
- **Not performed.** No product code, schema, API, OpenAPI/client types, catalogue or UI change, so product suites
  (`scripts/check`) were not run. No harness execution, real agents or providers, dependency installation, network
  access, commit, merge, push, publication or installation.
