# One-off tasks

**Queue:** OT006 source complete for **0.1.7**; delivery pending (PR merge, release publication).
**Next: OT006 delivery — merge the release PR and publish the draft v0.1.7 only on explicit owner instruction; then
NEXT_STEPS.md.**

OT004 was released as **0.1.6** ([evidence](phase/OT004-visual-profile-editor.md)) and removed after its published
downloads were verified. OT006's fix (D251) is integrated into develop; its agreed patch delivery is still open.

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

## OT006 — Repetitive preparation executor output and ownership loss

**Status:** source complete and integrated into develop
([evidence](phase/OT006-preparation-consumption.md#resolution-d251),
[D251](DECISIONS.md#d251--writer-tool-admission-bounded-repetitive-output-and-lease-renewal-evidence)); delivery
pending.
**Depends on:** OT005 source/release baseline; OT004 was delivered first as 0.1.6. OT006 precedes P001-T001; no
Metrics Records work is completed here.
**Classification:** bounded runtime reliability/consumption incident outside the roadmap, separate from released
OT005 and from P001's accounting feature work.
**Branch:** handoff `docs/ot006-preparation-consumption` (`6a1b721`, integrated by `f185265`); implementation and
release preparation on `fix/ot006-preparation-consumption`, merged into develop (see the evidence's delivery state).
**Delivery route:** agreed 2026-10-27: patch **0.1.7** (D239) via topic → `develop` → release PR → `main` (D235).
Done: source, integration into develop, release PR opened, the self-contained archive and its checksum uploaded to a
**draft** GitHub Release `v0.1.7`. Outstanding: merge the PR, tag the merge and publish the draft (each on explicit
owner instruction), verify the public downloads, record closing evidence and then remove this section. Installing
0.1.7 on the operator machine is a separate operator action with stopped service/writers. No retry of the failed
real preparation is authorized.
**Objective:** establish why the generic preparation executor emitted repetitive text without completing its
work, prevent unbounded useless generation, and diagnose/fix lease loss with truthful terminal process evidence.
**Evidence/handoff:** [OT006 incident notes](phase/OT006-preparation-consumption.md), including exact aggregate
counts, token limitations, local read-only lookup instructions and source inspection points.
**Allowed paths:** relevant CLI/stream/process adapters, generic preparation service/storage and managed write
coordination only as required by the reproduced cause; focused synthetic tests and current docs/parity artifacts.
No new dependency, operator configuration change or private production fixture.
**Acceptance criteria:**

- Reproduce the repetitive text/protocol symptom with synthetic streams and investigate prompt/tool/CLI contract
  handling before choosing a fix. Distinguish actual tool calls from textual imitations and stream events from
  provider requests; do not assume a model change or lower effort alone fixes the cause.
- Define and record a bounded output/repetition stop policy, with false-positive and legitimate long-output cases,
  then verify termination of the owned process group and retention of partial evidence. Do not silently grant
  more tools, writes, network access or retries; actual subscription quota is not inferable from token counts.
- Reproduce or otherwise establish the lease/heartbeat failure path under synthetic sustained streaming and
  contention. Make heartbeat failure diagnosable; preserve fencing, checkout exclusion, cancellation and recovery.
  Do not treat lease expiry or a stale process status as proof that a writer stopped.
- Preserve available usage, artifact and terminal/group evidence when ownership/persistence fails, through an
  ownership-safe design. An absent final token count remains unknown; do not double count initial/repeated usage,
  turn partial counters into totals or rewrite the original failed operation into a successful receipt.
- Keep en/es diagnostics and affected flow/API/schema parity if changed; preserve frozen recipes, histories,
  configuration and D247–D249 tool/write-scope guarantees. Scope any wider discovered issue explicitly.

**Validation:** synthetic fake-CLI/parser and preparation/storage regression tests for repetitive text, legitimate
streaming, lease contention/failure, cancellation, partial capture and stopped/uncertain groups; relevant offline
suites and parity checks. No real provider, production retry, recovery confirmation or installation without a
separate explicit operator instruction. Do not copy this real stream, prompt or project into tests.
**Deliverables:** established cause(s), accepted bounded design, implementation/tests/parity and updated incident
evidence with exact checks/omissions; separately track the agreed patch delivery and any operator validation.
