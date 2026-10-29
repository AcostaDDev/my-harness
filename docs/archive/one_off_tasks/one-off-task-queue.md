# Manual one-off development queue

**Date:** 2026-10-27.
**Status:** documentation setup complete; OT001 implementation remains pending.
**Decision:** [D237](../../DECISIONS.md#d237--one-off-development-queue-before-phase-work).

## Requested sequence and result

1. Reviewed and committed the existing empty failed-intake activation correction
   as `ef77229` (`fix: allow activation after empty failed intake`). The commit
   includes D236, synthetic regression tests and current behavior/flow documentation
   affected by the fix. No model/schema/API contract was changed. The 56 focused
   configuration tests passed again immediately before this checkpoint; the earlier
   69 related checks and offline installed-package verification are recorded in
   [the fix evidence](failed-intake-activation.md).
2. Fast-forwarded local develop to that checked commit, then created
   `docs/one-off-tasks` from develop for this documentation-only work. Nothing was
   pushed or released.
3. Created ONE_OFF_TASKS with a normally empty, phase-independent priority queue,
   stable OTNNN IDs, NEXT_STEPS-style contracts and explicit completion cleanup.
   STATE → ONE_OFF_TASKS → NEXT_STEPS is the discovery order. A blocked entry is
   visible and never silently treated as completed.
4. Added OT001 as the only pending entry: live application of ordinary agent
   settings, full candidate/client/project checks, busy-work handling, frozen-job
   preservation, recoverable activation and UI/session behavior. It includes the
   code map, design gate, acceptance, scope, checks and deliverables for the next
   session. The concrete runtime switching design is not already implemented.
5. Updated AGENTS, README, CONTRIBUTING, STATE and the NEXT_STEPS preface so the
   new entry is discoverable and has priority. The Metrics Records task sections
   and ROADMAP remain unchanged; P001-T001 resumes when the queue becomes empty.

## Completion protocol

The queue holds pending/in-progress/blocked work only. On completion, record the
result, exact checks and omissions in `docs/phase/OTNNN-<topic>.md`, retain durable
decisions in DECISIONS, reconcile current documents, remove the task section and
update Queue/Next. With no entries, it directs the next session to NEXT_STEPS.
Do not retain a completed-task catalog in the queue or reuse an OTNNN identifier.
This is manual repository workflow, not a new harness feature or managed layout.

## Verification and omissions

Static checks cover Markdown local link targets, required queue/contract fields,
priority references, AGENTS line budget and removal of the accidental non-existent
runtime-test reference. Diff review checks that no runtime, dependency, migration,
API, frontend or existing phase-task/roadmap content changed after `ef77229`.
The exact static results are recorded below after verification. No product tests
are required for this documentation-only setup; no providers, network operations,
installation, service restart or operational configuration edits were performed.


Final static results: **PASS** for 72 existing local Markdown link targets,
AGENTS at 53/60 lines with the requested discovery order, all priority references,
exactly one OT001 entry and its required contract fields. **PASS** for byte-for-byte
unchanged NEXT_STEPS shared constraints/task sections and unchanged ROADMAP after
the fix checkpoint. The diff is documentation-only and `git diff --check` passes.
At the owner's explicit request, the new documentation is recorded in a separate
commit on `docs/one-off-tasks`, branched from local develop. The prior source
checkpoint is `ef77229`, already integrated into local develop.
