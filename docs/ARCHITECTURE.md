# Architecture — My Harness

Stack, modules, patterns and conventions in force. Requirements: [SPECIFICATION](SPECIFICATION.md). Data:
[DDBB-DIAGRAM](DDBB-DIAGRAM.md). Flows: [docs/flows](flows/task-run.md). Installation and operation for users:
[README](../README.md).

## 1. Stack

| Layer | Choice and exact version |
|---|---|
| Core | Python 3.14.4, standard library, package `my-harness` 0.1.1 (`uv_build==0.12.19`) |
| Local API | FastAPI 0.143.0, Pydantic 2.14.0, Uvicorn 0.54.0; HTTP for actions and cursor-based observation of managed runs |
| Persistence | SQLite with SQLAlchemy 2.1.4 and Alembic 1.20.0 (schema `0028_usage_accounting`) |
| UI | React 19.3.0, TypeScript 5.9.3, Vite 8.3.4; `markdown-it` 15.0.2 (`html: false`) and `mermaid` 11.17.2 (`strict`) |
| Client types | `openapi-typescript` 7.13.0 from the exported OpenAPI |
| Tooling | uv 0.12.19 and `uv.lock`; Node 24.15.0, npm 11.12.1 and `frontend/package-lock.json` |
| Tests | `unittest` (dependency-free checks), pytest 9.1.1 + httpx 0.28.1 + pytest-xdist 3.8.0, `node --test` |
| Agents | Automatic discovery from Codex 0.163.0 / Claude Code 2.1.304; later releases with conditional compatibility, adapter `cli-14` ([D174](DECISIONS.md#d174--automatic-clients-and-conditional-compatibility)) |

No Celery, broker or Docker for the service ([D003](DECISIONS.md#d003--local-queue-without-celery),
[D004](DECISIONS.md#d004--native-service-containers-only-in-project-profiles)). Stack details of each managed project
(Django, Node…) belong to profiles, not to the core.

## 2. Components

```text
Browser (React, own routes over the History API)
   │ HTTP, local session + Host/Origin + CSRF
Local service (FastAPI + supervisor in a single Uvicorn process)
   ├── api/          /api/managed routes, session and guard
   ├── services/     supervisor, managed runtime, local TOML, registry, creation and preparation
   ├── core/engine/  engine: context, contracts, workflow, phases, documents, chat, definition, metrics
   ├── storage/      SQLite: operational authority, queue, journal, views
   └── adapters/     agent CLIs, commands, Git, processes and exports
Local application folder: SQLite, artifacts (streams, captures, copies), backups
```

The core (`core/`) does not import FastAPI, React, provider SDKs or stack rules: only the standard library,
`my_harness.core` and, as its single external leaf, the `my_harness.i18n` catalogs (standard library only). API
and CLI call the same use cases. The supervisor is the only component that launches processes and consumes the
queue; closing the browser does not cancel work.

## 3. Modules (`src/my_harness`)

| Module | Responsibility |
|---|---|
| `core/engine/context.py` | `ProjectContext`, profile, policy, commands; explicit context per project |
| `core/engine/contracts.py`, `planning.py` | Task contract, protected paths, deterministic planning from NEXT_STEPS |
| `core/engine/workflow.py`, `validation.py`, `review.py`, `acceptance.py`, `junit.py` | Plan → execution → validation → review → acceptance loop |
| `core/engine/commit.py`, `evidence.py`, `serialization.py` | Commit intent, mechanical updates, history codec (writes format 8; reads 1–8) |
| `core/engine/phases.py`, `storage/closure.py`, `storage/phase_plan.py` | READY check, unified closure and archive, tags, abandonment and confirmed later plan |
| `core/engine/documents.py`, `document_ops.py`, `document_export.py`, `document_text.py` | Documentation contract, template, managed blocks, archive, edits, export, reconciliation of earlier transitions and en/es vocabulary |
| `core/engine/definition.py`, `bootstrap.py`, `bootstrap_discovery.py` | Conversational definition and the bootstrap root commit; earlier one-shot discovery is only reconciled for recorded runs |
| `core/engine/chat.py`, `chat_commands.py` | Chat turns and command grammar |
| `core/engine/prompts.py`, `templates/*.md`, `language.py` | Versioned prompt catalog and variables; language directive sealed outside the templates |
| `core/engine/permissions.py`, `metrics.py` | Permissions by category and layer; `metrics-1` catalog |
| `core/project_onboarding.py`, `adapters/project_onboarding.py` | Onboarding: static inventory of HEAD (stack, entities, routes, tests and CI) and a profile proposal pending confirmation |
| `storage/onboarding.py`, `storage/onboarding_commit.py`, `core/engine/onboarding_commit.py` | Onboarding: reverse engineering, private drafts and confirmed documentation commit with profile and adopted P001 |
| `core/engine/import_commit.py`, `storage/project_import.py` | Shared onboarding infrastructure: documentation adoption, commit intent and recovery (historical table and purpose names kept) |
| `adapters/import_git.py`, `adapters/local_git.py`, `core/tree.py`, `storage/private_drafts.py` | Local Git objects, writer guards, tree entries and CAS drafts shared by onboarding and preparation |
| `core/managed_mode.py`, `adapters/managed_mode.py`, `storage/managed_mode.py`, `storage/retired_work.py` | Read-only compatibility with earlier activations and quarantine of retired or ambiguous work ([D161](DECISIONS.md#d161--retirement-of-the-previous-harness-support)) |
| `adapters/cli_agents.py`, `cli_compatibility.py`, `cli_diagnostics.py`, `streams.py`, `processes.py`, `process_gate.py` | Capability policy, discovery and local identity, per-attempt preflight, incremental capture and process groups |
| `adapters/commands.py`, `git.py`, `bootstrap.py`, `chat_snapshot.py` | Native validations (`commands-1`), Git, root commit, HEAD snapshot |
| `storage/*.py` | SQLAlchemy repositories by area (`managed`, `phases`, `documents`, `transition`, `planning`, `chat`, `metrics`, `registry`, `backup`, `retention`, `migrate`…) |
| `storage/run_projection.py`, `managed_views.py` | Derived `run-projection-1` projection written with the history, and run views that only read it |
| `services/managed.py`, `managed_runtime.py` | Supervisor (`run_once`, lease, quarantine) and runtime composition |
| `services/local_config.py`, `project_registry.py`, `project_creation.py` | `local-config-8` TOML (reads 1–7), automatic CLIs; registration and creation, presets, recipe generations, work language sealed at registration |
| `recipes/`, `services/project_preparation.py`, `storage/preparation.py`, `adapters/preparation.py` | Packaged recipes (`django-recipe-1/2`, `typescript-web-recipe-1/2`) and their confirmed, recoverable preparation |
| `api/app.py`, `managed.py`, `schemas.py`, `session.py`, `security.py` | Application, routes, Pydantic contracts, session and guard |
| `profiles/` | Built-in profile `typescript-web` (composable); TOML profiles are composed in `services/local_config.py` |
| `cli.py`, `launcher.py` | `my-harness` (`init-db`, `serve`, `migrate`, `check-config`, backup/upgrade, retention, `metrics-backfill`, accounting operations, `diagnose-cli`); `--ui-language` per invocation |
| `storage/preferences.py`, `i18n/` | Global language preferences with CAS, capture of the interface language when admitting each job, en/es catalogs of own messages; `tr()` emits in the language of each emission |
| `storage/work_language.py`, `services/work_language.py` | Immutable work language per root, `language-context-1` pair per job and attempt, explicit confirmation from absent to a value |
| `migrations/versions/0001…0027` | Alembic schema |

`frontend/src`: `router.ts`, `pages/` (Home, Registry, Project, Phases, Task, Run, Docs, Planning, Preparation, Stats,
Accounting, Settings, Preferences), `i18n.ts`, `i18n/{en,es}.json` and `Language.tsx` (catalogs and interface language
provider), `markdown.ts` and `mermaid-view.ts` (isolated rendering), `managed-api.ts` (idempotent submissions),
`api.generated.ts` (generated, never edited). `scripts/`: `dev`, `export_openapi.py`, `build_distribution.py`,
`check_distribution.py`, `smoke_cli.py`. `examples/`: the `local_config.example.toml` template, the minimal
one-provider example, v2 recipe fragments and a synthetic demo.

## 4. Patterns

- **Explicit, frozen context.** Each run freezes context, profile, policy, contract, prompt catalog, versions
  (adapters, composition, engine) and language pair by hash. A different version at execution time quarantines the
  job before effects; a frozen history is never rewritten.
- **Persisted jobs.** SQLite queue with `Idempotency-Key`, `expected_version`, lease and heartbeat; exclusion per
  canonical root (`checkout_locks`). Separate writer and chat lanes
  ([D083](DECISIONS.md#d083--chat-over-a-head-snapshot-in-its-own-lane)).
  D252: transient renewal failures retry within the existing lease and are recorded at owner closure; lost ownership
  still fences every effect. CLI read chunks journal their events in one transaction, preserving each sequence.
- **Intent before effect.** `CommitIntent` seals tree, message, identity, date and commit id before writing; after a
  crash the same commit is reconciled. The same applies to tags, bootstrap, export, edits, onboarding, creation and
  preparation.
- **Document CAS.** Every harness write admits only the previous hash or the sealed bytes.
- **Content-bound evidence.** Git capture by trees (worktree and index) and fingerprint; validations and review are
  bound to that content.
- **Managed blocks.** Deterministic projections of SQLite between markers; regenerated and compared, never read as a
  source.
- **Provenance.** Each datum distinguishes requested, reported, derived, measured or absent.
- **Conservative recovery.** `RECOVERY_REQUIRED` until the user confirms that the writer stopped.
  The closing managed owner settles its unfinished process rows from independent group liveness, preserving partial
  captures and reported/observed group states. This neither completes an attempt nor releases the checkout lock.

## 5. Persistence

SQLite is the operational authority (runs, attempts, jobs, phases, permissions, conversations, metrics, registry,
preferences). Git keeps code and documents. Markdown keeps the intent (requirements, architecture, phases,
decisions). Schema and relations in [DDBB-DIAGRAM](DDBB-DIAGRAM.md). Streams and captures live outside SQLite,
written with fsync and hash; retention purges them only with authorization and keeps metrics and verdicts. Backup
copies SQLite through its API together with the referenced artifacts; a restore is query-only (`query_only`).
The persistent restore mark, exposed as `SupervisorRead.read_only_archive`, enables standalone archive views without
configured projects, a checkout or supervisor. All mutations retain their 409 guard
([flow](flows/backup-consultation.md)).
`migrate` upgrades an existing database after a verified snapshot ([flow](flows/database-migration.md)).

## 6. Agents and configuration

- **Adapter `cli-14`.** A new session per attempt; explicit argv, environment (nothing inherited, `USER` checked
  against the UID, [D024](DECISIONS.md#d024--agent-environment-with-user-checked-against-the-uid)) and timeouts.
  Read-only reviewer: Codex `--sandbox read-only`; Claude Code `--restricted` with a typed `--json-schema`
  ([D058](DECISIONS.md#d058--typed---json-schema-for-claude-read-only-roles)). Codex executor in `workspace-write`
  with the checkout as its only writable root and an inline `untrusted` trust entry
  ([D059](DECISIONS.md#d059--codex-writer-with-explicit-writable-roots), [D068](DECISIONS.md#d068--codex-writer-trust-entry));
  Claude Code executor with declared tools and `dontAsk`, without a shell
  ([D121](DECISIONS.md#d121--claude-executor-without-a-shell)). Automatic memory is disabled in both
  ([D066](DECISIONS.md#d066--automatic-agent-memory-disabled-durable-context-in-documents)). No CLI loads the
  checkout instructions by itself: Claude Code runs with `--setting-sources ""` and Codex with a project-docs budget
  of 0; the engine injects `AGENTS.md` into the prompt of the roles on existing projects, and the `definition` role
  (definition and onboarding) writes it or analyzes it as evidence. Executor and reviewer outputs may carry decision
  proposals. The `definition` role works on read-only exports, where Codex skips its Git check
  ([D123](DECISIONS.md#d123--codex-refuses-a-working-directory-outside-git),
  [D124](DECISIONS.md#d124--codex-defines-a-new-project-outside-git)).
- **CLI compatibility.** Common minimums Codex 0.163.0 / Claude Code 2.1.304. Later releases are admitted by the
  known contract without a per-patch allowlist; their compatibility is conditional and no internal effect is claimed
  as observed. Version, launch fingerprint and policy are frozen per job; a fresh observation and argv validation per
  attempt, plus an identity check before GO. Drift leads to refusal or quarantine, without retry or provider
  substitution ([flow](flows/cli-compatibility.md)). The `cli_agents.SUPPORTED`/`WRITE_SUPPORTED` lists keep historical
  evidence and are no longer admission allowlists.
- **Legacy operator TOML** (`local-config-8`; 1–7 still readable; v9 authority is described in §11), outside every checkout and `chmod 600`: `[service]`,
  `[git]`, `[agents.reviewer]`, `[agents.executor]`, `[registration]` (roots and bootstrap ceiling), optional
  `[profiles.*]`, `[compositions.*]` (built-in or declared profile and authorized commands), optional `[[projects]]`
  with its policy, `[agent_presets.*]` with an optional `agent_selection` per project, `work_language` per project and
  `[recipes]`. No secrets. v7 lets agents and presets omit `executable` and `cli_version`: the selected providers are
  resolved on their explicit `PATH`, or on the optional path, without inheriting the environment. Parsing starts no
  process; startup and admission observe version and help before freezing the real version. Each mutation observes
  again and reuses its resolution only within that request; passive reads do not. Earlier formats keep their hashes
  and assertions but do not bypass the minimums. Confirmed changes serialize registration and admission in SQLite;
  proposed plans become `SUPERSEDED` without altering their snapshots ([flow](flows/project-agents.md)). The public
  catalog omits executables and environments. v8 adds optional declared-profile formatting; per-project preset
  selection is available in registration, creation and settings in v5–v8.
- **Profiles**: built-in in `profiles/` or declared in `[profiles.<name>]`
  ([D095](DECISIONS.md#d095--declared-profiles-in-local-config-4)): preparation and validations as argv without a shell,
  JUnit next to its validation, prefixes, protected and sensitive paths, `data_model_paths` and executor
  instructions. The profile content enters the frozen hash of the composition. Example `python-django` in
  `examples/local_config.example.toml`. v8 optionally accepts `formatter_argv` and `formatter_paths` together:
  non-empty argv ending in `--`, mapped executable, unique relative patterns and profile-command authorization.
  Omission retains the effective profile hash; v1–v7 keep their rules
  ([D194](DECISIONS.md#d194--optional-formatter-for-declared-profiles)).
- **Native validations** (`commands-1`): absolute executables, authorization per complete command, bounded capture in
  SQLite, POSIX groups. A task command with the argv of a profile validation run at the root without extra
  environment is that validation (its timeout) and runs once. The profile formatter is authorized separately (`formatter-paths`): its argv followed only by
  existing checkout files; the engine runs it after each executor turn
  ([D133](DECISIONS.md#d133--the-harness-runs-the-profile-formatter-after-each-executor-turn)).
- **Prompts** (`templates/`): `plan-task`, `execute-task`, `revise-task`, `review-task`, `executor-routing`,
  `close-phase`, `reconcile-phase`, `chat-turn`, `define-project`, `plan-phase`, `onboard-project` (read-only
  `definition` role, without injected `AGENTS.md` because it is part of the source) and `bootstrap-project`. Hierarchy
  base → profile → project; snapshot per attempt. `AGENTS.md` (≤32 KiB) enters through `{{PROJECT_INSTRUCTIONS}}` in
  every role except definition, with path, hash and size in the snapshot; without it, the attempt stops before
  invoking ([D094](DECISIONS.md#d094--agentsmd-in-every-frozen-prompt)). With the job's `language-context-1` pair,
  `render_attempt` adds the `language-directive-1` directive before the schema and seals it in the snapshot; jobs
  without a pair render as before ([D169](DECISIONS.md#d169--sealed-language-directive-generated-documents-in-the-work-language)).
  The frozen `document_layout` stops earlier jobs before effects. The managed-mode marker is excluded from Git only
  when validated by this installation's guard ([D099](DECISIONS.md#d099--managed-mode-marker-stays-untracked)). The
  retired import template is readable as historical data but never edited, activated or rendered for invocation.
  Sealed transitions keep their reconciliation with the original bytes. The planning prompt includes the instructions
  and DDBB-DIAGRAM among its context documents.
- **Git boundary of onboarding and preparation.** `adapters/import_git.py` keeps blobs by hash and refuses clean and
  process filters (includes too), gitlinks in HEAD or the index and new ignored targets. `storage/project_import.py`
  keeps the onboarding intent and repeats the guards before capturing, sealing, executing or reconciling.
  `adapters/local_git.py` requires complete local objects and `--no-lazy-fetch` in every writer and reader operation,
  without fallback or transport. The final seal requires the shown tree; attribute conversions cannot change confirmed
  bytes ([flow](flows/project-onboarding.md#git-boundary)).
- **Onboarding inventory**: Python AST, JSON and TOML manifests and a lexical subset of JS/TS/Prisma, standard library
  only. It reads blobs of a sealed Git tree, without `status`, filters or project code, and excludes installed
  dependencies and builds even when they are versioned. Each entity and route cites its source and line; routes are
  local declarations, without expanding mounts or imports. It proposes commands with argv, cwd and evidence in the
  `[profiles.*]` shape; it neither writes the TOML nor authorizes execution.

## 7. API, UI and security

- `/api/managed`: projects, registry, creation, preparation, runs, jobs, attempts, paginated diffs, permissions,
  phases, documents, chat, planning, onboarding, metrics and preferences. `onboarding` conversations use planning;
  `GET …/projects/{p}/onboarding` and `POST …/planning/{c}/onboarding/preview` / `…/onboarding/confirm` confirm
  documents and `profile_sha256`. `GET …/projects/{p}/mode` only diagnoses managed admission. Mutations carry an
  `Idempotency-Key` and an expected version; 409 with `{code, diagnostic}`; 422 on an invalid contract.
- `GET/PUT /api/managed/preferences`: global languages with an expected version and `Idempotency-Key`; each job
  exposes the `language_context` sealed when it was admitted ([flow](flows/language-preferences.md)).
- Work language ([flow](flows/project-work-language.md)): `work_language` is required in registration
  (`/registry/preview|apply`, action `register`) and creation (`/project-creations/*`), and refused with 409
  `work_language_immutable` in changes and unregistrations; `POST …/projects/{p}/work-language/preview` and
  `…/work-language` (hash and reason) for projects without a value. Without it, every new admission answers 409
  `work_language_required`. Projects, registrations, jobs and attempts expose the value or frozen pair.
- UI routes: `/`, `/stats`, `/accounting`, `/preferences`, `/projects/new`, `/projects/:p` with `setup`,
  `onboarding[/:c/*draft]`, `chat[/:c]`, `docs[/*path]`, `phases`, `phases/:code`, `phases/:code/plan[/:c]`,
  `phases/:code/tasks/:task[/runs/:run]`, `stats`, `accounting`, `settings`; `/runs/:id` redirects to the canonical project route
  in ordinary mode and opens a standalone evidence view in marked query-only copies. The archive home accepts a
  run id; operational routes and pending submissions are not mounted, and recorded active states do not trigger
  execution polling. Routes of the retired
  support show not found ([compatibility](flows/legacy-compatibility.md)).
- UI layout ([D240](DECISIONS.md#d240--question-first-answers-and-the-live-activity-rail)): pages use the full
  width. `Workbench` places a sticky side rail beside the main column when the body is at least 800 px wide (a CSS
  container query, so it also works beside the chat list or the draft tree) and below it otherwise; the main column
  comes first in reading and keyboard order. The rail of project, phase, task, run, chat and planning pages is the
  live activity of the relevant run (`Activity.tsx`, pure folding in `run-activity.ts`), read from the run events
  endpoint. Answer drafts of documentary conversations (`pages/Answers.tsx`, `answers.ts`) live in browser local
  storage and are sent as ordinary planning messages; no endpoint or stored data was added.
- Security: loopback only; an ephemeral session key in a private file and an eight-hour HttpOnly cookie; exact Host
  and Origin; CSRF header `X-My-Harness: 1` on mutations; `Sec-Fetch-Site: cross-site` refused
  ([D079](DECISIONS.md#d079--cross-site-navigations-rejected)). Markdown without HTML, Mermaid drawn as an image,
  checkout images with a `sandbox` CSP.

## 8. Conventions

- Code, comments, docstrings, OpenAPI descriptions, prompts and this repository's documentation are in English
  ([D163](DECISIONS.md#d163--code-in-english-and-v2-recipes)); canonical file names are English and the parsers
  accept English and Spanish aliases. v1 recipe sources keep their bytes because they enter fingerprints.
- Documents the harness generates in a project (blocks, documentation template, archive and records) follow its work
  language (`core/engine/document_text.py`); a context without one keeps the historical Spanish bytes.
- Visible messages live in the en/es JSON catalogs ([D166](DECISIONS.md#d166--global-language-preferences-and-catalogs)):
  one complete message per key, `{name}` parameters as text, English fallback. Every own service or CLI text comes from
  `i18n.tr()` in the language of the emission ([D171](DECISIONS.md#d171--service-and-cli-texts-in-the-language-of-each-emission),
  [D172](DECISIONS.md#d172--service-texts-in-both-languages-rejections-distinguished-by-code)); only internal
  invariants and what enters an agent's input stay in technical English, listed in
  `tests/fixtures/service_texts/english.json`. The client tells refusals apart by `code`, never by diagnostic text.
- Exact versions; no new dependency without a recorded decision. Never document scripts that do not exist.
- Client types are always regenerated from OpenAPI after changing a contract; never by hand.
- Offline tests with temporary Git and SQLite, fake processes and agents and synthetic data; never real runs or
  private data. pytest runs in parallel by default (`-n auto`,
  [D125](DECISIONS.md#d125--parallel-pytest-suite-and-fork-free-git)); `-n 0` runs it serially.
- Parity: a model or migration change updates `DDBB-DIAGRAM.md`; a flow change, `docs/flows/`. In managed projects,
  the profile's `data_model_paths` blocks acceptance without the diagram and the reviewer requires the flows.

## 9. Development and operation

Installation, checks, client type regeneration, package build and verification, configuration, the first run,
restart, update with `migrate`, backup and uninstallation are in the [README](../README.md#development). Real use
always runs from the installed wheel, never from the development checkout
([D051](DECISIONS.md#d051--real-use-from-the-installed-wheel-never-from-the-development-checkout)); `scripts/dev`
is for development only and creates or migrates its own database (`.local/harness.sqlite3`) after a snapshot.
`init-db` and `serve` keep creating a new database and starting without migrating
([D043](DECISIONS.md#d043--local-distribution-with-assets-and-migrations-explicit-start-on-loopback)).
`build_distribution.py` writes into a new or empty folder: the UI built from the npm lock, the sdist and the wheel
(sources, UI assets and the `LICENSE`/`NOTICE*` files), `pylock.toml` (the service dependencies with the URL and
hash of every wheel, installable offline) and `SHA256SUMS`. `check_distribution.py` verifies the exact members,
metadata, license files, checksums, absence of retired components and one version for package, API and UI, then
installs the wheel in an isolated venv and runs a synthetic journey. There is no hosted CI: these suites and package
checks run locally (D230).

`serve` writes the session key (`harness-session-*/login-key`, 0700/0600, deleted on exit) and temporary Git indexes
and seals (`harness-git-*`, `harness-bootstrap-*`) under the process `TMPDIR`. Without it, Python uses the system
temporary folder (`/var/folders/…` on macOS), outside the operating area. To keep them inside, start `serve` with
`TMPDIR` pointing to a 0700 folder of that area, as `check_distribution.py` does
([D126](DECISIONS.md#d126--package-verification-through-the-definition-flow-private-tmpdir)). Recipe commands do not
inherit that value: they receive their own `HOME`/`TMPDIR` inside the child.

## 10. Known limits

- Cooperative containment (POSIX groups, paths, each CLI's sandbox); no operating-system isolation
  ([D064](DECISIONS.md#d064--cooperative-containment-without-operating-system-isolation),
  [D065](DECISIONS.md#d065--nested-sandbox-profiles-not-qualified)).
- Validations do not record their time. Run views, metrics and the export preview read `run-projection-1`; the
  transition, the task commit and the rest of the engine read the history.
- A manifest pinned by a recipe (Django or TypeScript web) does not accept new dependencies after preparation; that
  needs a future confirmed flow. Created and onboarded projects bring their own `package.json`.
- The `typescript-web` profile protects `package.json`, `package-lock.json`, `tsconfig.json`, `scripts/**` and
  `tests/**` from the normal executor: the executor does not create or modify files under `tests/`.
- After a reboot that renumbers the disk device, creating another project requires choosing the projects folder again.
- Real-provider evidence is limited to macOS ARM64 and the recorded versions and journeys. With `cli-14`, Claude
  Code 2.1.310 reviewer → Codex 0.164.0 executor covers synthetic Django onboarding/declared-profile work, Spanish
  TypeScript v2 through closure, chat and backup/restore consultation. Four-combination and Django-recipe evidence
  predates this adapter; Django v2 creation, other current pairs, full language coverage and production projects
  remain unqualified ([scope](../README.md#supported-scope-and-limits)). Failed attempts/checks and uncertain
  historical process identity are preserved; consultation does not authorize resumption or certify stopped writers.
- Two *low* KaTeX advisories in Mermaid 11.

## 11. Versioned configuration and profile lifecycle

`services/configuration_setup.py` chooses authority before composing clients. `configuration.py` and
`storage/configuration.py` validate immutable TOML and journal CAS save/activation; `configuration_files.py`
publishes private files with atomic replacement. `configuration_editing.py` derives private project copies and
impact previews; `configuration_assistance.py` freezes active clients, context, process ownership and result.
`configuration_import.py` explicitly converts legacy sources without replacing legacy authority before preparation.
The shared registry work barrier excludes only empty, observed-unchanged failed intake conversations
with no surviving drafts, edits, deferrals or proposals (D236). Job/writer and adoptable-work gates remain;
activation never retries or rewrites earlier turns.

Live switching (D238): `storage/configuration.py` classifies a set (`restart_fields` hook from the runtime) and
splits current work (`_waiting`) from documentary refusals; a live set is recorded in the existing pending columns
with `apply: live` (scope status APPLY_PENDING) and promoted by `promote_pending`, or withdrawn by `fail_pending`.
`ManagedRuntime._stage` builds a shadow runtime (copied runtime with its own composer, registry, project
configuration and preparation services) from explicit candidate references; `apply_pending` runs from the idle
writer lane, configuration reads/confirmations and startup, and installs the staged configuration and project map
inside the promotion transaction. `require_ready` keeps refusing writes whenever the loaded and active global
references differ. Worker loops resolve ports/writer factories through the runtime on each claim. Task admission
binds the receipt selected for the frozen project revision (`selected_receipt`).

`IntakeContext` carries documentary capabilities without an executable profile. `profile_proposal.py` validates
structured commands/tool evidence against frozen documents/inventory; planning tables retain proposal versions.
`project_configuration.py` binds accepted proposals to confirmed documentary commits and private profile versions.
`profile_preparation.py` reuses preparation operations, locks, leases and process identities for the generic
`project-profile-preparation-1` contract, exact argv, JUnit, reconcilable technical commits and receipts. Activation
precomposes and verifies exact saved references before exposing a runnable `ProjectContext`.
`frontend/src/pages/PreparationReview.tsx` renders generic path/effect scope and kind-based/nested command steps
separately from recipe file content/diffs/hashes (D249). The shared preparation helpers name those steps in both
preview and journal and give own profiles generic network-mode wording. Request/consent/receipt authority is unchanged.
D247 adds optional inline `read_only_tool_links` evidence to new generic plans/receipts. File-link chains outside
`local_paths` resolve through at most 40 links to a declared frozen tool. D248's new `tool_link_policy` marker
`external-directories-1` explicitly resolves and binds external directory aliases along that exact tool chain; parent
access still uses `O_NOFOLLOW`, and directory links inside the checkout remain refused. File/directory links share
the ceiling; no external directory is enumerated. Plans without the marker retain the strict D247 resolver. Snapshots
and post-effect guards reverify tool hashes and exact chain text/modes; receipt verification also checks the complete
captured alias path set. Recovery preserves the original opt-in/policy marker or historical policy. D251: preview and
launch require a usable Claude file-writing tool for an executor with write scope (shared `inventory`/`write_tools`
with the argv). `streams.OutputGuard` (`output-guard-1`) stops degenerate repetitive Claude text. The preparation
agent journal records each chunk's events in one transaction. Heartbeat failures are retried within the lease and
reported at settlement. An interrupted invocation leaves `capture.json`, which the closing owner settles from
independent group liveness. Protected links
remain refused, stable-environment evidence is separate, and recipe fingerprints/sources are unchanged.

Alembic 0026 adds three configuration tables (scope references, revisions and operations); 0027 makes registered
composition/profile nullable for documentary intake; 0028 adds the P001 accounting records (§12), for 62 tables.
JSON journals extend existing operations without changing legacy histories. Backups (format 3 since 0028) inventory immutable/working configuration, partial intents and
referenced evidence; restore reads its bundle and never executes stored paths. See [data](DDBB-DIAGRAM.md#versioned-configuration)
and [flow](flows/configuration-setup.md). Formats 1–8 and their frozen hashes remain unchanged.

The installer/checker use only packaged materials for the package entry. Generation receipts and `current.json`
verify distribution and venv identity; instance/install locks survive in the child. The start port precheck uses
SO_REUSEADDR for recently closed connections, while a listener still blocks. Npm user/global configuration paths
are distinct and isolated from inherited overrides; uv's optional vendor suffix is accepted for the same pinned
version regardless of executable path. Builds disable uv's output `.gitignore` to retain the exact artifact set.

## 12. P001 accounting architecture (capture/storage, queries/API, accounting page and billing controls implemented)

[T001 contract](phase/P001-T001-accounting-contract.md), D254–D257; T002 pure boundary (D258); T003 native capture,
storage and operations ([D259](DECISIONS.md#d259--native-accounting-capture-frozen-revision-binding-and-format-3-archives)).
`terminal-2`/`metrics-1`, their floats and existing endpoints are unchanged. T004 added bounded read-only queries/API
([D262](DECISIONS.md#d262--bounded-accounting-aggregates-and-the-read-only-accounting-api)); T005a added the read-only
accounting page (`pages/Accounting.tsx`, `accounting.ts`, D264); T005b added the billing/reference controls
([D265](DECISIONS.md#d265--billing-controls-reference-listing-and-save-time-billing-review)): reference routes in
`api/configuration.py` over `accounting_views.references` and `accounting_operations.reference_*`, the save-time
`billing_review` (`services/configuration_editing.py`, shared pure `storage/billing.choose`) and the UI in `billing.ts`
and `BillingFields.tsx`.

- **Pure core.** `core/engine/metric_references.py` / `valuation.py` (T002) validate pinned canonical references and
  calculate exact Decimal lines. `core/engine/usage_capture.py` builds the allowlisted `usage-capture-1` document from
  sealed process evidence, enumerates terminal/model/request views and selects one reconciled `usage-accounting-1`
  view. `metrics.StreamMetrics` additively retains ID-keyed Claude requests and exact cost lexemes (`usage-stream-1`).
- **Ledger.** `storage/accounting.py` writes inside the native transaction: `managed.py` (attempt row → intent,
  `_history`/`confirm_stopped` → settlement), `storage/preparation.py` (executor intent, `process_finished`, closing
  owner) and `configuration_assistance.py` (INTENDED operation, settlement/recovery). Fencing is unchanged: a stale
  owner cannot write accounting. Not-invoked launches have no valuation; missing process rows stay `unknown_execution`.
- **Billing binding.** `storage/billing.py` dereferences only the immutable revision frozen at admission into a
  content-addressed `billing-binding-1`. `local-config-10`/`project-config-2` add billing metadata, validated in
  `services/configuration.py` and removed by `runtime()` before composing executable configuration; `technical()`
  excludes it, so billing-only edits keep compatible receipts. Profiles never select authentication.
- **Operations.** `storage/accounting_operations.py` provides previewed reference import, accounting backfill and
  repricing with idempotency keys and named cohorts built in bounded transactions; CLI `accounting-references`,
  `accounting-backfill`, `accounting-reprice`. Nothing runs on GET, startup, migration or restore.
- **Archives.** Retention removes authorized stream bytes only. `storage/accounting_backup.py` verifies all accounting
  digests in the same snapshot for backup format 3; `backup-upgrade` migrates a copy of an older-schema bundle into a
  new query-only bundle. Consultation needs no original roots, clients, network or configuration authority.
- **Queries/API.** `storage/accounting_views.py` (`accounting-aggregate-1`) selects one SQL row per invocation with
  its latest capture and the valuation of an explicit policy (original admission valuation or one named cohort) and
  accumulates coverage, token sums and exact decimal amount buckets in Python, constant memory per group; it never
  decodes histories, prices or writes. `api/managed.py` exposes `GET /api/managed/accounting/{summary,groups,tasks,
  invocations,cohorts}` and invocation detail/valuations; OpenAPI and generated client types include them.

See the [accounting data](DDBB-DIAGRAM.md#p001-accounting-records) and [accounting flow](flows/metrics-accounting.md).
