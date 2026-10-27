# Flow — phase lifecycle

Phases live in SQLite and READY is bound to exact content
([D032](../DECISIONS.md#d032--phases-in-sqlite-and-ready-bound-to-exact-content),
[D034](../DECISIONS.md#d034--unattended-batches-versioned-definitions-and-deterministic-annotated-tags)); closure
and archive form a single flow ([D091](../DECISIONS.md#d091--unified-closure-and-archive-with-later-planning)).

## Phase states

```mermaid
stateDiagram-v2
    [*] --> ACTIVE: bootstrap, previous closure or creation through the API
    ACTIVE --> CHECKING: check under the lock
    NEEDS_RECONCILIATION --> CHECKING
    READY_TO_CLOSE --> CHECKING
    BLOCKED --> CHECKING: no open questions
    CHECKING --> READY_TO_CLOSE: READY
    CHECKING --> NEEDS_RECONCILIATION: REVISE, document drift, STATE over 24 KiB or baseline over 12 KiB
    CHECKING --> BLOCKED: BLOCKED or open questions
    CHECKING --> ACTIVE: NOT_READY
    ACTIVE --> BLOCKED: blocking question
    NEEDS_RECONCILIATION --> BLOCKED: blocking question
    READY_TO_CLOSE --> BLOCKED: blocking question
    BLOCKED --> ACTIVE: questions answered
    NEEDS_RECONCILIATION --> ACTIVE: documents adopted by hash
    READY_TO_CLOSE --> ACTIVE: documents adopted or amendment
    READY_TO_CLOSE --> CLOSING: authorization on the shown READY or confirmed abandonment
    ACTIVE --> CLOSING: confirmed abandonment
    BLOCKED --> CLOSING: confirmed abandonment
    NEEDS_RECONCILIATION --> CLOSING: confirmed abandonment
    CLOSING --> CLOSED: tag and archive commit recorded
    CLOSING --> ABANDONED: archive recorded, no tag
    CLOSING --> NEEDS_RECONCILIATION: stale binding
    CLOSED --> [*]
    ABANDONED --> [*]
```

A check or closure that fails, is refused before effects or whose writer is confirmed stopped returns the phase to
its previous state (`BLOCKED` if there are open questions); a closure also invalidates its authorization and leaves
the tag intent sealed as an uncertain effect for reconciliation. Resuming a closure requires the same terminal state
and, for `CLOSED`, the same READY binding. Questions are refused in `CLOSING`, `CLOSED` and `ABANDONED`; amendments
also during `CHECKING`.

An amendment keeps the previous definition and invalidates READY and batches. The unattended batch chains
`task → commit → next task` but never checks or closes. An interrupted closure keeps its sealed intent: after the
writer is confirmed stopped, a new explicit request resumes the same run and commit.

## Unified closure and archive

```mermaid
flowchart TD
    A["READY check and its own authorization"] --> B["Verify clean checkout, document baseline and no pending work"]
    B --> C["Freeze the archive and the successor from ROADMAP; refuse collisions and links"]
    C --> D["Job under the lock: observe READY again and seal the commit intent"]
    D --> E["Persist the tag intent and create the tag on the evaluated HEAD"]
    E --> F["CAS of documents and artifacts: only previous or sealed bytes"]
    F --> G["One commit: STATE, NEXT_STEPS, REVIEW, SUMMARY and docs/phase/ in archive/phase-NNN/"]
    G --> H["Fresh STATE with the compact baseline; NEXT_STEPS with the objective and criteria of N+1, no tasks"]
    H --> I["ROADMAP: N completed with a link to its archive; docs/phase/ empty"]
    I --> J["SQLite records the closure and creates N+1 ACTIVE with its adopted documents, atomically"]
    J --> K["Plan N+1 later: user text or phase_planning proposal"]
    K --> L["Preview and hash confirmation: documentation commit and a new phase definition"]
```

Abandonment uses the same archive and commit, without READY or tag. If ROADMAP has no successor, the phase is
archived and STATE says that there is no active phase. STATE and NEXT_STEPS are archived byte for byte, as are binary
artifacts and subfolders of `docs/phase/`. REVIEW and SUMMARY are generated from the SQLite snapshot.

Separate phase transitions from earlier versions are refused; intents already sealed keep their recovery path in the
engine, without API or UI endpoints. A pending intent is never recomputed and its snapshots are never rewritten. The
planning prompt targets the exact phase of its context: the empty ACTIVE phase. It proposes NEXT_STEPS and requires
its own plan confirmation; it authorizes no other transition. The page of an ACTIVE phase without tasks offers text
or a conversational proposal, a preview with diff and hash, a reason and an idempotent confirmation of the plan.
Changing the phase version or the plan source discards the preview. A closed phase links to its successor.

## Reading a closed phase

Reading a `CLOSED` or `ABANDONED` phase adds `closure`, without changing `phase.documents`, the READY result or what
a check verifies:

```mermaid
flowchart TD
    A["Finished close operation"] --> B["Historical result and baseline: READY check, head, evidence, tag, reason"]
    A --> C["Expected = adopted baseline + documents renewed by the closure + later confirmed edits"]
    A --> D["Archive: hashes written by the closure"]
    C --> E{"Is there a successor?"}
    E -->|yes| F["Live documents belong to the successor: not compared here"]
    E -->|no| G["Live differs from expected: real drift (changed); equal: expected renewal (renewed)"]
    D --> H["Disk differs from the closure hash: archive altered (archive_altered)"]
```

The documents page uses the same expected hashes when the latest phase is finished, so the renewal made by the
closure does not show as drift. An open phase keeps its guards: drift against the adopted baseline and a stale READY
if the documents change.

## Source

- `core/engine/phases.py`, `storage/phases.py`: check, closure, questions, amendments, abandonment and batch.
- `storage/closure.py`, `core/engine/document_ops.py`: preparation, intent and adoption of the archive.
- `storage/phase_plan.py`, `storage/planning.py`: later plan confirmation and conversation over the empty active
  phase.
- `storage/transition.py`: reconciliation of earlier transitions.
- `storage/phases.py` (`closure_view`, `expected_documents`), `storage/documents.py` (`status`) and
  `frontend/src/Phases.tsx`: reading a finished phase.
- `core/engine/documents.py`: REVIEW, SUMMARY and the STATE, NEXT_STEPS and ROADMAP projections.
