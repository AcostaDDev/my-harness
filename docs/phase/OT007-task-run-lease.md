# OT007 — Task-run lease renewal and stream journal pressure

**Status:** delivered and closed: source qualified, released as **0.1.8**, public downloads verified and installed
offline with the operator service stopped. OT007 removed from the one-off queue; next work is P001-T001.
**Owner:** OT007, outside P001; target **0.1.8** confirmed by the owner on 2026-10-27 before product edits.
**Branch:** `fix/ot007-task-run-lease`, from clean `develop` / `origin/develop` at `b8e1a90`.

## Authorized delivery

Commit the qualified source, integrate the topic into develop and push, open develop → main PR, build/check the
self-contained archive offline, upload it and its `.sha256` to draft v0.1.8 and verify both downloads. Then merge
the PR, publish, verify public downloads, install offline with the service stopped, and record closure/remove
OT007 from the queue. Source, integration, publication, installation and closure were tracked separately;
their completed results are recorded below.
The session does not authorize real providers, a real project retry, network dependency installation or service start.

## Discovery

Read AGENTS, STATE, ONE_OFF_TASKS, NEXT_STEPS, the active ROADMAP, affected specification/architecture, decisions
(including D235/D239/D242/D251), persistence and task-run flow. OT006's preparation-only renewal/batching and partial
capture path provided the precedent. At discovery, managed runs stopped renewal after any exception, journaled one
transaction per record and left a stale process row if the fenced final capture write failed. Existing fencing,
checkout locks, recovery confirmations, frozen versions and history remain authoritative. No schema/dependency
change was needed.

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
  Before delivery every built source/UI/license member was compared again with the clean integration commit using
  the checkout verifier's pre-bundle stage; every bundled script was compared with its committed source. The final
  bundle verifier also passed. Packaging changed no source. The outer release archive/checksum were generated after
  integration and PR creation.

## Delivery state

Source qualification is complete and the diff reviewed (`git diff --check` clean). Shared version is **0.1.8**;
no dependency changed.

- Source commit **`df4d7dd`**, on `fix/ot007-task-run-lease` from `b8e1a90`; integrated with `--no-ff` into develop
  as **`a6c0f28198897ceaaa7f59ddbf45a2756900b29f`**, then pushed.
- [PR #7](https://github.com/AcostaDDev/my-harness/pull/7), develop → main, was opened before generating the outer
  distribution archive. The archive/checksum were uploaded to draft **v0.1.8**, then downloaded back through the
  authenticated asset route and verified byte for byte, including the archive SHA-256.
- After those checks, PR #7 was merged as **`c00529802a710ddb71466e0a1b4ebe551e5bc5ac`**. Its second parent is
  `a6c0f28`; its tree is exactly the qualified integration tree **`1ce096141d1ccf2ab82ffe0eb941474052b8640e`**.
  Annotated tag **`v0.1.8`** identifies that release merge; no tag/source history was rewritten.
- [GitHub Release v0.1.8](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.8) was published on
  2026-10-27 at 20:52:29 UTC (latest; not draft/prerelease). develop was fast-forwarded to the release merge and
  pushed. This closure documentation uses a new topic from that develop; the tagged source remains immutable.
- `my-harness-0.1.8-distribution.tar.gz`: **3,692,339 bytes**, SHA-256
  **`d782cb1e44ebdaac6f1b71545f2c4904c68f0adcb0bd632049ff8441ad77f3f9`**. Root `my-harness-0.1.8/` contains the
  established 13-file layout. The public archive and its `.sha256`, downloaded with unauthenticated `curl` from
  the README URLs, match both local assets byte for byte. The external checksum and all 12 internal SHA256SUMS
  entries pass; the freshly extracted bundle passes the complete member/metadata/license verifier.

## Operator installation

Before upgrade, the default installation was READY at 0.1.7 (`gen-8570ad968e0b42f090237633bd568570`). No operator
service/writer process or active job/preparation/checkout lock was present. The sole historical RUNNING process
row's group was independently checked dead immediately before upgrade. The failed OT006 preparation was preserved.
Data/configuration file hashes were recorded without copying their contents. The database was already at unchanged
head `0027_profile_proposals`, so no migration was needed or run.

The verified public package's `scripts/install --dist <extracted-public-package> --upgrade --writers-stopped
--offline --python /opt/homebrew/bin/python3.14` completed successfully in the same default installation/data/
configuration/cache paths. Generation **`gen-bb9bf97436d64ba5b20196784c1e229a`** is READY, `project_version`
**0.1.8**, `network: false`; its receipt digest matches `current.json`, and the installed package reports 0.1.8.
The isolated installed-wheel synthetic journey and offline `uv pip check` passed. Earlier generations, including
0.1.7, are kept. All data/configuration file hashes match the pre-installation values; schema remains 0027 and the
OT006 preparation remains FAILED. No operator service/writer process was present after upgrade; no service start,
configuration edit or project retry was performed.

## Closure

All agreed delivery stages are complete. Closure updates STATE/NEXT_STEPS/ROADMAP and D252 and removes OT007's
section from ONE_OFF_TASKS on `docs/ot007-release-closure`, integrated into develop separately from the immutable
release tag. The queue is empty and P001-T001 is the next task; no Metrics Records task is marked complete.

## Omissions and limits

No real provider, project retry or service start. No new UI, schema, API contract, frozen catalog/history or
configuration change. An idle CLI is stopped at its next journal operation after lost ownership, as before;
OT007 adds no separate watchdog. Process settlement never signals a persisted PID and never releases a writer lock.
