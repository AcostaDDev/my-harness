# Roadmap — my_harness

The repository opens with the first local version of My Harness already built: [STATE](STATE.md) describes that
starting baseline, including guided installation/configuration, and [DECISIONS](DECISIONS.md) the decisions behind it. That earlier work is not replayed here as
phases; phases are numbered from P001 in this repository.

## P001 — Metrics Records

**Target release:** **0.1.9, published at P001 closure**
([D253](DECISIONS.md#d253--phase-release-targets-after-018)). Earlier target history:
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020),
[D239](DECISIONS.md#d239--one-off-tasks-released-as-patch-versions); `0.1.2` was released for OT001 and `0.1.3`
for OT002.
OT003 was released as 0.1.4 outside the roadmap. The owner subsequently confirmed **OT005 preparation tool-link
hotfix → 0.1.5**, before **OT004 visual profile editor → 0.1.6**, then P001
([D246](DECISIONS.md#d246--ot005-preparation-tool-aliases-before-the-visual-editor) supersedes D243's target/order;
D239/D242 still govern separate patch deliveries). OT005 was released as **0.1.5** through PR #4, with its archive
and checksum verified after download. OT004 was released as **0.1.6** through PR #5 (tag `v0.1.6`), with its
archive and checksum verified after download.
OT006's repetitive-preparation/ownership-loss fix was released and installed as **0.1.7**. OT007's managed-run
renewal/journal follow-up was released and installed as **0.1.8** through
[PR #7](https://github.com/AcostaDDev/my-harness/pull/7); its draft/public downloads and installation were verified
([evidence](phase/OT007-task-run-lease.md)). The one-off queue is empty; P001-T001 is complete as design/inventory,
P001-T002 as an isolated calculator/reference library and P001-T003 as native capture/storage, integrated into
`develop`; P001-T004 is complete and integrated into `develop`, P001-T005a (accounting UI) is complete as source (D264) and
T005b (billing/reference controls) is next, split by [D263](DECISIONS.md#d263--p001-t005-split-accounting-page-and-billingreference-control-contracts). No production
retry was made.
See [OT005 release evidence](phase/OT005-preparation-tool-links.md); one-off deliveries are separate from Metrics work.

**Objective:** Record detailed consumption by provider and effective model, with reproducible cost and credit
analysis, versioned reference data and explicit coverage/provenance. Start with the supported Claude Code and Codex
clients; keep the accounting concepts extensible without adding another execution provider.
**Status:** active phase; T001 design/inventory, T002 pure calculator/references and T003 native capture/storage,
billing binding, explicit cohorts and format-3 archives complete and integrated into `develop`; remaining tasks in
[NEXT_STEPS](NEXT_STEPS.md). T004's bounded read-only queries/API are complete as source
([evidence](phase/P001-T004-aggregates-api.md), D262) the accounting UI (T005a, D264) is complete as source, and the controls (T005b, D263) and qualification (T006) remain.
[T002 evidence](phase/P001-T002-reference-calculator.md), D258; [T003 evidence](phase/P001-T003-capture-storage.md), D259. [T001](phase/P001-T001-accounting-contract.md) and D254–D257
settle the technical contract, source limits and synthetic acceptance matrix; data/flows remain labelled planned
until their implementing tasks. D234 still owns the six-task plan.

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

**Start here:** [task plan](NEXT_STEPS.md), [phase handoff](phase/P001-metrics-records.md), then
[pricing references and worked examples](phase/P001-metrics-records-references.md).

## P002 — Continuous Mode

**Target release:** `0.2.0`, published at P002 closure (D253)
([D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020)).

**Objective:** Automatically close and archive a completed phase, open and plan the next phase, and continue its
execution under one explicit, bounded authorization. Chain tasks, commits and the READY check while stopping at
the first error, question or limit.

**Status:** planned after P001; design and tasks pending.

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
