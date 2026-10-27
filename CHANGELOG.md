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
- By explicit roadmap assignment, P001 **Metrics Records** targets `0.1.2` as a specific exception to the patch
  scope above; it may include additive metrics data/API/configuration changes with the existing compatibility and
  migration guarantees. P002 **Continuous Mode** targets `0.2.0` for automatic phase closure and opening under a
  bounded authorization ([D233](docs/DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020),
  [roadmap](docs/ROADMAP.md)). Both are planned, not released.
- A version is released by tagging its commit and attaching to a GitHub Release the self-contained package
  `my-harness-<version>-distribution.tar.gz` (a `my-harness-<version>/` folder with the wheel, sdist,
  `pylock.toml`, `distribution-1.json`, `SHA256SUMS` and `scripts/` for `scripts/install --dist`) and its `.sha256`
  file; the wheel, sdist, `pylock.toml` and `SHA256SUMS` may also be attached individually. Nothing is published
  to PyPI, and built artifacts are never committed to the repository.

## [Unreleased]

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
