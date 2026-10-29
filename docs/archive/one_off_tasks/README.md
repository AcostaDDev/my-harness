# One-off development records

Completed work outside a roadmap phase, archived after its change reached `main`
([D267](../../DECISIONS.md#d267--archive-completed-one-offs-separately-from-active-phase-work)). Active tasks and
pending agreed delivery belong in [ONE_OFF_TASKS](../../ONE_OFF_TASKS.md). This is a repository-development archive,
not an implemented managed-project OneOffTask feature.

| Task | Delivered version / route | Historical record |
|---|---|---|
| OT001 — Live agent configuration | 0.1.2 | [Evidence](OT001-live-agent-configuration.md) |
| OT002 — Question-first answers and activity | 0.1.3 | [Evidence](OT002-question-answers.md) |
| OT003 — Intake/profile diagnostics | 0.1.4 | [Evidence](OT003-intake-profile-diagnostics.md) |
| OT004 — Visual profile editor | 0.1.6 | [Evidence](OT004-visual-profile-editor.md) |
| OT005 — Preparation tool aliases | 0.1.5 | [Evidence](OT005-preparation-tool-links.md) |
| OT006 — Preparation consumption guard | 0.1.7 | [Evidence](OT006-preparation-consumption.md) |
| OT007 — Task-run lease and stream journal | 0.1.8 | [Evidence](OT007-task-run-lease.md) |
| OT008 — Quiet development checks | Initially source-only into develop; included in 0.1.9 under D261 | [Evidence](OT008-development-checks.md) |

Supporting historical records:

- [One-off queue setup](one-off-task-queue.md), before OT001 implementation; its then-pending status is historical.
- [OT002 documentation handoff](pending-questions-handoff.md), superseded by the completed task evidence above.
- [Empty-intake activation fix](failed-intake-activation.md), recorded before stable OT numbering; no new ID is
  assigned retroactively.

The archived text/results are retained; only relative link targets are rebased. Later facts belong in the current
STATE/queue or a new record. The initial relocation used the already recorded `origin/main` release at `5cc1bc1`
as integration evidence without fetching or changing refs. No release, publication or installation was performed
by moving these files. See the [archive index](../README.md) for closed phases and other historical notes.
