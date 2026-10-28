# My Harness

My Harness is a local application that runs a development harness with AI coding agents over your own Git
repositories. A **reviewer** agent plans and reviews in read-only mode; an **executor** agent is the only writer.
The harness validates every change with your project's own commands, binds the review to the exact content, and
makes the commit itself. Work is organized in phases and bounded tasks, with project documentation, chat, metrics
and recovery after crashes. Everything runs on your machine: the service listens only on `127.0.0.1`, and the
models are reached through the official Codex and Claude Code CLIs with your own account.

[Leer en español](README.es.md)

## Status

- **Pre-release.** The first local version is complete within the scope described below; the package declares
  version `0.1.8`, the eighth patch of the first public release `0.1.0`, and is not published on PyPI. See the
  [changelog](CHANGELOG.md) for the versioning policy.
- **Platform.** Only macOS on Apple silicon (ARM64) has been tested. Other platforms are not characterized.
- **Evidence.** The offline test suites use temporary Git repositories, SQLite and fake agents. Real runs with
  providers exist only for the capabilities marked as such in [Supported scope](#supported-scope-and-limits).
- **First use.** The guided installation and both project entries are rehearsed with an installed wheel,
  fake clients/tools and temporary Git/SQLite on macOS ARM64. Setup uses the browser form; project operations use
  protected HTTP. Chrome was checked in English/Spanish, light/dark themes, desktop (1280/1470 px) and mobile
  (390 px; setup also 320 px), with sampled Tab/Enter navigation. Other browsers, screen readers, a complete
  keyboard audit and every size/theme/language combination are untested. These checks do not qualify real
  provider calls, other platforms or the next public candidate.
- **Guided configuration.** Installation/start scripts, global setup, own project profiles, confirmed preparation,
  editing and configuration backup are implemented. Installed synthetic evidence is separate from the historical
  provider evidence below.
- **Next.** An optional continuous mode (tasks → commits → check → closure → next phase) is planned for v0.2.0;
  see the [roadmap](docs/ROADMAP.md).

Licensed under the [MIT license](LICENSE); see [NOTICE.md](NOTICE.md) and the
[third-party notices](NOTICE-THIRD-PARTY.md).

## How it works

1. You choose the reviewer (provider, model and effort) and the executor provider and model catalog per project.
2. Each phase has a plan of tasks in `docs/NEXT_STEPS.md`. Queuing a task freezes its contract, profile, prompts,
   CLI versions and language pair.
3. The reviewer plans the task (or a deterministic plan is read from `NEXT_STEPS`) and picks the executor model.
4. The executor edits the checkout within the allowed paths. The harness runs the profile validations (and its
   formatter, if declared), then the reviewer accepts or asks for corrections, up to a limit.
5. You confirm the commit of the accepted content. The run becomes **COMMITTED**.
6. When every task is done, a READY check and your closure authorization archive the phase in one commit and open
   the next phase from the roadmap.

SQLite holds the operational state (runs, jobs, phases, conversations, metrics); Git holds code and documents;
Markdown holds the intent (specification, architecture, roadmap, decisions). Every effect records its intent first,
so an interrupted operation is reconciled instead of repeated. A job left in an unknown state waits for you to
confirm that its writer stopped.

## Two ways to start a project

- **Create a new project from scratch.** Choose a projects folder in the UI, name the project and start a
  definition conversation with the reviewer from a brief. You review and accept the generated documents; the
  harness makes the root commit after profile adoption. Complete the private tool configuration, confirm the
  preparation and activate the verified profile before tasks. Django/TypeScript recipes are optional helpers.
- **Onboard an existing repository without a harness.** Register a Git checkout that has at least one commit and
  no harness documents. The harness inventories its committed tree without running project code, the reviewer drafts
  the documentation and a profile proposal, and you confirm the documentation commit that adopts phase `P001`.

Registering again a project that this harness already manages is a normal registration, not a third entry. Older
harness formats are not imported as projects; importing legacy product TOML is a separate explicit operation.

## Requirements

| Use | Requirement |
|---|---|
| Running the service | macOS (tested on ARM64), Python 3.14 (tested 3.14.4) in its own virtual environment, Git with `--no-lazy-fetch` support (tested 2.50.1) |
| Building the package or developing | Exactly uv 0.12.19, Node 24.15.0 and npm 11.12.1 (the scripts check them); Python 3.14.4 available to uv |
| Agents | Codex CLI ≥ 0.163.0 and/or Claude Code ≥ 2.1.304, installed and signed in by you |
| Child projects | The tools of their profile or recipe: e.g. `python3` for the minimal example; CPython 3.11–3.13 and uv for the Django recipe; node/npm with a local npm cache for the TypeScript web recipe |

**Authentication.** The harness never stores credentials. Each CLI uses its own login, so sign in with `codex`
or `claude` before starting. The TOML gives every agent an explicit environment (`HOME`, `USER`, `PATH`), nothing is
inherited from the service, and `USER` must be the account that runs the service.

**Agent CLIs.** Clients are discovered on each role's explicit `PATH` (or an optional executable path); you do not
declare a version. Each version is checked against a minimum and against the capabilities the harness needs.

| CLI | Minimum | Status |
|---|---|---|
| Codex | 0.163.0 | Real executor runs at 0.164.0 with adapter `cli-14`; conditional compatibility |
| Claude Code | 2.1.304 | Real reviewer runs at 2.1.310 with adapter `cli-14`; conditional compatibility |

A candidate is a later release admitted automatically when its observed interface matches the known contract.
Its compatibility is conditional: help output and probes do not prove every internal effect, and no future version
is guaranteed. An older client gets an instruction to update; an observable incompatibility blocks the attempt
before the provider is invoked. Permission, sandbox, memory and trust controls are never relaxed.

## Install

Choose **one** of the two ways below. Both end in the same installed service. The installer creates its own
virtual environment (you never create or activate one), keeps everything outside your Git checkouts and does not
change your shell, Git or provider settings.

| | From the source code (Git clone) | From a release package |
|---|---|---|
| What you download | This repository | `my-harness-<version>-distribution.tar.gz` from the repository's GitHub **Releases** page |
| Tools you need | Python 3.14, uv 0.12.19, Git, Node 24.15.0 and npm 11.12.1 | Python 3.14, uv 0.12.19 and Git |
| What the installer does | Builds the package (a wheel that contains the compiled UI), verifies it and installs it | Verifies the checksums of the prebuilt package and installs it |

### 1. Check your tools

```sh
python3.14 --version   # Python 3.14.x
uv --version           # uv 0.12.19
git --version
node --version         # v24.15.0  (only to install from source)
npm --version          # 11.12.1   (only to install from source)
```

The installer never downloads these tools. **uv** creates the isolated environment and installs the locked Python
dependencies. If `python3.14` or `uv` is not on your `PATH`, add `--python /absolute/path/python3.14` or
`--uv /absolute/path/uv` to the install command.

### 2a. Install from the source code

```sh
git clone https://github.com/AcostaDDev/my-harness.git
cd my-harness
scripts/install --allow-network
```

### 2b. Install from a release package

Download `my-harness-0.1.8-distribution.tar.gz` and its `.sha256` from the
[Releases page](https://github.com/AcostaDDev/my-harness/releases) (or with `curl` as below) into the same folder, then:

```sh
curl -LO https://github.com/AcostaDDev/my-harness/releases/download/v0.1.8/my-harness-0.1.8-distribution.tar.gz
curl -LO https://github.com/AcostaDDev/my-harness/releases/download/v0.1.8/my-harness-0.1.8-distribution.tar.gz.sha256
shasum -a 256 -c my-harness-0.1.8-distribution.tar.gz.sha256
tar -xzf my-harness-0.1.8-distribution.tar.gz
cd my-harness-0.1.8
scripts/install --dist "$PWD" --allow-network
```

The archive holds the wheel (with the compiled UI), sdist, `pylock.toml`, `distribution-1.json`, `SHA256SUMS`
and `scripts/`. The installer checks every file against them; no Node/npm or source code is needed. A checksum
proves the download is intact, not who made it: download it only from the official repository.

### What the installer does

The first installation needs **`--allow-network`**: it downloads the locked dependencies into the cache.
Afterwards, `scripts/install` without options works offline: it verifies and reuses the installation. Without
`--allow-network`, a first installation fails because the cache is still empty.

The installer builds or checks the package, creates its own venv and publishes the installation only after an
isolated check with fake agents (no model is called). By default it uses these directories:

| Directory | Default | Option |
|---|---|---|
| Installation (versions and their venv) | `~/Library/Application Support/My Harness/installation` | `--install-dir` |
| Data (SQLite database and temporary files) | `~/Library/Application Support/My Harness/data` | `--data-dir` |
| Configuration (private TOML versions) | `~/Library/Application Support/My Harness/configuration` | `--config-dir` |
| Download cache | `~/Library/Caches/My Harness` | `--cache-dir` |

To choose other locations, pass absolute paths outside every Git checkout (quote paths with spaces) and use the
same `--install-dir` later with `scripts/start`:

```sh
scripts/install --allow-network --install-dir '/path/My Harness/installation' \
  --data-dir '/path/My Harness/data' --config-dir '/path/My Harness/configuration' --cache-dir '/path/Harness Cache'
```

If an installation fails, it is kept as FAILED with a diagnostic and nothing is published. Keep it for inspection
and retry with new installation/data/configuration directories; do not delete locks or data by hand.
`scripts/install --help` lists every option, including `--upgrade` (see [Operation](#operation)).

## First run

1. **Start the service** from the same folder where you ran the installer (the clone or the extracted package):

   ```sh
   scripts/start
   ```

   Add `--install-dir` if you chose another installation directory, or `--port` to use a port other than 8013.
   The script verifies the installation, creates the database only if it does not exist and serves the UI/API.
   It never reinstalls or silently migrates an existing database, and no Node/Vite is used at runtime.

2. **Copy the access key.** The service prints `My Harness: access key at <path>`. In another terminal:

   ```sh
   pbcopy < '<path printed by the service>'
   ```

3. **Open the UI.** Type `http://127.0.0.1:8013` in the browser's address bar and paste the key. Links from
   other sites are rejected. The session lasts eight hours; each start creates a new key, deleted when it stops.
4. **Configure.** Without a configuration the UI opens `/setup`; follow [Configure](#configure). Saving does not
   activate it: after confirming the activation, stop the service with Ctrl-C and run `scripts/start` again
   (then copy the new key and sign in again).

Defaults: `data/harness.sqlite3`, `data/tmp` and `configuration/global.toml` under the directories chosen at
installation. `--database`, `--temp-dir` and `--config` select other paths inside them. A missing or invalid TOML
keeps work blocked and opens setup; selecting a missing file does not create it. See `scripts/start --help`.

## Configure

1. In **Global configuration**, enter Git executable/commit identity, reviewer provider/model/effort, executor
   provider, and each client's explicit PATH, service account (`USER`) and optional HOME/executable. Choose existing
   allowed project roots and whether to allow confirmed creation and enable the job supervisor.
2. **Find local clients** only suggests paths. **Check client version/help** explicitly invokes those probes,
   without inference or authentication. Sign in to each provider separately; never paste credentials here.
3. **Validate and preview diff**, review the exact candidate and confirm **Save reviewed version**. Saving creates
   private TOML versions outside checkouts; it does not activate them.
4. **Review activation of saved version** and confirm the exact versions. The preview checks the selected clients
   (version/help) and every registered project first and names any setting to correct. The service applies the
   change without restarting and keeps your session: immediately when no work is running, otherwise it shows
   **Apply when current work finishes** and switches as soon as the listed work ends or is resolved. Only changes
   to the supervisor's lease/poll settings while it runs need a restart (`Ctrl-C`, then `scripts/start` with the same
   installation path/port); the preview says so before you confirm.

The form needs no Django/TypeScript composition or hand-written TOML. **TOML** exposes advanced settings;
conversion is validated on the server. Storage is chosen at startup and cannot be moved by this editor.
With the supervisor enabled, **each queued agent attempt uses your provider account and quota**. Detection,
preview and ordinary reading do not invoke a model.

**Existing configuration.** Formats 1–8 retain their original entry and hashes. Start with `--config` inside the
installation's configuration root, or use the installed CLI `serve --database … --config …` for an existing
operating area. The UI offers explicit import with source/hash/diff. Saving the conversion keeps legacy authority;
review each converted project, supply its current committed D088 documents and preparation plan, validate and
prepare it anew, then activate the entire set and restart using the managed store without the external source.
Old recipe receipts alone do not authorize converted profiles. This imports product configuration; onboarding an
existing code repository is the separate flow below.

Optional manual examples remain in [`examples/local_config.minimal.example.toml`](examples/local_config.minimal.example.toml)
and [the full v8 template](examples/local_config.example.toml), with [Django](examples/django-recipe.example.toml)
and [TypeScript](examples/typescript-web-recipe.example.toml) recipe fragments. Keep local paths/environments
outside checkouts, use private files (0600), and inspect a legacy file with the installed CLI:

```sh
/path/installation/generations/gen-ID/venv/bin/my-harness check-config /path/local.toml --preflight
```

## Start a project

1. **Preferences:** choose interface language and default work language.
2. **New project** or **Register project:** review the target/trust preview, agents, policy and immutable work
   language. A project can start without a stack composition. An existing composition is optional.
3. **Definition or onboarding conversation:** describe the project or let the reviewer inspect its static HEAD
   inventory. Answer the reviewer's questions in their own fields (one, a selection or all of them in one turn),
   review/apply document drafts, then review and adopt the proposed profile. Check
   tools, functional validations, command permissions, protected paths and the technical preparation plan.
4. Confirm the documentation commit that adopts `P001`. In the project's configuration editor, complete executable
   paths and the private environment, validate, review the diff and save the exact profile.
5. Review and confirm **preparation**: files, dependencies, argv, network and write scope. The executor prepares
   the permitted files; the harness runs the exact validations and records a receipt. A failure keeps tasks blocked.
   After success, review and separately confirm profile activation. This takes effect between tasks without restart.
6. **Phases → P001 → a task:** queue it and follow planning, execution, validation and review; the side panel of
   the task, run, chat and conversation pages shows what the agent is doing as its steps are recorded. At *accepted, commit
   pending*, review the evidence and confirm the commit to reach **COMMITTED**. A READY check and confirmed
   closure archive a completed phase.

Both entries use the same profile/preparation/activation gates; `P001 ACTIVE` alone does not enable a task.
Django/TypeScript recipes are optional helpers. A profile for another stack supplies its own tools and meaningful
validations. Onboarding inventories committed code without executing it and preserves existing sources.

Each managed project gets `AGENTS.md` with `CLAUDE.md`/`GEMINI.md` wrappers, `README.md`, and in `docs/`
`SPECIFICATION.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `STATE.md`, `NEXT_STEPS.md`, `DECISIONS.md`, `DDBB-DIAGRAM.md`,
`flows/`, `phase/` and `archive/phase-NNN/`. Managed blocks, task state and archive are maintained by the harness.

## Edit configuration later

Open **Global configuration** from navigation or the project's **Configuration** editor (on its overview and in its
Settings). Form/TOML editing uses validation, diff and separate save/activation confirmations. Guided forms cover
agents and their tool capabilities, reusable profiles, compositions and presets globally, and per project the profile
commands (arguments, directory, timeout, environment, JUnit), prefixes, protected/sensitive/data-model paths,
formatter, installed executable paths, command authorization/limits and agents, as far as the project's stage allows.
Fields marked invalid name what to correct; settings without a control are kept and stay editable in TOML. Preview shows affected projects, tools, receipts,
commands and pending jobs. A global change derives private project copies and activates the whole set in the
running service, waiting for current work when needed. A technical project change needs current committed documentation and a new preparation receipt before
activation. A nontechnical change may reuse an exact compatible receipt after verification.

Optional AI assistance uses the currently active clients and only the context you authorize. Applying its suggestion
changes the draft; saving, preparing and activating still need their own confirmations. It cannot edit your machine's
global settings. A confirmed change waits for running, queued or uncertain work, which keeps its frozen settings;
it is never cancelled or retried for you. Cancel the pending change from the same page if you prefer.

Conflicts retain your browser-tab candidate and exact request; review the current base before retrying. Reloading or
polling never resends a confirmation. External file edits do not reload authority. Recovery inspects recorded bytes
and requires an explicit stopped-writer declaration where appropriate; a timeout does not prove that a writer stopped.

## Languages

Two settings, both English or Spanish:

- **Interface language** — global and changeable at any time in Preferences. It governs the UI, the service and
  CLI messages, the conversation with the agents, their answers to you and their questions.
- **Work language** — chosen per project when it is created or onboarded (prefilled from the global default) and
  immutable afterwards. It governs documentation, plans, decisions, code and comments written in that project.

Changing the default work language only affects future projects. When a task, turn or operation is queued, both
languages are frozen for it: changing the interface language later applies to new interactions only, never to an
attempt, retry or answer already admitted. The pair reaches both providers as a sealed directive in the prompt; it
adds no CLI flags and changes no permissions. Keywords, paths, commands, formats and identifiers are never
translated, and existing files are read as they are.

Example: set the interface to *Español* and keep *English* as the work language of a new project. You talk with
the reviewer in Spanish and read its questions in Spanish, while every document, plan, decision, code change and
comment of the project is written in English — with Codex or Claude Code alike.

`my-harness --ui-language es <command>` chooses the language of a single CLI invocation; without it, the CLI
reads the preferences of an existing database or uses English.

## Safety model

- The service is reachable only on loopback, behind the session key, exact Host/Origin checks and a CSRF header;
  requests marked as cross-site are rejected, so links to the UI from other sites do not open.
- Every effect asks for an explicit confirmation of the exact preview hash: registrations, creations,
  preparations, document edits, commits and phase closures. Concurrent changes are rejected by version checks.
- The reviewer runs read-only. The Codex executor runs in `workspace-write` with the checkout as its only writable
  root and network disabled; the Claude executor gets only the declared tools (no shell). Automatic memory is
  disabled and checkout instructions are not loaded by the CLIs: the engine injects `AGENTS.md` itself.
- Containment is cooperative (CLI sandboxes, path checks, locks and content checks), **not** operating-system
  isolation. Register only repositories and tools you trust, preferably disposable checkouts at first.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Operation

**Restart.** Stop with Ctrl-C and repeat `scripts/start` with the same installation path and port. Queued work resumes; a job interrupted mid-attempt
shows *Recovery required* until you confirm that its writer stopped.

**Update.** Stop the service and every writer. Run `scripts/install` from the new clone or extracted package with
the same options as the first installation plus `--upgrade --writers-stopped` (and `--allow-network` if new
dependencies must be downloaded); it preserves previous generations and data. If the database needs a
schema upgrade, use the new generation's CLI separately before starting:

```sh
/path/installation/generations/gen-ID/venv/bin/my-harness migrate --database /path/data/harness.sqlite3 --snapshots /path/pre-migration --writers-stopped
```

`migrate` takes a verified snapshot outside every checkout and leaves a current database untouched. Failure
preserves database/snapshot for inspection; no automatic restore. `serve` never migrates.

**Backup.** With the service and writers stopped:

```sh
/path/venv/bin/my-harness backup-create /path/state/harness.sqlite3 /path/new-backup --artifact-root /path/data --artifact-root /path/configuration --writers-stopped
/path/venv/bin/my-harness backup-verify /path/new-backup
/path/venv/bin/my-harness backup-restore /path/new-backup /path/restored
```

`--artifact-root` (repeatable) authorizes state and configuration roots. Format 3 includes versioned TOML,
working copies, operation intents, referenced evidence and verified P001 accounting records. A bundle created before
schema `0028_usage_accounting` is not migrated in place: `backup-upgrade /path/old-backup /path/upgraded-backup`
writes a new verified format-3 bundle from a copy and leaves the original unchanged. A restore creates a new,
query-only database with the same schema revision. To browse it, start `serve --database
/path/restored/state.sqlite3` from the installed venv and open the local UI. The archive home accepts a run id;
`/runs/:id` opens its recorded evidence, diff, JUnit and metrics without a configured project or checkout.
No supervisor or agents run; mutations return 409. Historical pending jobs stay pending, and consultation does not
certify that a historical writer stopped. See the [consultation flow](docs/flows/backup-consultation.md).

**Other commands.** `logs-preview`, `logs-apply` and `logs-inspect` apply an explicit retention to agent streams;
`metrics-backfill` completes metrics; `accounting-references`, `accounting-backfill` and `accounting-reprice` are
explicit P001 accounting operations (without `--preview-sha256` they only preview; applying needs that digest and
`--key`); `diagnose-cli` checks one agent configuration. Every command documents its
arguments with `--help`.

**Diagnosis.** Start with the authenticated configuration status and explicit **Check client version/help**;
for a legacy TOML, use `check-config --preflight`. An occupied port requires stopping its owner or choosing `--port`.
An old schema needs the separate migration above; incomplete cache/installation needs inspection before retrying. Common blockers are explained in the UI: a CLI below its
minimum or missing from the role's `PATH`, a project without a confirmed work language, a configuration change
that quarantined pending jobs, or a recipe that still needs its preparation.

**Uninstall and keep your data.** Stop the service and all writers, then remove the installation directory
(including its generations), the download cache and any extracted package folder.
The SQLite database, the `state_dir`, backups and the TOML stay where you put them, and each project keeps its
Git history and documents. Delete them only if you no longer need that history.

## Supported scope and limits

| Capability | Offline (synthetic data and fake agents) | With real providers |
|---|---|---|
| Plan → execute → validate → review → commit, phases, closure and archive | Yes | Current adapter: Django and TypeScript tasks COMMITTED; TypeScript phase READY, closed and archived |
| Reviewer and executor, Codex or Claude Code, in the four combinations | Yes | Four combinations before `cli-14`; current adapter validated with Claude reviewer → Codex executor only |
| New Django project with the Django recipe | Yes | Historical creation, four tasks and closure on macOS ARM64/Python 3.13; v2 creation has offline evidence only |
| New TypeScript web project with its recipe | Yes, also with real node/npm and a local cache | v2, Spanish work language: definition, offline preparation, one task COMMITTED and phase closure |
| Recipes v2 that follow the project's work language | Yes, with synthetic tools | Spanish TypeScript v2 only; no real Django v2 creation or full language matrix |
| Declared profiles (`[profiles.*]`) and onboarding of existing repositories | Yes | Two synthetic Django repositories onboarded with originals intact; a documented clone reached COMMITTED using a v8 declared profile, six validations/13 JUnit cases and the native formatter (two files unchanged) |
| Chat, backup and restore | Yes | Two real reviewer answers, deterministic command without a model and proposal confirmed QUEUED without execution; backup/restored API and Chrome UI preserve real runs, diffs, JUnit and metrics |
| Run views, metrics and export preview over large synthetic histories | Yes | Restored real-run views/metrics verified; large histories and export preview have synthetic evidence only |

The current-adapter evidence was collected in October 2026 on macOS ARM64 with Claude Code **2.1.310** as
reviewer and Codex **0.164.0** as executor, using installed wheels, disposable synthetic projects and explicit
authorizations. Earlier four-combination and Django-recipe evidence used Codex 0.162.1/0.163.0 and Claude Code
2.1.295–2.1.304 before `cli-14`. These results do not qualify other pairs, versions, platforms or production
projects, compare model quality, or prove undocumented CLI effects; conditional compatibility still applies.
Two task attempts ended at REVISION_LIMIT and two TypeScript phase checks failed before a separately authorized
document edit and a valid READY check; their original results were preserved. The restored chat proposal remains
QUEUED, and historical process identity remains uncertain. See the [baseline](docs/STATE.md).

Known limits: no operating-system isolation; a recipe-pinned manifest does not accept new dependencies after
preparation; the `typescript-web` profile protects `package.json`, `scripts/**` and `tests/**` from the executor;
after a reboot that renumbers the disk device, creating another project requires choosing the projects folder
again; validations do not record their time; Gemini CLI is not a provider yet (its `GEMINI.md` wrapper only imports
the common instructions).

## Development

```sh
UV_CACHE_DIR=.local/uv-cache uv sync --frozen --no-python-downloads
npm --prefix frontend ci --ignore-scripts --cache .local/npm-cache
scripts/dev
```

The npm command also fills `.local/npm-cache`, which the Python tests with real Node/npm use offline for the
TypeScript fixture; with an empty cache they stop at *Environment preparation failed* and pytest names the cause.
Work happens on topic branches from `develop`; `main` only carries releases (see [CONTRIBUTING](CONTRIBUTING.md)).
Read [state](docs/STATE.md), then [one-off tasks](docs/ONE_OFF_TASKS.md), before the phase's
[next steps](docs/NEXT_STEPS.md). The normally empty one-off queue holds bounded fixes/improvements;
complete and remove those entries with durable evidence before resuming phase work.

`scripts/dev` checks the tool versions, migrates a development database (`.local/harness.sqlite3`) after backing it
up, and starts the API on `:8013` and Vite on `http://127.0.0.1:5173`; it accepts `--database` and `--config`.
Use it only for development: real use goes through the installed package.

Checks (offline once the caches are filled):

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q   # parallel; -n 0 runs it serially
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline alembic check
node --test frontend/tests/*.test.mjs
npm --prefix frontend run check
npm --prefix frontend run build
```

`scripts/check` runs the same suites with compact output: one line per suite, failing IDs with their first error
line, and the full log in `.local/check/<suite>.log`. Given paths, it runs only pytest over them. `--frontend` adds the
Node tests and the build, and `alembic check` uses a temporary SQLite database. `scripts/check-docs` checks local
Markdown links and anchors, code fences, en/es catalog keys and the schema head stated in `docs/DDBB-DIAGRAM.md`.

After changing an API contract, regenerate the client types (never edit them by hand):

```sh
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline python scripts/export_openapi.py
npm --prefix frontend run generate:types
```

Layout: `src/my_harness/` (engine in `core/`, adapters, storage, services, recipes, API, migrations and
message catalogs), `frontend/` (React/TypeScript UI), `tests/` (synthetic tests and fixtures), `scripts/`
(development and distribution) and `examples/` (configuration templates and a synthetic demo).

## Contributing and documentation

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the agent instructions in [AGENTS.md](AGENTS.md) before changing
anything. Project documents:

- [State](docs/STATE.md), [one-off tasks](docs/ONE_OFF_TASKS.md) (priority queue outside phases),
  [next steps](docs/NEXT_STEPS.md) (active phase) and [roadmap](docs/ROADMAP.md).
- [Specification](docs/SPECIFICATION.md): requirements and business rules; [architecture](docs/ARCHITECTURE.md):
  stack, modules, patterns and conventions; [data diagram](docs/DDBB-DIAGRAM.md): the SQLite schema.
- [Flows](docs/flows/task-run.md): task runs, phases, creation, onboarding, preparation, agents, CLI compatibility,
  languages, documents, chat and migration, one Mermaid document each in `docs/flows/`.
- [Decisions](docs/DECISIONS.md): the technical decisions of the starting baseline, cited by the code as `DNNN`.
- [Changelog](CHANGELOG.md): released versions and the versioning policy. There is no hosted CI: run the checks
  above locally before proposing a change.
