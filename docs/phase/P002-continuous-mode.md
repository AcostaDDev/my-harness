# P002 — Continuous Mode: design proposal and task plan

Status: **superseded draft** — the owner widened P002 to a fully autonomous mode; the discussion continues in
[P002-autonomous-mode-discussion](P002-autonomous-mode-discussion.md). Kept as the first proposal (2026-10-29). Nothing here is decided or implemented; once
confirmed, the plan moves into [NEXT_STEPS](../NEXT_STEPS.md) with a decision record, as D234 did for P001.
Target: **0.2.0 at P002 closure** ([D253](../DECISIONS.md#d253--phase-release-targets-after-018)); objective and exit
criteria in the [roadmap](../ROADMAP.md#p002--continuous-mode); reserved by
[D156](../DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020).

## Problem

Today each step of a managed project's lifecycle needs its own explicit authorization: an unattended batch chains
`task → commit → next task` but never checks or closes (D034); a closure needs a current READY check and its own
authorization (D091, SPECIFICATION §5 rule 9); the successor phase starts empty and its plan is confirmed by hash
(`phase_planning`). Continuous Mode lets one bounded authorization drive that whole chain across phases, stopping at the
first error, question, out-of-scope change or limit, without weakening any of those guarantees.

## Building blocks already in the code

| Step | Existing mechanism | Source |
|---|---|---|
| Chain tasks and commits | Batch authorization with `chain_commits`, frozen plan/definition/context/versions, deterministic step keys, driven by the supervisor (`advance_batches`) and stopping on expiry, definition change, questions, non-ACTIVE phase, recovery-required jobs or an ineligible acceptance | `storage/phases.py` (`authorize_batch`, `_batch_step`) |
| READY check | `submit_check` queues a `phase_check` run; the phase goes `CHECKING` → `READY_TO_CLOSE` / `NEEDS_RECONCILIATION` / `BLOCKED` / `ACTIVE` | `storage/phases.py`, [phase lifecycle](../flows/phase-lifecycle.md) |
| Closure and archive | `submit_close` bound to the shown READY `binding_sha256`, sealed tag/commit intents, one archive commit, successor created ACTIVE without tasks | `storage/phases.py`, `storage/closure.py`, D091 |
| Plan of the successor | `phase_planning` conversation proposes NEXT_STEPS; preview with diff and hash; idempotent confirmation creates a new definition version | `storage/planning.py`, `storage/phase_plan.py` |
| Consumption evidence | P001 invocation ledger with coverage, token categories and valuations per compatible basis | `storage/accounting_views.py` (D262) |
| Recovery | Intent before effect, idempotency keys, quarantine, explicit confirm-stopped | D052/D056, task-run flow |

## Proposed design (each point needs confirmation)

1. **One new authorization kind, `continuous`, composed from the existing steps.** It does not replace the batch,
   check, closure or plan operations: a driver advanced by the supervisor (like `advance_batches`) issues them with
   deterministic keys derived from the authorization, so every step keeps its own guards, intents and recovery. One
   active continuous authorization per project root; it excludes manual batches on that root while active.
2. **Explicit scope, frozen at authorization:** the starting phase, a maximum number of phase closures (`max_phases`,
   e.g. 1–3) and whether it may plan successors. ROADMAP order is fixed: it only advances to the successor that the
   closure already creates; a phase missing from ROADMAP stops the run. Frozen context/versions follow the batch rules;
   a configuration activation or definition amendment invalidates the authorization.
3. **Budget, counted from the start and checked before each new step:** wall-clock expiry (the current 24 h maximum,
   or a new bound to decide), maximum tasks, maximum agent invocations, and optionally a token cap computed from the
   P001 ledger. Unknown usage is never zero: with a token cap set, an expected invocation without usage evidence stops
   the run. An optional valuation cap applies only to one compatible basis and stops on any incomplete valuation. No
   quota or allowance is inferred (D232).
4. **Closure inside the authorization.** After the last task commit the driver queues the READY check; only a `READY`
   result lets it queue the closure, bound to that check's binding exactly as a manual closure would be; the tag kind
   stays the project's setting. `NOT_READY`, `REVISE`/`NEEDS_RECONCILIATION` and `BLOCKED` stop the run (automatic
   reconciliation tasks are excluded from the first version).
5. **Planning the successor inside the authorization (the key decision).** The driver starts the `phase_planning`
   turn for the new empty phase. Proposed default: the plan is **accepted automatically only if** it adds tasks within
   per-plan limits (task count, allowed paths inside the profile), raises no question, and the preview hash is sealed in
   the run's evidence; anything else stops for the owner. Alternative: a "semi-continuous" mode where every successor
   plan always waits for the owner's confirmation and the run resumes after it.
6. **Stop catalog with stable codes:** first job error or revision limit, any question or blocking question, scope
   grant requests (out-of-scope changes), ineligible acceptance, check not READY, closure refused or uncertain,
   plan outside the limits, budget exhausted, expiry, revocation, configuration/definition change, recovery-required
   job, missing successor. A stop never retries or falls back (SPECIFICATION §5 rule 4).
7. **Inspect and resume.** The authorization records each step (kind, job/run, result, consumption so far, stop code).
   A stopped run is read-only evidence; resuming means a new authorization that starts from the state derived from
   SQLite, never a silent restart. Revocation takes effect before the next step; a running job finishes or is
   cancelled with the existing controls.
8. **Without the authorization nothing changes:** explicit batches, explicit check, closure authorized on READY and
   a confirmed plan per new phase keep working exactly as now (exit criterion 5).
9. **Data, API and UI:** an additive migration (`0029`) for the authorization steps (or extending the existing
   authorization table, decided in T001), `/api/managed/.../continuous` routes with preview/confirm/revoke and step
   listing, and an en/es panel on the phase page with scope, budget, live progress and the stop reason. 0.2.0 may
   change API/UI under the pre-1.0 policy, with parity of DDBB, flows, OpenAPI and client types.

## Proposed task plan

| Task | Objective | Main deliverables |
|---|---|---|
| P002-T001 — Contract and design | Settle points 1–9: authorization model and scope, budget units, plan-acceptance policy, stop catalog, state machine, data/API contract, synthetic acceptance matrix | Contract document, decisions, planned data/flow updates (labelled planned) |
| P002-T002 — Authorization, driver and stops | Continuous authorization and its supervisor driver over existing batch/commit steps, budget counters (time, tasks, invocations), stop catalog, revocation, recovery | Migration, storage/services, synthetic tests incl. crash/restart and idempotency |
| P002-T003 — Automatic check, closure and planning | READY check → closure on READY within the authorization; successor `phase_planning` turn and the confirmed acceptance policy; multi-phase chaining up to `max_phases` | Phase lifecycle integration, flow update, synthetic multi-phase journeys |
| P002-T004 — Consumption limits from the ledger | Optional token and valuation caps over the P001 ledger with unknown-is-not-zero stops | Budget evaluation, tests over partial/unpriced coverage |
| P002-T005 — API and UI | Preview/confirm/revoke, step listing and stop reasons; en/es panel; archive read-only | API/OpenAPI/types, frontend page and tests, synthetic browser QA |
| P002-T006 — Qualification and phase handoff | Exit-criteria matrix, regression, 0.2.0 candidate and upgrade notes | Qualification evidence, release candidate |

Each task uses a topic branch from `develop` (D235) and the existing synthetic, offline checks; no real provider is
invoked to qualify the mode.

## Out of scope (proposed)

Automatic reconciliation or amendment tasks, ROADMAP edits by agents, creating new projects, running across several
projects at once, scheduling/time-based starts, new providers, and any billing integration. Consumption caps use only
the P001 ledger; they are local limits, not provider quotas.
