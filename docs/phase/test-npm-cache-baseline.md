# Test baseline — npm cache and branches

Branch `chore/test-npm-cache-baseline` from `develop`
([D235](../DECISIONS.md#d235--release-branch-integration-branch-and-topic-branches)).

## Diagnosis of the 40 Python failures

The [v0.1.1 notes](v0.1.1-model-selectors.md) recorded 40 failures, identical on `1dac555` and `e252fdc`. Their
cause was the environment, not the product:

- Tests with real Node/npm use `FixtureCommandRunner` from `tests/product/test_typescript_profile.py`, directly or
  through its `web`/`repository` fixtures and runner environment (agent roles, project agents, TypeScript profile,
  commands, CLI baseline, contract shapes, Codex workspace write, local configuration, project registry and typed
  JSON schema). Its npm cache is `<root>/.local/npm-cache`.
- Preparation of `tests/fixtures/typescript_web` runs `npm ci --offline`, which needs `typescript-5.9.3.tgz` in that
  cache. This clone never ran the README's `npm --prefix frontend ci --ignore-scripts --cache .local/npm-cache`
  (`frontend/node_modules` already existed), so npm ended with `ENOTCACHED`. The harness records that as
  `OperationalStop(stage='preparation', reason='Environment preparation failed')`, and the tests then report other
  symptoms (`STOPPED` instead of `ACCEPTANCE_READY`, stage `preparation` instead of `planner`, missing objects,
  wrong counts).
- Evidence: the preparation record of a failing test showed the `ENOTCACHED` stderr. On an export of `6dca5b8` with
  a copy of the cache filled by `build_distribution.py`, the 40 tests passed and the full suite gave 2048 passed,
  2 skipped, 0 failed.

## Change

- `tests/npm_cache.py` checks, without running npm or touching the network, that every package locked by the
  TypeScript fixture has both its cacache index entry (by URL) and content (by integrity) in `.local/npm-cache`.
- `tests/conftest.py` shows a line in the pytest header and, when there are failures, an `npm cache` section in the
  summary naming the missing packages and the setup command. Test outcomes do not change: tests that do not need
  npm keep passing, and the affected ones still fail visibly.
- `tests/test_npm_cache.py` covers the check with a synthetic lock and cache (unittest, also collected by pytest).
- README (Development) explains what the npm cache is for. The P001 handoff, NEXT_STEPS and the v0.1.1 notes
  record the diagnosis instead of an unresolved baseline.
- D235 adopts `main` for releases, `develop` for integration and topic branches; AGENTS, CONTRIBUTING, the
  changelog's release procedure and STATE follow it.

## Checks

- `tests/test_npm_cache.py` with unittest and pytest: 2 passed.
- With an empty cache (copy of the working tree without `.local`), three formerly failing tests: the header and
  the summary name `typescript@5.9.3` and the setup command, serially and with xdist.
- Full suites in this clone with the cache filled: `uv run --frozen --offline pytest -q` 2050 passed, 2 skipped
  (the earlier 2048 plus the two new tests); `python3 -m unittest discover -s tests -p 'test_*.py'` 10 tests OK.
  Frontend suites were not rerun: no frontend file changed.

Not done: hosted CI does not exist (D230); branch protection for `main` on GitHub is a repository setting left to
the owner.
