# One-off tasks

**Queue:** empty.
**Next: continue with NEXT_STEPS.md.**

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
  Then remove the entire task section and update Queue/Next. Completed tasks and
  their history do not accumulate here. Commit only when the user requests it.
- Keep scope proportional. If work needs multiple independently planned tasks or
  a full phase, surface that before implementation instead of growing this queue
  into a second roadmap. Follow AGENTS and its authorization/data rules throughout.
