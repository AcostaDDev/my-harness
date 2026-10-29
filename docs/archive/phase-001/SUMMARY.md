# P001 — Metrics Records: summary

Closed by hand on 2026-10-29 ([D266](../../DECISIONS.md#d266--manual-phase-closure-and-archive-in-this-repository)).
Opened on 2026-10-27 ([D232](../../DECISIONS.md#d232--metrics-records-phase-and-accounting-boundaries)); six tasks
planned in NEXT_STEPS ([D234](../../DECISIONS.md#d234--p001-task-plan-in-next_steps)); released as **0.1.9**
([D253](../../DECISIONS.md#d253--phase-release-targets-after-018)).

**Objective.** Record detailed consumption by provider and effective model, with reproducible cost and credit analysis,
versioned reference data and explicit coverage/provenance, for the supported Claude Code and Codex clients.

**Outcome.** All five [exit criteria](../../ROADMAP.md#p001--metrics-records) are met with synthetic evidence only. No
real CLI emission, account billing or invoice was validated; valuations are local calculations from pinned public prices.

## Tasks

| Task | Result | Decisions | Evidence |
|---|---|---|---|
| T001 — Accounting contract and evidence inventory | Design: invocation grain, billing profiles, reference lifecycle, Decimal valuation, compatibility, 32-case acceptance matrix | D254–D257 | [contract](P001-T001-accounting-contract.md), [observations](P001-T001-reference-observations.json) |
| T002 — Versioned references and pure calculator | `metrics-reference-1` bundle and pure `valuation-1` calculator | D258 | [evidence](P001-T002-reference-calculator.md) |
| T003 — Capture, storage and historical compatibility | Native invocation ledger, `usage-capture-1`, v10/v2 billing binding, cohorts, migration `0028`, backup format 3 | D259 | [evidence](P001-T003-capture-storage.md) |
| T004 — Aggregates and API | Read-only `/api/managed/accounting/*` with coverage, compatible buckets and 13 dimensions | D262 | [evidence](P001-T004-aggregates-api.md) |
| T005 — Controls and metrics UI (split T005a/T005b) | Accounting page; billing/reference controls and reference API | D263–D265 | [evidence](P001-T005-metrics-ui.md) |
| T006 — Qualification and phase handoff | Criterion matrix, integrated journey, invocation-label fix, 0.1.9 candidate, release, installation | D266 | [evidence](P001-T006-qualification.md) |

Handoff and reference material: [phase handoff](P001-metrics-records.md),
[pricing references](P001-metrics-records-references.md). Plan and state at closure: [NEXT_STEPS](NEXT_STEPS.md),
[STATE](STATE.md).

## Release and installation

- [PR #8](https://github.com/AcostaDDev/my-harness/pull/8), release merge `5cc1bc1727a9429c6c2b78fa115dad3508609e07`
  (tree equal to the qualified integration `34fc8bc`), annotated tag `v0.1.9`,
  [GitHub Release](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.9) published 2026-10-29 09:18:16 UTC.
- `my-harness-0.1.9-distribution.tar.gz`: 3,869,656 bytes, SHA-256
  `6eebdbc2d7df3ab8535fa457527f43f4b1515dc749f30a44c5da1320e25553ff`; public downloads verified byte for byte.
- Operator installation: generation `gen-455d272577f142df8ba411dcce1c0b16` (0.1.9, READY); database migrated
  `0027_profile_proposals` → `0028_usage_accounting` after a verified snapshot; legacy rows and configuration
  unchanged; service not started.

## Final checks

pytest 2346 passed, 2 skipped, 29 subtests; unittest 10; Node 248/248; typecheck/build; temporary-database
`alembic check`; offline distribution build and installed-wheel journey; served-archive browser QA; `scripts/check-docs`.

## Carried forward

- Unvalidated with real clients: CLI emission of request partitions, Codex cache writes and response models; real
  billing and invoices. Seed tariffs have unknown historical validity.
- Unsupported without supplied evidence: Batch/Flex, partner platforms, unpriced custom models, negotiated or unknown
  agreements, Enterprise USD without terms, unknown server-tool charges, speed/geography; no `confirmed_billed` producer.
- P002 Continuous Mode (0.2.0): [handoff](P001-T006-qualification.md#p002-handoff).
