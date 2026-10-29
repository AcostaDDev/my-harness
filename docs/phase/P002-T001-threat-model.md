# P002-T001 — Initial threat model

Status: **accepted design**, 2026-10-29; initial model, not an audit. It defines the threats each P002 task must
control and test as it builds its boundary (B23). T021 audits the integrated result against this list and records
findings; new threats found later are added with an owning task, never silently dropped. Contracts:
[P002-T001 contracts](P002-T001-contracts.md); flows: [P002-T001 flows](P002-T001-flows.md); decision
[D279](../DECISIONS.md#d279--p002-threat-model-coverage-and-design-record-placement).

No control listed here is implemented. The security baseline of 0.1.9 is unchanged: local service with session,
Host/Origin and CSRF guards (SPECIFICATION §5 rule 10), cooperative containment without operating-system isolation
([D064](../DECISIONS.md#d064--cooperative-containment-without-operating-system-isolation),
[D065](../DECISIONS.md#d065--nested-sandbox-profiles-not-qualified)) and only trusted repositories and tools.

## Scope and assets

In scope: managed projects under the P002 design in both modes, on one local machine and one operator account.
Assets: accepted knowledge revisions and product decisions; authorizations, grants and rulings; the checkout and its
Git history; generated targets; operation, trace, receipt and accounting records; artifacts and backups; owner
credentials and CLI subscriptions; the owner's attention (inbox) and consumption.

Out of scope: multi-user access, remote attackers beyond the existing loopback/session guards, a malicious operating
system account or machine owner (the history is not tamper-proof against the owner, SPECIFICATION §9), provider-side
compromise, and physical isolation, which D064 excludes.

## Trust boundaries

| Zone | Trust | Notes |
|---|---|---|
| Owner through the authenticated local UI | Trusted for decisions | Stale or duplicated actions are still guarded |
| Harness services, supervisor and domain model | Trusted computing base | Includes the LangGraph integration once adopted (G01) |
| SQLite database and artifact store | Trusted storage, same-user accessible | Not protected from processes running as the same user |
| LangGraph continuation state | Trusted code, untrusted as authority | Holds references; the service re-reads authority |
| Agent CLIs and model output | Untrusted proposals | Any text can be adversarial or mistaken |
| Tool broker requests | Untrusted requests | Caller bound by the transport session |
| Repository content, code, tests, dependencies, exports, imported files | Untrusted data | Executing project code relies on the trusted-repository limitation of D064 |
| Provider services and OS notification delivery | External | No sensitive content in notifications |

## Threats, controls and owning tasks

| ID | Threat | Required control | Owning tasks | Evidence | Residual risk |
|---|---|---|---|---|---|
| TM01 | Prompt injection from repository, tool output, exports or imports asks for broader powers or different behavior | Text is evidence, never policy; authority sealed outside prompts; every action validated by services | T005, T007–T011, T014 | Adversarial fixtures per role | A model may still produce poor but authorized work |
| TM02 | Catalogue or schema poisoning, or a stale schema used for a call | Harness-owned versioned catalogue; schema digests checked on invoke; untrusted text never alters catalogue entries | T005, T008 | Digest mismatch and forged descriptor cases | — |
| TM03 | Generic `invoke_tool` used to bypass authorization or reach SQL/arbitrary code | Each call revalidated as the underlying command; no SQL or code tool; unscoped tools undisclosed | T005, T008, T021 | Bypass attempts through the generic envelope | — |
| TM04 | Caller forgery or cross-project identifiers | Caller bound from the transport session; project-scoped identifiers verified server-side | T005, T008, T010 | Forged caller/target cases | Same-user processes can still read local files (TM11) |
| TM05 | Self-adoption, criteria weakening or goal drift by agreeing roles | Separate propose/adopt; owner-only meaning changes; criteria and requirements bound to the accepted revision; reviewer cannot accept its own proposals as owner | T004, T005, T009, T015, T016 | Weakened-criteria and self-adoption cases | Correlated model errors within delegated scope |
| TM06 | Permission laundering and compound grant accumulation | Compound effective-authority check; combinations never yield owner-only capabilities; request equivalence fingerprints | T010, T021 | Accumulation cases | — |
| TM07 | Permanent grant misuse after revocation, scope change or in another project | Project-scoped, exact targets, current ceilings on every use, revocation checked at commands and admission | T010 | Revocation race, cross-project and expiry/permanence cases | An in-flight native action may complete before process stop (D064) |
| TM08 | Unsafe judge grant or unnecessary escalation | Duty contracts, deterministic tiers, service validation, abstention, evaluation corpus | T009, T021 | Synthetic grant/deny/escalate expectations | Model judgement errors inside delegated tiers |
| TM09 | Import fabricates history: runs, approvals, grants, usage or execution states | Import creates knowledge revisions only; staged preview; provenance recorded | T013 | Fabrication attempts in import fixtures | — |
| TM10 | Generated-target abuse: traversal, links, unowned collision, discarding uncommitted bytes | Ownership manifest, root and link guards, clean-baseline refusal, sealed intents | T013, T014, T015 | Path/link/collision/dirty-target cases | Same-user changes between checks and writes (D065 races) |
| TM11 | Agents or other same-user processes read or modify the database, artifacts or exports directly | No database or SQL tool for agents; database outside the checkout; effective tool policy per adapter; claim no isolation | T008, T021 | Adapter tool-policy checks | Accepted: cooperative containment only (D064) |
| TM12 | Replay after a crash duplicates effects or inference | Operation identity, sealed intents, uncertain inference never reissued, confirm-stopped | T003, T006, T014, T015, T020 | Fault-injection matrix | — |
| TM13 | Stale or replayed inbox action approves different work | Fresh guards on every action; idempotency; items carry no approval | T017 | Stale and duplicate action cases | — |
| TM14 | Misleading telemetry: fabricated turns, double counting, receipts claiming comprehension | Declared counter meanings, source labels, unknown coverage, receipts as availability only | T006, T007, T018, T019 | Projection parity and missing-telemetry cases | Native CLI internals remain unobservable |
| TM15 | Resource exhaustion: no-progress loops, work inflation, context or history growth, disk exhaustion | Local bounds with lineage, fingerprints, bounded queries and projections, storage admission checks | T006, T007, T016, T019 | Long-roadmap and loop fixtures | Optional caps can be exceeded by an in-flight invocation |
| TM16 | Provider or client drift, unsupported capability or hidden fallback | Capability contract per client/version/profile; admission blocks; no provider/model/catalogue fallback | T002, T008, T021 | Fake-CLI capability matrix | Real-provider behavior needs separately authorized qualification |
| TM17 | Secrets or private content leak through prompts, traces, exports, notifications or portable bundles | Explicit environments (D024); no credentials in records; non-sensitive notifications; export scope limited to knowledge | T006, T013, T017, T020 | Secret-pattern fixtures in synthetic data | Project content itself may contain secrets the owner committed |
| TM18 | Local API misuse of new endpoints | Existing session, Host/Origin and CSRF guards on every new mutation; query-only 409 | T005, T012, T017 | API misuse tests | — |
| TM19 | Dependency supply chain of the new runtime | Exact locked versions through a recorded decision; offline packaging; no hosted tracing or deployment service | T002, T023 | Lock and package inspection | Trust in the pinned upstream code |
| TM20 | Graph version drift or upgrade during a long run alters an in-flight continuation | Versioned graph definitions; frozen versions; quarantine and explicit re-authorization | T003, T020 | Version-mismatch cases | — |

## Accepted residual risks

The owner accepts that autonomous mode makes important decisions and can make mistakes (discussion §1). Delegated
choices can be wrong while remaining within authority; the controls bound authority and preserve evidence, they do
not guarantee correctness. Same-user access and in-flight native actions are limited only cooperatively (D064/D065).
Optional consumption caps are thresholds, not spend ceilings. These limits are shown in the start preview and in
operator documentation (T016, T023).

## Maintenance

Each implementing task cites the threat IDs it controls in its evidence. T021 marks each threat as controlled with
evidence, mitigated with a recorded residual risk, or an owner-visible release blocker.
