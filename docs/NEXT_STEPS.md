# P002 — Autonomous mode and project authority redesign (target: 0.2.0)

**Status:** active phase; **draft task plan v0.2, 2026-10-29, pending owner review**. All tasks below are proposed;
none is implemented or started. The owner requested a complete, refinable task/subtask breakdown during the design
discussion. This authorizes planning, not implementation or operation. Read [ONE_OFF_TASKS](ONE_OFF_TASKS.md) first;
its queue is **empty**.

**Objective:** deliver optional complete-roadmap autonomy with LangGraph orchestration, structured database-owned
project knowledge, controlled discoverable tools, bounded judge decisions, recoverable operations, correlated
tracing, generated/manual-importable documentation, a global inbox and a task-instance graph. Normal mode shares
the new domain services. This broadens the original [Continuous Mode reservation](ROADMAP.md#p002--continuous-mode);
formal contract adoption/supersession belongs to T001, not an implied implementation claim in this draft.

**Design reference:** [P002 design basis](phase/P002-design-basis.md), especially B01–B24, consolidates owner directions,
recommendations and open gates. The [discussion](phase/P002-autonomous-mode-discussion.md) preserves the reasoning
and corrections. Start from these before inferring missing details. Technical baseline: [phase lifecycle](flows/phase-lifecycle.md),
[task run](flows/task-run.md), [definition](flows/project-definition.md), [onboarding](flows/project-onboarding.md),
[data](DDBB-DIAGRAM.md) and [architecture](ARCHITECTURE.md). Historical starting evidence remains in the
[P002 handoff](archive/phase-001/P001-T006-qualification.md#p002-handoff).

## Planning and delivery rules

- This is a complete initial problem/outcome map, not a promise that every implementation detail is known. Refine,
  split or add tasks/subtasks with a recorded reason and revised dependencies/acceptance coverage. Keep stable task
  IDs and never silently discard requirements, qualification or pending delivery. Subtasks are reviewable checklists
  inside their owning task, not independently admitted harness contracts. Never rewrite a contract already frozen
  by an actual product execution to match a new plan.
- Owner review/adoption of this plan precedes T001 and source work. T001 resolves normative contracts and detailed
  flow gates; T002 resolves capability/dependency feasibility before dependent integration. A newly discovered
  design inconsistency is surfaced instead of silently deciding it in implementation.
- One bounded task at a time. Before implementing a task, refine its contract and record its topic branch from
  develop, evidence requirements and accepted delivery disposition. Current planning branch: docs/p002-plan.
- Proposed common phase delivery: checked source → develop → 0.2.0 release through protected main → verified
  distribution/publication → local installation, each recorded separately under D242/D253. Commits, merges, pushes,
  real agents/providers, harness execution, network installation, publication and local installation require their
  own explicit authorization. This repository must not be run through the harness.
- Product changes maintain data/flow/OpenAPI/generated-client parity and English/Spanish UI/catalogue parity in
  their owning task. No new dependency before an accepted recorded decision with exact versions and packaging
  impact. Preserve historical prompts, receipts, catalogues, snapshots, runs and accounting provenance.
- Every implementation task includes focused synthetic evidence for its boundary. Security and recovery checks
  begin with the foundations and continue throughout; T021 is an integrated audit, not the first security review.
  New inference paths must participate in existing invocation accounting from introduction, before T019 aggregation.
- Any design area that remains unresolved becomes an explicit prerequisite or bounded follow-up. Source completion
  is distinct from integration/distribution/installation. One-offs use D261's latest-main-release route and do not
  absorb unreleased P002 work.

## Proposed phase exit criteria

- Created and onboarded projects use structured, revisioned database knowledge; task/decision access is attributable
  to agent runs. All ordinary/manual operations use the same canonical domain model.
- Scoped tools are discovered on demand rather than requiring the complete detailed catalogue in every context;
  selected CLI/profile capabilities are qualified or explicitly blocked, without assumed API access or hidden fallback.
  The baseline discovery/invocation contract is client-neutral and prepares future OpenCode support; native
  provider-specific tool search is optional, and no OpenCode adapter is claimed delivered by that design work.
- Reviewer/executor/judge configuration and judge duty-specific contracts are explicit; permission scope, permanent
  validity, revocation, delegation and independent acceptance checks are enforced outside the model.
- The authorized roadmap can finish without a phase-count cap, with bounded task attempts and no-progress cycles,
  exact-content/domain-revision evidence, current READY and recoverable task/phase/Git/export effects.
- Events correlate requests, workflows, operations, agents, observed turns, tool calls and knowledge delivery.
  Missing native telemetry remains explicit; no proof of model comprehension or undocumented CLI internals is claimed.
- Generated documents are regenerated at defined boundaries without disk/database drift detection. Explicit UI import
  supports the documented format and preserves provenance; it cannot fabricate execution/approval history.
- A global inbox supports normal/autonomous events and guarded actions. The graph shows persisted tasks and actual
  agent involvement, with the owner's visual direction, useful trace inspection and archive parity.
- Migration, backup/restore/portability, usage accounting, query-only consultation and normal-mode behavior are
  qualified. Integrated security/provider/recovery audits and complete synthetic journeys have recorded evidence.
- The 0.2.0 distribution and operator documentation are qualified; authorized release/publication/installation
  stages are completed or explicitly deferred with a destination. No designed-only behavior is labelled implemented.

## Task index

All statuses are **proposed**. Dependencies identify prerequisites; they do not authorize parallel implementation.

| ID | Problem/outcome area | Dependencies |
|---|---|---|
| P002-T001 | Adopt scope, authority contracts, threat model and detailed flow gates | Owner review of this draft |
| P002-T002 | Characterize graph/tool-discovery/provider integration and pin dependencies | T001 |
| P002-T003 | Establish the versioned LangGraph runtime and durable continuation boundary | T002 |
| P002-T004 | Introduce structured knowledge, identities and immutable accepted revisions | T001, T002 |
| P002-T005 | Centralize typed domain commands, queries and capability enforcement | T003, T004 |
| P002-T006 | Establish operations, agent invocations, correlated events and recovery records | T003, T004, T005 |
| P002-T007 | Assemble frozen context and record knowledge-access receipts | T004, T005, T006 |
| P002-T008 | Expose scoped tools with on-demand discovery through qualified CLI adapters | T002, T005, T006, T007 |
| P002-T009 | Add configurable judge profiles and duty-specific adjudication contracts | T007, T008 |
| P002-T010 | Implement permission requests, standing grants and revocation | T005, T006, T008, T009 |
| P002-T011 | Move definition, reverse-engineering onboarding and managed adoption to DB knowledge | T004, T005, T007, T008 |
| P002-T012 | Provide authoritative project knowledge/decision editing in the UI | T004, T005, T006 |
| P002-T013 | Deliver generated exports, explicit document import and portable format | T004, T005, T006, T011, T012 |
| P002-T014 | Refactor task execution, acceptance, export parity and commit integration | T003, T006, T007, T008, T010, T013 |
| P002-T015 | Refactor phase checks, planning, closure/archive and manual lifecycle | T004, T005, T007, T009, T013, T014 |
| P002-T016 | Deliver autonomous roadmap execution, local bounds and durable human waits | T003, T006, T009, T010, T014, T015 |
| P002-T017 | Deliver the global inbox and guarded actions for both modes | T005, T006, T015, T016 |
| P002-T018 | Deliver the task-instance graph and correlated trace inspection | T006, T007, T012, T015, T016, T017; owner visual direction |
| P002-T019 | Extend accounting/projections and measure context/tool efficiency | T006, T008, T009, T014, T015, T016 |
| P002-T020 | Qualify installed-data migration, crash recovery, backup/restore and archives | T003–T007, T011, T013–T017, T019 |
| P002-T021 | Audit integrated authority, provider contracts and failure containment | T002, T008–T010, T016, T017, T020 |
| P002-T022 | Qualify complete journeys, normal-mode regression, UX and performance | T011–T021 |
| P002-T023 | Qualify 0.2.0 documentation/package and track authorized delivery | T021, T022 |

## P002-T001 — Scope adoption, authority contracts and flow gates

**Problem:** the current specification/decisions describe narrower continuous mode and file-owned knowledge.
**Expected result:** an owner-reviewed design baseline identifies which contracts change and which guarantees remain,
with no ambiguity between proposed and implemented behavior. **Dependencies:** owner review of this draft.

**Subtasks:**

- Reconcile the design basis with current SPECIFICATION/ARCHITECTURE and cited decisions; record accepted changes
  and supersessions using the normal DECISIONS process, without changing frozen history.
- Define admission, tool/permission/judge, task, phase, knowledge/import/export, inbox, trace and recovery diagrams
  plus transition guards and effect owners. Establish the initial threat model and capability trust boundaries.
- Adopt phase acceptance/evidence and delivery rules; resolve the generated-target replacement policy, optional
  consumption caps and manual/autonomous authorization semantics before dependent source work.

**Evidence:** reviewed contract/flow changes, explicit open gates, requirement-to-task coverage and documentation checks.
**Basis:** B01–B24; detailed operational choices may still be refined in their owning tasks.

## P002-T002 — Runtime, provider and discovery feasibility

**Problem:** library/API capabilities do not establish compatibility with the supported subscription CLIs.
**Expected result:** a concrete integration/dependency choice with a supported capability matrix and explicit blockers.
**Dependencies:** T001.

**Subtasks:**

- Characterize LangGraph embedding, checkpoint/domain-operation boundaries, packaging and offline operation using
  bounded synthetic/fake-process probes; select exact dependencies through an accepted decision before adding them.
- Specify a client-neutral discovery/description/invocation contract and compare portable bridge vs native deferred
  loading for Claude/Codex profiles, including read-only roles and telemetry. Review future OpenCode extension points,
  distinguish client from inference provider, and separate published API facts from actual CLI evidence.
- Define the minimum admitted capability contract, explicit failure behavior and the later qualification matrix;
  do not replace subscriptions with API billing or silently load the whole catalogue as fallback.

**Evidence:** reproducible probes, dependency/compatibility record and labelled unknowns. Missing tools or unauthorized
real-provider access remain explicit prerequisites; synthetic evidence is not reported as native provider qualification.
**Basis:** B02, B08–B09, B23.

## P002-T003 — LangGraph runtime and continuation foundation

**Problem:** orchestration must become explicit without introducing a second process scheduler or unsafe replay.
**Expected result:** a versioned graph runtime can schedule/observe domain operations and persist/resume waits through
an agreed interface, first with synthetic operations. **Dependencies:** T002.

**Subtasks:**

- Introduce the runtime/application boundary, graph identity/version and supervisor ownership of admitted effects.
- Implement the selected continuation mechanism, domain operation references and explicit cancellation/revocation
  interface, with graph limits that do not cap valid roadmap length.
- Demonstrate interrupted-node re-entry, wait/resume and version mismatch using synthetic operations; establish
  how the production operation journal from T006 completes this boundary.

**Evidence:** deterministic lifecycle and crash-boundary checks; no duplicate synthetic effects or hidden inference.
**Basis:** B02, B12–B13, B18.

## P002-T004 — Structured knowledge and revision model

**Problem:** active requirements/plans/decisions depend on document parsing and mutable current content.
**Expected result:** structured identities, relationships and accepted revisions can represent project intent and
support exact context/evidence binding. **Dependencies:** T001, T002.

**Subtasks:**

- Refine entities for requirements/criteria, phases/tasks/dependencies, product decisions and rich supporting content,
  including status, provenance and supersession; avoid inventing a product one-off feature.
- Add migrations/repositories and immutable accepted revision/snapshot retrieval, preserving legacy records and
  explicit mapping between old and new identities. Do not fabricate missing historical knowledge.
- Update the data diagram and contracts; demonstrate retrieval of old/current accepted revisions and relationship
  constraints using synthetic data, before live installation conversion in T020.

**Evidence:** migration/constraint/revision tests and data parity. **Basis:** B03–B04, B13, B22.

## P002-T005 — Typed domain operations and capability policy

**Problem:** tools, UI and graph routes must not implement different authorization or database mutations.
**Expected result:** discoverable typed command/query services validate identities, authority, revisions and idempotency.
**Dependencies:** T003, T004.

**Subtasks:**

- Centralize query/propose/adopt/effect contracts with stable results and a versioned capability catalogue; define
  read-only filesystem access separately from allowed domain mutations. Provide broker-neutral logical operation
  schemas so MCP/native wrappers and LangGraph share the same validated implementations.
- Bind project/role/invocation identity server-side, enforce separate permission dimensions and current ceilings,
  and reject arbitrary SQL, forged targets, stale revisions and inappropriate self-adoption.
- Provide shared API/graph/tool entry points with transaction-bound outcome/audit interfaces, exported OpenAPI and
  generated client parity where applicable. Preserve local-session/CSRF and query-only mutation guards.

**Evidence:** command/API misuse, concurrency/idempotency and delegation checks. **Basis:** B02, B04, B06–B09, B13–B15.

## P002-T006 — Operations, invocations and correlated events

**Problem:** a single task status cannot explain agent activity or safely resume an uncertain effect.
**Expected result:** project tasks link to recoverable operations, invocations/attempts, observed turns/tool calls,
events and pending effects, with reconstructible request-to-result traces. **Dependencies:** T003, T004, T005.

**Subtasks:**

- Evaluate `agentic_task` versus explicit operation/invocation concepts against existing jobs/runs; implement the
  adopted identity, parent/causation, lifecycle and result/error references without a duplicate scheduler.
- Persist ordered events and status projections with command outcomes; define native-vs-derived counter meanings,
  coverage, bounded artifacts and the knowledge-access/discovery event envelopes needed by T007/T008.
- Integrate expected invocation accounting, writer ownership, effect intents and uncertain-result recovery; expose
  bounded trace queries and update data/API/client documentation together.

**Evidence:** trace ordering/deduplication, missing telemetry, interruptions and re-entry without duplicated effects.
**Basis:** B05, B10–B13, B19–B23.

## P002-T007 — Frozen context and knowledge-access receipts

**Problem:** database queries can change an agent's effective context silently and leave its knowledge use unexplained.
**Expected result:** each invocation has reconstructible context and attributed task/decision/document access.
**Dependencies:** T004, T005, T006.

**Subtasks:**

- Assemble minimal relevant context from accepted revisions, profile/instructions and code evidence, with stable
  source identities rather than relying on generated Markdown as authority.
- Add bounded revision-aware lookup/search and record exact delivered entities/sections, exposure levels, digests,
  pagination/truncation and context-delivery failures through T006 events.
- Define the boundary for accepted knowledge changes and new invocations; distinguish availability from claimed
  comprehension and leave unobserved native filesystem reads explicitly unknown.

**Evidence:** stale-query, revision and receipt reconstruction checks with realistic synthetic knowledge sizes.
**Basis:** B03–B04, B10–B11, B13, B21.

## P002-T008 — Scoped tool bridge and lazy discovery

**Problem:** ordinary Python tools are not automatically available inside the supported CLIs, and full catalogues
consume unnecessary context. **Expected result:** qualified role-scoped tool discovery/loading/calls reach the
shared domain services with auditable identities. **Dependencies:** T002, T005, T006, T007.

**Subtasks:**

- Implement the portable versioned search/describe/invoke surface through the selected transports; return bounded
  trusted catalogue/schema references and validate the selected logical operation's schema and authority on every
  call. Future clients must not require Anthropic-specific tool discovery to conform.
- Adapt the characterized Claude/Codex launch policies without global edits or hidden fallback, and preserve
  process control, schema validation and code/file restrictions for each role.
- Capture discovery, schema delivery, calls and outcomes; qualify missing-tool, malformed-call, stale/revoked-scope
  and unsupported-client behavior, including a synthetic additional-client conformance fixture and generic-invoke
  bypass attempts. Native discovery can optimize the same contract; do not claim OpenCode support from a fake fixture.

**Evidence:** fake-CLI integration/capability tests and context-loading measurements; label native evidence separately.
**Basis:** B05, B07–B11, B21–B23.

## P002-T009 — Judge configuration and duty contracts

**Problem:** one human-proxy prompt would mix distinct authority and failure semantics.
**Expected result:** one selectable judge provider/model/effort profile supports bounded, duty-specific adjudication.
**Dependencies:** T007, T008.

**Subtasks:**

- Add configuration/UI/admission support and frozen invocation selection without requiring provider diversity.
- Define prompts, typed inputs/outputs, context/tool scopes and failure routes for permissions, planning choices,
  specification gaps and eligible blocked checks; distinguish proposals from adopted domain effects.
- Record requests/rulings and any resulting product-decision links; preserve abstention, bounded reconsideration,
  unavailable evidence, refusal, malformed response and provider-error behavior.

**Evidence:** synthetic grant/deny/escalate and choice/gap cases with adversarial and incomplete inputs; accounting
participates from the first new inference path. **Basis:** B04–B07, B10, B18, B21, B23.

## P002-T010 — Permission lifecycle and standing grants

**Problem:** autonomous approval needs bounded delegated authority, permanent validity and enforceable revocation.
**Expected result:** permission requests/rulings create only eligible grants, with explicit scope/duration and traceable
effective snapshots. **Dependencies:** T005, T006, T008, T009.

**Subtasks:**

- Implement request lifecycle, per-operation/time-limited/permanent grants, denials, supersession and owner-only
  escalation using the five separate permission dimensions.
- Enforce compound scope and permanent-duration delegation, new-attempt application, request equivalence/no-progress
  controls and revocation at mediated effect/admission boundaries.
- Provide inspection/owner response controls and stop/recovery behavior for an already active writer, without
  pretending cooperative containment prevents every native side effect.

**Evidence:** grant accumulation, cross-project targets, expiry/permanence, stale responses and revocation race cases.
**Basis:** B06–B07, B12–B13, B18, B23.

## P002-T011 — Database-owned creation and reverse-engineering intake

**Problem:** definition/onboarding currently create documentary drafts and adoption around Markdown authority.
**Expected result:** both entry flows create reviewed structured drafts/accepted knowledge, with existing-code
reverse engineering preserved as a distinct path. **Dependencies:** T004, T005, T007, T008.

**Subtasks:**

- Move new-project definition conversations/proposals to database draft concepts and concrete adoption previews.
- Route static HEAD inventory and reverse-engineering output into structured knowledge with inferred/known/unknown
  provenance, questions, original-file preservation and no execution of inventoried project code.
- Preserve profile/preparation/activation gates and define adopted managed-project conversion inputs for T020;
  distinguish new definition, code onboarding, explicit document import and installed-state migration.

**Evidence:** both synthetic intake journeys, stale HEAD/proposal refusal, incomplete knowledge and idempotent adoption.
**Basis:** B03, B09, B13, B15–B16, B22–B23.

## P002-T012 — Authoritative knowledge and decision editing

**Problem:** users must change project intent through the product once IDE Markdown edits have no authority.
**Expected result:** usable project editors/read views support structured concepts and expressive prose with revision
history, references and exact adoption previews. **Dependencies:** T004, T005, T006.

**Subtasks:**

- Provide requirement/phase/task/decision editing and search, plus rich architecture/specification/diagram content
  without exposing database mechanics or forcing one form field per sentence.
- Distinguish drafts, accepted revisions, superseded product decisions and operational rulings; show impact on
  active attempts/READY and enforce current-version mutation rules.
- Preserve en/es, local API guards, accessibility and query-only consultation; link knowledge to affected task/run
  context and leave graph layout to T018 with owner input.

**Evidence:** editor/adoption concurrency and UI/API journeys, meaningful diffs and historical reads. **Basis:** B03–B04, B13, B20.

## P002-T013 — Exports, manual import and portable document format

**Problem:** generated Markdown must remain useful in the IDE and explicitly importable without automatic drift logic.
**Expected result:** reproducible supported exports and a staged UI import round trip with clear identity/provenance
rules. **Dependencies:** T004, T005, T006, T011, T012.

**Subtasks:**

- Define/version the supported document format and generated-target ownership; render accepted revisions at safe
  boundaries, regenerate known targets without content drift comparison and journal recoverable delivery outcomes.
- Implement explicit UI parse/validate/preview/adopt into structured records, including deliberate IDE edits;
  preserve prose/diagrams and report unsupported/lossy content without inventing execution, approval or usage history.
- Define project-scoped portable transfer with identity/version mapping and reference integrity; distinguish document
  round trips from evidence-bearing backup/restore. Enforce path/root/symlink/unowned-file guards.

**Evidence:** rich round trips, missing/edited generated files, rejected imports, interrupted exports and deterministic
retry without inference. No watcher, drift warning or automatic disk-to-database synchronization is introduced.
**Basis:** B03–B04, B13–B16, B22–B23.

## P002-T014 — Task execution and exact acceptance integration

**Problem:** the task engine must consume domain knowledge and participate in the new workflow/effect model.
**Expected result:** plan/execute/format/validate/review/accept/commit works through revision-bound operations and scoped
tools in both modes. **Dependencies:** T003, T006, T007, T008, T010, T013.

**Subtasks:**

- Integrate the existing task stages with graph/application boundaries, new context/capabilities and local correction
  limits, preserving a single writer and truthful agent/turn/tool traces.
- Bind validation/review/acceptance to code plus the adopted domain revision and required generated documentation;
  preserve diagram parity and reject changed evidence before commit.
- Reconcile export/commit intents and permission/gap stops without losing partial work, repeating accepted inference
  or resetting failure lineage through a new task identity.

**Evidence:** synthetic success, correction, denial, invalidation, interruption and duplicate-dispatch cases.
**Basis:** B01–B02, B07, B10–B14, B17–B18, B21–B23.

## P002-T015 — Phase lifecycle and successor planning

**Problem:** phase checks and transitions currently bind documentary baselines and separate explicit planning flows.
**Expected result:** manual and delegated phase operations use accepted knowledge revisions while retaining exact
READY, archive/tag and successor semantics. **Dependencies:** T004, T005, T007, T009, T013, T014.

**Subtasks:**

- Refactor phase planning, criteria/coverage checks and adopted plan revisions; expose actual reviewer involvement
  and distinguish missing work, eligible reconciliation, unresolved questions and operational failures.
- Implement authorized closure/archive/tag effects with immutable domain/evidence snapshots and recoverable exports;
  handle the final phase without inventing a successor.
- Preserve manual confirmations, amendments, abandonment and history consultation; emit durable lifecycle events
  suitable for the global inbox and graph without changing old closed evidence.

**Evidence:** all check outcomes, stale READY, closure crashes, successor/no-successor and manual regression cases.
**Basis:** B01–B02, B04–B06, B10–B14, B17–B19, B22–B23.

## P002-T016 — Full-roadmap autonomous execution

**Problem:** task/phase operations need a sustained delegated workflow that finishes valid roadmap work safely.
**Expected result:** an optional admitted run plans/executes/checks/repairs/closes successive phases until completion,
with no phase-count cap and inspectable durable stops. **Dependencies:** T003, T006, T009, T010, T014, T015.

**Subtasks:**

- Add readiness/start preview and explicit scope/delegation; derive concrete child authorizations without pretending
  the owner confirmed hashes of future content.
- Implement phase/task routing, judge paths and bounded remediation/no-progress controls with persistent task
  lineage, optional consumption caps and explicit quota/auth/environment stops.
- Implement durable owner questions, current-answer validation, pause/resume/revocation and final criterion coverage,
  with minimal visible start/stop/resume/question inspection before the full inbox/graph. Never infer stopped writers,
  retry uncertain inference or count abandoned phases as successful completion.

**Evidence:** multi-phase synthetic completion, long valid roadmaps, gaps, limits, revocation and stale-answer recovery.
**Basis:** B01–B02, B05–B07, B10–B13, B17–B19, B21–B23.

## P002-T017 — Global inbox and guarded shortcuts

**Problem:** actionable events and questions need one durable cross-project entry point in both operating modes.
**Expected result:** visible origin, useful context and current authorized actions for notifications/owner requests.
**Dependencies:** T005, T006, T015, T016.

**Subtasks:**

- Agree taxonomy and shortcuts with the owner; implement project/phase/task/run links, unread vs unresolved states
  and bounded global/project filtering.
- Derive deduplicated inbox items from committed events, including normal-mode task/phase events and autonomous
  questions; persist across browser closure/restart and keep optional OS delivery secondary.
- Route answers/shortcuts through ordinary guarded commands with current revisions/READY, idempotency and archive
  restrictions; a notification never serves as evergreen approval.

**Evidence:** both-mode event/response journeys, duplicate delivery, stale actions and query-only controls.
**Basis:** B10, B12–B13, B17–B19, B23.

## P002-T018 — Task graph and correlated trace views

**Problem:** users need to inspect actual task instances and agent work without reading raw workflow storage.
**Expected result:** a comfortable graph/detail experience linked to complete observable traces and knowledge access.
**Dependencies:** T006, T007, T012, T015, T016, T017; owner-supplied visual direction before layout adoption.

**Subtasks:**

- Agree phase/task cards, navigation and required information with the owner; provide bounded projections rather
  than a visual workflow editor or another executable graph authority.
- Show agent identity/configuration, stage/status, defined turn/attempt/tool counters, errors and phase-operation
  involvement; attribute deterministic stages to Harness and label missing telemetry honestly.
- Add trace/knowledge-receipt drill-down, lazy history and refresh semantics, accessible alternatives and read-only
  archive parity. Choose streaming only when it improves the agreed experience over existing polling.

**Evidence:** realistic-size synthetic histories, UI accessibility/navigation, refresh gaps and archive rendering.
**Basis:** B05, B10–B11, B17, B19–B20, B23.

## P002-T019 — Accounting and efficiency analysis

**Problem:** new roles, operations and discovery/context paths change attribution and can obscure consumption.
**Expected result:** P001-compatible accounting covers the complete hierarchy and efficiency claims have evidence.
**Dependencies:** T006, T008, T009, T014, T015, T016.

**Subtasks:**

- Verify every inference entry path already creates expected invocation records; extend aggregation/filtering across
  workflow/operation/role identities without treating discovery events or cached/cumulative values as extra calls.
- Preserve reference/billing provenance, unknown coverage, API/archive semantics and useful display in trace and
  accounting views, including partial interrupted results.
- Measure representative context/catalogue sizes, retrieval/discovery overhead, latency and completion quality;
  document observed efficiency and limitations instead of guaranteeing token savings or subscription quota.

**Evidence:** synthetic ledger/projection parity, counter/provenance checks and reproducible benchmark fixtures.
**Basis:** B08–B11, B13, B18, B21–B23.

## P002-T020 — Installed-state migration and integrated recovery

**Problem:** the redesigned authority/runtime must preserve existing installations and recover across all persisted effects.
**Expected result:** a verified conversion/backup/restore path preserves legacy evidence and coherent new execution
state, with explicit handling of unsupported continuations. **Dependencies:** T003–T007, T011, T013–T017, T019.

**Subtasks:**

- Qualify conversion from existing adopted documents/definitions and database records with stable mappings,
  pre-migration verification, original preservation and no invented historical access/turn records.
- Exercise graph/domain/CLI/Git/export crash boundaries, version drift, uncertain writers and explicit confirm-stopped;
  recover pending deterministic effects without repeating inference.
- Extend full backup, project portability, referenced artifacts and query-only consultation; test restoration on a
  separate synthetic root without silently restoring execution authority or exposing unrelated projects.

**Evidence:** migration fixtures, fault-injection matrix, verified backups/portable bundles and archive regression.
**Basis:** B02–B03, B10–B17, B19, B21–B23.

## P002-T021 — Integrated security and provider audit

**Problem:** individually passing features do not establish safe combined authority or provider compatibility.
**Expected result:** an explicit audit of the integrated threat model, capability matrix and failure behavior, with
findings resolved or recorded as owner-visible release blockers. **Dependencies:** T002, T008–T010, T016, T017, T020.

**Subtasks:**

- Audit prompt injection, schema/catalogue poisoning, cross-project access, caller forgery, self-adoption, compound
  standing grants, revocation, generated-target boundaries and exposed same-user/isolation limitations.
- Audit provider adapters, usage/event completeness, unexpected output, process cancellation, hidden retries and
  discoverability; include portable broker conformance, generic-dispatch authority and client/provider separation.
  Evaluate judge unsafe grants/escalations and preservation of owner criteria.
- Review the integrated recovery/trace evidence and document supported scope. Any real-provider qualification is
  separately authorized on disposable synthetic projects; do not claim absent real evidence as passed.

**Evidence:** review findings, adversarial fixtures, resolved blockers and explicit residual limitations.
**Basis:** B05–B13, B18–B23.

## P002-T022 — Complete journeys and usability qualification

**Problem:** the full redesign must be useful from intake through completion and preserve normal-mode operation.
**Expected result:** reproducible end-to-end evidence covers the proposed phase criteria and the owner's agreed UI.
**Dependencies:** T011–T021.

**Subtasks:**

- Qualify new-project definition and existing-code reverse engineering through multiple tasks/phases, local repair,
  final closure and complete-roadmap coverage; include document export/manual import.
- Qualify manual-mode tasks/phases, global inbox shortcuts, owner answers, graph/access traces, accounting and
  interrupted-work recovery, including stale actions and query-only consultation.
- Review en/es, accessibility, practical history/context sizes and owner-supplied graph design; run appropriate full
  repository/package checks and map every exit criterion to evidence or an explicit unresolved blocker.

**Evidence:** synthetic journey matrix, usability review and integrated check results; real-provider scope is labelled.
**Basis:** B01–B24.

## P002-T023 — Release qualification and delivery disposition

**Problem:** a source-complete redesign is not yet a verified installable 0.2.0 release.
**Expected result:** coherent operator/developer documentation and qualified distributables, with every authorized
delivery stage tracked to its actual outcome. **Dependencies:** T021, T022.

**Subtasks:**

- Finalize specification/architecture/data/flows/API/client types, changelog, supported-scope and migration/operation
  guidance; distinguish generated document import, project portability, full recovery and unsupported capabilities.
- Qualify exact locked dependencies, offline package/UI/migrations, self-contained archives/checksums and installed
  synthetic first-use/upgrade behavior; update version metadata together at the agreed release point.
- Record source/integration status; perform release PR/merge/tag, publication/download verification and local
  installation only with explicit authorization, or keep pending delivery visible with an agreed deferral.

**Evidence:** qualification/release artifacts, actual delivery ledger and current STATE/NEXT_STEPS; no premature
phase completion or installed/runtime claim. **Basis:** B09, B21–B24; D235/D242/D253/D261.

## Next action

Review/refine this draft and its [design basis](phase/P002-design-basis.md), then adopt the plan before T001. The
smallest unresolved architectural gates are the CLI discovery/capability contract, operation/checkpoint recovery,
structured revision boundaries and generated-document import/ownership rules. Those gates are assigned above;
they do not require pretending the entire refactor can be fully specified in one conversation.
