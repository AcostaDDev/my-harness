# Flow — frozen context and knowledge receipts

P002-T007 implements FL08 and D270/D277/D285 through the explicit canonical path
([D288](../DECISIONS.md#d288--frozen-invocation-context-and-exact-exposure-evidence),
[evidence](../phase/P002-T007-frozen-context.md)). Product graphs remain with T014–T016.

```mermaid
sequenceDiagram
    participant C as Trusted consumer
    participant S as Context and domain services
    participant DB as SQLite
    participant M as Fenced managed attempt
    participant A as CLI adapter
    C->>S: prepare_for(context, selected IDs, client, code captures, revision)
    S->>DB: Verify accepted revision; persist immutable source bytes and digest
    S-->>C: Snapshot ID (selection, no delivery)
    C->>S: render(snapshot ID, catalog, template, values)
    S-->>C: Prompt and sealed canonical-context marker
    C->>M: agent_started(request, InvocationOperation)
    M->>DB: One transaction: attempt + ledger + operation + context boundary + intent event
    alt Known refusal before spawn or before GO
        A->>M: Explicit refusal boundary (before_spawn or before_go)
        M->>DB: Fenced failure receipts, no delivered digest
    else Target launch permitted
        A->>A: Launch under the existing process intent; write complete input
        A->>M: Completed input observation with rendered and transport digests
        M->>DB: Fenced transaction: exact initial exposures + receipt envelopes
    end
    C->>S: execute(agent, knowledge.lookup/search ref, arguments, stable delivery key)
    S->>DB: Lock, verify caller/boundary/capabilities; replay or read frozen revision
    S->>DB: Exact response, per-exposure receipts and journal envelopes, commit together
    S-->>C: Bounded result (only after successful commit)
```

- **Selection.** Relevance is explicit by stable ID (at most 50), not a model inference or generated Markdown.
  Applicable active canonical instructions are mandatory: tree preorder within `agents`, then client-specific
  sections. In `frozen-context-2`, the exact per-section exposure is the full heading at accepted tree depth,
  one LF and the verbatim body; titleless preambles stay verbatim. These same exposures enter the prompt and
  determine receipt digests, including title-only rules and titles scoping child sections. Retired sections remain
  historical knowledge; only active sections enter instructions. The profile is captured from the frozen project
  context and checked again at render/start; code captures are
  supplied by trusted consumers with identity, version, provenance and checked bytes/hash. They never gain
  canonical knowledge authority. Preparation failures emit bounded failure events without context text.
- **Boundary.** The snapshot pins the accepted revision, its verified chain/hash, versions, order and bytes.
  `agent_started` checks the actual rendered prompt, snapshot marker and root, then seals the snapshot with the
  native attempt/ledger/invocation operation in one fenced transaction. A newer adoption changes neither that
  snapshot nor its queries. Only another explicit preparation and new invocation/attempt can receive it.
- **Delivery.** Selection, intent and observed input are different evidence. A known refusal before spawn is explicit
  in its intent/capture, has no target identity and creates no artifact references. If the executable changes
  while the gate waits, the adapter explicitly records `launch_boundary=before_go, launch_permitted=false` before
  sending GO; the gate identity stays recorded but the CLI did not run. Both persist failure receipts without
  delivered digests. A stopped group, cancellation, partial write or refusal diagnostic alone supplies no such
  boundary proof. A crash between intent and launch has no delivered receipt. A complete input write
  followed by a receipt-write failure is an uncertain delivery; the adapter stops/fails, and does not retry.
  Kernel-pipe availability is the observation; model ingestion or comprehension is not asserted.
- **Reads.** New lookup/search serve one verified accepted revision through the T005 pipeline. Search is literal,
  casefolded and deterministic. Cursors bind exact arguments (excluding the cursor) and frozen revision, and
  never consult a later head or another project. Metadata, excerpt and full exposures have separate actual
  exposure digests. UTF-8 byte ceilings and Unicode code-point ranges/truncation are explicit; full requests
  become excerpts when bounded. Per-exposure truncation and result-page continuation are both recorded.
- **Atomicity/reentry.** The write lock covers caller re-verification, current permissions, query and receipt.
  A receipt/event/commit failure returns no query content. Keys (1–180 characters) are scoped by invocation and
  delivery channel; identical calls return stored bytes without another receipt, changed arguments conflict.
  Recorded read failures reserve the delivery key; input/schema/caller/capability refusals stay in the ordinary
  domain refusal audit. Transport delivery after the service commits is availability to that transport; no
  end-to-end acknowledgement, cross-checkpoint atomicity or replayed inference is invented.
- **Archives.** `snapshot`, `invocation` and paged `deliveries` read persisted scope/bytes only. The invocation
  reader exposes the exact saved prompt and its snapshot outside trace events. Restored copies refuse every
  preparation/write. Backups verify snapshot/source hashes, boundary links, response/exposure digests and
  receipt-event correspondence. Missing native file observations remain unknown.
  Artifact inventories exempt only consistent, positively evidenced no-launch refusals without contradictory
  stream/agent/input observations. A before-spawn refusal has no prompt/stream paths. A before-GO refusal retains
  its real required prepared prompt, with no invented streams. Launched processes keep all artifact checks.
- **Compatibility.** An explicit canonical marker selects D285 rendering for all supported prompt templates,
  including definition templates without a historical instruction slot. Without it the historical rendering
  and snapshots stay unchanged. Body-only `frozen-context-1` snapshots/receipts remain readable and backed up
  verbatim; new canonical invocations require a newly prepared v2 snapshot. No existing project is converted;
  T008 adds the explicit [broker and persisted caller binding](tool-bridge.md), including descriptor/schema and
  logical-result receipts on `tool_result`. T013 owns generated exports, T010 permission storage,
  T014–T016 product graph migration, T018 views and T020 conversion.

Tables: [data diagram](../DDBB-DIAGRAM.md#p002-frozen-context-and-delivery-evidence).
