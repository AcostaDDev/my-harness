# OT007 — Task-run lease renewal and stream journal pressure

**Status:** source implemented and qualified; integration, publication and operator installation pending.
**Owner:** OT007, outside P001; target **0.1.8** confirmed by the owner on 2026-10-27 before product edits.
**Branch:** `fix/ot007-task-run-lease`, from clean `develop` / `origin/develop` at `b8e1a90`.

## Authorized delivery

Commit the qualified source, integrate the topic into develop and push, open develop → main PR, build/check the
self-contained archive offline, upload it and its `.sha256` to draft v0.1.8 and verify both downloads. Then merge
the PR, publish, verify public downloads, install offline with the service stopped, and record closure/remove
OT007 from the queue. Source, integration, publication, installation and closure are separate pending steps.
The session does not authorize real providers, a real project retry, network dependency installation or service start.

## Discovery

Read AGENTS, STATE, ONE_OFF_TASKS, NEXT_STEPS, the active ROADMAP, affected specification/architecture, decisions
(including D235/D239/D242/D251), persistence and task-run flow. OT006's preparation-only renewal/batching and partial
capture path provide the precedent. Managed runs currently stop renewal after any exception, journal one transaction
per record and leave a stale process row if the fenced final capture write fails. Existing fencing, checkout locks,
recovery confirmations, frozen versions and history remain authoritative. No schema/dependency change is planned.

## Implementation (D252)

Managed renewal retries non-ownership exceptions at min(lease/3, 1 s), retains the existing ownership/lease/checkout
guard, and records renewal counters and exception class at owner closure. Each CLI read chunk now journals its
events in one transaction. Closing owners settle their unfinished process rows from independent liveness and retain
the adapter's partial capture. Stored captures, history, confirm-stopped and frozen versions remain unchanged.
The existing repetitive status/stop/capture already surfaces output-guard-1; no API/UI addition was needed.

## Reproduction and focused checks

- Before the service fix, the new transient-heartbeat regression test failed with the original
  `Heartbeat failed; stop before the next effect` diagnostic (1 failed, 5.27 s). The first injected OperationalError
  prevented any successful renewal. After the fix it completes and records the recovered failure.
- Synthetic coverage includes a real SQLite busy error caused by an independent writer during renewal while a
  fake CLI streams for longer than a lease; permanent renewal errors stop a streaming group and retain partial usage
  with `final_usage_observed: false`; recovery remains an explicit action and never retries the provider.
- Batched events are compared with the synthetic raw JSONL and their full sequence, with one transaction per chunk
  and complete rollback on an invalid batch. Additional cases cover foreign owners, missing/malformed captures,
  dead/alive/unknown group liveness, preservation of stored captures and existing output-guard surfacing.
- Early test iterations corrected assumptions in new tests about pending attempts: they live in attempt rows until
  recovery/checkpoint, and existing interrupted AgentResult uses its error field rather than a new status. Product
  history/format behavior was preserved. The old capture-failure injections were moved to the new batch entry point.

## Final qualification

- First full offline pytest (`-n 4`): **2184 passed, 1 failed, 2 skipped, 29 subtests** (359.21 s). The failure was
  OT006's interrupted-capture test still injecting its error through the individual journal method, bypassed now
  that the adapter uses the batch method. Its injection was updated; no product behavior was weakened.
- Final full offline pytest (`-n 4`), after all product/test/version edits: **2185 passed, 2 skipped,
  29 subtests passed**, no failures (462.21 s). The same existing deprecation/synthetic-tampering warnings remain.
  All 18 cases in the new lease module passed, as did existing metrics/projection, cancellation, crash/recovery,
  fencing and compatibility coverage. No new provider or real-project validation is claimed.
- Unittest: **10 passed**. Frontend: **230 passed**, typecheck and production build passed (existing bundle-size
  warning only). OpenAPI differs only in `info.version`; generated client types have no diff.
- Fresh temporary SQLite `alembic upgrade head` and `alembic check`: **no new upgrade operations**.
- Offline `build_distribution.py` passed against the stable 0.1.8 candidate sources. `check_distribution.py` passed:
  exact members/metadata/licenses/SHA256SUMS and the isolated installed-wheel UI/assets/API/session,
  D088 definition/task/commit/restart, errors and restored-evidence journey. All processes/projects are synthetic.
  Before delivery the built members will be compared again with the clean integration commit; packaging changes
  no source files. The outer release archive/checksum are generated only after integration and PR creation.

## Delivery state

Source qualification is complete and the diff reviewed (`git diff --check` clean). Commit, integration/push, PR,
draft release/downloads, publication/public downloads, offline installation and closure remain pending.
Shared candidate version is **0.1.8**; no dependency changed.

## Omissions and limits

No real provider, project retry or service start. No new UI, schema, API contract, frozen catalog/history or
configuration change. An idle CLI is stopped at its next journal operation after lost ownership, as before;
OT007 adds no separate watchdog. Process settlement never signals a persisted PID and never releases a writer lock.
