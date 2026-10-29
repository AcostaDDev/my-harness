# P002-T001 — Flows, guards and recovery

Status: **accepted design**, 2026-10-29; not implemented. These diagrams specify the P002 target behavior for managed
projects. The implemented flows in [`docs/flows/`](../flows/task-run.md) remain normative for 0.1.9; each owning task
moves or updates the corresponding implemented flow there with parity when it delivers code. Contracts:
[P002-T001 contracts](P002-T001-contracts.md); threats: [threat model](P002-T001-threat-model.md); decisions D268–D279.

Each diagram is followed by its transitions with **guard**, **effect owner** and **failure/recovery**. Effect owners:
**Owner** (UI/inbox), **Graph** (routing and waits only, never effects), **Service** (typed domain command in a
transaction), **Supervisor** (sole process launcher, writer lease), **Git**/**Exporter** (adapters behind sealed
intents), and **Reviewer/Executor/Judge** (proposals or selections only). Cross-cutting rules apply to every transition:

- Every model call passes the revocation, local-bound, optional-cap and capability guards; every effect passes the
  writer, authority and intent guards (INV-01–INV-07).
- Any crash with an uncertain writer or effect leaves the ordinary path for
  [FL13](#fl13--crash-recovery-across-graph-and-domain-operations).
- Any stop persists a reason, evidence and an inbox item ([FL12](#fl12--durable-wait-inbox-answer-and-resume)).
- Quota, authentication, environment and policy failures stop without retry or fallback.

## FL01 — Admission and autonomous authorization

```mermaid
flowchart TD
    A["Owner opens the autonomous start for a project"] --> B{"Deterministic readiness: accepted revision, ordered roadmap with criteria, active phase, profile prepared, clients compatible, clean Git baseline, no pending effect"}
    B -->|fails| R["Readiness report with blocking reasons; no authorization"]
    B -->|passes| C["Reviewer gap report over the frozen revision"]
    C --> P["Start preview: scope, delegation, tiers, local bounds, optional caps, standing grants, risk text"]
    P --> O{"Owner confirms the exact preview hash"}
    O -->|no or stale| R
    O -->|yes| S["Service seals the autonomous authorization as owner_confirmed"]
    S --> G["Graph run created with references to the authorization and revision"]
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Readiness | Structural checks of G12; no uncertain writer or sealed pending intent; feasible bounds | Service | Report only; nothing persisted beyond the check record |
| Gap report | Reviewer invocation within accounting; frozen revision | Supervisor/Reviewer | Malformed output or provider error stops the preview; no retry |
| Confirmation | Preview hash, Idempotency-Key, unchanged revision and configuration versions | Owner → Service | Stale preview refused (409); duplicate confirmation returns the same authorization |
| Run creation | One active autonomous authorization per project root; excludes manual batches on that root while active | Service, then Graph | Crash before the graph run exists: the authorization is reconciled on restart, never duplicated |

## FL02 — Autonomous run states

```mermaid
stateDiagram-v2
    [*] --> RUNNING: authorization sealed
    RUNNING --> WAITING_FOR_OWNER: owner-only question, escalation or ambiguous ruling
    RUNNING --> PAUSED: owner pause at a safe boundary
    RUNNING --> LIMIT_REACHED: local bound, no progress or optional cap
    RUNNING --> FAILED: operational or policy failure
    RUNNING --> RECOVERY_REQUIRED: uncertain writer or effect
    RUNNING --> COMPLETED: all authorized phases CLOSED with criteria and coverage
    WAITING_FOR_OWNER --> RUNNING: current answer and explicit resume
    PAUSED --> RUNNING: explicit resume after revalidation
    LIMIT_REACHED --> RUNNING: owner raises bounds through a new authorization revision
    FAILED --> RUNNING: explicit resume after the cause is cleared
    RECOVERY_REQUIRED --> PAUSED: writer confirmed stopped and intents reconciled
    RUNNING --> REVOKED: owner revocation
    WAITING_FOR_OWNER --> REVOKED: owner revocation
    PAUSED --> REVOKED: owner revocation
    LIMIT_REACHED --> REVOKED: owner revocation
    FAILED --> REVOKED: owner revocation
    REVOKED --> [*]
    COMPLETED --> [*]
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| To any stop | Stop class decided by the service from typed outcomes, never by a model | Service | Stop record and inbox item in the same transaction as the outcome |
| Resume | Explicit owner action; repository, authority, versions, remaining bounds and evidence revalidated | Owner → Service → Graph | Any mismatch keeps the stop with a new reason; uncertain state goes to recovery first |
| Bounds raised | New authorization revision confirmed by hash; counters are not reset | Owner → Service | Old revision remains in the audit |
| Revocation | Owner only; blocks new commands and attempts immediately | Owner → Service, Supervisor | Active writer stopped through process control; uncertain effects go to FL13 |
| Completion | Every authorized phase CLOSED (not ABANDONED), criterion evidence and final coverage | Service | Missing evidence keeps RUNNING or stops; never claims completion |

## FL03 — Autonomous roadmap loop

```mermaid
flowchart TD
    L["Graph loads authorization, active phase and accepted revision"] --> G{"Guards: authority, revocation, bounds, caps, versions"}
    G -->|stop| X["Persist stop class and inbox item"]
    G -->|valid| P{"Active phase has an adopted plan?"}
    P -->|no| PL["Reviewer proposes plan for the authorized phase"]
    PL --> V{"Structure, scope, criteria coverage, no repeated equivalent plan"}
    V -->|valid| AD["Service adopts plan as owner_delegated child authorization"]
    AD --> L
    V -->|choice or gap| J["Judge request FL05"]
    V -->|invalid or no progress| X
    P -->|yes| T{"Pending task?"}
    T -->|yes| TK["Task operation FL04"]
    TK -->|committed| L
    TK -->|request or gap| J
    TK -->|error or local limit| X
    T -->|no| PH["Phase check, remediation and closure FL07"]
    PH -->|closed with successor| L
    PH -->|closed without successor| C["Verify roadmap completion; COMPLETED"]
    PH -->|remediation adopted| L
    PH -->|question| J
    PH -->|failure| X
    J -->|valid delegated ruling| L
    J -->|owner needed| W["WAITING_FOR_OWNER FL12"]
    J -->|no permitted progress| X
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Load and guard | Graph state holds only IDs and revisions; the service answers current authority | Graph → Service | Version drift of the graph definition quarantines the continuation (G03) |
| Plan proposal | Plan targets the authorized phase and revision; reviewer invocation accounted | Supervisor/Reviewer | Malformed output stops; equivalent repeated plans count against the replacement bound |
| Plan adoption | Stable task IDs, finite acyclic dependencies, profile-compatible capabilities, criterion coverage, no phase added | Service | Refused adoption returns typed reasons; nothing is half-adopted |
| Completion | No successor in the authorized roadmap revision; no invented phase | Service | ABANDONED phase stops the run without success |

## FL04 — Task operation in both modes

```mermaid
flowchart TD
    A["Task admitted: manual owner_confirmed or autonomous owner_delegated"] --> F["Freeze revision, contract, context, permission snapshot, catalogue and client versions"]
    F --> PL["Plan: deterministic or reviewer"]
    PL --> EX["Executor attempt through supervisor; domain tools through broker"]
    EX -->|typed permission or gap request| ST["Settle process; capture work; persist request"]
    ST --> RQ["Owner request in manual mode or FL05 in autonomous mode"]
    RQ -->|grant or answer| NA["New frozen attempt at the next boundary"]
    NA --> EX
    RQ -->|deny with alternative| NA
    RQ -->|no progress or owner needed| SP["Stop with preserved work"]
    EX --> VA["Format, validate, capture tree and diff"]
    VA --> RV["Reviewer: ACCEPT, REVISE or BLOCKED"]
    RV -->|REVISE within attempt bound| NA
    RV -->|BLOCKED| SP
    RV -->|ACCEPT| AC{"Acceptance: exact content, revision, parity, required exports renderable"}
    AC -->|no| SP
    AC -->|yes| CI["Seal export and commit intents; Exporter renders owned targets; Git commits"]
    CI -->|success| DONE["COMMITTED; events; inbox item"]
    CI -->|export or commit failure| RC["Keep acceptance evidence; retry only the deterministic effect"]
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Admission | Manual: owner hash confirmation. Autonomous: child authorization within parent scope | Owner or Service | Stale source refused; idempotent re-admission |
| Attempt | Single writer lease; client capability contract; frozen permission snapshot | Supervisor/Executor | Quota/auth stop; expired lease → FL13 |
| Request | Attempt ended and settled before any ruling; request fingerprinted | Service | Equivalent request without new evidence reuses the ruling or stops for no progress |
| Grant application | Only at a new attempt; failure lineage preserved | Service | Revoked before use → refused at admission |
| Acceptance | Code content + accepted revision + generated-doc parity + D090 data parity | Service | Any change after review invalidates; the evidence stays |
| Export and commit | Clean baseline for owned targets; sealed intents; CAS per D271 | Exporter, Git | Partial export recoverable from the generation manifest; crash after commit reconciles it |

## FL05 — Judge request lifecycle

```mermaid
flowchart TD
    A["Typed request persisted with evidence references"] --> P{"Deterministic policy gate"}
    P -->|owner-only or not delegated| O["Escalate: owner item, WAITING_FOR_OWNER"]
    P -->|policy violation or uncertain effect| X["Stop: FAILED or RECOVERY_REQUIRED"]
    P -->|equivalent request without new evidence| E["Reuse earlier ruling or stop for no progress"]
    P -->|eligible for a delegated duty| B{"Judge reconsideration bound remaining?"}
    B -->|no| X
    B -->|yes| J["Fresh judge invocation: duty prompt, frozen inputs, read-only access, duty tools"]
    J -->|malformed, refusal or unavailable evidence| O
    J -->|provider, quota, auth or timeout| X
    J -->|abstain or escalate| O
    J -->|candidate ruling| V{"Service validates outcome against duty contract, tier, ceilings, compound authority"}
    V -->|invalid| O
    V -->|valid| R["Persist ruling; create grant or adopt proposal as owner_delegated; link decision if durable"]
    R --> C["Continue at the next boundary"]
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Policy gate | Owner-only list, delegation tiers, request equivalence | Service | Never invokes a model for owner-only items |
| Judge invocation | Duty-specific contract; accounting from the first call; no persistent session | Supervisor/Judge | No retry after a provider failure; output preserved |
| Validation | Grant within tier and duration; chosen option was supplied; gap proposal within delegated intent | Service | Invalid ruling escalates instead of being repaired by the harness |
| Persistence | Ruling, grant or adoption and event in one transaction | Service | Crash before commit: request remains pending; crash during invocation: FL13 marks the inference uncertain |

## FL06 — Permission grant states

```mermaid
stateDiagram-v2
    [*] --> REQUESTED
    REQUESTED --> POLICY_REFUSED: malformed, forged or cross-project target
    REQUESTED --> AWAITING_JUDGE: delegable dimension and duration
    REQUESTED --> AWAITING_OWNER: manual mode, owner-only or not delegable
    AWAITING_JUDGE --> GRANTED: valid judge grant
    AWAITING_JUDGE --> DENIED: judge denial with alternative or none
    AWAITING_JUDGE --> AWAITING_OWNER: escalation or invalid ruling
    AWAITING_OWNER --> GRANTED: owner grant by hash
    AWAITING_OWNER --> DENIED: owner denial
    GRANTED --> ACTIVE: applied in a new frozen attempt
    ACTIVE --> CONSUMED: per-operation scope used
    ACTIVE --> EXPIRED: time limit reached
    ACTIVE --> REVOKED: owner revocation
    GRANTED --> REVOKED: owner revocation before use
    ACTIVE --> SUPERSEDED: replaced by a narrower or broader owner grant
    POLICY_REFUSED --> [*]
    DENIED --> [*]
    CONSUMED --> [*]
    EXPIRED --> [*]
    REVOKED --> [*]
    SUPERSEDED --> [*]
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Request | Bound to project, role, dimension, exact targets, purpose, invocation | Service | Forged or cross-project targets refused |
| Grant | Compound authority never yields an owner-only capability; permanent only if delegated | Service | Invalid grants are not created |
| Activation | Effective snapshot frozen per attempt | Service | A grant never alters a running attempt |
| Revocation | Owner only; checked at every mediated command and admission | Owner → Service, Supervisor | Active writer stopped; effects settled; cascade behavior is G10 |

## FL07 — Phase check, remediation, closure and successor

```mermaid
flowchart TD
    A["No pending task in the phase"] --> CK["Check: deterministic gates, then reviewer over exact code and revision"]
    CK -->|READY| AU["Closure authorization: owner_confirmed or owner_delegated bound to the READY binding"]
    AU --> CL["Closure under lock: re-observe binding, seal tag and commit intents"]
    CL --> AR["Archive accepted domain snapshot and evidence; Exporter renders archive and successor views; one commit"]
    AR --> SU{"Authorized roadmap has a successor?"}
    SU -->|yes| OP["Successor ACTIVE without tasks; planning in FL03"]
    SU -->|no| FN["Final phase archived; no invented successor"]
    CK -->|NOT_READY: missing work| MW["Remediation proposal linked to unmet criteria"]
    CK -->|REVISE or documentary reconciliation| RC["Reconciliation proposal"]
    MW --> BD{"Remediation bound for the same cause remaining?"}
    RC --> BD
    BD -->|yes| AD["Adopt as delegated plan revision; new tasks keep failure lineage"]
    BD -->|no| X["LIMIT_REACHED"]
    CK -->|BLOCKED: planning ambiguity| J["FL05 blocked_check"]
    CK -->|auth, environment, integrity, writer uncertainty| Y["FAILED or RECOVERY_REQUIRED"]
    CL -->|stale binding| CK
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Check | Clean baseline, accepted revision, committed tasks, answered questions; reviewer accounted | Service, Supervisor/Reviewer | Early NOT_READY without a model; malformed output stops |
| Remediation | Tied to unmet criteria; cannot weaken criteria or adopt external hash drift | Service | Equivalent remediation counts against the bound |
| Closure authorization | Current READY binding; manual mode keeps the owner confirmation | Owner or Service | Stale READY returns to check |
| Closure effects | Tag never moved; intents sealed; archive and exports from sealed inputs | Git, Exporter | Crash → FL13; same tag object and commit reconciled |
| Successor | Only from the authorized roadmap revision | Service | No successor ends the loop toward completion |

## FL08 — Context assembly and knowledge receipts

```mermaid
sequenceDiagram
    autonumber
    participant S as Service
    participant DB as SQLite
    participant SV as Supervisor
    participant A as Agent CLI
    participant B as Tool broker
    S->>DB: select accepted revision and minimal relevant entities
    S->>DB: persist context snapshot digest and initial delivery receipts
    SV->>A: launch with frozen context, revision ID and scoped catalogue
    A->>B: query knowledge through a logical tool
    B->>S: validate caller, revision, authority and bounds
    S->>DB: read entities at the frozen revision
    S->>DB: persist query receipt with IDs, sections, exposure and digest
    S-->>B: bounded result with truncation or pagination markers
    B-->>A: result
    Note over S,DB: a newer accepted revision is visible only to a new invocation or attempt
```

| Step | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Selection | Accepted revisions only; never generated Markdown as authority | Service | Missing entity → explicit context-delivery failure event |
| Initial receipts | Persisted before launch with the attempt intent | Service | Crash before launch: no receipt claims delivery |
| Query | Frozen revision unless the boundary rule changes; bounded size | Service | Over-limit result truncated with a marker, never silently |
| Receipt | Delivery is availability, not comprehension; unobserved native reads stay unknown | Service | Lost receipt write fails the query rather than returning unrecorded content |

## FL09 — Portable tool discovery and invocation

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent CLI
    participant B as Tool broker
    participant S as Service
    participant DB as SQLite
    A->>B: search_tools with a query
    B->>S: scoped catalogue for bound role, project and operation
    S-->>B: bounded descriptors with IDs, versions and digests
    B-->>A: descriptors
    A->>B: describe_tool for one ID and version
    B-->>A: schema and digest
    A->>B: invoke_tool with ID, version, digest, arguments and idempotency key
    B->>S: caller from the transport session, never from arguments
    S->>S: validate schema digest, arguments, authority, revision and idempotency
    alt valid
        S->>DB: command outcome and events in one transaction
        S-->>B: typed result
    else invalid, stale or unauthorized
        S->>DB: refusal event
        S-->>B: typed refusal
    end
    B-->>A: result or refusal
```

| Step | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Search | Only scoped tools disclosed; results bounded | Service | No full-catalogue fallback when discovery is unavailable: admission blocks |
| Describe | Exact schema digest returned and traced | Service | Unknown or retired version refused |
| Invoke | Discovery is not a grant; generic envelope revalidated as the underlying command | Service | Duplicate idempotency key returns the first outcome; mismatched payload refused |
| Transport | Characterized per client (G04); no global configuration change | Supervisor | Unsupported client capability blocks admission with a diagnostic |

## FL10 — Generated export and explicit import

```mermaid
flowchart TD
    B["Boundary: task commit, closure, owner regeneration or manual adoption"] --> I["Seal export intent: revision, renderer, manifest digest, targets"]
    I --> C{"Owned targets safe: clean baseline, regular or absent, no links, no unowned collision"}
    C -->|no| R["Refuse before writing; keep intent and reason"]
    C -->|yes| W["Render accepted revision; replace owned targets; record per-target outcomes"]
    W --> M["Generation manifest; commit within the owning operation"]
    W -->|partial failure| P["Recoverable export state; retry deterministic rendering only"]
    U["Owner selects files in the UI"] --> PA["Parse supported format version"]
    PA --> SG["Stage proposals; validation and loss report"]
    SG --> PV["Canonical-change preview with hash"]
    PV -->|owner confirms| AD["Adopt new revision as owner_confirmed"]
    PV -->|rejected or stale| DR["Discard staging"]
    AD --> B
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Export intent | Inside a writer-locked operation; owned targets only | Exporter | Crash: same intent re-rendered from sealed inputs |
| Replacement | HEAD-relative expected state; no content comparison with the database | Exporter | Uncommitted edits refuse the operation; nothing discarded |
| Import parse | Supported version; untrusted input | Service | Unsupported content reported; never guessed |
| Import adoption | Exact preview hash; stable ID mapping; no execution, approval, grant or usage history created | Owner → Service | Stale preview refused; idempotent confirmation |

## FL11 — Project intake paths

```mermaid
flowchart TD
    BR["New-project brief"] --> DEF["Definition conversation; database drafts"]
    HEAD["Existing committed code"] --> INV["Static inventory of HEAD; read-only reverse engineering"]
    INV --> RD["Database drafts with known, inferred and unknown provenance; questions"]
    FILES["Exported or edited documents"] --> IMP["Explicit import FL10"]
    OLD["Installed 0.1.x managed project"] --> MIG["Previewed conversion with verified snapshot T020"]
    DEF --> REV["Adoption preview with hash"]
    RD --> REV
    REV -->|owner confirms| ACC["Accepted revision; originals preserved; generated export and commit"]
    ACC --> PREP["Profile, preparation and activation gates unchanged"]
    IMP --> ACC2["New revision for an existing project"]
    MIG --> ACC3["Mapped revisions; legacy evidence untouched"]
```

| Path | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Definition | Drafts never authoritative before adoption | Service, Reviewer | Stale proposal refused |
| Onboarding | HEAD binding, private export, no project code executed | Service, Reviewer | Changed HEAD invalidates the preview |
| Import | Explicit, staged, no fabricated history | Owner → Service | Loss report blocks unless accepted |
| Migration | Verified pre-migration snapshot; stable identity mapping | Service (T020) | Unsupported continuations quarantined; originals retained |

## FL12 — Durable wait, inbox, answer and resume

```mermaid
flowchart TD
    E["Committed event: question, escalation, stop, task completed, phase awaiting closure"] --> D["Derive inbox item with dedupe key"]
    D --> N["Optional OS notification without sensitive content"]
    D --> U["Owner reads item: read state only"]
    U --> A{"Owner action"}
    A -->|answer or decide| G{"Fresh guards: current request version, revision, READY, authority, idempotency"}
    G -->|stale| S["Refuse; show current state"]
    G -->|valid| C["Ordinary guarded command records owner_confirmed outcome"]
    C --> R["Item resolved; explicit resume where a run waits"]
    A -->|dismiss| K["Read; still unresolved if the blocker remains"]
```

| Transition | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Derivation | Only from committed events; deduplicated across restarts | Service | Rebuilt from events after a crash |
| Notification | Optional, secondary, non-sensitive | Service | Delivery failure never blocks the inbox |
| Action | Same command and guards as the normal UI; never an evergreen approval | Owner → Service | Stale or duplicate answer cannot authorize different work |
| Archive | Query-only bundles expose items without actions | — | Mutations return 409 |

## FL13 — Crash recovery across graph and domain operations

```mermaid
flowchart TD
    S["Service restart or lost lease"] --> O["List operations not terminal"]
    O --> K{"Effect kind"}
    K -->|model invocation| P{"Writer process provably settled?"}
    P -->|no| RR["RECOVERY_REQUIRED; owner confirms stopped writer"]
    P -->|yes| UI["Invocation result recorded or uncertain; never reissued automatically"]
    RR --> UI
    K -->|Git commit or tag| GI["Reconcile sealed intent against the repository"]
    K -->|export| EX["Reconcile generation manifest; re-render from sealed inputs"]
    K -->|domain command| DC["Committed or absent by transaction; no partial state"]
    UI --> GR["Graph continuation re-enters the node with the same operation ID"]
    GI --> GR
    EX --> GR
    DC --> GR
    GR --> V{"Graph definition version compatible?"}
    V -->|no| Q["Quarantine continuation; owner decides"]
    V -->|yes| CONT["Node observes existing outcome before considering new work"]
```

| Step | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Classification | Operation identity, intent and evidence, not RUNNING status alone | Service | Unknown kind → RECOVERY_REQUIRED |
| Inference | Expired lease never proves a stop; uncertain inference kept, not repeated | Owner → Service | New inference only by a new explicit decision or bound-consuming attempt |
| Git/export | Sealed intents; tag never moved | Git, Exporter | Same commit/tag object reconciled |
| Graph re-entry | Same operation ID; consistency contract of G02 | Graph | Version mismatch quarantined (G03) |

## FL14 — Observation projection

```mermaid
flowchart LR
    EV["Committed domain events and operation records"] --> PR["Versioned bounded projections"]
    ACC["Invocation accounting"] --> PR
    RCPT["Knowledge receipts"] --> PR
    PR --> GV["Task-instance graph"]
    PR --> TV["Run and trace views"]
    PR --> IB["Global inbox"]
    PR --> AV["Query-only archive views"]
```

| Step | Guard | Effect owner | Failure / recovery |
|---|---|---|---|
| Projection | Derived, never authority; declared counter meanings and coverage | Service | Rebuildable from records; cursor gaps recovered by snapshot (D029) |
| Views | Read-only; no execution through visual edges | — | Missing telemetry shown as unknown |

## Verification

Mermaid validation and documentation checks are recorded in the
[T001 evidence](P002-T001-contracts.md#evidence).
