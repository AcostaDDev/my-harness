# P001-T001 — Accounting contract and evidence inventory

Status: accepted design; source inventory completed on 2026-10-27 against `2dcf9d4` (released code `v0.1.8`).
Implementation belongs to T002–T005; no new runtime format, table, configuration, route or calculator exists yet.
Authority: D074/D144/D150/D173–D174/D216–D228/D231–D234 and
[D253–D257](../DECISIONS.md#d253--phase-release-targets-after-018).

Owner/delivery: P001-T001, branch `docs/p001-t001-accounting-contract`, topic → `develop`, commit/merge/push
authorized by the owner. P001 targets **0.1.9 at phase closure**; P002 targets **0.2.0 at its closure**. No individual
T001 release, tag, installation or service operation. Qualification/publication remains phase work in T006 and
the release route in D235; the published `v0.1.8` remains intact. Delivery evidence is below.

## 1. Invocation inventory

There are three production calls to `adapter.invoke`: `core/engine/contracts.py:invoke_agent`,
`services/profile_preparation.py:_execute_step`, and `services/configuration_assistance.py:confirm`.
The first goes through managed attempts; the other two intentionally do not (D225/D227).
All paths below are under `src/my_harness/`. CLI provider is `codex` or `claude`; model vendor, billing platform,
product and scheme are separate dimensions. Role means the actual request role, with the configured agent role
recorded separately (several request roles use the reviewer configuration).

| Lane | Invocation / persisted source today | P001 accounting boundary |
|---|---|---|
| Task planning | `core/engine/workflow.py`, `contracts.invoke_agent`; purpose `task`, role `planner` | One managed attempt; deterministic `planning.deterministic_task` creates no planner invocation. |
| Execute / revise | `workflow.py`, roles `executor`, same task run, increasing attempt/round | Each fresh invocation counts, including failed revisions; a retry is new consumption, never a replacement. |
| Independent task review | `workflow.py`, role `reviewer` | Each review counts even on REVISE/BLOCKED; native formatting/validation adds no model invocation. |
| Phase check | `core/engine/phases.py:check_phase`, `storage/phases.py`; purpose `phase_check`, role `phase` | Only after deterministic readiness/content/validation gates does the phase reviewer run. Early NOT_READY has no model. |
| Phase close / transition | `phases.py:close_phase`, `core/engine/document_ops.py`, `storage/phases.py` / `transition.py` | Current close rechecks READY and applies intents; no new model. Its earlier phase-check invocation is counted once. Earlier recorded protocols remain readable. |
| Phase planning | `core/engine/definition.py`, `storage/planning.py`; purpose `phase_planning`, role `planning` | One managed attempt per model turn, including failures without an answer; plan adoption, task registration and successor opening are deterministic. |
| Project chat | `core/engine/chat.py`, `storage/chat.py`; purpose `chat`, role `chat` | One managed attempt per model turn over its HEAD snapshot. `chat_commands.py`/`chat_command` returns deterministic answers without an invocation. Confirming a proposal queues work; it does not spend tokens itself. |
| New-project definition | `definition.py`, `storage/planning.py`; purpose `definition`, role `definition` | One managed attempt per turn, including profile proposal turns. Draft review/application and confirmed foundation commit are deterministic. |
| Existing-project onboarding | Same engine/planning path plus `storage/onboarding.py`; purpose `onboarding`, role `definition` | Static inventory has no model; model turns have attempts. Confirmed adoption/commit has no new invocation. |
| Bootstrap / older import | `core/engine/bootstrap.py`, `bootstrap_discovery.py`, `storage/bootstrap*.py`, `retired_work.py` | Current bootstrap writes confirmed v2 documents without a model. v1 discovery (`bootstrap` role) and `project_import` are retired admission paths; count only actual historical attempts, never synthesize new ones. |
| Generic profile preparation | `services/profile_preparation.py`, `storage/preparation.py:PreparationAgentJournal`; executor step UUID, `managed_processes.preparation_id`, step evidence/events | New source kind `preparation_step`; one invocation per executor step. Failed steps can retain process capture even without successful step evidence. Recipe fixed-file/command/JUnit/commit steps have no model. |
| Configuration assistance | `services/configuration_assistance.py:AssistanceJournal`; `configuration_operations` kind ASSIST, payload `attempt_id`, `process.spec/capture`, result | New source kind `configuration_assistance`; reviewer request role `configuration` or executor `executor`. Scope can be global (no project/phase/task). No manufactured managed run. Applying a proposal only edits the draft. |
| Other local work | CLI discovery/version/help, permissions, registry, setup validation/save/activation, receipts, document export/edit, Git, formatter, validations, backup/migration/retention | Deterministic operations; no model row merely because a job/process exists. A configured command that privately calls a model is outside supported observation, not free or reconstructed from its text. |
| Outside the application | Manually launched CLIs, other tools/accounts, unjournaled model calls | Unsupported source; no automatic disk/account scan or managed-attempt invention. |

Managed persistence: `storage/managed.py:_history` inserts result + `attempt_metrics` + `attempt_model_metrics` in
one transaction; `confirm_stopped` can insert an interrupted result with absent metrics. `storage/metrics.py:record`
requires `result_json`; its explicit `backfill` only fills missing legacy rows, never replaces them. Queries use
per-field contributing counts; phase consumption excludes conversational purposes. The run projection is separately
written with history (D144). Neither the projection nor phase Markdown is a price ledger.

In assistance, stream bodies remain private adapter artifacts; the operation journal stores only process lifecycle
and capture. Preparation journals additionally retain executor events. `adapters/cli_agents.py:_interrupted`
writes a partial `capture.json` when journal ownership is lost; D251/D252 settlement and explicit stopped-writer
rules govern its native source. Accounting must not adopt a stray file or settle a process itself.

## 2. Capability matrix and evidence levels

Scope: adapter `cli-14`, `terminal-2` / `metrics-1`; minima Codex 0.163.0 and Claude Code 2.1.304. Later clients are
conditionally compatible (D174), not certified to emit every optional field. Current repository tests are synthetic.
No CLI was launched for this inventory. Code references are `adapters/streams.py:AgentStream`,
`core/engine/metrics.py:StreamMetrics/attempt_metrics`, `adapters/cli_agents.py`, and
`tests/product/test_metrics.py` / `test_cli_agents.py`. The older private D071 stream archive cited in a code comment
is absent from this distribution; no new inspection of those samples is claimed.

**C** = captured/normalized today when present; **R** = retained inside existing raw terminal/message evidence but
not normalized; **D** = documented in a provider API/product, without established CLI emission; **U** = unavailable
or unestablished. A synthetic fixture proves parsing behavior, not that an installed client emits the field.

| Field | Claude Code | Codex | Admission for new accounting |
|---|---|---|---|
| Requested model/effort, provider/client version | C: frozen selection/process spec | C: same | Requested is not reported. A process-less failure may lack provider/version. |
| Reported model | C: `modelUsage` keys; message models; top-level model | C if top-level/message field exists; usual supported terminal has no model breakdown | Preserve exact strings + source; a list of models without quantities does not split usage. No requested-model fallback. |
| Reported effort | C only when top-level `effort` exists | C on the same condition | Requested effort remains separate; thinking text is not effort evidence. |
| Input / cache reads / output | C: input excludes cache reads/writes | C: input includes cache reads | Normalize disjoint categories only with known semantics. Preserve raw counters. |
| Cache writes | C: aggregate `cache_creation_input_tokens` | C mapping for `cache_write_input_tokens`, nonzero semantics uncharacterized | Nonzero Codex writes cannot be priced or subtracted using `metrics-1` assumptions. |
| Write lifetimes | R if nested `usage.cache_creation` survives in terminal; streamed message usage is not retained in normalized summary. D: API 5m/1h fields | D: Responses API 30m/12h breakdown; not established for `exec --json` | T003 captures only present, versioned fields after synthetic parser characterization. Missing lifetime stays unknown; API docs do not prove CLI emission. |
| Reasoning | C: terminal `output_tokens_details.thinking_tokens`, model `thinkingTokens` if present | C: `reasoning_output_tokens` if present | Subset of output; no extra line charge. Claude estimated thinking events are not billable counts. |
| Per-request size/model | R: message starts may retain model/usage in raw events; current fallback sums starts, replaces cumulative deltas and ignores assistant snapshots | U for constituent requests inside one turn | T003 needs stable message/request identity and final counters; invocation sums cannot determine size tiers. Repeated starts currently have no ID-based deduplication in `StreamMetrics`. |
| Speed / service tier / geography | D; optional nested terminal usage could be R, not an established CLI guarantee | D; no normalized billing-speed/geography field | Model effort, wall time or configuration defaults do not verify applied speed/region. Explicit profile assertions remain labelled assertions. |
| Tools | C: deduplicated native `tool_use` IDs, anonymous counts, denials | C: completed item types/IDs (items also derive turns) | Activity counts are not billed server-tool quantities. Textual tool imitation is not a tool call (D251). Separate charged-tool evidence is D/U. |
| USD / credits / billing | C: `total_cost_usd`, `modelUsage.*.costUSD`, local estimates; no normalized rate basis | No established terminal amount or credit field | Preserve reported estimate independently. No CLI-confirmed invoice, allowance balance or purchased-credit spend. |
| Duration | C: measured wall; reported `duration_ms`, `duration_api_ms` if present | C: wall; other fields only if emitted | API duration is not generation-only time; overlapping invocations cannot be summed into elapsed time. |
| Failure / timeout / interruption | C metadata even on normal failed return; messages can be partial; lost-owner capture may only be a sealed partial artifact | C failed terminal if any; result-less interruption often has no usage | Outcome, terminal completeness and usage coverage are independent. Partial usage is an observed subtotal, never final spend or proof of stopped writers. |
| Delegation / multiple models | C: per-model summary; parent/child inclusion boundary unestablished | U: no established per-model child billing partition | Retain observations; exclude child totals from root totals unless disjointness is explicitly established. No token split from model names alone. |

## 3. Official-source revalidation

The [reference notes](P001-metrics-records-references.md) remain the original research seed. The companion
[observation file](P001-T001-reference-observations.json) is a minimal factual extraction with URLs, locale,
observation time, decimal rate strings and unknown effective dates; its SHA-256 is recorded in §10. It is research
evidence for T002, not an operational catalog or an archived copy of entire copyrighted pages. Do not rewrite it
after this task; corrections become another dated observation/version.

| Source | Result checked on 2026-10-27 | Contract consequence |
|---|---|---|
| [R1 Claude pricing](https://platform.claude.com/docs/es/about-claude/pricing) | Seed Standard rates still agree; model-specific cache reads, Haiku prompt tier, speed/region/tool conditions differ. | Use exact categories and conditions, not one universal cache factor. |
| [R2 Claude Code costs](https://code.claude.com/docs/en/costs) | CLI dollar figures are locally computed estimates, possibly organization-configured; included subscription use has a different billing meaning. | Reported USD cannot become a confirmed bill or establish a local tariff. |
| [R3 English credit card](https://help.openai.com/en/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing), [Spanish card](https://help.openai.com/es-es/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing) | Live Work/Codex rows now agree for the seed models, including Terra. The translated page identifies automatic translation. Legacy metering and Chat rows are separate. | The earlier seed discrepancy is resolved for these fetched rows, not by combining search snippets. Pin English Work/Codex data and retain both source URLs. Unresolved future conflicts block admission. |
| [R4 API pricing](https://developers.openai.com/api/docs/pricing) | Flattened HTML contains several speed tables. Model cards separately corroborate Standard rates. | Do not mistake an adjacent Flex/Fast/Ultrafast table for Standard, or apply API conditions to ChatGPT sign-in. |
| [R5 Codex pricing](https://learn.chatgpt.com/docs/pricing) | Confirms Work/Codex token-credit scheme and absence of a separate credit cache-write fee; included allowances are not token-credit balances. | Distinguish equivalent credits from observed credits spent. |
| [R6 Enterprise USD card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing) | Separate agreement-dependent USD scheme; Codex with ChatGPT sign-in has no long-context threshold surcharge. | Same unit USD does not make Enterprise usage-based pricing an API tariff. No credit-to-USD inference. |
| [R7 personal credits](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans) | Included usage precedes eligible credits and directs Codex rates to the rate card; actual availability depends on account. | No inference about which part of an invocation used purchased credits. Product auto-review safety exemptions do not exempt the harness's reviewer role. |
| [Claude model identity](https://platform.claude.com/docs/en/models/overview), [versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions) | The four suggested Claude IDs are official IDs; dateless 4.6+ IDs identify fixed snapshots, unlike older aliases. | Exact identifier records, with explicit platform and alias behavior; never invent a dated suffix. |
| [OpenAI models](https://learn.chatgpt.com/docs/models) and individual API cards in the observation file | Suggested Codex IDs have official entries; Terra is also researched without adding a UI suggestion. | Official identity/rate evidence does not prove selection or account availability in any invocation. |
| [Claude cache API](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | Documents distinct 5m/1h counters. | A provider API capability, not a blanket CLI guarantee. |
| [OpenAI cache API](https://developers.openai.com/api/docs/guides/prompt-caching) | Writes replace ordinary-input pricing; Responses details partition 30m/12h writes inside total input. | New API-aware normalization must subtract reads AND writes when established. `metrics-1` is preserved; the Codex CLI write partition remains unestablished. |
| [Codex non-interactive stream](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude programmatic CLI](https://code.claude.com/docs/en/headless) | Document streamed terminal usage / structured CLI output; neither proves every billing dimension in our minimum clients. | Optional fields need capture evidence; no real invocation is required to report an unsupported case. |
| [Codex speed](https://learn.chatgpt.com/docs/agent-configuration/speed) | Purchased-credit/PAYG factors differ from included-allowance factors; eligibility is separate. | No speed multiplier inferred from reasoning effort or elapsed time. |

Model identity and tariff observations have **unknown historical effective intervals** unless a source explicitly
states one. Help-page relative update labels and this retrieval date are not effective dates. T002 packages pinned
versions; it must not fetch during calculations. The initial scope is the four Claude and four Codex suggestions
in `frontend/src/configuration.ts`; include Terra as an additional researched reference only. Custom identifiers
stay valid configuration choices and unresolved pricing cases. Partner platforms, legacy per-message cards,
negotiated agreements without supplied rate evidence and other models are explicitly unsupported until sourced.

## 4. Record grain, identity and completeness (D254)

The planned **usage-invocation-1** ledger has one logical invocation per native source, identified by the unique
pair `(source_kind, source_id)`: `managed_attempt` + attempt UUID, `preparation_step` + executor-step UUID, or
`configuration_assistance` + operation UUID. Preserve the assistance request's UUID as evidence too. A job, run,
conversation or preparation operation can contain zero or several invocations; none is itself the billing unit.
Record nullable project/root/phase/task, purpose, actual/configured role, UTC start/end, outcome and frozen versions.
Global assistance has null project scope and must not acquire a fake project or current phase.
An initialization model string can echo a client selection. Retain its event/field provenance as reported selection;
only a response/model-usage association supported by the adapter evidence establishes the effective-model dimension.
That label describes reported response evidence, not an independent audit of provider routing or billing.

Persist the identity/expectation atomically with the native invocation intent before launch. Lifecycle projection
can advance under the existing source owner; captures/interpretations are append-only. Native observed launch gates
distinguish `pending`, `not_invoked` (positive evidence inference never began), `observed`, and `unknown_execution`.
No-spawn evidence must establish that the gate never opened; missing process rows alone prove nothing. A queued job
without an invocation intent is not an expected model invocation. Recovery never calls a model to fill a gap.

Each **usage-capture-1** contains the source key, capture/parser version, evidence digest and allowlisted evidence
sufficient for later offline interpretation, not prompts, credentials or arbitrary environment values. It records
exact requested/reported identifiers, raw counters/semantics, tool activity, client-reported decimal lexemes when
available, terminal state, timing/provenance and unknown-reason codes. A missing row is distinguishable from a row
whose fields are absent. Missing final data, invalid JSON, conflicting duplicate IDs and truncated streams remain
explicit. Replaying identical `(invocation, capture version, evidence digest)` is a no-op; changed evidence appends
a new capture, never overwrites the old one. Native source identity is not derived from stream content (two calls
with identical bytes are two calls).

Components have a stable local key and grain `invocation_total`, `model_total` or `request`, exact reported model,
optional parent key, provenance and inclusion relation `includes`, `disjoint` or `unknown`. They are alternative
views of the same consumption unless disjointness is established. Keep the authoritative terminal total separate
from its model/request breakdown and reconcile category sums before marking a partition complete. Use a complete,
consistent model partition for pricing; retain a single-model invocation total only when its model association is
established. Multiple model names without a partition leave the invocation unpriced. A conflicting partition is
visible evidence, not a reason to add both totals or invent a residual model. Request-tier pricing needs a complete
request partition, or sufficient per-request evidence proving every request is in the same tier. An invocation
sum below a threshold is not evidence that final usage is complete.

Parent totals that include children enter a scope once; child rows remain drill-down detail. Unknown inclusion
produces `delegation_boundary_unknown` and prevents a combined full total. A new harness retry has a new native
source ID and counts again. Internal provider retries/delegation not exposed by the CLI cannot be reconstructed.

Quantity coverage is `complete`, `partial` or `absent` independently of operation success. `not_invoked` is excluded
from spend denominators and shown separately. Final terminal evidence wins over constituent messages, never adds
to them; Claude ID-keyed final message counters replace cumulative snapshots. Incomplete message streams may have
measurable subtotals but cannot certify final usage. An observed zero is retained; null is never filled with zero
except when a versioned schema explicitly guarantees an omitted category is inapplicable. For legacy `metrics-1`,
preserve its current fallback semantics and floats verbatim, even where richer evidence permits a new interpretation.

## 5. Billing profiles and reference lifecycle (D255)

Global private **local-config-10** will own named **billing-profile-1** values and defaults by configured agent role;
**project-config-2** may select a global profile per role. These are proposed formats for T003, not changes to v9/v1.
The profile specifies client provider, billing platform/product, scheme, output unit, valuation basis, exact
reference-set digest and any explicitly asserted conditions/structured rate override with a reason/source. Profile
IDs are names within an immutable configuration revision, not mutable tariff identities. No credentials, account
identifiers, executable expressions, inferred balances or subscription fee allocation. Unknown is the default.

| Scheme / basis | Permitted interpretation |
|---|---|
| First-party Claude API / API USD | Valuation at the pinned applicable API rates; actual invoice remains unverified. Requires known platform and conditions. |
| OpenAI API / API USD | Separate API reference including applicable writes, tiers and modifiers. CLI evidence may be insufficient even though rate data exists. |
| ChatGPT Work/Codex credit scheme / token-credit valuation | Named current scheme/plan eligibility, separate purchased-credit/PAYG scenario. No claim that credits were actually debited. |
| ChatGPT Enterprise usage-based USD | Agreement-specific product/basis, not API-key pricing. Support only explicit source-backed terms; unknown/legacy agreement is unsupported. |
| Included subscription / equivalent valuation | Explicit counterfactual API-USD or token-credit comparator with its own reference/conditions. Label `subscription_equivalent`; it is not an extra charge or measured allowance. |
| Unknown / unsupported platform or arrangement | Preserve usage and reported estimates; no full calculated amount. |

Profiles cannot select authentication or change CLI configuration. Subscription access suffices to capture metrics;
no API key or billing connection is required. Equivalent API scenarios do not pretend subscription calls were API
requests. A counterfactual can use stated conditions, with provenance `asserted`, while unknown usage/model evidence
still blocks an exact scenario total. Included-allowance 2.5x/8x factors are contextual information, never credit or
USD conversion factors. No P001 invoice importer, manual billed-amount editor, credit purchase, quota API or fee
allocation is introduced. Reserve `confirmed_billed` as a distinct evidence kind; it has no producer in P001.

Save and activation use existing CAS, exact preview/confirmation and D238 idle-boundary gates. Old formats/files and
hashes keep their meaning; editing billing requires an explicit new-format save preview, never automatic conversion
on load. Billing-only edits do not invalidate technical preparation: T003 separates the new billing digest from the
technical receipt binding and proves existing receipt checks are preserved. Other edits still need their normal
preparation. Jobs freeze the resolved profile bytes/revision/hash and reference bundle at admission; assistance
freezes the appropriate active global/project binding at confirmation; preparation freezes it in its new plan
envelope. A queued old job or old plan lacking a billing binding stays unknown, even after activation. Resume cannot
substitute current profiles. A later explicit valuation can name a new scenario without altering that job.

Two separate **metrics-reference-1** document kinds are planned: model identity and tariff. Content-addressed IDs
use SHA-256 of canonical UTF-8 JSON (sorted keys, compact separators, no NaN, decimal values as strings, arrays
ordered by their declared keys). An envelope contains its format/kind, provider/platform/product, exact identifier
or explicit versioned alias rule, URLs/locale, observed UTC timestamp, known effective interval `[from, to)` with
nullable bounds and an explicit `effective_period_unknown` flag. Tariffs also hold scheme/unit, quantity basis,
rates, required conditions, modifiers and charge exclusions; overrides cite the prior reference and supplied terms.
Reject duplicate keys/IDs, digest mismatch, ambiguous overlaps and unsupported conditions. Unknown bounds never
mean timeless applicability. An alias mapping establishes identity semantics, not a model report for a call.

T002 seeds a packaged immutable bundle under `core/engine/` with package-data inclusion using existing packaging;
T003 stores referenced bytes/digests in additive SQLite rows. T005 permits explicit import of a bounded canonical
JSON bundle through configuration validation/preview; saving a file alone never activates it. No in-app web scraper
or network refresh is added. Importing equal bytes is idempotent; conflicting same IDs are rejected. Updating
references means a new immutable bundle and confirmed profile revision; existing captures/valuations are unchanged.
Expiry/future intervals block applicability; an old observation is labelled by age, never silently refreshed.
Unknown historical validity permits a labelled retrospective scenario, not a verified contemporaneous tariff.

## 6. Normalization, calculation and discrepancy (D256)

The new normalization **usage-accounting-1** records semantics per component. Claude:
`U = input`, with cache read `R`, writes `W5 + W60`, and output `O` disjoint. Established Codex legacy semantics:
`U = input - R`, only while writes are explicitly inapplicable/zero under that evidence contract. Responses API
semantics, if actually evidenced in a supported source, use `U = input - R - W30 - W720`. Do not transplant these
API fields into an uncharacterized CLI stream. Never subtract unproven writes or silently charge them as ordinary
input. Negative partitions, reads/writes above total input, mismatched lifetime sums and reasoning above output
are `invalid_quantity` / `inconsistent_usage`, not clamped values. Missing reasoning does not block a known O.

The pure **valuation-1** calculator takes evidence + an explicit profile/scenario + immutable references; it has no
I/O. For a disjoint category `c`, `line[c] = quantity[c] * rate[c] / rate_quantity * applicable_factors[c]`.
Token rate quantity is 1,000,000; a separately evidenced charged tool uses its own unit/quantity and reference.
Reasoning is already inside O. Never charge aggregate cache writes in addition to their lifetime components.

Select platform/scheme/model and per-request tier first, then the reference's speed-specific rate, then explicit
category-specific region/contract factors. A tariff with an already adjusted rate cannot reapply that adjustment.
Different tiers can alter input/cache/output differently; a generic multiplier across all tokens is invalid.
Server-tool fees are separate lines with independent modifier applicability. Client file/shell tool counts cannot
be multiplied by a web-search tariff. Unknown tool charges keep an otherwise priced token subtotal incomplete.
Unsupported modifier combinations are rejected rather than guessed; Batch/Flex are reference scenarios, not new
harness invocation modes. Stated profile conditions are visible assertions, never reported server evidence.

Use standard-library Decimal, never binary-float monetary arithmetic. Accepted quantities are nonnegative integers
up to `2**63-1` (booleans excluded); rates are nonnegative decimal strings at most `10**9` with at most 12 fractional
digits; at most eight factors per line, each positive, at most 1000 with at most six fractional digits. Reject
nonfinite, exponent-form and over-limit inputs with `invalid_quantity` / `invalid_rate` / `unsupported_modifier`.
Use precision 160 and trap unintended rounding during line arithmetic; rates/units have terminating decimal
denominators (1 or powers of ten). Retain exact unrounded line amounts, sum them and round once per invocation
valuation to 12 fractional digits using ROUND_HALF_EVEN. Preserve the exact sum and rounding adjustment. Aggregates
sum those persisted rounded valuation totals exactly as scaled integers; they never round individual tokens or
use SQLite REAL casts. Display formatting (USD usually two places, credits up to six) does not replace stored values.

Every result identifies normalization/calculator/profile/reference digests, selected evidence components, line
quantities/rates/factors/units, calculation status and reasons. `complete` means every charge within the declared
scope and basis is covered with an established or explicitly asserted applicable scenario. It does not mean billed.
`incomplete` means an identified case lacks required evidence: full `amount` is null, known lines may have a
`known_subtotal` with their own coverage. `unsupported` means the source/scheme/condition cannot be interpreted by
this version. A complete subscription-equivalent scenario is still clearly labelled counterfactual. Unknown
historical effective period makes an applicable historical valuation incomplete; an explicit retrospective
scenario can have a complete scenario total but never assert historical applicability.

Initial stable reason codes: `usage_missing`, `terminal_missing`, `partial_capture`, `capture_unavailable`,
`model_unreported`, `model_partition_unknown`, `model_partition_conflict`, `delegation_boundary_unknown`,
`billing_profile_unknown`, `scheme_unsupported`, `reference_missing`, `reference_conflict`, `effective_period_unknown`,
`reference_out_of_period`, `cache_lifetime_unknown`, `cache_write_semantics_unknown`, `request_tier_unknown`,
`speed_unknown`, `geography_unknown`, `tool_charge_unknown`, `unsupported_modifier`, `invalid_quantity`, `invalid_rate`,
`inconsistent_usage` and `legacy_evidence`. Multiple codes can apply. Codes remain language-neutral; T005 localizes
their explanations in en/es. A zero quantity explicitly observed can yield zero charge; absent quantity cannot.

Reported estimates remain immutable and separate. Compare only matching scope, unit, basis, model partition and
conditions; otherwise discrepancy is `not_comparable` with reasons. If the estimate's tariff basis is unknown,
show both figures without asserting a billing discrepancy. For comparable amounts, store the signed exact
`calculated - reported` delta. A documented source rounding quantum, when available, contributes half that quantum
plus the local `0.0000000000005` rounding bound to a `within_precision` comparison. Decimal lexemes alone do not
establish provider rounding accuracy: otherwise mark reporting precision unknown and show the exact descriptive
delta without a tolerance-based agreement claim. Preserve any nonzero delta and its comparison policy. Historical
floats lack an exact original lexeme: mark `legacy_float`, retain the original and do not claim equality at a
precision the evidence cannot establish. No discrepancy auto-correction.

## 7. Additive persistence, compatibility and operations (D257)

Planned tables/relationships are documented separately in
[DDBB-DIAGRAM](../DDBB-DIAGRAM.md#planned-p001-accounting-records-not-implemented). They do not change schema head
`0027_profile_proposals` or its 54 tables in T001. T003 adds the migration under D150 with a verified premigration
snapshot; no mass reinterpretation occurs inside that migration. Original histories, `metrics-1`, `terminal-1/2`,
old configuration versions, `run-projection-1`, phase summaries/catalogs and recipe sources retain bytes/hashes.

T003 records a source/capture in the same transaction that persists the corresponding native intent/result/capture.
Fenced owner loss cannot write accounting from a stale owner. If the native source already settled before accounting
was introduced, an explicit backfill can materialize it. Unique source keys, capture digests and valuation keys
make retries idempotent; rollback leaves neither half a new result nor a valuation without its inputs. Validated
references are inserted before valuations and immutable referenced rows cannot be deleted by stream retention.

Valuation identity is `(invocation ID, capture ID/digest, normalization version, calculator version, profile digest,
reference-set digest, basis, scenario digest)`. Equal evidence bytes in different invocations cannot collapse their
valuations. A different interpretation adds a row with an optional `supersedes` link; no amount
is updated in place. Ordinary totals use the original admission-bound valuation per invocation/basis, never all
valuations or an implicit latest price. Explicit backfill/repricing creates a named, closed cohort with a selection
digest; an analysis can select one cohort and count a given invocation once, including its unpriced members.
An incompletely built cohort is unavailable as a full-scope result. Legacy invocations with no admission-bound
valuation stay unpriced in that view until an explicit cohort is selected.
Cohort membership is a separate `(cohort, invocation, basis)` relation to a selected immutable valuation or an
explicit missing-evidence reason. Several cohorts can reuse the same valuation without duplicating it; membership
freezes when a cohort closes. Distinguish settled cohort gaps from incomplete construction/progress.

Keep the current `metrics-backfill` meaning. Add separately previewed, explicitly confirmed accounting backfill and
repricing operations in T003, with bounded selection/cursor, idempotency key and report. Backfill consumes sealed
native results/captures only; authorized artifact roots, size/hash checks and retired-stream exclusions remain.
When only a legacy metric exists, capture its limited provenance as `legacy_evidence`; never invent lost TTLs,
models, billing profiles or effective dates. Repricing requires explicit scenario/reference binding and never
claims a current tariff was historically effective. Neither operation launches clients, edits sources, or runs on
GET/startup/migration/restore. Old queued jobs are not re-bound by backfill.

New API fields/routes in T004 are additive and versioned; existing metrics endpoints, float `cost_usd`, nulls and
model aggregates keep their definitions. New amounts are decimal strings, not replacement values in old fields.
Bounded SQL/projection queries must include expected native invocations with no capture; do not decode whole
histories or reprice on reads. New phase exports may separately name accounting version/basis/coverage; already
frozen phase summaries are never regenerated. API shape changes require exported OpenAPI and generated types in
the implementing task, not guessed files in this documentation task.

Retention preserves invocation identities, captures' allowlisted billing evidence, components, referenced bytes,
profiles, cohorts, line items and reasons. It may remove authorized raw streams without erasing accounting facts.
T003 advances backup to format 3 for the new schema/evidence, while accepting old formats only with their already
supported matching schema; it does not promise cross-schema operational restore. A documented upgrade of an old
archive uses an explicit copy/new bundle path preserving the original query-only bundle, never GET-time migration.
Backup verifies reference/capture/valuation/cohort digests and native-source links in the same SQLite snapshot.
Restore consults those bytes without original roots, clients, configuration authority or network. Dangling evidence
or digest mismatches refuse verification; a known historical evidence gap is retained as a gap. Restoration grants
no mutation, activation, recalculation, stopped-writer proof or extra capability.

## 8. Aggregation contract for T004–T005

Group requested model and reported effective model independently; unknown/mixed model is a visible bucket. Filter
by provider, role, purpose, root/project, phase/task, outcome and UTC invocation start in `[from,to)`; invocations
crossing midnight are attributed to their start day. Global assistance belongs to global totals, not an invented
phase. Phase work excludes conversation/preparation/assistance by default and names its scope; separate installation
totals can include them. No historical SUMMARY is widened. All attempted task invocations, including revisions and
reviews, belong to task spend; conversational/setup activity is independently selectable.

Only add amounts with the same unit, billing product/scheme, basis and selected cohort/reference policy. Different
credit schemes, API USD, Enterprise USD, reported estimates and equivalent values remain separate. Model/request
children never add to an inclusive parent. Coverage reports expected invocations, not-invoked/pending/unknown
execution, present captures, complete/partial/absent usage, priced/unpriced counts and grouped reasons. For each
amount give numerator/denominator and show its known subtotal as partial when any relevant invocation is unpriced.
Missing rows remain visible even when no metric row can be joined.

Cache-hit ratio is `sum(R)/sum(U+R+all known writes)` over only comparable, complete input partitions, with excluded
invocation count; zero denominator is undefined. Cost per committed task is total task-invocation spend across
all attempted tasks in the selected scope/cohort divided by distinct tasks with a verified COMMITTED acceptance
there; it includes unsuccessful work and retries/reviews as overhead. Also report work cost linked only to committed
tasks as a separate amount, with excluded/unpriced tasks visible. Cost per task attempted uses all distinct attempted
tasks as its denominator and a separate label. Acceptance rate is not model quality. Throughput is output tokens /
matched measured invocation wall seconds with complete pairs and
positive duration, labelled wall throughput (not tokens per generation second); no API/wall duration mixing.
Overlapping durations are not elapsed service time; unknown acceptance or incomplete scope cannot yield an exact
full-scope cost/accepted-task indicator. Pagination cannot change totals or selection policy.

## 9. Synthetic acceptance matrix

All IDs, quantities, streams and references are synthetic. These are required implementation checks, **not passing
runtime tests** in T001. C1/C2/X1/X2 reproduce the companion examples under their stated conditions; additional
rows close the handoff's missing-evidence cases. §10 records the arithmetic actually checked for this document.

| ID | Input / trigger | Required result | Owning checks |
|---|---|---|---|
| A01 | C1 Sonnet U=100000,R=900000,W5=20000,O=10000; other quantities/charges explicitly zero | USD 0.44; five disjoint categories, no terminal+message sum | T002 |
| A02 | C2 moves all writes to 1h; mixed writes 10000 at each TTL | USD 0.47; mixed USD 0.455 | T002 |
| A03 | C1 writes known but lifetime absent | Incomplete, `cache_lifetime_unknown`; no cheapest-TTL fallback | T002/T003 |
| A04 | X1 Codex raw input=1000000,R=900000,O=10000, identified Sol, Standard credit scheme | U=100000; 9.75 credits; no write charge in this scheme | T002/T003 |
| A05 | X1 Fast purchased-credit factor 2; Ultrafast factor 6 with eligibility | 19.5 / 58.5 credits; included-allowance 2.5/8 is not substituted | T002 |
| A06 | X1 requested Sol but effective model missing; unknown scheme; custom model | No full amount; separate model/profile/reference reasons; usage remains | T002–T005 |
| A07 | 100 reasoning tokens within O=10000; reasoning absent | Same cost in both cases; reasoning is never another output line | T002/T003 |
| A08 | Haiku requests: prompt exactly 100000 vs 100001 (including cache), all uncached, O=1000 | USD 0.0105 vs 0.0525005; full request changes tier. Two 60000-token requests remain low tier, combined USD 0.013 with O=1000 each | T002/T003 |
| A09 | Only Haiku invocation totals above threshold; no request partition | `request_tier_unknown`; never tier by invocation sum | T002/T003 |
| A10 | C1 explicit applicable regional factor 1.1; rate already includes it | USD 0.484; applying the factor again is rejected | T002 |
| A11 | OpenAI API synthetic partition I=12000,R=4000,W30=3000,W720=4000; rates U=1,R=.1,W30=1.25,W720=2.5 | U=1000; input USD 0.01515, not ordinary input plus writes again. Same uncharacterized Codex CLI fields cannot certify this partition | T002/T003 |
| A12 | API Sol U=272000/O=1000 vs U=272001/O=1000, R/writes=0 and complete request evidence | USD 0.554 vs 1.103004 using 2x input/1.5x output above threshold; ChatGPT-sign-in credit reference does not inherit that threshold | T002 |
| A13 | Unknown speed/geography or server-tool charge quantity | Incomplete with the corresponding reason; token subtotal is not full spend | T002–T005 |
| A14 | Negative/bool/nonfinite/oversized quantities, R>I, TTL sum mismatch, reasoning>O | Invalid/inconsistent reason; no clamping or negative charge | T002/T003 |
| A15 | Terminal plus duplicate constituent messages; cumulative delta repeats | Terminal once; ID-keyed messages replace counters. Conflicting duplicate IDs invalidate that partition | T003 |
| A16 | Model partition A+B matches total; partial/mismatching split; parent includes child | Matching A+B priced once; otherwise explicit incomplete partition/boundary, never sum parent+child | T002–T004 |
| A17 | Two attempts with equal captured bytes; repeated recording of one attempt | Two invocations; replay inserts no duplicate capture/valuation | T003 |
| A18 | Failed/timeout/repetitive/interrupt, missing terminal, lost lease, result-less intent | Visible expected row/gap; partial capture stays partial; no zero, launch, retry or recovery effect from accounting | T003/T004 |
| A19 | Assistance (global/project) + executor preparation + deterministic chat/bootstrap/close | Native source keys for the first three; no manufactured attempts or model rows for deterministic work | T003/T004 |
| A20 | Alias drift/requested-reported mismatch/custom ID | Exact identities and pinned alias version; price only established reported association | T002–T005 |
| A21 | Expired/future/unknown-period/conflicting reference, same ID different digest | Explicit reason/rejection; unknown period supports only a labelled retrospective scenario | T002/T003 |
| A22 | Reference/profile edit while job queued; old job lacks binding | Original binding or unknown retained; new active profile only affects new admission | T003/T005 |
| A23 | Billing-only new-format save/activation; stale preview; legacy v9/v1 load | Exact CAS and idle boundary; technical receipt retained when otherwise compatible; old bytes/hashes unchanged | T003/T005 |
| A24 | Exact sums 0.0000000000005 and 0.0000000000015 | Half-even totals 0.000000000000 and 0.000000000002; original exact sums retained | T002 |
| A25 | Same USD but different scheme/basis; incompatible credit units; reported estimate without basis | Separate buckets; discrepancy not comparable. No universal conversion | T002/T004 |
| A26 | Comparable C1 estimate 0.45 with documented rounding quantum .01; same estimate with unknown quantum | Delta -0.01, outside .0050000000005 in the first case; precision unknown in the second. Retain both, never overwrite estimate | T002/T004 |
| A27 | Explicit backfill twice; new/overlapping repricing cohorts; interrupted transaction | Idempotent; reuse identical valuation through distinct memberships; new interpretations only; incomplete cohort construction excluded; atomic native/capture writes | T003 |
| A28 | Three expected calls: complete .44, partial .10 subtotal, absent; fourth proven not invoked | Full amount absent, known subtotal .54; coverage 1/3 fully priced, one partial, one absent, one separately excluded | T004/T005 |
| A29 | UTC boundary, mixed models, cursor/page changes, accepted/retried/conversational tasks | Stable bounded grouping/denominators and no parent/alternative duplication | T004 |
| A30 | Legacy metrics/result/phase/config/recipe bytes before and after migration/backfill/repricing | Bytes/hashes unchanged; no read-time recalculation; old API contracts preserved | T003/T004/T006 |
| A31 | Retire streams; backup/restore without roots/clients/network; corrupt reference digest | Values/reasons remain consultable; verification rejects corruption; no mutation or process-state certification | T003–T006 |
| A32 | Billing controls/partial details/archive in en/es, themes, mobile/desktop and keyboard | Clear basis/unknown reasons, bounded views; archive has no mutation/polling | T005/T006 |

## 10. Task evidence and handoff

Read-only comparison covered the code paths above and D074/D144/D150/D173–D174/D216–D228/D231–D235/D238/D239/D242.
The decision index was searched for precedents; no frozen archive was edited. All open questions in the original
handoff are resolved by §§4–8, including invoice scope, native assistance identity, future formats, backfill,
reference ownership, precision and historical validity. Unknown provider fields are supported incomplete outcomes,
not unresolved design choices or promises that T003 can discover them without evidence.

T002 owns the pinned reference representation and pure Decimal calculator. Its allowlist includes packaged JSON
under `core/engine/` and existing package-data metadata; no new dependency. T003 owns all native invocation sources,
new configuration formats, additive storage/migration, reference import backend, explicit accounting operations,
retention and backup. T004 exposes additive bounded queries/decimal-string contracts and preserves old consumers.
T005 supplies controls/import UI and en/es explanations; T006 qualifies the entire chain and the 0.1.9 candidate.
This refines the existing boundaries without beginning a second task.

Validation completed for this documentation task:

| Check | Result |
|---|---|
| Official research | R1–R7 reopened; English/Spanish credit rows compared; identity, cache, speed and CLI pages corroborated. Eighteen minimal observation records retained, with unknown historical effective intervals explicit. |
| Read-only Python AST/source comparison | Three production invocation call sites; 54 table declarations and unchanged schema head 0027; all eight current model suggestions covered by identity observations. No application modules executed. |
| Standard-library Markdown checks | 240 local targets/anchors across the 12 changed/new documents; no missing targets/anchors or unclosed fences. Six unique ordered phase tasks retain required fields/dependencies; T001 complete, T002 next, T003–T006 pending. D253–D257 are unique; 32 ordered synthetic acceptance rows; one-off queue remains empty. |
| Independent Decimal arithmetic | 17 cases passed: C1/C2/mixed TTL, X1/X2/Ultrafast, Haiku below/above and two-request boundary, region, API write partition and long-request boundary, two half-even ties, signed discrepancy and partial subtotal. Expected values are in §9. |
| Evidence integrity | JSON parses; 18 unique IDs, HTTPS sources, decimal-string rates/null unknowns and explicit unknown effective periods. SHA-256 below binds exact file bytes, not the live websites. |
| Diff/scope | Reviewed all changed/new files; `git diff --check` clean. Only current `docs/**` changed; runtime version/schema, dependencies, source/tests, OpenAPI/types, archived evidence and recipe sources remain unchanged. |

Observation file SHA-256:
`2e7e88f759e206f40ceb641668d104fbe788fae37e75ecb117de6f71e790baf8`.

Omissions: no unittest/pytest/frontend suites, migration/schema execution, package build, browser QA, real CLI or
provider invocation, private billing/run inspection, harness operation, installation or service restart. There is
no new runtime code to qualify in T001. The synthetic matrix is an implementation acceptance contract; only the
17 arithmetic cases above were executed here, not the future integrated cases. API-internal fields remain
unestablished for CLI capture wherever §2 says so.

Delivery states: documentation source/design complete; integrated through the D235 topic → `develop` merge and
published to `origin/develop` as this task's source delivery. Git records the source/merge commits; final session
verification checks the remote ref and clean checkout. This is not a distribution publication. **0.1.9 remains
pending P001 qualification/closure/release**, **0.2.0 remains pending P002**, and local installation is outside T001.
