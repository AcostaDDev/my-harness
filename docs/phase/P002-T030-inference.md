# P002-T030 — Proposed inference and typed execution contracts

Part of the [T030 review record](P002-T030-contracts.md). Crosswalk for the
[eight T025 families](P002-T025-accounting-efficiency.md#inference-entry-points-and-persistence) and
[planning §7.1](P002-knowledge-context-proposal.md#71-complete-inference-entry-coverage-matrix).

## Stages and seals

Register the following graph definitions and invocation stage IDs exactly as below. A stage ID is its I-number
(e.g. `I01`), unique across graph definitions. Each row has a distinct closed `context/Ixx@1` policy with the
listed source-mode union, mandatory inputs and typed output, plus the common envelope below. Roles are
`planner, executor, reviewer, phase, planning, definition, bootstrap, chat, judge, configuration`; client enum is
`codex, claude, gemini` (schema labels are separate from runtime eligibility). A role enum alone does not
identify purpose, and an eligible client label proves no qualified profile.

| Graph/stage registry | Directed stages and transitions (I-number = sole inference in that stage) |
|---|---|
| `managed-task@2` | resolve → I01 proposal or confirmed manual typed proposal → admit typed contract → I02 initial → validate → I03 → route to guarded acceptance/export, hold, or newly authorized I02 correction → validate → I03. A separately admitted retry enters I02; revalidation enters validate and I03 only if the current route requires a new review |
| `managed-phase@2` | resolve → plan via I05 → validate proposal → owner plan hold; or resolve → deterministic checks → I04 if review required → validate coverage → guarded READY/hold. Close consumes exact READY and sealed effects, with no independent call. Any fresh review required for closure re-enters I04 through the check lane |
| `managed-planning@1` | resolve → I06 → validate proposal → wait/settle |
| `managed-intake@1` | capture/resolve → I07 or I08 → validate mapped proposal → owner hold; I09 is reconcile/refuse for legacy, optional fresh owner admission routes to I08 with the I08 policy, not an I09 launch |
| `managed-chat@2` | resolve → I10 or I11 → validate → settle. Deterministic chat command branches directly to existing effects without model context admission |
| `autonomous-roadmap@2` | existing coordinator advances authorized batch → I12 (readiness) or I13 (contract) via managed reviewer job stages → validate → route/hold; a delegated task then enters managed-task@2. Phase completion uses managed-phase@2. Scheduler/continuation/caps stay with existing supervisor |
| `managed-judge@1` | create/resolve → assemble/start → I14 (one declared duty) → result validation/settlement → read ruling or unknown/hold |
| `profile-preparation@1` | confirmed operation → resolve step → I15 for agent steps → validate/settle → next confirmed step or hold; deterministic command steps use existing command journal, not I15 |
| `configuration-assist@1` | confirmed operation → resolve scratch/candidate → I16 or I17 → validate proposal → settle or hold. Applying configuration remains a separate operation |

The last three register explicit stage bindings at their owners. They do not move those owners into a second
scheduler, retry loop or journal. All I-stages expand to resolve → assemble → fenced seal → pre-GO → invoke →
validate/settle. Version changes seal a new graph/policy/catalogue stamp. State stores immutable references,
route and attempt ordinal; effects retain their owner records. The operation key incorporates graph version,
thread, node, stage and stable request/attempt ordinal. Replay uses the original key and reconciles only
verified prior evidence. A pending/uncertain attempt is never replayed as a fresh invocation. A provable
pre-GO refusal records `not_invoked` if an intent exists, uncertain launch keeps `unknown_execution`,
and interrupted partial evidence remains partial. Version-incompatible continuation is quarantined for
consultation/reconciliation; no in-place upgrade. D288 and T025 accounting semantics stay intact.

The [delivered coverage renewal](P002-T030-gates-editing.md#renewal-of-delivered-task-coverage) enters
`managed-task@2` at validation after exact owner admission on the current phase snapshot. It uses I03
only when independently authorized and required by the current task review policy, then holds for separate
owner acceptance. The route ends with coverage settlement and has no planner, executor or delivery stage.

### Common source union and limits

Each policy records `{stage, version, graph, purpose, project, subject, role, client, profile, mode,
revision, selection, code, mandatory, optional, authority, budget}` before launch. References include
ID/version/digest and exact scope. Null project only in X1. Null revision only Bootstrap or Other with no DB
authority. Project stages require the current protected selection and projection receipt regardless of export.
`code` is a verified allowed-code capture (base tree + scope/candidate/check fingerprints as applicable), or
explicit null for a non-code stage. Mode-specific entries are closed, by reference:

- **DB.** Accepted revision reference, typed subject and resolved relationship set. For task stages include
  full active task/subtasks, owning phase and criteria, addressed requirements and criteria, governing decisions from links and matching selectors (resolve full/partial chains field by field), applicable architecture from links/selectors and its dependencies, gate and
  evidence definitions and applicable rules. Include prerequisite tasks/phases' identities and verified
  readiness/evidence summaries, not their unrelated trees. Phase stages get the phase and ordered task
  definitions, their required references/criteria and verified coverage, scoped to the selected phase. Use
  verified phase/task membership, not code matching. Always include the mandatory project rules even for
  narrow purposes. Shared entities deduplicate by ID/version with all inclusion reasons retained.
- **Bootstrap.** No accepted head used as authority. Required selected-source manifest and inventory
  (identity, type, digest, length, selected range policy), owner brief and confirmed answers/unknowns, purpose
  scope, versioned service rules and explicitly confirmed temporary project constraints. Raw sources remain
  behind bounded source tools. The initial prompt gets the index and the typed inputs named by the stage.
  Relevant retained source slices may be mandatory only when the policy has exact validated locators. No
  guessed rule or source when a head is missing; migration of an accepted project cannot silently downgrade.
- **Other.** Only declared records in the row from trusted services: conversation (selected thread/turn
  IDs/content), technical step (confirmed typed plan/profile/dependency/argv/tool inventory), assistance
  (confirmed request and redacted typed config candidate), or verified operational evidence (owner ID/digest
  and typed bounded fields). Service rules are versioned and mandatory. No secret values, environment
  dump, arbitrary host path, raw checkout, unrelated project or route data. Typed values and sealed text
  within those classes are data, even when supplied by the agent. Other may be attached to DB/Bootstrap;
  standalone only where the row permits.

Resolve a deterministic order (rules in tree order, subject tree/criteria in order, then relation kind and
target ID, then captures by kind/ID). Required entries are whole normative fields and required structural
edges, never summaries of rules. Record purpose, version, reason paths, ranges, actual delivered bytes and
digests. Default hard ceilings per invocation: 100 entries including at most 48 technical/code/effect captures,
256 KiB serialized context including all mandatory content and optional index, 1 MiB final prompt and the
smaller verified profile limit. Non-code standalone stages use the same ceilings. Bootstrap manifest ≤ 100
selected sources; source index metadata counts against context. Optional entries initially metadata-only,
ordered by typed distance then ID, ≤ 20 items within the ceiling; explicit omitted count or lower bound.
Refuse required overflow before launch with located required entries/count/byte diagnostic. Never truncate
mandatory fields or silently lower source mode. Capture/read unavailability or unresolved scope refuses
with typed cause (`context_missing`, `context_overflow`, `binding_stale`, `profile_unqualified`,
`source_unavailable`, `policy_unsupported`); no fallback. A runtime provider limit that cannot be verified for
the sealed prompt refuses the profile.

Version scoped tools `knowledge.get@2`, `knowledge.tree@1`, `knowledge.related@2`,
`knowledge.search@2`, `knowledge.coverage@1`, `knowledge.propose@2` and `sources.read@1` through the existing
catalogue and broker. Reads take scoped identity/filter, not file path or SQL. Tree/related use direction,
closed relation kind and depth ≤ 4, ≤ 20 entries/page; query ≤ 256 UTF-8 bytes and cursor binds caller,
query, epoch, revision and versions. Lookup and source reads allow exact UTF-8 ranges up to 8 KiB; metadata,
full/slice level and data digests are explicit, no split code point. Every result ≤ 64 KiB serialized, across
all calls ≤ 32 requests and ≤ 256 KiB delivered cumulative including at most 64 KiB raw Bootstrap slices
and ≤ 16 KiB per source; sources up to 512 KiB each, 4 MiB selected total. Source access is purpose/range
limited by the selection manifest, with no alias or arbitrary locator. A small selected record may fit wholly
in an authorized range. Budget atomic per attempt; identical replay returns existing receipt without
recharging or extending the authorized ranges. Results log scope, reason, revision/selection, source and
range, exact delivered bytes/hash, cursor and errors. Tool reads and proposals preserve D288 revocation,
D286 capability and query-only checks. They never introduce new inference. No tool obtains a new head for
an old invocation. Security revocation may refuse a subsequent tool call under its existing owner.

## Launch-site crosswalk

Paths below are relative to `src/my_harness`. **Families** in order are T025's task, phase, intake, chat,
autonomous, judge, preparation, ASSIST. Unless stated otherwise, project calls use the managed journal
(`core/engine/contracts.py:invoke_agent` → `services/managed.py:_Journal.agent_started` →
`storage/managed.py:agent_started` → adapter), with its ledger and fenced checkpoint. T034 owns all bindings,
T036 the Bootstrap consumers, T035 every qualified launch, T038 the full reachable-route audit.

| Route / family | Current admission or launch call site, including variants | Proposed policy additions (beyond common envelope) and result | Future positive/refusal evidence |
|---|---|---|---|
| I01 task | `core/engine/workflow.py:OfflineEngine.start` → `_invoke` with planner / plan-task; deterministic parser branch has no inference | DB task bundle + approved planning objective/delivery and optional sealed owner notes, code scope/inventory and prerequisite readiness. Typed execution proposal | Normal and delegated routes; required bundle and stale scope refusal; confirmed typed manual branch with zero I01/I13 invocations |
| I02 task | `workflow.py:_execute` initial and `resume(retry_executor=True)`; `_review_loop` revise-task | DB + admitted typed contract, exact work baseline, full verified correction findings where applicable and owner gap resolution; candidate/code delta receipt | Initial/revise/retry counts, D296 cap, changed evidence stop, operation replay and frozen rule parity |
| I03 task | `workflow.py:_review_loop` review-task, including correction rounds and `resume` revalidation when review is required | DB + exact candidate fingerprint/diff, check results, criteria and labelled executor claims; diagnostic review may use authentic terminal failures under the review-entry guards; review recommendation | Failed/stale/unknown review evidence, independent acceptance, no inference for pure validation |
| I04 phase | `core/engine/phases.py:check_phase` phase role; structured path `services/phase_lifecycle.py:execute` and legacy branch in `services/managed.py:LocalSupervisor._run_claimed`; `close_phase` consumes guarded READY with no launch | DB phase bundle + verified checks, task evidence, delivery and unresolved gates; typed check result | Normal/autonomous check, READY vs closure race, no invented closure call or accepted evidence |
| I05 phase | `services/phase_lifecycle.py:execute` plan / structured-phase-plan, planning role with reviewer policy | DB phase objective/criteria + previous plan, task evidence, open/answered questions, exact base. Typed scoped plan proposal | Proposal vs separate D298 owner adoption, changed code refusal |
| I06 phase | `services/managed.py:_run_claimed` planning_turn → `core/engine/definition.py:planning_turn` kind phase_planning / plan-phase, planning role | DB phase bundle or Bootstrap manifest + explicitly selected phase intent, conversation and known/unknown facts. Typed response/proposed plan | Both modes; converted-project fallback refusal; stale queued observation |
| I07 intake | Same `planning_turn`, definition / define-project[-profile], definition role and verified observations | Bootstrap owner specification, selected originals, answers, missing facts and current draft refs. Typed definition/profile proposal | Unowned/no-head source, read receipt, independent profile/adoption/export consent |
| I08 intake | Same `planning_turn`, onboarding / onboard-project[-profile], definition role; supervisor currently exports HEAD | Bootstrap trusted captured code inventory + selected originals, owner answers/unknowns and draft refs. Typed attributed mapping/profile proposal | Curated projection before and after transition, no raw copied-HEAD access, preserve provenance |
| I09 intake | `services/managed.py:_run_claimed` bootstrap_discovery → `core/engine/bootstrap_discovery.py:execute` → bootstrap role with saved prompt | No fresh policy for raw saved requests. Read/reconcile original recorded work only. Fresh discovery explicitly admitted as new I08 request | Pre-GO no-call refusal for queued legacy request; stop/reconcile interrupted recorded outcomes without rerunning |
| I10 chat | `core/engine/chat.py:chat_turn` → chat role. `services/managed.py:_run_claimed` chat_turn/chat_snapshot (legacy live/copy variants); deterministic command separate | Project DB + selected bounded conversation; pre-adoption Bootstrap only with confirmed selection. Global Other only, service policy and selected conversation, empty project/host workspace (X1) | Both project modes and global isolation, refusal of old unbound raw-reading requests, command no-call |
| I11 chat | Same chat_turn with canonical frozen element, `services/managed_runtime.py:run_chat_graph` from supervisor | DB selected phase/task and verified run/step refs, exposure level/data digest and mandatory rules. Other exact retained element/conversation. Unavailable selected evidence refuses rather than substituting checkout | Revision/element receipts and mismatched/unavailable selection, T024 parity |
| I12 autonomous | `services/autonomous_review.py:execute` kind readiness, `roadmap_review` managed phase graph, planning role with reviewer selection | DB roadmap/phase criteria and task/gate coverage + parent delegation, admitted batch/budget and code binding; typed gap report | Stale head/criteria, unknown coverage and caps refuse advance; one ledger row |
| I13 autonomous | Same execute task-contract branch → `task_contract` currently renders Markdown then `deterministic_task` parses | DB full task scope + delegation/caps, exact profile/code/criteria; typed contract directly through validator below | Direct typed validation, no Markdown authority, authority/budget and purpose checks |
| I14 judge | `services/judge.py:JudgeService.assemble/start/seal/record_result/settle/reconcile` and scoped `submit` candidate. No productive caller of start/result was found in this baseline; T027 scripted boundary is evidence only | DB scoped subject + immutable request and verified choice/evidence; duties below; typed candidate ruling only | Four independent duty launches/refusals, no start without exact native cell, recover original request and ruling/unknown without retry |
| I15 preparation | `services/profile_preparation.py:_execute_step` → adapter.invoke, its `process_intent`/finished/closing/stopped-writer ledger owner | Other confirmed technical plan/step/profile/dependencies/allowed tools + code capture and applicable DB rules/project constraints or explicit Bootstrap equivalents (X2); step result/observations | Agent step and deterministic command distinction, project source isolation, fault after intent and ledger parity |
| I16 ASSIST | `services/configuration_assistance.py:confirm` → adapter.invoke (project reviewer/executor, native roles configuration/executor) with ASSIST intent; `recover` reconciles stopped writers | Other redacted candidate, exact request and private scratch, applicable DB constraints or explicit Bootstrap. Reviewer scratch read-only, executor confined writer. Typed config proposal | Both roles, denied project-source bypass and no configuration apply from the reply |
| I17 ASSIST | Same confirm/recover, global reviewer/executor variants (native configuration/executor) | Other candidate/request/service rules, isolated scratch, no project DB/mounts/source tool (X1). Typed config proposal | Both roles, no project inference, exact intent/ledger, recovery without relaunch |

I14 duty inputs are disjoint schemas selected by the registered duty, each restricted to its existing
`core/engine/judge.py` duty input contract and independent verification. `permission` receives exact request,
target and policy choice; `planning_choice` sealed admissible plan alternatives and decision context;
`spec_gap` the scoped gap, accepted constraint and permitted clarification/disposition; `blocked_check`
the verified blocked intent/check evidence and permitted classification. No other project tree is needed
beyond mandatory matching rules and referenced normative facts. A ruling is not authority to expand scope
or bypass existing owner-only approval. No duty uses Bootstrap or a substitute profile.

**Proposed dispositions for owner review.** X1 seals global chat and global ASSIST as Other-only, with
isolated no-project access and separate accounting. X2 seals generic preparation to confirmed technical scope
plus applicable project constraints and instructions (DB or explicit Bootstrap), never the full unrelated
task/roadmap bundle. I09 retires fresh legacy invocation and retains deterministic reconciliation; any new
discovery is an independently confirmed I08. No route is exempt from D321, stage admission or accounting.
Unresolved dispositions block the corresponding new path. Deterministic reads, tool actions, validation,
Git and configuration apply keep existing effects, not synthetic inference entries.

## Typed execution admission

T034 registers `execution-contract-2`, a closed immutable record with required keys
`{format, project, revision, phase, task, plan, criteria, objective, allowed_paths, denied_paths,
checks, executor_profile, authority, budget, code, selection}`. References are exact ID/version/digest;
revision/plan/task/phase must be mutually bound. `objective` is the accepted exact text. `criteria` contains
ordered exact criterion refs (≤ 64). Paths are validated relative file paths or tagged directory prefixes
(≤ 64 of each), confined to the code projection, intersected with current protection and permission rules.
No overlap that weakens denied, owned or protected paths. `checks` (≤ 32) are ordered
`{id, argv, timeout_seconds}` with nonempty argv ≤ 64 strings of ≤ 512 UTF-8 bytes and timeout 1–3600,
further limited by profile/approved command policy. No shell coercion. Profile includes exact configured
client/model/effort/runtime identity. Authority includes owner/optional delegation, grant IDs and epochs.
Budget carries integer correction ceiling/current ledger binding (D296 family) and authority caps. Code
binds base tree/fingerprint; selection binds projection/source epoch. Limits are upper ceilings, not new grants.

I01 and I13 return `execution-proposal-2` with exactly `{format, allowed_paths, denied_paths, checks,
rationale}`. The first three editable fields use the typed bounds above; rationale is nonblank text ≤ 8 KiB,
with no effect authority. The trusted admission writer resolves accepted subject/version/criteria, execution scope,
profile and authority and validates directly as specified below. Review and correction prompts label rationale and prior
review instructions as claims; neither adds scope, commands or authority. Preserve the existing per-role
result validators and snapshot their output schema version (including `review_contract`,
`validate_phase_result`, `validate_phase_plan`, `validate_planning_result`, `validate_chat_result` and the
duty-specific judge schemas). A typed result never bypasses independent evidence/acceptance. No Markdown generation/parsing inside this path. I02/I03 use the admitted typed
record plus fresh stage observations and do not rewrite it. The historical D301 adapter stays reachable
for explicit historical-format interpretation/reconciliation; a fresh new-path launch always needs this
typed contract and a qualified boundary. T034 verifies direct construction, independent authorization,
path/argv checks, profile/correction binding and format-version quarantine. T038 compares old records
and new receipt/ledger/effect counts under retries, corrections, recovery and both supervisor modes.

### Manual deterministic entry and authority

A manual execution request uses the currently confirmed D298 phase plan for the exact accepted task,
and two distinct persisted typed inputs owned by the managed task admission service:

| Record | Contents and authority |
|---|---|
| `execution-limits-2` | Closed immutable reference record with `{format, project, revision, phase, plan, task, owner, allowed_paths, denied_paths, check_definitions, required_checks, executor_profile, authority, budget, code, selection}`. Exact bindings and limits use the contract grammar above. Check definitions carry the exact registered ID, argv and timeout in a trusted validation catalogue version. Required check IDs are a subset of those definitions. The writer derives the maximum admissible scope from current permission, ownership/protection, projection and qualification records. An authenticated owner independently confirms the exact bounded envelope of paths/denies, permitted check definitions, profile, code baseline and budget. Store the confirmation and version/digest under the existing writer and CAS. A plan or proposal alone cannot grant any of these limits |
| `manual-execution-2` | Closed `{format, limits, proposal}`, where `limits` is the exact confirmed record ref and `proposal` is an `execution-proposal-2` assembled from typed path selectors and named checks in that record. The owner confirms this exact requested selection and its comparison with the limits. No I01/I13 invocation is needed. Rationale and accepted narrative remain data |

For planner/reviewer entry I01 and I13 propose within independently established limits for their respective
routes. Autonomous limits also bind the exact existing delegation and caps. Proposing scope neither
creates nor enlarges those limits. For every origin, the writer verifies the expected head/plan/task,
limits and proposal refs, exact code/selection and current authority/profile epochs. It resolves checks
by registered ID and exact argv/timeout, proves each requested file/prefix is inside a permitted limit
against the verified projection, and retains all mandatory denies. A narrower requested deny can only
restrict scope further. Every required validation check for the route must be present. An out-of-scope
request, mismatched command, unknown binding or missing typed record refuses admission with located
diagnostics, before I02. Do not trim an excess request and silently execute the remainder. Derive the
objective and ordered task coverage criteria from accepted typed definitions and memberships. Seal the
validated contract with immutable limits/proposal/confirmation references in its admission receipt.
Bind the admitted contract and receipt at stage seal and pre-GO. No phase/task Markdown, template,
legacy notes or historical contract may provide paths, argv, limits or authority. No fallback to I01
for a refused manual request.

### Legacy documentary reconciliation

The existing `storage/phases.py:submit_reconcile_task` constructs a deterministic document-scoped
contract from the legacy phase definition, layout and template, then follows the task lane that can
launch executor and reviewer. Treat it as a historical-format route. Under the proposed v2 boundary,
queued legacy reconciliation without an invocation refuses fresh launch. A previously started or
uncertain job may settle or reconcile its original recorded outcomes, with stopped-writer and exact
receipt guards. It gains no new executor, reviewer, correction attempt, consent or authority to write
canonical documents. Retain its inputs and results for consultation. This applies even where the legacy
contract is deterministic.

Fresh reconciliation of canonical material uses explicit owner mapping/typed knowledge changes,
independent adoption, and separately confirmed deterministic export or phase delivery through the
existing writers. A required unresolved reconciliation holds the phase. If noncanonical work independently
qualifies as a new typed task, it requires fresh scope, contract and qualified I02/I03 admission on
permitted projected paths. No automatic conversion, replay or resume of a legacy task through that lane.
The legacy route disposition is part of owner acceptance of T030.
