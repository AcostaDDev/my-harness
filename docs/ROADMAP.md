# Roadmap — my_harness

The repository opens with the first local version of My Harness already built: [STATE](STATE.md) describes that
starting baseline, including guided installation/configuration, and [DECISIONS](DECISIONS.md) the decisions behind it. That earlier work is not replayed here as
phases; phases are numbered from P001 in this repository.

## P001 — Optional continuous mode between phases

**Objective:** Let one explicit, bounded authorization chain tasks, commits, the READY check, the closure and archive
of a phase, and the planning and execution of the next phase, stopping at the first error, question or limit
([D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020)). Planned for v0.2.0; design and tasks
are pending.
**Exit criteria:**
- The mode is optional and starts only from an initial authorization with an explicit scope and budget.
- It stops at the first error, blocking condition, question for the user, out-of-scope change or consumption limit,
  and the stopped work can be inspected and resumed.
- READY binding, acceptance by exact content, intent before effect and recovery keep their current guarantees.
- Without that authorization the current behavior is unchanged: explicit task batches, explicit check, closure
  authorized on READY and a confirmed plan for each new phase.
**Dependencies:** the first public release.

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
