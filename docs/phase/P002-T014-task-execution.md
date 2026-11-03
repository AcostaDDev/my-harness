# P002-T014 — Task execution and exact acceptance integration

Branch `feat/p002-t014-task-execution` starts at `5e0b804` on `develop`.
The task contract is to retain manual confirmation and share the managed task boundary with scoped delegated admission.
Each attempt freezes authority and context, and validation and review bind code and adopted knowledge to the required
document manifest. Export and commit reconcile through durable identities and receipts. Synthetic tests cover success,
bounded correction, denied authority, evidence drift, interrupted effects and duplicate dispatch.

| Delivery stage (D235/D242/D253) | Status |
| --- | --- |
| Local source for technical review | Completed; independent technical re-review passed |
| Source commit | `624631e` |
| Integration into develop | Accompanying authorized merge |
| Push | Authorized for develop; verify remote tip after merge |
| Phase 0.2.0 release through main | Pending |
| Verified distribution publication | Pending |
| Installation | Pending |

## Local evidence

The T013 consumption boundary now exposes the sealed commit receipt and per-target write receipts.
The current-delivery predicate checks the commit and exact path/content digest coverage against the same
intent before reporting delivery. Synthetic Git tests cover complete delivery, ownership replacement and
a completion record without effect receipts. This covers persisted export evidence relevant to TM12.
It does not establish the current state of the checkout.

The shared manual/delegated graph, frozen attempt authority and scoped tooling (TM01/TM10), exact acceptance
at the task effect boundary and recovery across the combined task effects (TM12) remain open. The owned-project
task entry guard stays in place. No real provider, running service, installed conversion or native qualification
was exercised.

Focused offline knowledge-document tests passed (46). The full offline check passed unittest (10) and
Alembic, and pytest reported 2,759 passed, 97 failed, 26 errors and two skipped. Process inspection and
relay tests encountered permission errors, including access to `/bin/ps`. A clean full-suite result is
unverified. The documentation check passed with 112 files and zero errors.

## Managed commit recovery evidence

Explicit stopped-writer confirmation now preserves accepted history for an interrupted task commit with a
sealed intent or recorded outcome and settled invocations. The managed job still records the interruption.
A pending commit excludes inference retry. The existing commit dispatch reconciles the same operation ID.
Synthetic repositories exercise interruption before the commit object, before the ref move, and after
the ref move. Each case checks preserved acceptance, rejected inference retry and one final commit.
The focused Git and knowledge-document review suites passed (48 tests).

The follow-up full offline check passed unittest (10) and Alembic. Pytest repeated the previous totals
(2,759 passed, 97 failed, 26 errors, two skipped) and the same failing files: tool bridge, judge, CLI
diagnostics and start command. The log again contains process-inspection and relay permission failures.
A clean full-suite result remains unverified. Documentation passed with 112 files and zero errors.

## Git effect boundary evidence

The managed task Git writer recaptures the checkout after creating the sealed commit object, immediately before
the ref CAS. Two synthetic fault injections edit the working tree after object creation, with and without staging.
Both invalidate the persisted intent, preserve the local edit and leave the reference at its original revision.
This strengthens code evidence at the Git effect boundary (TM12). It does not bind domain revision, renderability
or export receipts to task acceptance. The focused Git and knowledge-document review suites passed (50 tests).

The full check passed unittest and Alembic. Pytest reported 2,761 passed, 97 failed, 26 errors and two skipped.
The two added cases passed. Failures and errors remained in the same four files and counts as the preceding run,
with recurring permission errors. The full suite remains unverified. Documentation passed with 112 files and
zero errors, and the diff passed whitespace validation.

## Manual admission and commit with an existing delivered generation

Manual task admission now accepts owned-document projects when T013 has delivered the current adopted revision
and manifest. The run journal binds the exact export intent ID. The frozen profile protects generated targets.
Before task execution, after review and before commit dispatch the supervisor checks the current receipt,
export-commit ancestry, index and local target bytes. Stale evidence stops dispatch and preserves the checkout.
Pending commits with stale documentary evidence are quarantined for recovery. The legacy document regeneration
step is bypassed for owned targets, and mechanical overrides cannot change those targets.

The synthetic HTTP journey submits a task, waits for acceptance, confirms the commit and repeats the confirmation.
It produces one commit after the documentary delivery. Repository-level cases also check duplicate admission,
no second dispatch and invalidation after either a local document edit or a new adopted revision. These cover
a subset of TM12. The earlier note that all owned-document task entry remains guarded is superseded by this lane.
Task-driven export and coordinated recovery, the shared graph and delegated admission, and attempt-level
authority integration (TM01/TM10) remain open. The four focused suites passed with 103 tests.

The full offline check passed unittest and Alembic. Pytest reported 2,765 passed, 97 failed, 26 errors and
two skipped. All four additional cases passed. The failing files and counts repeated the preceding full
check, including permission errors in process and relay checks. A clean full-suite result remains unverified.
The documentation check passed with 112 files and zero errors. The reviewed diff passed whitespace validation.

## Documentary authority at the Git reference update

The managed Git task writer checks the frozen documentary generation and current job fence under the SQLite
write barrier through the Git reference CAS. Checkout recapture still precedes the CAS. Knowledge adoption
and ownership changes cannot interleave with the authority check and the reference update. Reconciliation
first recognizes a reachable sealed commit; an advance in documentary authority does not erase an effect
that already occurred. The documentary path still requires an existing completed T013 delivery.

Synthetic faults advance the adopted revision after the commit object is written and, separately, after
the reference has moved but before recording its receipt. The first invalidates the intent and retains the
work; the second reconciles the same commit after explicit stopped-writer recovery without further inference.
This adds TM12 evidence. It leaves the shared graph, delegated admission, attempt authority and task-driven
export open.

The five focused suites passed (154 tests). Documentation passed (112 files), and the diff passed whitespace
validation. Full offline unittest and Alembic passed. Full pytest reported 2,767 passed, 97 failed, 26 errors
and two skipped. Both new cases passed. Failures and errors repeated the preceding file distribution, with
process and relay permission errors. A clean full-suite result remains unverified.

## Versioned dispatch of the delivered-manifest lane

The managed scheduler now routes owned-document task execution through `managed-task@1`. Its node calls
the existing task engine and retains the managed journal as the authority for history. The node gives each
agent invocation a deterministic operation key; the fenced attempt transaction binds the existing usage
invocation, current adopted revision and export intent. The HTTP test verifies graph completion and the two
settled invocation operations. A fault between executor output and persistence leaves partial work and an
unsettled operation with the job in recovery. The scheduler does not redispatch it.

The lane still consumes an existing completed delivery. Delegated admission, canonical context and broker
integration, task-driven export and coordinated recovery are open. T013's standalone writer currently claims
the checkout lock itself and refuses changes outside its generated targets. A task integration needs to reuse
the already-claimed writer and seal task code and generated targets together under the accepted evidence.

The first full check exposed regressions in the orchestration import boundary and service text catalog.
The runtime now injects the graph callback, and the diagnostic has English and Spanish catalog entries.
The corrected focused check passed (134 tests), as did documentation, unittest and Alembic. The corrected full
pytest run reported 2,768 passed, 97 failed, 26 errors and two skipped. The import and catalog checks passed.
The remaining failures repeated the preceding four-file distribution with process and relay permission errors.
A clean full-suite result remains unverified.

## Task-generated delivery, scoped attempts and delegated admission

The managed HTTP path now runs with or without a current T013 delivery. With no current delivery, it
seals a clean baseline and renders the adopted revision and manifest. The reviewer receives the generation
identity, revision hash, manifest and target digests. The managed commit pairs the export and commit intents.
The task writer uses the T013 target replacement guard under its current fence and publishes the reviewed
code and required documents in one commit. Target observations persist under the export identity and the
completion receipts settle in the commit outcome transaction. Standalone delivery refuses task intents.

The task graph passes explicit provider identities to the canonical context builder, seals permission
boundaries for the reviewer and executor and binds the existing scoped broker for exact qualified reviewer
clients. The synthetic HTTP reviewer checks that an allowlisted query without a grant is denied. No new
native qualification is inferred. The synthetic delegated admission checks an exact writable file and a
live child and parent authorization at admission, attempt sealing and publication. A revoked parent stops
dispatch without starting an agent. The owned-document correction cases verify a local correction limit
and a persisted gap linked to the review. The existing owner decision path supplies a denial and the next
frozen executor boundary refuses before launch.

Faults after a target write and after the Git reference update recover using the same commit intent, with
no repeated inference or extra commit. The HTTP case checks repeated confirmation and exact generated
files. Prior documentary authority and checkout drift cases remain regressions. These checks cover portions
of TM01, TM10 and TM12. Native executor broker qualification, automated typed gap resolution, and failure
lineage across a change of task identity remain unverified.

The first full check found a knowledge-service import-boundary regression. Knowledge reads and render
preparation were moved into the knowledge delivery service. The corrected focused run passed 329 tests.
Documentation (112 files), whitespace validation, unittest and Alembic passed. The corrected full pytest
run reported 2,775 passed, 97 failed, 26 errors and two skipped. The import-boundary regression passed.
The remaining failures repeated the previous four-file distribution, including process-inspection and
relay permission errors. A clean full-suite result remains unverified.

## Closure of owner gap continuation and task replacement lineage

The earlier pending gap and lineage notes are superseded by this section. Both criteria have local source
and synthetic evidence. Technical review and all delivery actions remain pending.

| Criterion | Effective implementation and synthetic evidence |
| --- | --- |
| Typed owner gap resolution | A settled question request binds attempt, review cycle, code fingerprint, frozen contract/context and documentary generation. The owner records one clarification per question by event ID and request hash with an explicit expiry. The endpoint validates the current binding outside the model and cannot grant capability or product authority. |
| Effective continuation | The managed run action consumes a resolution once for a job. A new runtime session loads the same events. The new attempt freezes the clarification, canonical context and permission snapshot. Scope, source evidence, expiry and revocation are checked before the next attempt is sealed. Publication also rechecks the resolution. |
| Refused and repeated decisions | HTTP tests cover a forged request fingerprint, an unresolved continuation, a forged delegated origin, a second answer, revocation before admission and immediately before attempt sealing, expiry and changed source code. Rejected cases retain work and start no new inference. The same continuation key returns the same job. A revoked answer blocks publication. |
| Persistent task lineage | The owner approved D296 during this session. Schema `0037_task_lineage` adds the acyclic task-to-task `replaces` relationship, with irreversible adopted edges. Its connected family shares executor consumption and the smallest persisted local ceiling. Old catalogue schemas remain frozen and `knowledge.draft.apply@2` supports the new relation. |
| Budget under a new identity | A graph task consumes one correction, a replacement task starts in a new repository session with only the remaining executor allowance, and further retry starts no inference. A second test adopts replacement after the original budget is exhausted and reopens the database before checking refusal. An unrelated task keeps its own budget. |
| Storage and public contracts | Migration round trip preserves previous revision hashes and protection triggers. Downgrade refuses replacement evidence. OpenAPI and generated types include owner gap routes and the new relation. The owner knowledge editor exposes the relation with English/Spanish labels. No new tables are introduced. |

The gap API accepts owner clarification within the already adopted intent and frozen task contract.
A changed requirement or durable product decision still requires the existing owner knowledge adoption
path. The clarification endpoint accepts no judge ruling or delegated origin, so it does not broaden FL05
delegation. Permission grants retain their separate persistent lifecycle.

Threat evidence covers injected answer text as prompt data with frozen contract and capability scope (TM01),
binding and revocation checks before a fresh attempt (TM10), and exact evidence and persistent budget
enforcement across continuation and task identity (TM12). Source code and documents stay under the same
managed writer and acceptance/commit guards exercised by the preceding journeys and recovery tests.

The two final criteria use `test_http_gap_clarification_is_bound_and_applied_once` and
`tests/product/test_task_lineage.py`. Regressions include the normal HTTP journey without current delivery,
task export interruption, lost Git receipt, duplicate dispatch, bounded correction and denial.
Native client/provider execution, new native qualification, phase lifecycle, autonomous roadmap admission,
installed conversion, release/publication and installation were not exercised. All fixtures remain synthetic.

## Final verification and delivery disposition

The two final criteria passed their focused journeys. The broader affected suites passed 409 tests, and
the schema/API/recovery follow-up passed 118 tests (overlapping suites, not additive totals).
The first full restricted check found two assertions still expecting schema `0036`; those now expect
`0037`. Its other 97 failures and 26 errors were in the same process/relay suites as earlier checks.

The authorized offline `scripts/check --frontend` was repeated with local process inspection available.
It passed completely. This supplies direct evidence separating the process restrictions from regressions.

| Check | Final result |
| --- | --- |
| unittest | 10 passed |
| Alembic/model parity | No new upgrade operations |
| pytest | 2,909 passed, 2 skipped, 29 subtests passed |
| Node | 275 passed |
| TypeScript and Vite | Build passed |
| Documentation | 112 Markdown files, zero errors |
| Reviewed diff | Whitespace validation passed |

Pytest reported one warning from the synthetic duplicate-entry ZIP tampering case. The two skipped tests
remain omitted. No native provider/agent qualification, real project execution or operational installation
is claimed. Source, model/schema, public API, generated client and English/Spanish parity are included
in the same diff.

P002-T014 is implemented and verified as local source, ready for independent technical review on
`feat/p002-t014-task-execution` from `5e0b804`. The repository has no T014 source commit.
Source commit, integration into `develop`, push, phase 0.2.0 release through `main`, verified distribution
publication and installation remain separate pending delivery stages under D235/D242/D253.

## Technical review correction — single-identity correction budget

The review reproduced a D296 violation in the singleton family path. Filtering by run ID discarded earlier
executor intents and ceilings for the same task identity. This correction belongs to P002-T014 on
`feat/p002-t014-task-execution` and retains the source-review and D235/D242/D253 delivery route above.
The regression fixtures use an owned-document project with a current T013 delivery, repeated normal
admission through the managed graph, and a reopened database. Verification is recorded below.

The four new managed-graph regression variants failed before the correction, reproducing missing prior
consumption and loss of the smaller admission ceiling. The run-ID filter and its parameter are removed.
Admission now seals the smallest ceiling from all existing runs of the same identity or replacement
family. The supervisor and the fenced attempt transaction read that same complete budget.

Regression coverage includes one or two prior executor attempts, unchanged or widened policy, a new
admission key, reopened SQLite connections, the current T013 delivery and the managed task graph. An
exhausted identity starts neither executor nor reviewer. A partially consumed identity uses only its
remaining executor attempt. A separate identity without replacement links retains its own allowance.
An additional test bypasses the supervisor and confirms that fenced attempt admission rejects the
exhausted budget without creating an attempt or usage intent, rolling back the intermediate history update.

Focused verification passed 353 tests, including task lineage, manual HTTP admission, gap clarification,
export and Git recovery, permissions, frozen context, journal and accounting regressions. The correction
changes no model, migration, public API or catalogue contract. Independent technical re-review remains
pending, together with the separately recorded source commit and delivery stages.

The single closing `scripts/check --frontend` run used local process inspection and passed unittest
(10), Alembic parity, Node (275) and the TypeScript/Vite build. Pytest reported 2,913 passed, 2 skipped,
29 subtests passed and one failure in the existing three-scenario metrics fixture. No process or relay
permission failures occurred. That fixture had relied on a fresh budget per run to admit three executor
intents under a two-execution ceiling. It now explicitly allows three intents and asserts their shared
consumption. This changes only the fixture's declared budget, preserving its cancellation, failure and
duplicate-terminal assertions.

Final focused verification, including the entire metrics file and the budget/HTTP/gap/export/recovery
regressions, passed 380 tests after that fixture adjustment. The complete suite was run once as requested
and was not repeated after the test-only adjustment. Its log is preserved locally at
`.local/check/p002-t014-budget-full.log`; the final focused result is in `.local/check/pytest.log`.
Documentation and whitespace checks passed. The singleton reset finding is corrected and ready for
technical re-review. All previous local source and pending delivery states are retained.

## Independent technical re-review and authorized delivery — 2026-11-03

Independent re-review verified the singleton correction, including persistence across sessions, partial
consumption, the smallest recorded ceiling, unrelated task budgets and fenced attempt refusal.
The metrics fixture adjustment retains its cancellation, failure and duplicate-terminal checks with
an explicit three-execution budget. No outstanding relevant technical finding remains.

The reviewer reran the focused lineage/metrics suites (36 passed), followed by the complete offline
`scripts/check --frontend` with local process inspection available. Unittest passed (10), Alembic/model
parity passed, pytest passed (2,914 tests, 2 skipped, 29 subtests, one synthetic ZIP warning), Node passed
(275) and TypeScript/Vite built successfully. Native provider qualification and operational installation
remain outside this evidence.

The owner explicitly authorized the source commit, merge into `develop` and push of `develop` after
successful review. Those delivery steps are pending at this pre-commit record. Phase 0.2.0 release through
protected `main`, distribution/publication and installation remain separately pending under D242/D253.

## Source integration record — 2026-11-03

Reviewed source commit `624631e` is integrated into `develop` by the accompanying merge, from
`feat/p002-t014-task-execution`. The merge updates current task/delivery tracking and removes one trailing
blank line in `storage/task_lineage.py` detected when checking newly tracked files. Product behavior is the
same as the completely verified source. Documentation and the full staged diff are checked before the merge
commit. The owner authorized pushing `develop`; the reviewer verifies the remote tip after the merge.

P002-T015 is next. Release 0.2.0 through protected `main`, distribution/publication and installation
remain pending and require their separate authorization.
