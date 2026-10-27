# Data diagram — my_harness

SQLite schema of the local service: Alembic head `0027_profile_proposals`, 54 tables, defined in
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
`composition` and `profile` nullable for documentary intake. Current head: `0027_profile_proposals`, **54 tables**.
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
Activation records exact receipt evidence; it never rebuilds historical receipts.

Profile proposals reuse planning proposals (`kind=profile`) with frozen binding/document evidence. Generic
preparation reuses project preparation operations/steps/receipts with a contract discriminator, not a task run.
Own configuration authority is in scope references, while nullable registry composition/profile marks intake.
Jobs seal project revision/hash and environment receipt in `versions_json`; earlier snapshots retain their bytes.
A backup inventory covers all three tables plus referenced configuration/evidence. Restore keeps the existing
query-only mark and execution disabled, without interpreting original paths as writable destinations.
