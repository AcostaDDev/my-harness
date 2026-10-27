# my_harness — agent instructions

Canonical source for agents; `CLAUDE.md` and `GEMINI.md` import it. For people, `README.md`.

My Harness: a local application that orchestrates development agents. Its reviewer and executor roles describe
the product, not the session that edits this repository. The repository is developed by hand, with or without
agents; its work language is English.

## Discovery at the start of a session

1. `docs/STATE.md`: accumulated baseline and active phase.
2. `docs/NEXT_STEPS.md`: tasks of the active phase and the next task.
3. `docs/ROADMAP.md`: section of the active phase.
4. `docs/SPECIFICATION.md` and `docs/ARCHITECTURE.md`: only the sections that affect the task.
5. `docs/DECISIONS.md`: the decisions the task cites; the index, to look for precedents.
6. `docs/DDBB-DIAGRAM.md` and `docs/flows/` when the task touches data or flows.
7. `docs/archive/` only when a document cites it.

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
- Never present as implemented what is only designed. Frozen histories, snapshots, catalogs and fingerprinted
  recipe sources are not rewritten.
- When finishing: relevant checks, reviewed diff, `docs/STATE.md` and `docs/NEXT_STEPS.md` up to date, durable
  decisions in `docs/DECISIONS.md` (`## DNNN — title`, new numbers from D230) and work artifacts in `docs/phase/`.
  Say what was tested and what was not.

## Commands (from the root; offline after the first installation)

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
