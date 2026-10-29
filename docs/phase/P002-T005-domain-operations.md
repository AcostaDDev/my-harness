# P002-T005 — Typed domain operations and capability policy

Status: **completed (2026-10-29); committed, merged into `develop` and pushed at the owner's authorization.** The owner accepted this contract with Q1 option (a), the
correspondence with the 0.1.9 ceilings and E21, and recorded it as
[D286](../DECISIONS.md#d286--typed-domain-operation-service-capability-policy-and-command-outcome-record); Q3 was
answered by implementing on `feat/p002-t005-domain-operations` from `develop` with this refinement carried along.
Sections 1–14 are the accepted contract; [§15](#15-delivery-status) records the implementation, its evidence and what
remains pending.

Owner/delivery: P002-T005, refinement on `docs/p002-t005-domain-operations` and implementation on
`feat/p002-t005-domain-operations`, both from local `develop` at `95ac6df` (T004 merge, equal to the local
`origin/develop` ref; no fetch). Proposed route (D242/D253): topic branch → `develop` →
**0.2.0** phase release through protected `main` → verified distribution/publication → local installation. Each stage
needs its own authorization and is recorded separately; T005 has no individual release. Binding design:
[D269](../DECISIONS.md#d269--langgraph-orchestration-over-sqlite-domain-authority)–[D275](../DECISIONS.md#d275--client-neutral-tool-discovery-and-invocation-contract),
[D280](../DECISIONS.md#d280--langgraph-1218-dependency-set-placement-and-runtime-hygiene)–[D285](../DECISIONS.md#d285--canonical-database-instructions-and-generated-instruction-files),
[T001 contracts](P002-T001-contracts.md) §§3–4, 7–9, flows [FL04](P002-T001-flows.md#fl04--task-operation-in-both-modes),
[FL08](P002-T001-flows.md#fl08--context-assembly-and-knowledge-receipts),
[FL09](P002-T001-flows.md#fl09--portable-tool-discovery-and-invocation),
[FL13](P002-T001-flows.md#fl13--crash-recovery-across-graph-and-domain-operations), threats TM01–TM05 and TM18
([threat model](P002-T001-threat-model.md#threats-controls-and-owning-tasks)), basis B02, B04, B06–B09, B13–B15.
No formal gate is open for T005 (NEXT_STEPS **Gates:** —).

## 1. Problem and scope

UI/API, model-selected tools and graph nodes must not each implement their own authorization or database mutation.
T005 delivers one typed command/query service: every entry point names a catalogued logical operation, receives a
caller bound by trusted infrastructure, and passes the same validation of schema, identity, project membership,
authority, revision and idempotency before the same handler mutates SQLite, in one transaction with its outcome record.

**In scope.** The operations of [§3](#3-operation-surface) over the T004 knowledge storage; the versioned logical
catalogue and its schema validator; the caller model and binders, including the frozen-revision view of agents and
archive reads from persisted data ([§4](#4-trusted-caller-context)); the capability policy: per-operation
requirements evaluated against frozen grants and current ceilings through `PermissionProvider`, and the
sensitive-change classifier with its owner-only exclusion ([§5](#5-capability-and-authorization-policy)); idempotency and CAS
([§6](#6-revisions-idempotency-and-concurrency)); the shared unit of work and command outcome record
([§7](#7-transaction-and-audit)); the owner API binding, the deterministic graph binding and the broker-facing
dispatcher ([§8](#8-shared-entry-points)); the provider interfaces later tasks fill in ([§11](#11-boundaries-with-later-tasks)).

**Out of scope.** Operation/invocation/event journal and traces (T006); context assembly and knowledge receipts (T007);
MCP transport, search ranking and CLI adaptation (T008); judge duties and rulings (T009); grant storage, request and
ruling lifecycle, revocation actions, expiry/permanence and G10 target normalization (T010); creation/onboarding drafts (T011); UI editing and rebase (T012); export, import and wrappers (T013);
task, phase and autonomous flows (T014–T016). Existing 0.1.9 endpoints, the `permission_requests` ledger and
the job queue are unchanged.

## 2. Baseline observed in the code

| Fact (at `95ac6df`) | Consequence for T005 |
|---|---|
| `storage/knowledge.py`: every method opens its own `Session`/transaction; `adopt` accepts any `origin` in `ORIGINS` and any non-empty `actor` dict from its caller | Outcome and mutation cannot share a transaction today; authority is not checked anywhere. The service must become the only product caller and pass a shared session |
| Drafts (`knowledge_revisions` with `DRAFT`) record no author; members/links are freely editable while `DRAFT` | Self-adoption and draft ownership cannot be enforced without recording the opener |
| No idempotency key in knowledge tables; existing patterns key `managed_jobs`, `product_preference_events` and conversations by `(idempotency_key, request_sha256)` with replay or conflict | T005 needs its own durable key/result record |
| `core/engine/knowledge.change_summary` marks requirements, criteria and instructions sections as `sensitive`; structure is one boolean; it is part of `revision_sha256` (D284) | The summary cannot be extended without changing an accepted hash contract; phases, decisions, relationships and order need a separate classifier |
| `core/engine/permissions.KINDS` already names the five dimensions; `storage/permissions.actor()` gives the service OS identity, explicitly not browser authentication | Reuse both; owner identity is "holder of a valid local session" on one operator account |
| `core/engine/permissions.allowed` requires an exact target in every layer (`global`, `project`, `contract`, `provider`) of the project's `permission_authority`, which the operator configures as exactly those four layers and which is frozen into each job's `versions`; a null authority allows nothing; `files` targets also pass the task and profile path rules | All four layers and the file rules are kept, with the same exact-target, every-layer semantics; no pattern matching is introduced ([§5.2](#52-per-operation-capabilities-and-current-ceilings)) |
| A marked restored copy runs with `query_only`, a session and no project composition, checkout or supervisor ([flow](../flows/backup-consultation.md)); `knowledge_projects.root` is persisted | Archive reads cannot resolve projects through `ManagedRuntime.projects`; they must address the persisted knowledge project |
| `orchestration/operations.py`: `operation_key(config, name, references)` and `OperationPort`; production journal is T006 | The graph binding derives idempotency keys from the same deterministic key |
| `api/security.local_request` (Host, Origin, `Sec-Fetch-Site`, `X-My-Harness: 1`), session middleware, `restored_read_only` middleware (409 on non-GET in marked archives) | New routes inherit them by being mounted under `/api/managed`; the service also refuses writes on `PRAGMA query_only` |
| No JSON Schema validator in dependencies (`pydantic==2.14.0` only, used by the API) | Catalogue schemas need a standard-library subset validator in the core |

## 3. Operation surface

T005 catalogues only operations that have a real handler over existing storage. Ten entries, catalogue
`domain-catalogue-1`, each at version 1. **Kinds** follow D275: query, propose, adopt, effect; T005 has no effect entry.
Each entry also declares its capability requirements ([§5.2](#52-per-operation-capabilities-and-current-ceilings)).

| Operation | Kind | Principals | Input (all objects closed, `additionalProperties: false`) | Result | Main refusals |
|---|---|---|---|---|---|
| `knowledge.projects` | query | owner | `{offset ≥0, limit 1–100}` | Persisted knowledge projects: `{id, root, head: {number, revision_sha256} \| null}`, `total` | — |
| `knowledge.head` | query | owner, harness, agent (reviewer, executor) | `{}` | Owner/harness: the current accepted head, null or `{id, number, revision_sha256, knowledge_sha256, origin, accepted_at, counts}`. Agent: the same fields for its **frozen** revision, never a later one ([§4](#4-trusted-caller-context)) | `not_found` |
| `knowledge.list` | query | same | `{revision?: int ≥1, kind?, document?, offset ≥0, limit 1–100}` | Metadata only: `{item_id, kind, document, code, version, content_sha256, title, status}`, `total`, `delivery` | `revision_unknown`, `revision_outside_context` |
| `knowledge.get` | query | same | `{revision?: int, item_id}` | One member with content, provenance, source, incoming/outgoing links at that revision, `delivery` | `not_found`, `revision_outside_context` |
| `knowledge.draft.get` | query | owner (any draft of the project); harness/agent (own drafts) | `{draft_id}` | `{draft_id, base_revision_id, draft_sha256, opener, members, links}` | `not_found` |
| `knowledge.draft.open` | propose | owner, harness, agent (reviewer) | `{expected_revision_id: string \| null}` | `{knowledge_project_id, draft_id, base_revision_id, draft_sha256}` | Owner/harness: `stale_revision`. Agent: `revision_outside_context` unless it names its frozen revision |
| `knowledge.draft.apply` | propose | the draft's opener only | `{draft_id, expected_draft_sha256, changes: 1–200 of put/remove/link/unlink}` | `{draft_sha256, item_ids}` | `draft_changed`, `draft_not_owned`, `knowledge_invalid`, `provenance_not_allowed` |
| `knowledge.draft.discard` | propose | opener; owner for any draft | `{draft_id}` | `{draft_id, status: DISCARDED}` | `draft_not_open` |
| `knowledge.adoption.preview` | query | owner | `{draft_id}` | `{base_revision_id, base_revision_sha256, draft_sha256, changes, classification, reason_required, preview_sha256}` | `knowledge_invalid`, `empty_adoption` |
| `knowledge.adopt` | adopt | owner (`owner_confirmed`); harness only through providers that do not exist yet | `{draft_id, expected_revision_id, preview_sha256, reason?: ≤2000}` | `{revision_id, number, revision_sha256, knowledge_sha256, origin, changes}` | `preview_stale`, `stale_revision`, `reason_required`, `owner_required`, `delegation_unavailable` |

Every mutating result adds `{command_id, replayed}`. `put` is `{op, kind, code, document?, content, provenance,
source?, root_position?}`; `remove` is `{op, item_id}`; `link`/`unlink` are `{op, kind, source_item_id,
target_item_id, position?, qualifier?}`. Content is validated by `core/engine/knowledge.validate_content` during
`apply`; whole-revision rules (`validate_revision`) run at preview and adoption, since a draft may be inconsistent
while being edited.

**Why this set.** It is the smallest set that lets one principal create a proposal, another inspect it, and the owner
adopt it by exact preview, which is what the propose/adopt separation, self-adoption and sensitive-change controls
need to be tested on real code. Reads exist so agents (later) and the owner never need direct table access;
`knowledge.projects` lets the owner address knowledge from persisted data, including in restored archives, without
the runtime's project map. Item
history, draft listing, rebase/fork and search are left to T007/T012.

**Reserved, not catalogued.** No entry, stub or disabled placeholder is added for: broker `search_tools`/
`describe_tool`/`invoke_tool` transport (T008); permission requests and rulings, judge duties (T009/T010); operation and
event queries (T006); context or receipt queries (T007); export, import, commit, phase and inbox commands (T013–T017);
creation/onboarding staging (T011). T005 defines the interfaces they plug into ([§11](#11-boundaries-with-later-tasks)).

## 4. Trusted caller context

A `Caller` is a frozen value built only by binders inside the trusted computing base; no operation schema can carry
any of its fields, and the catalogue linter refuses schemas that name `project`, `project_id`, `role`, `caller`,
`principal`, `invocation_id`, `attempt_id`, `origin`, `actor` or `authorization_id`.

| Field | Owner (API) | Harness (graph or internal) | Agent (broker, T008) |
|---|---|---|---|
| `principal`, `channel` | `owner`, `api` | `harness`, `graph` or `internal` | `agent`, `broker` |
| Project | Reads: path `knowledge_project_id` → persisted `knowledge_projects` row only. Mutations: path registered `project_id` → `ManagedRuntime.projects` → canonical root → knowledge project (created by the first `draft.open`) | The thread's or service call's registered project | The invocation's frozen project (T006 record) |
| Role | — | — | Frozen in the invocation (reviewer, executor, judge) |
| Invocation/attempt | — | Graph thread id and deterministic operation key | Invocation and attempt ids (T006) |
| Revision context | Any accepted revision | Head, unless the call names one | The frozen accepted revision of the invocation (D270); the only revision it can read or base a draft on |
| Allowed operations | Catalogue principals | Catalogue principals | Catalogue principals ∩ the invocation's frozen tool policy (entry id, version, digest) |
| Authority | Session holder on the single operator account (SPECIFICATION §5 rule 10) | Only what a provider below returns | Only what a provider below returns |
| Actor recorded | `{principal: owner, channel: api, uid, user}` from `storage/permissions.actor()`; never the session token | `{principal: harness, channel, thread_id?, operation_key?}` | `{principal: agent, role, invocation_id, attempt_id}` |

**Project membership.** The service resolves the knowledge project once per call and checks inside the transaction
that every identifier belongs to it: a draft's `project_id`, an item through draft membership (and the composite
foreign keys of 0030), a revision number within that project. An identifier from another project and a missing one
return the same `not_found` with the same body, so existence elsewhere is not disclosed (TM04). On mutation routes the
draft's knowledge project root must equal the registered project's canonical root.

**Frozen revision for agents.** For an agent caller the frozen revision replaces the head everywhere: `knowledge.head`
returns that revision's identity, number, hashes and counts; `list` and `get` without `revision` read it; `draft.open`
bases the draft on it. Naming any other number — a later accepted one or a nonexistent one — returns the same
`revision_outside_context` with the same body, and an item that exists only in a later revision is `not_found`. No
result, refusal or diagnostic for an agent carries a later revision's id, number, hash, count or the fact that one
exists; whether a later revision becomes visible is T007's context boundary. An agent draft on a superseded base is
accepted as a proposal; only the owner's adoption, which compares the base with the current head, finds it stale.

**Restored archives.** Reads resolve the project only from `knowledge_projects` by id and read revisions through T004's
verified retrieval. They use neither `ManagedRuntime.projects`, the registry, the checkout nor the supervisor, so they
work in a marked query-only copy whose original root no longer exists. The owner is the archive service's session
holder. Mutations are refused by the existing middleware (409 `restored_read_only`) and, if the service is called
directly, by its own `query_only` check before any write; nothing is recorded there. Archived drafts are readable data
and can never be adopted. The same reads work in ordinary mode for a knowledge project whose root is no longer
registered; its mutations are refused `project_unregistered`.

**Missing infrastructure fails closed.** Agent callers need a `CallerResolver` that maps a transport-bound
credential to a persisted invocation and re-verifies it inside the transaction (T006/T008). The product composition
installs `UnavailableResolver`, so every agent call is refused `caller_unavailable`. Delegated adoption needs an
`AuthorizationProvider` (T016) and grants a `PermissionProvider` (T010); the product composition installs providers
that refuse (`delegation_unavailable`). Agent queries additionally need a `DeliverySink` (T007) and are refused without
one. Synthetic implementations live only under `tests/`; a test asserts the product composition contains none of them.

**Model-derived content.** The harness principal never wraps a model output as its own proposal: content produced
by an invocation is proposed under that invocation's agent principal (T008/T009 enforce it through the resolver).
`harness` drafts are for deterministic staging such as D285's instructions staging (used later by T011/T013).

## 5. Capability and authorization policy

### 5.1 Evaluation order

Every call runs the same pipeline in `execute(caller, operation_ref, arguments, key)`; the first failure returns a
typed refusal:

1. Catalogue: `(id, version)` exists and is not retired; the presented `schema_sha256` equals the entry's; no fallback
   to another version or to a broader entry (TM02).
2. Arguments: validated against the entry's input schema (closed objects, bounded strings and arrays) (TM01, TM04).
3. Caller: principal and role listed for the entry; for agents, the entry is in the frozen tool policy (TM03).
4. Inside the command's transaction: query-only refusal, re-verification of the caller through its resolver, project
   membership of every identifier, idempotency lookup ([§6](#6-revisions-idempotency-and-concurrency)). Mutations,
   and agent queries (whose T007 receipts are writes), take the write lock first; owner and harness queries use one
   read transaction.
5. Capabilities: the entry's requirements, completed with the targets derived from the arguments or the
   classification, are evaluated for this principal with the state that `PermissionProvider` reads in the same
   session ([§5.2](#52-per-operation-capabilities-and-current-ceilings)); adoption also needs the authority of
   [§5.3](#53-propose-adopt-and-self-adoption); effect kinds have no entry in T005.
6. Preconditions (expected revision, draft hash, preview hash, opener), handler, outcome record with the capability
   basis, commit.

Role and tool policy (step 3) say which operations a principal may attempt; step 5 says whether this call, with these
targets, is authorized now. Neither substitutes for the other. Prompts, argument text and model output never enter
steps 1–5 as policy (TM01). The filesystem is not part of this policy: reading the checkout stays the adapters'
read-only tool policy, and no catalogue entry reads or writes files, runs code, or accepts SQL (D275, INV-11).

### 5.2 Per-operation capabilities and current ceilings

Each entry declares its requirements, covered by its schema digest. They use the five dimensions of
`core/engine/permissions.KINDS` and exact string targets (no patterns; target normalization is G10, T010):

| Entries | Requirements |
|---|---|
| Every entry | `tools`: `domain:<operation id>@<version>` |
| `knowledge.draft.apply` | Also `product`: `knowledge.propose:<group>` for every group a change touches (`requirement`, `criterion`, `phase`, `task`, `decision`, `section:<document>`); a link counts for the groups of both endpoints |
| `knowledge.adopt` | Also `product`: `knowledge.adopt:<class>` for every class in the classification ([§5.4](#54-sensitivity-and-owner-only-exclusion-requires-owner-confirmation-q1)) |

The evaluator is one pure function in `core/engine/domain_policy.py`, the same for every channel:

- **Owner.** Satisfied by owner authority (the session holder); grants and ceilings bound delegated and agent
  authority, not the owner's. Basis recorded: `owner`.
- **Harness.** Query and propose entries are satisfied with basis `harness_internal` on the `graph` and `internal`
  channels only. Adoption requirements are evaluated with the three agent rules below, the parent authorization's
  tiers supplied by `AuthorizationProvider` (T016) taking the place of the snapshot; without that provider they fail.
- **Agent.** Each requirement must be (1) outside the owner-only exclusion set (`knowledge.adopt:owner_only` and the
  D273 list expressed as targets); (2) matched exactly by one entry of the attempt's frozen permission snapshot that
  the provider reports neither revoked nor expired; (3) contained in **every** ceiling layer of the fixed set below,
  with the every-layer rule of `permissions.allowed`. The layer set is fixed by the evaluator, not by the provider: a
  missing layer, or a project without `permission_authority`, is empty and denies, as in 0.1.9. A grant never satisfies
  another dimension or target, and no combination of grants satisfies an excluded target (TM06's control, used here).

**Correspondence with the 0.1.9 restrictions.** Every restriction that applies today is kept; T005 adds `role` and
evaluates nothing more permissively than 0.1.9 does.

| Restriction | Source today | Domain-capability use | Evaluated |
|---|---|---|---|
| `global`, `project`, `contract`, `provider` layers of `permission_authority` | Operator project configuration, validated as exactly these four layers (`services/managed_runtime.validate_projects`), frozen into the job's `versions` at admission (`api/managed.frozen_versions`) | Kept unchanged and all four required. The effective layer is the **intersection** of the copy frozen with the invocation (T006 record) and the project's current value, so a narrowing applies at the next command and a widening only at a new attempt (D274) | T005 evaluator, step 5, with both copies read by `PermissionProvider` |
| `role` (new) | Delegation ceiling per role, T010 | Required fifth layer; empty until T010 provides it, so agent calls deny | T005 evaluator, step 5 |
| File rules of `permissions.allowed`: task `allowed_paths`/`forbidden_paths`, executor-protected paths, profile sensitive paths and allowlist | Frozen task contract and profile | Not reimplemented. T005 entries declare no `files` requirement; a later entry that does must call the same `permissions.allowed` logic | Unchanged: 0.1.9 grant decision and executor intent (`storage/permissions.py`) |
| Client and provider capability contract MC1–MC7, adapter tool policy and the invocation's frozen tool policy | D281, frozen at admission | An entry outside the frozen tool policy is refused before any grant is considered | Admission (T008); T005 step 3 |
| 0.1.9 `permission_requests` grants (`files`, `tools`, `network` for executor attempts; `product`/`acceptance` never unlock an executor or commit) | `storage/permissions.authorize` | Never read as domain grants; how T010 relates the two ledgers is T010's | Unchanged |

`PermissionProvider` is the only source of that state:

```python
class PermissionProvider(Protocol):
    def state(self, session: Session, caller: Caller) -> PermissionState: ...

@dataclass(frozen=True)
class PermissionState:
    snapshot_sha256: str                              # frozen at the attempt (D274: grants apply at a new attempt)
    grants: tuple[tuple[str, str, str], ...]          # (grant_id, dimension, target) from that snapshot
    unavailable: frozenset[str]                       # grant ids revoked or expired now
    frozen_authority: Mapping[str, Mapping[str, frozenset[str]]]   # permission_authority frozen with the invocation
    current_authority: Mapping[str, Mapping[str, frozenset[str]]]  # the project's current permission_authority
    role_ceiling: Mapping[str, frozenset[str]]        # T010: dimension -> targets for the caller's role
    ceilings_sha256: str                              # digest of the three ceiling inputs
    policy_version: str
```

- **Transactional use.** `state` is called once per call inside the command's session, after the write lock when the
  call takes it, and may only read. The decision and its basis (snapshot digest, grant ids used, ceilings digest,
  policy version) are written in the outcome row of that transaction. A provider error or an incomplete state refuses
  the call and rolls everything back.
- **Current state.** The snapshot and the frozen authority stay as admitted; the current authority, the role ceiling
  and revocation are read now, so a narrower ceiling or a revocation committed before the call takes the lock refuses
  it, and one committed afterwards applies from the next call. Owner and harness queries see the state of their read
  transaction's start.
- **Refusals.** `capability_unavailable` (no provider or no snapshot), `capability_denied` (no exact unrevoked grant),
  `ceiling_excluded` (a required layer, frozen or current, lacks the target; the diagnostic names the layer),
  `owner_only_excluded`; an entry outside the frozen tool policy stays `caller_not_allowed` (step 3).
- **Ownership.** T005 implements the evaluator, the protocol, `UnavailablePermissions` (the product default, which
  refuses every agent call) and tests with a test-only provider backed by a table that each test creates in its
  temporary database and reads through the command session. T010 implements the storage-backed provider, grant
  storage, the role ceiling, requests, rulings, revocation actions, expiry, permanence and target normalization; T006
  records the frozen authority with the invocation.

### 5.3 Propose, adopt and self-adoption

- **Agents never adopt.** No agent principal is listed for `knowledge.adopt` or `knowledge.adoption.preview`, and
  the origin is derived from the caller, never from arguments, so model output cannot become an approval (INV-12).
- **Owner adoption.** `owner_confirmed` requires the exact `preview_sha256` of the current draft and base, the expected
  head, an `Idempotency-Key`, and a reason when the classification contains a sensitive entry. The owner may adopt a
  draft opened by any principal of the project; the outcome records the adopting owner and the draft's opener
  separately, so an agent's proposal is never shown as owner-authored.
- **Draft ownership.** `apply` is allowed only to the opening principal scope (the owner, the same harness thread, or the
  same agent invocation); the owner can discard but not edit another principal's draft. Forking a draft for owner edits
  is T012.
- **Delegated adoption (reserved).** `owner_delegated` will need, at adoption time: an active parent authorization
  from T016 with its revision, no owner-only entry in the classification, every class and sensitive entry named by the
  authorization's tiers, a ruling from a different invocation than the draft's author where a ruling is required
  (T009), and the §5.2 evaluation with current ceilings and revocation (T010). Until those providers exist it is
  refused, so no delegated adoption is possible in T005.
- **Deterministic adoption.** `harness_deterministic` adoption needs a named deterministic rule covered by an existing
  authorization (T001 §4). T005 defines the rule registry empty, so every such adoption is refused.

### 5.4 Sensitivity and owner-only exclusion (requires owner confirmation, Q1)

A pure function compares the draft's manifest with its base and gives every change, including relationship and order
changes, two independent properties. It does not alter the D284 summary or hashes; both properties are part of the
preview hash and of the outcome record.

- **Sensitive.** The change is listed individually in the preview and the outcome, owner adoption requires a reason,
  and a future delegated adoption may include it only if the authorization names its class explicitly. The sensitive
  set is a superset of `change_summary.sensitive` (requirements, criteria, instructions), checked by a test.
- **Owner-only exclusion.** The change can be adopted only as `owner_confirmed`: its class maps to the excluded target
  `knowledge.adopt:owner_only`, which no grant, delegation tier or ruling can satisfy. Every owner-only change is
  sensitive; a sensitive change is not necessarily owner-only.

| Changes (added, changed, removed, linked, unlinked or reordered) | Class | Sensitive |
|---|---|---|
| Requirements | `owner_only` | yes |
| Criteria of a requirement, a phase or a task already in the base, including re-owning or reordering them | `owner_only` | yes |
| Phases: the set (added, removed, withdrawn), objective, title or tag, and their `addresses` links | `owner_only` | yes |
| `instructions` sections: content, target, parent, position or root order | `owner_only` | yes |
| A `supersedes` link on an accepted decision | `owner_only` | yes |
| Criteria created with a task added in the same draft | `planning` | yes |
| New decisions that supersede nothing | `product` | yes |
| Sections of `specification`, `architecture`, `data_model` and `flows`, their tree and root order | `product` | no |
| Tasks inside existing phases (added, changed, withdrawn), their `part_of` link and position, `depends_on`, task `addresses` links | `planning` | no |

The owner-only rows cover D273's list (roadmap objectives, phase set, requirement meaning, weakening criteria,
instructions/policy). They are conservative because "weakening" or "change of meaning" cannot be decided mechanically.
Changes to objectives or to the authorized phase set stay owner-only under every option of Q1 (D273; D276 makes them
owner amendments). Manual mode is unaffected because the owner adopts everything; the properties matter for the
preview, the reason, the capability targets of §5.2 and later delegation (T016), which may only adopt `planning` and
`product` changes within its declared tiers.

### 5.5 Provenance by principal

Agent principals may write only `inferred` or `unknown` provenance with an `observation` source; `known` and legacy
sources are reserved to owner and deterministic harness staging, where the source can be verified. This keeps an
agent from asserting that content is known from a document (D284 forbids invented provenance).

## 6. Revisions, idempotency and concurrency

- **Key scope.** `(knowledge project, principal scope, Idempotency-Key)`, where the principal scope is `owner`,
  `harness:<thread or service>` or `invocation:<id>`. One principal cannot replay or observe another's result by
  guessing its key. Keys are 1–200 characters, as in the existing API.
- **Payload identity.** `request_sha256` = canonical JSON digest (`freeze`) of operation id, version, schema digest,
  normalized arguments and derived origin. Caller fields are covered by the scope.
- **Identical repetition.** Same scope, key and `request_sha256`: the stored result is returned with `replayed: true`.
  No precondition is re-evaluated and nothing is written; this returns evidence of a persisted outcome, it does not
  execute the operation again.
- **Reuse with other content.** Same key, different `request_sha256`: `idempotency_conflict`, nothing written.
- **Refusals do not reserve keys.** A refused call is recorded for audit but does not consume its key; retrying the
  same request re-evaluates it. A stale request stays stale because the head never goes back.
- **Stale state.** For owner and harness callers `expected_revision_id` must equal the current accepted head; for
  agents it must equal their frozen revision and is never compared with the head in anything they receive (§4).
  `expected_draft_sha256` must equal the digest of the draft's current manifest, computed like T004's
  `knowledge_sha256`; `preview_sha256` must equal the preview recomputed in the adoption transaction. Any change after
  the preview (draft edit, head moved) returns `preview_stale`. There is no rebase (T012).
- **Concurrency.** Every mutation starts with a no-op write so SQLite's write lock is held before any read, as in
  `ManagedRepository._write` and T004's adoption; concurrent calls serialize, and the second sees the first's outcome
  (replay, `draft_changed` or `stale_revision`). T004's partial unique indexes and numbering trigger stay the database
  guarantee for one accepted successor per base. A partial unique index on accepted outcomes guarantees one result per
  key.
- **Revocation.** Capabilities are evaluated at the command, inside its transaction, with the current ceilings and
  revocation state of §5.2. An outcome committed before a revocation remains valid evidence; a replay after revocation
  returns that evidence and performs nothing new; a new key after revocation is refused (`capability_denied` or
  `ceiling_excluded`). Owner logout ends the session, so the API refuses before the service.

## 7. Transaction and audit

- **Unit of work.** `DomainOperations.execute` opens one SQLAlchemy session and transaction per call. The T004
  repository gains session-bound variants (`KnowledgeRepository.bound(session)`) used by the service; the existing
  self-transacting methods stay for compatibility and tests. Inside the transaction: lock, re-verification,
  idempotency lookup, handler, adoption sealing with its verification read in the same session, outcome row, commit.
  Any exception rolls back the mutation and the outcome together.
- **Outcome record.** One insert-only row per accepted mutation in a new `domain_commands` table (proposed in
  [§9](#9-technical-impact), Q2): operation id/version/schema digest, catalogue digest, principal, channel, caller
  references and actor, origin, scope, key, `request_sha256`, capability basis (§5.2), result (bounded identifiers
  and hashes, ≤16 KiB), draft/revision references and time. The opener of each draft is the accepted `knowledge.draft.open` row; a draft
  without one is refused (`draft_unattributed`).
- **Refusals.** Recorded in their own short transaction after the rollback, with code, operation, caller and
  `request_sha256`, never with a result. If that write fails, the call returns an operational error rather than a
  typed refusal; it never returns success. In a query-only database nothing is recorded.
- **Queries** write nothing in T005 and need no registered project, checkout or runtime project map, so they also
  run on a restored query-only copy (§4). Agent queries return a `delivery` descriptor (entity ids, revision, digests,
  exposure, pagination/truncation) that T007's `DeliverySink` persists as receipts in the same transaction; without the
  sink they are refused (FL08: unrecorded content is not returned).
- **T006 boundary.** T005 provides an `AuditSink` protocol called in the same session; T006 adds operation links and
  ordered events through it. T005 does not create events, traces or invocation records.
- **No wider atomicity.** Nothing is atomic with LangGraph checkpoints or external effects. A domain command is
  committed or absent (FL13); a graph replay finds it through its key. Exports, Git and CLI effects keep sealed intents
  in their own tasks.

## 8. Shared entry points

All channels call `execute` with a catalogue reference; there is no second implementation of any check.

**API (owner).** A new `api/knowledge.py` router under `/api/managed`, so it inherits `local_request`, the session
middleware and `restored_read_only`. Each route is typed (no generic `invoke` endpoint for the browser), fills the
operation reference from the catalogue constant and binds the owner caller. Reads are `GET` under
`/api/managed/knowledge/projects/…`, addressed by the persisted knowledge project id and resolved without
`ManagedRuntime.projects` or the checkout, so they work on restored archives (§4). Mutations and the adoption preview
stay under the registered project, require `Idempotency-Key` (mutations) and are refused in query-only archives;
previews are `POST` like existing previews.

| Route (`…` = `/api/managed`) | Operation | Project resolution |
|---|---|---|
| `GET …/knowledge/projects` | `knowledge.projects` | Persisted |
| `GET …/knowledge/projects/{knowledge_project_id}` | `knowledge.head` | Persisted |
| `GET …/knowledge/projects/{knowledge_project_id}/revisions/{number}/items` | `knowledge.list` | Persisted |
| `GET …/knowledge/projects/{knowledge_project_id}/revisions/{number}/items/{item_id}` | `knowledge.get` | Persisted |
| `GET …/knowledge/projects/{knowledge_project_id}/drafts/{draft_id}` | `knowledge.draft.get` | Persisted |
| `POST …/projects/{project_id}/knowledge/drafts` | `knowledge.draft.open` | Registered |
| `POST …/projects/{project_id}/knowledge/drafts/{draft_id}/changes` | `knowledge.draft.apply` | Registered |
| `POST …/projects/{project_id}/knowledge/drafts/{draft_id}/discard` | `knowledge.draft.discard` | Registered |
| `POST …/projects/{project_id}/knowledge/drafts/{draft_id}/adoption/preview` | `knowledge.adoption.preview` | Registered |
| `POST …/projects/{project_id}/knowledge/drafts/{draft_id}/adopt` | `knowledge.adopt` | Registered |

Errors keep `{code, diagnostic}`: 404 `not_found`/`project_unregistered`, 422 schema and argument refusals, 409 for
stale, conflict, query-only and policy refusals. Diagnostics use `tr()` keys `domain.*` in English and Spanish.
OpenAPI is exported and `frontend/src/api.generated.ts` regenerated; no UI is added (T012).

**Graph (harness).** `orchestration/domain.py` provides `domain_command(config, operations, ref, arguments)`, which
binds a harness caller from the thread and uses `operation_key(config, name, references)` as the idempotency key. A
replayed node therefore receives the stored outcome; because the command is transactional there is no sealed-but-
uncertain state, which is how FL13's "committed or absent" satisfies D282's deterministic-key rule for domain
commands. No product graph is registered; evidence uses synthetic graphs with the real runner and service.

**Broker (agents, T008).** T005 provides `scoped(caller)` (entries visible to the caller, nothing else disclosed),
`describe(caller, id, version)` and the same `execute`. Transport, search ranking, bounded descriptors over MCP and
launch flags are T008. Until then no agent can reach the service in the product (§4).

**Available versus integrated.** At T005 closure the owner API and the graph binding would be callable and tested;
no UI, product graph, broker transport or agent uses them. Flows FL04/FL09 remain unintegrated.

## 9. Technical impact

| Component | Change |
|---|---|
| `core/engine/domain_catalogue.py` (new) | Entries, canonical schema digests, catalogue digest, reserved-name linter, standard-library validator for the schema subset used (object, string, integer, boolean, array, enum, required, closed objects, bounds, pattern) |
| `core/engine/domain_policy.py` (new) | Principal/kind rules, capability evaluator over snapshot, ceilings and exclusions ([§5.2](#52-per-operation-capabilities-and-current-ceilings)), sensitivity and owner-only classifier ([§5.4](#54-sensitivity-and-owner-only-exclusion-requires-owner-confirmation-q1)), provenance rule, request and preview digests; pure |
| `services/domain_operations.py` (new) | `Caller`, binders, `PermissionProvider`/`PermissionState` and the other provider protocols with fail-closed defaults, `execute`, handlers, refusals; constructed from the engine, with a read path independent of the runtime's project map |
| `storage/knowledge.py` | Session-bound variant; no behavior change for existing callers |
| `storage/domain_commands.py` (new), `storage/models.py`, `storage/schema.py`, migration `0031_domain_commands` | Outcome table, insert-only triggers, partial unique index on accepted keys; `SCHEMA_REVISION`, required tables and trigger digest; backup/restore already copy the database and check the trigger digest |
| `api/knowledge.py` (new), `api/schemas.py`, `api/app.py` | Typed routes and models; router inclusion |
| `orchestration/domain.py` (new) | Graph binding; LangGraph stays confined to `orchestration/` |
| `services/managed_runtime.py` | `domain_operations()` composition with the fail-closed providers |
| `i18n/en.json`, `i18n/es.json` | `domain.*` diagnostics |
| `frontend/openapi.json`, `frontend/src/api.generated.ts` | Regenerated; no UI change |

**Schema.** One table, `domain_commands` (72 → 73 tables, head `0031_domain_commands`), because draft authorship,
idempotency and the outcome record need durable rows and no existing table can hold them without changing T004's
protected tables or the job queue. Downgrade refused while rows exist, as for 0030. No grant, snapshot or ceiling
table is added: their storage is T010's, behind `PermissionProvider`. No new dependency.

**Alternatives discarded.** A `created_by` column on `knowledge_revisions`: alters a trigger-protected T004 table and
solves authorship only. Waiting for T006's journal: T006 depends on T005. Idempotency in `managed_jobs`: would
route domain commands through the scheduler and create a second queue meaning. `jsonschema`: a new dependency without
need. Pydantic-derived JSON Schema digests: they change with the pydantic version, which would silently change
catalogue digests, and the core must stay standard-library only. A generic browser `invoke` endpoint: untyped
OpenAPI and a wider bypass surface (TM03). Extending `change_summary`: changes D284's hashed contract.

## 10. Evidence plan

All synthetic: temporary SQLite and Git roots, the real service, repository, runner and API test client; no CLI,
provider, network or harness execution.

| ID | Threat | Case | What it shows |
|---|---|---|---|
| E01 | TM04 | Caller fields (`project_id`, `role`, `origin`, `actor`, `invocation_id`…) in arguments of every entry, through API and `execute` | Refused `arguments_invalid`; the linter rejects such schemas; identity comes only from binders |
| E02 | TM04 | Draft, item and revision ids of project B used from project A (API and service) | Same `not_found` for foreign and missing; no row changed |
| E03 | TM04, TM03 | Agent caller in the product composition; synthetic resolver only in tests | Product refuses `caller_unavailable`; no synthetic provider in `src/` |
| E04 | TM02 | Wrong schema digest, unknown or retired version, golden digests of all entries | Refused without fallback; any silent schema change fails a pinned-digest test |
| E05 | TM03 | Each entry reached through `execute` by every principal/role; static check that no product module except the service calls knowledge mutation methods | One path; no SQL, file or code entry exists; the catalogue is a pinned list |
| E06 | TM01, TM05 | Executor propose, reviewer adopt, entry outside the frozen tool policy, judge any entry | Refused `caller_not_allowed` |
| E07 | TM05 | Agent draft adopted by the agent, by a harness caller (`owner_delegated`, `harness_deterministic`), then by the owner | Only the owner succeeds; outcome shows `owner_confirmed`, owner actor and agent opener separately |
| E08 | TM05, TM01 | Classification fixtures for every row of §5.4: requirement and criterion edits, criterion re-owned or reordered, phase added, withdrawn or objective changed, phase `addresses`, instructions target/parent/root order, decision supersession, new decision, task planning with new criteria, spec sections; injected "this change is not sensitive" text | Expected class and sensitivity per row; sensitive ⊇ `change_summary.sensitive`; every owner-only change sensitive; reason required for sensitive changes; `knowledge.adopt:owner_only` unsatisfiable by any snapshot; text does not change the result |
| E09 | TM05 | Stale expected head, stale draft hash, draft edited after preview, head moved after preview | `stale_revision`, `draft_changed`, `preview_stale`; no revision or version written |
| E10 | TM05 | Two connections adopting drafts on one base; two applies with one expected hash; one key sent concurrently | One success; the other stale, changed or replayed; database indexes hold with the service bypassed |
| E11 | TM03, TM04 | Same key and payload; same key other payload; same key in two principal scopes | Replay without writes; `idempotency_conflict`; scopes independent and not observable |
| E12 | — (INV-05) | Fault injected after the knowledge mutation and before the outcome insert, and after the outcome insert before commit; subprocess exit before commit | Mutation and outcome both absent; never one without the other |
| E13 | TM18 | Every new route without session, foreign Host/Origin, cross-site, missing CSRF header, missing key, on a marked query-only archive (mutations and previews 409, reads 200) | Existing guards apply to all new mutations; diagnostics in en/es |
| E14 | TM12 (support) | Synthetic graph opening a draft; crash after commit and before the checkpoint; resume | One draft; the replay receives the stored outcome; the harness cannot adopt |
| E15 | TM05 | Agent `known` provenance or legacy source | `provenance_not_allowed` |
| E16 | TM01, TM15 | Paging bounds, agent revision other than frozen, agent query without a delivery sink | Bounded results; `revision_outside_context`; refused without receipts |
| E17 | TM01, TM04, TM05 | Test-only provider: a snapshot granting `knowledge.list` but not `knowledge.get`; `draft.open` but not `draft.apply`; `knowledge.propose:task` while the change also touches a requirement; a grant in another dimension; a target the snapshot grants but the current `project` layer or the `role` ceiling lacks; a grant revoked or expired after the snapshot; grants combined to reach `knowledge.adopt:owner_only` | Each call refused with `capability_denied`, `ceiling_excluded` or `owner_only_excluded` and nothing written; the allowed counterpart succeeds and its outcome records snapshot digest, grant ids, ceilings digest and policy version |
| E18 | TM04, TM12 (support) | Provider transactionality: the provider receives the command's session; a provider exception rolls back the mutation; a revocation committed by another connection before the command takes the lock refuses it; one committed while the command holds the lock waits and applies to the next call; product composition uses `UnavailablePermissions` | Capability state, mutation and outcome come from one transaction; product refuses `capability_unavailable` |
| E19 | TM01, TM14 | Agent frozen at revision N; the owner adopts N+1 (adds item X, changes item Y, adds a phase); the agent calls `knowledge.head`, `list` without and with `revision: N+1`, `get` of X and Y, `draft.open` naming N | `head` returns N's id, number, hashes and counts; `list` returns N's members; Y at N's version; X `not_found`; `revision: N+1` and `revision: 99` give identical `revision_outside_context` bodies; the draft is based on N; a scan of every serialized result and refusal finds no id, number, hash or count of N+1 |
| E20 | TM18 | Backup and query-only restore of a database with two accepted revisions and an open draft; archive service with no registered project, no supervisor and the original root removed | `knowledge.projects`, `head`, `list`, `get` of revisions 1 and 2 and `draft.get` return content and hashes identical to the source; every mutation route 409 `restored_read_only`; the service called directly refuses `query_only`; the database file is unchanged; in ordinary mode an unregistered root keeps its reads and refuses mutations `project_unregistered` |
| E21 | TM01, TM04, TM16 | An exact unrevoked grant allows the operation, but: the frozen `contract` layer lacks the target; the frozen `provider` layer lacks it; the current `permission_authority` drops it from `contract` or `provider` after admission; the current value adds a target the frozen copy lacks; the project has no `permission_authority`; the provider omits a layer; the client's frozen tool policy excludes the entry; a 0.1.9 `permission_requests` grant names the same target | `ceiling_excluded` naming the layer in the first five cases and for the omitted layer (no widening from the current copy); `caller_not_allowed` for the tool policy; the 0.1.9 grant satisfies nothing; nothing written in any case; the same call with every layer containing the target succeeds |

**Not qualified by T005.** Real transport and CLI behavior (T008, T021); real invocation identity, tool policy and
permission snapshots (T006/T008/T010); receipts (T007); grant storage, lifecycle, target normalization and
delegated adoption (T010, T016), beyond the evaluator and transactional use tested with the test-only provider; UI
journeys and archive UI (T012, T020); same-user processes altering the database (TM11, D064); correctness of what an
authorized principal adopts.

## 11. Boundaries with later tasks

| Task | Uses from T005 | Stays blocked until that task |
|---|---|---|
| T006 | `AuditSink`, `CallerResolver` protocol, `domain_commands` rows to link | Agent callers; events and traces of commands |
| T007 | `delivery` descriptors, `DeliverySink`, frozen-revision rule | Agent knowledge queries; D094 replacement |
| T008 | `scoped`, `describe`, `execute`, catalogue digests | Any model-selected call |
| T009 | New duty-scoped entries through the same catalogue and pipeline | Judge rulings; spec-gap proposals |
| T010 | `PermissionProvider`/`PermissionState`, the evaluator and capability targets of §5.2 | Storage-backed snapshots, grants, ceilings and revocation; agent authority in the product |
| T011, T013 | Harness/owner drafts and `knowledge.adopt` | Creation/onboarding drafts, import, export effects |
| T012 | The owner routes | UI editing, fork and rebase |
| T014–T016 | Effect kinds, `AuthorizationProvider`, classification classes | Effects, delegated adoption, autonomous runs |

## 12. Decisions and owner questions

**Applied without change.** D269 (services validate; graph holds references), D270/D284 (drafts, CAS adoption,
immutability, hashes), D272 (three origins, delegated never shown as owner), D273 (owner-only list, judge never
adopts), D274 (five dimensions, checks at every command, new-attempt application left to T010), D275/D281 (catalogue,
digest, caller from the transport, no SQL or fallback, broker left to T008), D282/D283 (deterministic keys; no
atomicity with checkpoints), D285 (instructions sensitive; D094 in force until T007), D235/D242/D253 (branch and route),
D260 (quiet checks), INV-01–INV-12.

**Technical resolutions offered for review** (reversible, within those decisions): the ten operations and their
kinds (§3); the frozen-revision view of agents and persisted-data archive reads (§4); capability targets, the
evaluator and `PermissionProvider` (§5.2); draft ownership by opener and owner-only adoption in T005 (§5.3);
fail-closed provider defaults (§4); agent provenance limited to `inferred`/`unknown` (§5.5); refusals not reserving
keys (§6); typed owner routes instead of a generic endpoint, reads addressed by knowledge project (§8); graph keys from
`operation_key` (§8); standard-library schema validator (§9).

**Q1 — Sensitivity and owner-only exclusion.** Choose the table of
[§5.4](#54-sensitivity-and-owner-only-exclusion-requires-owner-confirmation-q1). Sensitivity (listed individually, reason
required, explicit naming in any delegation) and owner-only exclusion (never adoptable except `owner_confirmed`) are
separate properties. Under every option, changes to roadmap objectives and to the authorized phase set, requirements,
criteria that may be weakened and instructions stay owner-only (D273, D276); delegating them is not an admissible
alternative.

- (a) **Recommended:** the table as proposed.
- (b) Same owner-only set, except three changes that become sensitive but delegable (`product`): a phase title or tag
  edit that leaves its objective and the phase set unchanged, a reorder of criteria without content change, and the
  supersession of an accepted decision.
- (c) Every change owner-only until T016 defines its tiers.

(b) relies on judging mechanically that a title, tag or order change has no meaning, and lets delegation supersede a
product decision; (c) is safe but blocks the delegated task planning D276 requires, so T016 would have to reopen it.

**Q2 — Proposed D286: typed domain operation service and command outcome record.** Adopt §§3–8 as the T005 contract
and the new `domain_commands` table with migration `0031_domain_commands` (insert-only, partial unique index on
accepted keys). Alternatives and why they were discarded are in [§9](#9-technical-impact). Recommendation: accept.
If declined, T005 cannot enforce draft ownership or durable idempotency and would have to wait for T006, reversing the
plan's dependency.

**Q3 — Implementation branch.** (a) **Recommended:** integrate this accepted refinement and implement on
`feat/p002-t005-domain-operations` from the resulting `develop`. (b) Continue on this branch and integrate refinement and
code together. Either keeps the route above.

No other incompatibility was found between the accepted documents and the code. D284's `change_summary` is not
extended; the classifier is separate.

## 13. Acceptance criteria

1. API, graph and dispatcher calls of each entry run the same `execute` pipeline; no product module mutates
   knowledge outside the service (static test).
2. Caller identity, project and origin never come from arguments; foreign identifiers are indistinguishable from
   missing ones.
3. Only the owner adopts in T005, by exact preview hash, with a reason for sensitive changes; agents and the harness
   are refused; delegated and deterministic adoption fail closed; owner-only changes are unsatisfiable by any grant
   combination.
4. Every call is checked against its entry's per-operation requirements, in addition to role and tool policy: for
   agents, exact unrevoked grants of the frozen snapshot within all of `global`, `project`, `contract` and `provider`
   (frozen and current copies intersected) and the `role` ceiling, read by `PermissionProvider` in the command's
   transaction, with the basis recorded in the outcome. No 0.1.9 restriction is dropped or widened: path rules, the
   client capability contract and the tool policy keep their current evaluation points.
5. Agents see only their frozen revision: no result or refusal discloses a later revision.
6. Stale head, draft or preview, idempotency reuse and concurrent calls behave as §6, with the database guarantees
   intact when the service is bypassed.
7. Every accepted mutation has exactly one outcome row in its transaction; no mutation exists without it.
8. All new routes keep session, Host/Origin, `Sec-Fetch-Site`, CSRF, `Idempotency-Key` and query-only guards; reads
   work on a restored query-only copy from persisted data alone, without registered projects or the checkout.
9. The product composition contains no permissive or synthetic provider; agent calls are refused.
10. Evidence E01–E21 passes, with TM01–TM05 and TM18 cited; parity documents updated; nothing designed-only is
    labelled implemented.

## 14. Verification plan and parity

- Focused first: `scripts/check tests/product/test_domain_operations.py tests/product/test_knowledge.py`, then
  `tests/product/test_knowledge_api.py` (including the restored-archive reads), `test_orchestration.py`,
  `test_backup.py`, `test_configuration.py` (table count) and `test_service_texts_catalog.py`.
- At closure: `scripts/check` (shared infrastructure: unittest, `alembic check`, full pytest) and
  `scripts/check --frontend`, because the exported OpenAPI and generated client types change.
- `scripts/check-docs` and `git diff --check`.
- Parity in the same task: DDBB-DIAGRAM (head `0031_domain_commands`, 73 tables, the new entity and its relation to
  knowledge); a new implemented flow `docs/flows/domain-operations.md` (pipeline, refusals, replay) and an update of
  `graph-continuation.md` for the graph binding; OpenAPI and `api.generated.ts`; en/es keys; SPECIFICATION §14 and
  ARCHITECTURE §13 labels ("implemented, used by the owner API only"); STATE and NEXT_STEPS.

## 15. Delivery status

**Delivery status.** Source complete on `feat/p002-t005-domain-operations`, created from `develop` at `95ac6df` with the
refinement's uncommitted documents carried along (Q3). After reviewing the result the owner authorized commit, merge
into `develop` and push (2026-10-29); Git history records the commit and merge identities. No release, publication or
installation applies to T005; the 0.2.0 route remains pending (D242/D253).

### Implementation notes

Technical choices made within the accepted contract:

- The T004 repository runs inside a caller's transaction through `KnowledgeSession`; `KnowledgeRepository` keeps its
  self-transacting API on top of it, so T004 behavior and tests are unchanged.
- `domain_commands` stores JSON `None` as SQL NULL (`none_as_null`), which the outcome check needs to tell refusals
  from accepted rows. The trigger digest now covers 24 triggers (21 of 0030, 3 of 0031).
- Item ids are assigned by `put`, so a link to an item created in the same `draft.apply` call is not possible; the
  caller links it in a following call with the new draft hash. A link counts for the groups of both endpoints, so
  attaching a task to a phase needs `knowledge.propose:task` and `knowledge.propose:phase`.
- A replay returns the stored result before capabilities are evaluated again (§6); agent queries take the write lock
  because their receipts are writes.
- `AuthorizationProvider` is declared for T016; T005 refuses every non-owner adoption before consulting it.
- The knowledge router is mounted after the existing routers, so the exported OpenAPI only gains the ten paths and
  their schemas; no existing path or schema changed.

### Evidence

- **Focused suites.** `tests/product/test_domain_operations.py` (39 tests, stable over three runs) and
  `tests/product/test_knowledge_api.py` (3 tests) cover E01–E21: reserved caller fields for every entry (E01);
  foreign and missing ids with one body (E02); product composition refusing agents and no test double in `src/` (E03);
  pinned digests, schema mismatch, unknown and retired versions (E04); one mutation path by static check (E05); roles
  and tool policy (E06); owner-only adoption with opener and adopter recorded apart (E07); 17 classification cases,
  D284 superset, injected text and the unsatisfiable owner-only target (E08); stale head, draft and preview (E09);
  concurrent adoptions, applies and keys, and raw-SQL substitution of outcomes (E10); replay, conflict and key scopes
  (E11); fault before the outcome row, after it and a child process exiting before commit (E12); session, Host,
  Origin, `Sec-Fetch-Site`, CSRF, missing key, forged body field and unregistered project on the API (E13); a graph
  node crash after its committed command, recovered with the stored outcome (E14); agent provenance (E15); bounded
  agent queries and receipts (E16); per-operation grants, dimension, current project and role ceilings, revocation and
  the recorded basis (E17); provider in the command transaction, provider failure rolled back and a concurrent
  revocation waiting for the lock (E18); frozen revision N against an adopted N+1 with no disclosure (E19); backup and
  query-only restore read identically with every mutation route refused and the database unchanged (E20); contract and
  provider layers frozen or current, current widening, missing layer, null authority, tool policy and a 0.1.9 grant
  (E21). Threats cited: TM01–TM05 and TM18, with TM12 support for graph replay.
- **Existing tests adjusted.** Schema head (`test_storage_api`, `test_usage_accounting`), table count 74
  (`test_configuration`) and the knowledge trigger count (`test_knowledge`). Outside T005's own scope,
  `test_knowledge.py::test_substitution_bypasses_are_refused_by_the_database` was flaky on `develop` (3 of 8 runs
  failed with the original code: `LIMIT 1` over random UUIDs sometimes picked the spare item's own version); its query
  now excludes that item (one line), and 12 runs passed.
- **Closure checks.** `scripts/check --frontend`: unittest 10 ran ok; `alembic check` no new operations; pytest 2436
  passed, 2 skipped (one pre-existing intentional zip warning); node 248 passed; frontend build (tsc + vite) ok.
  `scripts/check-docs`: 91 tracked documents, 0 errors; the untracked record and flow pass when given explicitly (2
  documents, 0 errors). `git diff --check` is clean over tracked changes, and the untracked files have no trailing
  whitespace.
- **Mermaid.** All 66 Mermaid blocks of the repository's Markdown pass `mermaid.parse` with the installed mermaid
  11.17.2 under Node (DOMPurify stubbed, no DOM). The first parse found two sequence diagrams broken by `;` inside
  messages, which Mermaid reads as a statement separator: the new domain-operations flow and the existing T003
  graph-continuation flow; both now use commas. Layout and browser rendering were not exercised.
- **Parity.** DDBB-DIAGRAM (head `0031_domain_commands`, 73 tables, the new entity), flows
  [domain operations](../flows/domain-operations.md) (new) and [graph continuation](../flows/graph-continuation.md),
  exported OpenAPI and `frontend/src/api.generated.ts` (additions only), 34 `domain.*` keys in English and Spanish,
  SPECIFICATION §14, ARCHITECTURE §§1, 7 and 13, ROADMAP, STATE, NEXT_STEPS and D286.
- **Not performed or not qualified.** No UI; no real agent, CLI, provider, broker transport, harness execution or
  network access. Real invocation
  identity, permission snapshots, receipts, grant lifecycle and delegated adoption remain with T006–T010/T016, as
  listed in [§10](#10-evidence-plan) and [§11](#11-boundaries-with-later-tasks).
