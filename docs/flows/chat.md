# Flow — project chat

Questions over a HEAD snapshot without waiting for the executor, deterministic commands and proposals that become
tasks only after confirmation ([D035](../DECISIONS.md#d035--chat-as-new-read-only-turns-with-confirmed-proposals),
[D083](../DECISIONS.md#d083--chat-over-a-head-snapshot-in-its-own-lane)).

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant API as Chat API
    participant DB as SQLite
    participant L as Chat lane
    participant R as Reviewer (chat, read-only)
    U->>API: message
    alt command /estado /tests /siguiente /lote /check /cerrar /exportar /abrir-fase
        API-->>U: preview without effects (closed grammar, no model)
        U->>API: the same confirmation as the equivalent UI control
    else command /tarea text
        API->>DB: QUEUED turn (chat_command) with a frozen deterministic proposal
        L->>DB: ANSWERED with that proposal, without exporting HEAD or invoking the reviewer
    else question or request
        API->>DB: QUEUED turn with frozen context
        L->>L: export the HEAD tree to a private folder (no .git, no links)
        L->>R: chat-turn (new session)
        R-->>L: answer and optional proposal
        L->>L: compare the evidence before and after
        L->>DB: ANSWERED, FAILED, UNKNOWN or REFUSED
    end
    U->>API: accept the proposal (hash and version)
    API->>DB: normal task in the active phase (plan, execution, review, commit)
```

Questions do not take the checkout lock; accepted tasks follow the [task flow](task-run.md). Command names are
protocol tokens with historical Spanish names (`/estado` status, `/siguiente` next task, `/lote` batch, `/cerrar`
close, `/exportar` export, `/abrir-fase` open phase, `/tarea` task) and are not translated; the `/tarea` answer follows the interface language and the proposed task
text follows the work language ([D169](../DECISIONS.md#d169--sealed-language-directive-generated-documents-in-the-work-language)).
A turn whose writer is confirmed stopped becomes `UNKNOWN`, and one refused before effects `REFUSED`; neither is
retried automatically. Each turn seals the interface language current at admission
([language preferences](language-preferences.md)).

## Source

- `core/engine/chat.py`, `core/engine/chat_commands.py`, `storage/chat.py`, `adapters/chat_snapshot.py`.
- Template `chat-turn.md`.
