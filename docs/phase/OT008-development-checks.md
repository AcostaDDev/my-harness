# OT008 — Quiet development checks and agent workflow guidance

Status: complete; source delivered through `chore/ot008-development-checks` (branched from `develop` at `2817cdc`).
Owner: OT008, [D260](../DECISIONS.md#d260--quiet-development-checks-and-economical-agent-workflow).
Delivery route confirmed by the owner on 2026-10-28: topic → `develop`/`origin`, source-only, no patch release;
commit, merge and push authorized by the owner after review. Git records the source and merge commit IDs; the local
topic branch is removed after the merge. The OT008 queue section was removed with this delivery (D242).
Route deviation: one-offs should have branched from the latest release instead
([D261](../DECISIONS.md#d261--one-off-tasks-branch-from-the-latest-release-not-from-develop)); OT008 stays in
`develop` and reaches `main` with the P001 closure release.
Development tooling only: it completes no Metrics Records task and leaves P001's plan and the 0.1.9 target unchanged.

## Implemented boundary

| Area | Implementation |
|---|---|
| Suites | `scripts/check` → `scripts/check.py`: unittest, `alembic upgrade head` + `alembic check` on a temporary SQLite, full pytest; paths ⇒ pytest only (`--` passes options); `--frontend` adds `node --test --test-reporter=tap` and `npm --prefix frontend run build` (includes `tsc --noEmit`); `--suite` selects. One line per suite, ≤ 20 failing IDs with their first error line, full log in `.local/check/<suite>.log`. |
| Documentation | `scripts/check-docs` → `scripts/check_docs.py`: tracked `*.md` (or given files), local targets and anchors with GitHub slugs, `-N` duplicates and `<a id>`/`<a name>`; unclosed fences; en/es key parity for `src/my_harness/i18n` and `frontend/src/i18n`; DDBB "head `…`, N tables" statements against `SCHEMA_REVISION`, the migration head and the `__tablename__` count. |
| Guidance | `AGENTS.md` Commands section: wrappers first, cheapest sufficient check, range/`grep` reads, no ad hoc link checkers. `README.md#development` describes the wrappers. `CLAUDE.md` unchanged (thin import). |
| Tests | `tests/product/test_development_checks.py` (17): parsers for pytest/unittest/TAP/tsc/alembic output, suite selection, bounded output, an end-to-end unittest run (pass and injected failure) in a temporary tree, GitHub slugs, links/anchors/fences, catalog parity and the DDBB head/count, all synthetic. |

No product source, migration, API, frontend source, dependency or configuration changed. No `.claude/settings.json`
was added (declined by the owner). The new scripts are not in `BUNDLE_SCRIPTS`; the 0.1.6 sdist lists only `src/`,
`pyproject.toml`, README, LICENSE and notices, so no new file enters a distribution. `README.md` is packaged as
metadata, so its development paragraph ships with the next normal release build; that needs no separate release.

`check-docs` found one stale link on the current tree: `docs/phase/pending-questions-handoff.md` pointed to the
removed OT002 queue section. Its line now points to the retained [OT002 evidence](OT002-question-answers.md), the only
edit to that handoff.

## Checks

| Check | Result |
|---|---|
| Direct full pytest (`uv run --frozen --offline pytest -q`) | 2311 passed, 2 skipped, 11 warnings, 29 subtests; exit 0; 213 s. |
| `scripts/check` (unittest, alembic, full pytest) | unittest 10 ran; alembic no new upgrade operations; pytest 2328 passed (2311 + the 17 new), 2 skipped, 11 warnings, 29 subtests; exit 0; 236 s. Same outcome as the direct commands. |
| `scripts/check --suite unittest --suite alembic --suite node --suite build` | unittest 10 ran; alembic no new upgrade operations; node 230 tests/230 pass; build tsc + vite; exit 0. Same outcomes as the direct commands. |
| Injected pytest failure (synthetic scratch file: assertion, exception, fixture error, skip) | Direct and wrapped both exit 1; the wrapper lists `2 failed, 1 passed, 1 skipped, 1 error` and the three IDs with `AssertionError: synthetic mismatch`, `RuntimeError: synthetic runtime error`, `ValueError: synthetic fixture error`. |
| Injected unittest failure | Covered end to end in the focused tests (pass ⇒ 0, failure ⇒ 1 with `FAIL … — AssertionError: 1 != 2 : synthetic mismatch`). |
| Injected Node failure (synthetic scratch test) | Direct exit 1; parser reports `2 tests, 1 pass, 1 fail` and `a.test.mjs › synthetic failure — one is not two`. |
| `scripts/check-docs` | 69 Markdown files, 615 local links (391 with anchors), 0 errors after the fix above; 0.45 s. A synthetic scratch file reports the unclosed fence, missing target and missing anchor, exit 1. Missing catalog keys and a stale DDBB head are covered by the focused tests. |
| Focused tests | `scripts/check tests/product/test_development_checks.py`: 17 passed. |
| Development database | `.local/harness.sqlite3` unchanged (size and modification time) after the alembic suite. |
| `git diff --check` | clean. |

## Output size (same suite, same tree)

| Run | Bytes printed |
|---|---|
| Full pytest, direct | 3,633 (47 lines: progress dots, warnings, summary) |
| Full pytest, through `scripts/check` | 85 (one line); 153 for unittest + alembic + pytest together |
| Synthetic failing file, direct | 2,333 (tracebacks, sections, summary) |
| Synthetic failing file, through `scripts/check` | 803 (three IDs with long scratch paths; repository paths are shorter) |
| Synthetic Node failure, direct (spec reporter) | 1,189 |

A passing pytest run is quiet in both cases; the saving grows with the number of failures, since tracebacks stay in
the log. Most of the P001-T003 shell output came from whole-file reads, which the AGENTS guidance addresses; the
scripts cannot measure that, and no real-session token comparison was made.

## Omissions and limits

- External URLs are not fetched, and links to non-Markdown files are checked for existence only (no `#Lnn` anchors).
  Heading slugs follow GitHub's rules for the constructs used in this repository; raw HTML headings are not parsed.
- `check-docs` with explicit files checks only links and fences; catalogs and the DDBB head run in the full mode.
- Codex was not run; the guidance is client-neutral text in AGENTS.md and needs no client configuration.
- The full suite was not rerun with the direct command after adding the new test file; the wrapped full run includes it.
- A first wrapped full run, started while a focused run was going, parsed the other run's log: both wrote
  `.local/check/pytest.log`. Each run now writes a per-process log and renames it when done. A concurrent focused
  run then reported only its own results, and the full rerun above is correct. With concurrent runs, `<suite>.log`
  holds whichever run finished last.
