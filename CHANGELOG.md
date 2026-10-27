# Changelog

All notable changes to My Harness are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Versioning policy

- One version string is shared by the Python package (`pyproject.toml`), the API (`/openapi.json`) and the UI
  package (`frontend/package.json`). A release changes all three together.
- The project is pre-1.0: a minor release (`0.x.0`) may change the configuration, the API or the UI, and its notes
  say what to do. Patch releases (`0.x.y`) fix defects and may carry small interface improvements that change no
  configuration format, API contract or stored data
  ([D231](docs/DECISIONS.md#d231--packaged-model-suggestions-and-small-ui-patch-releases)). Data compatibility does
  not depend on the version number: every release keeps reading older databases and histories, and the SQLite schema
  is upgraded only by `my-harness migrate`, which takes a verified snapshot first.
- At the owner's direction each completed one-off task is released as the next patch version and may carry the
  additive API/UI changes it needs ([D239](docs/DECISIONS.md#d239--one-off-tasks-released-as-patch-versions)).
- By explicit roadmap assignment, P001 **Metrics Records** targets the patch release after the one-off queue (it
  was `0.1.2` before D239) as a specific exception to the patch
  scope above; it may include additive metrics data/API/configuration changes with the existing compatibility and
  migration guarantees. P002 **Continuous Mode** targets `0.2.0` for automatic phase closure and opening under a
  bounded authorization ([D233](docs/DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020),
  [roadmap](docs/ROADMAP.md)). Both are planned, not released.
- A version is released through a pull request from `develop` to the protected `main`, merged as a merge commit
  (`--no-ff`), tagging that merge commit
  ([D235](docs/DECISIONS.md#d235--release-branch-integration-branch-and-topic-branches)) and attaching to a GitHub
  Release the self-contained package `my-harness-<version>-distribution.tar.gz` (a `my-harness-<version>/` folder
  with the wheel, sdist, `pylock.toml`, `distribution-1.json`, `SHA256SUMS` and `scripts/` for
  `scripts/install --dist`) and its `.sha256` file; the wheel, sdist, `pylock.toml` and `SHA256SUMS` may also be
  attached individually. Nothing is published to PyPI, and built artifacts are never committed to the repository.

## [Unreleased]

## [0.1.8] — 2026-10-27

Patch release for OT007 (D252). Stop the service and writers before installing. No database migration,
configuration, dependency, recipe, API contract or `cli-14` adapter-version change.

### Fixed

- Managed task, phase, chat and definition runs retry transient heartbeat failures within the existing lease.
  Ownership loss still stops the next journal operation; diagnostics and closure events retain renewal evidence.
- CLI stream events are journaled once per read chunk, with their original contents, order and sequence numbers.
- The closing owner settles interrupted process rows using independent group liveness and retains partial captures.
  Existing captures and histories stay intact; quarantine, checkout exclusion and confirm-stopped remain required.

## [0.1.7] — 2026-10-27

GitHub Release `v0.1.7` (tag on merge `a3e9794`), with the self-contained archive and its checksum.

Patch release for OT006 (D251). Install the new package after stopping the service and writers; projects,
configuration and histories are preserved. No configuration format, API contract, database schema, migration,
dependency, recipe or `cli-14` adapter-version change.

### Fixed

- Generic preparation no longer launches a Claude executor that has write scope but no usable file-writing tool.
  Preview refuses it with an en/es diagnostic naming `Write`, `Edit` or `MultiEdit`, and plans queued earlier fail
  before launch. Tools are never granted automatically.
- Repetitive streamed Claude text is bounded by `output-guard-1`, which stops the owned process group, keeps the raw
  output as evidence and issues no receipt.
- Preparation lease renewal retries transient failures within the lease instead of stopping after the first one,
  and records why renewal failed. Stream events are journaled once per read chunk, which reduces write pressure.
- Interrupted executor attempts leave a partial capture beside their artifacts. The closing owner settles their
  process rows from an independent liveness check instead of leaving a stale `RUNNING` row. Captures say whether
  final usage was observed.

## [0.1.6] — 2026-10-27

Patch release for OT004 (D250). Install the new package after stopping the service and writers; projects,
configuration and histories are preserved. Interface only: no configuration format, API contract, database schema,
migration, dependency or recipe change.

### Added

- Guided forms in **Global configuration** for agent environment variables, a pinned client version and tool
  capabilities, and for reusable profiles, compositions and agent presets. Recipes and any setting without a control
  are kept exactly and remain editable in TOML.
- The project's profile configuration editor is also available in the project's **Settings**. It explains what the
  private copy inherits and edits profile commands (arguments, directory, timeout, environment, JUnit report),
  command prefixes, protected/sensitive/data-model paths, executor instructions, the optional formatter, installed
  executable paths, the command environment, authorization and limits, and the project's agents, as far as the
  project's stage allows.
- Field checks name what to correct before a preview is requested; save reviews state per project whether a new
  preparation is required, which project copies only change their global reference and that admitted work keeps its
  frozen settings.

### Changed

- Tool lists are offered only for a Claude Code executor and explained as explicit CLI tool permissions. Lists made
  unsupported by a provider or role change stay visible and block validation until removed explicitly.

## [0.1.5] — 2026-10-27

Patch release for OT005 (D247–D249). Upgrade by installing the new package after stopping the service and writers;
projects, configuration and historical operations/receipts are preserved. No configuration format, API response model,
database schema, migration, dependency or packaged recipe change. New inline tool-link evidence is opt-in; old
receipts and explicit recovery retain their original policy.

### Fixed

- Generic preparation accepts pre-existing read-only executable aliases outside its private write scope when their
  exact file-link chain ends at an explicitly declared, resolved and hash-bound tool. External directory aliases
  along that tool chain (such as a Homebrew interpreter alias) are explicitly recorded and checked. Checkout
  directory links and unrelated targets remain refused; this grants no new write scope or environment accreditation.
- Tool-link text/modes, executable bytes and the complete alias path set stay bound through confirmation,
  post-effect guards, receipt verification and explicit recovery. Link-resolution errors identify the link instead
  of incorrectly reporting a changed project-folder identity.
- Generic preparation review shows authorized paths/effects, private directories, executor selection/instructions,
  exact command arguments and command context/evidence. It no longer invents file hashes or leaves numbered steps
  blank. Generic mode/consent wording follows the profile; recipe v1/v2 fixed-file review remains supported.

## [0.1.4] — 2026-10-27

Patch release for OT003 (D241/D244/D245). Install the new package to update the service and UI; existing projects,
configuration and histories are preserved. No configuration format, response-field, database schema or migration
change. API descriptions and generated client comments reflect the corrected adoption guards.

### Fixed

- Intake profiles using installed executable paths now identify the command field and explain logical aliases;
  definition/onboarding prompts clarify direct tool names, and subsequent turns receive prior failure reasons.
- Profile adoption no longer treats informational pending notices as blockers and respects explicit deferrals of
  blocking questions. Missing or changed applied document drafts have specific diagnostics instead of also being
  reported as an invalid profile. Exact document/context/HEAD checks and confirmation remain required.
- Documents returned by failed turns are labelled unavailable to apply. Profile guidance explains applying document
  drafts before adoption; unchanged profile forms no longer enable redundant draft creation.

### Added

- A joint review of current definition/onboarding document proposals, with exact diffs, document exclusions and
  one explicit confirmation to apply the selected proposals to drafts. Existing per-document CAS actions run in
  order; conflicts or uncertain responses stop the sequence and report confirmed progress without automatic retry
  or rollback. Profile adoption and the documentary commit keep their own confirmations.

## [0.1.3] — 2026-10-27

Patch release for one-off task OT002 ([D240](docs/DECISIONS.md#d240--question-first-answers-and-the-live-activity-rail),
[D239](docs/DECISIONS.md#d239--one-off-tasks-released-as-patch-versions)). Interface only: no configuration format,
API contract, database schema or stored data changes. Upgrade by installing the new package; existing
configurations, projects, conversations and histories are kept.

### Added

- The reviewer's questions in onboarding, project definition and phase planning come first, each with its own answer
  field. Answers are saved as drafts in the browser while you type and sent only after reviewing the exact message:
  one answer, the selected ones or all prepared answers go in one message, which is one reviewer turn. Each question
  shows whether it is a draft, waiting for the reviewer, resolved, still asked or not reviewed; drafts for questions
  the reviewer stopped asking are kept for you to include or discard. Deferring a blocking question stays a separate
  action with a reason.
- A live activity panel shows what the agent is doing in the latest run of a task, phase or project, in a run, and
  in the latest turn of a chat or planning conversation: files read and edited, commands, searches, validations,
  messages and the text being written, as the run records them.

### Changed

- Pages use the full window width. Project, phase, task, run, chat and conversation pages place the live activity
  and a short status beside the main content on wide screens and below it on narrow ones.
- The free message box of a documentary conversation is labelled as a message other than the answers and says so.
- Run states `ANSWERING` and `DISCOVERING` have their own labels.

## [0.1.2] — 2026-10-27

Patch release for one-off task OT001 ([D238](docs/DECISIONS.md#d238--live-configuration-switch-at-an-idle-boundary),
[D239](docs/DECISIONS.md#d239--one-off-tasks-released-as-patch-versions)). Upgrade by installing the new package;
no configuration format or database schema changes, and existing configurations, projects and histories are kept.
The API adds fields and one state; the generated client types are regenerated.

### Changed

- Activating a saved global configuration (agents, models, efforts, timeouts, executables, PATH/environment, presets,
  Git identity, roots) applies it in the running service: no restart, reinstall or new access key. The activation
  preview first checks the selected clients (version/help only) and recomposes every registered project with the
  candidate, and names any project, role or setting to correct. A refused candidate changes nothing.
- When work is running, queued, awaiting acceptance or recovery, the confirmed change waits as **Apply when current
  work finishes**, listing that work. Admitted work keeps its frozen settings and is never cancelled, retried or
  rebound; new work uses the active configuration until the switch. A change that cannot be applied at the switch
  is withdrawn and the previous configuration stays active. It can be cancelled while it waits.
- Project-only activations follow the same rule for running work; their documentary barriers are unchanged.
- Only the supervisor's `lease_seconds`/`poll_seconds`/`supervisor` while it runs, and promoting a legacy import,
  still need a restart; the preview says so before confirming.
- The save preview lists fields removed by the candidate.

### Fixed

- A definition or onboarding conversation whose turns all failed without output or draft changes no longer blocks
  activating a corrected configuration, such as a longer client timeout
  ([D236](docs/DECISIONS.md#d236--empty-failed-intake-turns-are-not-pending-configuration-work)).
- Tasks of a project with its own profile could not be admitted after a global change or an agent-only project
  change (`preparation_required`): admission now binds the receipt selected for the job's exact configuration
  revision.

## [0.1.1] — 2026-10-27

Interface-only patch release: no configuration format, API contract or database change. Upgrade by installing the
new package; existing configurations, models and projects are kept as they are.

### Changed

- The reviewer's model in the global setup is chosen from a selector of models for its provider, with **Other…**
  to type any model the CLI accepts. A saved model outside the list stays visible and editable.
- A project's executor models are checkboxes instead of a free-text list: the preset's models in catalog mode, or
  the suggested models for the executor's provider plus any model added by hand. The reviewer keeps choosing one of
  the checked models for each task.
- Patch releases may include small interface improvements like these (versioning policy above).

## [0.1.0] — 2026-10-27

First public release candidate. Earlier development happened in a private repository; this is the starting point
of the public history, so there is no earlier public version to upgrade from.

### Added

- Local service (FastAPI + SQLite, loopback only, session key and CSRF guard) with a React UI in English and
  Spanish, and the `my-harness` CLI.
- Two ways to start a project: create one from scratch through a definition conversation, or onboard an existing
  Git repository without a harness. Optional Django and TypeScript web recipes prepare a new project's environment.
- Task runs with a read-only reviewer and a single writing executor (Codex CLI or Claude Code, in any
  combination), profile validations, review bound to the exact content and a commit made by the harness.
- Phases with a READY check, authorized closure and archive; project chat, documents, metrics, backups and recovery
  after crashes.
- Global interface language and default work language (English or Spanish); each project's work language is fixed
  when it is created or onboarded.
- Automatic discovery of agent CLIs with minimum versions (Codex 0.163.0, Claude Code 2.1.304) and conditional
  compatibility for later releases, checked by capabilities before each attempt.
- Optional native formatter for declared profiles in `local-config-8`, with existing formats 1–7 preserved.
- Query-only archive UI: direct run links, evidence, paginated diffs, JUnit and metrics without a configured project
  or checkout, backed by the persistent restore mark and mutation guards.

### Fixed

- CLI capability diagnostics read explicit choices wrapped over multiple help lines.
- Project preset selection remains available with `local-config-8` in registration, creation and settings.
- Resolving agent CLIs rebinds a compatible completed preparation receipt before admitting new work, preserving the
  exact environment digest and the existing drift checks.

### Known limits

- Tested only on macOS on Apple silicon. Real-provider evidence covers only the capabilities marked as such in the
  README: current adapter with Claude Code 2.1.310 reviewer and Codex 0.164.0 executor; four-combination evidence is
  historical. The scope includes synthetic Django onboarding/declared-profile work, Spanish TypeScript v2 creation
  through closure, chat and query-only backup consultation. Other pairs, Django v2 creation and production projects
  are not qualified by these runs.
