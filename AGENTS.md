# my_harness — agent instructions

Canonical source for agents; `CLAUDE.md` and `GEMINI.md` import it. For people, `README.md`.

My Harness: a local application that orchestrates development agents. Its reviewer and executor roles describe
the product, not the session that edits this repository. The repository is developed by hand, with or without
agents; its work language is English.

## Discovery at the start of a session

1. `docs/STATE.md`: accumulated baseline and active phase.
2. `docs/ONE_OFF_TASKS.md`: pending bounded work outside phases; handle it before phase tasks. Normally empty.
3. `docs/NEXT_STEPS.md`: tasks of the active phase and the next task when the one-off queue is empty.
4. `docs/ROADMAP.md`: section of the active phase.
5. `docs/SPECIFICATION.md` and `docs/ARCHITECTURE.md`: only the sections that affect the task.
6. `docs/DECISIONS.md`: the decisions the task cites; the index, to look for precedents.
7. `docs/DDBB-DIAGRAM.md` and `docs/flows/` when the task touches data or flows.
8. `docs/archive/` only when a document cites it.

## Unbreakable rules

- Do not invent beyond the specification or what was decided. On an inconsistency between documents, or between
  documents and code, ask before changing the design. Reversible details are resolved with judgment.
- Parity: a model or migration change updates `docs/DDBB-DIAGRAM.md`; a flow change, `docs/flows/`; an API contract
  change, the exported OpenAPI and the generated client types; all in the same task.
- Do not run the harness on this repository, launch real agents or providers, install over the network, push or
  publish without explicit authorization. Do not modify the user's global configuration.
- Fixtures are always synthetic: no runs, credentials or private data. Exact versions; no new dependency without a
  recorded decision.
- One bounded task at a time. Do not discard someone else's changes. Commit only when asked.
- Before product changes, record the owning phase/task or one-off ID and its agreed delivery route. Track source
  completion separately from integration, distribution and installation; do not drop pending delivery (D242).
- Work on a topic branch from `develop` (`<kind>/<topic>`); `main` only receives release merges. Check the current
  branch at the start of a session
  ([D235](docs/DECISIONS.md#d235--release-branch-integration-branch-and-topic-branches)).
- Never present as implemented what is only designed. Frozen histories, snapshots, catalogs and fingerprinted
  recipe sources are not rewritten.
- When finishing: relevant checks, reviewed diff and current STATE/NEXT_STEPS/ONE_OFF_TASKS. Record durable
  decisions in `docs/DECISIONS.md` (`## DNNN — title`, new numbers from D230) and evidence in `docs/phase/`.
  Remove one-off sections after recording evidence and completing or explicitly deferring their agreed delivery.
  Say what was tested and what was not.

## Commands (from the root; offline after the first installation)

Prefer the quiet wrappers ([D260](docs/DECISIONS.md#d260--quiet-development-checks-and-economical-agent-workflow)).
They print one line per suite plus failing IDs with their first error line, keep the full output in
`.local/check/<suite>.log`, and exit nonzero on any failure:

```sh
scripts/check tests/product/test_x.py   # focused pytest only; options after `--`, e.g. -- -k name -n 0
scripts/check                           # unittest, alembic check on a temporary SQLite, full pytest
scripts/check --frontend                # adds the Node tests and the frontend build (which runs tsc)
scripts/check-docs                      # local links/anchors, fences, en/es keys, DDBB head and table count
```

To save tokens: run the cheapest sufficient check first (focused paths, then the full suite only for shared code or
at task closure), and inspect a log with `grep`/a line range instead of re-running verbosely. Read source and long
documents by range or after `grep -n`, not whole. Do not write ad hoc link checkers; extend `scripts/check-docs`.

The wrapped commands (direct `alembic check` uses `.local/harness.sqlite3`):

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q   # parallel (xdist); -n 0 serially
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline alembic check
node --test frontend/tests/*.test.mjs
npm --prefix frontend run check
npm --prefix frontend run build
scripts/dev   # API :8013 and Vite :5173, with migration and backup first
```

Installation, client type regeneration and operation from the wheel: `README.md`.
