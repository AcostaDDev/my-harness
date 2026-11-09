# P002 — Structured knowledge and invocation orchestration proposal

## 1. Status, ownership and delivery

**Status:** adopted as P002 v0.5 planning by the owner on 2026-11-09
([D323](../DECISIONS.md#d323--p002-v05-planning-adoption-and-prerequisites-before-journey-qualification)), after review
of the coverage corrections and human-editing extension. Scope, responsibilities, matrices and acceptance are the
planning basis for [T030–T038 in NEXT_STEPS](../NEXT_STEPS.md#p002-t030--semantic-context-and-human-editing-contracts-and-d321-feasibility).
D321/D322 remain accepted policies. **T030 is next and not complete:** it must resolve the pending designs,
mechanism feasibility, schemas and impact choices. No product behavior, new format or qualified profile is delivered.

**Owner:** P002 v0.5 planning adoption; T030 owns subsequent design resolution. Documentation topic branch:
`docs/p002-knowledge-context-proposal`, from clean `develop` at `812559f`. Delivery remains checked source
→ `develop` → 0.2.0 through protected `main` → verified distribution/publication → operator installation, with each
stage recorded separately. The owner authorized the checked documentation commit, merge into develop and push
of develop for this adoption. Implementation, provider/harness runs, network installation and operational delivery
are not authorized by that instruction. The operator installation remains 0.1.9.

This repository remains manually developed and Markdown-owned. Its own AGENTS.md and documentation discovery
instructions are not runtime instructions for harness-managed projects and are not changed by this proposal.

**Coverage review correction:** this revision separates export ownership from protected source selection, inventories
every inference entry point from T025 and assigns gate/evidence evaluation design, implementation and acceptance.
These coverage obligations are adopted as planning under D323; D321/D322, existing IDs and frozen histories are unchanged.

**Human-editing review extension:** §10.1–§10.6 is adopted as UI planning coverage for the six documents and
canonical instructions, including recoverable incomplete work, exact adoption, separate export and execution
impact obligations. It preserves [D293](../DECISIONS.md#d293--owner-knowledge-consultation-and-exact-adoption-presentation)
and [D298](../DECISIONS.md#d298--structured-manual-phase-plans-and-sealed-lifecycle-exports). T030 still resolves its
design/storage/impact contracts; T037 implementation and visual acceptance remain pending.

## 2. What exists and what is missing

The owner's database-authority direction was accepted in D269–D271; it was not wholly omitted. There are important
differences between that direction, the implemented foundations and the more specific behavior requested now.

| Area | Current evidence | Remaining difference |
|---|---|---|
| Knowledge | D284; `core/engine/knowledge.py` defines requirements, criteria, phases, tasks, decisions and sections | Subtasks are strings; evidence is task text; no first-class project gate or task-to-decision/architecture link exists |
| Instructions | D285/D288; active DB instruction sections are mandatory in canonical contexts | All applicable generic/client sections are injected; imported discovery prose can still request file discovery |
| Context | T007; `frozen_context.assemble` selects explicit IDs, fixes revision and records exact exposure | It does not resolve a semantic task dependency/context closure or choose content by workflow stage |
| Task consumer | `services/knowledge_delivery.task_context_snapshot` selects the task identity | Links accompany that entity, but linked bodies such as decisions/architecture are not automatically selected |
| Execution contract | D301; `services/autonomous_review.task_contract` renders a typed proposal to task Markdown and checks the deterministic parser's result | The new typed runtime path should admit the validated contract directly, without a Markdown intermediate |
| Agent queries | T007/T008; `knowledge.lookup` and `knowledge.search` through the scoped broker | The missing entity types and relations cannot be queried; relation traversal and typed change proposals need definition |
| Documents | D294/T013; deterministic marked Markdown plus `docs/.harness/knowledge.json` | Round-trip framing exists; rich section bodies remain generic and current task fields cannot express the requested semantics |
| Graphs | `orchestration/task.py` and `phase.py` each wrap `work()` in one node; roadmap has advance/hold nodes | Task/reviewer/executor transitions and context assembly are not explicit graph stages |
| Instruction exports | D294 requires AGENTS.md and permits selected client wrappers | Runtime independence does not yet mean an optional compatibility-only export contract |
| File access | Codex argv already sets `project_doc_max_bytes=0`; file/shell access remains available by role | Preventing automatic loading does not prove prevention of deliberate raw reads, including Git/history/shell reads |
| Views | D315; canonical drawer uses DB rendering, with a separate legacy checkout lane | Entity navigation, relations and bounded semantic reads need to cover the expanded model |

References: [T004](P002-T004-knowledge.md), [T007](P002-T007-frozen-context.md),
[T013](P002-T013-document-roundtrip.md), [T023](P002-T023-trace-docs.md),
[T025](P002-T025-accounting-efficiency.md), [T026](P002-T026-installed-recovery.md),
[T027](P002-T027-security-provider-audit.md), [data model](../DDBB-DIAGRAM.md#p002-structured-knowledge).
These are observations from source, not newly executed product qualification.

## 3. Proposed authority and boundaries

1. SQLite accepted knowledge is the source of project intent; operational records are the source of execution
   facts. Markdown is an import/export view. No runtime stage discovers project intent by opening generated files.
2. A versioned LangGraph graph owns workflow transitions and selects the context policy for each invocation.
   Deterministic harness services resolve, validate, assemble, persist and deliver the context. An LLM is not
   needed to decide which explicitly required rule to supply.
3. An agent proposes typed changes or obtains bounded knowledge through harness tools. It cannot write canonical
   records with SQL, assign execution facts, approve its own proposal or edit owned documentary exports.
4. Human UI, imports, intake proposals and agent tools share the same domain validation/adoption path. The
   authorized owner/delegation policy still determines adoption; typed data is not authorization.
5. Sessions may remain stateless at the model level. Graph continuation state still needs run/operation/revision
   references for routing and recovery under D282/D283. This is not conversation memory or a second knowledge store.

LangGraph and its installed `langchain_core` primitives already provide the local graph interfaces. Adding the
top-level LangChain package, an API-backed agent runtime, a vector database or a new inference launcher is not a
prerequisite for these contracts. Any dependency change still needs its own recorded exact-version decision.

## 4. Logical model before physical tables

Keep stable project-scoped identities, immutable accepted versions, provenance, linear adoption and typed
revision-bound links. A concept needs its own identity when it must be referenced, retrieved, constrained or
tracked independently. A title or Markdown heading alone is not an identity.

| Record | Proposed content and ownership | Important constraints |
|---|---|---|
| Project knowledge | Existing project root, language and accepted revision | No machine path is used as a portable identity |
| Requirement | Title, statement, active/retired definition status | Project-wide; not forced into one phase |
| Criterion | A checkable condition, owner and evidence requirements | Exactly one requirement, phase, task or subtask owner |
| Phase | Title, objective, scope, exclusions, planned delivery, criteria | Part of the project roadmap; execution state is separate |
| Task | Title, problem, objective/result, scope, exclusions, delivery requirements | Exactly one phase; operational contract retains paths/commands/permissions and its own admission |
| Subtask | Stable ID, title, outcome and ordered parent | Parent task or subtask, acyclic; exactly one root task and inherited phase |
| Decision | Existing context, decision, alternatives, consequences and provenance | Accepted content remains immutable; supersede explicitly, never edit history |
| Section | Typed document/block, title, rich body and ordered parent | Same-document tree; document and block type constrain valid fields/relations |
| Gate definition | Title, purpose, finite evaluator kind, required inputs, applicability and failure action | Owner/phase/task applicability is explicit; agent text cannot invent runnable checks or grant authority |
| Evidence requirement | What must be demonstrated, criterion/gate owner, accepted evidence kinds | Normative requirement only; importing it does not assert that evidence exists |
| Evidence association | Existing run/attempt/check/artifact reference, subject and exact revision/content | Operational fact, created by the harness from verified records; not ordinary portable knowledge |
| Instruction rule | Versioned instruction content, applicability, role/client/workflow stage and scope | Owner-sensitive change; applicable mandatory rules cannot be silently dropped for token savings |

Subtasks are persistent reviewable decomposition, not separately queued execution contracts in this proposal.
Their nesting is explicitly bounded and their result is supported by the owning task's verified evidence; an
agent-written checkbox is not completion. Independently scheduling subtasks would be a separate lifecycle change.

Global requirements, architecture, decisions and rules remain project-scoped and reusable across phases. Tasks
and their decomposition belong to a phase through their parentage; do not duplicate every global decision in each
phase. Normative gate definitions are also distinct from the harness's built-in authorization/READY guards.

Proposed typed relations, with exact endpoint/cardinality rules to adopt in T030:

- Existing `part_of`, `criterion_of`, `depends_on`, `addresses`, `supersedes` and `replaces` keep their meanings.
  Extend parentage for subtasks without changing task replacement families or correction budgets. Phase dependency
  links need explicit phase-to-phase endpoint rules; they are not valid under today's task-only dependency rule.
- `governed_by`: phase/task/subtask → accepted decision. Cross-cutting applicability also contributes required
  decisions; a task author cannot omit a global rule merely by leaving out this link.
- `uses_architecture`: phase/task/subtask → architecture block. Dependencies between architecture blocks are
  separate explicit links, not inferred from Markdown mentions.
- `requires_gate`: phase/task/subtask → gate definition; `requires_evidence`: criterion/gate → evidence requirement.
- `applies_to`: instruction/gate/architecture rule → an admitted project scope. Closed scope forms distinguish
  all-project, entity and component/path applicability; no arbitrary executable filter is accepted.
- Operational evidence associations resolve existing records separately. Do not make knowledge adoption fabricate
  an evidence record or an execution state.

All endpoints must resolve in the same project/revision, except explicitly classified historical evidence
references. Ordered trees have one parent and stable sibling order; dependency/supersession graphs are acyclic.
Relation changes participate in revision hashes and adoption previews. Textual cross-references remain prose until
an explicit typed relation is proposed and validated; the renderer never promotes them automatically.

T031 should extend the current item/version/revision/link model where it fits. A new logical entity does not
automatically require a separate SQL table; operational evidence and authority must retain their distinct owners.

### 4.1 Gate evaluation and evidence coverage responsibilities

T030 owns the evaluation contract, not only the gate definition schema. It must define the following before
dependent implementation; the semantic cases below are required coverage, not adopted enum names or wire schemas:

| Design obligation | Required resolution in T030 |
|---|---|
| States and transitions | Distinguish a gate definition, an evaluation outcome and evidence coverage. Define initial/pending, satisfied, failed, unknown, stale/expired and explicitly inapplicable cases, plus how reevaluation changes current status while preserving past evaluations |
| Evaluators | A closed, versioned registry of harness evaluators and allowed evidence kinds, including verified validation results, capability/authority checks and explicit owner attestations where policy permits them. Define unsupported evaluator/error behavior; agent-authored predicates or executable prose are not evaluators |
| Inputs and attribution | Bind the gate/requirement versions, subject and scope, knowledge revision, exact code/contract, profile/check definition, verified source records and evaluator version. Mark non-code gates explicitly; do not invent an irrelevant code binding |
| Validity | Specify freshness rules, clocks where relevant, and invalidation on changed code/revision/contract/check/profile, revoked authority or unavailable source evidence. A previous pass does not imply a current pass |
| Coverage | Map every required criterion/evidence requirement to admissible verified witnesses. Specify conjunction, optional alternatives and applicability explicitly; an aggregate percentage or one passing check cannot conceal a missing mandatory witness |
| Boundaries | Map applicable gates to intake/conversion promotion and profile/preparation/activation, task selection/admission/inference, validation/review/acceptance, execution-linked export/commit, phase READY/closure and autonomous admission/continuation/resume. Identify which checks run before each effect and which must be repeated at its fenced transaction |

Normative project gates cannot weaken built-in permission, independent acceptance, READY or single-writer guards.
Knowledge adoption or a standalone document export is not automatically proof of execution readiness. T030 must
specify the applicable gate set at each boundary rather than imposing every execution gate on every document edit.

| Evidence case | Required acceptance behavior for a mandatory gate |
|---|---|
| Absent | No admissible witness exists; coverage is incomplete and the guarded transition is refused |
| Unknown | An invocation/process/result exists but its relevant outcome or integrity cannot be established; preserve unknown and refuse satisfaction |
| Failed | A verified relevant check failed; retain the failure and refuse satisfaction |
| Stale/expired | A former witness no longer matches current bindings or validity; retain historical success, require fresh admissible evidence and refuse satisfaction |
| Agent claim or imported assertion | Text, a checkbox, an imported status or a model-proposed evidence ID alone creates no verified witness and cannot satisfy a gate |
| Current admissible evidence | Only the harness evaluator may record satisfaction after source integrity, scope, bindings, freshness and all required coverage are verified |

An inapplicable requirement needs a validated applicability rule or the separately authorized disposition defined
by T030; it cannot be manufactured by labelling absent evidence optional. An owner attestation, if admitted, is a
verified owner-origin operational record, not imported prose or the agent relaying that an owner approved.

Implementation ownership is explicit: **T031** owns persisted evaluation/evidence associations and history
invariants; **T033** owns the shared evaluator registry, current-outcome/coverage calculation and bounded queries;
**T034** owns invocation/lifecycle/effect-boundary guards and revalidation; **T036** owns intake/conversion/profile
consumer guards; **T037** owns truthful UI projection; **T038** audits their integration. T032 must reject attempts
to import operational satisfaction. Their acceptance tests cover every row above, a valid positive control,
source deletion/unavailability, wrong subject/revision/code, evaluator failure and invalidation between preview
and effect. Missing/unknown/failed/stale witnesses cannot be promoted to success by replay, restore or aggregation.

## 5. Document block contracts

Define a closed, versioned semantic schema first, then a deterministic Markdown projection. Arbitrary prose is
allowed only in declared rich-text fields. Unknown keys, invalid parentage, unresolved references, duplicate IDs
and invalid enum values are located validation failures, not opportunities for a model to repair the input.

| Document | Required blocks and permitted sub-blocks | Import meaning |
|---|---|---|
| SPECIFICATION.md | Purpose/objectives; scope/exclusions; identified requirements with criteria; assumptions/unknowns; optional narrative extensions as identified sections | Project intent; narrative organization may vary while the envelope, requirement IDs, criteria and references stay typed |
| ARCHITECTURE.md | Overview; identified component/interface/invariant/data-flow/deployment blocks with responsibilities, boundaries and relations; declared rich Markdown/Mermaid | Versioned design, not proof that code already implements it; data-model/flow blocks retain their own logical document ownership |
| DECISIONS.md | Decision index; identified records with context, resolution, alternatives, consequences, provenance and supersession links | Draft proposals or explicitly reviewed historical records; accepted decisions cannot be rewritten by an import |
| ROADMAP.md | Project objective; ordered phases with objective, scope/exclusions, criteria, dependencies and planned delivery | Planned intent; CLOSED/READY/actual release facts are read-only operational projections |
| NEXT_STEPS.md | Active-phase reference and next-task projection; ordered task trees with subtasks, criteria, decision/architecture/dependency links, gates and evidence requirements | Task definitions and decomposition; next executable task and verified completion come from harness policy/evidence |
| STATE.md | Accepted revision; active phase; definition/delivery summary; derived task/run/gate status, blockers and evidence links with explicit unknowns | Generated consultation snapshot; imported execution/approval/READY/installation claims cannot become authority |

NEXT_STEPS is a **tree for ownership and display**, and a **graph for references**. A decision shared by ten tasks
exists once; each task refers to its ID. Gates and evidence requirements displayed beside subtasks do not become
children of those subtasks unless they actually have that normative owner. Dependencies do not change parentage.

For example, the following is an illustrative semantic payload, **not an implemented wire format**. T030 must
publish the complete closed schemas and field-to-Markdown mapping before T031/T032 implement them:

```json
{
  "format": "harness-task-definition-2",
  "phase": "P003",
  "task": {
    "code": "P003-T002",
    "title": "Validate an imported plan",
    "problem": "Malformed references can enter a proposed plan.",
    "expected_result": "Reject invalid references with a located diagnostic.",
    "scope": ["plan validation"],
    "exclusions": ["changing accepted history"],
    "depends_on": ["P003-T001"],
    "criteria": [{"code": "C010", "statement": "An unknown decision reference is refused.", "evidence_requirements": ["E010"]}],
    "subtasks": [{"code": "P003-T002-S001", "title": "Validate decision links", "subtasks": []}],
    "decisions": ["D010"],
    "architecture": ["architecture/plan-validator"],
    "gates": ["G010"]
  }
}
```

The full project revision supplies all referenced definitions. An isolated task payload cannot adopt unresolved
references. Codes are human labels resolved to stable local identities under the import mapping; code equality
never silently grants cross-project identity or authority.

STATE should not become a seventh editable knowledge model mirroring operational tables. Its editable narrative,
if needed, is an identified section; task status, blockers and delivery are projections from their owning records.
Planned delivery and verified delivery are separate fields/sources. Export seals its operational input snapshot
and provenance so the same sealed inputs render the same bytes without a wall-clock-dependent renderer.

## 6. Versioned import/export and compatibility

Retain the useful T013 discipline: the supported round-trip unit is marked Markdown **plus its typed companion**,
or the standalone portable typed envelope. Six ordinary Markdown files alone do not reconstruct strong types,
stable identities and graph relations reliably. A stricter v2 must extend, not pretend to have invented, that codec.

For each field, the new contract must define its type, required/optional/null semantics, source of authority,
ordering, stable locator, size bound, applicable document/block, import disposition and export representation.
T030 supplies schemas and valid/invalid synthetic examples for every document and relation, including en/es
decoration. Names ending in `-2` here are proposed version labels, not registrations in the live catalogue.

- Harness rendering writes all generated bytes; agents submit values/references and never hand-author markers.
- Import is deterministic parsing → source retention → located diagnostics/mapping → draft → exact preview →
  authorized adoption. Unknown format versions fail explicitly. Invalid content never triggers silent LLM repair.
- Partial imports keep unselected entities/relationships; omission does not delete. Existing ownership, clean
  baseline, original-byte preservation and recoverable export/commit rules remain in force.
- Keep v1 readers, historical renderers, manifests, fingerprints, receipts and frozen prompts intact. A versioned
  conversion maps old subtask strings to fresh IDs preserving order and provenance. It does not infer decisions,
  gates, completed evidence or phase relationships from similar wording.
- Conversion preview identifies missing semantics and blocks affected execution until resolved or explicitly
  classified as inapplicable under the adopted schema. Do not label an incomplete conversion runtime-ready.
- Never replay imported operational/approval facts as local history. Optional historical display stays explicitly
  source-claimed and cannot satisfy gates or count as evidence.

Arbitrary existing documentation belongs to the separate onboarding source lane. The harness may ingest and chunk
owner-selected bytes, and an agent may propose a mapping with known/inferred/unknown provenance; this is not a
strict-format import and cannot bypass its preview/adoption. Unmapped material remains preserved and visible.

## 7. Dynamic context policy

Proposed deterministic per-invocation pipeline:

```mermaid
flowchart LR
    A["Resolve project, phase, task and stage"] --> B["Pin accepted revision and capabilities"]
    B --> C["Resolve mandatory rules and typed relations"]
    C --> D["Apply role policy and byte budgets"]
    D --> E["Seal context and scoped tool surface"]
    E --> F["Invoke agent through supervisor"]
    F --> G["Validate typed result and settle operation"]
    G --> H["Guarded transition or durable wait"]
```

The task bundle includes the task/decomposition, owning phase objective/criteria, applicable requirements and
criteria, governing decisions and architecture, gates/evidence requirements, allowed scope and independent
acceptance contract. Include full required normative content; a summary is not a substitute for an applicable
rule. Optional background starts as bounded metadata/references and is fetched on demand. Resolve replacement and
decision supersession explicitly, preserving relevant partial supersession rather than treating every old record
as simply inactive.

| Invocation purpose | Additional context |
|---|---|
| Plan | Existing plan, dependency readiness, missing knowledge and scope/delivery constraints |
| Execute | Frozen execution contract, permitted code scope, relevant design and verified prior review findings |
| Review | Exact evaluated code/diff, acceptance criteria, validation evidence, executor claims labelled as claims |
| Judge | Only its duty-specific subject, admissible choices, authority boundary and required evidence |
| Phase check/close | Phase criteria, task evidence coverage, unresolved gates and delivery obligations |
| Contextual chat | Explicit selected element plus bounded related knowledge/evidence under its own purpose policy |

Each selection records a versioned policy, selection reason/path, revision, entity versions, source bytes and
exposure digests. Required context exceeding a bound produces a typed stop with the blocking entities; it is not
silently truncated or replaced with raw-file discovery. Optional pagination/truncation is explicit. T030 must set
the exact bounds and overflow behavior before implementation, taking T007's current bounds into account.

All knowledge tools default to the same pinned revision. A new adoption applies at an explicitly admitted fresh
boundary after revalidation, never midway through one invocation. A reviewer and executor may receive different
role-specific views of the same accepted revision; neither relies on the other to forward mandatory project rules.

Stateless calls still receive the small necessary instruction set each time. The saving comes from eliminating
repeated document discovery, unrelated history and duplicated instructions. Cross-call zero-token memory or provider
prompt-cache savings are not promised. Measure delivered bytes, queries, coverage and actual known usage separately.

### 7.1 Complete inference-entry coverage matrix

Baseline inventory: [T025 — inference entry points and persistence](P002-T025-accounting-efficiency.md#inference-entry-points-and-persistence).
The eight T025 route families are expanded below so ordinary and special-purpose lanes have named owners. This
is a proposed target matrix, not a claim that the current graphs already cover them. Graph/stage labels are
logical responsibilities; T030 must settle registered names/versions, stage policies and exact source schemas.
All policies are versioned and sealed per invocation, with purpose, source provenance, bounds and exposure receipts.

**DB** means verified accepted knowledge at the pinned revision. **Bootstrap** means harness-captured selected
sources, questions/answers and inventory before adoption, exposed through bounded source tools. **Other** means
the explicitly confirmed technical/configuration/conversation inputs named in that row; it does not authorize
directory discovery. The source-selection boundary in §9 applies even without a knowledge revision or export owner.

| ID / inference route from T025 | Responsible graph / stage | Context policy and permitted source | Implementation owner (planned) | Required route evidence; existing baseline suites |
|---|---|---|---|---|
| I01 Task planner | task / plan | Planning policy: DB task/phase/relations plus frozen execution scope and admissible code captures | T034, using T033 resolver | Complete required bundle and stale-revision refusal; `test_usage_accounting`, `test_operation_journal`, T014 task fixtures |
| I02 Task executor, including corrections/retry | task / execute | Execution policy: DB task contract/rules, exact code scope and verified prior review findings; new admitted attempt for a retry | T034 | Same required rules across corrections, no raw rediscovery, no duplicate invocation on replay; T014 fixtures, `test_autonomous_journey` |
| I03 Task reviewer, including correction rounds | task / review | Review policy: DB criteria/decisions/gates plus exact evaluated code, checks and separately labelled agent claims | T034 | Independent acceptance with complete evidence and failed/unknown/stale refusal; `test_operation_journal`, T014 fixtures |
| I04 Phase check and inference used by closure | phase / check; close consumes the guarded result | Phase policy: DB phase/task coverage, unresolved gates and delivery; verified check/effect records | T034 | Current READY/closure binding and no inferred completion; `test_structured_phases`, `test_autonomous_journey` |
| I05 Structured phase planning | phase / plan | Phase planning policy: DB objectives/criteria, previous accepted plan, verified task evidence and open questions | T034 | Typed proposal and unchanged authoritative revision until adoption; `test_structured_phases` |
| I06 Ordinary phase-planning conversation (`planning_turn`, `phase_planning`) | planning / phase conversation | Planning policy: DB if adopted; otherwise explicit Bootstrap source selection plus owner conversation, with no file-discovery fallback | T034; T036 for pre-adoption binding | Both source modes and refusal of an unconverted raw-reading path; planning/supervisor fixtures and `test_structured_phases` |
| I07 New-project definition / initial setup conversation | intake / define | Bootstrap definition policy: frozen owner specification, selected originals, answers and unknowns through source tools; no accepted revision required | T036; T034 stage binding | No export ownership/head required, bounded source receipts and typed draft; `test_structured_intake` |
| I08 Existing-project onboarding / reverse engineering | intake / onboard | Bootstrap onboarding policy: captured committed code inventory and selected documentary/instruction sources through source tools; known/inferred/unknown attribution | T036; T035 boundary | Original/copy/history bypass refusal before and after adoption, preserved provenance; `test_onboarding_conversation`, `test_structured_intake` |
| I09 Legacy bootstrap discovery (`bootstrap_discovery`) | intake / legacy discovery admission or reconciliation | Explicit legacy disposition: retained original evidence for read/reconcile; any fresh inference needs a newly admitted bounded Bootstrap contract and D321-qualified profile | T036; T034 admission | Retired route stays closed to new legacy runs; no inference from an unqualified saved raw-read contract and no snapshot rewriting; bootstrap/supervisor fixtures |
| I10 Ordinary chat, project or global | chat / ordinary turn | Conversation policy: frozen conversation; project DB/rules when scoped, or explicit Bootstrap source selection if admitted pre-adoption. Global chat has only conversation/service policy; no implicit project/filesystem context | T034; T036 for Bootstrap sources | Ordinary and global coverage, scope isolation and no untagged legacy/raw fallback; `test_chat_global`, `test_chat_context` |
| I11 Contextual chat | chat / contextual turn | Element policy: DB phase/task and verified retained run/step evidence, frozen selected element plus bounded related knowledge | T034, using T033 | Element/source revision and receipt parity, no checkout substitution; `test_chat_context`, T024 fixtures |
| I12 Autonomous readiness review | roadmap / readiness review | Readiness policy: DB roadmap/criteria and verified task/gate/evidence coverage, authority and budgets | T034 | Missing/unknown/stale coverage prevents advancement; counted invocation and caps; `test_autonomous_journey` |
| I13 Delegated task-contract review | roadmap / task-contract review | Delegated planning policy: DB task/references, frozen profile/code, scope, current delegation and evidence | T034 | Typed contract admission, permission/budget/current-revision checks; `test_autonomous_journey` |
| I14 Judge: permission, planning_choice, spec_gap and blocked_check | judge / duty admission, invoke and result | Separate duty policies: pinned DB subject/rules plus verified request/evidence/authority and admissible choices; no unrelated project dump | T034, using T033; T035 qualification | Each of four duties, unqualified role refusal, invalid evidence and no ruling-as-owner-approval; `test_judge` |
| I15 Generic preparation executor | preparation / confirmed executor step | Technical-preparation policy: Other confirmed technical plan/profile/dependency/tool inputs and admitted code captures; applicable DB rules if a revision exists, explicit Bootstrap rules/sources otherwise | T034; T035 boundary; T036 pre-adoption sources | Dedicated context seal despite its separate process journal, purpose/step binding, source bypass refusal, uncertainty/ledger parity; `test_profile_preparation` |
| I16 Project configuration assistance, reviewer and executor variants | configuration assistance / project ASSIST | Assistance policy: Other confirmed candidate configuration and owner request/private scratch scope; project constraints from DB or explicit Bootstrap source tools, replacing document-file reads | T034; T035 boundary; T036 Bootstrap binding | Both roles, protected-source reads refused, sensitive configuration kept purpose-scoped, one ASSIST/ledger seal; `test_configuration_editing`, `test_usage_accounting` |
| I17 Global configuration assistance, reviewer and executor variants | configuration assistance / global ASSIST | Global assistance policy: Other confirmed candidate configuration, owner request and service rules in private scratch; no project DB or project-document access | T034; T035 boundary | Both roles, no implicit project selection or file access, intent/result/recovery attribution; `test_configuration_editing`, `test_usage_accounting` |

The evidence column is an obligation for future changes; the named suites only identify baseline coverage and have
not been run for this proposal. T030 records a crosswalk from every T025 family to these rows and each row to an
actual inference admission call site. T034 owns the launch-site audit and context-stage binding for managed calls,
generic preparation and ASSIST, preserving their existing journal/ledger owners. T036 completes the pre-adoption
source consumers. T038 must demonstrate that every reachable launch has a covered row, a sealed policy and an
enforced source boundary, including retries, interrupted work and both ordinary/autonomous modes. A nominal graph
wrapper or an existing accounting link alone does not establish context coverage.

**Explicit exceptions/dispositions for owner review in T030:** no inference route is exempt from purpose/context
admission, D321 or accounting. The proposed exceptions to a full *project* DB bundle are (X1) global chat/ASSIST,
which have no project subject, and (X2) generic preparation, which gets only applicable project constraints plus
its confirmed technical scope. Pre-adoption Bootstrap is an explicit source mode, not an exemption. For I09,
retirement excludes new legacy admission, not the audit of reachable recovery or inference. These dispositions
need owner review; an unresolved disposition blocks that route in the new path rather than silently excluding it.
Deterministic commands, validations, imports, document/commit effects, capability checks and tool reads cause no
new inference and keep their guards/receipts; any model call added to them needs its own matrix row and owner.

## 8. Agent read and change tools

Extend/version the existing broker and domain catalogue rather than adding a direct DB or filesystem-document
tool. Candidate semantic operations (final names/schemas belong to T030):

- Get an entity or paged subtree, list/filter task readiness, search within a kind/scope and traverse typed related
  entities with explicit direction, depth and byte/result limits.
- Obtain a task's required context or evidence coverage using the same resolver as initial injection.
- Propose a typed change set: expected accepted revision, operation kinds, entity IDs/temporary IDs, typed values,
  relations, rationale and source evidence. An identical idempotency key returns the same stored outcome.
- Read proposal diagnostics/preview/outcome. Acceptance is a separate owner or explicitly delegated operation;
  mandatory instructions, scope expansions and product decisions retain the applicable sensitive-change policy.

Responses carry project/revision/entity identity, version/hash, exposure level/range, continuation and receipt.
Capabilities, caller identity, current revocation and query-only guards apply on every call, including replay.
Search results are project data, not higher-priority instructions. Claims inside raw source text cannot grant
permissions or bypass validation. No tool accepts SQL, arbitrary file reads or agent-authored execution status.

## 9. Instructions and raw-document access

Proposed runtime policy: canonical instruction rules come from the DB and specify role/stage applicability.
Remove the need for recursive AGENTS → discovery of six documents → prompts that repeat discovery. Existing rules
must be reviewed into explicit applicable constraints, not deleted by automatic summarization. Intake highlights
file-discovery directives and contradictions for resolution; it does not silently rewrite accepted instructions.

The owner explicitly resolved both policy choices on 2026-11-09:

- **Instruction export (D322):** retain AGENTS.md/CLAUDE.md/GEMINI.md as optional compatibility exports for external
  work, independently selected in ownership. Harness invocations do not load them. Existing owned files cannot
  simply be deleted or abandoned without explicit ownership migration and preservation.
- **Read guarantee (D321):** require verifiable technical prevention and refuse a profile that cannot guarantee
  it. A prompt-level prohibition, disabled automatic loading or post-run detection does not meet the requirement.
  With unrestricted shell and a readable checkout, `cat`, `rg`, Python and `git show` can recover raw documentation;
  a file-tool path denylist alone is insufficient. There is no weaker cooperative fallback.

**Export ownership and protected-source selection are separate authorities.** The export manifest determines
which exact files the harness may regenerate. A versioned protected-source selection determines which project
documentation/instructions an invocation may obtain only through harness context/source tools. Selection does
not acquire write ownership; lack of ownership does not make a selected source available for direct agent reads.

The proposed protected set must explicitly cover:

- Harness-owned project knowledge/instruction exports, companion/portable payloads and DB/evidence storage whose
  direct access would bypass scoped delivery.
- Original documentary and instruction sources selected for definition/intake, onboarding/reverse engineering
  and installed/legacy conversion, including unowned inputs before any accepted revision or export manifest exists.
- Those selected originals as reachable through copied HEAD exports, private intake/conversion workspaces,
  temporary/cached copies, retained originals, aliases and Git object/history routes. Protecting the generated
  destination while leaving its selected original or a copied source readable does not meet D321.

T030 must define source-selection identity, content/HEAD binding, lifecycle and how original/copy/history coverage
is established before an agent can access the workspace. It must cover selected sources outside the checkout and
resolve retained archives, nested/client instructions and mixed code/document files explicitly. The selection may
exist without a knowledge project revision; it does not derive from matching export filenames or file extensions.
No automatic loss of protection follows adoption, conversion or a later export ownership change; T030 must define
the explicit scope transition and its admission/revalidation rule.

The harness may capture and read selected originals to supply bounded source tools. Agents receive selected
chunks/locators with source identity, provenance, range/continuation and exposure evidence; they cannot use a source
tool to choose an arbitrary filesystem path or recover a whole raw corpus outside the declared bounds. Code,
tests and separately admitted noncanonical documentation remain available through their permitted route. This is
not an indiscriminate ban on Markdown, source code or all files in a project's documentation directory.

T035 must qualify the required technical boundary against file tools, shell, subprocesses,
symlinks/aliases, Git history/object reads, client autoload and nested instructions. It must also preserve builds,
tests and exact commit semantics. Possible mechanisms require a capability/design decision; do not assume the
current cooperative CLI profiles provide isolation. A profile that cannot enforce the adopted guarantee must
refuse admission, with no silent weaker fallback. Native qualification requires separate explicit authorization.

T035 owns adversarial access-route qualification for originals, copies and history across the matrix in §7.1;
T036 owns end-to-end source selection and tool-only delivery checks in definition, onboarding and conversion,
both before and after adoption/ownership. Each must test denied direct file/shell/Git/copy reads alongside a
successful bounded source-tool read; refusing all source consultation is not a valid positive control.

The enforcement mechanism is still open. T030 must establish feasibility and the exact protected set, including
selected unowned/pre-adoption originals and their alternative routes, admitted access routes, profile/version
qualification and residual limits before T031 or other dependent product work.
That gate prevents implementing the semantic model on an assumed access guarantee. A failed feasibility gate
returns the concrete incompatibility to the owner; it does not authorize relaxing D321.

## 10. Setup, reverse engineering and visual documentation

- **New definition:** before an accepted revision exists, freeze owner-provided specification and answers as
  bounded source evidence. The harness ingests it; the agent receives source chunks/locators through an intake
  service and emits typed draft knowledge. Protect selected originals and copies before the first inference,
  without requiring export ownership. Bootstrap is an explicit lane, not a fallback to directory reads.
- **Existing project:** retain static committed code inventory and reverse engineering. The harness inventories,
  captures and chunks selected documentation/instructions deterministically; the agent works with scoped source
  tools and proposes mappings/unknowns. Strict v1/v2 import, arbitrary-source interpretation and installed-project
  conversion remain distinct workflows with explicit confirmations/provenance. Their selected originals, copied
  inventories/workspaces and history are covered by §9; T036 verifies no alternate direct-read route and no imported
  assertion satisfying a gate. Missing/unknown/failed/stale required evidence blocks the applicable promotion or
  readiness boundary without preventing preservation and review of an incomplete draft.
- **Editing:** forms and agent proposals share schemas and validators; exact diffs show changed relations, sensitive
  rules, provenance and effects on context/readiness. Do not expose raw SQL or require editing a large Markdown blob.
- **Work map/drawer:** keep L0–L4 semantics; show bounded phase/task/subtask trees, decision/architecture links,
  gate/evidence coverage and exact source/revision. Lazy entity reads replace whole-document loading by default;
  full human document export/preview remains available as an explicit view. Existing observed steps are not subtasks.
- **Archives:** serve persisted revisions/evidence with no checkout and no mutation. The legacy checkout lane is
  explicitly labelled and never substitutes for a failed canonical read. Runtime adoption of the new policy must
  not silently accept a legacy file-discovery route.

### 10.1 Human editing matrix

This matrix is the proposed authoring contract, not permission to edit generated files. Editable content means a
working draft for a new accepted knowledge revision. Every relation uses the same domain invariants as agent
proposals/imports. Operational columns are consultation only; their owning commands remain separate UI actions.
All past accepted revisions and retained originals remain read-only, even when a current definition is editable.

| Document / canonical area | Editable content in a draft | Editable relations and order | Operational projections: read-only here | Protected historical content |
|---|---|---|---|---|
| SPECIFICATION.md | Purpose, scope/exclusions, requirement statements, criteria, assumptions/unknowns and declared narrative fields | Requirement/criterion ownership, permitted references, block order and hierarchy | Verified criterion coverage, check outcomes and actual delivery | Prior accepted requirements/criteria/sections, their adoption/provenance records and frozen source versions |
| ARCHITECTURE.md | Component/interface/invariant/flow descriptions and declared Markdown/Mermaid bodies | Component/block dependencies, task/design links and valid section hierarchy/order | Observed implementation/evidence availability and execution-linked check results | Accepted past design versions, sealed diagrams/exports and originals; editing current design does not rewrite what a past run received |
| DECISIONS.md | New proposed decisions: context, resolution, alternatives and consequences; existing proposed draft content | Permitted applicability/governing links; explicit full/partial supersession by a new decision; draft order where schema permits | Operational rulings/approvals are separate records, never decision-field toggles | Accepted, rejected or retired decision content, adoption metadata and retained supersession history; no editing/deleting an immutable record |
| ROADMAP.md | Planned phase objectives, scope/exclusions, criteria and planned delivery | Phase ordering/dependencies and permitted coverage/references | Active/closed phase, READY, actual release/publication/installation, closure/archive results | Adopted plan snapshots, completed phase records, sealed roadmap generations and delivery receipts |
| NEXT_STEPS.md | Task problem/result/scope, identified subtasks, criteria, gate definitions and evidence requirements within their admitted schema | Task-to-phase membership, subtask tree/order, dependencies, criteria coverage, decision/architecture/gate references; replacement uses explicit lineage rules | Next executable task, admitted/running/completed status, verified subtask/gate coverage, attempts/budgets and actual evidence | Admitted execution contracts, accepted past task/plan versions, run evidence, replacement lineage and frozen snapshots |
| STATE.md | Only an explicitly identified narrative section if T030 admits it; no parallel editable execution-state model | Permitted narrative references only; operational navigation is derived from its source records | Current revision, active phase, task/run/gate status, blockers, readiness, evidence and actual delivery | Past state snapshots, recorded blockers/outcomes and historical generation receipts; actor/time/revision fields are never user-authored facts |
| Canonical instructions (DB; compatibility AGENTS/CLAUDE/GEMINI views) | Rule title/body, permitted role/stage/client/scope applicability and declared narrative fields, through the owner-sensitive path | Valid instruction hierarchy/order and applicability references; wrapper selection belongs to separate export ownership | Actual instruction delivery/context associations and client/profile qualification | Prior accepted rules, invocation-delivered bytes/digests and generated wrapper history; no historical rewrite or file-based override |

Human-readable codes and titles help people find entities; internal IDs, revision digests and generated framing
are managed by the harness. Creation allocates identities through the shared commands. Removal, withdrawal,
reparenting and supersession are distinct permitted actions with visible consequences and domain validation;
there is no generic delete that can erase an adopted plan identity, decision or execution history.

### 10.2 Document presentation with entity/block editing

T030 owns the interaction design; T037 implements it. Provide a readable document presentation with its title,
contents/section navigation, ordered headings and rendered narrative blocks. Entering edit mode exposes controls
on the selected block/entity while retaining its document position and nearby context. The document, entity
inspector and work map select the same revision/draft and identity; navigation does not create duplicate records.
Large documents use bounded entity/subtree reads and explicit continuation, not a mandatory whole-file editor.

- Edit scalar fields in labelled controls and narrative fields in Markdown/Mermaid text with a rendered preview.
  Preserve original field text; preview rendering must not normalize saved bodies or execute embedded content.
- Add/edit/reorder subtasks in their task tree, with keyboard alternatives to pointer gestures. Pick relations
  using titles, human codes, type and scope; show their direction, owner and target. Users do not type internal IDs,
  JSON, HTML field markers or renderer tokens. Invalid/unresolved choices remain visible as draft errors.
- Keep read-only operational blocks visible beside definitions, clearly identified with source/revision and
  unavailable/unknown/stale labels. A completion checkbox or status selector cannot mutate an execution fact.
- Immutable decisions open in consultation mode with a separate action to propose a new superseding decision;
  show full/partial extent and consequences in the comparison. Rule changes are visibly owner-sensitive, and
  editing their text cannot change permissions or client qualification.
- Present document status, selected accepted revision/base, saved/unsaved work and pending requests in plain
  language. Explain unavailable edit actions, including archive/unconfigured consultation and protected history,
  without exposing implementation details as mandatory user steps. Localized en/es controls preserve the project's
  work-language content; focus, keyboard navigation and narrow-screen layouts are part of the contract.

### 10.3 Working draft, validation, exact comparison and confirmation

Preserve the [T012 editing/recovery guarantees](P002-T012-knowledge-editing.md#implementation-and-review-map).
The following are separate states and actions, even if the interface offers a convenient sequence between them:

1. **Edit and save draft.** Keep incomplete field values and unresolved relations in a recoverable authoring working
   copy, separate from a valid canonical knowledge draft. Saving work does not require invented values to satisfy
   adoption validation and changes neither the accepted head nor files, plans, READY or execution authority.
   Track project/base/draft identity, order and local buffers; do not erase unsaved work on a read failure,
   validation refusal, navigation, reload or stale server response. Restore incomplete inputs as well as valid
   ones. T030 specifies storage, retention and durability boundaries; T031/T033 provide the required persistence
   and typed working-copy commands, and T037 preserves local buffers/pending envelopes under D293. A save is shown
   as durable only after its acknowledgement; unavailable recovery storage is visible, with explicit retry and
   protection against silently leaving unsaved work. This authoring storage grants no adoption authority.
2. **Validate and prepare comparison.** Valid field/relation edits stage through the shared typed domain commands.
   Keep invalid/incomplete input with located field/entity diagnostics and correction links; never silently repair,
   drop a relation or invent a required value. Unsaved inputs or unresolved validation errors cannot enter an
   adoption preview. T030 defines working-copy versus canonical-draft version bindings so a successful save of an
   incomplete authoring copy is not misrepresented as a valid staged revision.
3. **Review exact changes.** Derive before/after from the verified accepted base and the exact sealed staged draft
   in the preview transaction, including narrative bytes, field changes, added/removed relations, root/child order,
   provenance, supersession and sensitive instructions. A readable document comparison and entity/link details
   expose the full change without JSON; summaries may aid navigation but cannot replace the exact comparison.
   Impact uses verified associations, with explicit truncation/unknowns when unavailable, never guessed joins by
   a matching task code. T030 resolves what impact information is required before acceptance.
4. **Accept changes.** An authorized owner confirms the exact preview/hash, expected head/draft version, reason
   and idempotency key through shared adoption. Adopt the sealed draft, never current unsaved controls. Any input
   edit, relevant reload/refusal or stale head/draft/preview invalidates visible consent and requires a fresh
   comparison. CAS refusal preserves the authoring work and original base. There is no automatic rebase, merge,
   new preview acceptance, retry with a new key or inferred owner confirmation.
5. **Recover a request or resolve a conflict.** Keep the exact pending request body/key across response loss and
   reload, prevent overlapping submissions and offer explicit recovery of that same outcome. Do not submit a
   second adoption while the first outcome is unknown. Clearing a visible preview does not change an already
   dispatched envelope or its previously authorized outcome. A concurrent head change leaves saved work accessible
   alongside the new head; intentional transfer to a newly opened draft is an explicit user resolution, validates
   again and requires new consent. Failed index/head/history/inspection reads can be retried without resetting
   editing buffers; delayed responses cannot replace the current project/revision or clear newer work.
6. **Export documents.** After adoption, export is a separate preview/confirmation/effect using T032's accepted
   revision, ownership/renderer and recoverable delivery receipts. Display accepted knowledge and exported
   generation independently, including export pending/failed/partial or blocked by an ownership/dirty-path guard.
   A failed export does not undo accepted knowledge or lose the draft/request outcome. Recover the same sealed
   export intent; never rerun adoption to repair export. Existing task/phase-owned export effects remain on their
   execution path. Saving or accepting in this editor does not itself commit, export or imply current delivery.

Explicit discard affects only the identified working draft after any pending outcome is resolved; reload and
conflict are not discard. Query-only archives/unconfigured consultation retain D293's read-only mounting without
a project action workspace. T030 must define incomplete-work retention and recovery limits rather than weakening
T012's existing saved-input, exact-envelope and stale-response guarantees.

### 10.4 Impact on adopted plans and running work: T030 design gate

Editing current knowledge cannot silently become lifecycle execution. T030 must publish a matrix of change
categories and affected boundaries before implementation. It must specify which operations can coexist with adoption, which current
bindings become stale, which existing writer guards refuse a mutation and which separate confirmations/actions
are required. The following are constraints and required design coverage, not newly invented cancellation rules:

| Affected area | Preserved guarantee and obligation for T030 / implementing consumers |
|---|---|
| Adopted phase plans and batches | General knowledge adoption does not adopt/reconcile a phase plan. Preserve D298's separate scoped draft validation, exact owner plan preview/hash, CAS and idempotency; product objective/criterion amendments precede that confirmation. Subsequent plan confirmation invalidates READY/batches under D298. Specify task/dependency/criterion/order and instruction change impacts without automatic replanning or identity erasure |
| Admitted tasks and queued work | Admission and execution contracts retain exact task/phase/revision/code/profile/authority bindings and D296 lineage/budgets. Define fresh-boundary checks and stale-contract refusals; editing the document neither rewrites an admitted contract nor implicitly cancels, retries or replaces it. Preserve a working draft when existing writer/pending-effect guards prevent adoption |
| READY and evidence coverage | READY binds its accepted revision and documentary ownership under D298. Do not display an old READY as validating a new head. Keep evidence attributed to its original code/contract/revision; evaluate current applicability/freshness under §4.1. T030 defines recomputation/invalidation and required fresh checks, without editing or deleting historical pass/fail facts |
| Autonomous execution | Knowledge edits grant no new delegation, task scope, budget or continuation authority. Define compatibility checks against the sealed parent/child authorization and next effect boundary, plus explicit owner actions where required. Do not infer cancellation, authorization renewal, expanded roadmap adoption or automatic replanning from an editor confirmation |
| Invocations already in progress | Frozen instructions, context, prompt/catalogue, revision and tool-read revision remain unchanged for that invocation. A later adoption is considered only at a newly admitted boundary after revalidation. No retroactive injection, evidence relabelling, hidden model retry or automatic cancellation is introduced |
| Exports and closure/recovery | Preserve D298's sealed domain/evidence/manifest/Git/archive effects and confirmations. Later editor adoption cannot alter a pending sealed intent or recorded closure; current authority/binding checks still guard pending effects. Show export/readiness pending and resolve any writer conflict without discarding human work |

Existing explicit cancellation and live revocation controls keep their owners and semantics; accepting a document
change does not invoke or replace them.

The preview must distinguish known affected bindings from unavailable associations. D293 currently provides bounded
persisted context/run links and explicitly lacks a revision-bound READY association; this proposal does not claim
that missing association already exists or treat its absence as proof of no impact. T030 specifies the additional
domain evidence needed; T031/T033 own its persisted/read contracts and T034/T036 own consumer enforcement. An
impact explanation never substitutes for D298's independent plan/READY/closure or delegation confirmations.

### 10.5 Transition from the previous document editor

Use the existing [knowledge UI](P002-T012-knowledge-editing.md) and
[documentary lane](../flows/documents.md) as the compatibility baseline, not two writers for the same authority.
T030 defines authoritative classification and transition; T037 implements navigation and editing around it:

- **Canonical document/instruction views:** document navigation and the drawer read accepted DB entities and
  working drafts through shared queries. Their edit actions use T033's typed working-copy/draft/adoption commands,
  never `document_edit`, whole-file writes or a JSON-only editing fallback. This holds even before acquiring export
  ownership or when the generated file is absent. A DB read failure cannot redirect an edit to checkout bytes.
- **Previously opened file editors:** recheck authority/classification at mutation and confirmation. A stale file
  editor cannot write a document that has since become canonical/owned. Preserve unsaved text and any pending
  exact request; resolve an uncertain old outcome before starting a competing mutation. Any transfer of file text
  into canonical knowledge is an explicit import/mapping draft with its own preview, not an automatic conversion
  or silent import. T032/T036 define the transition while T037 presents recovery without requiring marker editing.
- **Noncanonical documents:** keep an explicitly labelled file view. Where the existing documentary contract
  permits edits, retain its confirmed file-edit lane and path/managed-block/CAS/commit/recovery guards; unsupported
  files are view-only. Editing such a file does not adopt knowledge, establish evidence, obtain export ownership
  or exempt a selected protected source from D321. Projects not yet converted retain their explicit legacy lane;
  it cannot act as an alternative canonical writer after conversion. Changed selected source bytes require the
  source-binding revalidation defined in §9, not automatic adoption or a raw-read exception for an agent.
- **Historical files/archives:** retained originals, sealed exports, prior accepted revisions, immutable decisions,
  snapshots and `docs/archive/**` remain consultation/download only, with their actual provenance. An explicit
  import into a new current draft preserves the original and grants no historical/execution authority. Query-only
  restored copies expose no editing, adoption/export or legacy file mutation controls and need no checkout.

This transition retains T012/D293's no-automatic-rebase policy, field/buffer retention, exact-envelope recovery,
independent loading/mutation state, current-generation response checks, revision-bound search/cursors, localized
labels, bounded association notices and sensitive-change comparison. T037 must test these through the real routed
document and knowledge views, not only isolated form components.

### 10.6 Implementation ownership and human-editing acceptance

T030 owns all design in §10.1–§10.5, including authoring recovery guarantees, source classification, interaction
design, execution-impact matrix and a reviewable user-journey/visual acceptance contract. T031 owns persisted
working copies, revision/evidence/impact bindings and historical invariants; T033 owns shared typed working-copy,
staging, validation, comparison/adoption and conflict/recovery queries/commands. T032 owns export state/delivery
and codec/ownership transitions; T034 owns task/plan/READY/autonomy/invocation effect-boundary checks; T036 owns
intake/conversion/source-editor transition. T037 owns all UI implementation and owner visual review, T038 audits
recovery/domain integration and T028 includes final normal/autonomous user journeys. No new task ID is introduced.

| Required acceptance / user journey | Evidence owners |
|---|---|
| Open each of the six document views and canonical instructions; edit permitted narrative/fields in document context, including Markdown/Mermaid, with no JSON/marker/internal-ID authoring | T037 routed interaction tests and owner browser visual review; T033 domain parity |
| Create/edit/reorder/reparent subtasks and add/remove valid dependencies/decision/architecture/gate links; invalid cycles, ownership or unresolved targets preserve input and prevent acceptance | T031/T033 structural tests; T037 keyboard/pointer and exact comparison journey |
| Save an incomplete working copy, trigger validation/read/save failure, navigate/reload, then recover inputs/order/relations and the exact pending request; delayed responses do not replace newer work | T031/T033 durability/idempotency/error cases; T037 routed recovery journey; T038 integration |
| Two editors advance the head or change a draft after preview; stale confirmation refuses without discarding work, auto-rebase or a second uncertain adoption | T033 CAS/conflict cases; T037 explicit conflict/recovery journey |
| Inspect an immutable decision; attempt protected edits; create and confirm a separate full/partial superseder with visible consequences and preserved historical content | T031/T033 immutability tests; T037 decision/sensitive-instruction comparison journey |
| Read STATE/task/phase/gate projections and old READY/evidence; verify there is no status-edit route or false current satisfaction, including unknown/stale/missing associations | T033/T034 evidence/read contracts; T037 read-only/unknown UI assertions |
| Edit knowledge while a task, invocation, plan/READY, autonomous child or closure/export intent exists; preserve frozen bytes and apply the T030-defined fresh-boundary guards and separate D298 confirmations without automatic cancellation/replanning | T034/T036 integrated fixtures; T037 impact/conflict presentation; T038 frozen-history regression |
| Accept a valid revision, then fail/refuse/partially complete export; show accepted revision and pending delivery separately, recover the same export intent without repeating adoption or losing work | T032 export/recovery cases; T037 end-to-end editing/export journey; T038 ledger/receipt parity |
| Move from a legacy file editor to canonical editing; preserve unsaved/pending work, block a stale file write, retain permitted noncanonical editing and checkout-free historical/read-only consultation | T032/T033/T036 authority-transition cases; T037 routed legacy/canonical/archive journeys |

T037's owner visual review uses synthetic projects in a real browser at desktop and narrow widths, in en/es, with
document readability, field/relationship controls, exact comparison, focus/keyboard paths, protected history,
conflict/recovery and export-pending states. Record screenshots/measurements and observed user-journey outcomes;
component tests alone are not visual acceptance. Current source inspection or this documentation change supplies
none of that future product evidence. T038/T028 preserve scope labels for synthetic versus authorized native runs.

## 11. Proposed graph responsibilities

Replace the task/phase single-node wrappers with versioned explicit stages such as resolve → assemble → plan →
execute → validate → review → route/hold → guarded acceptance/export. The exact node map and stage dependencies
must be adopted in T030; context assembly is repeated before each model invocation with that stage's policy.
All I01–I17 entry points in §7.1, including ordinary planning/chat, preparation, ASSIST and judge admission, receive
an explicit policy/stage binding. They use the shared resolver where knowledge is applicable and the declared
Bootstrap or Other source mode where it is not. T034 owns graph/stage integration without replacing preparation,
ASSIST or judge's existing journal/ledger owners; T036 completes the intake and pre-adoption consumers.

The new task path admits a strongly typed execution contract bound to its accepted task version and independent
authority checks. It must not depend on rendering task Markdown and parsing it again, as the current D301 adapter
does. Keep that historical adapter for its explicit legacy format; document rendering moves to the export edge.
Execution-contract changes still require validation of paths, commands, criteria, profile, permissions and budgets.

Graph state holds references and routing progress. Existing supervisor scheduling, invocation ledger, journal,
permission checks, correction budgets, READY and export/Git effect owners remain authoritative. A node replay
reconciles its existing deterministic operation key; it cannot rerun an uncertain model call. Versions/stamps
change for new graph definitions; old continuations remain readable and incompatible continuation is quarantined.
Moving logic into graph nodes must not introduce two nested owners of retries or a second process launcher.

## 12. Adopted work before T028 and T029

Plan v0.5 preserves every existing ID and adds T030–T038 as prerequisites **before** T028 without renumbering
T028/T029. These tasks are adopted as planning under D323 and expanded in NEXT_STEPS; none is complete here.
The matrices remain detailed coverage obligations, while T030 resolves the pending designs. Each implementation task needs
its own topic branch, focused synthetic evidence, current parity, diff review and independent technical review;
frontend changes also need owner visual review. Dependencies determine order, not concurrent authorization.

| Adopted task ID | Bounded outcome | Dependencies | Required evidence |
|---|---|---|---|
| T030 | Adopt semantic/document contracts, §10 human-editing/recovery/transition and execution-impact design; define §4.1 evaluators, I01–I17 policies, protected selection and D322 transition | D323 adoption (given); D321/D322; T027 integrated baseline | D321 feasibility before T031, complete launch crosswalk/reviewed exceptions, gate/schema fixtures and §10 matrix/user-journey/visual acceptance contract; preserve D293/D298; design only |
| T031 | Extend knowledge/revisions, recoverable authoring working copies, gate/evidence/impact bindings and history; explicit v1 conversion | T030, including accepted D321 feasibility | Incomplete-work persistence separate from valid revisions; cardinality/cycle/decision/evaluation immutability, conversion/backup/query-only parity and DDBB update |
| T032 | Implement codec, ownership and legacy-editor transitions, six views and separate accepted/export delivery state | T031 | Round trips/partial imports, no imported operational satisfaction, old renderers preserved; §10 pending/failed/partial export recovery without repeating adoption; stale file-writer refusal |
| T033 | Implement shared typed working-copy/draft/validation/comparison/adoption and recovery commands, context/relation tools and gate/coverage services | T031 | §10 incomplete input, exact field/link/order/sensitive comparison, CAS/conflict/pending-envelope and read-generation cases; §4.1 negatives/positives and context/receipt/capability tests |
| T034 | Bind I01–I17 stages and typed contracts; implement gate guards and T030's editor-impact rules for tasks/plans/READY/autonomy/invocations and sealed effects | T032, T033 | Complete launch coverage and §4.1 race/refusal tests; §10 changes during executions retain frozen contracts/bytes and separate D298 confirmations; no automatic cancellation/replanning; ledger/commit parity |
| T035 | Implement/qualify D321 access boundary for selected originals, copies/history and owned exports, across supported inference profiles | T030, T033, T034 | Unowned/pre-adoption and owned cases; denied file/shell/Git/alias/copy/autoload bypasses plus successful bounded source-tool access; guarantee or profile refusal, no assumed native capability |
| T036 | Bind intake/onboarding/conversion/pre-adoption sources and gates, including §10 legacy-to-canonical editor/source transition | T032, T033, T035 | No head/ownership required; original/copy/history protection and source-tool success; gate refusal and I06–I10/I15–I16 Bootstrap/I09 checks; retain unsaved/pending work and explicit conversion/adoption/plan confirmations |
| T037 | Implement §10 document-oriented entity/block editing, recoverable drafts, exact comparison/adoption and separate export, plus map/drawer integration | T032, T033, T036 | All six documents/instructions, subtasks/relations, immutability/projections, conflict/reload/running-work/export-pending and legacy/archive routed journeys; owner browser visual review desktop/narrow/en/es, keyboard/accessibility; API/client parity |
| T038 | Re-audit inference/source/gate boundaries and human-editing recovery/impact integration; requalify migration/accounting | T031–T037 | I01–I17/source-bypass/§4.1 matrices, §10 conflicts/pending adoption-export/active execution/frozen-history/restore journeys, targeted T025–T027 deltas and efficiency evidence |

T028 then depends on T011–T027 **and T030–T038**, and qualifies complete normal/autonomous journeys on the final
model. T029 retains its delivery responsibilities and also consumes T038's revised supported-scope evidence.
No earlier task is relabelled incomplete; its evidence remains true for its original version and scope.
T028's complete journeys also include §10 human editing, explicit phase-plan confirmation and pending export in
normal/autonomous project flows; T037's visual review and focused routed journeys are prerequisites, not substitutes.

The adopted ordering is T030 → T031 → T032 → T033 → T034 → T035 → T036 → T037 → T038 → T028 → T029.
Physical schema/API/flow changes require the existing parity in their implementing task, not a fabricated migration
or generated API diff in this design proposal.

## 13. Acceptance of the requested outcome

Before T028 can qualify this direction, demonstrate that:

1. One accepted phase/task resolves required decisions, architecture, criteria, gates and evidence without raw
   document reads or reliance on another agent's summary; unused historical records are not injected wholesale.
2. Every reviewer/executor/judge invocation has an explicit purpose policy and frozen provenance; adoption during
   one call cannot change its reads. Applicable mandatory context is complete or invocation is refused.
3. Agents retrieve scoped entities and propose validated changes; invalid fields/relations are rejected, proposals
   cannot self-approve and no imported status becomes verified execution or delivery.
4. All six document formats have deterministic field mappings, loss diagnostics and versioned round trips; v1
   histories and in-flight evidence are preserved through explicit conversion.
5. The adopted read guarantee is demonstrated for the exact supported client/role profiles. A cooperative policy
   is never labelled technical prevention, and technical prevention has no cooperative fallback. T030's D321
   feasibility gate covers selected unowned/pre-adoption documentary/instruction originals and their copies/history
   independently of export ownership before T031 can begin. T035/T036 verify denied direct/alternate-route reads
   and successful bounded source-tool delivery both before and after adoption/conversion/ownership changes.
6. Setup, existing-project onboarding, manual/autonomous runs, UI/map/chat, backup/restore and query-only archives
   use the same model and expose unresolved conversions or unavailable capabilities honestly.
7. Context efficiency measurements compare equivalent mandatory knowledge and task outcomes, include assembly
   costs/tool exchanges and report unknown native usage. Smaller payload alone does not prove equivalent behavior.
8. The T025-to-I01–I17 launch-site crosswalk is complete: every reachable inference entry, including generic
   preparation, both roles/scopes of configuration assistance, ordinary/contextual chat, ordinary/structured
   planning, definition/onboarding/legacy bootstrap, autonomous reviews and all four judge duties has a graph/stage
   owner, versioned context/source policy, responsible task and evidence. Owner-reviewed dispositions are recorded;
   unresolved coverage/exceptions refuse admission rather than bypassing D321 or policy assembly.
9. The shared gate/evidence service and its consumers satisfy §4.1: absent, unknown, failed and stale/expired
   evidence each refuse a mandatory gated transition; agent claims/imports/checkboxes create no satisfaction.
   Positive cases require admissible verified witnesses with complete coverage, current bindings and validity.
   Invalid evaluators, unavailable evidence and change/revocation between preview and effect refuse or invalidate
   the result. Replay, resume, aggregation and restored consultation preserve the distinction and history.
10. T030 records gate states/evaluators/inputs/validity and every affected boundary; T031/T033/T034/T036 implement
    their named storage/evaluation/consumer responsibilities, T032 rejects imported operational satisfaction and
    T037 projects outcomes truthfully. T038 supplies integrated negative cases and positive controls for the
    inference, source-access and gate-coverage matrices before T028's final journeys.
11. Every document/instruction area satisfies §10.1: people edit allowed fields/subtasks/relations in a readable
    document presentation without JSON/markers/internal IDs. Immutable decisions, historical bytes and derived
    states cannot be edited; valid supersession and sensitive instruction changes have exact visible comparisons.
12. Incomplete and valid working inputs survive the §10.3 error/reload/conflict cases within the T030-defined
    recovery contract. Save draft, adoption and export have distinct outcomes; exact pending requests and sealed
    comparisons preserve D293, no automatic rebase occurs, and export pending/failure cannot masquerade as delivery
    or require a second adoption. Legacy/canonical transitions retain work and block competing file writes.
13. T030's §10.4 impact matrix is adopted before implementation. Consumer tests cover edits with adopted plans,
    admitted/queued tasks, READY/evidence, autonomous work, active invocations and pending exports/closure. Frozen
    contracts/context/tool reads remain unchanged; fresh boundaries enforce current bindings and D298's separate
    plan/readiness/effect confirmations without inferred cancellation, retroactive changes or automatic replanning.
14. T037 provides real-browser owner visual review and routed user journeys from §10.6, including en/es,
    desktop/narrow screens, keyboard/focus, subtasks/relations, conflict/recovery and export-pending views. T038
    verifies recovery/impact/domain integration and T028 includes final normal/autonomous editing journeys.

## 14. Choices and accepted decisions that need explicit resolution

Recommended design defaults: persistent identified subtasks within one task execution; typed gates/evidence
requirements separate from verified facts; variable specification narrative within a strict semantic envelope;
same frozen revision for an invocation and its tools; compatibility-only instruction exports optional.

The owner accepted technically enforced raw-source access with profile refusal (D321) and optional external
compatibility instruction exports (D322), then adopted this work/coverage plan as v0.5 (D323). That planning
adoption does not resolve T030's detailed semantic, mechanism, schema, policy or execution-impact choices.
T030 must resolve the following before dependent implementation starts; these remain open design decisions,
not adopted mechanisms or authorization to implement product during this planning adoption:

- D321 mechanism/feasibility, protected-source selection and original/copy/history identity, lifecycle and scope
  transitions independently of export ownership, including unowned/pre-adoption and nested/mixed-source cases.
  The existing feasibility block before T031 remains in force.
- Registered graph/stage and policy contracts for I01–I17, permitted DB/Bootstrap/Other inputs and exact bounds;
  owner review of X1/X2 and I09's legacy disposition, with no implicit inference exclusion.
- Gate/evidence states, versioned evaluator catalogue, trusted inputs/witness kinds, freshness/invalidation,
  applicability and aggregation, error behavior and exact effect-boundary revalidation, with the §4.1 test matrix.
- Human editing (§10): document/entity interaction design, incomplete authoring-work persistence/retention and
  durability, shared typed command/version bindings, legacy/noncanonical authority transition, exact impact on
  adopted plans/tasks/READY/evidence/autonomy/in-flight invocations and sealed effects, with D293/D298 guarantees,
  required impact evidence/unknown handling, separate export state and owner visual/user-journey criteria.
- Remaining semantic/document schemas and fixtures, instruction applicability, mandatory-context overflow and
  D322 ownership/version transition. Complete schemas and a concrete isolation mechanism are not resolved here.

Subsequent T030 design adoption would extend D284/D288 and refine D269/D298/D301 for graph/context consumers and D304/D315 for
semantic consultation. D322 records the accepted target change to D285/D294's instruction export obligation;
D321 records the required refinement of D064's cooperative boundary. Neither asserts an implemented mechanism,
new format or qualified profile. Add further numbered decisions when adopted; do not rewrite the bodies of old
decisions or frozen task records.
AGENTS.md for development of this repository is outside that supersession.

## 15. Verification of this proposal

Documentation planning adoption only: this record, STATE/NEXT_STEPS/ROADMAP and new decision D323. Earlier decision
bodies (including D293/D298/D321/D322), T012/T025 records and frozen snapshots/histories remain unchanged. The
reviewed coverage/human-editing obligations are adopted as planning; T030's design and implementation remain pending.
No product implementation, migration, dependency change or provider/harness execution.
Local verification: `scripts/check-docs` passed (133 Markdown files, 0 errors); `git diff --check` passed, and the
untracked proposal passed the separate `git diff --no-index --check` whitespace check. Byte comparison against the
pre-adoption snapshot confirms existing DECISIONS content is retained before appended D323 and the frozen T012/T025 records are unchanged. The
incremental tracking/proposal diff was reviewed. STATE/NEXT_STEPS/ROADMAP link to this refinement and its accepted
D321/D322 policies and D323 adopted plan while distinguishing pending T030 designs; the
ONE_OFF_TASKS queue remains empty. Product suites and native prevention/efficiency qualification have not been
run here because no product change was made. The owner authorized source commit, develop integration and push;
the source commit and accompanying merge carry this record and their exact identities are in Git history. The
completion report verifies push independently. Release/publication/installation remain pending under T029.
