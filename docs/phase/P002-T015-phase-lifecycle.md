# P002-T015 — Phase lifecycle and successor planning

## Local contract and delivery

Owner-authorized local implementation, 2026-11-03. Branch `feat/p002-t015-phase-lifecycle`,
independent worktree `/private/tmp/my-harness-p002-t015`, from develop `c707986` (T014 integrated at
`72c8a8c`; subsequent accepted visual-direction documentation is baseline only).
The original checkout is preserved. No T017/T018 implementation belongs to this task.

Scope: manual structured-knowledge phase planning/adoption, exact checks, reconciliation,
closure/archive and roadmap-only succession, preserving documentary compatibility, questions,
amendments, abandonment and read-only history. Accepted SQLite revisions own knowledge; operational
phase states remain operational. Reuse existing supervisor, journal, frozen context, commands,
judge contracts, permissions and recoverable documentary delivery. No autonomous loop or T016
gate defaults, global inbox/map, installed-data conversion, real providers or new dependencies.

Acceptance: a synthetic managed HTTP journey through structured planning/adoption, check and
confirmed closure; stale evidence and authority rejection; coverage/scope/dependency validation;
remediation lineage; deterministic versus reviewer attribution; recoverable tag/export/commit/results;
byte-preserving artifacts; final and successor phases; manual regression and historical consultation.
Manual proposals require an independently confirmed exact preview and CAS; no model adopts itself.

Delivery: reviewed source → develop → release 0.2.0 through protected main → verified distribution
→ installation. Source implementation and verification are tracked separately from technical review
and each delivery stage. Commit, merge, push, release, distribution and installation remain pending
and unauthorized. The one-off queue stays empty.

Threats: TM05 (phase evidence/closure), TM10 (knowledge/document authority), TM12 (uncertain effects).

## Implementation and review map

- `storage/structured_phases.py` provides accepted-roadmap activation, scoped planning previews/adoption,
  separate reviewer-candidate staging, versioned operational definitions, criterion coverage and accepted task
  evidence. Generic documentary creation/amendment/reconciliation cannot supply authority for structured projects.
  Product amendments use the existing owner knowledge editor followed by a new phase-plan confirmation.
- Reviewer planning and phase checks use `services/phase_lifecycle.py`, `managed-phase@1`, frozen canonical context,
  the existing supervisor and accounted invocation journal. Deterministic controls run before the reviewer. Typed
  HTTP check results expose classification, exact bindings, actual participation/model/effort/provider and Harness
  attribution. Validated previews supply T009 planning-choice inputs; explicitly classified planning ambiguity can
  supply blocked-check inputs. No judge ruling adopts a plan or waives READY.
- Task acceptance must match the current accepted task identity/version, task criteria and dependency links.
  Reconciliation candidates cover unmet phase criteria; withdrawn tasks need a replacement link. Existing D296
  persistent family consumption and smallest ceiling remain authoritative. Manual batches retain task-only scope,
  bind knowledge and become invalid after plan adoption or knowledge changes.
- `storage/closure.py` dispatches structured preparation to a separate SQLite-based producer. The old Markdown
  roadmap/parser/writer is not used for structured authority. Closure snapshots seal the complete domain revision,
  ownership, evidence, artifact bytes, successor definition and generated files. D294 export intent/commit/target/
  completion records accompany the existing phase operation and commit/tag intents. No extra scheduler or ledger.
- Fresh origin/scope/fingerprint/validity/knowledge checks run under the SQLite writer through tag and Git reference
  effects. Repeated confirmations reconcile the same operation. Explicit stopped-writer confirmation and renewed
  confirmation of the original binding are required after an interrupted closure. The tag stays on the evaluated
  HEAD and the archive/views use one commit. Successor creation and the terminal result share a transaction.
- Nested binary artifacts, including a synthetic 1 MiB file, retain exact bytes. The documentary text budget does
  not truncate or prohibit sealed archive bytes/domain snapshots; ordinary generated documents retain D294 limits.
  Case aliases, links, hardlinks, dirty targets, traversal and archive collisions refuse writes before a tag.
- Operational status is separately identified by `harness:phase-view-1` decoration; ordinary task/export boundaries
  retain the current lifecycle view. Explicit import reports and omits operational decoration while preserving raw
  input, so it cannot manufacture runs, approvals or operational state. Canonical renderer output and historical
  snapshots/intents are not rewritten. Generated targets are never compared with SQLite for drift.
- Existing phase pages provide structured activation, coverage editing, reviewer proposal/staging, exact adoption,
  checks, closure/abandonment and historical evidence. Documentary-only controls remain in their compatibility lane.
  OpenAPI and TypeScript types are regenerated by the README procedure; messages and UI keys have en/es parity.

No model, migration or dependency change: schema remains `0037_task_lineage`, 86 tables. The accepted contracts
TM05/TM10/TM12 and D269–D273/D282–D283/D286–D288/D290/D294/D296 remain the basis; D298 records representation and
integration details. T016 gates G11/G12/G17, native-provider qualification, installed conversion, the inbox and
map are not implemented here. Missing/fabricated delegated authority is refused; T015 creates no autonomous grants.

## Synthetic acceptance evidence

`tests/product/test_structured_phases.py` adds 47 cases over disposable repositories, migrated SQLite and fake
ports. Its HTTP journey activates accepted P001, requests a reviewer proposal, stages it, previews/adopts separately,
executes and commits a synthetic task, checks READY, confirms closure, retries the same confirmation and observes
P002 ACTIVE pending planning. A separate case completes the final phase without inventing a successor.

Additional cases cover READY/REVISE/BLOCKED, pending plans/tasks, insufficient evidence and missing required docs;
code/knowledge/question staleness; exact preview/CAS/idempotency; criteria/objective weakening and reviewer
self-adoption boundaries; cyclic dependencies; task-version evidence; remediation lineage/shared budget; manual
batch invalidation; abandonment; ownership/path attacks; and generated-view explicit import without operational
history adoption. The old phase/closure/adjustment suites remain regression evidence.

Fault injection interrupts tag, partial export, commit and result persistence. Recovery confirms the writer stopped,
reopens the repository/database engine and reconciles the identical sealed commit/tag and one successor without
another reviewer invocation. A separate lost-inference-receipt case stays RECOVERY_REQUIRED and is never reissued
by a restarted supervisor or by replaying the original submission. Revoked, expired, forged-origin/parent,
wrong-scope and empty-actor closure authority never reach a tag or archive writer.

Focused verification before closure: original phase suites **76 passed**; expanded phase/knowledge/lineage/context
selection **204 passed**; judge suite **141 passed** with synthetic CLIs; pre-closure structured suite **39 passed**.
The first restricted judge run failed because the environment denied its local process socket. Inspection isolated
that restriction; the authorized local fake-process run passed. No native provider, network install or project
service was used. Closure and correction results are recorded below.


## Complete check, corrections and final disposition

`scripts/check --frontend` was executed once at task closure, with local process inspection permitted for
synthetic subprocess/relay tests. Results:

| Check | Result of the complete run |
| --- | --- |
| unittest | 10 passed |
| Alembic/model parity | No new upgrade operations |
| pytest | 2,950 passed; 4 failed; 2 skipped; 29 subtests passed; 1 warning |
| Node | 275 passed |
| TypeScript/Vite | Passed |

All four failures were inspected and corrected in this task:

1. The central-knowledge mutation guard found direct knowledge access in the phase repository. Root/CAS-checked
   candidate reads and confirmed adoption/staging now go through the existing exchange service's bounded
   `PhaseKnowledge` composition. The architectural allowlist is unchanged; repositories receive no raw writer.
2. The service diagnostic guard found a Spanish operational-view literal. All lifecycle decorations now use
   the en/es catalogue with the sealed work language.
3. The project-instructions coverage list did not include the new phase-planning template. It now tests that
   template too, including its explicit instruction delimiter; historical templates/catalogues are unchanged.
4. The graph import guard found a consumer import outside the composition root. `managed_runtime.run_phase_graph`
   now supplies the lazy graph boundary, preserving cold imports without LangGraph and the existing scheduler.

The immediate correction selection passed **131 tests**. The wider affected phase/knowledge/lineage/context,
service-diagnostic and architecture selection then passed **302 tests**. The final source selection passed
**166 tests**, including all **47 new structured cases**, managed HTTP and the four previously failing guard
suites. Selections overlap and are not additive. The complete suite was not repeated after corrections, honoring
the requested single complete run; its four observed failures all pass in the subsequent targeted checks.
The existing two skipped cases and synthetic duplicate-ZIP warning remain explicit.

Final refinements also preserve historical task contracts after later accepted changes, permit operational
abandonment of a withdrawn canonical phase, expose stale code on HTTP reads, distinguish an observed reviewer
response from an unknown failed attempt, and verify the active job/owner/lease/checkout fence before each archive/export write and through Git effects.
Revocation between targets stops subsequent writes. Plan adoption preserves unanswered questions and BLOCKED
status; HTTP reads preserve the recovery action for expected partial writes of a sealed interrupted closure.
Loss of the writer fence prevents a tag/archive write and leaves the checkout lock for explicit recovery.
Plan previews expose dependency, replacement and task-criterion bindings. Planning prompts select only scoped
canonical sources (including task criteria), without copying unrelated roadmap knowledge outside the frozen
context receipt boundary. OpenAPI/client types were regenerated after the nullable participation result; the final TypeScript/Vite build
passed. Final `scripts/check-docs`: **114 Markdown files, zero errors**. Final `git diff --check`: **passed**.
The final frontend recheck passed **275 Node tests**; the final TypeScript/Vite build passed (the existing large
chunk advisory remains non-fatal). Source inspection includes the API, service/graph/knowledge import boundaries,
sealed intents and recovery guards, and confirms an unchanged clean original checkout.

**Source disposition:** implemented locally, checked and ready for independent technical review. No review
approval is claimed. Branch `feat/p002-t015-phase-lifecycle`, worktree `/private/tmp/my-harness-p002-t015`,
base develop `c707986`. The original checkout remains clean on develop and the accepted T017/T018 direction is
unchanged. No source commit, merge or push was made. Review/source commit → develop → release 0.2.0 through main
→ distribution/publication → installation remain separate pending stages. ONE_OFF_TASKS remains empty.

**Qualification limits:** synthetic HTTP/process/Git/SQLite evidence and frontend build/Node checks; no native
provider qualification, browser visual smoke test, running project service, harness execution on this repository,
release/package distribution or operator installation. T016 delegation/bounds and T017/T018 interfaces remain
outside this implementation. There are no known uncorrected test failures from the complete run.

## Technical review corrections

The review reproduced three defects in the local T015 source. This correction keeps the same worktree,
operation formats, API and delivery route.

- **Published closure recovery.** Recovery admission checks whether Git can prove the original sealed commit
  is reachable. A published result uses the original closure snapshot and verifies the exact commit object,
  archive and export blobs, and sealed tag reference under the writer fence. Settlement records export receipts
  for the original revision and creates the successor from the original preview. A later accepted revision
  stays current. A later working copy edit stays in place. Recovery can repair the original index when HEAD
  still points to the sealed commit and the index still matches the original baseline. Unpublished effects
  continue to require current authority, including during partial export and at reference publication.
- **Roadmap archive history.** The closure preview and later generations render links for all archived phases
  from persisted outcomes. Regression journeys cover two closed phases and a mix of abandoned and closed
  phases. They check a successor task commit, a later explicit regeneration, and import that omits the
  operational decoration.
- **Structured planning output.** A closed schema for the structured template requires the six fields the
  consumer validates, including the knowledge proposal, coverage, and `plan: null`. Task items describe D284
  content and provenance. Fake Claude and Codex processes verify the frozen contract at launch and return a
  proposal that reaches PROPOSED, staging and separate owner adoption. The documentary schema retains its
  existing plan shape and historical prompt snapshots retain their frozen contracts.

Independent technical re-review and source integration remain pending.

The affected suites passed 244 tests, including six new regression cases. The requested full run on the
corrected source reported 10 unittest passes, Alembic parity, 2,967 pytest passes, two skips, 29 subtests
passed, 275 Node passes and a successful TypeScript/Vite build. Pytest reported one warning and one failure
in the existing lease test `test_stream_survives_real_sqlite_busy_during_one_renewal`. The trace showed a
SQLite lock while recording the start of a task validation. A serial run of the lease suite reproduced a
renewal failure in that case with the other 17 passing. The case passed when run alone on the corrected
source. The base `c707986` passed the isolated case and the 18-test lease suite in a temporary checkout.
These results establish intermittent behavior on the corrected source. They do not establish its cause
or a clean full run.

Documentation validation passed with 114 Markdown files and zero errors. The diff whitespace check passed.
Verification used synthetic processes and repositories. The correction leaves schema and public API contracts
unchanged. Source remains uncommitted and pending technical re-review.

## Tag publication review correction

The owner reported that the three prior corrections passed re-review and that 71 structured phase and lease
tests passed. A new finding reproduced an obsolete tag after worktree bytes, the index, or HEAD changed
between persistence of the tag intent and its publication. The new regression reproduced all three cases.

The Git adapter checks the sealed closure fingerprint immediately before creating a new tag. The fingerprint
includes the base revision, worktree tree and index tree. The same Git reference transaction verifies HEAD
and creates the tag only if the reference is absent. A mismatch settles the operation as STALE before archive
publication and preserves the owner's files, index and commits. Git cannot lock arbitrary worktree files against
external writers. The final capture is the observation boundary for the index and worktree, and the Git
transaction provides the atomic HEAD check.

An exact existing tag remains reconcilable. Recovery of a partial archive still compares the observed tree
and target bytes against the sealed commit plan. Recovery of a published archive still verifies its exact
commit, tag and blobs before settling the historical result.

Focused verification passed 134 cases across structured phases, closure, phases and phase adjustments.
New cases cover worktree, index and HEAD changes after the intent, a HEAD move after the final capture,
and a foreign edit during partial recovery with an existing tag. The selection also includes successful
partial recovery and published recovery after later knowledge adoption.

The final `scripts/check --frontend` passed on the corrected source. Unittest passed 10 tests and Alembic
reported no new upgrade operations. Pytest passed 2,973 tests and 29 subtests, with two skips and one warning
from the synthetic duplicate ZIP entry. Node passed 275 tests and TypeScript/Vite built successfully.
`scripts/check-docs` checked 114 Markdown files with zero errors and `git diff --check` passed.

The intermittent lease failure did not recur in the final run. The owner verified that the test's
`PRAGMA busy_timeout=1` survives return of the connection to the pool. Its role in the earlier failures
remains unproven. The correction leaves lease code and its test unchanged. The original checkout is clean.
The diff awaits technical review, source commit and integration.

## Independent technical re-review

The reviewer verified the final checkout capture and the atomic HEAD check before creating a new tag.
The focused selection passed 21 tests covering tag publication, partial and published recovery, roadmap
archive history and native planning with synthetic clients. Documentation and whitespace checks passed.
The implementer's full check on the final product source passed as recorded above. The earlier intermittent
lease failure remains unattributed. The owner authorized the source commit, merge into develop and push
of develop after successful review. Release 0.2.0, distribution and installation remain pending.
