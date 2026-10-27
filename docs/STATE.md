# State — my_harness

No managed blocks: this repository is developed by hand and is not registered in a harness. The work done before the
first public snapshot is summarized below as the starting baseline; its decisions are in [DECISIONS](DECISIONS.md).

## Work routing

Read [ONE_OFF_TASKS](ONE_OFF_TASKS.md) before [NEXT_STEPS](NEXT_STEPS.md). It is the
normally empty priority queue for bounded fixes/improvements outside roadmap phases
([D237](DECISIONS.md#d237--one-off-development-queue-before-phase-work)).
The queue contains **OT006**, the repetitive-preparation/ownership-loss incident (release target pending), before
the unchanged Metrics Records task P001-T001 (D246). OT001/OT002/OT003/OT005/OT004 were released separately as
0.1.2/0.1.3/0.1.4/0.1.5/**0.1.6** (D239). No Metrics task is complete.

OT004 (D250) was integrated on develop at `bd0787b`, released through
[PR #5](https://github.com/AcostaDDev/my-harness/pull/5), merge **`0319b66`**, and tagged **`v0.1.6`**. The
[GitHub Release](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.6) includes the self-contained archive and
checksum, downloaded and verified byte for byte. Full pytest: **2140 passed, 2 skipped, 29 subtests** (`-n 4`; two
earlier default-worker runs under heavy unrelated load each hit one different pre-existing timing race, recorded in
the evidence); **230 frontend tests**, 10 unittest cases, typecheck/build, temporary schema and installed-wheel checks
passed. OT004 was removed from the queue only after delivery. Publication did not install or restart anything.

OT005 was integrated on develop at `b50070d`, released through
[PR #4](https://github.com/AcostaDDev/my-harness/pull/4), merge **`b0d035d`**, and tagged **`v0.1.5`**. The
[GitHub Release](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.5) includes the self-contained archive and
checksum, downloaded and verified byte for byte. Full final pytest: **2140 passed, 2 skipped, 29 subtests**;
**213 frontend tests**, 10 unittest cases, typecheck/build, temporary schema and final installed-wheel checks passed.
[The evidence](phase/OT005-preparation-tool-links.md) records D247–D249 and the owner's ACTIVE-preparation report;
completed real commands/receipt/activation are not claimed. OT005 was removed from the queue only after delivery.

**OT006 handoff:** committed and integrated into develop (`f185265`); read
[OT006 evidence](phase/OT006-preparation-consumption.md). The later real preparation FAILED with `OwnershipLost`:
one Claude session emitted 226,378 text characters with extensive repetition over about nine minutes, before any
native command; its process group is now dead. Exact quota consumption and the repetition/lease root causes remain
unproven. That request recorded evidence only; OT006 is now next, and its delivery target is still to be agreed. Do not start Metrics Records or retry real preparation from this handoff.

Publication did not replace/restart the operator installation: its separately installed source `be76164`
contains the OT005 fixes with **0.1.4 metadata**, and the same loopback service remained running. Installing the
published 0.1.5 package is a separate future operator action when service/writers are stopped; it was not requested
or performed during publication. Closing release documentation is kept on develop, without changing the tag.

OT003's intake diagnostics, corrected adoption guards and joint document review (D241/D244/D245) were released
through [PR #3](https://github.com/AcostaDDev/my-harness/pull/3), merge `9985b0a`, tagged `v0.1.4` on main. The
[GitHub Release](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.4) includes the self-contained archive
and checksum, downloaded and verified byte for byte. Full offline pytest: 2095 passed, 2 skipped, 29 subtests passed;
203 frontend tests, unittest/typecheck/build, temporary schema and installed-wheel checks passed. Earlier authorized
local installation used the uncommitted implementation with 0.1.3 metadata; publishing this release did not restart
or replace the operator's running service. See [the evidence](phase/OT003-intake-profile-diagnostics.md).

## Accumulated baseline

What exists and works at the first public snapshot, verified offline with temporary Git repositories, SQLite and
processes, fake agents and synthetic data unless stated otherwise. First local version complete within the scope
described in the [supported scope](../README.md#supported-scope-and-limits); package `0.1.1`, published with `0.1.0` as GitHub Releases.
The real validation originally deferred in D151 now has the bounded evidence below.

- **Engine.** Package `my_harness` with an explicit context per project, frozen task contracts, planning by the
  reviewer or deterministic from `NEXT_STEPS`, the execute → format → validate → review loop with a correction limit,
  acceptance bound to the exact content and a reconcilable commit made by the harness (D052, D056, D129, D133).
- **Persistence and recovery.** SQLite schema `0027_profile_proposals` managed by Alembic; idempotent job queue
  with leases, a lock per checkout, quarantine when frozen versions change and explicit confirmation of a stopped
  writer. Backup and query-only restore, explicit stream retention, explicit migration of existing databases with
  a verified snapshot (D150). Derived run projection written with each history (D144).
- **Agents.** Reviewer and executor, Codex or Claude Code in any combination, per-project presets; read-only
  reviewer with a typed output schema; automatic memory disabled; Codex writer limited to the checkout. Clients are
  discovered on an explicit `PATH`, checked against minimums (Codex 0.163.0, Claude Code 2.1.304) and a packaged
  capability policy, frozen per job and revalidated before every attempt (adapter `cli-14`, D173, D174). Native
  validations with JUnit reports; declared profiles in the operator TOML (D095), including the optional native
  formatter in `local-config-8` (D194). Formats 1–7 retain their rules. Explicit capability lists wrapped across
  help lines are read within their option; missing required values still block admission.
- **Phases and documents.** Unified documentation layout (D088): `AGENTS.md`, single `DECISIONS.md` with an index,
  managed blocks regenerated on every task commit, confirmed edits, READY check, unattended task batches,
  amendments, abandonment and a unified closure that archives the phase in `docs/archive/phase-NNN/` and opens the
  next one without tasks until its plan is confirmed (D034, D089, D091). `AGENTS.md` is injected into every frozen
  prompt (D094).
- **Creation and chat.** New projects through a definition conversation with drafts on disk and compare-and-swap
  writes (D075); conversational phase planning; chat over a read-only HEAD snapshot with deterministic commands and
  proposals that become confirmed tasks (D083). Projects folder chosen in the UI and creation intents with recovery
  (D116).
- **Recipes.** Confirmed, recoverable preparation of new Django (D119) and TypeScript web (D143) projects with a
  separate technical commit; v2 recipes follow the project's work language (`local-config-6`–`8`, D168).
  Resolving agent clients rebinds compatible completed receipts before admission, preserving the exact
  `project_environment_sha256`; missing or drifting receipts still block work.
- **Onboarding.** Static inventory of a committed tree, read-only conversation with private drafts, confirmed
  profile and documents, and a reconcilable documentation commit that adopts `P001` (D102). Support for the
  previous harness format is retired; earlier data stays readable and old jobs are quarantined (D161).
- **Languages.** Global interface language and default work language with version checks (D166); immutable work
  language per project root (D167); both frozen per job and attempt and sent to the agents as a sealed directive;
  generated documents in the work language (D169); interface, service and CLI texts in English and Spanish
  (D170–D172).
- **API and UI.** `/api/managed` behind a local session, Host/Origin checks and a CSRF header; React UI with URLs for
  projects, registry, creation, onboarding, documentation, phases, tasks, runs with paginated diffs, chat,
  statistics, settings and preferences; per-attempt metrics with provenance (D074). Query-only copies expose
  `read_only_archive` from their persistent mark and a standalone `/runs/:id` view with evidence, diff, JUnit and
  metrics, without project configuration, a checkout, execution polling or mutation controls
  ([flow](flows/backup-consultation.md)).
- **Distribution and operation.** Wheel and sdist with UI, migrations, catalogs and license/notice files, checked
  member by member with `SHA256SUMS`; `init-db`, `serve`, `migrate`, `check-config`, backup, retention,
  `metrics-backfill` and `diagnose-cli`; `scripts/dev` for development (D043, D051). No hosted CI: the suites and
  package checks run locally (D230); versioning policy in the [changelog](../CHANGELOG.md). The repository is public;
  the protected `main` only carries releases merged from `develop` by pull request, and work goes through topic
  branches into `develop` (D235).
- **Real-provider evidence.** Historical evidence before `cli-14`: first real use to a closed phase, four
  reviewer/executor combinations COMMITTED (D071), and Django recipe creation through four tasks and phase closure
  on macOS ARM64/Python 3.13. Current-adapter evidence (October 2026, same platform): Claude Code 2.1.310 reviewer
  and Codex 0.164.0 executor, installed wheels and disposable synthetic projects. Two existing Django repositories
  were onboarded with originals intact and idempotent confirmation; a documented clone reached COMMITTED using a
  v8 declared profile, six validations/13 JUnit cases and native formatting (two files unchanged). Spanish
  TypeScript v2 creation, offline preparation, one task COMMITTED, a valid READY check, closure/tag/archive and an
  empty active successor were verified. Two chat answers, a deterministic command without a model and a confirmed
  proposal left QUEUED without execution were verified. Backup/restored API and Chrome UI preserved run/diff/JUnit/
  metrics evidence. No real Django v2 creation, other current-adapter pair or full language matrix is claimed.
- **Preserved failures and limits of that evidence.** Two Django task attempts ended at REVISION_LIMIT; no failed
  result was repaired or relabelled as success. Two TypeScript phase checks failed before a separately authorized
  document edit and a valid check. The chat proposal remains QUEUED. Restored consultation leaves historical
  process identity uncertain and does not certify stopped writers. These runs do not qualify production projects,
  compare model quality or prove undocumented CLI effects; conditional compatibility is unchanged.
- **Limits.** Cooperative containment without operating-system isolation (D064); validations without timestamps;
  recipe manifests fixed after preparation; only macOS ARM64 tested; first use from a clean clone rehearsed
  with fake CLIs only (no sign-in or real model calls); installed UI reviewed in Chrome only (en/es, light/dark,
  desktop/mobile), without other browsers or screen readers.

## Guided installation and configuration baseline

- `scripts/install` builds from a clone or consumes a self-contained package, creates a venv per generation and
  verifies the isolated installed wheel before publishing READY. Paths/caches are chosen explicitly, with spaces
  supported; offline is default and network downloads require `--allow-network`. `scripts/start` verifies the
  receipt, initializes only an absent database, keeps instance locks/signals and serves the packaged UI without Node.
- Authenticated `/setup` works without TOML or inference. Global v9/project v1 private TOML versions live outside
  checkouts; SQLite owns saved/active/pending references and recoverable CAS intentions. Form/TOML editors show
  exact diffs; saving and activating are separate. Since `0.1.2` a confirmed global or project set applies in the
  running service at an idle boundary (D238); only worker-loop service fields under a running supervisor and legacy
  import promotion still need a restart.
- Creation from documents and onboarding from a static committed inventory can start without a stack composition.
  The reviewer proposes a profile after context; confirmed documentary commit/P001, saved tool paths, bounded
  preparation, fresh validation receipt and separate activation precede the first task. Other stacks are supported;
  Django/TypeScript recipes remain optional. Later manual editing and optional assistance retain those gates and
  freeze active clients/context; they cannot change machine-wide settings or earlier job snapshots.
- Formats 1–8 preserve entry and hashes. Explicit conversion keeps legacy authority until converted profiles are
  newly prepared and the complete set is confirmed/promoted. Backup format 2 includes configuration versions,
  working copies, intents and referenced evidence. Query-only restore uses bundle bytes without original roots,
  clients or execution authority. Schema 0027 has 54 tables; data/flows are documented alongside the implementation.
- Installed first-use checks use fake Claude and Go tools, disposable projects and temporary Git/SQLite on macOS
  ARM64. Browser setup, protected HTTP journeys and visual checks are synthetic evidence; the real-provider scope
  above is unchanged. Final export/package qualification and release remain separate; no new publication is implied.

## Patch 0.1.3 — question-first answers and live activity (OT002)

[D240](DECISIONS.md#d240--question-first-answers-and-the-live-activity-rail): in onboarding, definition and phase
planning the reviewer's open questions come first, each with an answer field whose draft lives in browser local
storage; one answer, a selection or all prepared answers are sent after an explicit review as one ordinary planning
message (one turn), with states derived from the turns (draft, waiting, resolved, still asked, not reviewed) and
drafts for questions no longer asked offered for an explicit decision. Question, blocking, deferral and adoption rules
are unchanged. At the owner's request the release also uses the full window width and adds a sticky side rail
(container query) whose live activity folds the run's recorded events into plain-language steps on the project, phase,
task, run, chat and planning pages. Interface only: no API, schema or stored data change. Verified with offline suites,
synthetic component/request tests and synthetic Chrome QA against an in-browser API mock. Published as the GitHub
Release `v0.1.3` (tag on the release merge `64c21d0`) with a self-contained package built and checked locally; see
the [work notes](phase/OT002-question-answers.md).

## Patch 0.1.2 — live agent configuration (OT001)

[D238](DECISIONS.md#d238--live-configuration-switch-at-an-idle-boundary): a confirmed configuration set is staged
completely (client preflight, every registered project) before confirmation and applied in the running service
without restart or new login; with current work it waits as **Apply when current work finishes** and switches at the
first idle boundary, withdrawing itself if the candidate no longer composes. Admitted work keeps its frozen settings.
Task admission now binds the receipt selected for the frozen project revision, fixing refused tasks after derived or
agent-only revisions. Additive API (state `APPLY_PENDING`, `live_activation`, preview `apply`/`restart_fields`/
`waiting`, save `removed_fields`, structured 409 corrections); no schema or format change. Verified with offline
suites and synthetic en/es Chrome QA. Published as the GitHub Release `v0.1.2` (tag on the release merge `c606116`)
with a self-contained package built and checked locally; see the [work notes](phase/OT001-live-agent-configuration.md).

## Patch 0.1.1 — model selectors

Interface-only patch before P001
([D231](DECISIONS.md#d231--packaged-model-suggestions-and-small-ui-patch-releases)): the global setup chooses the
reviewer's model from packaged suggestions per provider with a hand-written **Other**, and project policies choose the
executor's models with checkboxes (preset models in `catalog` mode, otherwise suggestions plus models added by hand).
No configuration format, API contract or schema changes; only the shared version string moves to `0.1.1`. Covered by
the frontend suites; no visual QA was run for these controls. Published as the GitHub Release `v0.1.1` (tag on
`e252fdc`) with a self-contained package built and checked locally
([work notes](phase/v0.1.1-model-selectors.md)).

## Active phase — P001 Metrics Records (target: next patch after the one-off queue)

Documentation initialized on 2026-10-27 at the user's request
([D232](DECISIONS.md#d232--metrics-records-phase-and-accounting-boundaries)); reordered as P001 with target `0.1.2`
by [D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020), then moved after the
one-off releases by [D239](DECISIONS.md#d239--one-off-tasks-released-as-patch-versions).
The [handoff](phase/P001-metrics-records.md) records the implemented `metrics-1` baseline, missing billing inputs,
scope and verification matrix. [Reference notes](phase/P001-metrics-records-references.md) contain
official pricing sources, dated starter data and synthetic calculation examples. Detailed provider/model metrics,
independent USD/credit valuation and versioned reference records are planned, not implemented.
[NEXT_STEPS](NEXT_STEPS.md) now contains the six pending task sections with dependencies, scope, acceptance,
validation and deliverables; **next phase task is P001-T001**, the accounting contract/evidence inventory
([D234](DECISIONS.md#d234--p001-task-plan-in-next_steps)). No task is complete and technical design remains pending
T001. Assigning a release target does not release it.

## Planned phase — P002 Continuous Mode (target 0.2.0)

After Metrics Records, automate closing/archiving a completed phase and opening/planning its successor under one
explicit bounded authorization, retaining stop conditions, READY and recovery guarantees. Design and tasks remain
pending; this is not implemented
([D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020)).

## Bounded fix — activation after empty intake failure

On `fix/failed-intake-activation`, the work barrier no longer classifies a fully
failed, observed-unchanged, empty definition/onboarding conversation as adoptable
pending work. Real/uncertain jobs, answered turns, drafts, edits, deferrals,
proposals and other barriers remain protected (D236). Frozen histories are unchanged.
This source correction is separate from P001 Metrics Records; no P001 task is complete.
An explicitly authorized offline local upgrade installed the correction and
restarted the service, preserving configuration and historical rows; no release
was published. After the operator confirmed the normal activation preview, a second
restart promoted saved revision 3. The operator then restored the explicit client
paths/PATH in revision 4 and confirmed its activation; a further requested restart
promoted revision 4 with both clients at 3600 seconds. No new provider invocation was started.
Focused synthetic checks and limitations are recorded in
[the fix artifact](phase/failed-intake-activation.md).

## Patch 0.1.4 — onboarding profile adoption and joint document review (OT003)

Current definition/onboarding prompts explain logical executable aliases and exact direct-tool membership. Invalid
executable names now identify the command field/index without echoing candidate values; later planning contexts
carry prior failure reasons. The UI labels rejected document lists as unavailable to apply. Strict validation,
whole-turn failure, earlier proposals and explicit confirmations remain protected (D241).
The owner included the adoption blockers found in manual testing before commit (D244): informational notices no
longer prevent adoption, explicit blocking-question deferrals are respected, and missing/changed applied documents
have specific diagnostics. The UI explains the document/adoption order and disables redundant saves of unchanged
profiles. The owner also included a joint review of selected document proposals with one consent (D245), reusing
per-document CAS and stopping/reporting acknowledged progress on error or uncertainty. Profile/commit confirmations
remain separate. API descriptions/OpenAPI/types are in parity, with no response-shape or schema change.
Focused offline synthetic checks and frontend build passed. No real provider, preparation, production-data write,
release was performed. The owner-authorized offline local upgrade/restart subsequently completed successfully;
installed checks, HTTP/source/UI verification and unchanged conversation/proposal/configuration hashes are recorded
in the task artifact. Frozen histories/catalogs remain unchanged.
Released through PR #3 as 0.1.4, with full offline regression, package verification and matching GitHub downloads.
OT003 was removed from ONE_OFF_TASKS only after publication/verification (D242). Subsequent preparation diagnosis
and the owner's D246 priority decision now put OT005 before OT004.
See [OT003](phase/OT003-intake-profile-diagnostics.md) for results and limits. No Metrics Records task is complete.

## Patch 0.1.5 — read-only preparation tool aliases and complete review (OT005)

Generic preparation admits pre-existing read-only aliases outside private local paths only for explicitly declared,
resolved and hash-bound executables (D247/D248). New evidence freezes exact file/external-directory link chains,
modes and alias path sets through confirmation, scope guards, recovery and receipt verification. Checkout directory
links, unrelated/changed targets and protected links remain refused; old plans/receipts retain their original policy.
No extra write scope, environment accreditation, dependency, schema/configuration format or recipe-source change.
D249 makes generic scope/effects, executor details and exact nested commands visible without invented file hashes
or blank steps, retaining recipe review and the existing confirmation/activation gates.

Released as **0.1.5** through PR #4 and tag `v0.1.5` on `b0d035d`, with qualified final artifacts and matching GitHub
downloads. [Evidence and limits](phase/OT005-preparation-tool-links.md) include the synthetic matrix, full checks,
local upgrades and the owner's progress into ACTIVE preparation. Publication did not restart/reinstall the service or
invoke a real provider/project command. OT004 followed as 0.1.6; Metrics Records remains unimplemented.

## Patch 0.1.6 — visual profile and agent configuration editor (OT004)

[D250](DECISIONS.md#d250--guided-profile-and-agent-forms-over-the-existing-configuration-contract): guided forms over
the existing global/project tables. Globally: agent environment, version pin and tool capabilities, reusable
profiles, compositions and agent presets (recipes stay TOML-only). Per project, in Settings and the overview: profile
commands/JUnit/prefixes/paths/formatter/instructions, installed executables, command environment, authorization and
limits, and the project's agent copies, as the stage allows (`check_candidate`). Tool lists only for a Claude
executor; unsupported ones stay until explicitly removed. Client checks focus the field to correct; save reviews say
whether a new preparation is required and which derived copies only change their global reference. Frontend only:
no API, schema, format or dependency change. [Evidence](phase/OT004-visual-profile-editor.md) records 230 frontend
tests, build, full regression, distribution checks and synthetic Chrome QA. Released as **0.1.6** (PR #5, tag
`v0.1.6` on `0319b66`) with verified GitHub downloads.
