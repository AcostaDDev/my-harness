# State — my_harness

No managed blocks: this repository is developed by hand and is not registered in a harness. The work done before the
first public snapshot is summarized below as the starting baseline; its decisions are in [DECISIONS](DECISIONS.md).

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
  package checks run locally (D230); versioning policy in the [changelog](../CHANGELOG.md).
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
  exact diffs; saving and activating are separate. Global activation requires restart; project activation happens
  between tasks after preparation/receipt checks and the work barrier.
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

## Patch 0.1.1 — model selectors

Interface-only patch before P001
([D231](DECISIONS.md#d231--packaged-model-suggestions-and-small-ui-patch-releases)): the global setup chooses the
reviewer's model from packaged suggestions per provider with a hand-written **Other**, and project policies choose the
executor's models with checkboxes (preset models in `catalog` mode, otherwise suggestions plus models added by hand).
No configuration format, API contract or schema changes; only the shared version string moves to `0.1.1`. Covered by
the frontend suites; no visual QA was run for these controls. Published as the GitHub Release `v0.1.1` (tag on
`e252fdc`) with a self-contained package built and checked locally
([work notes](phase/v0.1.1-model-selectors.md)).

## Active phase — P001 Optional continuous mode between phases

No notes yet. The phase has no tasks: its design and plan are pending (see [NEXT_STEPS](NEXT_STEPS.md)).
