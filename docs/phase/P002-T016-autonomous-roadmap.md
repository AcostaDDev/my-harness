# P002-T016 — Full-roadmap autonomous execution

## Local contract and delivery

Owner-authorized local implementation, 2026-11-03. Branch `feat/p002-t016-autonomous-roadmap` in the original
checkout (no concurrent activity was present), from `develop` at `91d3a74`, which matched the local
`origin/develop`. T003, T006, T009, T010, T014 and T015 are integrated (T015 as `f7c5ce3`). Starting schema
`0037_task_lineage`, 86 tables. The existing T015 worktree `/private/tmp/my-harness-p002-t015` is preserved
untouched. The one-off queue is empty. D297 (T017/T018 design) is outside this task.

Scope contract: the T016 section of [NEXT_STEPS](../NEXT_STEPS.md#p002-t016--full-roadmap-autonomous-execution) and
[D276](../DECISIONS.md#d276--autonomous-roadmap-runs-local-bounds-and-stops). Authority and effects: D269, D272.
Continuation and recovery: D282, D283, D287. Judge and permissions: D290, D291. Lineage, READY and closure: D296,
D298. [Contracts](P002-T001-contracts.md) §§4, 7, 10–13; [flows](P002-T001-flows.md) FL01–FL07 and the wait,
answer and recovery parts of FL12–FL13. Threats TM05 and TM15. Inputs and limits from the T011, T014 and T015
records, SPECIFICATION §14 and ARCHITECTURE §13.

In scope: readiness and start preview over the accepted revision; an `owner_confirmed` autonomous authorization
sealed by exact hash with idempotency and revalidation; one active autonomous authorization per root excluding
concurrent starts and manual batches; reconciliation of a sealed authorization whose run creation was interrupted;
a LangGraph roadmap graph over the existing runtime and journal routing planning, adoption, tasks, checks,
remediation, closure, archive and succession through typed services; concrete `owner_delegated` child records;
persistent local bounds and optional caps checked before each inference; durable stop states with reasons and
evidence; per-project start, status, questions, answer, pause, resume, revoke and recover controls; deduplicable
events and references for T017; the completion rule.

Out of scope: T017 global inbox, T018 map, T019 accounting projections, T020 installed-data conversion, real
provider qualification, new dependencies, and any rewrite of frozen contracts, catalogues, receipts, snapshots or
historical evidence.

Gates: G11 (default bounds and no-progress fingerprints), G12 (readiness predicates and reviewer gap
classification) and G17 (risk acknowledgement text and version) are open in D276 and the T001 register. This task
prepares one joint proposal ([§3](#3-joint-gate-proposal-g11-g12-g17)). Until the owner resolves them, the
definitive defaults and fingerprints, the definitive readiness verdict and the productive confirmation that depends
on the acknowledgement stay blocked; persistence, transitions, already decided guards and their parametrized
synthetic tests proceed without treating provisional policies as approved.

Delivery route: reviewable local source → `develop` after review → release 0.2.0 through protected `main` →
verified distribution/publication → installation. The recorded installed version is 0.1.9. Integration and every
later stage are pending in this assignment; commit, merge, push, publication, installation, service start, harness
execution on this repository and real agents/providers are not authorized.

## 1. Implementation map

Status: **source complete; five technical-review findings ([§8](#8-technical-review-findings-and-corrections)),
three remaining blockers ([§10](#10-remaining-review-blockers)), two third-review blockers
([§12](#12-third-review-blockers)) and the final-review held-review window ([§14](#14-final-review-held-review-window))
corrected and verified locally**; gates resolved (D300) and the integral
production route over T014/T015 ([§6](#6-integral-production-route)). Final review is pending.
Representation details are recorded in [D299](../DECISIONS.md#d299--autonomous-run-authority-children-and-persistent-bounds).

| Area | Files (under `src/my_harness/`) | State |
|---|---|---|
| Pure contract | `core/engine/autonomy.py` | States/transitions (FL02), bound/cap/delegation validation, cap evaluation, failure classes, scope digest, FL01 structural checks, verdict, FL03/FL07 `decide`, completion rule. `GatePolicy` carries G11/G12/G17 values; `PRODUCT_POLICY` has none. G11/G12 proposals are labelled functions selected only by a policy. |
| Schema | `migrations/versions/0038_autonomous_runs.py`, `storage/models.py`, `storage/schema.py` | Seven tables (93 in total); five insert-only by trigger; partial unique index for one non-terminal run per root; trigger digest and required tables updated. Empty on upgrade; downgrade refused with evidence. |
| Authority | `storage/autonomous_runs.py` | Seal by idempotency key and request digest; run creation with exclusion; CAS state moves with events; delegated children; root-scoped consumption; versioned questions; deduplicated events with references for T017. |
| Permissions | `services/permission_lifecycle.py` | `roadmap_parent` (owner-confirmed parent with phases and tiers, no targets), `task_child` (exact contract write paths of an authorized phase, `owner_delegated`, verified unchanged by T014's `_check_delegated_scope`), `end_roadmap` (cascade, D291) and `delegated_inactive`, which makes the existing `cancelled` poll stop a delegated writer after revocation. Manual runs are unaffected. |
| Service | `services/autonomous_roadmap.py` | Readiness, preview, confirmation, revision, reconciliation, the graph step (guard → observe → decide → bounds/caps → child + consumption → sealed effect), controls (status, events, answer, pause, resume, revoke, recover) and harness-wait advancement. |
| Graph | `orchestration/roadmap.py`, `services/managed_runtime.py` | `autonomous-roadmap@1`: an `advance` loop node and a `hold` node that interrupts; effects through `run_operation` with deterministic keys; per-segment limit only. Reached through `managed_runtime.roadmap_graphs` (lazy LangGraph import). |
| Production effects | `services/autonomous_effects.py` | Readiness observation, routing observation from SQLite, observed invocation count, writer settlement, revision items, and every effect over the existing operations ([§6](#6-integral-production-route)). |
| Exclusion | `storage/phases.py` | Manual batch authorization refused while an autonomous run is active on the root; confirmation refused while a batch is active. |
| API | `api/autonomous.py`, `api/schemas.py`, `api/app.py`, `frontend/openapi.json`, `frontend/src/api.generated.ts` | Routes under `/api/managed/projects/{project_id}/autonomous`: readiness, preview, confirm, status, events, questions, answer, pause, resume, revoke, recover, revise. Additive OpenAPI; types regenerated by the README procedure. |
| Messages | `i18n/en.json`, `i18n/es.json` | Two keys with en/es parity. |
| UI | `frontend/src/AutonomousRun.tsx`, `frontend/src/pages/Project.tsx`, `frontend/src/i18n/{en,es}.json` | Minimal project panel: readiness with explicit bounds (no defaults), preview with acknowledgement, start, status, consumption, open questions and answers, pause, resume, revoke, recover. |

Decided guards applied now: exact preview hash, idempotency, revalidation of revision, configuration and Git
baseline; one active run per root versus concurrent starts and manual batches; FL01 structural checks; parent
activity, latest revision, policy version, scope digest and configuration before every decision; caps before every
inference, with unknown usage stopping only when its cap is set; bounds before every delegated action; durable stop
reasons, evidence and events in the transition transaction; explicit resume with revalidation; revocation cascade
and cancellation; recovery only with stopped-writer evidence, abandoning uncertain sealed effects under their
original identity; completion only with every authorized phase `CLOSED`, criterion evidence, coverage and the sealed
successor; `ABANDONED`, a missing successor or incomplete evidence fail without success. Closure never pushes,
releases, publishes or deploys: no effect for those exists in the port.

Gate values: before D300 the product policy had none, so readiness answered `PENDING_GATES` and confirmation was
refused `gates_pending` before anything was sealed (still covered with `PENDING_POLICY`). After D300 the product
policy carries the accepted values ([§5](#5-owner-decision-and-gate-conditions)) and the production route is
integrated ([§6](#6-integral-production-route)).

## 2. Synthetic acceptance evidence

`tests/product/test_autonomous_roadmap.py`: 129 cases over migrated temporary SQLite, a disposable Git checkout,
the real LangGraph runtime, saver and operation journal, the real T010 permission records and an in-memory roadmap
behind the typed port. Synthetic policies are labelled `synthetic`; the G11 proposal is parametrized against a
strict alternative equivalence.

| Area | Cases |
|---|---|
| Contract | All 64 FL02 state pairs; explicit finite bounds without defaults; caps as thresholds and unknown usage; failure classes; G11 fingerprint invariance under rename/noise; G12 citations and current answers. |
| Gates | Product policy: readiness `PENDING_GATES` with all structural checks passing, confirmation refused, zero rows. Six structural failures block without a model; a G12 owner-answer gap blocks. HTTP: same gate through the routes, missing Idempotency-Key 422, absent bounds blocked. |
| Admission | Exact hash, acknowledgement version, explicit confirmation, Git baseline change → stale, idempotent replay, conflicting replay; sealed preview, policy label and T010 parent; concurrent starts on two threads → one run; partial unique index; manual batch exclusion in both directions; interrupted run creation reconciled without duplicates. |
| Normal route | Three phases × two tasks complete through 18 `owner_delegated` children (both fingerprints); twelve phases cross ≥ 5 durable segments with segment limit 5; judge children for planning choice and blocked check with READY from a fresh check; remediation bounded per cause with lineage. |
| Waits and limits | Phase question: open-question resume refused, stale version, superseded answer after a revision change, explicit resume to completion; idempotent answer; task attempts persist across resume, a lowered revision refused, a raised revision and a D296 replacement family (no refill); no-progress bound (both fingerprints); four caps before inference; quota/authentication/environment stop once without retry and resume explicitly; pause at a boundary with Git revalidation; scope amendment waits for revision 2. |
| Revocation and recovery | A parent already ended from the permission controls stops the run `authority_inactive` and the run can still be revoked; revocation ends the parent and task child, revokes the thread and admits nothing more; revoked parent makes the existing cancellation poll fire for the delegated run only; simulated process crash inside an effect → `RECOVERY_REQUIRED`, refused recovery without confirmation or with an active writer, owner-confirmed recovery abandons the sealed operation, resume completes without reissuing its key; node failure continues on a new thread only without pending operations. |
| Not success | Abandoned successor, missing successor and incomplete evidence end `FAILED`. Insert-only tables refuse deletes. |
| Authority boundary | Task child satisfies T014's delegated scope, out-of-scope phase or empty targets refused, refused without the delegable tier, inactive after revocation. |

Focused run: `scripts/check tests/product/test_autonomous_roadmap.py -- -n 0` passed 128 before the closure
correction below and 129 after it. Affected selection
(orchestration, permissions, structured phases, phases, storage API, accounting migration, service diagnostics,
backup, operation journal) passed 289 before the OpenAPI regeneration and 290 after it. Complete checks are
recorded in [§4](#4-checks-and-diff-review).

Pending (integral route, after the gates): the production routing observation and the delegated plan/task/check/
closure/judge effects over T014/T015 (including supervisor-driven harness-wait advancement, the T009 delegation
contract on the parent and `ruling_id` on children), the reviewer gap-report invocation, and an end-to-end
synthetic managed journey across several structured phases with fake CLIs.

## 3. Joint gate proposal (G11, G12, G17)

Only the pending decisions, each with one recommendation. Accepting them unblocks the definitive defaults and
fingerprints, the definitive readiness verdict and the productive confirmation; the integral route is then
integrated and verified in this task.

### G11 — default bounds and no-progress equivalence

Recommendation: accept these defaults as **prefilled preview values** that the owner confirms by hash (none is
applied silently; the representation ceiling stays 1,000) and the identities below.

| Bound | Default | Consumes one unit | Identity that keeps the budget |
|---|---|---|---|
| `task_attempts` | 3 | Each delegated task admission (managed run) of any task in its D296 replacement family; failed, denied and uncertain admissions count. D296's correction ceiling still applies inside each run. | Task code, counted over the adopted `replaces` family. |
| `judge_reconsiderations` | 1 | Each judge request after the first for an equivalent subject. | Duty + phase knowledge item + subject operation. |
| `replacement_plans` | 2 | Each plan proposal for a phase after its first (remediation excluded). | Phase knowledge item. |
| `remediation_per_cause` | 2 | Each remediation proposal for a check cause. | Phase item + digest of check classification and sorted unmet criterion items. |
| `no_progress` | 3 | Each delegated action taken from an equivalent progress fingerprint. | `g11-proposal-1` fingerprint. |

Equivalence `g11-proposal-1`: digest of the phase knowledge item, planned and committed D296 families, latest check
verdict/classification with unmet criterion items, open owner questions, and the decided action with its subject
family or duty. It excludes timestamps, run/attempt/operation/authorization identities, codes and wording.

No reset: consumption is insert-only and scoped to the project root, so resume, a new authorization revision,
phase change, task rename (stable item identity) and split (joined family) never refill it; a later run on the same
root also sees it. A revision may raise bounds but never lower them below the confirmed values.

### G12 — readiness predicates and reviewer gap classification

Recommendation: accept the twelve structural predicates as implemented (accepted revision; roadmap ordered by
phase code; at least one active criterion per authorized phase; exactly one open phase, the first unclosed one;
preparation receipt admitted; clients compatible; clean Git baseline; no uncertain writer; no pending job,
commit intent or document intent; no other active run; no active manual batch; explicit finite bounds), and the
reviewer report contract:

- A fresh accounted reviewer invocation through the existing supervisor and ledger over the frozen accepted
  revision returns `{revision, gaps: [{classification, statement, citations: [{item, revision}]}]}`.
- `blocking` (contradiction, untestable or missing criterion, dependency conflict) → BLOCKED.
  `owner_answer_required` (requirement meaning the owner must settle) → BLOCKED until a current owner answer
  bound to the same revision and gap digest exists. `advisory` → shown, does not block.
- A gap without citations, or citing another revision, is blocking. Malformed output or a provider failure yields no
  verdict and is not retried (FL01).
- The preview binds the report digest with the revision; any revision change invalidates the preview.

The versioned prompt template that produces the report is drafted at integration under the G16 conventions and is
shown in the diff for review before use.

### G17 — risk acknowledgement text and version

Recommendation: accept version `autonomy-ack-1` with this text. The preview shows it in the visual language and
binds the version and the digest of both texts; a new authorization revision requires the current version.

> I authorize My Harness to plan, execute, check, repair and close the phases listed in this preview without asking
> me at each step, within the delegation, bounds and caps shown. Agents run as local processes with my user's
> permissions; the harness contains them cooperatively and can stop them, but it cannot guarantee that no action
> happens before a stop takes effect. Caps are thresholds checked before each new model call, so a call already
> running may exceed them. The run never pushes, publishes, releases or deploys, never changes objectives, criteria
> or requirements, and stops for my answer when it needs one. I can pause or revoke it at any time.

> Autorizo a My Harness a planificar, ejecutar, comprobar, reparar y cerrar las fases indicadas en esta vista previa
> sin preguntarme en cada paso, dentro de la delegación, los límites y los topes mostrados. Los agentes se ejecutan
> como procesos locales con los permisos de mi usuario; el harness los contiene de forma cooperativa y puede
> detenerlos, pero no puede garantizar que no ocurra ninguna acción antes de que la detención surta efecto. Los topes
> son umbrales que se comprueban antes de cada nueva llamada a un modelo, por lo que una llamada ya en curso puede
> superarlos. La ejecución nunca hace push, publica, lanza versiones ni despliega, nunca cambia objetivos, criterios
> ni requisitos, y se detiene para pedirme una respuesta cuando la necesita. Puedo pausarla o revocarla en cualquier
> momento.

## 4. Checks and diff review

`scripts/check --frontend` was executed once on the complete source: unittest 10 passed; Alembic no new upgrade
operations; pytest 3,100 passed, 1 failed, 2 skipped, 1 warning (the existing synthetic duplicate-ZIP entry), 29
subtests passed; Node 275 passed; TypeScript/Vite build passed. The failure was
`test_configuration.py::test_additive_migration_and_metadata`, a table-count assertion that still expected 86
product tables; it now expects 92. Diff review found one defect: if the owner had already ended the roadmap parent
from the standing-permission controls, revoking the run failed on the duplicate end record. `end_roadmap` now returns
the existing end record, with a regression case. The corrected selection (autonomous roadmap, configuration and
permission lifecycle) passed 224. The complete suite was not repeated after these two corrections, as requested.
`scripts/check-docs` and `git diff --check` passed on the final diff.

Not tested: native providers or CLIs, a running service or browser smoke test of the new panel (type-checked and
built only), harness execution on this repository, release packaging or installation, and backup verification of the
new tables beyond the schema trigger digest. The production routing and delegated effects are not implemented, so
no integral productive route is claimed.

Source disposition: implemented locally and checked; not committed. Review, integration into `develop`, release
0.2.0 through protected `main`, distribution/publication and installation (recorded installed version 0.1.9) remain
pending. The one-off queue stays empty.

## 5. Owner decision and gate conditions

On 2026-11-03 the owner supplied a review of §3 as the decision: G17 accepted as proposed; G11 and G12 accepted
with conditions; revocation from `RECOVERY_REQUIRED` accepted. It identified two bypasses in the source and two
G12 binding defects. Recorded as [D300](../DECISIONS.md#d300--g11-g12-and-g17-accepted-with-conditions).

| Condition | Change |
|---|---|
| G11: a split could change the fingerprint without progress (duplicated family entries) | `_progress` and `progress_fingerprint` (`g11-1`) use sorted, deduplicated canonical families (and deduplicated criteria and questions). |
| G11: a new operation gave the same judge subject a new budget | `judge_subject(duty, phase item, cause)`; blocked-check causes are the classification and unmet criteria; the operation identity is no longer part of it. |
| G11: consumption across runs of the same project | Already root-scoped and insert-only; recorded as accepted. Defaults prefill the preview (`default_bounds`, panel button) and stay subject to confirmation. |
| G12: report validated against the service's frozen revision, citations to existing items | `validate_gap_report` (closed schema) and `classify_gaps(report, context)`: the service supplies the revision number, the item identities of that revision (`revision_items`) and the answers; a report for another revision blocks. |
| G12: answers from current owner records | New insert-only review table (now `autonomous_reviews`, `answer` kind, `owner_confirmed`, bound to the revision) through `answer_gap` and `POST …/autonomous/gaps/answer`; answers inside a report make it malformed. |
| G12: reviewer only after structural checks | `readiness` requests the report only when all twelve checks pass. |
| G12: confirmation reused no sealed report | One sealed report per frozen revision and classifier version (`report` kind), reused by every later readiness; a malformed report is sealed too and not retried. Confirmation calls the preview with `generate=False`: without a sealed report it is refused, and a revision or answer change makes the hash stale. |
| G17 | `autonomy-ack-1` en/es texts in the message catalogs; `ACKNOWLEDGEMENT_SHA256` disables the acknowledgement if the catalog text changes. |

Schema now has seven T016 tables (93 in total). Focused verification after the changes: the autonomous suite
passed 135 cases (new: classification against service items, split and judge-subject bypasses, accepted product
policy, single reviewer call after structural checks with owner-record answers and sealed-report reuse at
confirmation, three invalid reports never retried, confirmation without a sealed report). The selection with
configuration, storage API and service diagnostics passed after regenerating OpenAPI and client types. The wider
affected selection (autonomous, orchestration, permission lifecycle, structured phases, phases, configuration,
storage API, service diagnostics, backup, accounting migration) passed 423; Node 275 passed; the TypeScript check
and Vite build passed; `scripts/check-docs` and `git diff --check` passed. The complete `scripts/check --frontend`
was not repeated for these changes; it is due once more at task closure, after the integral route.

The integral route that remained after these conditions is recorded in [§6](#6-integral-production-route).

## 6. Integral production route

Owner instruction of 2026-11-03: integrate and verify the production route in this task under D300. Recorded
design detail: [D301](../DECISIONS.md#d301--delegated-task-contracts-and-effect-boundary-verification).

### Where to review

| Topic | Files (under `src/my_harness/` unless noted) |
|---|---|
| Versioned prompts | `core/engine/templates/roadmap-readiness.md`, `core/engine/templates/roadmap-task-plan.md`; registration and closed schemas in `core/engine/prompts.py` and `core/engine/autonomy.py` (`gap_report_schema`, `task_plan_schema`, `validate_task_plan`, `render_task_plan`); CLI shape in `adapters/cli_agents.py` |
| Reviewer jobs | `storage/autonomous_jobs.py` (queue, keys, settlement and sealing), `services/autonomous_review.py` (frozen canonical context, accounted invocation, validation), dispatch in `services/managed.py` and `storage/managed.py` |
| Adoption authority | `storage/structured_phases.py` (`StructuredPhases.adopt`, `delegated`), `services/knowledge_exchange.py` (`PhaseKnowledge.adopt`), `storage/autonomous_runs.py` (`verify_child`) |
| Closure authority | `storage/phases.py` (`submit_close`, `delegated`), `storage/structured_phases.py` (`effect_guard`), `storage/autonomous_runs.py` (`verify_child`) |
| Recovery and continuation | `services/autonomous_roadmap.py` (`advance_all`, `advance_waiting`, `recover`, `reconcile`, `_continue_thread`), `services/managed.py` (`LocalSupervisor.autonomy`), `services/managed_runtime.py` |
| Judge | `services/autonomous_effects.py` (`judge`, `_ruling`), `services/permission_lifecycle.py` (`judge_policy` for `roadmap:` subjects), `services/autonomous_roadmap.py` (`_judge_delegation`) |

### Route

- **Readiness.** After all twelve structural checks pass, `gap_report` queues one `roadmap_review` job per frozen
  revision (purpose `autonomy`) through the existing queue, supervisor, frozen-context receipts and ledger. Its
  settlement seals the validated report or a malformed record once; an operational failure leaves an event and is
  never requeued. Readiness reports `gap_report_pending`/`gap_report_failed` meanwhile; readiness jobs do not count
  as pending effects. Confirmation reuses the sealed report (D300).
- **Task contracts (gap found and resolved).** Accepted D284 task content has no write-path contract, while D291 and
  D299 require exact write targets for a delegated child, and T014 derives a delegated contract only from a
  deterministic plan text. Delegated task planning therefore uses `roadmap-task-plan`: the reviewer proposes exact
  files and restated criteria; the harness validates them (no directory, glob, absolute, parent or protected path;
  every accepted criterion restated), renders the plan section, checks that T014's deterministic parser agrees and
  seals the result. Only then is the task child derived with those exact paths. A refused contract stops for the
  owner and is not re-planned automatically.
- **Effects.** Plan proposal (T015 `propose`), delegated adoption (T015 `stage`, `preview`, `adopt`), task admission
  (T014 `submit` with the child), commit of accepted content (T014 `submit_commit`; harness-deterministic under its
  child, rechecked by T014's reference guard), check (T015 `submit_check`) and delegated closure (T015
  `submit_close`). Archive and succession are T015's closure effects. Every effect is idempotent by its operation
  key; typed refusals of the reused operations become an owner stop, never a retry.
- **Boundary verification.** `verify_child` runs inside the effect's own writer transaction: the child must exist with
  the right kind and an untampered subject, belong to a live run of the root under the latest authorization revision
  with an active T010 parent, name the phase inside the sealed scope and, for closure, the exact READY binding.
  Delegated adoption records `owner_delegated` knowledge with the child as actor and refuses activation; delegated
  closure stores `owner_delegated` scope with the child as parent, and `effect_guard` repeats the verification under
  the writer fence before each Git reference effect. Owner-confirmed paths, the exact READY, recovery renewal and
  D298 reference publication are unchanged.
- **Judge.** The parent carries the T009 delegation contract (enabled duties, `judge_reconsiderations`, duration
  ceiling, no grant dimensions). A judge request uses subject `roadmap:<parent>:<canonical subject>`, so T009 reads
  that contract; native judge inference is unqualified (D290), so the request escalates and the run stops for the
  owner with the exact request and ruling. A validated ruling of that subject is linked (`ruling_id`) to the
  resulting remediation proposal or adoption child and authorizes nothing by itself.
- **Background continuation.** `LocalSupervisor` calls `advance_all` before each claim. It resumes only RUNNING runs
  whose graph waits on settled harness jobs; owner stops are never continued; the graph CAS resumes a thread at most
  once, and the same operation identity reconciles a replay. Caps, bounds and the revocation guard apply on every
  step.

### Evidence

`tests/product/test_autonomous_journey.py` (11 cases; migrated SQLite, disposable Git with accepted structured
knowledge from the T015 fixture, scripted agents, the real supervisor, journal and graph runtime, product policy):

| Case | Result |
|---|---|
| Two-phase managed journey | Readiness queues the reviewer job, seals the report, READY, confirmation; P001 plan proposal, delegated adoption, task contract, delegated admission, commit, check READY, delegated closure with tag, archive and P002 successor; P002 adds a new task identity by delegated knowledge adoption and closes as final phase; COMPLETED with both closures `owner_delegated`, a clean checkout, five reviewer planning invocations and no new jobs or children after repeated notifications and a restarted service. |
| Background continuation | No continuation while a job is queued; one continuation after it settles; a paused run is never advanced by repeated hook calls; explicit resume continues. |
| Adoption authority | Missing and wrong-kind children refused at the adoption boundary; adoption without any child refused; out-of-scope phase and revoked run refused by `verify_child`; owner-confirmed manual adoption of the same preview still works. |
| Closure authority | Revocation after the delegated closure is queued: the closure job stops at the writer fence, no tag, no successor, job `RECOVERY_REQUIRED` for the existing recovery path. A check child is not closure authority and a stale READY binding is refused before any authorization row. |
| Segments | The two-phase production journey with segment limit 3 completes; every sealed operation of its thread is `COMPLETED`. |
| Prompts through fake CLIs | `roadmap-readiness` and `roadmap-task-plan` through the real CLI adapter with fake Claude and Codex processes: the launched schema equals the closed schema, the report is sealed, the task contract is validated and rendered. |
| Judge | Duties enabled: the parent carries the delegation contract; the T009 request stores exactly it and escalates with its ruling. |
| Caps | An invocation cap of 2 stops after the plan proposal and the task contract; a token cap stops on unknown usage before the second inference. Usage comes from the ledger rows of the delegated jobs, found through each child's operation key. |
| Readiness | A second readiness call for the same frozen revision creates no second reviewer job and reports the pending report, not a pending effect. |

The synthetic suite gained routing cases (task contract missing/refused, commit of accepted work, operational task
failure without retry, ruling linked to remediation and adoption): 140 cases. D300 and segmentation cases are kept.

Focused verification: the autonomous suites (151) and the affected suites (structured phases, phases, closure,
adjustments, project instructions, CLI agents, prompts, managed, managed API, permission lifecycle, judge,
orchestration, service diagnostics, storage API, configuration, Git) passed 782 together. Complete checks are in
[§7](#7-closure-checks).

Self-review corrections before the closure run: job states are `QUEUED`/`ACTIVE` (two queries used `RUNNING`),
the readiness reviewer job is not a pending checkout effect, and caps and writer settlement resolve the delegated
managed runs through the job idempotency keys (previously only commit children carried a run identity, so the
invocation cap would not have counted delegated inference).

Not covered: native providers, a running service or browser, real judge inference (unqualified, D290), crash of the
service process during a production closure (the T015 recovery suites keep covering closure recovery), quota or
authentication classification of production task failures (the adapters do not classify them; such failures stop
the run as operational failures and are never retried), installed-data conversion and release packaging.

## 7. Closure checks

`scripts/check --frontend` was executed once on the final diff: unittest 10 passed; Alembic no new upgrade
operations; pytest 3,126 passed, 2 skipped, 1 warning (the existing synthetic duplicate-ZIP entry), 29 subtests
passed; Node 275 passed; TypeScript/Vite build passed. `scripts/check-docs` checked 116 Markdown files with zero
errors and `git diff --check` passed. OpenAPI and the client types were regenerated after the last API change and
are unchanged since; message catalogs keep en/es parity.

Source disposition: complete locally and ready for technical review; not committed. The original checkout is on
`feat/p002-t016-autonomous-roadmap` from `91d3a74`; the T015 worktree is untouched. Integration into `develop`,
release 0.2.0 through protected `main`, distribution/publication and installation (recorded installed version
0.1.9) remain pending. The one-off queue stays empty.

## 8. Technical review findings and corrections

Technical review (2026-11-04) blocked integration with five findings on the uncommitted diff. All five are
corrected in this branch; D300 and the manual T014/T015 paths are unchanged. No schema, API or message change was
needed (still 93 tables; OpenAPI and en/es catalogs unchanged).

| # | Finding | Correction | Evidence |
|---|---|---|---|
| 1 | A valid `plan_adoption` child could pass the adoption guard for another proposal or draft of the same phase (the preview was computed after sealing; the guard checked phase and kind only). | Preparation is separate: `prepare_adoption` stages the proposal and computes the exact preview before the child is sealed; the child subject binds proposal operation and digest, draft, coverage, preview digest, accepted revision and expected phase version. Inside T015's adoption transaction, after the idempotent-replay check, `verify_child` compares those values with what is being adopted and `adopt` rechecks the proposal operation (PROPOSED, staged, same draft, digest and coverage). | `test_delegated_adoption_is_bound_to_the_exact_proposal_preview_and_revision`: a real child and a second valid proposal of the same phase → `delegated_adoption_mismatch`, accepted revision, definition and READY unchanged; replay of the original adoption under its key returns without a new effect. |
| 2 | Caps were checked only before queuing an effect; one T014 job can start several inferences; production usage always reported unknown tokens/valuation. | The fenced attempt start (`SQLiteManagedRepository.agent_started`) calls `inference_admission` for every inference of a delegated managed run (found through the job idempotency key = child operation key), including later ones inside the same job and after queuing. A refusal records `autonomy_admission_refused`, raises `AdmissionRefused` and `invoke_agent` stops without launching a process; the observation routes it to `LIMIT_REACHED` with its cause. `observed_usage` reads the existing ledger: invocation count, observed tokens from each selected capture (unknown when any is unknown) and valuation on the cap basis as known, unknown or incompatible (new reason `cap_valuation_basis_incompatible`); zero invocations are known zero. No T019 projection. | `test_invocation_cap_is_enforced_inside_a_job_that_needs_more_than_one_inference` (cap 3: the task job's executor takes the last unit and its reviewer is refused at admission; no reviewer process); `test_token_cap_reads_known_observed_usage_and_stops_on_unknown` (known 5 × 400 tokens reach the 2,000 threshold only after P001 closes; unknown stops before the second inference); cap unit cases for incompatible and unknown valuation. |
| 3 | Task state was derived from any run of the task code (manual or older) and failures without a class led to readmission. | Only runs admitted by task children of the active run for the same phase, task and task version are the run's own; their `ACCEPTANCE_READY` is committed only while the delegated authority is active, and `commit_task` rechecks that provenance. Another pending acceptance of the task stops for the owner (`foreign_task_acceptance`). A failed delegated run is a durable stop by evidence: admission refusal → `LIMIT_REACHED`; reviewer BLOCKED → `WAITING_FOR_OWNER`; revision limit → `LIMIT_REACHED`; stopped, interrupted or refused → `FAILED` (operational/policy; no quota/authentication classification exists, so none is guessed). Readmission happens only after an explicit owner resume acknowledged that failure, consuming `task_attempts`. | `test_prior_manual_acceptance_is_never_committed_by_delegation`; `test_operational_port_failure_stops_without_a_second_admission`; `test_failed_task_is_a_durable_stop_until_an_explicit_resume`; the task-attempt and no-progress bound cases now retry through explicit resumes. |
| 4 | The parser check of D301 discarded its result; criteria were matched by substring over joined text; protection used literal equality. | The objective comes from the accepted task content (removed from the prompt and schema); every accepted criterion must be its own exact item and no other item may contain one; text that could add fields (newlines, backticks, `**`, list or heading markers) is refused; paths must be canonical repository files (`targets.path`, no directory, `.`, `..`, glob or alias) not matching protected or harness-owned patterns (fnmatch, as T014); validation commands must match the profile's allowed prefixes. The parsed T014 contract is compared field by field (identity, title, objective, paths, criteria, commands, executor selection) and its digest is sealed; admission re-parses the plan text and refuses on any digest difference. | `test_delegated_task_contract_rejects_weakened_criteria_protected_paths_and_foreign_commands` (inverted and reworded criteria, injected field, directory, `AGENTS.md`, `docs/STATE.md`, `./` path, foreign command); `test_delegated_task_contract_is_refused_when_the_parser_disagrees`. |
| 5 | Final coverage used plan keys and the latest check. | Closure evidence is the READY check sealed by the closure operation (`check_operation_id`) and must pass every criterion of the phase. The observation adds requirement coverage over the accepted revision's relations: a requirement is covered only by a CLOSED phase with sealed READY evidence that addresses it, a passed criterion of that phase that is a criterion of it, or a task of that closed plan that addresses it. `completion` refuses without coverage data or with any uncovered requirement. | `test_all_phases_closed_without_requirement_coverage_is_not_completed` (both phases CLOSED, R002 covered by P002, R001 uncovered → `FAILED completion_evidence_incomplete`); `test_completion_requires_requirement_coverage_data_and_coverage`. |

Focused verification after the corrections: the autonomy suites passed 171 (144 synthetic, 27 journey); together
with the affected T014/T015, judge, CLI, prompt, managed, lease, permission, orchestration, diagnostics, storage API,
configuration, Git, accounting and engine suites, 909 passed. Complete checks: [§9](#9-closure-checks-after-review).

Not covered: the same limits as [§6](#6-integral-production-route); tokens and valuations are read only from
captures and complete valuations already in the ledger (synthetic captures in the tests; no real provider usage),
and a valuation basis incompatibility is tested at the cap rule, not with synthetic valuation rows.

## 9. Closure checks after review

`scripts/check --frontend` was executed once on the final corrected diff: unittest 10 passed; Alembic no new
upgrade operations; pytest 3,146 passed, 2 skipped, 1 warning (the existing synthetic duplicate-ZIP entry), 29
subtests passed; Node 275 passed; TypeScript/Vite build passed. `scripts/check-docs` checked 116 Markdown files with
zero errors and `git diff --check` passed. Source remains uncommitted on `feat/p002-t016-autonomous-roadmap`;
independent re-review, integration into `develop`, release 0.2.0, distribution and installation remain pending.

## 10. Remaining review blockers

Second review (2026-11-04): three paths not covered by the tests. All corrected; the §8 corrections and D300 are
kept. No schema, API or message change (93 tables; OpenAPI and en/es catalogs unchanged).

| # | Blocker | Correction | Evidence |
|---|---|---|---|
| 1 | `inference_admission` ran in its own transaction and checked only run state and caps; a queued delegated plan or check job could start the reviewer after the owner ended the T010 parent in the permissions panel. | Replaced by `admission_check`, executed inside `SQLiteManagedRepository.agent_started`'s writer transaction before the attempt row, ledger intent and operation are sealed. It checks the child is bound to the lineage's latest authorization, the T010 parent is active, the autonomous run is RUNNING (a pause holds new inferences; revocation or recovery ends them) and then the caps. A refusal commits only its reason (`autonomy_admission_refused` with `kind` `authority`, `state` or `cap`) and returns `AdmissionStop`; the journal raises `AdmissionRefused` and `invoke_agent` stops without a process or attempt. Authority refusals end `FAILED` (`delegated_authority_refused` or the guard's `authority_inactive`), never `LIMIT_REACHED`; caps stay `LIMIT_REACHED`; a pause-held job is retried after the explicit resume without counting as a replacement plan. Already started effects keep their recovery semantics. | `test_queued_delegated_job_does_not_infer_after_the_parent_is_ended` for a queued plan proposal and a queued phase check: no port invocation, no attempt row, persisted authority refusal, run `FAILED`. `test_pause_holds_the_next_inference_of_a_queued_job_and_resume_continues`: no invocation while paused, `state` refusal, resume completes both phases. |
| 2 | A failed `roadmap-task-plan` job left no sealed contract; observation saw `missing` and a later step could queue another reviewer. | The observation reads the durable outcome of the run's latest contract job for the task identity (through its child's operation key): missing, pending, proposed, refused, failed (admission class or operational) or uncertain (job `RECOVERY_REQUIRED`). A failed contract job stops `FAILED task_contract_failed` (cap → `LIMIT_REACHED`, authority → `FAILED`); it is re-planned only after an explicit owner resume acknowledges that job. | `test_task_contract_port_failure_is_a_durable_stop_without_a_second_reviewer`: a port failure in the contract job stops the run; three supervisor ticks and graph advances queue no job and invoke no reviewer. |
| 3 | The contract identity was `digest(task)` from the frozen plan and contracts were reused by root and code; a criterion change could reuse an older contract or acceptance. | `contract_identity` digests, from the current accepted revision, the task item, its active criteria (or the phase's when it has none), its phase, dependency and replacement links; the contract request carries those accepted criteria. Contracts and acceptances are selected only through this run's children for the same phase, task and identity. The admission child seals the identity and the contract digest; admission re-parses the plan text and compares the parsed digest, the child's digest and the current identity; commit selection and `commit_task` require the current identity. | `test_changed_criterion_never_reuses_the_previous_contract` (only C001 changes: new identity, contract `missing`, stale admission refused `task_contract_mismatch`); `test_changed_criterion_never_commits_the_previous_delegated_acceptance` (the earlier delegated ACCEPTANCE_READY becomes foreign; `commit_task` refuses; the run stays uncommitted). |

Focused verification: the autonomy suites passed 177 (144 synthetic, 33 journey); with the affected T014/T015,
judge, permission, Git, CLI, engine, orchestration, accounting, storage API and diagnostics suites, 763 passed.
Complete checks: [§11](#11-closure-checks-after-the-second-review).

Not covered: as in [§6](#6-integral-production-route) and [§8](#8-technical-review-findings-and-corrections).
A pause or revocation that lands while an inference is already running does not interrupt it here; revocation of
a running delegated writer still goes through the existing cancellation poll, and recovery of started effects
still requires stopped-writer evidence.

## 11. Closure checks after the second review

`scripts/check --frontend` was executed once on the final diff: unittest 10 passed; Alembic no new upgrade
operations; Node 275 passed; TypeScript/Vite build passed; pytest 3,151 passed, 2 skipped, 1 warning (the existing
synthetic duplicate-ZIP entry), 29 subtests passed and **1 failed**:
`test_managed_lease.py::test_stream_survives_real_sqlite_busy_during_one_renewal`, whose assertion expects exactly
one heartbeat renewal failure under `PRAGMA busy_timeout=1`. This is the same test the
[T015 record](P002-T015-phase-lifecycle.md#technical-review-corrections) documents as intermittent with an
unattributed cause. After the run it passed three times in isolation and the 18-case lease suite passed serially.
The attempt-start transaction now also reads the job keys and the delegated child for every attempt (blocker 1);
that small lengthening of the writer transaction is not excluded as a contributor to the extra renewal failure.
The complete suite was not repeated, as requested. `scripts/check-docs` checked 116 Markdown files with zero
errors and `git diff --check` passed. Source remains uncommitted; independent re-review, integration, release
0.2.0, distribution and installation remain pending.

## 12. Third review blockers

Third review (2026-11-04): two reproduced failures. Both corrected; the earlier corrections, D300 and the manual
T014/T015 paths are kept. No schema, API or message change (93 tables; OpenAPI and en/es catalogs unchanged). The
`autonomy_admission_refused` event payload gains `role` (JSON payload, no column). D301 records the rules.

| # | Blocker | Correction | Evidence |
|---|---|---|---|
| 1 | The executor of `P001-T001` wrote `app/main.txt` inside its contract and the owner paused before it returned; `admission_check` correctly held the reviewer and the run was `PAUSED`, but `resume` refused `resume_revalidation_failed` because the checkout held that same delegated work. | A held review is identified by persisted evidence (`storage/autonomous_runs.py::held_review`): the T014 run STOPPED at the reviewer by a `state` refusal of its latest job (event now records the refused `role`), settled attempts, last attempt the executor and its content evidence frozen in the last review cycle without a review. The observation reports `held_review`. The explicit resume accepts a non-clean checkout only when one held review verifies (`verify_held_review`: same evidence, run admitted by the active run of the root under the latest authorization with a live parent and task-child authority, frozen contract equal to the child's digest, current contract identity, no unfinished job, checkout base, fingerprint and changed paths equal to the evidence); otherwise it adds the refusal code. After the resume, `decide` routes `resume_review`: one journaled effect keyed by the persisted refusal queues T014's `resume` (revalidation, no `retry_executor`) on the same run under its existing admission child, with the same verification and a RUNNING run inside T014's resume transaction (`delegated` check). No child is sealed and no task attempt or progress unit is consumed; caps stay at the reviewer's admission. Executor-held pauses keep the earlier readmission. | `test_pause_between_executor_and_reviewer_resumes_review_in_the_same_t014_run`: refusal `role` reviewer and `kind` state; the change stays uncommitted; three supervisor ticks and graph notifications while paused change nothing; a repeated resume is refused by version; repeated notifications and a rebuilt service queue exactly one revalidation job on the same run; the reviewer prompt carries the kept `app/main.txt` change; executor invoked once for P001; `task_attempts` for P001-T001 stays 1; two admissions in total (one per phase); the same run's commit is COMMITTED with the executor's content; the journey completes. `test_foreign_change_after_a_held_review_refuses_the_resume[new_file, same_path]`: a foreign untracked file or a further edit of the contract file refuses with `git_baseline_clean` and `held_review_checkout_mismatch`, nothing queued, no reviewer; after removing the foreign change the same resume continues. |
| 2 | `ManagedRoadmapEffects.admit_task` and `_commit` compared the contract identity and digest before calling T014; an owner adoption of a changed C001 and the updated phase plan between those reads and T014's transaction let T014 queue the previous contract. | `SQLiteManagedRepository.submit`, `resume` and `submit_commit` take an optional `delegated` check that runs inside their writer transaction after the idempotent replay and before anything is created. The autonomous effects pass `verify_task_admission` (sealed `task_admission` child, phase and task, live authority via `verify_child`, the task-child permission named by the request, digest of the contract T014 freezes, identity recomputed from the accepted knowledge read by that session) and `verify_task_commit` (sealed `task_commit` child under live authority, the acceptance run admitted by this autonomous run for the phase and task with its frozen `task_delegated` contract equal to the admission digest, admission and commit identities equal to the current one, active task-child authority). Earlier caller-side comparisons remain only as early refusals. Stale identity or contract returns `owner_required` with the code (`task_contract_stale`, `task_contract_mismatch`, `acceptance_not_delegated`, `acceptance_identity_stale`) in the journal outcome and the WAITING_FOR_OWNER stop; authority codes stop FAILED as before. Manual and T010-delegated callers pass no check; Git publication guards are unchanged. | `test_t014_queue_transaction_refuses_a_contract_made_stale_by_a_concurrent_adoption`: the owner amends only C001 and adopts the updated plan from inside the intercepted `submit` before its real implementation; the identity and criteria changed, the phase plan was adopted (new version, planned), no task run or job exists for the key, the journal operation is COMPLETED with the refusal and the run waits with `task_contract_stale`. `test_t014_commit_queue_refuses_a_delegated_acceptance_made_stale_concurrently`: same interleaving at `submit_commit`; no commit job or record, the run stays ACCEPTANCE_READY, stop `acceptance_identity_stale`. `test_replayed_delegated_requests_return_their_recorded_jobs_without_a_second_effect`: replaying the recorded admission and commit requests with their keys returns the same jobs without invoking the check, and the commit completes once. |

The five new regressions were also run with the in-transaction calls and the `held_review` route disabled: all
five failed (one continuation missing, jobs queued for the stale contract and commit), and passed again once
restored. The temporary review reproductions were run before and after the fix (two failed, then all three passed)
and are not part of the repository.

Focused verification: the new and affected journey cases (8) passed; the autonomy, T014, T015, Git, permission,
judge, engine, orchestration, journal, lineage, storage API and lease suites passed 711 together; after the final
tidy-ups, autonomy, managed, Git and structured phases passed 322.

Not covered: the same limits as [§6](#6-integral-production-route), [§8](#8-technical-review-findings-and-corrections)
and [§10](#10-remaining-review-blockers). The checkout comparison of a held review is made just before T014's
transaction (Git is not part of the SQLite transaction) and T014's review loop captures evidence again before the
reviewer, so a change landing between the two is reviewed as part of the work, as in any T014 revalidation. A pause
held before the executor ran is still readmitted after the resume (consuming a task attempt), as before. A REVISE
verdict in the continued review stops the run (`allow_revision=False` in T014's revalidation), which the run
reports as a durable failure.


## 13. Closure checks after the third review

`scripts/check --frontend` was executed once on the final diff (2026-11-04): unittest 10 passed; Alembic no new
upgrade operations; pytest 3,158 passed, 2 skipped, 1 warning, 29 subtests passed, no failure or error (the lease
case `test_stream_survives_real_sqlite_busy_during_one_renewal` passed in this run; the lease and environment tests
are unchanged); Node 275 passed; TypeScript/Vite build passed. The earlier independent run with 97 failures and 26
errors from local-socket and process-inspection restrictions did not recur in this environment. `scripts/check-docs`
checked 116 Markdown files with zero errors; `git diff --check` passed and the untracked T016 files have no trailing
whitespace. OpenAPI, client types and message catalogs are unchanged. Source remains uncommitted on
`feat/p002-t016-autonomous-roadmap`; the T015 worktree is untouched. Final review, integration into `develop`,
release 0.2.0, distribution and installation (recorded installed version 0.1.9) remain pending.

## 14. Final review: held-review window

Final review (2026-11-04): the six regressions of [§12](#12-third-review-blockers), `scripts/check-docs` and
`git diff --check` passed independently. One failure was reproduced: after the explicit resume queued T014's
revalidation of the held run, a foreign overwrite of `app/main.txt` (a path the contract allows) landed before the
supervisor ran the job. `resume_review` had compared the checkout only when queueing; the persisted job said only
`revalidate`, and `OfflineEngine.resume`/`_review_loop` captured the checkout again and validated and reviewed that
capture. The reviewer accepted the foreign content, T014 committed it and the roadmap ended `COMPLETED`.

Correction: the continuation job is bound to the executor's frozen evidence. `SQLiteManagedRepository.resume` takes
an optional `expected_evidence` (base revision, fingerprint, changed paths; refused with `retry_executor`) and
stores it in the job request, so the binding survives a restart. The supervisor passes it to `OfflineEngine.resume`,
and `_review_loop` compares its first effective capture, the one that feeds validation and the review prompt, with
the binding before using it. A difference stops the run with stage `continuation` and the localized reason
`workflow.continuation_evidence_changed` (en/es). No validation runs, no reviewer is invoked and the files stay as
they are. The observation classifies that stop as `review_evidence_changed`. The run stops `FAILED
held_review_evidence_changed` with no automatic readmission. A later explicit resume needs a clean checkout, as
for any other failed task. The checks after validation, acceptance and publication are unchanged. Manual T014
revalidation passes no binding and keeps its semantics. Git capture is not made atomic with SQLite; the
correction checks which content is reviewed.

| Case | Evidence |
|---|---|
| Foreign edit between queueing and execution | `test_foreign_edit_between_continuation_queue_and_execution_is_never_reviewed_or_committed`. The queued request carries the held evidence. A newly constructed supervisor runs it, reading the binding from SQLite. The T014 run stops with stage `continuation`. The autonomous run is `FAILED held_review_evidence_changed`. No reviewer was invoked and no commit record exists. `app/main.txt` keeps the foreign text and `git status` shows it modified. Three further ticks queue nothing and seal no child. One executor; `task_attempts` stays 1. |
| Unchanged held review | `test_pause_between_executor_and_reviewer_resumes_review_in_the_same_t014_run` now also asserts the persisted binding; it still reviews, commits in the same T014 run with one executor and no further admission, and completes. |

The independent reproduction failed before the change (`COMPLETED`, two reviewers, foreign text committed) and
passed after it; it is not kept in the repository. With the engine comparison disabled, the new regression failed
(the run reached `ACCEPTANCE_READY`) and passed again when restored.

Focused verification: the held-review, foreign-change, stale-contract and replay selection passed 17. The journey,
roadmap, managed, managed API, engine, Git, structured phases, phases, lineage, lease, permission, orchestration and
journal suites passed 561. The acceptance matrix, offline end-to-end, run projection, accounting and CLI agent
suites passed 95.

Not covered: the limits of [§12](#12-third-review-blockers) except the closed window. A change made after
the bound capture and before the reviewer returns is still caught only by T014's existing checks after validation
and at acceptance and publication, which this correction keeps. No native provider, service or browser was used.

Closure checks: `scripts/check --frontend` was executed once on the final diff. Unittest 10 passed; Alembic
reported no new upgrade operations; pytest 3,159 passed, 2 skipped, 1 warning, 29 subtests passed, with no failure
or error; Node 275 passed; the TypeScript/Vite build passed. `scripts/check-docs` checked 116 Markdown files with
zero errors. `git diff --check` passed and the untracked T016 files have no trailing whitespace. The en/es message
catalogs gained one key each and keep parity; schema, OpenAPI and client types are unchanged. Source remains
uncommitted on `feat/p002-t016-autonomous-roadmap`; the T015 worktree is untouched. Final review, integration into
`develop`, release 0.2.0, distribution and installation (recorded installed version 0.1.9) remain pending.

## 15. Independent final re-review

The reviewer verified that the queued continuation retains the executor evidence, that the supervisor passes it
through after restart, and that the engine checks the capture used for validation and review before using it.
Seven focused journey cases passed independently, including the foreign edit after queueing, the unchanged
continuation, the two earlier checkout-mismatch cases, the T014 transaction races and idempotent replay.
Documentation and whitespace checks passed. The implementer's final complete synthetic check is recorded in
[§14](#14-final-review-held-review-window). The full suite was not repeated during this final re-review.
The source passed review. The owner authorized the source commit, merge into `develop` and push of `develop`
conditional on successful review. Release 0.2.0, distribution and installation remain pending.
