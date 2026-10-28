# One-off tasks

**Queue:** OT008 pending.
**Next:** OT008, before P001-T004.

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

## OT008 — Quiet development checks and agent workflow guidance

**Status:** pending; registered 2026-10-28 at the owner's request, to be done in the next session before P001-T004.
No implementation yet.
**Depends on:** P001-T003 integrated into `develop` (`79e4cdb`). OT008 completes no Metrics Records task and does
not change P001's plan or the 0.1.9 target.
**Classification:** bounded development-tooling improvement outside the roadmap. It is for working on this
repository, not a harness feature: managed projects already run formatter/validations/JUnit deterministically in
the engine with journaled evidence, and the adapters deliberately disable client hooks and project configuration
(Claude `--setting-sources ""` with `disableAllHooks`; Codex project marked `untrusted`). That boundary stays.
**Branch:** create `chore/ot008-development-checks` from current `develop`.
**Delivery route (proposed; confirm with the owner before edits, D242):** topic → `develop` only. D239's patch release
applies to one-offs that change the product; if this work changes nothing installed or packaged, there is no
release, and it ships in source only. If any new file would enter the wheel/sdist/archive, decide explicitly whether
to exclude it or treat it as a product change. Commit, merge and push each need explicit owner instruction.
**Objective:** reduce agent token use and repeated ad hoc tooling when developing this repository. The P001-T003
session spent about 181k tokens on shell output. Most was reading source with `cat`/`sed`, and part was full test
output. T001, T002 and T003 each rebuilt their own Markdown link/anchor checker.
**Scope:**

- `scripts/check` (standard library only, no new dependency): runs the existing AGENTS command sets
  (focused paths, full pytest, unittest, alembic check on a temporary database, optional frontend) through the
  pinned offline `uv` invocation, and prints only per-suite counts plus failing test IDs with their first error line.
  The exit status is nonzero on any failure; the complete log goes to a file under `.local/` for inspection.
- `scripts/check-docs`: local Markdown targets/anchors (GitHub slug rules, including underscores and explicit
  `<a id>` anchors), paired fences, en/es i18n key parity, and DDBB head/table count against
  `storage/schema.py`/models. Reports a compact list of errors.
- AGENTS.md guidance for any agent (Claude Code and Codex): use these scripts instead of raw suite output, read
  files by range or `grep` rather than whole large files, and prefer the cheapest sufficient check before the full
  suite. Keep CLAUDE.md as a thin import.
- Optional, only if the owner agrees: a minimal project `.claude/settings.json` with a read-only/script permission
  allowlist and at most a cheap `PostToolUse` syntax check on edited Python files that reports only failures.
  Not in scope: a `Stop` hook running suites, hooks that push/commit, Codex project configuration without first
  verifying its documented format, or any change to the managed-project hook/config isolation.

**Allowed paths:** `scripts/check`, `scripts/check-docs` (or equivalent names), focused `tests/**` for the scripts,
`AGENTS.md`, `CLAUDE.md`, `README.md#development`, optional `.claude/settings.json`, current docs and a new decision
(D260). No product source, migration, API, frontend or dependency change; no user/global configuration change.
**Acceptance criteria:**

- Each script reproduces the pass/fail outcome of the commands it wraps on a clean tree and on an injected synthetic
  failure, with the failing ID visible and bounded output. It runs offline, needs no network, and never creates
  or migrates a user database (temporary SQLite only for `alembic check`).
- `check-docs` passes on the current documentation and catches a synthetic broken link, missing anchor, unpaired
  fence and missing es/en key.
- The guidance works identically from Claude Code and Codex (no client-specific behavior required).
- Record D260, evidence in `docs/phase/OT008-development-checks.md` (exact checks, a before/after output-size
  comparison on the same suite, omissions), update STATE/this queue, then remove this section after delivery.

**Validation:** focused tests for both scripts; one run of each wrapped suite through the scripts compared with the
direct command; `git diff --check`. The full suite only if a shared test helper changes.
