# OT005 — Generic preparation and read-only existing tool aliases

**Status:** source implemented, synthetically qualified and installed locally; owner manual verification pending.
Separate 0.1.5 release is authorized conditionally on the owner confirming that verification succeeds.
**Priority/target:** hotfix 0.1.5, before OT004 (0.1.6), then unchanged Metrics Records (D246).
**Task contract:** [ONE_OFF_TASKS](../ONE_OFF_TASKS.md#ot005--read-only-existing-tool-aliases-in-generic-preparation).
**Decisions:** [D246](../DECISIONS.md#d246--ot005-preparation-tool-aliases-before-the-visual-editor),
[D247](../DECISIONS.md#d247--frozen-read-only-tool-link-evidence-in-generic-preparation).

## Resumption and delivery status

The initial handoff was documentation only, on `fix/ot005-preparation-tool-links`, created from `develop` at
`a8efd10`. The owner subsequently requested continuation through OT005 and authorized a repository commit.
That commit includes the preserved task/priority documents and this implementation. No OT004/P001 work is included.

OT003 remains the published 0.1.4 release: implementation `437acf5`, release merge/tag `9985b0a` / `v0.1.4`, PR #3;
its closing documentation reached develop at `a8efd10`. Its frozen evidence and published artifacts are unchanged.
Package/API/UI metadata remains **0.1.4** during the local test; 0.1.5 release preparation awaits the owner's
manual success confirmation. Source implementation commit: `e2d62fe`.

The agreed delivery remains topic → `develop` → separate release PR/merge into `main` → **0.1.5** distribution.
The owner subsequently requested stopping, reinstalling and starting the running service for their own manual test;
that local operation is complete as recorded below. After they report success, their instruction authorizes the
0.1.5 archive, release PR to main and GitHub publication through the agreed route. Do not publish before that report.
Integration, version/upgrade notes, 0.1.5 package qualification and release PR/tag/publication remain pending. Keep
OT005 in ONE_OFF_TASKS until delivery is complete or explicitly deferred under D242. No push, merge, tag,
publication, operator TOML edit, real preparation or provider invocation was performed. Do not rerun the operator's
onboarding/preparation automatically.

## Observed failure and diagnosis

The operator completed documentary onboarding and reached own-profile configuration/preparation. Reviewing
preparation failed with `422 · invalid_request: Unexpected symlink: .venv/bin/python` before any operation started.
The initial read-only diagnosis found saved project configuration, no active project revision and no preparation
operation. No private content, credentials, run identifiers or absolute project paths are retained here.

An existing environment has `python`/`python3`/versioned-interpreter aliases ending at an installed executable outside
the checkout. The plan reuses that environment and confines writes/local directories to a separate private area.
`local_config._executable` accepts symlinks and preview binds their resolved target/hash, but the generic `_links`
policy additionally required every tool alias to match writable `local_paths`. Whole-checkout snapshots therefore
rejected these read-only inputs. Configuring the resolved executable alone did not remove aliases from the scan.
Deleting/recreating the environment or granting writes to it was not an acceptable fix.

The first two new regression cases reproduced `Unexpected symlink: .venv/bin/python` against the original source,
with configuration pointing either to the alias or directly to the resolved fake executable.

## Implemented behavior

Only `services/profile_preparation.py` changes product behavior. New generic previews carry
`read_only_tool_links`, an exact map of existing aliases outside `local_paths`. Each file-link chain is resolved
through at most 40 links, with parent directories checked through the existing fd/O_NOFOLLOW helper. The terminal
file must be a regular executable at an explicitly configured resolved path; `verify_tools` checks its original
path resolution and frozen SHA-256. The evidence records chain paths, raw link text, link modes and terminal mode.
An identical hash at another undeclared path is insufficient.

Preview only reads this evidence. Confirmation binds it in the existing preview hash. Later snapshots require the
same alias map/evidence and recheck frozen tools, including after executor and native-command effects. Existing
before/after guards still reject changes to the read-only environment outside write scope. Even explicitly naming
a read-only alias in `write_paths` cannot authorize deleting it. No hash or chain is silently refreshed.

Receipts copy the frozen map and verify its complete alias path set, chain evidence and executable bytes before
configuration readiness/admission. Missing/replaced/added/retargeted aliases are refused. The existing protected-link
receipt guard remains, and new protected read-only aliases are rejected in preview before steps/commit.
`environment_paths` continues to accredit only declared stable environments; tool-link evidence does **not** certify
other pre-existing environment contents. The successful regression preserves an unrelated existing dependency file
without adding `.venv` to write, local or environment paths.

Historical plans/receipts without the field keep their original policy and exact bytes. Linked recovery uses the
original opt-in/evidence or historical policy, never rediscovery; the established recovery event may be appended,
while old plan/step/receipt evidence remains intact. Recipe link policies, fingerprinted recipe sources, snapshot
entry/byte limits, confirmation/configuration/HEAD/work barriers and network rules are unchanged.

The field lives in existing opaque inline JSON: no schema/model, TOML format, endpoint, API response model,
dependency or shared version change. Specification, architecture and configuration/preparation flows are in parity.
The current generated OpenAPI was compared with the live schema generator and matches exactly; client regeneration
is unnecessary because its schema is unchanged.

## Synthetic acceptance evidence

Temporary Git/SQLite fixtures, fake executable tools and a fake executor cover:

| Case | Result |
| --- | --- |
| Existing interpreter chain outside local scope, configured alias or resolved tool | Passive preview, confirmed execution, receipt and configuration-readiness verification succeed; links/modes and dependency bytes preserved |
| Existing byte-bound local alias | Retained; the pre-existing regression still passes |
| Undeclared target with identical bytes, broken/looping/overlong chain, directory link or directory hop (including `..`) | Refused before executor/preparation effects |
| External file-link intermediary | Exact chain bound; unrelated external broken link is never scanned; changed intermediary text is refused |
| Alias changed after preview, executable changed after confirmation | Stale confirmation or pre-execution guard refuses |
| Executor rewrites/deletes/replaces/chmods/adds an alias, edits existing environment bytes or changes external tool bytes | Failed operation, no receipt/native validation/technical commit; effects retained for diagnosis; recovery refuses drift |
| Native command changes external tool bytes | Post-command guard fails before receipt/commit |
| Completed receipt with changed/missing/new/replaced alias or changed tool | Verification refuses without rewriting persisted receipt |
| Protected alias | Preview and receipt guard refuse |
| Explicit linked recovery, new and historical policies | Exact accredited prefix reused, no executor replay, original evidence/policy preserved |
| Historical receipt without opt-in | Still verifies original workspace; adding an outside-local alias retains historical refusal |

These are cooperative change-detection guards, not OS isolation or rollback. Arbitrary directory links (including
unrelated links exposed by a later scan) remain unsupported. No real environment, Python/Docker/project workload,
provider call, operator service or private configuration was used. Existing synthetic CLI transport tests use only
fake probe scripts; they are not real-provider evidence.

## Validation

- Original regression: **2 expected failures** at `Unexpected symlink: .venv/bin/python`, before the fix.
- `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q`: **2126 passed, 2 skipped,
  29 subtests passed**, no failures, in **292.42 seconds**. The 11 warnings are the existing FastAPI TestClient
  deprecations and intentional duplicate-ZIP-member fixture. This includes 31 new generic-preparation cases.
- After strengthening the existing protected API test to include the alias chain, the focused `-n 0` rerun of
  `test_generic_api_validates_exact_union_and_security_before_confirming`: **1 passed**, 68 deselected. Exact
  preview/confirmation evidence, strict input, Origin guard and idempotent confirmation all remain covered.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: **10 passed**.
- `node --test frontend/tests/*.test.mjs`: **203 passed**.
- `npm --prefix frontend run check` and `npm --prefix frontend run build`: passed; existing large-chunk advisory.
- Alembic upgrade-to-head and `command.check` with `database_url` pointing to a fresh temporary synthetic SQLite:
  passed, **no new upgrade operations detected**; no operational database opened.
- In-memory `create_app().openapi()` equals `frontend/openapi.json`: passed; API/types unchanged.
- Reviewed product/test/document diff and current STATE/NEXT_STEPS/ONE_OFF_TASKS; local documentation targets and
  `git diff --check` passed. The source commit containing this artifact includes the initial uncommitted task docs.

Intermediate test iterations corrected fixture assertions (the receipt adapter wraps refusal in `JournalError`,
and explicit recovery appends an event/version to the old operation). They did not waive a product failure.
No fresh visual/browser/accessibility QA or real-provider validation was run. The subsequent local installation
qualified the source package/installed wheel as recorded below; final 0.1.5 release artifacts are still pending.

## Authorized local installation and restart — 2026-10-27

At the owner's explicit request, identified the existing installed launcher and its loopback 8013 listener, checked
live process identity/parentage, and sent SIGTERM to the launcher. The launcher and server exited gracefully and
the port was released. Before reinstalling, all seven jobs were DONE, all six recorded processes STOPPED, no checkout
locks/preparations were reserved and no configuration activations were pending. No work was replayed.

Ran `scripts/install --clone "$PWD" --upgrade --writers-stopped --offline`, retaining the existing installation,
data, configuration and cache locations. New generation **`gen-ed75f514daec491896380b45ce16c6ba`** is READY;
the previous generation was retained. Package metadata is **0.1.4**, including the committed OT005 source fix.
No network dependency download or migration was needed or performed.

The installer passed exact artifact/member/metadata/license/checksum verification, its isolated installed-wheel
UI/assets/API/session/definition/task/commit/restart/error/restored-evidence journey with fake agents, and
`uv pip check`. The installed `services/profile_preparation.py` bytes match source commit `e2d62fe` exactly.

Started `scripts/start --install-dir <existing installation> --port 8013` detached, with a private 0600 log and a new
0600 access-key file. Startup completed and the HTTP root returned **200**. Canonical row hashes for every SQLite
table and the combined private TOML path/content hash were identical before installation, after installation and
after startup. All seven jobs remain DONE and the six recorded processes STOPPED. Hash baselines/logs stay private
outside the repository; no operational rows, key bytes or TOML contents are copied into fixtures or documentation.

The service is ready for the owner to sign in with the new key and perform the manual preparation test. No claim
that the real failing project is fixed is made before their report. On success, continue the conditionally authorized
0.1.5 archive/release PR/GitHub publication; OT004 stays behind OT005's delivery.
