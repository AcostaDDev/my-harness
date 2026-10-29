# P002 — Continuous Mode (target: 0.2.0 at phase closure)

**Status:** active since the P001 closure (2026-10-29), **without tasks**. The design and the task plan must be
proposed and confirmed by the owner before any implementation, as D234 did for P001. Read
[ONE_OFF_TASKS](ONE_OFF_TASKS.md) first; its queue is **empty**.

**Objective** ([ROADMAP](ROADMAP.md#p002--continuous-mode)): automatically close and archive a completed phase, open and
plan the next phase, and continue its execution under one explicit, bounded authorization; chain tasks, commits and
the READY check while stopping at the first error, question or limit.

**Exit criteria:**

- The mode is optional and starts only from an initial authorization with an explicit scope and budget.
- Phase closure, archiving and opening/planning the successor happen automatically within that authorization,
  subject to a valid READY check and the existing content-bound guarantees.
- It stops at the first error, blocking condition, question for the user, out-of-scope change or consumption limit,
  and the stopped work can be inspected and resumed.
- READY binding, acceptance by exact content, intent before effect and recovery keep their current guarantees.
- Without that authorization the current behavior is unchanged: explicit task batches, explicit check, closure
  authorized on READY and a confirmed plan for each new phase.

**Starting context:** [P002 handoff](archive/phase-001/P001-T006-qualification.md#p002-handoff), the
[phase lifecycle](flows/phase-lifecycle.md) and [task run](flows/task-run.md) flows,
[D091](DECISIONS.md#d091--unified-closure-and-archive-with-later-planning),
[D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020) and
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020). The previous phase's plan is
archived in [P001 NEXT_STEPS](archive/phase-001/NEXT_STEPS.md).

**Next:** propose the P002 design questions and task plan for the owner's confirmation. Each task will use a topic
branch from `develop` (D235); no code, release or harness operation before that plan is accepted.
