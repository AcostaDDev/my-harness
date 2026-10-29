# State — my_harness

No managed blocks: this repository is developed by hand and is not registered in a harness. The work done before the
first public snapshot is summarized below as the starting baseline; its decisions are in [DECISIONS](DECISIONS.md).
Detailed history up to the P001 closure is kept in the [P001 archive](archive/phase-001/STATE.md).

## Work routing

Read [ONE_OFF_TASKS](ONE_OFF_TASKS.md) before [NEXT_STEPS](NEXT_STEPS.md); the one-off queue is **empty**
([D237](DECISIONS.md#d237--one-off-development-queue-before-phase-work); later one-offs branch from the latest release
on `main`, D261). **P001 Metrics Records is closed** (D266): released as **0.1.9**, installed on the operator machine
and archived in [`archive/phase-001/`](archive/phase-001/SUMMARY.md). **Active phase: P002 Continuous Mode** (target
**0.2.0** at its closure, D253). The owner adopted the expanded autonomous-mode/database-authority plan as the
evolving baseline (**v0.3, 23 tasks**,
[D268](DECISIONS.md#d268--p002-scope-complete-roadmap-autonomy-and-evolving-plan-baseline)).
**P002-T001 is completed as design** ([contracts](phase/P002-T001-contracts.md), [flows](phase/P002-T001-flows.md),
[threat model](phase/P002-T001-threat-model.md), D268–D279) on `docs/p002-t001-contracts`, committed and merged
into develop at the owner's authorization. **P002-T002 is completed** ([feasibility](phase/P002-T002-feasibility.md);
D280–D281 accepted) on `docs/p002-t002-feasibility`, merged into develop and pushed with it. **P002-T003 is
completed** ([runtime record](phase/P002-T003-runtime.md); D282–D283 accepted) on `feat/p002-t003-langgraph-runtime`,
merged into develop and pushed: LangGraph 1.2.18 added under D280, schema `0029_graph_continuations`, a harness saver and
segment runner exercised by synthetic graphs only; no product behavior uses it yet. **P002-T004 is completed** ([knowledge record](phase/P002-T004-knowledge.md);
D284–D285 accepted) on `feat/p002-t004-structured-knowledge`, merged into develop and pushed: schema `0030_structured_knowledge` with
seven knowledge tables protected by triggers, a pure core and a repository exercised by synthetic knowledge only.
**Next: P002-T005**, not started. Historical starting
context: [P002 handoff](archive/phase-001/P001-T006-qualification.md#p002-handoff).
Develop with `scripts/check` and `scripts/check-docs` (D260) on topic branches from `develop` (D235).
Completed one-off records are in the [one-off archive](archive/one_off_tasks/README.md); earlier non-phase notes
are in [project history](archive/project-history/README.md). [D267](DECISIONS.md#d267--archive-completed-one-offs-separately-from-active-phase-work)
keeps main integration separate from pending publication/installation. `docs/phase/` now contains current P002 work.

## Releases

Each release went through a PR from `develop` to the protected `main`, a merge commit tagged `vX.Y.Z` and a GitHub
Release with the self-contained archive and checksum verified after download (D235, D239).

| Version | Content | Release merge | Evidence |
|---|---|---|---|
| 0.1.9 | P001 Metrics Records (D232–D266); includes OT008's development checks | [PR #8](https://github.com/AcostaDDev/my-harness/pull/8), `5cc1bc1` | [summary](archive/phase-001/SUMMARY.md) |
| 0.1.8 | OT007 managed-run lease renewal and stream journals (D252) | [PR #7](https://github.com/AcostaDDev/my-harness/pull/7), `c005298` | [OT007](archive/one_off_tasks/OT007-task-run-lease.md) |
| 0.1.7 | OT006 preparation consumption and output guard (D251) | [PR #6](https://github.com/AcostaDDev/my-harness/pull/6), `a3e9794` | [OT006](archive/one_off_tasks/OT006-preparation-consumption.md) |
| 0.1.6 | OT004 visual profile and agent configuration editor (D250) | [PR #5](https://github.com/AcostaDDev/my-harness/pull/5), `0319b66` | [OT004](archive/one_off_tasks/OT004-visual-profile-editor.md) |
| 0.1.5 | OT005 read-only preparation tool aliases (D247–D249) | [PR #4](https://github.com/AcostaDDev/my-harness/pull/4), `b0d035d` | [OT005](archive/one_off_tasks/OT005-preparation-tool-links.md) |
| 0.1.4 | OT003 intake diagnostics, adoption guards, joint document review (D241/D244/D245) | [PR #3](https://github.com/AcostaDDev/my-harness/pull/3), `9985b0a` | [OT003](archive/one_off_tasks/OT003-intake-profile-diagnostics.md) |
| 0.1.3 | OT002 question-first answers and live activity (D240) | `64c21d0` | [OT002](archive/one_off_tasks/OT002-question-answers.md) |
| 0.1.2 | OT001 live agent configuration (D238) | `c606116` | [OT001](archive/one_off_tasks/OT001-live-agent-configuration.md) |
| 0.1.1 | Model selectors (D231) | `e252fdc` | [notes](archive/project-history/v0.1.1-model-selectors.md) |

The bounded activation fix after an empty failed intake (D236) is documented in
[failed-intake-activation](archive/one_off_tasks/failed-intake-activation.md).

## Current operator installation

0.1.9 installed offline from the verified public package into the default paths: generation
**`gen-455d272577f142df8ba411dcce1c0b16`**, READY; earlier generations retained. The database was migrated
`0027_profile_proposals` → `0028_usage_accounting` with a verified snapshot under `My Harness/pre-migration/`; legacy
rows and configuration files are unchanged and the accounting tables start empty (no backfill, repricing or billing
profile). The service remains **stopped**; start it explicitly with `scripts/start`. The failed OT006 preparation
stays `FAILED` (retrying needs `Write`/`Edit` configured for the Claude executor, an operator action not performed).

## Accumulated baseline

What exists and works at the first public snapshot, verified offline with temporary Git repositories, SQLite and
processes, fake agents and synthetic data unless stated otherwise. First local version complete within the scope
described in the [supported scope](../README.md#supported-scope-and-limits); first published as `0.1.0`/`0.1.1`, now
`0.1.9` (see [Releases](#releases)).
The real validation originally deferred in D151 now has the bounded evidence below.

- **Engine.** Package `my_harness` with an explicit context per project, frozen task contracts, planning by the
  reviewer or deterministic from `NEXT_STEPS`, the execute → format → validate → review loop with a correction limit,
  acceptance bound to the exact content and a reconcilable commit made by the harness (D052, D056, D129, D133).
- **Persistence and recovery.** SQLite schema `0028_usage_accounting` managed by Alembic (released in 0.1.9; the
  operator database is migrated; unreleased develop adds P002-T003's `0029_graph_continuations` and P002-T004's
  `0030_structured_knowledge`); idempotent job queue
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
  member by member with `SHA256SUMS`; `init-db`, `serve`, `migrate`, `check-config`, backup/upgrade, retention,
  `metrics-backfill`, explicit accounting operations (T003) and `diagnose-cli`; `scripts/dev` for development (D043, D051). No hosted CI: the suites and
  package checks run locally (D230); versioning policy in the [changelog](../CHANGELOG.md). The repository is public;
  the protected `main` only carries releases merged from `develop` by pull request, and work goes through topic
  branches into `develop` (D235).
- **Usage accounting (P001, 0.1.9).** One invocation record per managed attempt, executor preparation step and
  configuration assistance with an allowlisted `usage-capture-1`; pinned `metrics-reference-1` references and a pure
  Decimal calculator; optional `local-config-10`/`project-config-2` billing profiles frozen at admission; explicit
  previewed reference import, backfill and repricing cohorts; read-only `/api/managed/accounting/*` and the
  **Accounting** page (also on archives); format-3 backups with `backup-upgrade`. `metrics-1` and its endpoints are
  unchanged. Synthetic evidence only; missing evidence stays unknown (D254–D266,
  [summary](archive/phase-001/SUMMARY.md)).
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
  working copies, intents and referenced evidence; T003's format 3 adds verified accounting records and an explicit
  `backup-upgrade` copy for older bundles. Query-only restore uses bundle bytes without original roots, clients or
  execution authority. Schema 0028 has 62 tables; data/flows are documented alongside the implementation.
- Installed first-use checks use fake Claude and Go tools, disposable projects and temporary Git/SQLite on macOS
  ARM64. Browser setup, protected HTTP journeys and visual checks are synthetic evidence; the real-provider scope
  above is unchanged. Release evidence is recorded per version below.

## Active phase — P002 Continuous Mode (target 0.2.0)

Automate closing/archiving a completed phase and opening/planning its successor under one explicit bounded
authorization, retaining stop conditions, READY and recovery guarantees ([ROADMAP](ROADMAP.md#p002--continuous-mode),
[D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020)). Opened at the P001 closure
without tasks. The owner broadened it to whole-roadmap autonomy with LangGraph orchestration, database-owned
structured knowledge, generated documents with explicit UI import, client-neutral discoverable tools, a configurable
judge, permanent revocable grants, correlated tracing, a global inbox and a task-instance graph; D268 supersedes
D156. The [discussion](phase/P002-autonomous-mode-discussion.md) and [design basis](phase/P002-design-basis.md) are
preserved. **T001 (completed as design, integrated into develop)** formalized the supersession map, authority invariants,
judge/permission/tool/autonomy/trace contracts, flows FL01–FL14 with guards and recovery, threats TM01–TM20, gates
G01–G17 with owning tasks and requirement coverage; SPECIFICATION §14 and ARCHITECTURE §13 carry the design labelled
not implemented. **T002 (completed, integrated)** characterized LangGraph 1.2.18 (lockable with 27
additions and no pin change, offline install, re-executed nodes, silent graph-version drift, hosted tracing by
inherited environment) and the per-invocation MCP broker on Claude Code 2.1.312 and Codex 0.165.0 with 14 bounded
real runs; D280 (dependency set and placement) and D281 (transport and minimum capability contract) are accepted.
[NEXT_STEPS](NEXT_STEPS.md) holds plan v0.3. **T003 (completed, integrated)** added the LangGraph runtime foundation
(D282–D283), the only dependency adopted (D280); **T004 (completed, integrated)** adds structured knowledge
with immutable accepted revisions (D284) and canonical database instructions (D285); T005–T023 are planned. No
OpenCode adapter exists, and installed behavior remains 0.1.9.
