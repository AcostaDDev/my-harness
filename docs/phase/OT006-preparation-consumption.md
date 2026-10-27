# OT006 — Preparation consumption and ownership-loss incident

**Status:** evidence/handoff only, recorded 2026-10-27 at the owner's request before clearing context.
No runtime fix, retry, recovery confirmation, installation or new provider invocation was performed during diagnosis.
Task contract: [ONE_OFF_TASKS](../ONE_OFF_TASKS.md#ot006--repetitive-preparation-executor-output-and-ownership-loss).
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

1. Read STATE/ONE_OFF_TASKS/NEXT_STEPS and preserve this uncommitted documentation topic. OT006 is pending, not
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
