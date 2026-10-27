# One-off tasks

**Queue:** OT007 in progress.
**Next: OT007 — task-run lease renewal and stream journal pressure; then NEXT_STEPS.md.**

OT006 was released as **0.1.7** ([evidence](phase/OT006-preparation-consumption.md), D251), installed locally and
removed after its published downloads were verified. OT007 is the wider task-run issue that OT006 scoped out.

Read after [STATE](STATE.md), before [NEXT_STEPS](NEXT_STEPS.md). This queue is for
bounded fixes, improvements and design changes outside a complete roadmap phase.
It belongs to development of this repository; the harness does not execute this
file or use it as a new project-document contract.

## Queue rules

- Normally there are no task sections. When empty, retain this introduction/rules,
  set Queue to **empty** and Next to **continue with NEXT_STEPS.md**.
- Pending/in-progress tasks take precedence over phase work. Work on one bounded
  task at a time, in the stated dependency/order. An explicit user instruction can
  override the order. A blocked task stays visible with its missing prerequisite;
  do not silently skip it or resume the roadmap as if it were complete.
- Use stable, phase-independent IDs `OTNNN` and the contract fields below. Allocate
  the next unused ID from retained work artifacts/Git history; never reuse an ID.
  Do not assign these tasks phase numbers or mark a phase task complete for them.
- Before removing a completed task, satisfy its acceptance, review the diff, run
  relevant checks and record results/omissions in `docs/phase/OTNNN-<topic>.md`.
  Record durable choices in DECISIONS and update affected current docs/parity.
  After agreed delivery is complete or explicitly deferred (D242), remove the task section and update Queue/Next.
  Completed tasks and their history do not accumulate here. Commit only when the user requests it.
- Keep scope proportional. If work needs multiple independently planned tasks or
  a full phase, surface that before implementation instead of growing this queue
  into a second roadmap. Follow AGENTS and its authorization/data rules throughout.

## Ownership and delivery

Before product edits, identify the phase/task or one-off owner and agree whether the work belongs to the roadmap
or needs a separate distribution. Record its branch, target version/route and outstanding delivery steps (D242).
Source completion, integration into `develop`, release merge into `main`, distribution publication and local
installation are different states. Keep outstanding agreed delivery in this queue until completed or explicitly
deferred with a recorded destination. D239's patch-per-one-off rule and D235's branch/release route apply.
Recording a release target does not authorize a commit, merge, push, publication, service restart or installation.

## OT007 — Task-run lease renewal and stream journal pressure

**Status:** source implemented and qualified; owner confirmed **0.1.8** on 2026-10-27. Integration, release and
installation remain pending; evidence: [OT007](phase/OT007-task-run-lease.md).
**Depends on:** OT006/D251 (released 0.1.7), which fixed the same pattern only for generic preparation. OT007
precedes P001-T001; no Metrics Records work is completed here.
**Classification:** bounded runtime reliability fix outside the roadmap, for managed task/phase/chat/definition runs.
**Branch:** `fix/ot007-task-run-lease` from clean, synchronized `develop` (`b8e1a90`).
**Delivery route:** the agreed one-off policy applies: next patch **0.1.8** (D239) via topic → `develop` → release PR
→ `main` → GitHub Release with the self-contained archive (D235/D242). The owner explicitly authorized the final
commit, integration/push, release PR, offline archive/checksum build, draft upload/download verification, PR merge,
publication/public download verification, offline installation with the service stopped and closure evidence.
Track these states separately until all are complete. No real provider invocation or service start is authorized.
**Objective:** apply D251's lease-renewal and write-pressure lessons to managed runs. Keep their fencing and their
explicit heartbeat-failure stop. Decide whether `output-guard-1` evidence/stop behavior needs any run-level surfacing.
**Known facts (from OT006 source inspection, not yet reproduced for runs):**

- `services/managed.py`, `LocalSupervisor.run_once` → `heartbeat()`: any exception sets `heartbeat_failed` and the
  thread returns. `_Journal._call` then refuses the next journal operation with
  `supervisor.heartbeat_failed_stop_before`. A single transient SQLite busy error (a waiting writer can hit the 5 s
  `busy_timeout` under a tight writer loop; see OT006's experiment) therefore ends an otherwise healthy attempt.
- `storage/managed.py`, `process_update()`: one guarded write transaction per stream record and per byte chunk.
  `CLIProcessAdapter.invoke` already batches via an optional `process_updates(attempt_id, items)` journal method
  (D251); the managed `_Journal`/repository do not implement it yet.
- The CLI adapter already writes `capture.json` on interrupted invocations and reports `output_guard` /
  `final_usage_observed` in run attempt metadata. Check how run recovery (`RECOVERY_REQUIRED`, confirm-stopped)
  treats a stale `RUNNING` process row versus that capture.

**Allowed paths:** `services/managed.py`, `storage/managed.py`, CLI/stream adapters only if a shared helper is
needed, focused synthetic tests and current docs/parity (flows `task-run.md`, DECISIONS, ARCHITECTURE, catalogs en/es).
No schema change unless a decision is recorded first; no new dependency or operator configuration change.
**Acceptance criteria:**

- Reproduce, with synthetic tests and temporary SQLite/processes, that one transient heartbeat failure stops a
  managed run today. After the fix, transient failures are retried within the lease, and only lost ownership (or
  an exhausted lease) stops the attempt. The diagnostic names the renewal failure; the lease is not merely lengthened.
- Batch each read chunk's stream events into one guarded transaction for managed runs. Keep event content, order,
  sequence numbers and run-projection/metrics derivations identical (existing metrics/projection tests prove it).
- Interrupted-attempt evidence on runs: the closing owner settles its own stale `RUNNING` process rows from
  independent group liveness, keeping the adapter's partial capture, never replacing a stored capture, never
  marking an attempt successful and never treating lease expiry as proof that a writer stopped.
- Preserve job fencing, checkout exclusion, cancellation, quarantine/recovery, frozen versions (`cli-14`) and
  histories; en/es parity for any new text.

**Validation:** synthetic fake-CLI/managed tests for transient and permanent heartbeat failure, sustained
streaming, cancellation and recovery; full offline suites, `alembic check`, frontend tests/typecheck if texts or API
change. No real provider, production retry or installation without explicit owner instruction.
**Deliverables:** decision record, implementation/tests/parity, `docs/phase/OT007-task-run-lease.md` evidence with
exact checks/omissions, and the agreed 0.1.8 delivery tracked here until completed or explicitly deferred.
