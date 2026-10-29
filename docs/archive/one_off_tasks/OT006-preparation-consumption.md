# OT006 — Preparation consumption and ownership-loss incident

**Status:** delivered. Released as **0.1.7** ([PR #6](https://github.com/AcostaDDev/my-harness/pull/6), merge/tag
`a3e9794` / `v0.1.7`) and installed locally
([D251](../../DECISIONS.md#d251--writer-tool-admission-bounded-repetitive-output-and-lease-renewal-evidence)); see
[Resolution](#resolution-d251), [Delivery state](#delivery-state) and [Published 0.1.7](#published-017). The sections down to
"Resume after context reset" are the original handoff (2026-10-27), kept as recorded. No retry, recovery confirmation,
installation or new provider invocation was performed during diagnosis or the fix.
Task contract: formerly in ONE_OFF_TASKS, removed after delivery; the remaining task-run issue is OT007.
Documentation topic: `docs/ot006-preparation-consumption`, from develop `3876230`.

## Context and delivery boundary

After OT005 publication, the owner reported that Claude Code usage jumped from 85% to 100% within seconds of
starting generic project preparation. Their later screenshot showed failure in the executor step with
`OwnershipLost`. The percentage/timing is the owner's observation, not account telemetry captured by Harness.

OT005 was already released as 0.1.5 through PR #4, main/tag `b0d035d` / `v0.1.5`; its release is not rewritten.
The operator service uses separately installed source `be76164` with 0.1.4 package metadata, containing OT005's
tool-link and preview fixes. Publication did not replace/restart that installation. The earlier ACTIVE report in
[OT005's release evidence](OT005-preparation-tool-links.md) was not a successful real receipt: the later operation
failed. No completed preparation/validation/activation is claimed.

This new task records two observed symptoms; a causal connection is not established. OT004/0.1.6 retains its
existing queue priority. Agree any reprioritization and OT006 target before product changes (D242). Separate source,
integration, release, archive/publication, installation and real validation remain pending; previous OT005 release
authorization does not authorize an OT006 release or another real invocation.

## Sanitized read-only observations

The operator SQLite database was opened with `mode=ro`; local stdout/stderr artifacts were read without modifying
the operation. Only aggregates are retained here: no project name/path, operation/session/message identifiers,
credentials, prompt, raw stream, generated project text or private source. Do not create production fixtures.

| Observation | Recorded value |
| --- | --- |
| Operation creation → settlement (UTC) | 2026-10-27 17:51:32.039234 → 18:00:53.836204 |
| Elapsed | 561.797 seconds, approximately 9 min 22 sec |
| Outcome | `FAILED`, diagnostic `OwnershipLost`, `owner_closed = true` |
| Last persisted lease deadline (UTC) | 18:00:53.451934, just before settlement |
| Requested / message-start reported model | `claude-sonnet-5-5` / `claude-sonnet-5-5` |
| Requested effort / session | `high` / fresh session |
| Recorded executor processes | 1 |
| Steps | 15: directories DONE; executor STARTED without completion evidence; 12 native commands and technical commit PENDING |
| stdout / stderr | 5,176,329 bytes / 0 bytes |
| Recorded process row | `RUNNING`, no final capture; stale status, not proof of a live writer |
| Independent recorded-group liveness check | `dead` during diagnosis, checked again during handoff |

There was one observed API message identity in the captured stream. This establishes neither all internal CLI
requests/retries nor other account activity. It is not 17,299 provider invocations:

- Journal: 2,180 `executor_stream_bytes` events, 17,299 `executor_agent_event` events; one executor intent/spawn.
- JSONL records: 5 `system`, 17,297 `stream_event`, 1 `assistant`. Stream-event UUIDs are distinct.
- Stream subtypes: one `message_start`, two `content_block_start`, 17,293 `content_block_delta`, one
  `content_block_stop`. Deltas: 17,289 text, three thinking, one signature.
- Text deltas concatenate to **226,378 characters**, **5,388 lines**, only **11 distinct lines**. Several lines
  repeat approximately 1,790 times; text includes 1,795 opening `<invoke` markers and repeated `parameter` tags.
  These are text deltas, not native `tool_use` blocks. No actual tool call was observed in the captured response.
- No `message_delta`, `message_stop`, terminal `result`, provider error or rate-limit event was captured.
  There is no completed result or final usage total.

The repetitive generation is anomalous and plausibly wasted quota. It is not evidence that normal native
preparation commands are intrinsically expensive: none of those commands started. Exact account attribution of
the reported 15 percentage-point increase, or its apparent instantaneous timing, cannot be established here.

## Usage evidence and limits

The single `message_start` reports:

| Field | Value | Interpretation |
| --- | --- | --- |
| `input_tokens` | 2 | Uncached input reported at message start |
| `cache_creation_input_tokens` | 15,892 | All attributed to `ephemeral_1h_input_tokens`; 5-minute bucket is zero |
| `cache_read_input_tokens` | 649 | Reported cache read |
| Sum of input categories | 16,543 | Count once; the repeated initial usage in an assistant event is not another request |
| `output_tokens` | 6 | Initial counter only; **not** the final output total |

Prompt file size was 30,486 bytes. Text character count is not a token count. There is no final output quantity,
actual subscription quota accounting or confirmed cost. Missing is not zero; do not calculate a complete cost from
the initial six output tokens or translate the input sum into a subscription percentage.

Official documentation consulted on 2026-10-27: [usage-limit factors](https://support.claude.com/en/articles/9797557-usage-limit-best-practices)
include context, tools, model and effort; [Pro/Max usage limits](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)
are shared across Claude and Claude Code. [Claude Code costs/usage documentation](https://code.claude.com/docs/en/costs)
also describes cached usage displays under rate limiting. These explain why a percentage change need not be
linear or immediately visible; none proves that stale display, this operation alone, or quota exhaustion caused
this incident. `OwnershipLost` is a Harness ownership diagnostic, not a provider quota diagnosis.

## Source inspection and unresolved causes

- `adapters/cli_agents.py`: Claude is invoked with streaming/partial messages, explicit tools, no session
  persistence and the frozen model/effort. Inspect argv, role/tool mapping, prompt construction and CLI protocol
  compatibility using synthetic data. The captured text imitates tool invocation syntax, but its origin/cause is
  not established. Do not assume a particular model or client defect from that symptom alone.
- `adapters/streams.py`: JSONL/partial events produce agent events. Keep raw-event counts distinct from API message
  counts, and initial usage distinct from final/cumulative usage.
- `storage/preparation.py`: `owned()` requires ACTIVE state, matching owner token and checkout lock, and an
  unexpired lease. Heartbeat and each journal update use this guard. The persisted lease deadline precedes the
  failure, consistent with expiry; no detailed heartbeat failure reason was recorded.
- `services/project_preparation.py`, `_run_claimed()`: heartbeat runs every `lease_seconds / 3`; any heartbeat
  exception silently exits the heartbeat thread. Final settlement closes the owner and checks process-group
  liveness before releasing the checkout lock. Establish why renewal stopped/arrived late.
- `storage/managed.py`, `_write()`, and `storage/preparation.py`, `process_update()`: each parsed agent event
  entails a guarded SQLite write. Sustained event pressure/SQLite contention is a hypothesis for lease failure,
  **not a reproduced or proven root cause**. Do not fix it by weakening ownership checks or blindly lengthening leases.
- `adapters/cli_agents.py`, invocation exception/finalization: an exception stops the owned process group and
  re-raises before normal `process_finished` capture. The preparation journal also requires ownership for that
  update. This explains the possible stale RUNNING/no-capture row; independent liveness is necessary. Investigate
  ownership-safe interrupted capture and diagnostics without allowing an expired owner to mutate active work.

## Resume after context reset

1. Read STATE/ONE_OFF_TASKS/NEXT_STEPS (this handoff is integrated into develop at `f185265`). OT006 is pending, not
   implemented. Resolve its priority/release target before product edits; OT004's existing assignment is unchanged.
2. Use the aggregates above for synthetic reproduction. If additional local diagnosis is required, open
   `~/Library/Application Support/My Harness/data/harness.sqlite3` with SQLite URI `mode=ro`; locate the incident by
   its UTC creation/settlement timestamps in `project_preparation_operations`. Inspect its related steps/events and
   `managed_processes` row; that row's `spec.artifacts` points to local `stdout.bin`/`stderr.bin`. Inspect only needed
   fields locally; do not print/copy the prompt, raw artifacts or project into repository fixtures or public reports.
3. Establish the repetition/protocol cause and independently reproduce the lease failure with a fake CLI and
   temporary SQLite/processes. Design a bounded stop policy and interrupted-evidence handling under existing
   fencing/write-scope rules. Record accepted design before implementing a behavior change.
4. Verify relevant synthetic regressions and update affected parity docs/contracts. No real agents/providers,
   production recovery confirmation/retry, service restart, installation, push or publication is authorized by this
   handoff. Preserve the failed operation and any uncertain effects; do not replay or manufacture a successful receipt.

Checks for this handoff: read-only database/artifact aggregation, source comparison and independent group-liveness
check; documentation diff/link checks. No product tests, model calls or production mutations were needed or run.

## Resolution (D251)

**Release target.** On 2026-10-27 the owner asked the session to continue with OT006 and, once it was done, open
the GitHub pull request, build the `.tar.gz` and upload it. Under D239 that makes OT006 patch **0.1.7**, on the
existing topic → `develop` → release PR → `main` route (D235). Merging the PR and publishing the release follow the
0.1.6 precedent: each needs its own explicit owner instruction.

### Additional read-only observations

The operator database was opened again with `mode=ro`, and only argv flags and aggregates were read. No prompt, raw
stream, project name or identifier was printed or copied.

| Observation | Value |
| --- | --- |
| Executor CLI / adapter | Claude Code 2.1.311 / `cli-14`, `timeout_seconds` 3600 |
| Executor `--tools` / `--allowedTools` | `''` / `''`: **no tool at all** |
| Permission mode | `dontAsk` |
| Frozen plan | 6 write paths, 24 dependency entries, no network destinations |
| Journal events | 19,488 total (17,299 agent events, 2,180 byte events) |
| Largest gap between consecutive events | 2.48 s (directories step), at most 0.79 s while streaming |
| Last event before closing | 18:00:53.398, then `owner_closed` 18:00:53.832 |

The stream writer kept journaling until about 50 ms before the persisted lease deadline. With the default 30 s
lease, the last successful renewal was about 18:00:23. Journaling never stalled, so the lease expired because
renewal stopped while streaming went on.

### Established causes

1. **Repetitive text (established).** Generic preparation asked a Claude executor to write six confirmed paths but
   launched it with an empty tool inventory. The only way it could "act" was to write tool-call markup as text.
   That text (1,795 `<invoke` markers, 11 distinct lines, no native `tool_use`) is the textual imitation recorded
   above. Nothing in preview or launch checked that the writer had a usable write tool, and nothing bounded output
   apart from the 3,600 s timeout. A model or effort change would not have fixed it: no tools existed.
2. **Ownership loss (mechanism reproduced; incident exception unrecorded).** `_run_claimed`'s heartbeat thread
   returned on its **first** exception, so one transient failure ended renewal and the lease expired one lease
   later. The next guarded journal write or cancel check raised `OwnershipLost`. The adapter then stopped the group
   and re-raised before `process_finished`, which left the stale `RUNNING` row with no capture. Each stream record
   was its own write transaction (about 35 per second here). A synthetic SQLite experiment (WAL, one tight writer
   loop, scratch files only) showed how this can happen: with a 1 s busy timeout, 3 of 15 competing heartbeat-style
   writes failed with `database is locked`; with the product's 5 s timeout, single waits reached 5.36 s. The
   specific exception in the real incident was not recorded, so SQLite busy remains the most plausible trigger, not
   a proven one. Against the old service code, the new synthetic test with one injected `OperationalError`
   reproduces the incident's exact diagnostic, `Preparation stopped: OwnershipLost`.
3. **Quota.** Exact consumption is still unknown. The initial counters and character counts above remain the only
   evidence; the fix changes nothing in how usage is accounted.

### Accepted design and implementation

Recorded in D251; no schema, migration, API, configuration-format, dependency or `cli-14` change.

- `adapters/cli_agents.py`: `inventory()` is shared with argv construction, and `write_tools()` /
  `executor_write_tools()` report the usable `Write`/`Edit`/`MultiEdit`. Stream events are flushed per read chunk
  through `process_updates` when the journal supports it. The process spec records `output_guard`. A guard stop
  ends the group with status `repetitive`. Captures add `output_guard` and `final_usage_observed`. After a spawn,
  an exception writes `capture.json` (status `interrupted`) beside the attempt's artifacts.
- `adapters/streams.py`: `OutputGuard` (`output-guard-1`, 400-line window with at most 20 distinct lines, or one
  line over 262,144 characters). It counts Claude `text_delta` text only and keeps native tool uses and textual
  markers as separate counts.
- `services/profile_preparation.py`: `_writer_tools` refuses at preview and again before launch, and a guard stop
  maps to `profile_preparation_executor_repetitive`.
- `services/project_preparation.py`: the heartbeat retries non-ownership failures within one second while the lease
  lasts. Settlement records `heartbeat` and a `preparation.heartbeat_lost` diagnostic, then calls
  `interrupted()` before `owner_closed`.
- `storage/preparation.py`: `PreparationAgentJournal.process_updates` (one guarded transaction per chunk) and
  `PreparationRepository.interrupted` (independent group liveness, kept partial capture, never replaces a stored
  capture, `process_interrupted` event).
- en/es catalogs: `preparation.heartbeat_lost`, `profile_preparation.executor_tools`,
  `profile_preparation.executor_repetitive`.
- Parity: D251, CHANGELOG 0.1.7, ARCHITECTURE and `docs/flows/project-preparation.md`. Data model, OpenAPI paths
  and client types are unchanged (OpenAPI only carries the new `info.version`).

### Synthetic regression tests

`tests/product/test_output_guard.py` (new, 18 cases) covers:

- stopping the repeated tool imitation exactly when the window fills;
- split deltas and split markers;
- five legitimate long shapes that are not stopped: numbered lines, code with repeated braces, native tool input,
  blank lines and thinking;
- the single-line limit;
- Codex having no guard;
- the writer inventory matrix, including grantable tools and scoped rules;
- a real CLI-transport repetitive stream stopped with a dead group, kept artifacts, initial-only usage and
  `final_usage_observed=false`;
- a long varied stream that completes;
- an interrupted invocation that leaves `capture.json` while the fenced journal row stays stale `RUNNING`.

`tests/product/test_profile_preparation.py` gains 9 cases:

- a Claude writer without a usable write tool is refused at preview (3 variants);
- an older queued plan fails before any launch;
- the repetitive preparation executor is stopped, with no receipt and the lock released;
- 1,501 stream records are journaled in fewer than a tenth as many transactions;
- one transient heartbeat failure is retried and the preparation completes (it fails on the old code);
- permanent renewal failure stops a streaming executor promptly and settles `STOPPED` from independent liveness
  with its partial capture (it fails on the old code with a bare `OwnershipLost`).

The existing Claude transport test now configures explicit `Read`/`Write` executor tools. Every fixture is
synthetic; nothing from the real stream, prompt or project was copied.

### Checks

All checks ran offline on macOS ARM64 / Python 3.14 with temporary SQLite, Git and processes.

- Full pytest (`-n 4`): **2166 passed, 2 skipped, 29 subtests passed**, 0 failed (353 s). An earlier full run had
  one failure, `test_exported_openapi_matches_runtime_without_database_side_effects`, only because the version bump
  landed during that run. The module then passed alone (10/10), and the final run above started after every change.
- Focused suites: new output-guard tests 18/18 and the new preparation cases 9/9. Run against the old
  `project_preparation.py`, both heartbeat tests fail, which shows they detect the defect.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 10 passed. Frontend `node --test`: **230 passed**; `tsc`
  typecheck passed.
- Fresh temporary SQLite `alembic upgrade head` + `alembic check`: no new upgrade operations.
- `scripts/export_openapi.py` differs only in `info.version` (0.1.7); `generate:types` produced no diff.
- `git diff --check` clean.

## Delivery state

- Topic `fix/ot006-preparation-consumption` from develop `f7f3917`: fix `6c88977` and this release
  preparation commit (shared version **0.1.7** in `pyproject.toml`, `api/app.py`, `frontend/package.json`/lock,
  the `uv.lock` project entry, exported OpenAPI, CHANGELOG and en/es README download instructions). No dependency
  change.
- Route in this session, on the owner's request: merge into develop (`--no-ff`) and push it, open a release pull
  request develop → main, build `my-harness-0.1.7-distribution.tar.gz` offline from a clean worktree of the develop
  integration commit, run `check_distribution.py`, and upload the archive and its `.sha256` to a **draft** GitHub
  Release `v0.1.7` targeting `main`, then verify both by downloading them. The PR number, archive size and SHA-256
  are listed in the PR description and the draft release.
- **Completed later at the owner's instruction:** merge, publication, public download verification and local
  installation ([below](#published-017)). The remaining task-run question went to OT007.

## Published 0.1.7

The owner then asked the session to merge the PR, publish the release, install the new version and register the
remaining issue as a one-off for the next session.

- [PR #6](https://github.com/AcostaDDev/my-harness/pull/6) was merged with a merge commit,
  **`a3e979446fc908de16c2067cc04761b98a2cdcc1`**. Its first parent is the 0.1.6 release `0319b66` and its second the
  develop integration `59bb475`. Its tree equals `59bb475`'s exactly, so the archive built from that tree is the
  release artifact, without a rebuild.
- `my-harness-0.1.7-distribution.tar.gz`: **3,689,519 bytes**, SHA-256
  **`e0ecbb7a62b9adeda014a56785ae41aab3116743abee162adaa65df70ecbaddc`**. Its root `my-harness-0.1.7/` has the same
  13 files as 0.1.6's layout. It was built offline from a clean detached worktree of `59bb475` and passed
  `check_distribution.py` (exact members, metadata, licenses and `SHA256SUMS`; the isolated installed-wheel
  UI/API/session/definition/task/commit/restart/error/restored-evidence journey).
- The draft release was downloaded back and matched byte for byte. The annotated tag `v0.1.7` was pushed on the
  merge `a3e9794`, and the draft was then published as
  [GitHub Release v0.1.7](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.7) (latest, not draft or
  prerelease).
- The public `curl` downloads from the README URLs pass the published `.sha256`, match the local archive and checksum
  byte for byte, and all 12 `SHA256SUMS` entries pass after extraction.
- develop was fast-forwarded to the release merge and pushed. This closing documentation is integrated into develop
  separately, so the tagged source is not rewritten.

### Local installation

The operator installation was upgraded at the owner's explicit request.

- Before the upgrade: no Harness service, `process_gate.py` or `my-harness` process was running. The database, read
  with `mode=ro`, had only `DONE` jobs, the single `FAILED` preparation, no checkout locks, and one stale `RUNNING`
  process row: the incident's, whose group had been confirmed dead. The other Codex/Claude processes on the
  machine were the owner's own sessions, not Harness writers.
- `scripts/install --dist <public my-harness-0.1.7> --upgrade --writers-stopped` (offline, default paths) published
  generation `gen-8570ad968e0b42f090237633bd568570`: `READY`, `project_version` **0.1.7**, `network: false`. Its
  isolated distribution check and `uv pip check` passed. The previous generation (`gen-d55da…`, package 0.1.4
  metadata) is kept, and the installer changed no database or configuration file.
- The database is already at `0027_profile_proposals`, the unchanged schema head, so no migration was needed or run.
- The service was not running before and was not started. Start it with `scripts/start` when ready.
- **Before retrying the preparation:** the failed operation remains `FAILED`. Its linked successor is refused at
  preview until the Claude executor agent has `Write` and/or `Edit` in both its tools and allowed tools (editable
  in the agent form, D250). Retrying it is an operator action that was not performed.

## Not covered

- No real provider, real preparation retry, recovery confirmation of the failed operation, service restart or
  installation. The failed operation stays `FAILED` exactly as recorded; its linked successor would now be refused
  at preview until the operator configures a write tool for the Claude executor.
- The guard watches Claude text only. Codex partial text is not streamed by `exec --json`, and thinking loops are not
  inspected. The thresholds are engineering bounds checked against synthetic cases, not tuned on provider data.
- Task runs were not changed (now tracked as **OT007**). Their journal still writes once per stream record. `LocalSupervisor`'s heartbeat
  also stops after its first exception, but unlike preparation it sets `heartbeat_failed`, so the next journal call
  stops the attempt with an explicit diagnostic. Its exposure to transient SQLite busy is the same wider issue and
  is left for a separately scoped task.
- Why the original SQLite write failed (or whether something else raised) is unproven. Real account quota
  attribution is still impossible to infer.
