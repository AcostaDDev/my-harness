# One-off tasks

**Queue:** OT004 and OT006 pending.
**Next: OT004 — visual profile/agent editor for 0.1.6; then OT006, then NEXT_STEPS.md.**

OT006 records the later preparation incident and the handoff requested before `/clear`. This documentation-only
request does not change D246's OT004 priority/version; agree any incident reprioritization and OT006 release target
before product changes.

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

## OT004 — Visual profile and agent configuration editor

**Status:** pending; priority and separate patch delivery chosen by the owner. Not implemented.
**Depends on:** released OT005/0.1.5 (completed); precedes P001-T001 Metrics Records (D243/D246).
**Classification:** bounded UX development outside the roadmap; separate patch **0.1.6**, after OT005 (D239/D246).
**Branch:** a separate `feat/ot004-visual-profile-editor` topic from `develop` when OT004 starts.
**Delivery route:** its own topic → `develop` → separate release PR/merge into `main` → 0.1.6 distribution.
**Objective:** make the existing profile/agent configuration accessible through interactive forms in project
settings and the applicable global settings, with clear effective values, scope and save/activation behavior.
**Allowed paths:** relevant `frontend/src/**`, `frontend/tests/**`, existing configuration service/API modules only
if required to expose supported fields, and current documentation/parity artifacts. No new dependencies by default.
**Acceptance criteria:**

- Inventory supported fields and their actual scope before implementation. Reuse the existing versioned editors
  and configuration authority rather than introducing another settings store. Global defaults/reusable profiles
  belong to the global editor; project profiles/overrides belong to project settings; explain inheritance/effective
  configuration and the impact on other projects.
- Add guided forms for profile preparation/validation commands (argument arrays, cwd, timeout, environment and
  optional JUnit), command prefixes/authorization, executable-name-to-path mapping, protected/sensitive/allowed
  exception/data-model paths, executor instructions and the optional formatter pair. Preserve exact values and
  distinguish a command alias from an installed path. Keep TOML/advanced editing as a compatible alternative.
- Show each agent's provider, model/effort policy, environment/timeouts and supported tool capabilities. Edit only
  capabilities the existing provider/role/configuration contract permits; explain fixed read-only reviewer and
  checkout restrictions. Do not imply arbitrary filesystem/network/sandbox permission switches or add execution
  authority without a separately recorded design decision.
- Provide actionable field validation, keyboard-accessible add/edit/remove controls and en/es guidance. Drafts and
  values outside the currently displayed controls survive navigation, conversion, provider changes and conflicts;
  no hidden capability is silently dropped or granted.
- Preserve exact diff/CAS/version/idempotency review and separate save/preparation/activation. Preview explains
  whether new preparation is required and how global/project changes apply under existing rules. Editing alone
  starts no provider, preparation, project command or activation; frozen runs retain their settings.
- Keep legacy configurations and query-only archives under their existing supported edit/read gates. Update
  flows and, if contracts change, OpenAPI/generated types in the same task. Do not mark these forms implemented
  until their code and validation are complete.

**Validation:** focused synthetic form/component/request tests; frontend suite, typecheck/build; related offline
configuration/API regressions if touched; visual QA in en/es, light/dark, desktop/mobile and keyboard navigation.
No real agents/providers or changes to the operator's installed configuration.
**Deliverables:** editor implementation, tests/parity, `docs/phase/OT004-visual-profile-editor.md`, and a separately
qualified 0.1.6 delivery. Implementation details are resolved within the existing contract; inconsistencies are
raised before changing its permission design.

## OT006 — Repetitive preparation executor output and ownership loss

**Status:** pending investigation/fix; sanitized read-only evidence recorded, no implementation.
**Depends on:** OT005 source/release baseline; follows OT004 under the current queue order unless the owner
explicitly reprioritizes it. Both precede P001-T001; no Metrics Records work is completed here.
**Classification:** bounded runtime reliability/consumption incident outside the roadmap, separate from released
OT005 and from P001's accounting feature work.
**Branch:** handoff on `docs/ot006-preparation-consumption` from `develop` at `3876230`; preserve its uncommitted
documentation. Create a `fix/ot006-preparation-consumption` topic from current `develop` for implementation,
carrying forward this handoff if it has not yet been integrated.
**Delivery route:** product delivery target/order must be agreed before implementation (D242); the existing
topic → `develop` → separate release PR/merge into `main` → patch distribution policy applies (D235/D239).
No version is assigned here; OT004's 0.1.6 is unchanged. Source, integration, publication and installation are
all pending; this request authorizes evidence/task documentation only, not a retry or new provider invocation.
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
