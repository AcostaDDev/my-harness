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

**Target release:** `0.2.0`, published at P002 closure (D253). The heading keeps the reserved name; the adopted scope
is **autonomous mode and project authority redesign**
([D268](DECISIONS.md#d268--p002-scope-complete-roadmap-autonomy-and-evolving-plan-baseline), superseding
[D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020) and D233's Continuous Mode description).

**Objective:** optional autonomy over the whole authorized roadmap of a defined or onboarded project — execute tasks,
check, close and archive each phase, plan its successor and finish — without a phase-count cap, with bounded task
attempts and no-progress cycles. LangGraph orchestrates; SQLite owns structured, revisioned project knowledge;
documentation is generated with explicit UI import; scoped tools are discovered through a client-neutral contract; a
configurable judge handles delegated duties; grants can be permanent and revocable; requests, agents, turns, tools and
delivered knowledge are traced; a global inbox and a task-instance graph serve both modes.

**Status:** active since the P001 closure (2026-10-29). The owner adopted plan v0.2 and the
[design basis](phase/P002-design-basis.md) as the evolving baseline; **P002-T001 completed the contracts, flows,
threat model and coverage as accepted design (D268–D279)**, refining the plan to **v0.3** with 23 tasks
([NEXT_STEPS](NEXT_STEPS.md), [T001 contracts](phase/P002-T001-contracts.md)). T001 and T002 (feasibility, D280–D281)
are integrated into develop. **P002-T003** (LangGraph runtime and continuation foundation, D282–D283) is completed and
integrated into develop; it is exercised by synthetic graphs only and no product behavior
uses it. **P002-T004** (structured knowledge and revision model, D284–D285) is completed and integrated into develop; it is
exercised by synthetic knowledge only.

**Exit criteria (adopted with D268):**

- Created and onboarded projects use structured, revisioned database knowledge; task/decision access is attributable
  to agent runs; ordinary and autonomous operations use the same domain model.
- Scoped tools are discovered on demand through a client-neutral contract; client capabilities are qualified or
  explicitly blocked, without assumed API access, native-tool-search dependency or hidden fallback.
- Reviewer, executor and judge configuration and judge duty contracts are explicit; permission scope, permanent
  validity, revocation, delegation and acceptance checks are enforced outside the model.
- The authorized roadmap can finish without a phase-count cap, with bounded task attempts and no-progress cycles,
  exact-content/domain-revision evidence, current READY and recoverable effects.
- Events correlate requests, workflows, operations, agents, observed turns, tool calls and knowledge delivery, with
  missing native telemetry explicit.
- Generated documents are regenerated at defined boundaries without drift detection; explicit UI import preserves
  provenance and never fabricates execution or approval history.
- A global inbox supports both modes with guarded actions; the graph shows persisted tasks and actual agent
  involvement following the owner's visual direction.
- Migration, backup/restore/portability, accounting, query-only consultation and normal mode are qualified, with
  integrated security, provider and recovery audits and complete synthetic journeys.
- The 0.2.0 distribution and documentation are qualified and every authorized delivery stage is completed or explicitly
  deferred; designed-only behavior is never labelled implemented. Without an autonomous authorization, the manual
  behavior keeps its explicit confirmations.

**Dependencies:** P001 Metrics Records, the existing phase lifecycle, authorization, recovery and accounting
guarantees, and the T002 feasibility/dependency decision before dependent integration.

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
- OpenCode is a requested future CLI integration. P002's accepted portable discovery contract (D275) prepares
  the extension point; no OpenCode adapter, authentication/billing compatibility or admission qualification exists yet.
