# P002-T027 — Integrated security and provider audit

## Scope and delivery contract — 2026-11-09

Owner: P002-T027, NEXT_STEPS task contract; G15 security/provider portion. Effective base: clean
`develop` at `fdc81bdab862115fb7b664e8a27dee6c5e28dd4e`, equal to local `origin/develop`.
Topic branch: `feat/p002-t027-security-provider-audit`. ONE_OFF_TASKS queue checked: empty.
T026 source `2fe92a4` is integrated after independent technical re-review (D319).

The owner authorized this local audit, bounded corrections to accepted contracts, synthetic regression tests
and a reviewable diff. Evidence planned: TM01–TM20 control/disposition matrix, MC1–MC7 matrix with client,
version, role, transport and provenance, integrated adversarial regressions, recovery/trace cross-checks,
G15 measurable synthetic criteria and explicit unqualified cells. Historical T021/T022 references in T001/T002
mean current T027/T028 (D303). Frozen historical evidence will remain unchanged.

Delivery route (D242): local source ready for independent technical review → separately authorized source commit
and integration into `develop` → 0.2.0 release through protected `main` → distribution/publication → installation.
The implementation session authorized only the first stage. It performed no commit, merge, push, publication, installation, network
installation, global configuration changes, service startup, harness execution on this repository or real
agent/provider invocation. Operator installation remains **0.1.9**. No new dependency is planned.

T028 owns complete journeys, UX and performance; T029 owns package/release qualification. New native qualification
needs specific owner authorization on disposable synthetic projects. Same-user access and already-started native
actions retain D064/D065's cooperative-containment limits. Design changes or missing owner decisions block only
their dependent acceptance cells.

## Minimum acceptance contract

These are synthetic pass/fail checks of accepted invariants, not new model-quality or performance targets:

| Check | Threshold and observed boundary |
| --- | --- |
| A — authority (INV-04/10/11/12) | Zero unauthorized accepted revisions, grants, command effects or cross-project content deliveries in adversarial cases; a denial is checked at the effective service and in persisted outcomes/events |
| P — client/process (INV-07) | Every MC1–MC7 omission blocks a scoped launch; one actual fake invocation per launched attempt; zero automatic retry/fallback; every launched relay observed stopped, independently of CLI exit 0 |
| R — recovery (INV-02/05/06/08) | One original attempt/invocation/operation identity across recovery; no repeated inference; stale actions acquire no authority; no writes or foreign reads during archive consultation |
| O — observation (INV-09) | Available raw bytes/digests, tool events and partial counters retained; every unreported usage/model field stays absent/unknown; no fabricated zero or comprehension |
| E — audit coverage | All TM01–TM20 and MC1–MC7 have reproducible evidence and a disposition; unsupported cells remain explicitly unqualified |

## Evidence index and reproduction

All current checks use temporary synthetic Git/SQLite, in-process HTTP clients, scripted ports or local fake
executables. No service listens, real CLI/provider is invoked or native cell renewed. Paths below identify the
executable tests; test names identify the exact boundary reused, rather than treating a previous task's completion
as sufficient evidence. The closing general check includes these suites.

| ID | Source and decisive cases |
| --- | --- |
| E1 | [T027 probes](../../tests/product/test_security_provider_audit.py): injected catalogue/compound grants; broker-to-domain grant/parent revocation and ceiling narrowing, for both first effect and replay; foreign IDs/caller forgery; same-revision context substitution; stored unsafe judge proposals; all seven missing qualifications for both clients and reviewer/executor; failed scoped streams with durable evidence; each judge duty over real stdio |
| E2 | [Broker](../../tests/product/test_tool_bridge.py): `test_scope_schema_closed_envelopes_replay_and_revocation`, `test_independent_guard_rejects_extra_servers_tools_and_approval_bypass`, `test_cancel_mid_call_stops_detached_bridge_even_with_exit_zero_and_never_relaunches`, `test_relay_loss_terminates_during_domain_call`, availability/import-isolation/receipt-failure/archive cases |
| E3 | [Domain commands](../../tests/product/test_domain_operations.py): `test_only_the_owner_adopts_and_proposals_keep_their_author`, sensitivity/classification, current exact capability, frozen revision, atomic outcome and graph replay cases; [contexts](../../tests/product/test_frozen_context.py): instruction injection, immutable sources, bounded exposures, actual delivery and rollback |
| E4 | [Permissions](../../tests/product/test_permission_lifecycle.py): compound dimensions/current ceilings, recursive permanence/expiry, revocation serialization, post-executor native cancellation, target normalization, one-operation consumption and inbox confirmations; [judge](../../tests/product/test_judge.py): G16 E01–E21 corpus, native-shaped malformed/operational failure distinction, wrong duty, unsafe tier/duration/alternative, reconsideration, frozen profile and recovery |
| E5 | [Integrated autonomous effects](../../tests/product/test_autonomous_journey.py): `test_delegated_task_contract_rejects_weakened_criteria_protected_paths_and_foreign_commands`, delegated adoption/closure guards, revoked queued job, criterion drift before queue/commit, T014 transactional races, held-review changes; [autonomy](../../tests/product/test_autonomous_roadmap.py): bounds/lineage, caps on unknown usage, auth/quota durable stops and no automatic resume |
| E6 | [Knowledge exchange](../../tests/product/test_knowledge_documents.py): hostile paths, dirty/link targets, forbidden history, embedded operational fields, exact consent, uncontained content and partial-export recovery; [export](../../tests/product/test_document_export.py): collision/foreign-byte preservation, dirty/stale targets and partial closure/export recovery |
| E7 | [Inbox](../../tests/product/test_inbox.py): stale READY, expired permission, duplicate action, owner questions, HTTP and archive guards; [contextual chat](../../tests/product/test_chat_context.py): `test_foreign_missing_incoherent_stale_and_browser_content_queue_nothing`, UTF-8/injection, frozen evidence, delivery faults and forged persisted element |
| E8 | [Observed steps](../../tests/product/test_observed_steps.py): malformed records/gaps, unique native/broker linkage, retention/oversize/link boundaries, projector replay; [trace observation](../../tests/product/test_trace_observation.py): absent/partial telemetry, cancelled exit 0, secret masking, closed/bounded envelopes; [work map](../../tests/product/test_work_map.py): `test_guards_isolation_cursors_and_restored_query_only_archive`, invocation/source isolation, permission ancestry and unknown status |
| E9 | [Operation journal](../../tests/product/test_operation_journal.py): real process-exit fault matrix, unresolved invocation and stale writer, cross-root replay/read/complete refusal, immutable events/offloaded artifacts and archive reads; [installed recovery](../../tests/product/test_installed_recovery.py) and [migration](../../tests/product/test_installed_migration.py): T026 exact migration, conversion and backup-upgrade fault cases; [orchestration](../../tests/product/test_orchestration.py): graph-version quarantine and import boundary |
| E10 | [CLI adapter](../../tests/product/test_cli_agents.py): missing help capabilities, unexpected/partial/error streams, no-GO persistence faults, raw captures, live/unknown groups and fresh frozen selection; [T002 historical feasibility](P002-T002-feasibility.md) §§3–6: native probes only, not the integrated-code qualification |

Focused reproduction of the added boundary and its consumers:

```sh
scripts/check tests/product/test_security_provider_audit.py tests/product/test_permission_lifecycle.py tests/product/test_tool_bridge.py tests/product/test_judge.py
```

Individual cases can be selected with `-- -k <test_name>`; all fixtures remain synthetic.

## Corrected finding F01 — substituted permission evidence

**Contract:** D291, T001 §8 and INV-11: canonical evidence/authority comes from trusted invocation binding, not
model-selected identifiers. **Before:** `PermissionLifecycle.request` compared the submitted context's project and
accepted revision with the caller. Another valid snapshot of that same revision, containing different code or
knowledge exposures, could create a second permission request/evidence identity inside the same invocation.
No grant or inference was automatically created by this bug, but the persisted request incorrectly asserted new
evidence and could feed reconsideration/owner escalation.

**Reproduction:** `test_permission_request_cannot_substitute_another_context_at_the_same_revision` creates two
different snapshot hashes at one accepted revision, seals only the first into a live fenced invocation with a real
permission boundary, and invokes `permissions.request` through the broker. Before the fix, the second call returned
`ok: true` with a new request. The isolated regression failed **1/1** on that assertion.

**Correction:** the command transaction uses the existing `frozen_context.bound` verifier to compare the submitted
snapshot with the exact invocation context before equivalence lookup or request persistence. A valid request still
works; substitution returns `permission_invalid`, appends a domain refusal and its trace, and creates no second
request. D320 records this enforcement detail. No design expansion, catalogue/schema rewrite or new message.
Flow parity is in [permissions](../flows/permissions.md). Model/migration/API-shape/frontend/en-es parity is not
needed: those surfaces do not change. Historical permission evidence is preserved.

No other reproducible accepted-contract defect was found in the audited paths. This is a bounded audit, not a proof
against every adversarial repository or model behavior.

## TM01–TM20 integrated disposition

**Controlled** means synthetic enforcement evidence for this scope. **Mitigated** includes the stated residual.
**Conditional** means a qualification/delivery cell remains open, not a synthetic pass for a native capability.

| Threat | Control at the integrated boundary | Reproducible evidence | Disposition and residual |
| --- | --- | --- | --- |
| TM01 injection | Canonical content is evidence; transport caller, closed command schema and current authority govern effects | E1 injection and context-substitution regression; E3 instruction rendering; E7 contextual injection | Controlled; F01 corrected. Models can still produce poor authorized proposals |
| TM02 catalogue/schema poisoning | Harness-owned versioned entries, scope and exact digest; no catalogue assembled from model text | E1 injected descriptor/body, wrong digest and unchanged catalogue; E2 schema/scope cases; E3 pinned historical digests | Controlled; trusted installed code remains in the TCB |
| TM03 generic dispatch | `invoke_tool` resolves the exact scoped logical command and re-enters ordinary authorization | E1 owner-adoption/respond attempts and effect/replay denials; E2 SQL/code/unscoped refusals | Controlled; no SQL/arbitrary-code tool |
| TM04 identity/project forgery | Persisted attempt/invocation/operation/job/lease/lock/context caller verification; all IDs scoped server-side | E1 real authority and foreign-ID cases; E2 forged caller fields; E7/E8/E9 foreign query/replay/archive cases | Controlled within mediated routes; same-user files remain accessible |
| TM05 self-adoption/criteria drift | Proposal and adoption separate; owner-only exclusions; delegated exact accepted criteria and content-bound child checks | E1 proposed weakening leaves accepted criterion unchanged despite combined grants; E3 owner-only adoption; E5 changed/weak criteria and transaction races | Controlled; semantic mistakes inside valid delegated scope remain possible |
| TM06 grant laundering/accumulation | Every required dimension intersects frozen/current ceilings and exclusions; no role/scope elevation | E1 accumulated tool/product grants, F01, effect and replay revocations; E4 compound dimensions/inherited tiers | Controlled; a grant never confirms future content |
| TM07 revoked/permanent grants | Recursive current ancestry/expiry, new-boundary snapshots, transactional effect checks and existing process stop | E1 grant/parent/ceiling interposition before effect/replay; E4 expiry/cascade/live writer; E5 queued inference/tag guards | Mitigated: a native action already started can finish before cooperative stop |
| TM08 unsafe judge/escalation | Eligibility, owner-only tiers, duty/evidence/duration/alternative checks, abstention and explicit consumer | E1 stored VALIDATED proposals rejected for six faults; E4 G16 corpus, no implicit adoption, malformed versus operational stop | Synthetic controls pass; native judgment/error rates unqualified (RB1). No deterministic claim of optimal escalation |
| TM09 fabricated imported history | Selected import creates knowledge only; exact preview, provenance and forbidden operational fields | E6 forbidden-history/embedded-fields cases; E9 converted portable transfer does not copy authority/history | Controlled; imported prose can still contain misleading claims |
| TM10 generated-target abuse | Canonical owned paths, clean baseline, links/collisions refused, sealed delivery and delegated contract paths | E6 hostile/dirty/link/partial-write cases; E5 protected paths and stale commit/closure checks | Mitigated under D064/D065: concurrent same-user link/hard-link races are not isolation |
| TM11 direct storage access | Relay has only private endpoint; isolated imports; no DB/SQL tool; role-specific launch guards | E2 import shadowing and extra tools/server/bypass refusals; E1 real role binding | Mitigated only: same UID can read/modify DB, artifacts, endpoint and exports outside the checkout |
| TM12 crash replay | Durable intent/identity, fenced effects and settlement; unresolved inference never reissued | E2 cancelled in-flight broker/recovery; E9 process-exit/seal/settlement fault matrix; E7 lost-delivery faults | Controlled within tested fault boundaries; uncertain writers require explicit confirm-stopped |
| TM13 stale inbox | Items carry no authority; fresh version/content/permission guards; domain idempotency | E7 stale READY/expired permission/duplicate owner actions; E4 standing-permission shortcut; E5 stale owner answers | Controlled; opening/reading an item does not approve work |
| TM14 misleading telemetry | Native/broker/logical events separate; exact byte evidence; source/coverage labels and unknowns | E1 failed scoped stream captures/one ledger row/unknown usage; E8 partial/malformed/projection tests; E9 no fabricated completion | Controlled for observed evidence; CLI internals and receipt comprehension remain unknown |
| TM15 exhaustion | Saved finite lineage/no-progress bounds, admission caps, bounded reads/context/steps, storage guards | E5 long-roadmap/bound/cap/unknown-usage cases; E3 bounded queries/context; E8 capped steps/queries | Mitigated; optional token/valuation/deadline caps are thresholds, an in-flight call can exceed them. T028 owns practical performance |
| TM16 client/provider drift | Fresh capability/launch identity and independent argv guards; exact scoped qualification; no harness retry/fallback | E1 all MC omissions and auth/quota/partial/invalid streams; E2 discovery/cancellation; E10 missing help/frozen version; matrix below | Conditional: current-code synthetic pass, historical native provenance only; missing native cells stay closed (RB1/RB2) |
| TM17 sensitive content | Explicit environments, sanitized bounded trace projections, knowledge-only exports, non-sensitive notification payload | E8 secret-pattern masking; E6 export scope; E7 notification/HTTP tests; E2 isolated environment/relay launch | Mitigated; authorized prompts and retained owner originals can contain committed project secrets. Originals are not claimed sanitized |
| TM18 local API | Shared session middleware, exact Host/Origin, CSRF and archive mutation refusal; scoped readers | E6/E7 knowledge/inbox/chat HTTP misuse; E8 map/trace archive and foreign reads | Controlled for tested API boundaries. No multi-user/remote-host security claim |
| TM19 supply chain | Existing exact lock under D280; offline runtime; only orchestration imports LangGraph; no hosted tracing | E9 import guard and T002 lock/offline/no-hosted-trace evidence; closing frozen/offline checks | Conditional: no dependency change; candidate package/offline installation requalification belongs to T029 (RB4) |
| TM20 graph drift | Registered version/structure stamp checked before resume or replacement; explicit recovery/quarantine | E9 version/structure mismatch; E5 failed-thread replacement cannot bypass stamp | Controlled; no automatic upgrade/re-authorization of an in-flight continuation |

## MC1–MC7 client, profile and transport matrix

`H` = historical native observation from T002 only; `H*` retains its supervisor-control condition.
`S` = synthetic current implementation evidence.
`S*` = exact shared transport/process boundary reused across roles, with direct role admission/normal cleanup also
checked. `W` = write-role policy checked; MC5's no-native-write requirement applies only to read-only roles.
`U` = unqualified; `—` = outside this transport/role's applicable contract. No `S` promotes a cell to native.

| Client | Version | Role/profile | Transport | MC1 | MC2 | MC3 | MC4 | MC5 | MC6 | MC7 | Origin and exact scope |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Code | 2.1.312 | reviewer, haiku/low | probe stdio broker | H | H | H | H | H | H | H | T002 §§1/3/4/5, probe scripts and saved native results; one sample per case, read-only |
| Codex | 0.165.0 | reviewer, gpt-6.1-sol/low | probe stdio broker | H | H | H | H | H | H | H* | Same historical source; MC7 requires independent supervisor reaping/EOF/parent-loss control, not CLI exit status |
| Claude Code fake | 2.1.312 asserted | reviewer, synthetic-model/medium | integrated stdio broker | S | S | S | S | S | S | S | E1/E2, real adapter/relay/broker/journal, fake executable only |
| Codex fake | 0.165.0 asserted | reviewer, synthetic-model/medium | integrated stdio broker | S | S | S | S | S | S | S | E1/E2, same synthetic scope, no native model reported |
| Claude Code fake | 2.1.312 asserted | executor, synthetic-model/medium | integrated stdio broker | S | S | S | S | W | S | S | E1/E2, guarded configured native writer tools; does not qualify real filesystem containment |
| Codex fake | 0.165.0 asserted | executor, synthetic-model/medium | integrated stdio broker | S | S | S | S | W | S | S | E1/E2, workspace-write guard; same containment limit |
| Claude Code fake | 2.1.312 asserted | judge: permission, planning_choice, spec_gap, blocked_check; synthetic-model/medium | integrated stdio broker | S | S | S | S | S | S | S* | E1 each duty performs search/describe/lookup over stdio; E4 validates/submits each exact duty scope and result; cancellation loop reused from E2 |
| Codex fake | 0.165.0 asserted | judge: same four distinct duty cases; synthetic-model/medium | integrated stdio broker | S | S | S | S | S | S | S* | Same provenance; native judge qualification remains absent |
| Both native clients | exact historical versions | executor or any judge duty | integrated stdio broker | U | U | U | U | U/W | U | U | No native write/judge cell in T002; simulated tests cannot fill it (RB1/RB2) |
| Both native clients | any other version/profile | any scoped role | integrated stdio broker | U | U | U | U | U | U | U | Exact qualification lookup refuses; no later-version inference from the native reviewer cells |
| Both clients | eligible cli-14 versions | planner/phase/chat/bootstrap/definition/planning/configuration | legacy non-broker launch | — | — | — | — | — | — | — | E10 and existing role workflows cover their legacy contract; no MC1–MC7 scoped-broker qualification is claimed or borrowed from reviewer |
| Claude Code | any | optional native ToolSearch | deferred native discovery | U | U | U | U | U | U | U | T002 comparison only, no product optimization enabled; portable broker remains the default |
| OpenCode | any | any | any | — | — | — | — | — | — | — | Out of scope, no adapter and no qualification in this task |

For MC1 the integrated adapter's JSON payload is validated by the owning engine/duty service; T002 native probe
argv, including its Codex `--output-schema`, remains historical evidence for that probe, not a byte-identical
current-code run. MC2–MC5 use strict invocation-only configuration, the harness server's exact three-tool allowlist,
server-local approval, read-only native tool limits and an independent guard. MC6 compares observed tool events
with broker/logical events, without inventing hidden calls/turns. MC7 covers normal exit/orphan, explicit cancel
with exit 0, mid-call EOF, parent loss and supervisor disconnect. All seven absent capabilities are denied through
the actual scoped adapter before launch for both reviewer/executor clients (28 cases), beyond the earlier pure
qualification tests. Judge qualification is independently mandatory at assemble/seal/start (E4).

Client identity is **not** an inference-provider or reported-model assertion:

| Evidence | Client | Inference route/provider evidence | Requested model/effort | Reported model |
| --- | --- | --- | --- | --- |
| T002 native | Claude Code 2.1.312 | CLI-native route; no independent backend attestation | haiku / low | claude-haiku-5-5, reported by that historical run |
| T002 native | Codex 0.165.0 | OpenAI CLI route; no backend attestation from tool traces | gpt-6.1-sol / low | Unknown; not reported by that stream |
| T027 current-code | both named fake clients, asserted versions | **None**: local synthetic executable, no inference service | synthetic-model / medium | Absent except explicit synthetic Claude partial-message marker `synthetic-reported` |

The legacy configuration/accounting field named `provider` selects the client adapter (`claude`/`codex`); it does
not prove a remote backend. Requested selection, per-message reported model and absent native telemetry stay
separate in process captures/accounting. There is no provider/model/API-billing/catalogue fallback. The harness
issues one invocation; undocumented retries inside a real CLI/provider remain unknown, not certified absent.

## Recovery, trace and read-only cross-check

T026's [fault matrix](P002-T026-installed-recovery.md#fault-matrix) is reused at its exact seams (E9), rather than
rerunning a harness against this repository. Process-exit-before-GO and output-before-settlement preserve the original
native attempt, usage invocation, captured bytes and operation seal. Lease expiry never proves death; a stale owner
cannot settle. Confirm-stopped reconciles uncertain inference without opening an agent port. Graph stamp mismatch
quarantines before execution, including replacement after an autonomous failure.

E2's in-flight broker cancellation adds the authority/process cross: detached relay stopped even at CLI exit 0,
operation UNCERTAIN, old caller denied. E1 adds persisted real-grant checks between broker entry and domain effect,
including idempotent replay; historical boundaries stay identical. E5 verifies revocation again at delegated native
admission and Git reference effects. E7 verifies stale inbox, chat references and lost deliveries never become
approvals or a second inference. E8/E9 isolate map, trace, source records, contextual evidence and accounting after
restore without a checkout; archive readers do not compose a client or writer. Wrong project and missing IDs are
indistinguishable. Mutations return 409/query-only refusals. Missing model/usage after cancellation or partial output
remains unknown; existing available tool/byte evidence is retained.

## G15 remainder, release blockers and residual risk

The synthetic A/P/R/O/E criteria above close only T027's audited source portion. G15 as a whole is **not closed**.
No new owner design decision is required for F01. Pending native cells are not permissions to run a provider.

| ID | Still pending | Scope blocked and evidence needed |
| --- | --- | --- |
| RB1 | New native judge qualification and model-quality thresholds | Productive native judge duties: owner must specifically authorize disposable synthetic projects and exact client/version/profile/duties; record MC1–MC7 and G16 corpus outcomes. Repeated-sample counts and acceptable unsafe-grant/unnecessary-escalation rates need the owner's measurable native qualification decision; synthetic zero-violation checks are not model-quality rates |
| RB2 | Native executor-broker/later-version/profile cells | Claims or enabling of those scoped native cells: explicit qualification authorization and per-cell seven-capability/failure/cancellation evidence, or an explicit supported-scope release disposition. Historical reviewer data alone cannot qualify them. Unmarked legacy writer paths retain their existing conditional compatibility, not a new native pass |
| RB3 | T028 complete journeys, normal mode, UX/accessibility and practical performance thresholds | Whole-phase G15 and full experience claims: T028's journey/criterion/UX/performance evidence and any unresolved owner thresholds. This task does not substitute isolated security tests for those journeys |
| RB4 | T029 release package and operational delivery | 0.2.0 package/install claims: exact candidate/offline package checks and separately authorized protected-main release, publication and installation. T002's pinned-runtime evidence is not qualification of the future release candidate |

T029 must keep these supported-scope decisions visible; no unqualified role may be silently labelled passed.
Optional native ToolSearch and OpenCode do not block the accepted portable-broker scope. Same-user read/write,
hard-link/replacement races and already-started native effects remain D064/D065 residuals. Owner originals, artifacts
and DB are trusted local storage rather than a hostile-user boundary. No sandbox redesign, new dependency, OS
isolation, security benchmark or guarantee of model correctness is introduced.

## Verification and omissions

Early fixture-authoring failures (role selection, result/event field names and test interposition recursion)
were corrected locally; they are not product findings. F01's failing
pre-correction regression is distinguished above.

| Command/check | Result |
| --- | --- |
| Initial focused broker/permission/judge/domain/autonomy/inbox/chat/trace/installed-recovery baseline | 529 passed (39.1 s) |
| New audit probes before F01 was added | 52 passed (6.6 s) |
| Isolated F01 before correction | 1 failed, expected refusal reproduced as an accepted second request |
| Audit + broker/permissions/judge after F01 correction | 302 passed (20.7 s) |
| Same focal suites including six stored-judge effect-boundary cases | 308 passed (20.2 s) |
| Final general `scripts/check` — executed once on the final product correction | Passed: unittest 10 ran (0.0 s); Alembic no new upgrade operations (0.7 s); pytest 3,364 passed, 3 skipped, 1 warning, 29 subtests passed (350.7 s) |
| Final audit + broker/permissions/judge focal suites, including the extra judge-stdio cases and trace-link assertions | 316 passed (23.7 s), including all 67 T027 cases |
| `scripts/check-docs` | 132 Markdown files, 0 errors |
| `git diff --check`, whitespace checks of new files and final diff inspection | Passed; tracked changes and both new files reviewed |

The full check collected 59 T027 cases before the final eight judge-stdio cases were added. Those eight cases and
the final test-only assertion refinements were then covered by the 316-test focused closure. Product code did not
change after the general check started; the general suite was not repeated. The three existing skip conditions
and one warning remain reported; no test was newly skipped. A final-focal assertion initially used a payload key
instead of the existing trace `command_id` column; that test-only mistake was corrected and the focal closure passed.

No frontend source or contract change: Node/frontend build and visual review are not required for this diff and
were not run. No native qualification, service startup, installed wheel/package qualification, real project data,
network access/install, global change, commit, merge or delivery was performed. T028/T029 omissions and unqualified
native scopes are explicit in RB1–RB4. Independent technical review has not been performed in this session.

## Independent technical review — 2026-11-09

Independent technical review passed with no outstanding relevant findings. The reviewer inspected all nine changed
and added files, the exact invocation-context verifier and domain transaction, and the cited integrated authority,
API, archive and recovery boundaries. The 316 focused audit/permission/broker/judge cases passed independently,
including all 67 new cases. A further 92 selected integration cases passed across owner-only adoption, frozen
context, hostile imports and generated targets, delegated authority, inbox, contextual chat, map isolation,
graph recovery, installed recovery and trace observation.

The reviewer also loaded only the baseline `PermissionLifecycle.request` method from `fdc81bd` into the test
process, leaving the working tree intact. F01's regression failed at the expected substituted-context assertion
because the baseline accepted the second request. The corrected method passed in the focused run. Documentation
and whitespace checks passed independently. The implementer's full check remains recorded above and was not
repeated. Frontend, native providers and operational installation were outside this review's verification.

The owner's review instructions authorize source commit, merge into `develop` and push of `develop` upon a
successful review. This condition is satisfied. G15 native qualification and RB1–RB4 remain as recorded above.

## Delivery ledger

| Stage | Actual state |
| --- | --- |
| Local T027 source/diff | Complete and checked on `feat/p002-t027-security-provider-audit`; independent technical review passed |
| Independent technical review | Passed with 316 focused and 92 selected integration cases independently verified |
| Source commit | Pending; authorized after successful independent review |
| Integration into develop / push | Pending; authorized after successful independent review; develop remains at the recorded base |
| Protected-main release 0.2.0 | Pending T028/T029 and separate authorization |
| Distribution/publication | Pending; not authorized |
| Operator installation | Remains 0.1.9; no installation performed |
