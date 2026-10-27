# P001 — Metrics Records: reference notes

Status: research seed for the [planned phase](P001-metrics-records.md), not an operational tariff catalog.
Official pages checked on **2026-10-27**. Observation date does not establish historical validity or account access.
Values below are starter examples; revalidate model identity, billing scheme and applicable conditions in T001.
They must not be applied automatically to old runs or to an account with an unknown billing arrangement.

## T001 revalidation handoff

T001 re-opened R1–R7, compared the English/Spanish Work/Codex credit rows and corroborated model IDs/API prices.
The [accepted contract](P001-T001-accounting-contract.md#3-official-source-revalidation) records applicability,
remaining evidence limits and conflict handling. The [dated extraction](P001-T001-reference-observations.json)
retains minimal facts/rate strings with a digest in the task evidence; it is not a runtime tariff catalog.
The original seed tables/examples below are retained. The earlier translated-page discrepancy is resolved for
these fetched rows; future conflicting sources still block reference admission. API cache writes now have explicit
lifetime categories in the research, without assuming the Codex CLI emits them. Current phase target is 0.1.9
at closure (D253), not the handoff's original 0.1.2.

## Source register

| ID | Official source | Use and limit |
|---|---|---|
| R1 | [Claude model/function pricing](https://platform.claude.com/docs/es/about-claude/pricing) | First-party USD reference; inspect model-specific conditions rather than generalizing a multiplier. Partner platforms need their applicable source. |
| R2 | [Claude Code cost reporting](https://code.claude.com/docs/en/costs) | Explains locally estimated session spend and its relation to subscription billing. |
| R3 | [ChatGPT Business/Enterprise/Edu credit rate card](https://help.openai.com/es-es/articles/11481834-chatgpt-rate-card-business-enterpriseedu-credit-based-pricing) | Use the Work/Codex section for the applicable credit scheme, not the Chat per-message table. |
| R4 | [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) | Separate API-key billing reference; not interchangeable with ChatGPT credits. No API tariff table is seeded here. |
| R5 | [Codex pricing](https://learn.chatgpt.com/docs/pricing) | Entry point for plan/usage context; follow current official links for the relevant plan. |
| R6 | [ChatGPT Enterprise token-based rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing) | Separate USD contract research entry point; no rates adopted here. |
| R7 | [Personal-plan credit guide](https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-personal-plans) | Research entry point when the account is not on the R3 scheme; no rates adopted here. |

R1–R4 were opened during this documentation task; R5 was opened during the preceding investigation. R6/R7 were
identified as separate schemes, not validated as implementation inputs. Full pages have not been archived or hashed
into an approved reference catalog. T001 must record a sufficient immutable representation, digest and verification
date for any adopted tariff. English search results and the translated R3 page exposed different model lists/speed
notes during research; do not combine them. Resolve against the applicable current official source before adoption.

## Claude starter data

R1, Standard first-party USD per million tokens:

| Model label | Uncached input | Output | Cache write 5m | Cache write 1h | Cache read |
|---|---:|---:|---:|---:|---:|
| Opus 5.5 | 4 | 20 | 5 | 8 | 0.20 |
| Sonnet 5.5 | 2 | 10 | 2.50 | 4 | 0.10 |
| Fable 5.1 | 10 | 50 | 12.50 | 20 | 0.25 |
| Haiku 5.5, prompt up to 100,000 tokens | 0.10 | 0.50 | 0.125 | 0.20 | 0.01 |
| Haiku 5.5, prompt above 100,000 tokens | 0.50 | 2.50 | 0.625 | 1 | 0.05 |

R1 also documents speed, geography and tool charges. Request-size tiers require request evidence, not an invocation
sum. Verify how the threshold is defined before implementing it. These labels do not verify configured model IDs.
R2 describes CLI USD as a local estimate, potentially using organization rates; its billing authority is Console,
and included subscription usage is distinct. Preserve reported amounts independently of a new local valuation.

## Codex starter data

R3, Work/Codex Standard credits per million tokens under its applicable billing scheme:

| Model label | Uncached input | Cached input | Output |
|---|---:|---:|---:|
| GPT-6.1 Sol | 50 | 2.5 | 250 |
| GPT-6.1 Terra | 25 | 1.25 | 125 |
| GPT-6 Sol | 50 | 5 | 250 |
| GPT-6 Astra | 250 | 25 | 1250 |
| GPT-6 Luna | 2.5 | 0.25 | 12.5 |

R3 lists no cache-write charge. Its observed notes distinguish purchased-credit speed multipliers (Fast 2x;
eligible Ultrafast 6x) from included-allowance multipliers (2.5x/8x). Plan eligibility and legacy schemes matter.
Do not extrapolate these factors to API billing, other plans or ordinary harness reviewer calls from product
features with similar names. This seed is not an allowance-balance model or a USD conversion table.

## Synthetic arithmetic examples

These disjoint quantities and expected amounts are hand calculations for discussing the contract. They are not
captured sessions or provider-confirmed bills. All conditions in each example are explicit assumptions.

Let `U` be uncached input, `R` cache reads, `W5`/`W60` cache writes by lifetime, `O` output and `p*` rates per million.
Without other charges or modifiers:

```text
Claude USD = (U*pU + R*pR + W5*pW5 + W60*pW60 + O*pO) / 1,000,000
Codex credits = (U*pU + R*pR + O*pO) / 1,000,000
```

| Example | Assumed quantities and tariff | Expected valuation |
|---|---|---|
| C1 | Sonnet 5.5 Standard; U=100,000, R=900,000, W5=20,000, W60=0, O=10,000; no other charges | USD 0.44 = 0.20 + 0.09 + 0.05 + 0 + 0.10 |
| C2 | Same quantities as C1, all 20,000 writes at 1h instead of 5m | USD 0.47 = 0.20 + 0.09 + 0 + 0.08 + 0.10 |
| X1 | GPT-6.1 Sol Standard under R3; U=100,000, R=900,000, O=10,000 | 9.75 credits = 5 + 2.25 + 2.5 |
| X2 | X1 with an explicitly applicable purchased-credit Fast factor of 2 | 19.5 credits; not a subscription-allowance calculation |

For X1, the baseline Codex raw `input_tokens` would be 1,000,000, including the 900,000 cached tokens. Pricing that
raw value at the uncached rate and adding cache again would be incorrect. A separately reported reasoning count
already within O does not increase these sums.

Required negative examples: C1 without write-lifetime evidence cannot select C1 over C2; X1 with an unknown actual
model or unknown billing scheme cannot claim an exact applicable valuation. Identical token totals under a
subscription do not establish purchased credits spent. Unknown is not zero.

## Reference admission checklist for T001

- Resolve exact model IDs/aliases against official model documentation and observed client evidence; retain both
  requested and reported strings. UI suggestions alone cannot certify actual selection.
- Verify the tariff's billing product, plan/contract scope, speed, tier basis, geography and extra charge categories.
  Document unsupported cases instead of filling defaults.
- Record source URL/locale, observation timestamp, known effective interval (or unknown), adopted data bytes/digest,
  currency or credit unit, quantity basis, calculation precision and any documented override.
- Keep source observation, tariff activation and invocation time separate. Check promotions, expired references and
  conflicting pages explicitly; do not assign a historical effective date from a current help-page update label.
- Seed synthetic fixtures with pinned references and expected line items. Tests and normal runtime views must work
  offline; source refresh is an explicit operation, never a hidden price lookup during a read.
