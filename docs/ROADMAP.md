# Roadmap — my_harness

The repository opens with the first local version of My Harness already built: [STATE](STATE.md) describes that
starting baseline, including guided installation/configuration, and [DECISIONS](DECISIONS.md) the decisions behind it. That earlier work is not replayed here as
phases; phases are numbered from P001 in this repository.

## P001 — Metrics Records

**Status:** **completed** — released as **0.1.9** on 2026-10-29
([PR #8](https://github.com/AcostaDDev/my-harness/pull/8), merge/tag `5cc1bc1`/`v0.1.9`,
[GitHub Release](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.9)), installed on the operator machine and
closed by hand ([D266](DECISIONS.md#d266--manual-phase-closure-and-archive-in-this-repository)). Archive and summary:
[`archive/phase-001/`](archive/phase-001/SUMMARY.md). Target history: D233, D239, D246 and
[D253](DECISIONS.md#d253--phase-release-targets-after-018); the one-off releases 0.1.2–0.1.8 were delivered outside
the roadmap ([STATE](STATE.md#releases)).

**Objective:** Record detailed consumption by provider and effective model, with reproducible cost and credit
analysis, versioned reference data and explicit coverage/provenance. Start with the supported Claude Code and Codex
clients; keep the accounting concepts extensible without adding another execution provider.

All five exit criteria are met with synthetic evidence only; no real CLI emission, account billing or invoice was
validated ([qualification](archive/phase-001/P001-T006-qualification.md)).

**Exit criteria:**

- Attempts preserve provider/client versions, requested and reported model/effort, token categories, durations,
  tools, outcome and evidence provenance without double counting or treating missing data as zero.
- Each supported billing case has either a reproducible valuation or an explicit reason it cannot be calculated;
  reported amounts, calculated USD, calculated credits and confirmed billing evidence remain distinguishable.
- Versioned references identify the applicable provider, model, billing scheme, units, source, observation date,
  known effective period and pricing conditions; later updates do not change historical valuations.
- Statistics support provider/model, role, project, phase, task and time analysis with coverage and compatible
  units; subscription allowances and invoices are not inferred from tokens.
- Synthetic checks cover calculation, capture, aggregation, historical compatibility, retention, backup and
  query-only consultation; data diagrams, flows, OpenAPI/client types and en/es UI stay in parity where changed.

**Dependencies:** the current metrics baseline (D074), model-selection distinction (D231), and the repository's
configuration, backup and immutability guarantees. No continuous-mode behavior is required for the calculation
engine. The accepted T001 contract guides implementation; unsupported evidence cases remain explicit.

**Record:** [summary](archive/phase-001/SUMMARY.md), [closing STATE](archive/phase-001/STATE.md) and
[task plan](archive/phase-001/NEXT_STEPS.md).

## P002 — Continuous Mode

**Target release:** `0.2.0`, published at P002 closure (D253)
([D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020)).

**Objective:** Automatically close and archive a completed phase, open and plan the next phase, and continue its
execution under one explicit, bounded authorization. Chain tasks, commits and the READY check while stopping at
the first error, question or limit.

**Status:** active since the P001 closure (2026-10-29), without a plan: design and tasks pending, to be confirmed by
the owner before any code ([NEXT_STEPS](NEXT_STEPS.md)).

**Exit criteria:**

- The mode is optional and starts only from an initial authorization with an explicit scope and budget.
- Phase closure, archiving and opening/planning the successor happen automatically within that authorization,
  subject to a valid READY check and the existing content-bound guarantees.
- It stops at the first error, blocking condition, question for the user, out-of-scope change or consumption limit,
  and the stopped work can be inspected and resumed.
- READY binding, acceptance by exact content, intent before effect and recovery keep their current guarantees.
- Without that authorization the current behavior is unchanged: explicit task batches, explicit check, closure
  authorized on READY and a confirmed plan for each new phase.

**Dependencies:** P001 Metrics Records and the existing phase lifecycle and authorization guarantees.

## Known gaps without a phase

- Broader real-provider coverage: current `cli-14` evidence covers Claude Code 2.1.310 reviewer → Codex 0.164.0
  executor on synthetic Django onboarding/declared profiles and Spanish TypeScript v2, plus chat and restored
  consultation. Other pairs on the current adapter, Django v2 creation, a full language matrix and production
  projects remain unqualified ([scope](../README.md#supported-scope-and-limits)). The narrow onboarding/profile
  gap originally deferred by D151 has been exercised; it is no longer pending.
- Platforms other than macOS ARM64 are not characterized.
- Operating-system isolation of the agents is not provided
  ([D064](DECISIONS.md#d064--cooperative-containment-without-operating-system-isolation)).
- Gemini CLI is not a provider; its `GEMINI.md` wrapper only imports the common instructions.
