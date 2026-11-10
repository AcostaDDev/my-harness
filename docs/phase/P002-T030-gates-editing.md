# P002-T030 — Proposed gates, authoring and execution impact

Part of the [T030 review record](P002-T030-contracts.md). Normative requirements live in the
[semantic revision](P002-T030-model-codec.md), evaluations and authoring work have separate owners.

## Evaluation contract

`Boundary` is closed: `intake_promote, conversion_promote, profile_confirm, preparation_start,
preparation_finish, activate, plan_confirm, task_admit, inference, task_validate, task_review, task_accept,
task_export_commit, phase_validate, phase_ready, phase_close, autonomy_advance`. Bootstrap has no DB gates before a head
exists. Its promotion checks use the sealed prospective semantic draft and selected sources, never imported
assertions. Owner/project policy, version/identity, isolation, approval, checkout fencing, ledger limits and
READY remain built-in guards regardless of project definitions. In particular a satisfied gate is no permission.

A `WitnessRule` is one of the following closed records. All keys are required, with no nulls. The
registry seals each rule's source owner, binding dimensions and producer transition with the evaluator
version and implementation digest. Definitions select registered IDs only.

| WitnessRule discriminator and fields | Source owner and first availability |
|---|---|
| `{kind:"check@1", check:ID}` | Trusted validation owner after settlement of the named check in the confirmed task or phase validation plan. Retain terminal status, output digest, exact definition and environment. Bind to the task candidate or phase check snapshot respectively. A check command or an executor claim is insufficient |
| `{kind:"authority@1", capability:ID}` | Trusted permission or qualification owner after resolving the exact scope, profile and live epoch before the guarded transition. Registry declares code-bound or non-code. A judge ruling cannot grant owner authority |
| `{kind:"owner-attestation@1", topic:ID}` | Independently authenticated owner after explicit attestation of the exact subject, topic, bindings and reason. `scope-reviewed` is non-code and available after scope confirmation. `delivery-observed` is code-bound, supplemental and available only after the named delivery settled. Attestation cannot replace objective validation, delivery receipts or independent acceptance |

`coverage@1` evaluates every applicable owned evidence requirement of each criterion or gate consumed
at that boundary. A requirement is OR over its fully verified alternatives. Retain alternate failures.
A failed mandatory check cannot be made optional through OR. Zero applicable slots for a required
criterion or gate means incomplete coverage. Scope uses exact lineage, component closure and the frozen
path scope. A gate enters through an explicit link from the subject, its owning task or phase, or by scope
match, and is consumed only at declared boundaries. An out-of-scope or wrong-boundary link is reported
as inapplicable with proof. Unknown applicability blocks a boundary that could consume it. There is no
manual N/A override.

### Criterion ownership and coverage composition

- At task acceptance evaluate active task criteria, criteria of its active subtasks and criteria of requirements
  explicitly addressed by the task or those subtasks. The task validation owner produces the check record.
  Evaluate a separate slot for each exact criterion and requirement version in that task execution context,
  including its owning subtask or addressed requirement and the verified relation. Sharing a source across
  these slots requires the same full task/candidate binding and a matching rule in each slot.
- At phase readiness evaluate active phase criteria and criteria of requirements explicitly addressed by the
  phase on the current phase check snapshot. The phase validation owner produces these check records.
  Additionally, verify the exact phase plan's task membership and criterion-to-task coverage mappings from
  D298. For each required task, join its verified delivery and original acceptance to the currently eligible
  task coverage, including subtask and task-addressed requirement slots. Persist references to the task
  subject, versions, evaluation IDs/digests, candidate and receipts, plus the exact membership and mapping.
  A mapped contribution supports that phase criterion alongside its own required slots. It does not
  satisfy a phase check slot or relabel a task witness.
- The phase writer verifies each referenced source, expiry, authority and version against the required plan
  and scope. Verify that the committed task result is included at the phase snapshot using trusted delivery
  receipts and Git ancestry, applying the [task result and shared generation rules](#task-result-and-shared-generation-proofs),
  with no changed check inputs since validation. The validator must prove equality
  of the sealed complete check input set against the phase snapshot, including relevant dependencies and
  environment. If the validator cannot prove a smaller complete set, compare the entire bound tree.
  Changed or unavailable inputs hold the contribution until a verified renewal or a new required delivery
  supplies current coverage. Record the composition against the phase snapshot, with distinct task and phase
  witnesses. A missing mapping, unresolved task, or failed required contribution holds READY. A withdrawn
  historical task contributes only where the currently confirmed plan explicitly requires its receipt and
  the current eligibility rules allow it.
- At task export/commit reverify the accepted task coverage and exact candidate. At phase close reverify
  READY's referenced phase and task coverage and delivery bindings before sealing or mutating. At admission,
  inference, validation start and diagnostic review, criterion definitions may be inputs for context and
  planning, with no requirement for their eventual passing evaluations.

Store append-only `evaluation-1` facts with evaluator and registry digest, project, boundary, subject ID/version
and scope digest, gate/criterion and requirement versions, accepted revision ID/hash (or prospective draft
ID/version/hash for promotion), contract/profile/check definitions and digests, code fingerprint plus base tree
for code-bound slots, explicit `non_code` marker otherwise, source record ID/digest and availability,
authority/selection epoch, outcomes, observed/evaluated time and valid-until. Missing irrelevant dimensions
must be declared by the registry as non-applicable. Missing required dimensions yield unknown. Bind
evaluation to the full subject even if the same evaluator is reused elsewhere. Persist source verification
and exact rule/alternative selection, including failed checks; never reduce to a percentage or latest text.

| Current state | Derivation and guarded behavior |
|---|---|
| `pending` | No evaluation for this binding yet; work may be queued, effect refuses |
| `incomplete` | Evaluated, one or more mandatory slots absent; refuses |
| `satisfied` | All mandatory slots verified current, with applicable built-ins separately passing |
| `failed` | Verified applicable witness failure with no passing alternative; refuses when consumed as a passing slot. A diagnostic input may retain the failure |
| `unknown` | Integrity/outcome/source unavailable, unsupported registry, evaluator error, or insufficient facts to determine applicability; refuses |
| `stale` | Previously evaluated slot with changed subject/revision/code/contract/check/profile/registry/source selection/authority, or expired evidence; refuses |
| `inapplicable` | Applicability demonstrably false; excluded with proof. The report shows zero applicable gates explicitly when applicable |

Evaluation operates against a verified source index. For each alternative choose the newest authoritative
matching source by persisted owner sequence, tie-break by ID, checking terminal integrity and completeness
rather than falling back past a relevant later failure or uncertain attempt. An unrelated witness is refused
as a candidate, not treated as a failure of the current subject. For unsatisfied combined rows use
unknown > failed > stale > incomplete > pending for the summary and display each slot's cause. Preserve
underlying source facts even when the current view becomes stale or unavailable. Every reevaluation appends
or reconciles the same operation. Expiry is inclusive at earliest non-null gate/requirement/registry TTL
from the verified source observation time (range 1–2,592,000 seconds). Use trusted harness UTC and persisted
monotone last-observed time per store; regressing/unverified time yields unknown for time-dependent checks.
No cache may certify a new binding, revoked authority, missing evidence, or changed clock. On restore,
reverify availability and binding before showing current applicability. Historical results display as recorded.

### Renewal of delivered task coverage

The proposed task lane admits a separate coverage renewal for a delivered task that the current confirmed
phase plan still requires under the exact same task, contract and coverage definitions. A stale contribution
holds READY. The authenticated owner explicitly confirms an exact renewal preview under the task writer.
Admission verifies current task, checkout and check authority, including any separately required authority
for I03. Phase evaluation or a prior acceptance, delivery or batch grant cannot queue or approve renewal.
The original run remains terminal. The renewal job moves through validation, I03 if required, and an
independent exact owner acceptance, or settles with a hold or refusal. Use the existing task validation,
review and acceptance guards on this route. The route has no planner, executor, formatter or export/commit
stage and does not reset the task's correction budget.

The preview and admission seal project, phase plan and membership/mapping, task lineage and exact versions
of the task, scope, contract, criteria and gates, accepted revision and ownership, original acceptance and
delivery IDs/digests, current phase snapshot (ref, HEAD, tree and candidate fingerprint), and the registry,
check plan, environment, profile, selection and authority bindings. Verify Git inclusion of the original
delivery and verify its result and required generation proofs at that snapshot using the rules below.
Capture the exact snapshot and complete check inputs for the new validation, then seal its terminal
check and coverage records and any required independent review (IDs/digests) into the acceptance preview.
Recheck bindings under the task writer at admission, before validation/review effects and at acceptance,
with exact replay of the same request. Changed bindings require fresh confirmation. Failed, stale or
uncertain required evidence cannot produce renewed acceptance.

Append a coverage-only acceptance bound to that snapshot, referencing both the original acceptance and
the unchanged delivery receipts. The phase writer joins the original delivery proof to the renewed task
evaluation and acceptance for that exact snapshot, including the sealed membership and mapping. Renewal
supplies the current witness set as a whole. A later failed or unresolved renewal for that binding holds
the contribution without falling back to an earlier pass. The phase readiness route recomposes coverage
and reuses a phase check or I04 result only if all of its own sealed inputs still match. READY and closure
reverify the joined references, inclusion, authority and freshness. The original acceptance, delivery,
candidate and history retain their original meanings and bytes. A coverage-only acceptance is ineligible
as authorization for `task_export_commit`.

#### Task result and shared generation proofs

The sealed delivery receipt records two disjoint footprints fixed by the authorized task contract and
document ownership manifest at delivery. It binds the task result entries (paths, byte digests, modes and
required absences, including generated artifacts required as the task's own output) and other required
task effects. It separately binds each required shared export destination to its harness generation
intent and settled per-target receipt, including the ownership and renderer versions, sealed render inputs,
expected path, bytes and mode or absence, and observed commit. Verify the classification from those
authorities. Neither file type nor the fact that a path changed in the task commit determines its class.
An ambiguous classification or incomplete footprint holds the contribution.

Verify the original result and each original generation against the receipt's delivery commit and prove
its ancestry to the evaluated snapshot. Compare the complete task result to that snapshot, including
required absences, and verify its other required effects. For a shared destination such as v2
[STATE.md](P002-T030-model-codec.md#operational-projection), verify the current path against the settled
generation applicable to that snapshot under its own harness export authority. Use its sealed inputs,
ownership and renderer, per-target outcome and Git observation to verify the bytes, mode or required
absence. A later valid generation can differ from the one sealed by the original delivery. Bind the
current generation proof into the renewal preview and phase composition and reverify it at their effect
fences. Missing, unresolved or mismatched proof for either generation holds the contribution.

Shared destinations remain subject to the complete check input comparison. If a check reads a shared
view, directly or through a dependency, changed view bytes make that coverage stale. A check that cannot
prove a smaller complete input set still compares the entire bound tree.

An input-only change can use renewal when the task result and required delivery obligations still match.
A changed task result, a missing required task effect, or a new task or delivery obligation requires the
normal authorized task and delivery lane with its own exact acceptance and receipt. A changed plan or
contract must first be resolved through the existing plan and task admission guards.

### Fences and test matrix

Preview is diagnostic. Confirmation seals the relevant binding and exact evaluation set (IDs/digest and
snapshot versions). At each effect the current authoritative writer checks the same set, current bindings,
registry, verified source availability, epoch and freshness in its existing fenced transaction. An external
effect uses a durable intent under the writer, rechecks immediately before first external mutation, and checks
the expected before/after observation at settlement (including ref CAS where relevant). Drift leaves a durable
stop/refusal. Once an effect may have happened, reconcile only that intent from verified observations and keep
its original authority/evidence; never authorize a fresh effect under the name of recovery.

| Boundary | What must be available before the effect | What the effect can produce |
|---|---|---|
| `intake_promote`, `conversion_promote` | Gates at that boundary on the sealed prospective draft. The intake/conversion owner has already verified source, mapping, parse and missing data, and the owner has confirmed the exact comparison. Check current draft/head/selection/HEAD | Adopted head and promotion receipt |
| `profile_confirm` | Gates on the exact profile proposal. Permission/qualification owner supplies verified scope and any qualification required for this effect | Confirmed technical plan/scope |
| `preparation_start` | Confirmed plan, qualified launch boundary and start gates based on already available scope and prerequisite step receipts | Step intent and subsequent step output |
| `preparation_finish`, `activate` | Finish gates use already settled step results; activation gates use confirmed prepared outcome and documentary checks. Both use the current profile/selection and exact authority | Finish and activation receipts respectively |
| `plan_confirm` | Gates on the prospective phase plan; complete task tree and coverage mappings, plan definition checks, exact independent owner preview and CAS | Confirmed plan, with D298 READY/batch invalidation |
| `task_admit` | Confirmed plan, typed contract, current scope/profile/code, prerequisite task/phase receipts, and admission gates with available sources. No candidate validation of this attempt | Admitted contract |
| `inference` | Gates on the actual stage subject and verified inputs already produced on that route. I01 uses confirmed planning scope; I02 uses admitted contract and prior correction evidence when applicable; I03 uses terminal candidate validation; I04 uses current deterministic phase check results. Apply at seal and pre-GO, including corrections/retries | Invocation and result/settlement records |
| `task_validate` | Validation-start gates, exact candidate capture and authorized check plan. This attempt's check result is still pending | Terminal trusted check records bound to the candidate |
| `task_review` | Review-entry gates, exact candidate and authentic terminal validation results. A verified failed check can be presented to an independently authorized diagnostic I03. Missing, uncertain or stale required results hold review. Diagnostic output can explain failure or inform a separately authorized correction | Bound recommendation, including diagnostic findings |
| `task_accept` | Acceptance gates, passing mandatory validation and complete task coverage on that same candidate, required independent review and exact acceptance authority. A diagnostic recommendation never converts a failed check to a pass | Task acceptance receipt, or coverage-only acceptance referencing a verified existing delivery on the renewal route |
| `task_export_commit` | Export gates, current acceptance/coverage, exact candidate/index/ref/ownership and renderer, and export/commit authority | Sealed export/commit and delivery receipts |
| `phase_validate` | Current phase plan and snapshot, authorized phase check definitions and validation-start gates using earlier sources | Terminal trusted phase check records |
| `phase_ready` | Readiness gates, current plan/head/ownership, settled deterministic phase checks, required I04 review, verified composed coverage and delivery/Git guards | Exact D298 READY |
| `phase_close` | Closure gates, current READY and its verified coverage, and separately confirmed sealed Git/archive/tag intent | Closure, archive and succession receipts |
| `autonomy_advance` | Boundary gates for the actual advance, parent/child authority, plan/batch/caps and earlier prerequisite receipts. Recheck before each downstream effect. I12/I13 cannot rely on their own result for admission | Advance/hold or separately guarded downstream work |

For activation of definitions and again when confirming a concrete plan/admitting a route, compile the
dependency graph from selected gates/criteria, registry producer transitions and the actual workflow.
Phase validation runs as a deterministic predecessor of I04 and READY on the exact snapshot with
confirmed authorized check definitions and current built-in scope. A consumed slot must have an earlier
reachable producer on every applicable route or a verified receipt from an explicitly required predecessor. Check each alternative for a legal
producer and exact compatible binding. Reject unsupported or later producers (including a current
check at `task_validate`, phase READY at its own boundary, or a delivery observation before its
delivery), cycles through prerequisites, and gates whose applicability inputs cannot be known until the
effect they guard. Diagnostic review and acceptance use separate guards. An acceptance check requirement
must not be installed as a review-entry or I03 pre-GO gate if that route must diagnose a failed check.
Validate both pass and fail branches. Report the definition, route, consumer and producer on refusal.
Do not activate a contradictory definition, borrow a witness from a different attempt, or suppress a
failed result. Recompile when route, plan, registry or definition changes.

Ordinary authoring save/preview/adoption and standalone export do not consume execution gates. They retain
their own writer, confirmation, validation and authority checks. A fresh guarded boundary must re-evaluate
if a prerequisite differs, obtain a new authorized preview where required, and stay stopped until then.

| Synthetic case (apply at each applicable boundary) | Required oracle |
|---|---|
| Absent vs unknown terminal/integrity | `incomplete` after evaluation with no witness vs `unknown`; no effect; retained known partial data |
| Verified fail vs expired or changed binding | `failed` vs `stale`; old pass stays historical |
| Source deleted/inaccessible, evaluator exception or unknown version | `unknown` + located source/registry failure, bounded safe diagnostic, no false fallback |
| Wrong subject/project/revision/code/contract/check/profile | Reject candidate; missing correct witness refuses. Same task label or a formerly valid ID cannot substitute |
| Claim/checkbox/import/ruling as consent, forged record ID | Reject as witness; no change to history or coverage |
| Source/revision/clock/authority changes between preview, seal and effect | Refuse before effect; retain preview/work and exact pending record; verify stale rather than promote on replay |
| Pass, valid OR alternative, verified N/A | Current complete binding allows only this gate; OR never conceals another mandatory slot; verified N/A shows its proof and does not imply satisfaction |
| Restore, replay, eventual source loss | Same verified replay yields same fact; original fact remains but lost source gives unknown now; no repeated effect or promotion |
| A later delivered task changes an earlier task's check input | Earlier contribution is stale and holds READY. Renew task coverage on the exact current phase snapshot with the earlier result intact, then join the new acceptance to the original delivery. A changed delivered result requires a new delivery |

T031 owns append-only provenance/evaluation/association persistence, T033 registry and proof projections,
T032 rejects imported authority, T034/T036 own the named fences, T037 shows current/history distinction
and T038 exercises races and restore end to end. T034 owns renewal admission and acceptance in the task
lane. T038 verifies its composition with original delivery in the phase lane.

## Human editing and recovery

Document navigation renders adopted entities and blocks in order. Open inline or a side panel for an entity
and show type, code, readable fields, provenance and linked records. Use typed selection controls, move/reparent
commands, preview rendered safe Markdown/Mermaid with a raw authoring text area, and locate diagnostics on
the corresponding field/edge. In the UI renderer output and markers are read-only. Explicit IDE import can propose edits inside
marked narrative fields through the [exchange contract](P002-T030-model-codec.md#markdown-and-portable-exchange). Retired and historical
versions remain viewable. All views distinguish work language from en/es interface labels.

| View | Authoring surface | Read-only and protected |
|---|---|---|
| SPECIFICATION | Purpose/scope/exclusions/assumptions/unknowns/narrative blocks, requirements and criteria, ordered block tree and criterion ownership | Verified coverage and old source/revision |
| ARCHITECTURE | Component/interface/invariant/flow/deployment blocks, responsibilities, boundaries, Markdown/Mermaid, order/dependency and referring entities | Implementation evidence, original and sealed diagram history; DDBB and flow blocks keep separate ownership |
| DECISIONS | New proposal or draft edit, full/partial superseder with field selection and exact consequences; move draft order | Frozen accepted/rejected/retired record and prior links; rulings and adoption facts |
| ROADMAP | Project intent, ordered phases with scope/exclusions/delivery plans, dependencies, criteria | Active/READY/closed state, adopted plan, actual release/installation, archive/closure |
| NEXT_STEPS | Tasks, subtasks, reorder/reparent, criteria, dependencies, decision/architecture/gate/evidence pickers, explicit replacement preview | Next runnable, actual status/checks/budgets and admitted contracts |
| STATE | Optional note only | All other rows derived; unknown/truncated explicit, no status edit |
| Instructions | Rule title/body/tree, scope/client/stage/role and compatibility grouping on owner-sensitive path | Exposure and qualification history; target ownership remains a separate action |

### Persisted working copies and commands

Use `working-copy-1` separate from canonical `draft-2`. Working copy identity is project + ID with immutable
owner and base revision/hash, monotonic version, editor generation and typed input buffers. Closed buffers:
`{locator, type:text|choice|reference|order, raw, target:ID?}`, locator is stable entity/temporary ID +
field pointer or typed edge key. raw is the exact UTF-8 string for text/choice, unresolved label for reference
and ordered array of existing/temporary IDs for order. Null target means unset/unresolved.
The versioned locator catalogue distinguishes member fields, new member declarations, explicit
member withdrawals, edge add/remove controls and order groups. The action at each locator fixes its
buffer type and allowed raw choices. A saved blank value is distinct from an absent buffer. Raw text can be
blank/invalid for the target schema. Persist unresolved relations, field order and diagnostics keyed to copy
version. Limits: 1 MiB per copy, 2,048 buffers, ≤ 65,536 bytes per buffer, 32 open copies per project; reject
over-limit saves with local input intact. Backup includes acknowledged copies and pending/outcome records;
query-only restore reads them without creating mutation workspaces. Acknowledgement follows durable
transaction commit, including on full-disk or crash boundaries. No idle expiry of open copies or pending
requests. Explicit discard marks the resolved copy closed and permits payload removal; keep identity/base,
tombstone and command receipts. Keep successful staged/adopted canonical data and exact pending/outcome
records under existing adoption and effect retention. When limits are reached the owner can recover,
download authorized work, or explicitly discard a resolved copy. Backup copies retain their recorded state.

All commands are versioned catalog operations, with the common envelope
`{command, project, key, expected, input}`. `expected` and `input` are closed by the table. ID/version/hash
references carry all three values unless specified. Session, actor, permissions, project and query-only guards
precede lookup/replay. Digest canonical envelope bytes, scope key to project/actor/command, and persist
outcome with mutation in one transaction. Same key/bytes returns stored outcome, same key/different bytes
refuses. Exact resolved refusal can be inspected; retry after correction uses a newly confirmed envelope.
No writes through generic filesystem/SQL tools.

| Command | Expected CAS and input | Durable effect |
|---|---|---|
| `author.open@1` | Current head reference; editor classification | Allocate copy with empty buffers/current base |
| `author.save@1` | Copy version; complete buffer set and order | Persist incomplete work; no staging/head change. Base may be stale; mark conflict |
| `author.discard@1` | Copy version; explicit reason | Close only after pending outcomes resolved |
| `knowledge.stage@2` | Exact copy ID/version/hash and base head, expected prior draft ref or null; empty input | Derive edits from exactly that saved copy, validate and seal the draft, edit digest and copy ref; located failure leaves copy and prior draft intact |
| `knowledge.preview@2` | Current head, draft/copy refs; no extra input | Seal exact before/after fields/ranges, links/order, provenance, supersession, sensitive text and verified impact version |
| `knowledge.adopt@2` | Same head/draft/copy refs, preview ID/hash; nonempty reason and confirmation of exact preview | Recheck authorization, draft/copy CAS, writer and impact fence; adopt sealed draft atomically with outcome |
| `documents.preview@2`, `documents.confirm@2` | Accepted revision, ownership/renderer and checkout baseline; preview hash + reason on confirm | Independent sealed export intent, per-target and Git receipts; no adoption |
| `operations.reserve@1` | Scope generation and exact preview; canonical confirmed envelope and its digest | Verify current CAS and consent, consume preview and durably reserve its exact command |
| `operations.dispatch@1` | Reservation ref; same canonical confirmed envelope | Verify ticket/envelope and execute or reconcile under the original effect owner |
| `operations.cancel@1` | Reservation ref; explicit reason | Close only a provably undispatched reservation; persist tombstone |
| `operations.fence@1` | Writer domain, generation and complete recovery view token; explicit confirmation of that view | Compare the observed view under the writer and advance generation only with no unresolved reservation, fencing older previews without an effect |
| `operations.recover@1` (read) | Project writer domain with optional copy/preview filter and bound cursor | List authorized reservations, terminal outcomes and acknowledged copy references. An unfiltered, complete domain view supplies a fence token |
| `operations.outcome@1` (read) | Command and exact key + request digest | Read the same intent/outcome; actor/scope guard, no write or retry |

Typed edits are a bounded ordered list (≤ 2,048) of `put_member` (new temp ID or expected member version,
closed kind/content/code/provenance), `withdraw_member` (expected ID/version), `put_link` (exact link),
`remove_link` (exact old link), `order_group` (root/owner group and exact prior/new ID order).
Constrain each to the actor's scope, canonicalize temporary IDs on the server and include allocation in the
idempotent outcome. For human staging the server computes the complete list from the immutable base and
the referenced saved buffer snapshot using the versioned command compiler. A save is a full snapshot of
intended changes, with explicit clears, withdrawals and removed edges. Absent buffers leave base values
unchanged. Resolve typed selectors, group field edits for one member into its full candidate value, resolve
temporary IDs and edges, and apply exact order edits. Every buffer must be accounted for as a validated
change, explicit no-op against the base, or located diagnostic. Duplicate or overlapping locators,
incompatible edits, unresolved targets and dropped buffers refuse the entire stage. An edit list supplied
by a staging caller is an unknown input key, even if it appears equivalent. Seal the ordered operations
and buffer-to-operation/no-op mapping with the draft. Changes to a saved copy, concurrent head, or draft
version invalidate its old preview.
Inspect pending command, history, heads, diagnostics and projections via revision-bound queries. Agent
proposals use the same typed edits through scoped `knowledge.propose@2` with expected revision and rationale;
no human buffers or adoption consent are granted to the proposal tool. D293 sensitive changes stay owner-only.
An import/conversion carries source/map confirmation in its draft and cannot be adopted through a weaker path.

Local buffers and exact pending envelopes survive reload/navigation in the project's browser storage,
namespaced by owner/project/copy/generation. Persist canonical request bytes and key before dispatch.
Report storage failures and refuse new irreversible confirmation without recoverable storage. Local text
is unsaved until acknowledged. Save/stage recovery can query the acknowledged copy and exact
command outcome. Irreversible effects additionally require the reservation below. Read, edit and preview generations are independent. Late responses must
not clear newer input or restore stale consent.

For irreversible confirmation, reserve a server ticket before any effect request. The reservation
records the authenticated owner's exact confirmed command bytes, key/digest, preview and scope bindings
under the authoritative writer. It performs no adoption/export effect. The effect endpoint accepts only
the matching ticket and exact envelope. The server owns a single unresolved reservation per
project/writer domain (knowledge head for adoption and checkout for export, with existing cross-domain
writer exclusions). The reserve CAS covers current preview/base and a monotonic scope generation, shared
across tabs and copies. Each successful reservation consumes that preview's confirmation token;
a distinct command requires a new preview. Cancellation leaves the consumed token closed. Persist the
reservation and acknowledgement receipt in one transaction before returning. Effect dispatch, cancellation
and settlement serialize under the same guard. An undispatched reservation may be explicitly cancelled with a durable tombstone that rejects late dispatch. A dispatched or possibly
applied effect holds the slot until exact settlement, or verified no effect with stopped writers where
required. TTL, missing response and a temporary empty read never release the guard.

Authenticated, owner-scoped recovery lists acknowledged working copies by project, and reservations and
retained outcomes by writer domain with their copy/draft/preview/operation references and status. It can
rediscover the command, key and digest and return the original confirmed envelope to that same authorized
owner for inspection and explicit exact resend. Do not expose another actor's command bytes. Apply current
permissions and read-only/restore restrictions before dispatch. Pending or uncertain results offer status
and existing intent reconciliation, not a new confirmation. Reconciliation of a dispatched external
effect still requires the effect owner's stopped-writer evidence and fresh explicit confirmation of
the same intent where D298 requires it.

For a recovery fence, the owner reads the unfiltered domain recovery view. Bind every page to the same
generation and monotone domain recovery revision. Under the domain writer, increment that revision with
every reservation, dispatch/status change, cancellation, settlement or other change to the reservation and
outcome set or its availability, and with the fence itself. Return an authenticated complete-view token
only after the unfiltered traversal of that snapshot finishes. Bind it to the owner, project, writer
domain, generation, recovery revision and digest of the ordered reservation and retained outcome references,
statuses and result digests, including outcomes from earlier generations. A filtered or partial view cannot
authorize a fence. Restart if pagination drifts. Hold if a required result cannot be presented under current permissions.
The client presents the complete view, including terminal outcomes, before asking the owner to explicitly
confirm that view for fencing.

The fence writer verifies that confirmation, current authorization and the token's bindings against the
current generation, recovery revision and result set, and verifies no unresolved reservation, atomically
with the generation advance. If a reservation settles between the read and the fence, even an empty
current slot and unchanged generation cannot pass that CAS. Refresh the recovery view and show the
intervening result before another fence confirmation. The fence invalidates older previews and delayed
reservations and creates no adoption or export effect. Enable fresh effect consent only after a successful
fence, using its resulting current generation and a fresh preview. An old dispatch without a live matching
reservation cannot act. Retain original receipts and superseded generations for lookup. Unacknowledged
offline buffers may be lost and must never be labelled durable.

No automatic rebase/merge. Conflict resolution opens a new draft against current head and transfers only
owner-selected inputs with diagnostics and fresh comparison. Old saved work remains available.

### Authority and delivery transition

Track classification at the document view and file-target boundary independently of protected selection:
legacy edit lane, noncanonical permitted file or view-only, canonical DB authority, and historical/query-only.
A project may read a canonical DB view before any owned file exists. Once DB authority for a registered view
is adopted, forbid that target in legacy mutation/confirmation/ref recovery using current classification and
single-writer CAS. Resolve a pending old intent before transitioning; recorded effects are reconciled in their
own lane, unsent text preserved and explicitly mapped if requested. A dirty legacy file has its existing
confirmed file lane only if still classified writable; no fallback on DB/read errors. Noncanonical permitted
files retain D293/D294 legacy guards. An edit to a protected selected original triggers source revalidation,
not adoption or reclassification. Historical archives/retained originals stay consultation/download only.
Explicit import creates new work with provenance. Query-only and unconfigured consultation require no checkout.

Export shows accepted revision independently of delivery. States are pending/refused/failed/partial/completed
with intent, per-target results and exact commit evidence. Resolve uncertainty with the same intent and owner
under D294/D298; verify baseline/absence or sealed bytes, refuse unrelated dirt, and preserve known receipts.
Task/closure-owned exports remain in their owners' existing paths. No save/adoption implies an export, commit,
READY or actual delivery.

## Execution impact

Knowledge changes can be staged and saved alongside any activity. Adoption coexists only where existing
writer, pending-effect and authority guards permit it. Under a held writer refusal retain work; do not time
out or displace that writer. Proposed default is **strict current binding** at the next guarded effect:
even a display-only accepted revision change requires current binding validation. Changed head is an exact
mismatch for old admission/READY/delegation/intent that requires it. Project-note edits gain no exemption.
Consultation remains possible for every historical result.

| Affected binding | Change and consequence at fresh boundary | Separate action and persisted association |
|---|---|---|
| Adopted plans/batches | Task/dependency/criterion/order/instruction changes do not edit sealed plan. New head cannot be shown as that plan's current READY. A fresh structured plan check resolves actual incompatibilities; later confirmed plan invalidates READY/batches per D298 | Separate plan preview/hash + CAS. Store phase plan→revision/ordered task and criterion versions, batch/READY IDs and ownership generation |
| Admitted/queued task | Scope/dependency/order, contract, code, instructions or any stale required head/profile/authority fails at next admission/inference/validation/review/accept/commit fence. Queue identity and budget intact. Withdrawn scope does not silently retarget | Explicit new admission/owner resolution through existing workflow, D296 lineage/budget preserved. Store job→plan/contract/revision, code/selection/profile/authority and all used gate/evidence refs |
| READY and evidence | New head/ownership or different code/criteria makes current READY stale. Historic passes stay attributed to prior subject/effect. Missing evidence means current unknown/incomplete | New readiness checks/confirmation against exact new binding. Store READY→revision/ownership/plan, evaluated code + gate/evaluation witness set |
| Autonomous parent/child | Changes do not renew or expand authorization. Parent, child, cap/plan/revision checked on admit, continuation and resume. Incompatible fresh boundary holds | Explicit existing owner authorization/resolution. Store parent/child→batch, scope/version, task/plan refs, qualification and budget counters |
| Active invocation | No retroactive prompt/tool/context replacement. Complete/settle original attempt and record its original digests. Live security revocations keep existing owners; changed source exposure may deny new tool reads, never serve replacement bytes to an old invocation | Fresh admitted attempt only after exact compatibility checks. Store attempt→policy, sources, epoch, revision, code, sealed prompt and permissions |
| Sealed export/closure | Later adoption cannot rewrite intended/generated bytes or closure history. Writer fences may refuse adoption while intent pending. Reconcile any already-applied effect on its original observation; missing or stale current binding refuses further effects requiring it | Resolve same intent, then obtain separate preview/consent for a new effect. Store intent→ownership/renderer/revision/evaluation/READY and exact Git/index/ref/archive/tag receipts |

Impact query reads a deterministic joined association index (≤ 100 per area per page, version-bound cursor)
with explicit `verified, unknown, unavailable, truncated` coverage. Preview seals index generation, observed
classes, exact changed subject bindings and count or lower bound. Show known affected refs and unavailable
areas with a separate acknowledgement when presentation is bounded. An unknown current writer, authority
or pending effect guard **refuses** adoption. An unknown historical association may be acknowledged for
knowledge adoption because no historical authority is used; it refuses any fresh effect requiring that binding.
Recheck the index generation/authoritative bindings under the adoption writer. No joins by task label, no
automatic cancellation, replan, rebase, authorization renewal, replacement, retry or retroactive mutation.
T031 persists associations, T033 projects them, T034/T036 enforce fresh guards, and T032 owns export recovery.

## Routed acceptance for T037

Use synthetic project routes in a real browser in en/es, desktop (at least 1280×800) and narrow (at most
390×844). From each document, the knowledge history and map drawer, navigate to the same typed entity
and back with selection/focus retained. Exercise readable Markdown/Mermaid, new/edit/reorder/reparent
subtasks with keyboard and pointer, relationship pickers with invalid cycles/unresolved targets, immutable
decision and explicit supersession, exact sensitive comparison, derived/read-only states, and unknown impact.
Record per journey route/locale/viewport, screenshots, focus order, overflow/scroll measurements and outcome.
Verify visible labels/announcements, no horizontal page overflow outside contained code/diagrams, focus
restoration on dismiss, keyboard reachability without traps, and diagnostics linked to fields.

Drive response loss after successful save/adopt/export, validation/read errors, stale responses, two editors,
reload/remount, partial export and exact recovery. Show local-unsaved vs durable work, stale preview refusal,
conflict transfer, committed knowledge with failed delivery, and effect races in the impact matrix. Traverse
legacy unsent/pending text, stale writer refusal, noncanonical permissions and checkout-free archive reads.
In the recovery race, show the outcome that settled after the empty read and require confirmation of the
refreshed view before enabling fresh consent. Exercise the opposite ordering with a delayed reservation.
Capture before/after screenshots and exact observed effect/receipt counts without rendering internal IDs as
authoring controls. Require observed real-browser journeys and owner visual acceptance; T038 audits
cross-layer recovery/restore and T028 repeats final normal/autonomous journeys.
