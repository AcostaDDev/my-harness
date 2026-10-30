# Flow — scoped tool bridge and lazy discovery

P002-T008 implements FL09 and the T008 part of G04 under D275/D281/D289, with FL08 receipts and FL13 recovery.
Source is integrated into develop at the owner's authorization after the three review corrections; no product graph launches it.
[Contract, checks and limits](../phase/P002-T008-scoped-tools.md).

```mermaid
sequenceDiagram
    participant T as Trusted request assembler
    participant DB as SQLite
    participant SV as Supervisor and domain services
    participant CLI as Selected CLI
    participant MCP as Invocation stdio relay
    T->>T: policy(request, exact tool refs, qualified client/version/role cell)
    T->>DB: Fenced agent_started: attempt request/policy + ledger + operation + canonical boundary
    SV->>DB: Resolve and verify attempt, invocation, operation, project, revision, policy and live writer
    SV->>SV: Private invocation endpoint; process intent; independent launch guard
    SV->>CLI: Strict per-invocation harness server and exact three-tool allowlist
    CLI->>MCP: Spawn isolated Python stdio relay (possibly in another process group)
    MCP->>SV: Register PID, parent and process group on private endpoint
    SV->>DB: Persist bridge identity before acknowledging calls
    CLI->>MCP: initialize with supported protocol
    MCP->>SV: Confirm protocol and exact broker surface digest
    SV->>DB: Persist bridge.ready with registered identity before acknowledgement
    SV-->>MCP: Availability acknowledgement
    MCP-->>CLI: MCP initialization response (logical calls remain optional)
    CLI->>MCP: search_tools, describe_tool
    MCP->>SV: Forward broker arguments (no authority fields)
    SV->>DB: Reverify caller; commit scoped response, discovery envelope and exact response receipt
    SV-->>CLI: Bounded descriptors or exact schema/digest
    CLI->>MCP: invoke_tool(id, version, digest, arguments, key)
    MCP->>SV: Forward invocation
    SV->>DB: DomainOperations.execute: current authority, closed schema, project, revision and idempotency
    SV->>DB: Commit outcome/response/receipts and correlated logical/broker result events
    SV-->>CLI: Typed result or refusal after persistence
    SV->>SV: On cancellation or CLI exit close bridge connection independently of CLI exit code
    MCP->>MCP: EOF, supervisor disconnect or parent loss exits even during a call
    SV->>DB: Record disconnect and observed stopped identity; uncertainty blocks recovery
    SV->>DB: Persist invocation failure if scoped bridge availability was never confirmed
```

- **Authority.** Only trusted assembly selects the frozen exact logical refs. `InvocationResolver` reconstructs the
  caller from native persisted rows and verifies all fields inside each domain transaction, including the job's
  owner token, live lease and checkout lock. The relay receives an endpoint, never a database connection or caller
  supplied by the model. The private Unix socket/directory have modes 0600/0700; same-user containment is cooperative,
  not OS isolation. The stdio child performs no domain effects itself.
  Its trusted interpreter uses `-I -m`, excluding checkout and inherited Python import paths/user site; imports
  resolve through the installed harness environment. The independent guard requires that isolated launch.
- **Disclosure.** Exactly three initial MCP schemas. Search matches literal casefolded ID/summary, sorts by ID/version,
  returns at most 50 descriptors (default 20); cursor binds query, limit, scoped refs and invocation. Description
  returns only an exact scoped version; schema/digest/version mismatch and generic-invoke bypasses are refused.
  Discovery is availability, not a grant. T010 permissions remain absent and deny logical calls in product composition.
- **Persistence.** `tool-discovery-1` remains unchanged; scoped search and delivered schema emit `tool.discovered`.
  Descriptor/schema bytes use existing `tool_result` response receipts. `broker.called/result`, `tool.called/result`
  keep separate identities under the existing invocation operation; mutation results include their command ID.
  Domain command events link back to that invocation. No extra usage invocation or inferred model turn is created.
- **Reentry.** Stable keys deduplicate descriptors/schemas in `broker:` and domain reads in `tool_result:`.
  Queries commit response and receipts together; mutations commit effects/outcomes in the domain transaction, then
  receipt the stable response before returning. A crash between those transactions replays the command after current
  authority checks; it cannot repeat an effect. Receipt/event failure returns no unrecorded content. Transport
  acknowledgement is not atomic with these commits. Each actual broker retry is an event, not a new inference.
- **Lifecycle.** The adapter injects only its own server. Bridge registration is written to the existing process spec
  and trace, then successful protocol/surface preparation writes `bridge.ready` before acknowledgement. Registration
  alone is insufficient: missing availability with an otherwise valid CLI final answer persists `failed` with
  `bridge_unavailable`, no answer, and the existing observed launch/telemetry. Available bridges need no logical calls.
  Cancellation and known prelaunch refusals clean up without asserting availability. No new table.
  Closing the socket stops detached relays; the supervisor observes PID liveness
  and records `bridge.stopped`. Potentially live bridge identities also block process recovery, without signalling
  persisted PIDs. An in-flight deterministic transaction may settle after disconnection; its outcome is reconciled.
  Peer EOF/reset/broken pipe at socket boundaries is an expected disconnect; a lost response is recorded and does
  not prove client delivery. Real domain/receipt/journal failures still propagate, even if cancellation already began.
  The inference with no native result becomes UNCERTAIN, never automatically relaunched, even after CLI exit 0.
- **Admission.** MC1–MC7 are required per exact client/version/role/evidence cell. T002's historical readonly
  `reviewer` cells are retained with their narrow provenance; simulated reviewer/executor cells exercise the current
  implementation. Other versions/roles/clients are blocked, with no catalogue, provider, model or API fallback.
  The synthetic third client proves protocol portability only; no OpenCode adapter exists.
- **Compatibility.** Requests without `scoped_tools` keep the historical launch policy (Claude MCP empty) and renderer.
  No product graph or installed project is converted. Persisted trace/receipt readers and backups retain the evidence
  without a checkout; archives never enable execution or writes. No HTTP contract, database schema or dependency changes.
