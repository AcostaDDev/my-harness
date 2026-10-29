# Flow — explicit SQLite migration

The installed `my-harness migrate` command upgrades an existing database after a verified snapshot
([D150](../DECISIONS.md#d150--explicit-migration-from-the-installed-cli)). `init-db` creates a database; `serve`
checks the revision and never migrates ([D043](../DECISIONS.md#d043--local-distribution-with-assets-and-migrations-explicit-start-on-loopback)).

```mermaid
sequenceDiagram
    actor U as Operator
    participant CLI as my-harness migrate
    participant DB as Existing SQLite
    participant C as Snapshot folder
    U->>U: Stop the service and the writers, install the wheel
    U->>CLI: absolute --database, absolute --snapshots, --writers-stopped
    CLI->>DB: Reads: revision, restore marker, owners and groups
    Note over CLI,DB: Refusal without migrating on a linked path, missing database or no Alembic,<br/>unknown revision or a live recorded owner/group
    CLI->>CLI: Check snapshots are outside Git checkouts and persisted roots
    alt Current revision
        CLI-->>U: current, no changes and no snapshot
    else Known earlier revision
        CLI->>C: Exclusive SQLite backup, integrity and revision
        CLI->>C: premigration-1 manifest with SHA-256 and fsync
        CLI->>DB: Alembic upgrade head and require_schema
        alt Success
            CLI-->>U: migrated, previous and final revision, snapshot path
            U->>U: Start serve explicitly
        else Failure
            CLI-->>U: Diagnostic, database and snapshot kept
            Note over U,C: Manual inspection, no automatic restore, deletion or retry
        end
    end
```

`--writers-stopped` also declares that no idle service without a persisted owner remains: there is no global process
discovery. The liveness check uses the same cooperative identities as backup; it does not kill processes or infer
their death from a lease. Global configurations are not explored and checkouts are not touched. The folder is created
only when a copy is needed; snapshot names are exclusive, with mode 0600. Paths are absolute and without links,
including auxiliary files and components. The snapshot contains SQLite only, not agent streams or other artifacts; it
does not replace `backup-create` and is not a query-only restore. Restored query-only databases are refused.

If the copy or its seal fails, Alembic is not called; partial files are kept. If the migration fails, the resulting
state and the earlier copy are kept, without hiding changes through an automatic restore. The operator keeps writers
stopped during the whole operation. Earlier histories and snapshots are preserved; revision `0023` fills the derived
run projection by reading history formats 1–8. Revision `0028` only creates the P001 accounting tables: it never
backfills, reprices or reads streams, and its downgrade refuses while accounting rows exist. Accounting backfill and
repricing are separate explicit, previewed CLI operations ([accounting flow](metrics-accounting.md)).

`scripts/dev` uses the same preparation for its development database: it may create it and keeps its own snapshot
location. It shares the extended owner and group checks and the verified snapshot, without the installed CLI's
arguments.

## Source

- `storage/migrate.py`, `cli.py` (`migrate`), `scripts/dev`.
