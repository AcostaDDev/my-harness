# OT001 — Live application of agent configuration

One-off task ([D237](../../DECISIONS.md#d237--one-off-development-queue-before-phase-work)). Design recorded in
[D238](../../DECISIONS.md#d238--live-configuration-switch-at-an-idle-boundary) before the runtime change; release
numbering in [D239](../../DECISIONS.md#d239--one-off-tasks-released-as-patch-versions).

## Problem

A global activation always recorded RESTART_REQUIRED: `ConfigurationSetup.start` read the active revision only at
startup and `ManagedRuntime` plus its writer/chat workers held the resulting composer, ports and writer
factories. Changing a timeout, model, executable or PATH needed a manual restart and a new login. An activation
with any pending work was refused outright, and nothing checked the candidate clients before the switch.

## Design

### Field classification

| Global field | Applied |
| --- | --- |
| `agents.*` (provider, model, effort, executable, `cli_version`, timeout, environment/PATH, tools) | live |
| `agent_presets.*`, `git.*`, `registration.*`, `profiles`, `compositions`, `recipes` | live |
| `service.supervisor`, `service.lease_seconds`, `service.poll_seconds` | live only while no worker thread runs (the switch then starts it); with a running worker: restart |
| `service.state_dir` | fixed at startup (already refused by the save) |
| listener host/port, database, configuration directory | startup arguments, not configuration fields |

A global activation is also restart-only while legacy authority is in use or a legacy import is being promoted
(its registry promotion stays a startup step, D228). Project-scope activations were already live; they now share
the boundary policy below. The activation preview lists `restart_fields`, so the reason is visible before
confirmation. There is still no HTTP restart endpoint and no software update.

### Preparation before the switch

The activation preview of a live candidate builds a complete staging runtime outside any write transaction:
the candidate global (or the current one, for a project-only set) is composed with the existing loader, both
global roles are preflighted with their exact executable, PATH and environment (D173/D174, version/help probes
only, no inference), and every ACTIVE registered project is recomposed with the candidate, including the private
project revisions of the activation set and their selected receipts. A failure is a 409
`live_configuration_refused` that names the project or role, the code and the setting to correct; a project
that already fails with the current authority is reported but does not block a fix. Nothing changes in SQLite
or in memory.

### Safe boundary

Waiting reasons (current work): unfinished jobs (QUEUED, ACTIVE, RECOVERY_REQUIRED) of both lanes, checkout
locks, reserved preparations, phase operations in QUEUED/INTENT/INTERRUPTED, reserved project creation,
unfinished documentary bootstrap/import commits, runs in ACCEPTANCE_READY, commit intents and unresolved
configuration assistance. With none, the confirmed activation applies immediately. Otherwise SQLite records the
pending references (existing `pending_revision`/`pending_operation_id` columns) with `apply: live`, the scope
status is APPLY_PENDING and the UI shows **Apply when current work finishes** with the reasons.

While pending, work continues with the active configuration: admitted jobs, executing calls (and their timeouts),
acceptance and commits keep their frozen versions; new admissions also use the active configuration until the
switch. Nothing is terminated, retried, advanced or rebound. Documentary conversations and chat/profile
proposals are not waiting reasons for a global switch: each later turn or accepted proposal is a new admission
that freezes the then-active configuration (generalizing D236), and phase-plan proposals keep their existing
explicit supersession. For project-scope activations the documentary barriers keep refusing as before.

### Switch and recovery

`ManagedRuntime.apply_pending` runs from the writer worker when it is idle, after a confirmation and on reads of
the configuration state, under a runtime lock. It rebuilds the staging runtime from the pending references; a
failure clears the pending references and records a PROMOTE operation with result FAILED, so the previous
authority stays active and the installation is never left on the candidate. Otherwise `promote_pending`
rechecks, in one write transaction, the pending set, the absence of waiting reasons and the activation
evidence, and publishes the active references. Until the staged objects are installed (configuration, project
map, unavailable projects, loaded reference, worker start), the existing write guard refuses every write because
SQLite's active revision differs from the loaded one; so new work can never be admitted with clients that
disagree with the active references. The worker loops read the factories through the runtime on each claim.

A crash before the promotion leaves the pending set; the restarted service loads the previous active revision and
the same boundary procedure applies it. A crash after the promotion loads the new active revision at startup.
Cancellation uses the existing CAS cancel for both kinds; a concurrent second activation is refused while one is
pending. Replays of activate/promote are idempotent by key.

## Implementation

- `storage/configuration.py`: `live()` marks ACTIVATE operations with `apply: live`; `_state` reports APPLY_PENDING
  for them; `_waiting`/`_roots`/`_live_blockers` split current work from documentary refusals (`_blockers` keeps the
  D222 restart path); `activate` records a global live set as pending and lets the runtime promote it (a project-only
  set still activates at once when idle); `promote_pending` accepts live sets without the restart assertion, rechecks
  waiting work and runs `on_commit` inside its transaction; `fail_pending` withdraws a set; `cancel_pending` covers
  both kinds; the save preview adds `removed_fields`. `ConfigurationConflict` carries optional `details`.
- `storage/registry.py`: `_documentary_blockers` extracted from `_configuration_blockers` (unchanged behavior).
- `storage/preparation.py`: task admission with an own project configuration uses `selected_receipt` for the
  frozen revision. Before, it required the receipt's own configuration hash to equal the job's revision hash, which
  refused every task after a derived (global) or agent-only revision (`preparation_required`); this was found while
  testing the live switch and also affected the previous restart path.
- `services/managed_runtime.py`: `_restart_fields`, `_stage` (shadow runtime from explicit references), pointer-swap
  `_install_staging`/`_restore`, `apply_pending`/`try_apply_pending`, worker factories resolved per claim, the idle
  hook of the writer lane and starting a stopped supervisor at the switch; startup records projects whose active
  configuration could not be installed (`degraded`).
- `services/configuration_setup.py`: startup leaves a live set pending; `state` reports APPLY_PENDING, the pending set
  of any scope and `live_activation` (waiting reasons or last FAILED switch); `require_ready` admits writes while a
  live set waits, never without an active revision.
- `services/project_configuration.py`, `profile_preparation.py`: explicit candidate references for staging.
- API: `ConfigurationRead.mode` adds `APPLY_PENDING` and `live_activation`; previews add `apply`, `restart_fields`,
  `waiting`; 409 `live_configuration_refused` carries `details`. OpenAPI and `api.generated.ts` regenerated.
- UI (`Configuration.tsx`, `configuration.ts`, `ProjectProfile.tsx`, `managed-api.ts`, en/es catalogs): pending
  policy and waiting reasons, failed switch and refusal corrections, apply mode in the activation review, removed
  fields in the save review, the distinction between applying configuration, technical preparation and software
  update; texts that still promised a restart were corrected after the browser QA.
- Version `0.1.2` in `pyproject.toml`, `uv.lock`, the FastAPI app, `frontend/openapi.json` and
  `frontend/package.json`/`package-lock.json`; CHANGELOG, READMEs, specification §12, architecture §11, configuration
  flow, data diagram, roadmap/next steps (Metrics Records target, D239) and STATE updated.

## Checks

Run:

- `pytest -q` (full suite, parallel): 2072 passed, 2 skipped, 0 failed (`.local/npm-cache` filled, see the
  [npm cache baseline](../project-history/test-npm-cache-baseline.md)). `test_documentation_parity.py` rerun after the last doc edits.
- New `tests/product/test_configuration_live.py` (9 cases): idle timeout change in the same process/session with
  every other field preserved, explicit removal named in the save preview, missing client refused with its role
  and setting, waiting work deferring the switch and a second activation refused meanwhile, candidate withdrawn when
  its client disappears before the boundary, restart before the boundary, running supervisor applying at idle plus
  `service.lease_seconds` classified as restart, query-only archive inert, failure injected inside the promotion
  transaction rolling back both SQLite and the runtime.
- Updated: first setup now applies live (`test_configuration_api.py`); global derived set applied live and a task
  admitted with the derived revision; a queued job keeps its frozen versions while the project set waits, then the
  set switches after the job is refused; cancelling a waiting global set; an uncertain checkout owner makes a
  project set wait instead of refusing; agent-only project change admits a task (`test_configuration_editing.py`,
  `test_project_configuration.py`). The shared configuration fixture uses the synthetic version/help probe.
- `node --test frontend/tests/*.test.mjs`: 162 pass (new en/es cases for the waiting policy and cancel, refused and
  failed corrections). `npm --prefix frontend run check` and `npm --prefix frontend run build`.
- `alembic check` against a temporary database upgraded to head: no new upgrade operations.
- Synthetic browser QA in Chrome against an isolated service (scratch database, configuration and state
  directories, port 8023, version/help probe as both clients): signed in once; first activation applied live; a
  probe path that could not be launched was refused with both roles named; a timeout change through the form was
  saved, reviewed (“applies without restarting… as soon as this current work finishes”), confirmed, shown as
  **Apply when current work finishes** with “A project creation in progress” and applied by the page's polling
  after the work was released, with the same session. In Spanish, a reviewer-model change waited the same way, and
  removing the probe before the boundary withdrew it with both corrections while revision 4 stayed active.
- Release package: `scripts/build_distribution.py` (offline) from the tree of `v0.1.2`, then
  `scripts/check_distribution.py` (exact members, metadata, licenses, `SHA256SUMS`, isolated wheel journey: OK).
  `my-harness-0.1.2-distribution.tar.gz` has the same layout as 0.1.1, SHA-256
  `c214972b456cc79e6ea65cc8da020f08167cd150cfc165d16d4a471bf5e4f89c`.
- Released through pull request #1 (`develop` → `main`, merge commit `c606116`, lightweight tag `v0.1.2`) and published
  as the GitHub Release `v0.1.2`; the downloaded asset matches its `.sha256` and the local build byte for byte.

Not run or not covered:

- Real providers, installed-wheel upgrade over `0.1.1`, other browsers, screen readers, mobile/light-theme QA of the
  new states, and browser QA of the project configuration page (its pending hint is covered only by type checks).
- A job that is executing while a set waits is covered by the waiting reasons and frozen-version tests, not by a
  real long-running client; an executing call keeps its adapter (and timeout) because it was built at claim time.
- Known limit: a request that read the project map just before a switch and is admitted right after it carries the
  previous versions; such a job is refused before effects by the existing composition check, never run with other
  clients.
