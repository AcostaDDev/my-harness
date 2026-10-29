# Data diagram — my_harness

SQLite schema of the local service: Alembic head `0032_operation_journal`, 76 tables, defined in
`src/my_harness/storage/models.py`. Any change to the models or migrations updates this document in the same task
(parity rule, [D088](DECISIONS.md#d088--unified-documentation-contract)).

Conventions: `PK` primary key, `FK` declared foreign key, `UK` single-column uniqueness; "null" marks optional
columns. Composite uniqueness and partial unique indexes are listed under each diagram. Entities from another
context appear only with the columns that relate them. Heavy artifacts (agent streams, captures, copies) live outside
SQLite and are referenced by path and hash.

## Previous-harness compatibility and simulations

Compatibility tables kept after the previous harness support was retired
([D161](DECISIONS.md#d161--retirement-of-the-previous-harness-support)). There is no active indexer, viewer or
observer; an earlier `watch_enabled` value is inert. `simulations` holds the engine's own synthetic skeleton. The
retirement changed no table or Alembic revision ([compatibility flow](flows/legacy-compatibility.md)).

```mermaid
erDiagram
    simulations {
        string id PK
        string title
        string created_at
        json events
    }
    legacy_sources {
        string root PK
        string observed_at
        boolean watch_enabled
        text diagnostic "null"
    }
    legacy_runs {
        string root PK, FK "→ legacy_sources.root"
        string path PK
        string identity
    }
    legacy_artifacts {
        string root PK, FK "→ legacy_sources.root, legacy_runs.root"
        string path PK
        string run_path FK "null; → legacy_runs.path"
        string kind
        string format
        string status
        string sha256 "null"
        integer size_bytes "null"
        json payload "null"
        text diagnostic "null"
    }
    legacy_events {
        integer id PK
        string root FK "→ legacy_sources.root"
        string kind
        string observed_at
        json payload
    }
    legacy_sources ||--o{ legacy_runs : "root"
    legacy_sources ||--o{ legacy_artifacts : "root"
    legacy_runs |o--o{ legacy_artifacts : "root, run_path"
    legacy_sources ||--o{ legacy_events : "root"
```

## Managed execution

Operational authority for runs, attempts, the job queue, exclusion per checkout, processes and commits.
`managed_runs.root` is the canonical root of the checkout; there is no project table in this context.

CLI compatibility ([D174](DECISIONS.md#d174--automatic-clients-and-conditional-compatibility)) uses no extra
tables, only the JSON columns: `versions_json` freezes the observed CLI version, `reviewer_cli_launch_sha256` and
`executor_cli_launch_sha256`, the policy hash and, with `local-config-7`/`8`, the automatic provenance or explicit
assertion and the explicit PATH or executable path. `managed_processes.spec.preflight_observed` keeps the diagnostic,
minimum, launch fingerprint and conditional profile of each attempt. A refusal before the target starts has
`launch_permitted=false`, a null process identity and a `refused` capture; if a group was already waiting for GO, its
observed stop is recorded. Fields absent from older histories stay absent and are never back-filled
([flow](flows/cli-compatibility.md)).

```mermaid
erDiagram
    managed_runs {
        string id PK
        string root
        string task_id
        string phase_id "→ managed_phases.id (logical, no FK)"
        text context_json
        text versions_json
        text history_json
        string status
        string stage
        integer revisions
        integer revision_limit
        integer version
        string created_at
        string updated_at
        string purpose
    }
    managed_attempts {
        string id PK
        string run_id FK "→ managed_runs.id"
        integer number
        text request_json
        text versions_json
        string status
        text result_json "null"
        string started_at
        string finished_at "null"
        json language_context "null; copy of the job's (0025)"
    }
    managed_events {
        integer id PK
        string run_id FK "→ managed_runs.id"
        integer sequence
        string kind
        string recorded_at
        json payload
    }
    managed_jobs {
        integer id PK
        string idempotency_key UK
        string run_id FK "→ managed_runs.id"
        text request_json
        string status
        string owner_token "null"
        string heartbeat_at "null"
        string lease_until "null"
        string created_at
        string finished_at "null"
        text diagnostic "null"
        json process_owner "null"
        boolean owner_closed
        string activation_id FK "null; → managed_activations.id"
        json language_context "null; ui-language-1 (0024) | language-context-1 (0025)"
    }
    checkout_locks {
        string root PK
        integer job_id FK, UK "null; → managed_jobs.id"
        string preparation_id FK, UK "null; → project_preparation_operations.id"
    }
    managed_processes {
        string id PK
        string attempt_id FK, UK "null; → managed_attempts.id"
        integer job_id FK "null; → managed_jobs.id"
        string preparation_id FK "null; → project_preparation_operations.id"
        json spec
        json identity "null"
        string status
        json capture "null"
    }
    managed_commits {
        string operation_id PK
        string run_id FK "→ managed_runs.id"
        integer job_id FK "→ managed_jobs.id"
        string status
        string base_revision
        string reviewed_fingerprint
        string expected_tree
        string expected_commit
        text intent_json
        text result_json "null"
        string commit_sha "null"
        string created_at
        string finished_at "null"
    }
    managed_activations {
        string id PK
        string root
        string repository_key "null"
        string status
        string preview_sha256
        text legacy_stopped
        text rules_json
        text marker
        string marker_sha256
        string snapshot_root
        text manifest_json "null"
        string manifest_sha256 "null"
        string owner_token "null"
        integer version
        string created_at
        string activated_at "null"
        string finished_at "null"
        text diagnostic "null"
        text revert_reason "null"
        string export_path "null"
        string export_sha256 "null"
    }
    managed_runs ||--o{ managed_attempts : "run_id"
    managed_runs ||--o{ managed_events : "run_id"
    managed_runs ||--o{ managed_jobs : "run_id"
    managed_activations |o--o{ managed_jobs : "activation_id"
    managed_jobs |o--o{ checkout_locks : "job_id"
    managed_attempts |o--o| managed_processes : "attempt_id"
    managed_jobs |o--o{ managed_processes : "job_id"
    managed_runs ||--o{ managed_commits : "run_id"
    managed_jobs ||--o{ managed_commits : "job_id"
```

Uniqueness: `managed_attempts` (run_id, number); `managed_events` (run_id, sequence); `uq_managed_commits_live` on `managed_commits` (run_id) where status IN ('INTENT', 'COMMITTED'); `uq_managed_activations_live_root` on `managed_activations` (root) where status IN ('PREPARING', 'ACTIVE', 'REVERTING'); `uq_managed_activations_live_repository` on `managed_activations` (repository_key) where status IN ('PREPARING', 'ACTIVE', 'REVERTING').

## Prompts and permissions

Prompt catalog versioned by scope, and exact permission requests with their consumption.

```mermaid
erDiagram
    prompt_heads {
        string scope PK
        string owner PK
        string name PK
        integer generation
        string active_id "null"
    }
    prompt_versions {
        string id PK
        string scope
        string owner
        string name
        text template
        string sha256
        text source
        string created_at
    }
    prompt_activations {
        string id PK
        string scope
        string owner
        string name
        string previous_id "null"
        string version_id FK "→ prompt_versions.id"
        integer generation
        text reason
        string created_at
    }
    permission_requests {
        string id PK
        string run_id FK "→ managed_runs.id"
        integer version
        string status
        json request
        string fingerprint
        string expires_at
        string created_at
        json decision "null"
        string consumed_by "null"
        string supersedes FK "null; → permission_requests.id"
    }
    managed_runs {
        string id PK
    }
    prompt_versions ||--o{ prompt_activations : "version_id"
    managed_runs ||--o{ permission_requests : "run_id"
    permission_requests |o--o{ permission_requests : "supersedes"
```

## Phases and creation

Phases with a versioned definition, questions, operations (check, closure, transition, document edit),
authorizations and events ([D032](DECISIONS.md#d032--phases-in-sqlite-and-ready-bound-to-exact-content),
[D034](DECISIONS.md#d034--unattended-batches-versioned-definitions-and-deterministic-annotated-tags),
[D037](DECISIONS.md#d037--root-commit-intent-for-new-projects)). `managed_runs.phase_id` is a logical reference
without a foreign key.

```mermaid
erDiagram
    managed_phases {
        string id PK
        string root
        string code
        json definition
        string definition_sha256
        json documents
        string status
        integer version
        string created_at
        string updated_at
        integer definition_number
    }
    phase_definitions {
        string id PK
        string phase_id FK "→ managed_phases.id"
        integer number
        json definition
        string definition_sha256
        json documents
        string origin
        text reason "null"
        json actor "null"
        string created_at
    }
    phase_questions {
        string id PK
        string phase_id FK "→ managed_phases.id"
        text text
        json source
        string status
        json answer "null"
        integer version
        string created_at
    }
    phase_operations {
        string id PK
        string phase_id FK "→ managed_phases.id"
        string kind
        string run_id FK "null; → managed_runs.id"
        string status
        string previous_status
        json request
        json result "null"
        string created_at
        string finished_at "null"
    }
    phase_authorizations {
        string id PK
        string phase_id FK "→ managed_phases.id"
        string kind
        string status
        json scope
        string fingerprint
        json actor
        text reason
        string expires_at
        string created_at
        json closed "null"
        integer version
    }
    phase_events {
        integer id PK
        string phase_id FK "→ managed_phases.id"
        integer sequence
        string kind
        string recorded_at
        json payload
    }
    project_bootstraps {
        string id PK
        string root UK
        string run_id FK, UK "→ managed_runs.id"
        string phase_id FK "null; → managed_phases.id"
        string status
        json preview
        json intent
        json decision
        json result "null"
        string created_at
        string finished_at "null"
    }
    managed_runs {
        string id PK
        string phase_id "→ managed_phases.id (logical, no FK)"
    }
    managed_phases |o..o{ managed_runs : "phase_id (logical)"
    managed_phases ||--o{ phase_definitions : "phase_id"
    managed_phases ||--o{ phase_questions : "phase_id"
    managed_phases ||--o{ phase_operations : "phase_id"
    managed_runs |o--o{ phase_operations : "run_id"
    managed_phases ||--o{ phase_authorizations : "phase_id"
    managed_phases ||--o{ phase_events : "phase_id"
    managed_runs ||--o{ project_bootstraps : "run_id"
    managed_phases |o--o{ project_bootstraps : "phase_id"
```

Uniqueness: `managed_phases` (root, code); `uq_managed_phases_open_root` on `managed_phases` (root) where status NOT IN ('CLOSED', 'ABANDONED'); `phase_definitions` (phase_id, number); `phase_events` (phase_id, sequence).

## Chat and conversational planning

Project chat ([D035](DECISIONS.md#d035--chat-as-new-read-only-turns-with-confirmed-proposals),
[D083](DECISIONS.md#d083--chat-over-a-head-snapshot-in-its-own-lane)), definition conversations and phase
planning ([D075](DECISIONS.md#d075--conversational-creation-and-planning-with-drafts-on-disk)). Onboarding
(`kind = 'onboarding'`, [D102](DECISIONS.md#d102--onboarding-by-reverse-engineering-over-head-with-private-drafts))
uses the `source` column to freeze the inventory, HEAD and tree, and `onboarding-drafts/<id>/` next to the database
for its drafts; `managed_runs.purpose = 'onboarding'` links its turns to the planning authority, and the export intent
is recorded in events before the effect. Conversations of the retired import flow (`kind = 'project_import'`) and
their `import-drafts/<id>/` folders are kept only as data: they are neither deleted nor executed again. The downgrade
guard of revision `0019` protects both sources.

```mermaid
erDiagram
    chat_conversations {
        string id PK
        string root
        string title
        string phase_id FK "null; → managed_phases.id"
        string task_run_id FK "null; → managed_runs.id"
        json actor
        integer version
        string created_at
        string updated_at
        string idempotency_key UK "null"
        string request_sha256 "null"
    }
    chat_turns {
        string id PK
        string conversation_id FK "→ chat_conversations.id"
        integer number
        string run_id FK, UK "→ managed_runs.id"
        string status
        text message
        json request
        string request_sha256
        json result "null"
        json actor
        string created_at
        string finished_at "null"
    }
    chat_proposals {
        string id PK
        string conversation_id FK "→ chat_conversations.id"
        string turn_id FK "→ chat_turns.id"
        integer number
        string status
        json proposal
        string proposal_sha256
        string run_id FK, UK "null; → managed_runs.id"
        json decision "null"
        integer version
        string created_at
    }
    planning_conversations {
        string id PK
        string root
        string kind
        string phase_id FK "null; → managed_phases.id"
        string title
        json brief "null"
        json known
        json deferred
        json log
        json actor
        integer version
        string created_at
        string updated_at
        string idempotency_key UK "null"
        string request_sha256 "null"
        json source "null"
    }
    planning_turns {
        string id PK
        string conversation_id FK "→ planning_conversations.id"
        integer number
        string run_id FK, UK "→ managed_runs.id"
        string status
        text message
        json request
        string request_sha256
        json result "null"
        json actor
        string created_at
        string finished_at "null"
    }
    planning_proposals {
        string id PK
        string conversation_id FK "→ planning_conversations.id"
        string turn_id FK "→ planning_turns.id"
        integer number
        string kind
        string path "null"
        text content
        text reason
        string content_sha256
        string base_sha256 "null"
        string proposal_sha256
        string status
        json decision "null"
        integer version
        string created_at
    }
    managed_runs {
        string id PK
    }
    managed_phases {
        string id PK
    }
    managed_phases |o--o{ chat_conversations : "phase_id"
    managed_runs |o--o{ chat_conversations : "task_run_id"
    chat_conversations ||--o{ chat_turns : "conversation_id"
    managed_runs ||--o{ chat_turns : "run_id"
    chat_conversations ||--o{ chat_proposals : "conversation_id"
    chat_turns ||--o{ chat_proposals : "turn_id"
    managed_runs |o--o{ chat_proposals : "run_id"
    managed_phases |o--o{ planning_conversations : "phase_id"
    planning_conversations ||--o{ planning_turns : "conversation_id"
    managed_runs ||--o{ planning_turns : "run_id"
    planning_conversations ||--o{ planning_proposals : "conversation_id"
    planning_turns ||--o{ planning_proposals : "turn_id"
```

Uniqueness: `uq_chat_conversations_key` on `chat_conversations` (idempotency_key); `chat_turns` (conversation_id, number); `uq_chat_turns_pending` on `chat_turns` (conversation_id) where status = 'QUEUED'; `chat_proposals` (conversation_id, number); `uq_planning_conversations_key` on `planning_conversations` (idempotency_key); `uq_planning_definition` on `planning_conversations` (root) where kind = 'definition'; `planning_turns` (conversation_id, number); `uq_planning_turns_pending` on `planning_turns` (conversation_id) where status = 'QUEUED'; `planning_proposals` (conversation_id, number).

## Confirmed documentation commit of onboarding

`project_imports` keeps one operation per checkout and conversation: the full preview, the commit intent sealed
before the effect, the decision and the result. Onboarding reuses this table without new columns or indexes:
`preview.flow = "onboarding"` identifies the source; `preview.profile` and `profile_sha256` seal the composition
profile, and `decision.profile_sha256` records its confirmation. It keeps the shared purpose
`managed_runs.purpose = 'import_commit'`; the conversation keeps `kind = 'onboarding'`. Job, lock, lease and recovery
are those of `managed_jobs`. Phase `P001` and its document baseline are inserted in the same transaction as the
result and the end of the job. An `INTERRUPTED` status keeps the intent and blocks new work until it is reconciled.

```mermaid
erDiagram
    project_imports {
        string id PK
        string root UK
        string conversation_id FK, UK
        string run_id FK, UK
        string phase_id FK "null"
        string status
        json preview
        text intent
        json decision
        json result "null"
        string created_at
        string finished_at "null"
    }
    planning_conversations ||--o| project_imports : "conversation_id"
    managed_runs ||--o| project_imports : "run_id"
    managed_phases |o--o{ project_imports : "phase_id"
```

## Metrics and project registry

Per-attempt metrics with provenance ([D074](DECISIONS.md#d074--per-attempt-metrics-with-provenance-and-no-double-counting))
and project registration from the UI ([D078](DECISIONS.md#d078--local-config-3-and-registration-from-the-ui)).
With `local-config-5` and later, the JSON `row` of the registry row and its events can carry `agent_selection`:
`reviewer = {preset_id, model, effort}` and `executor = {preset_id}`; the executor catalog and mode stay in
`row.policy`. A new registry version, its event and the invalidation of proposed phase plans are atomic; only the
proposal's status, version and decision change, never the turn's request or result nor the run snapshots. A row
without a selection keeps the reviewer/executor pair of the TOML ([agents flow](flows/project-agents.md)).

```mermaid
erDiagram
    attempt_metrics {
        string attempt_id PK, FK "→ managed_attempts.id"
        string run_id FK "→ managed_runs.id"
        integer number
        string root
        string phase_code
        string task_id
        string purpose
        string role
        string provider "null"
        string adapter_version "null"
        string cli_version "null"
        string requested_model "null"
        string requested_effort "null"
        json reported_models "null"
        string reported_effort "null"
        string status
        text error "null"
        string verdict "null"
        integer executor_round
        string accounting "null"
        string input_semantics "null"
        integer input_tokens "null"
        integer cache_read_tokens "null"
        integer cache_write_tokens "null"
        integer output_tokens "null"
        integer reasoning_tokens "null"
        integer uncached_input_tokens "null"
        integer total_tokens "null"
        integer turns "null"
        integer tool_calls "null"
        json tools "null"
        integer permission_denials "null"
        integer wall_ms "null"
        integer duration_ms "null"
        integer api_duration_ms "null"
        float cost_usd "null"
        string started_at
        string finished_at "null"
        string day
        string source
        string normalization "null"
        string catalog
        json provenance
        json diagnostics
        string recorded_at
    }
    attempt_model_metrics {
        string attempt_id PK, FK "→ attempt_metrics.attempt_id"
        string model PK
        integer input_tokens "null"
        integer cache_read_tokens "null"
        integer cache_write_tokens "null"
        integer output_tokens "null"
        integer reasoning_tokens "null"
        float cost_usd "null"
    }
    registered_projects {
        string id PK
        string creation_id FK, UK "null; → project_creation_operations.id"
        integer version
        string status
        string root
        string composition
        string profile
        json row
        string row_sha256
        json trust
        string created_at
        string updated_at
    }
    registered_project_events {
        integer id PK
        string project_id FK "→ registered_projects.id"
        integer version
        string action
        json row
        string row_sha256
        string previous_sha256 "null"
        string preview_sha256
        json actor
        text reason "null"
        string recorded_at
    }
    managed_attempts {
        string id PK
    }
    managed_runs {
        string id PK
    }
    managed_attempts ||--o| attempt_metrics : "attempt_id"
    managed_runs ||--o{ attempt_metrics : "run_id"
    attempt_metrics ||--o{ attempt_model_metrics : "attempt_id"
    registered_projects ||--o{ registered_project_events : "project_id"
```

Uniqueness: `ix_attempt_metrics_run` on `attempt_metrics` (run_id, number); `uq_registered_projects_active_root` on `registered_projects` (root) where status = 'ACTIVE'; `registered_project_events` (project_id, version).

## Projects folder and creation of new projects

The projects folder chosen in the UI ([D116](DECISIONS.md#d116--creation-authority-per-project-presets-and-separate-preparation))
authorizes new direct children; it does not widen the TOML registration roots. The singleton row does not exist
until the first selection. Root events keep a snapshot of each revision, without a foreign key to a mutable row as
proof of authority. The intent is sealed before `mkdir`; the child's identity is recorded only after the parent is
synced. Registration, its event, `creation_id` and the `REGISTERED` result are committed together. Creation
operations have no jobs, agents or processes; recipe preparation is recorded separately (below).

```mermaid
erDiagram
    project_creation_root {
        integer id PK "singleton; CHECK id = 1"
        integer version
        string status
        string path "null"
        json identity "null; device, inode"
        string row_sha256
        string updated_at
    }
    project_creation_root_events {
        integer id PK
        integer version UK
        string idempotency_key UK
        string request_sha256
        json payload "before, after, preview, actor, reason, date and hashes"
    }
    project_creation_operations {
        string id PK
        string idempotency_key UK
        string request_sha256
        integer version
        string project_id
        string directory_name
        string target
        boolean reserved
        json authority "current authorized revision; original intent intact"
        json intent
        string intent_sha256
        string status
        json child_identity "null"
        json result "null"
        text diagnostic "null"
        string created_at
        string updated_at
    }
    project_creation_operation_events {
        integer id PK
        string operation_id FK
        integer version
        string idempotency_key UK "null; resume/cancel"
        string request_sha256 "null"
        json payload "snapshot, transition, actor, date and hash chain"
    }
    registered_projects {
        string id PK
        string creation_id FK, UK "null; earlier rows kept"
    }
    project_creation_root ||..o{ project_creation_root_events : "logical revision"
    project_creation_root ||..o{ project_creation_operations : "frozen logical authority"
    project_creation_operations ||--o{ project_creation_operation_events : "operation_id"
    project_creation_operations |o--o| registered_projects : "creation_id"
```

Uniqueness: `uq_creation_reserved_id` on (project_id) and `uq_creation_reserved_target` on (target) where
reserved = 1; `project_creation_operation_events` (operation_id, version); `uq_registered_creation` on
registered_projects (creation_id). Reservations are checked transactionally against registry rows and nested
targets, including case-insensitive physical aliases; the textual indexes do not replace that check. `REGISTERED`
releases the operation's reservation and the registry row takes over; `CANCELLED` releases it only when the
absence of the folder is proven. Reservations do not expire by timeout. Authority changes, withdrawal and short
effects share the SQLite write exclusion ([creation flow](flows/project-creation.md)).

## Recipe preparation

[D119](DECISIONS.md#d119--django-recipe-preparation) and [D143](DECISIONS.md#d143--typescript-web-recipe-1). A
prior intent and a single reservation per checkout; confirmation and job admission or registration share the
SQLite transaction. No fictitious run or attempt is created. Captures and prepared bytes stay inside SQLite, with no
new external artifacts for backup or retention. The receipt is adopted only together with `COMPLETED` and the
release of the lock; its SHA-256 is frozen in later jobs as `project_environment_sha256`.

```mermaid
erDiagram
    project_preparation_operations {
        string id PK
        string project_id FK "→ registered_projects.id"
        string root
        string idempotency_key UK
        string request_sha256
        string previous_id FK "null; → project_preparation_operations.id"
        integer version
        string status
        boolean reserved
        json plan
        string plan_sha256
        string owner_token "null"
        string lease_until "null"
        json process_owner "null"
        boolean owner_closed
        boolean cancel_requested
        json commit_intent "null"
        json receipt "null"
        text diagnostic "null"
        string created_at
        string updated_at
    }
    project_preparation_steps {
        string id PK
        string operation_id FK
        integer number
        json spec
        string status
        json evidence "null; capture and snapshot of proven bytes"
    }
    project_preparation_events {
        integer id PK
        string operation_id FK
        integer version
        string kind
        json payload "actor, confirmation, process, capture or transition"
        string recorded_at
    }
    registered_projects ||--o{ project_preparation_operations : project_id
    project_preparation_operations |o--o{ project_preparation_operations : previous_id
    project_preparation_operations ||--o{ project_preparation_steps : operation_id
    project_preparation_operations ||--o{ project_preparation_events : operation_id
    project_preparation_operations |o--o| checkout_locks : preparation_id
    project_preparation_operations |o--o{ managed_processes : preparation_id
```

Uniqueness: `uq_preparation_reserved` on (root) where reserved = 1; steps (operation_id, number), events
(operation_id, version). A retry creates another linked operation and copies only the proven `DONE` prefix; the
rows and payloads of earlier attempts keep their bytes. The succession is audited and transfers the reservation.
Cancelling without effects releases the reservation; uncertain effects stay reserved, even without a live lock.
CAS controls store their key and hash in the event payload under the same SQLite exclusion, for replay.

`checkout_locks` keeps `root` as its primary key and requires exactly one owner (`job_id` or `preparation_id`). In
`managed_processes`, `id` replaced `attempt_id` as primary key: older rows keep `id = attempt_id`, its foreign key
and their job; for a preparation, `attempt_id` and `job_id` are null and `preparation_id` is required. A CHECK
constraint forbids empty or mixed owners. Downgrading past this revision is possible only without preparation
history; otherwise a query-only backup is used, without deleting evidence.

## Run projection

`run-projection-1` ([D144](DECISIONS.md#d144--run-projection-run-projection-1)): tables derived from
`managed_runs.history_json`, which remains the authority. They are written in the same transaction as the history,
and revision `0023_run_projection` filled them once by decoding each existing history (formats 1–8) without
modifying it. Run views only read these tables, and metrics and the export preview read them together with
`managed_attempts`; the engine, recovery, checks, chat and permissions keep reading the history. The `*_json`
columns hold the exact text of the history or frozen JSON. The reviewed diff is stored in fixed 64 KiB chunks
(`chunk` from 0). A backup recomputes every run and compares rows and counts; it never rebuilds them.

```mermaid
erDiagram
    run_projections {
        string run_id PK, FK "→ managed_runs.id"
        string projection "run-projection-1"
        string history_sha256 "of the text it was derived from"
        string history_status
        text task_json "null"
        integer attempts
        integer executor_attempts
        integer cycle_count
        integer stop_count
        text stop_stage "null; current stop"
        text stop_reason "null"
        text acceptance_json "null"
    }
    run_projection_stops {
        string run_id PK, FK "→ managed_runs.id"
        integer ordinal PK
        text stage
        text reason
    }
    run_projection_cycles {
        string run_id PK, FK "→ managed_runs.id"
        integer number PK
        text verdict "null"
        text fingerprint
        text changed_paths_json
        string diff_sha256
        integer diff_bytes
        text provenance_json "null"
        text review_json "null"
        text formatting_json "null"
        text validation_json "view without cases or diff"
        text validation_evidence_json
        text validation_run_id "null"
        text validation_source_attempt_id "null"
    }
    run_projection_diff_chunks {
        string run_id PK, FK "→ managed_runs.id"
        integer cycle PK
        integer chunk PK
        blob data "≤ 64 KiB of UTF-8 bytes"
    }
    run_projection_reports {
        string run_id PK, FK "→ managed_runs.id"
        integer cycle PK
        integer entry PK
        integer report PK
        text command_id "null"
        text summary_json
        text original_base64 "null"
        string sha256 "null"
        integer size_bytes "null"
        integer case_count
    }
    run_projection_cases {
        string run_id PK, FK "→ managed_runs.id"
        integer cycle PK
        integer entry PK
        integer report PK
        integer ordinal PK
        text case_json
    }
    managed_runs {
        string id PK
    }
    managed_runs ||--|| run_projections : "run_id"
    managed_runs ||--o{ run_projection_stops : "run_id"
    managed_runs ||--o{ run_projection_cycles : "run_id"
    managed_runs ||--o{ run_projection_diff_chunks : "run_id"
    managed_runs ||--o{ run_projection_reports : "run_id"
    managed_runs ||--o{ run_projection_cases : "run_id"
```

Composite primary keys fix a stable read order: stops by ordinal, cycles by number, chunks, reports and cases by
their indexes. The `cycle` of chunks, reports and cases is the cycle's `number`, without a declared foreign key.
Downgrade removes only these tables.

## Language preferences

One row per installation and database ([D166](DECISIONS.md#d166--global-language-preferences-and-catalogs)).
Revision `0024_product_preferences` creates it with `en`/`en` and version 1; reading it never creates or repairs it.
No foreign key: the rest of the schema only reads it when admitting a job.

```mermaid
erDiagram
    product_preferences {
        integer id PK "CHECK id = 1"
        string format "product-preferences-1"
        string ui_language "CHECK en | es"
        string default_work_language "CHECK en | es"
        integer version
        string updated_at
    }
    product_preference_events {
        integer id PK
        integer version UK
        string idempotency_key UK
        string request_sha256
        json payload "before, after, actor, recorded_at, previous_sha256, sha256"
    }
```

Each `PUT /api/managed/preferences` with the expected version increments `version` and appends an event chained by
hash; the same key with the same request returns the recorded result. `managed_jobs.language_context` seals
`{format: ui-language-1, ui_language, preferences_version}` in the transaction that admits the job; resuming a run
(retry, revalidation, bootstrap, import commit, export or document edit) copies the value of the run's first job,
null included. Jobs older than `0024` keep null ("not recorded"). Downgrade is refused when events exist; without
them every capture is the factory `en` and is dropped with the column ([flow](flows/language-preferences.md)).

## Work language per project

One row per canonical root ([D167](DECISIONS.md#d167--immutable-work-language-per-root-language-pair-per-job-and-attempt)),
written once and never updated or deleted. Revision `0025_project_work_languages` creates the table empty: earlier
projects have no confirmed work language and none is inferred. No foreign key: the root identifies the checkout even
if its registration is removed, changes id or the project comes from the TOML.

```mermaid
erDiagram
    project_work_languages {
        string root PK "canonical root"
        string format "work-language-1"
        string project_id "project that confirmed it"
        string work_language "CHECK en | es"
        string source "CHECK registration | creation | toml | migration"
        json confirmation "preview_sha256 or TOML hash, actor, reason, default and preferences version"
        string sha256 "row hash"
        string confirmed_at
    }
```

It is written in the transaction that confirms a registration (including the registration of a newly created
project), at startup from a `local-config-6`–`8` TOML that declares it, or by the explicit confirmation from absent to
a value. Another value for the same root is refused. Since `0025`, `managed_jobs.language_context` seals
`language-context-1` (`ui_language`, `preferences_version`, `work_language`, `work_language_source`,
`work_language_sha256`) when admitting each new job; without a row no new work is admitted.
`managed_attempts.language_context` copies the job's value when each attempt starts (null before `0025`). Downgrade
is refused when any row exists (an explicit confirmation cannot be represented earlier); without rows it drops the
table and the column ([flow](flows/project-work-language.md)).

## Versioned configuration

Alembic `0026_configuration` adds the three tables below; `0027_profile_proposals` makes registered-project
`composition` and `profile` nullable for documentary intake. `0028_usage_accounting` adds the
[accounting records](#p001-accounting-records) (**62 tables**).
References to saved/active/pending revisions are checked transactionally by the service; revision numbers are
scoped composite keys. The content authority is immutable private TOML, while SQLite owns executable references.

```mermaid
erDiagram
    configuration_scopes ||--o{ configuration_revisions : versions
    configuration_operations ||--o{ configuration_revisions : saves
    configuration_scopes {
        string scope PK
        string directory
        int version
        int saved_revision "nullable"
        int active_revision "nullable"
        int pending_revision "nullable"
        string pending_operation_id "nullable"
        string working_sha256 "nullable"
        string updated_at
    }
    configuration_revisions {
        string scope PK,FK
        int revision PK
        string sha256
        string status "DRAFT or VALIDATED"
        string operation_id FK
        string created_at
    }
    configuration_operations {
        string id PK
        string format
        string kind
        string status
        string idempotency_key UK
        string request_sha256
        json payload
        json result "nullable"
        string created_at
        string updated_at
    }
```

Operation states: INTENDED, FILES_WRITTEN, SAVED, RECOVERY_REQUIRED, CONFLICT, APPLIED. Kinds include SAVE,
ACTIVATE, PROMOTE, CANCEL, RECOVER and ASSIST. Intent records and exact request hashes precede file effects;
idempotent replay does not repeat commands or model calls. Assistance has its own process journal without a
fictitious managed run. Global SAVE can include derived project copies or a legacy-import provenance snapshot.
Activation records exact receipt evidence; it never rebuilds historical receipts. A live activation (D238) keeps
its set in `pending_revision`/`pending_operation_id` with `payload.apply = live` until the idle-boundary PROMOTE;
a candidate that no longer composes is withdrawn by a PROMOTE whose `result.state` is FAILED, with structured
corrections. No new table or column.

Profile proposals reuse planning proposals (`kind=profile`) with frozen binding/document evidence. Generic
preparation reuses project preparation operations/steps/receipts with a contract discriminator, not a task run.
New generic `plan`/`receipt` JSON includes optional `read_only_tool_links` (D247): an exact alias-path map with file-link
chain paths/text/modes and resolved executable/mode. Existing tool evidence owns the frozen executable hash.
D248 adds the optional inline `tool_link_policy = external-directories-1` marker; chain entries may bind external
directory aliases with `directory: true`. Historical JSON is not backfilled and retains its original link policy.
No table, column or migration changes.
Own configuration authority is in scope references, while nullable registry composition/profile marks intake.
Jobs seal project revision/hash and environment receipt in `versions_json`; earlier snapshots retain their bytes.
A backup inventory covers all three tables plus referenced configuration/evidence. Restore keeps the existing
query-only mark and execution disabled, without interpreting original paths as writable destinations.

## P001 accounting records

<a id="planned-p001-accounting-records-not-implemented"></a>
Alembic `0028_usage_accounting` (P001-T003, [D254–D257](DECISIONS.md#d254--native-invocation-accounting-and-immutable-evidence),
[D259](DECISIONS.md#d259--native-accounting-capture-frozen-revision-binding-and-format-3-archives)) adds eight tables;
62 tables at that revision (0.1.9). The migration only creates them: it never backfills or reprices,
and its downgrade refuses while any accounting row exists. Existing metrics, histories and configuration bytes are
unchanged. T004's bounded read-only queries/API (`storage/accounting_views.py`, D262) read these rows without a schema
change ([flow](flows/metrics-accounting.md)).

```mermaid
erDiagram
    usage_invocations {
        string id PK "source_kind:source_id"
        string source_kind "managed_attempt|preparation_step|configuration_assistance"
        string source_id
        string attempt_id FK "null; → managed_attempts.id"
        string run_id FK "null; → managed_runs.id"
        string preparation_id FK "null; → project_preparation_operations.id"
        string preparation_step_id FK "null; → project_preparation_steps.id"
        string operation_id FK "null; → configuration_operations.id"
        string request_id "null"
        string root "null"
        string project_id "null"
        string phase_code "null"
        string task_id "null"
        string purpose
        string role
        string agent "null"
        string requested_model "null"
        string requested_effort "null"
        json versions
        json binding "null; billing-binding-1"
        string binding_sha256 "null"
        string launch "pending|not_invoked|observed|unknown_execution"
        string outcome "null"
        string started_at
        string finished_at "null"
        string recorded_at
        string updated_at
    }
    usage_captures {
        integer id PK
        string invocation_id FK "→ usage_invocations.id"
        string version "usage-capture-1|legacy-metrics-1"
        string digest
        json document
        json evidence "null; usage-accounting-1"
        string evidence_digest "null"
        string source "capture|backfill"
        string recorded_at
    }
    usage_components {
        integer capture_id PK, FK "→ usage_captures.id"
        string key PK
        string grain "invocation_total|model_total|request"
        string parent_key "null"
        string inclusion "null"
        string reported_model "null"
        string model_source "null"
        string semantics "null"
        string coverage
        integer input_tokens "null"
        integer cache_read_tokens "null"
        integer cache_write_tokens "null"
        integer write_5m "null"
        integer write_1h "null"
        integer output_tokens "null"
        integer reasoning_tokens "null"
        json reasons
    }
    metrics_references {
        string id PK "SHA-256 of canonical content"
        string kind "model_identity|tariff|bundle"
        string format
        text content
        string source "packaged|import"
        string provider "null"
        string product "null"
        string model "null"
        string observed_at "null"
        string recorded_at
    }
    usage_valuations {
        string id PK "digest of the valuation identity"
        string invocation_id FK "→ usage_invocations.id"
        integer capture_id FK "→ usage_captures.id"
        string origin "admission|backfill|repricing"
        string normalization
        string calculator
        string profile_digest
        string reference_set_digest FK "→ metrics_references.id"
        string basis
        string scenario_digest
        string evidence_digest
        json scenario
        string status "complete|incomplete|unsupported"
        string unit
        string scheme
        string amount "null; decimal string"
        string known_subtotal "null; decimal string"
        text exact_sum "null"
        text rounding_adjustment "null"
        boolean counterfactual
        boolean retrospective
        json reasons
        json warnings
        json selected_components
        json discrepancy "null"
        string supersedes FK "null; → usage_valuations.id"
        string recorded_at
    }
    usage_valuation_lines {
        string valuation_id PK, FK "→ usage_valuations.id"
        integer number PK
        string component_key
        string category
        integer quantity
        json rate
        json factors
        json included_adjustments
        string tariff_reference FK "→ metrics_references.id"
        string identity_reference FK "null; → metrics_references.id"
        string rate_case
        text exact_amount
    }
    valuation_cohorts {
        string id PK
        string name UK
        string kind "backfill|repricing"
        string idempotency_key UK
        string request_sha256
        json selection "frozen members"
        string selection_digest
        json scenario "null"
        string scenario_digest "null"
        string reference_set_digest FK "null; → metrics_references.id"
        string status "BUILDING|CLOSED"
        integer expected
        integer built
        string cursor "null"
        json report "null"
        string created_at
        string closed_at "null"
    }
    valuation_cohort_members {
        string cohort_id PK, FK "→ valuation_cohorts.id"
        string invocation_id PK, FK "→ usage_invocations.id"
        string basis PK
        string valuation_id FK "null; → usage_valuations.id"
        string reason "null"
        string recorded_at
    }
    usage_invocations ||--o{ usage_captures : "invocation_id"
    usage_captures ||--o{ usage_components : "capture_id"
    usage_invocations ||--o{ usage_valuations : "invocation_id"
    usage_captures ||--o{ usage_valuations : "capture_id"
    usage_valuations ||--o{ usage_valuation_lines : "valuation_id"
    metrics_references ||--o{ usage_valuations : "reference_set_digest"
    metrics_references ||--o{ usage_valuation_lines : "tariff/identity"
    valuation_cohorts ||--o{ valuation_cohort_members : "cohort_id"
    usage_invocations ||--o{ valuation_cohort_members : "invocation_id"
    usage_valuations ||--o{ valuation_cohort_members : "valuation_id"
```

Uniqueness: `usage_invocations` (source_kind, source_id); `usage_captures` (invocation_id, version, digest);
`usage_valuations` (invocation_id, capture_id, normalization, calculator, profile_digest, reference_set_digest,
basis, scenario_digest). Indexes: `ix_usage_invocations_scope` (root, phase_code, task_id) and
`ix_usage_invocations_started` (started_at). Checks: source kind and launch vocabularies; the native link must match
the source kind (`attempt_id = source_id` with a run, `preparation_step_id = source_id` with its operation, or
`operation_id = source_id`); valuation status/origin; cohort kind/status; a member has exactly one of a valuation or
an explicit reason.

- An invocation is written with its native intent (attempt row, preparation `executor_intended`, assistance
  INTENDED operation) and settled in the transaction that records the native result/capture. Lifecycle columns may
  advance; captures, components, references, valuations, lines and closed memberships are append-only.
- `binding` dereferences only the immutable configuration revision frozen at admission (`billing-binding-1`,
  [D259](DECISIONS.md#d259--native-accounting-capture-frozen-revision-binding-and-format-3-archives)); null means no
  billing-capable format was frozen. Global `local-config-10` owns `billing.profiles`/`billing.defaults`;
  `project-config-2` may select profiles per configured role. Both are explicit new formats; v9/v1 keep their bytes.
- References are content-addressed canonical JSON. A valuation stores its scenario, digests, exact sum and rounded
  decimal strings; never SQLite REAL. Admission-bound valuations (`origin = admission`) are the default selection;
  backfill/repricing values are only reachable through an explicit cohort membership.
- Retention removes authorized stream bytes only; these rows never depend on them. Backup format 3 recomputes all
  digests and the exact line sums in the same snapshot; an older-schema bundle needs the explicit upgraded copy.

## P002 graph continuations

LangGraph continuation storage owned by the harness saver
([D282](DECISIONS.md#d282--harness-checkpoint-saver-and-continuationjournal-consistency-contract),
[D283](DECISIONS.md#d283--durable-segments-graph-version-stamping-and-quarantine); migration
`0029_graph_continuations`). Routing progress only: the domain records stay the authority and no table here copies
tasks, grants or policy. No product graph writes these tables yet; P002-T003 exercises them with synthetic graphs.

```mermaid
erDiagram
    graph_threads {
        string id PK
        string graph_id
        string graph_version
        string fingerprint
        string status
        int segments
        string reason "null; code"
        json detail "null"
        string created_at
        string updated_at
    }
    graph_checkpoints {
        string thread_id PK, FK "→ graph_threads.id"
        string checkpoint_ns PK
        string checkpoint_id PK
        string parent_checkpoint_id "null"
        string checkpoint_type
        bytes checkpoint
        string metadata_type
        bytes metadata_value
        string created_at
    }
    graph_checkpoint_writes {
        string thread_id PK, FK "→ graph_threads.id"
        string checkpoint_ns PK
        string checkpoint_id PK
        string task_id PK
        int idx PK
        string channel
        string value_type
        bytes value
        string task_path
    }
    graph_threads ||--o{ graph_checkpoints : "thread_id"
    graph_threads ||--o{ graph_checkpoint_writes : "thread_id"
```

Index: `ix_graph_threads_status` (status). Check: `status` in `RUNNING`, `WAITING`, `COMPLETED`, `CANCELLED`,
`REVOKED`, `QUARANTINED`, `RECOVERY_REQUIRED`, `FAILED`.

- A thread row is stamped by the runner before any checkpoint (foreign key); status changes are compare-and-set.
- Checkpoints are immutable strict-serializer bytes; a second put of the same id must carry identical bytes. Writes
  of one task are kept once per index; LangGraph's special channels (error, interrupt, resume, scheduled) replace
  their own row.
- Downgrade below 0029 is refused while any row exists. Backups copy the tables with the database; a query-only
  restore refuses every runner write.

## P002 structured knowledge

Project knowledge with stable identities, immutable versions and accepted revisions
([D284](DECISIONS.md#d284--structured-knowledge-entities-revisions-and-immutability),
[D285](DECISIONS.md#d285--canonical-database-instructions-and-generated-instruction-files); migration
`0030_structured_knowledge`, no backfill). A revision is the complete manifest of members and links. Product paths
write these tables only through the P002-T005 domain service ([below](#p002-domain-command-outcomes)), so far reached
by the owner API and synthetic graphs. `knowledge_projects.root` relates to the
roots of the managed tables logically, without a foreign key.

```mermaid
erDiagram
    knowledge_projects {
        string id PK
        string root UK
        string created_at
    }
    knowledge_items {
        string id PK
        string project_id FK "→ knowledge_projects.id"
        string kind
        string document "null; sections only"
        string code
        string created_at
    }
    knowledge_item_versions {
        string id PK
        string item_id FK "→ knowledge_items.id"
        integer number
        json content
        string content_sha256
        string provenance
        json source "null"
        string created_at
    }
    knowledge_revisions {
        string id PK
        string project_id FK "→ knowledge_projects.id"
        string base_revision_id FK "null; (project_id, base_revision_id) → knowledge_revisions"
        string status
        integer number "null until accepted"
        string knowledge_sha256 "null until accepted"
        string revision_sha256 "null until accepted"
        string origin "null until accepted"
        json actor "null until accepted"
        text reason "null"
        json changes "null until accepted"
        string created_at
        string closed_at "null while draft"
    }
    knowledge_revision_members {
        string revision_id PK, FK "(project_id, revision_id) → knowledge_revisions"
        string item_id PK, FK "(project_id, item_id) → knowledge_items"
        string project_id
        string version_id FK "(item_id, version_id) → knowledge_item_versions"
        integer root_position "null; root sections only"
    }
    knowledge_revision_links {
        string revision_id PK, FK "→ knowledge_revision_members"
        string kind PK
        string source_item_id PK, FK "(revision_id, source_item_id) → knowledge_revision_members"
        string target_item_id PK, FK "(revision_id, target_item_id) → knowledge_revision_members"
        integer position "null; ordered kinds only"
        string qualifier "null; supersedes only"
    }
    knowledge_identity_map {
        string project_id PK, FK "(project_id, item_id) → knowledge_items"
        string legacy_kind PK
        string legacy_ref PK
        string item_id FK
        string legacy_sha256 "null"
        string created_at
    }
    knowledge_projects ||--o{ knowledge_items : "project_id"
    knowledge_projects ||--o{ knowledge_revisions : "project_id"
    knowledge_items ||--o{ knowledge_item_versions : "item_id"
    knowledge_revisions |o--o{ knowledge_revisions : "base_revision_id"
    knowledge_revisions ||--o{ knowledge_revision_members : "revision_id"
    knowledge_items ||--o{ knowledge_revision_members : "item_id"
    knowledge_item_versions ||--o{ knowledge_revision_members : "version_id"
    knowledge_revision_members ||--o{ knowledge_revision_links : "source / target"
    knowledge_items ||--o{ knowledge_identity_map : "item_id"
```

Uniqueness: `knowledge_items` (project_id, id); `uq_knowledge_items_code` on `knowledge_items` (project_id, kind,
code) where document IS NULL; `uq_knowledge_items_section` on `knowledge_items` (project_id, document, code) where
kind = 'section'; `knowledge_item_versions` (item_id, number) and (item_id, id); `knowledge_revisions` (project_id,
id); `uq_knowledge_revisions_number` (project_id, number), `uq_knowledge_revisions_base` (project_id,
base_revision_id) and `uq_knowledge_revisions_root` (project_id) where status = 'ACCEPTED' (the last two split by
base present/absent); `uq_knowledge_links_order` on `knowledge_revision_links` (revision_id, kind, target_item_id,
position) where position IS NOT NULL.

Checks: `kind` in `requirement`, `criterion`, `phase`, `task`, `decision`, `section`; only sections have a `document`,
in `specification`, `architecture`, `data_model`, `flows`, `instructions`; `provenance` in `known`, `inferred`,
`unknown`; revision `status` in `DRAFT`, `ACCEPTED`, `DISCARDED`, with number, hashes, origin (`owner_confirmed`,
`owner_delegated`, `harness_deterministic`), actor, changes and `closed_at` exactly when accepted; link `kind` in
`part_of`, `criterion_of`, `depends_on`, `addresses`, `supersedes`, never a self-link, a position exactly for
`part_of`/`criterion_of` and a qualifier (`full`, `partial`) exactly for `supersedes`; `legacy_kind` in
`managed_phase`, `phase_task`, `decision_heading`, `document_section`.

- **Triggers (21).** Projects, items, versions and identity mappings are insert-only and refuse an insert over an
  existing key, so REPLACE and upsert cannot substitute a row. Revisions are inserted as `DRAFT` on an accepted base,
  change once to `ACCEPTED` (number = base number + 1) or `DISCARDED`, and are never deleted. Members and links change
  only while their revision is a draft, checked on the old and the new revision. The schema check, backups, bundle
  verification and restore compare the trigger set with a fixed digest (shared with the 0031 and 0032 triggers).
- Content (`knowledge-content-1`), relationship and order rules and the canonical hashes are checked by the
  repository at adoption and again on every retrieval, together with the chain to the root revision.
- Downgrade below 0030 is refused while any row exists. Backups copy the tables and triggers with the database; a
  query-only restore refuses every repository write.

## P002 domain command outcomes

One row per accepted typed domain command, written in the mutation's own transaction, and one per recorded refusal
([D286](DECISIONS.md#d286--typed-domain-operation-service-capability-policy-and-command-outcome-record); migration
`0031_domain_commands`, no backfill). The opener of a knowledge draft is its accepted `knowledge.draft.open` row.

```mermaid
erDiagram
    domain_commands {
        integer id PK
        string command_id UK
        string knowledge_project_id FK "null for refusals before a project; → knowledge_projects.id"
        string operation_id
        integer operation_version
        string schema_sha256 "null when the operation is unknown"
        string catalogue_sha256
        string principal
        string channel
        json caller "role, invocation, attempt, thread, operation key, frozen revision"
        json actor
        string origin "null; adoptions"
        string scope "owner, harness:<thread>, invocation:<id>"
        string idempotency_key "null for refusals without a key"
        string request_sha256 "null"
        string outcome
        string refusal_code "null"
        json capability "null for refusals"
        json result "null for refusals"
        string draft_id FK "null; (knowledge_project_id, draft_id) → knowledge_revisions"
        string revision_id FK "null; (knowledge_project_id, revision_id) → knowledge_revisions"
        string recorded_at
    }
    knowledge_projects ||--o{ domain_commands : "knowledge_project_id"
    knowledge_revisions |o--o{ domain_commands : "draft_id / revision_id"
```

Uniqueness: `command_id`; `uq_domain_commands_key` (knowledge_project_id, scope, idempotency_key) where outcome =
'ACCEPTED'. Index `ix_domain_commands_draft` (draft_id, operation_id).

Checks: `principal` in `owner`, `harness`, `agent`; `channel` in `api`, `graph`, `internal`, `broker`; `origin` null or
one of the three knowledge origins; an `ACCEPTED` row has project, key, request hash, schema digest, capability and
result and no refusal code; a `REFUSED` row has a refusal code and no result, draft or revision. Null JSON values are
stored as SQL NULL.

- **Triggers (3).** Rows are insert-only: updates and deletes abort, and an insert over an existing id, command id or
  accepted (project, scope, key) aborts, so REPLACE cannot substitute an outcome. They join the knowledge triggers in
  the fixed digest compared by the schema check, backups, bundle verification and restore (24 triggers at 0031;
  27 with the trace-event triggers of 0032).
- Downgrade below 0031 is refused while any row exists. Backups copy the table; a query-only restore writes nothing,
  not even refusals.

## P002 operation journal and trace events

One recoverable operation per `OperationPort` key inside a graph thread and the ordered, deduplicated events of the
trace ([D287](DECISIONS.md#d287--operation-journal-granularity-and-recovery-contract); migration
`0032_operation_journal`, no backfill: 0.1.9 runs keep their own journals). The invocation is the existing
`usage_invocations` row; operations hold no usage amounts. `usage_invocations.operation_id` keeps its meaning
(`configuration_operations`).

```mermaid
erDiagram
    workflow_operations {
        string id PK
        string thread_id FK "→ graph_threads.id"
        string key "deterministic OperationPort key"
        string root "project root; fixed by the thread's first operation"
        string kind "domain_command, agent_invocation, sealed_effect"
        string parent_operation_id FK "null; → workflow_operations.id"
        string causation_event_id "null; trace_events.event_id"
        json origin "null; {kind, id} request reference"
        json refs "at most 32 string references of 200 characters"
        string request_sha256 "kind and refs"
        string status
        integer job_id FK "null; agent invocations; → managed_jobs.id"
        string owner_token "null; fencing token of the job"
        string command_id FK "null; → domain_commands.command_id"
        string attempt_id FK "null; → managed_attempts.id"
        string invocation_id FK "null; → usage_invocations.id"
        json result "null; verbatim, at most 16 KiB, no credentials"
        json error "null; code and reference"
        string created_at
        string updated_at
    }
    trace_events {
        integer id PK "global order"
        string event_id UK
        string dedupe_key UK
        string root "null for refusals without a project"
        string thread_id FK "null; → graph_threads.id"
        string operation_id FK "null; → workflow_operations.id"
        string invocation_id FK "null; → usage_invocations.id"
        string command_id FK "null; → domain_commands.command_id"
        string parent_event_id "null; previous event of the operation"
        string causation_id "null"
        string kind
        string source
        json payload "trace-payload-1: bounded and sanitized"
        string payload_sha256 "payload and links"
        boolean truncated
        integer redactions
        string recorded_at
    }
    trace_artifacts {
        string event_id PK "FK → trace_events.event_id"
        string sha256 PK "digest of content"
        integer size
        string media
        blob content "masked content the event offloaded"
    }
    graph_threads ||--o{ workflow_operations : "thread_id"
    workflow_operations |o--o{ workflow_operations : "parent_operation_id"
    domain_commands |o--o| workflow_operations : "command_id"
    managed_attempts |o--o| workflow_operations : "attempt_id"
    usage_invocations |o--o| workflow_operations : "invocation_id"
    managed_jobs |o--o{ workflow_operations : "job_id"
    workflow_operations |o--o{ trace_events : "operation_id"
    graph_threads |o--o{ trace_events : "thread_id"
    trace_events ||--o{ trace_artifacts : "event_id"
```

Uniqueness: (`thread_id`, `key`); `uq_workflow_operations_attempt` (attempt_id) where not null; `event_id`;
`dedupe_key`. Indexes `ix_workflow_operations_root` (root, thread_id), `ix_workflow_operations_status` (status),
`ix_trace_events_thread` (thread_id, id), `ix_trace_events_operation` (operation_id, id), `ix_trace_events_root`
(root, id).

Checks: `status` in `INTENDED`, `COMPLETED`, `FAILED`, `UNCERTAIN`, `ABANDONED`; an `agent_invocation` has attempt,
invocation, job and owner token; a `domain_command` has its command and is `COMPLETED`; `source` in `supplied`,
`reported`, `derived`, `measured`, `absent`.

- **Status is a projection.** Every transition is a compare-and-set that writes its `operation.<status>` event in the
  same transaction; the last such event rebuilds the status. Transitions: INTENDED → COMPLETED | FAILED | UNCERTAIN;
  UNCERTAIN → COMPLETED | FAILED (reconciled from the native source) | ABANDONED (owner).
- **Triggers (6).** Events and artifacts are insert-only: updates and deletes abort, and an insert over an existing
  event id, event key or (event, digest) aborts. They join the fixed trigger digest of the schema check, backups and
  restore (30 triggers).
- **Artifacts.** Strings over 1 KiB and payloads over 8 KiB of an event are stored, already masked, in
  `trace_artifacts` with the event (at most 1 MiB per event; more is refused). Every reference in a payload, and
  inside an offloaded `application/json` payload, has its row (checked at write and by backup verification); digest
  and size are verified on read and by backups.
- **Bounds.** `refs` (≤ 32 lowercase keys, printable string values ≤ 200 characters) and `origin` (`{kind, id}`) are
  validated before writing and never coerced; credential names and secret-looking values are refused.
- Downgrade below 0032 is refused while any row exists. Backups copy the three tables; a query-only restore serves
  the read-only trace routes and refuses every journal write.
