# Bounded fix — configuration activation after empty intake failure

## Problem and scope

An operator cannot increase an active client's timeout after onboarding times out:
although the job is DONE and its empty turn FAILED, the registry work barrier
counts any started intake conversation as pending. Global activation reuses that
barrier, creating a dead end before the operator can apply the required timeout.

This correction is independent of P001 Metrics Records. It changes no API/schema,
dependencies, frozen formats, historical rows or configuration bytes. The active
provider timeout is still selected by the normal save/preview/activate/restart flow.

## Implementation

`storage/registry.py` excludes a definition/onboarding conversation only if all
turns FAILED with no result, observations explicitly unchanged and no observed
drafts on either side, plus no known drafts, edit log, deferrals or proposals.
The query reads turn status/result rather than full frozen requests. Answered,
queued, unknown, unobserved, changed or substantive work keeps the barrier.
Independent queued/running/recovery jobs, checkout/preparation reservations,
acceptance, commit/document intents and phase operations remain blockers.

Earlier attempts and conversation versions are not rewritten. A later explicit
message freezes then-active client settings as usual; no automatic retry or model
fallback was added. See D236 and the configuration flow.

## Checks

- `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q -n 0 tests/product/test_configuration.py`:
  **56 passed** on the final source. Includes empty definition/onboarding activation
  through promotion without historical-row changes, and eleven substantive/uncertain
  cases that must still block, alongside existing pending-job/acceptance coverage.
- `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q -n 0 tests/product/test_configuration_api.py tests/product/test_configuration_editing.py tests/product/test_configuration_import.py tests/product/test_project_registry.py`:
  **69 passed**, one existing Starlette TestClient/httpx deprecation warning.
- Tests use temporary Git/SQLite, synthetic configurations and fake clients only.
  No real provider was invoked, and no operational failure data was copied into fixtures.
- Full Python regression, standalone unittest, frontend test suites and browser QA
  were not run for this storage-only fix. Frontend type checking/build ran as part
  of the offline installer below; no migration check is required because no
  schema/model changed.

## Local installation

The owner explicitly authorized an offline local upgrade and restart after reviewing
the correction. Before stopping, read-only checks found no queued/running/recovery jobs,
checkout locks or reserved preparation. The service was stopped cleanly and a private,
integrity-checked SQLite snapshot plus configuration fingerprints were retained outside
the checkout. The previous installation generation remains available. No global
configuration was edited and no inference was started by this work.

`scripts/install --offline --upgrade --writers-stopped` completed successfully:
locked frontend install/typecheck/build, sdist/wheel member/metadata/hash checks,
new isolated venv, installed synthetic API/UI/task/commit/restart/archive journey,
and dependency compatibility verification. The installer reported network disabled
and did not migrate or alter the operational database/configuration. The project
version remains 0.1.1; this is a local unreleased correction, not a publication.

`scripts/start` restarted the installed package outside the checkout; the UI
returned HTTP 200 on the existing loopback port. A read-only query using the
installed module confirmed that the original empty failed onboarding no longer
has configuration work blockers. Operational run/attempt/conversation/proposal/import
rows and configuration revision references still match the private pre-upgrade
snapshot; all configuration TOML bytes matched their saved fingerprints. No real
provider call or new attempt was made during installation. At that point saved
revision 3 still required normal activation preview/confirmation and restart.

The operator subsequently confirmed revision 3 in the UI and explicitly requested
its restart. Read-only checks verified the pending revision, both 3600-second client
timeouts and absence of queued/running/recovery work, locks or reserved preparations.
The first start waited on the old supervisor's still-held installation lock and
was refused without effects; after confirming both old processes exited and locks
were released, a fresh start succeeded. HTTP 200 and read-only database checks
confirmed revision 3 ACTIVE, no pending activation, both timeouts at 3600 seconds,
and only the two original completed jobs/runs. The failed turns remain historical;
no new model invocation was launched.

The owner subsequently requested a source commit for this bounded fix. No tag, push or release was made.


After that activation, the operator reported client discovery failure. A read-only
comparison showed the saved revisions had also removed the original executable
paths and shortened the explicit PATH. The installed clients were still present.
The operator restored the client paths/PATH in the UI and confirmed revision 4;
no configuration bytes were edited directly by the agent. On the operator's next
restart request, the pending executable files and Node resolution were checked,
both timeouts were verified at 3600 seconds, and absence of pending work/locks
was confirmed. The previous supervisor exited and released its lock before the
new service started. HTTP 200 and revision 4 ACTIVE/no pending activation were
verified, with the same run count and no new inference.
