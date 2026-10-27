# P001 — Optional continuous mode between phases

Objective and exit criteria in [ROADMAP](ROADMAP.md#p001--optional-continuous-mode-between-phases).

Pending a confirmed plan.

Before it: tag and publish the `0.1.1` patch (model selectors, D231) from its commit, building and checking the
self-contained package locally ([work notes](phase/v0.1.1-model-selectors.md)).

## Shared constraints

- One bounded task at a time; durable decisions in [DECISIONS](DECISIONS.md) from D230 and task artifacts in
  `docs/phase/`.
- Real providers, paid calls, network installs, pushes and publication need explicit authorization of their own.
- Tests and fixtures are synthetic: no runs, credentials or private data.
- Model, migration, flow and API changes keep their diagrams and generated types in the same task.
