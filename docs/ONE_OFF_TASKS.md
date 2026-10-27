# One-off tasks

**Queue:** OT005 reopened after owner manual-test failure; then OT004.
**Next: resolve OT005 external tool-directory alias failure; release remains gated on owner success; then OT004/0.1.6.**

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

## OT005 — Read-only existing tool aliases in generic preparation

**Status:** reopened: the owner's preparation-preview test failed after local installation. The D247 implementation
rejects an external Homebrew directory alias in the declared interpreter's chain; the API translates that OSError
to `target_identity_changed`. The owner approved the bounded external-tool-directory evidence amendment (D248);
its source implementation is qualified (2140 pytest cases passed), awaiting another local reinstall and owner retest.
Integration and
separate 0.1.5 delivery remain gated on manual success.
Initial source commit: `e2d62fe`; the D248 follow-up is in the current topic commit. The owner-requested offline local reinstall/restart is complete, with unchanged data/TOML
hashes and HTTP 200 on loopback 8013. The owner will test; their success report conditionally authorizes the archive,
release PR to main and GitHub publication. Keep this section until delivery is completed or explicitly deferred (D242).
**Priority:** before OT004 and P001-T001, explicitly confirmed by the owner (D246).
**Classification:** bounded hotfix outside the roadmap; separate patch **0.1.5**, after released OT003/0.1.4.
**Branch:** `fix/ot005-preparation-tool-links`, created from `develop` at `a8efd10`. The source commit includes the
previous documentation handoff as requested; metadata remains 0.1.4 pending separate release preparation.
**Delivery route:** topic → `develop` → separate release PR/merge into `main` → 0.1.5 distribution (D235/D239/D242).
**Objective:** let generic preparation inspect an existing environment's read-only executable aliases when they
resolve to the explicitly declared, byte-bound tool, without granting writes to that environment or arbitrary links.
**Cause:** `_executable` admits executable symlinks and preparation binds their resolved target/hash, but
`ProfilePreparation._links` also requires the alias to match `local_paths`. Existing `.venv/bin/python` aliases
outside the private preparation write scope are therefore rejected by the whole-checkout snapshot, even when the
plan only reuses that environment. Changing the executable mapping alone leaves those links in the scanned tree.
**Implementation paths:** `services/profile_preparation.py`, shared preparation snapshot/tool
helpers only where necessary, focused synthetic preparation/receipt tests, and current docs/parity artifacts.
No recipe fingerprint/source rewrite, new dependency or configuration-format change. D247 records additive opt-in
inline link evidence and historical receipt/recovery compatibility, with no API model or schema change.
**Acceptance criteria:**

- Add a synthetic regression for a pre-existing `.venv/bin/python`/`python3`/versioned-interpreter link chain outside
  preparation `local_paths`, resolving to the declared frozen executable. Preview must remain read-only and not
  require adding the environment to `write_paths`/`local_paths`, relocating it or deleting/recreating it.
- Bound any exception to the explicitly declared resolved tool and its content evidence. Never follow directory
  links inside the checkout, traverse arbitrary external trees or allow unrelated external targets, broken links, loops
  or changed tools. The owner-approved D248 amendment permits external directory aliases only along exact declared
  tool chains with frozen evidence. Retain existing private-environment link behavior and snapshot limits.
- Preserve link bytes/modes and the before/after write-scope guards: accepting a read-only input must not allow the
  executor to rewrite that alias/environment or affect its external target. Reject retargeted links or changed
  executable bytes through the appropriate existing guards; do not silently refresh hashes.
- Verify the complete path: preview, execution checks, scope checks, receipt creation and receipt verification.
  Review protected-link refusal and environment accreditation explicitly; fixing preview alone is insufficient.
  Old snapshots/receipts and failed operations remain immutable; no automatic preparation/retry/activation is added.
- Keep exact preview/confirmation, configuration/HEAD binding, work barriers and offline/network rules. If a wider
  link/receipt/configuration contract is needed, record the design and compatibility decision before implementing it.
- Record results/limits and update current flows/specification as implementation requires; regenerate OpenAPI/types
  in the same task if an API contract changes. A release target is not a completed release or installation.

**Validation:** focused offline generic-preparation, snapshot/tool, receipt/recovery and API tests with temporary
Git/SQLite, synthetic executables and links; relevant regressions and release checks before delivery. No real
provider, Docker/project commands, operator configuration edits or preparation execution without separate authorization.
**Handoff/evidence:** [OT005-preparation-tool-links](phase/OT005-preparation-tool-links.md), with code map,
implementation/compatibility evidence, exact checks/omissions and outstanding delivery steps.
**Deliverables:** bounded fix, regression/compatibility evidence, current parity docs, and separately qualified
0.1.5 delivery after authorization. Source implementation and commit are authorized; integration, version bump,
0.1.5 release package qualification/publication await the owner's manual success report. Local reinstall/restart
has completed separately as recorded in the evidence; no real preparation was invoked by maintenance.

## OT004 — Visual profile and agent configuration editor

**Status:** pending; priority and separate patch delivery chosen by the owner. Not implemented.
**Depends on:** OT005's separate 0.1.5 hotfix; precedes P001-T001 Metrics Records (D243/D246).
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
