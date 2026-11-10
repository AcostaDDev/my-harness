# P002-T030 — Semantic, context and human-editing contracts and D321 feasibility

Design owner P002-T030. Prepared on 2026-11-10 on `docs/p002-t030-contracts` from clean `develop`
and `origin/develop` at `5cc7fe5`. T001–T027 are integrated and the one-off queue is empty.
Route under D235/D242: checked design artifacts → authorized integration into `develop` → release 0.2.0
via protected `main` → distribution/publication → installation. The recorded installation is 0.1.9.

**Disposition:** the design proposal passed independent technical re-review and is integrated into `develop`
as source `9894bae`. Explicit owner acceptance is pending.
[D323](../DECISIONS.md#d323--p002-v05-planning-adoption-and-prerequisites-before-journey-qualification)
adopted the coverage/ownership plan; it did not adopt these design choices. T031 is blocked by both explicit
T030 acceptance and established D321 feasibility. D321 and D322 are accepted policy. There are no proposed
changes to their guarantees or to the behavior of any existing installation.

## Resolutions and review map

| Obligation from the [adopted plan](P002-knowledge-context-proposal.md) | Proposed resolution and future evidence owners |
|---|---|
| §§4–6, 14 semantic model, codec, decisions, legacy conversion and instructions | [Closed semantic grammar and byte mapping](P002-T030-model-codec.md), [positive and negative vectors](P002-T030-fixtures.md#codec-and-relation-vectors). D284/D285/D294 history remains readable. T031 verifies typed ownership/order/identity and immutable history, T032 round trips/ownership/effects, T033 prospective validation and T036 explicit mapping/loss recovery. T037 verifies editing against the same types |
| §§7–8, 11, 14 all inference routes, purpose, bounds, receipts, typed execution | [I01–I17 crosswalk and stage contracts](P002-T030-inference.md). T033 resolver/scoped tool tests, T034 launch/admission/accounting/no-replay fixtures, T035 profile refusal and T036 pre-adoption source proof. T038 reconciles all actual launches and recovery to one owner each |
| §§7.1, 9, 14 D321/D322 | [Isolated guest, curated projection and trusted host effects](P002-T030-d321.md). T035 future per-profile bypass denial and bounded positive controls, T034 exact launch and Git fence, T036 unowned/source transition, T038 integrated re-audit. Current proof is synthetic and partial |
| §§4.1, 10.4, 14 gates/evidence | [Append-only outcomes, coverage and effect fences](P002-T030-gates-editing.md#evaluation-contract). T031 persists exact bindings, T032 rejects operational imports, T033 evaluator and negatives, T034/T036 before-effect revalidation, T037 projection, T038 integrated proof |
| §§10.1–10.6, 13–14 authoring, recovery, impact and visual acceptance | [Separate working copy, canonical draft, adoption and export](P002-T030-gates-editing.md#human-editing-and-recovery). T031/T033 durable incomplete data, exact envelope/CAS and bounded impact, T032/T036 editor transition/export, T034 effect guard and T037 real routed UI/owner review, T038 re-audit. T028 consumes those results; T029 owns release qualification |

Baseline inspected: `knowledge.py` has six v1 item kinds, fixed link endpoints and immutable adopted decision
versions. `knowledge_documents.py` renders v1 marked Markdown and companions, requires AGENTS for v1
ownership and preserves legacy parsing. `frozen_context.py` uses explicit item IDs plus applicable instructions
with fixed bounds; `knowledge_delivery.task_context_snapshot` selects the task, without automatic linked
bodies. `autonomous_review.task_contract` currently renders Markdown and reparses it. The current task/phase
graphs wrap one work node. The inference annex cross-references the managed, judge, preparation and ASSIST
launch boundaries. `cli_agents.py` disables Codex automatic project-doc loading but that setting cannot prove
prevention of deliberate reads. Design uses the [existing data model](../DDBB-DIAGRAM.md#p002-structured-knowledge),
[current context flow](../flows/frozen-context.md), [exchange flow](../flows/knowledge-documents.md) and
[legacy file lane](../flows/documents.md) as baseline. D288 frozen exposure, D293 exact editing recovery,
D296 shared correction budgets, D298 separate phase/READY/sealed closure and D301 independent authority remain
in force. Current architecture/specification, diagrams, OpenAPI, generated client, catalogues and historical
recipes describe their implemented versions and are outside this design patch.

## Technical review corrections

| Finding | Resolution | Local evidence |
|---|---|---|
| Criterion evidence blocked its own producer and could be rebound to a phase | [Boundary producers and consumers](P002-T030-gates-editing.md#fences-and-test-matrix) and [verified phase composition](P002-T030-gates-editing.md#criterion-ownership-and-coverage-composition) | First execution reaches READY; terminal failure permits diagnostic I03 and prevents acceptance; future producer and changed inputs refuse |
| v1 section type and slug conflicted with v2 identity | [Versioned projections and typed maps](P002-T030-model-codec.md#identity-mapping-and-order) | Two same-slug sections map to distinct blocks; a converted instruction keeps its historical link and original bytes |
| Complete reconstruction conflicted with partial or edited imports | [Verified baseline and sealed selection](P002-T030-model-codec.md#markdown-and-portable-exchange) | Exact supplied view, omitted component with/without verified mapping, hidden instruction retained, marked IDE edit retains CRLF. Portable locators remain separate from host bindings |
| Deterministic admission lacked typed scope and source | [Manual entry and legacy disposition](P002-T030-inference.md#manual-deterministic-entry-and-authority) | No I01/I13 on matching typed inputs; missing limits or excess path/command refuses; legacy reconciliation has no fresh launch |
| Stage could substitute saved edits and consent identity could be lost | [Saved-copy compiler and server reservation](P002-T030-gates-editing.md#persisted-working-copies-and-commands) | Saved edits preserved, lost response and identity recover the same result, competing or late confirmation is fenced |
| A delivered task could lose phase coverage without an eligible revalidation route | [Owner-confirmed coverage renewal](P002-T030-gates-editing.md#renewal-of-delivered-task-coverage) | In the two-delivery vector, B changes A's check input. READY holds until A's exact renewed acceptance is joined to its unchanged original receipt. Changing A's delivered result instead requires a new delivery |
| A reservation could settle between recovery lookup and fence at the same generation | [Complete recovery view and writer CAS](P002-T030-gates-editing.md#persisted-working-copies-and-commands) | B's empty view cannot fence after A settles. Presenting A's result and confirming the refreshed view permits the fence. If B fences first, A's old in-transit reservation and dispatch are refused |
| Shared document regeneration could make an unchanged task result ineligible for renewal | [Task result and shared generation proofs](P002-T030-gates-editing.md#task-result-and-shared-generation-proofs) | B changes A's check input and publishes a different valid STATE generation. Stale coverage holds READY. Renewal on B's snapshot restores READY with both original deliveries. Missing original or current generation proof holds READY, a changed generated artifact of A requires a new delivery, and a view-only change stales a check that reads it |

The [review vectors](P002-T030-fixtures.md#technical-review-vectors) document the synthetic cases and their
local verification scope.

## Evidence and delivery

- Existing local offline probe passed for known fixture paths, bounded synthetic exposure, positive build/test
  and exact host Git effect with stale ref refusal. It is partial D321 component evidence.
  [Reproduction and scope](P002-T030-fixtures.md#offline-boundary-probe).
- All seven synthetic review groups passed, including the two-delivery renewal and both recovery race
  orderings, with fixture identity/order checks for 27 members and 22 links. The full documentation check,
  explicit check of the six new Markdown files and whitespace checks for tracked changes and all new files passed.
- Product, frontend and browser suites, harness, real guest and native transport were outside this design
  verification. The D321 guest and native feasibility protocol is pending separate authorization and evidence.
  [Feasibility gate](P002-T030-d321.md#evidence-and-gate-disposition).
- Independent technical re-review on 2026-11-10 verified the eight corrections, including the distinction
  between task results and shared generations. All seven synthetic review groups, documentation and diff
  whitespace checks passed. The owner authorized the source commit, merge and push of `develop` after review.
  The accompanying merge integrates reviewed source `9894bae`. Explicit design acceptance, protected-main
  release, distribution/publication and installation remain separately pending.

## Owner decisions required

1. **D321 feasibility authorization and supported scope.** Decide whether to authorize the bounded
   disposable guest test and native transport protocol separately. Accept only scope demonstrated by
   evidence, or resolve any concrete incompatibility returned by the test. D321/D322 remain in force.
2. **Explicit T030 design acceptance.** Review the v2 identity/exchange and authoring contracts, including
   the retained T013 marked IDE path, proposed v2 metadata/instruction editing transition and server
   reservation, the inference registry and budgets (including X1, X2,
   I09 and legacy documentary reconciliation), and the gate, evidence and impact rules. Accept the
   resulting supported contract as a unit, including the strict current-binding policy and the handling
   of unknown historical impact.

Record adopted choices with new decision numbers after acceptance. Both established feasibility and explicit
design acceptance are required before T031. Integration and delivery have their own authorization.
