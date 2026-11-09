# P002-T025 — Accounting and efficiency analysis

## Ownership and delivery

Source work began on 2026-11-09 on `feat/p002-t025-accounting-efficiency`, from clean `develop`
at `45805c4` (aligned with `origin/develop`, containing reviewed and visually accepted T024 source
`c1f28ab`). The one-off queue is empty and T025's dependencies are integrated.

| Stage | Disposition |
|---|---|
| Topic source | Independently re-reviewed and committed as `18bef36` |
| Integration | Integrated into `develop` by the accompanying merge |
| Release | Pending P002 closure and release 0.2.0 through protected `main` |
| Distribution/publication | Pending release build and publication |
| Installation | Pending; the recorded operator installation is 0.1.9 |

This is the D235/D242 phase route. There is no T025 design gate. G15 and installed/native qualification
belong to later tasks. The owner authorized local verification, source commit, merge and push of `develop`.

## Minimum contract and planned evidence

The [T025 task](../NEXT_STEPS.md#p002-t025--accounting-and-efficiency-analysis-formerly-t019), design basis
B08–B11, B13, B18 and B21–B23, and the [threat model](P002-T001-threat-model.md) TM14/TM15 govern this work.

- The native source remains the unique ledger grain. Audit intent and settlement at each launch boundary
  with synthetic evidence for refusal, uncertainty, interruption, duplicate settlement and distinct retries.
  Deterministic work, discovery and knowledge deliveries contribute trace evidence.
- Use direct persisted invocation links in the operation journal to project workflow and workflow operation
  independently of managed run, attempt, invocation and configuration-assistance operation. Unlinked rows
  remain visible. Group and filter using the same one-row-per-invocation accounting selection, with an
  exact accounting evidence link from L4. Preserve ordinary valuations, explicit cohorts and frozen evidence.
- Check synthetic ledger, API and read-only restored archive parity, including bounded pages, project scope
  and partial results. Keep historical formats, autonomous authority and limits, and legacy metrics semantics.
- Run a separate reproducible offline workload comparison with matched simulated tasks, measuring UTF-8
  payload sizes, exchanges, local time and exact completion criteria. Preserve the T008 evidence.
- Run focused Python and Node checks, regenerate OpenAPI and client types for API changes, and run the
  full frontend-inclusive check, documentation check and diff review before handoff.

## Inference entry points and persistence

The product launch call sites are the managed engine's `invoke_agent`, the managed judge's explicit
start/result boundary, the generic preparation executor and configuration assistance. The supported adapters
receive their native journal before launch. T006 and T014–T016 attach workflow operations only on their
graph-backed paths. The ledger counts native sources across both graph-backed and older lanes.

| Route and scope | Intent and settlement | Synthetic evidence |
|---|---|---|
| Task planner, executor and reviewer, including correction/retry | `agent_started` seals the attempt and ledger together. The structured task graph supplies its invocation operation. Fenced `_history` records the result and accounting. | `test_usage_accounting`, `test_operation_journal`, T014 task fixtures and `test_autonomous_journey` |
| Phase check and structured phase planning | Phase reviewer/check and planning use the same managed seal and checkpoint. Structured jobs supply a phase graph operation. Ordinary planning uses `planning_turn`. | `test_structured_phases` and the production autonomous journey |
| Definition, onboarding and legacy bootstrap discovery | `planning_turn` or `bootstrap_discovery` seals before the model call. The copied HEAD, inventory and evidence checks are local preparation. Existing attempts without a graph link stay unlinked. | `test_structured_intake`, `test_onboarding_conversation` and the managed supervisor fixtures |
| Chat | Ordinary chat uses the managed attempt, contextual chat adds the T024 graph operation in the same seal. Deterministic commands take the separate command path. | `test_chat_context`, `test_chat_global` |
| Autonomous readiness and delegated task contract reviews | The managed phase graph links each call's operation. The delegated authorization and cap check precede the attempt seal inside the same transaction. | `test_autonomous_journey` tests the two review prompts, ledger counts, refusals and caps |
| Judge | Explicit `start` binds the admitted request to the native attempt, invocation and operation. `record_result` checkpoints result and ruling; repeated result handling is idempotent. The unavailable role/qualification path refuses before a launchable intent commits. | `test_judge` with scripted duties, fake CLI and rollback on an unqualified marker |
| Generic preparation executor | The executor's `process_intent` seals the step's process and ledger row. `process_finished`, the closing owner and explicit stopped-writer paths settle existing evidence. | `test_profile_preparation` with synthetic success, a fault after the intent and interrupted stream evidence |
| Configuration assistance | The confirmed `ASSIST` operation and ledger intent commit together before the private workspace and launch. Completion or stopped-writer recovery settles that operation. | `test_usage_accounting` and configuration-editing fixtures with synthetic private workspaces |

Deterministic validation, closure, document/commit effects and capability checks incur no new invocation.
Tool search, schema descriptions and knowledge deliveries remain evidence inside their parent invocation.
The older **bootstrap discovery** route is itself an explicit inference call. An admitted attempt with no
process record stays `unknown_execution` when settled. A persisted process intent without launch evidence
also becomes `unknown_execution` after closure. A proven pre-spawn or pre-GO refusal is `not_invoked`;
legacy captures with the recorded stopped identity-change gate retain their interpretation. A stopped process
with retained incomplete output contributes partial evidence, preserving counters with known values.
The seal, runtime authority, refusal diagnostics, stop gates and retry policy keep their existing owners.

## Projection and consultation

The existing workflow journal provides the immediate workflow execution ID (`graph_threads.id`) and workflow
operation ID (`workflow_operations.id`). The projection matches an `agent_invocation` operation by its
unique attempt, exact `invocation_id` and project root. Using the existing attempt index keeps the link
one-to-one. The API adds both as filters, dimensions and nullable invocation fields. The separate
`workflow_linked` filter selects recorded or absent attribution. Historical rows, preparation and
assistance without a link are in the explicit null/unknown group; `operation_id` still means the
configuration-assistance operation. Run, attempt and ledger identities remain independently visible.

SQL ranks a page of workflow or operation keys and aggregates the existing invocation selection for
those keys. Ranking by invocation count counts cohort members once, including when the cohort has
several valuations for one invocation. The amount buckets keep running Decimal sums and the same
coverage/reason rules. Tests compare pages to summaries across project, phase, task and role filters,
later captures and valuations, multiple correlated events, explicit cohorts, partial outcomes and
unlinked history. The ordinary view selects the original admission valuation; selected evidence uses
the latest capture. L4 exposes the same persisted operation and opens the standalone Accounting detail
with the exact ledger identity, including for unlinked rows. The restored HTTP reads resolve project
identities from the same persisted scope as the archive map and require no checkout.

## Offline efficiency benchmark

Run from the repository root:

```sh
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline python scripts/measure_accounting_efficiency.py --repeats 30
```

[Recorded JSON](P002-T025-context-measurements.json). macOS 27.2 ARM64, Python 3.14.4, one warm-up and 30
timed repetitions per mode and fixture. The script constructs its fixtures deterministically and uses
the product's compact JSON serializer, catalogue document and descriptor formats, and broker argument schemas. Both modes answer the same ordered task for
the same immutable synthetic records. The full load includes the complete catalogue, relevant records
and unrelated UTF-8 background. The selected load includes the broker surface plus one search,
description and record retrieval per criterion. The local simulator checks the broker arguments, the matching
description digest and the selected schema's input identity. It compares the entire final answer, including
order, exact record ID, revision, value and unit,
against explicit expected answers. A wrong or missing answer fails the run.

| Background bytes | Catalogue entries | Required records | Initial bytes full / selected | Total bytes full / selected | Tool exchanges full / selected | Local median ms full / selected | Local p95 ms full / selected | Exact completions each |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 12,000 | 40 | 1 | 56,207 / 1,490 | 56,262 / 3,482 | 0 / 3 | 0.294 / 0.059 | 0.306 / 0.070 | 30/30 |
| 63,960 | 200 | 2 | 283,813 / 1,550 | 283,920 / 5,514 | 0 / 6 | 1.464 / 0.148 | 1.626 / 0.158 | 30/30 |
| 255,960 | 1,000 | 3 | 1,352,673 / 1,610 | 1,352,835 / 7,566 | 0 / 9 | 6.910 / 0.550 | 7.598 / 0.582 | 30/30 |

For the largest selected workload, search added 1,076 bytes, descriptions added 3,794 and retrieval added
924 across their request/response bodies. The common completion was 162 bytes. JSON escaping and the
simulated method/argument/result envelopes are included. The JSON artifact separates both directions at
each stage. Initial prompt and final answer form one shared exchange across modes. The reported tool
counts exclude that shared exchange, MCP initialization/tool-list, supervisor readiness, framing, real
IPC and storage. Local timings include serialization, parsing, simulated in-memory search and retrieval,
and answer construction, with fixtures already loaded. The modes run sequentially with no competing
load controlled. The p95 uses the nearest rank. Latency varies with host and load. A fresh single-repeat run reproduced every
fixture size, stage byte count and exchange count.

The observed payload reduction is for these deliberately sparse synthetic workloads. Extra calls would
incur transport and processing overhead in a deployed system. The exact completions establish parity for
the deterministic fixture only. Native tokens, provider latency, model quality, billing and quota were
outside the measurement. [T008 §5 and its measurements](P002-T008-scoped-tools.md#5-reproducible-context-loading-measurements)
remain the historical catalogue-only comparison.

## Verification and handoff

- Initial `scripts/check tests/product/test_accounting_views.py` baseline passed 11 tests. Expanded
  focused checks exercised usage accounting, operation journal, generic preparation, work map, structured
  intake, the autonomous journey, structured phases, contextual chat and judge. They exposed incomplete
  synthetic cohort rows and preparation assertions that included unrelated fixture invocations. After
  correcting the fixtures, `scripts/check tests/product/test_accounting_views.py tests/product/test_profile_preparation.py
  -- -k 'accounting_views or closes_an_executor or lost_lease_stops'` passed 14 tests.
- `node --test frontend/tests/accounting.test.mjs frontend/tests/router.test.mjs frontend/tests/trace-docs.test.mjs`
  passed all 54 focused tests. These render Accounting and L4 in English and Spanish, including the archive
  route, the exact invocation read and the absence of archive polling.
- Regenerated the exported API with
  `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline python scripts/export_openapi.py` and the
  client types with `npm --prefix frontend run generate:types`. A direct `npm --prefix frontend run check` passed.
- The single closing `scripts/check --frontend` passed unittest (10), Alembic (no new upgrade operations),
  pytest (3,278 passed, 3 skipped, 29 subtests passed, one existing duplicate ZIP-member fixture warning),
  Node (428 passed) and the TypeScript/Vite build.
- `scripts/check-docs` passed (130 Markdown files, zero errors), and `git diff --check` passed.
  The local diff review covered product code, synthetic fixtures, generated API/types, en/es keys, flows
  and delivery status. The schema and T008 historical artifacts were checked against the base.

The archive fixture restores a verified format-3 bundle, removes the source checkout and process artifacts,
asserts SQLite `query_only`, then compares scoped HTTP totals and follows the map's ledger identity into the
exact accounting detail. It compares database rows before and after consultation. The regression suite also
covers `metrics-1`, older backup compatibility and the existing autonomous authority and caps.

Local verification used temporary databases, synthetic checkouts and synthetic ports/fake CLI executables.
Browser visual acceptance, live native/provider behavior, provider billing/quota, and qualification of an
installed upgrade are unverified. The source diff remains on the topic branch for technical review. Integration,
the 0.2.0 release, distribution/publication and installation remain separate pending stages. T026–T029 are
outside this task.

## Technical review corrections

The three review findings are scoped to T025 on the same topic branch and delivery route. Regression
evidence covers wrapper-only versus native launch evidence, persisted project assistance ownership and
the separate parent autonomous execution attribution.

The launch regression interrupts the actual synthetic gate after its identity is committed and before GO.
Recovery retains the capture and classifies the execution as unknown. A second fault after native stream
output keeps its partial usage. A refusal still requires positive supervisor evidence. The classifier is
shared by the ledger and trace observation. Previous capture and trace records remain sealed.

The project assistance fixture consults the same two rows in ordinary and restored read-only modes. Global
scope counts two, the associated project one, and the foreign project zero. It includes a retired registry
identity and removes the checkout before the restored reads. The persisted operation and ledger identities
are preserved.

The parent execution projection uses exact job keys from inference-bearing children, verifies the historical
authorization lineage and project, and collapses matches before joining the ledger. The two-phase journey
attributes ten invocations, while readiness before delegation, manual work, a separate execution and a
cross-root job link are excluded. Extra matching job/child links, events, captures and valuations leave the
parent's invocation count and original admission subtotal intact. The immediate workflow grouping is separate.

The incoming technical review reported 24 focused Python and 54 focused Node passes and reproduced the
benchmark payload sizes and exchange counts. Before the correction, the added regressions reproduced
wrapper-only observations, missing project scope and the unfiltered autonomous selection.

Correction checks used the following commands.

```sh
scripts/check tests/product/test_accounting_views.py tests/product/test_usage_accounting.py \
  tests/product/test_operation_journal.py tests/product/test_work_map.py \
  tests/product/test_autonomous_journey.py tests/product/test_profile_preparation.py \
  tests/product/test_trace_observation.py
node --test frontend/tests/accounting.test.mjs frontend/tests/router.test.mjs frontend/tests/trace-docs.test.mjs
UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline python scripts/export_openapi.py
npm --prefix frontend run generate:types
```

The focused Python check passed 242 tests with one skip. All 54 focused Node tests passed. The API and
client types were regenerated. A one-repeat benchmark replay reproduced the recorded byte sizes and
exchanges, leaving the benchmark script and result artifact as delivered for the first review.

The single closing `scripts/check --frontend` passed unittest (10), Alembic (no new upgrade operations),
pytest (3,282 passed, 3 skipped, 29 subtests passed, one duplicate ZIP-member fixture warning), Node
(428 passed) and the TypeScript/Vite build. `scripts/check-docs` passed (130 Markdown files, zero errors)
and `git diff --check` passed. The local diff review covered the launch evidence boundary, the effective
project scope, the delegated join and grouping grain, and generated API and en/es parity.

The gate faults were exercised with synthetic CLIs through stopped-writer settlement. The restored
consultation regression covers project assistance, and the parent attribution regression uses the local
two-phase journey. Browser visual acceptance, live CLI/provider behavior, installed recovery and installed
upgrade qualification remain unverified. The corrected diff is uncommitted for technical re-review.
Integration into `develop`, release 0.2.0 through protected `main`, distribution/publication and installation
remain pending.

## Wrapper startup attribution

This follow-up belongs to T025 on the same topic branch at `45805c4`. The owner authorized local correction
and verification for an uncommitted review. Integration into `develop`, release 0.2.0, distribution and
installation remain pending.

The incoming re-review reported 48 focused Python and 54 focused Node passes. A new regression configured
`PYTHONPATH` to load a synthetic `sitecustomize.py` that writes during wrapper startup. The real supervisor
sent GO to the real gate with a missing executable. Before the fix, `execvpe` raised `FileNotFoundError` and
the wrapper's 16 stdout bytes caused normal settlement to record `observed`.

The supervisor now starts the gate interpreter with `-I -S`, matching the native command launcher. The
configured environment still reaches the CLI through `execvpe`. The same fault now leaves zero stdout bytes
and records `unknown_execution` in both the invocation and its sealed capture. The interrupted-launch test
checks that the synthetic CLI receives its configured environment and that partial native output remains
`observed`. The before-GO interruption and proven refusal cases remain covered. The classifier and previously
sealed records are untouched.

The focused adapter, operation journal, usage accounting, trace observation and accounting view checks passed
all 140 tests. Local diff review confirmed that the interpreter flags apply to the wrapper and that the
existing environment, GO gate and settlement path still reach the same entry points. Verification used
synthetic executables and temporary databases. Live CLI/provider behavior and installed operation were
outside the verification scope.

The single closing `scripts/check --frontend` passed unittest (10), Alembic (no new upgrade operations),
pytest (3,283 passed, 3 skipped, 29 subtests passed, one duplicate ZIP-member fixture warning), Node
(428 passed) and the TypeScript/Vite build. `scripts/check-docs` passed (130 Markdown files, zero errors)
and `git diff --check` passed.

## Source integration — 2026-11-09

Independent technical re-review passed. The reviewer inspected the adapter launch and synthetic regression
and repeated `scripts/check` for the adapter, operation journal, usage accounting, trace observation and
accounting views (140 passed). The final implementer full check is recorded above. Browser visual
verification, live CLI/provider qualification and installed-state qualification remain pending.

The owner authorized source commit, merge and push of `develop`. The accompanying merge integrates
reviewed source `18bef36`, adds the integration record and advances the plan to P002-T026. Release 0.2.0
through protected `main`, distribution/publication and installation remain pending. The recorded
operator installation is 0.1.9.
