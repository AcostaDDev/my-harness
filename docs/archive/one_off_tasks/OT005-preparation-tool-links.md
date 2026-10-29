# OT005 — Generic preparation and read-only existing tool aliases

**Status:** released as **0.1.5** on 2026-10-27 through [PR #4](https://github.com/AcostaDDev/my-harness/pull/4),
merge/tag `b0d035d` / `v0.1.5`. GitHub archive/checksum downloaded and verified; OT005 delivery complete.
The owner's last real-workflow evidence is ACTIVE preparation; a completed receipt/activation is not claimed.
**Priority/target:** hotfix 0.1.5, before OT004 (0.1.6), then unchanged Metrics Records (D246).
**Release task contract:** [OT005 at the immutable v0.1.5 tag](https://github.com/AcostaDDev/my-harness/blob/v0.1.5/docs/ONE_OFF_TASKS.md#ot005--read-only-existing-tool-aliases-in-generic-preparation).
Current queue: [ONE_OFF_TASKS](../../ONE_OFF_TASKS.md).
**Decisions:** [D246](../../DECISIONS.md#d246--ot005-preparation-tool-aliases-before-the-visual-editor),
[D247](../../DECISIONS.md#d247--frozen-read-only-tool-link-evidence-in-generic-preparation),
[D248](../../DECISIONS.md#d248--external-directory-aliases-only-along-frozen-tool-resolution),
[D249](../../DECISIONS.md#d249--complete-generic-preparation-review-within-ot005).

## Resumption and delivery status

The original topic `fix/ot005-preparation-tool-links` was created from develop at `a8efd10`. Initial source: `e2d62fe`;
D248 external directory amendment: `3e2ad45`; D249 review display: `be76164`; qualified release metadata: `d25548d`.
Integration on develop: `b50070d`; release PR #4 merged to main at `b0d035d`, tagged `v0.1.5`. The source topic was
deleted after integration. OT003's earlier 0.1.4 tag/evidence remain unchanged.

Delivery is complete: the 0.1.5 archive/checksum were published, downloaded and verified; OT005 is removed from the
queue. OT004/0.1.6 is next; no Metrics Records task is complete. Final publication details are recorded at the end.
Closing documentation is integrated into develop separately so the published tag/artifact source is not rewritten.

Local installation is a separate state: the previously authorized generation contains source `be76164` with 0.1.4
metadata. Publication left it running and did not install the 0.1.5 release, edit operator configuration or replay any
preparation/provider. A future upgrade to the published package is an explicit operator operation with stopped
service/writers, not outstanding work implicitly owed by this release request. The owner authorized publication
while their preparation was ACTIVE; completion of its real commands/receipt/activation remains unverified.

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

## Initial D247 implementation and qualification

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

## Manual preview failure — external tool-directory alias

The owner reported `409 target_identity_changed` from **Review preparation plan** after the local upgrade. Read-only
inspection found no preparation operation, an accessible canonical checkout root, and interpreter aliases resolving
to declared tools. Their chain traverses the external Homebrew directory alias `/opt/homebrew/opt/python@3.14`.
The D247 `tool_link` helper's parent-directory O_NOFOLLOW check rejects that component with `NotADirectoryError`
(errno 20); the API registry wrapper maps all OSError instances to the generic folder-identity diagnostic. Direct
read-only invocation of that helper reproduced the error without invoking tools/providers or changing data.

The external-directory case was missing from the synthetic acceptance matrix. D247 explicitly forbids every
directory-link traversal, so changing it requires an agreed design amendment. Proposed boundary: allow directory
aliases outside the checkout only along resolution of the explicitly declared executable, bind exact alias text/modes
and final executable hash, keep all checkout directory links refused and grant no extra writes/tree enumeration.
The owner explicitly approved that bounded amendment; D248 records the accepted boundary. Publication remains
gated on their eventual success report. The running service/data/configuration have not been changed during this diagnosis.

## D248 implementation after the manual failure

New plans/receipts add `tool_link_policy = external-directories-1`. The resolver opens each current parent with
O_NOFOLLOW, lstat/readlink-checks each component, and explicitly resolves/binds directory links only outside the
checkout. Both file and directory links count against the 40-link ceiling. Chain entries record raw path/text/mode,
mark directory aliases, and end at an exact declared, hash-bound regular executable. Dot/parent/trailing-slash
components retain their filesystem meaning, so a checkout directory redirect cannot be hidden by `..` and a regular
file cannot be used as a directory. No external tree is enumerated or made writable.

The marker and exact chain evidence survive confirmation, post-effect guards, receipt verification and explicit
recovery. Older D247 plans/receipts without the marker use their original strict resolver; pre-D247 evidence also
retains its old behavior. No historical bytes are rewritten. Broken new-policy link resolution now becomes the
existing localized unexpected-link diagnostic instead of leaking OSError into the generic folder-identity response.

The added synthetic Homebrew-style directory-alias fixture reproduced the old `NotADirectoryError` before this
amendment. Read-only inspection with the new resolver accepts the actual interpreter aliases and binds one external
directory alias per chain; no interpreter, preparation command or provider was invoked. Further cases cover
external link text/mode/target/broken/loop drift, confirmation and executor changes, the combined 40/41-link boundary,
trailing slash/dot file targets, protected API preview/confirmation and D247 recovery compatibility. Full results and
the subsequent authorized local reinstall are recorded below. No real-project success is claimed before the owner.

### D248 verification

- Full offline `pytest -q`: **2140 passed, 2 skipped, 29 subtests passed**, no failures, in **320.58 seconds**.
  The same 11 known TestClient/intentional duplicate-ZIP warnings remain. Fourteen new parametrized cases were added.
- After strengthening the existing new-policy recovery test with an external directory chain and policy-marker
  comparison, its focused serial rerun passed (**1 passed, 82 deselected**, 12.02 seconds).
- The Homebrew-style synthetic regression first failed with the same `NotADirectoryError` as the manual case;
  it now completes passive preview, confirmed execution, scope guards, receipt creation and receipt verification.
- Read-only resolver checks of the actual interpreter aliases succeeded, preserving declared tool binding. The full
  checkout snapshot also succeeded (**11843 entries, 4 bound read-only aliases**), using the saved declared tools and
  accepted plan. No real provider/preparation/command or database write was invoked. The owner still owns the real
  preview/execution test.
- The intermediate focused preparation run had **184 passed, 1 skipped** plus one fixture assertion failure from
  reading the API error envelope at the wrong key. The corrected envelope assertion passes in the full run.
- Specification, architecture, inline JSON data description and both affected flows are in parity. No API model,
  ORM/migration, dependency, configuration format, recipe source/fingerprint or version change. UI tests/visual QA
  and schema checks were not repeated for this backend-only amendment; the local installer built/checked the UI
  and qualified the installed package before restart, as recorded below.

### D248 local installation and restart

After the green full regression and source commit **`3e2ad45`**, continued the owner's authorized local test workflow.
Verified the current listener/launcher identity and idle database state (seven DONE jobs, six STOPPED processes, no
checkout lock, preparation operation or pending configuration activation). Stopped the launcher gracefully and checked
that its server exited and released loopback 8013. Captured a fresh private canonical-table/TOML hash baseline.

Ran the same offline clone upgrade with `--upgrade --writers-stopped --offline`, retaining all installation/data/
configuration/cache locations and the prior READY generation. New generation **`gen-be6f2fbf38754254b94003eb3e174d8d`**
is READY, with **0.1.4 metadata plus the D248 source correction**. The offline UI build/typecheck, exact package/
checksum/license checks, isolated installed-wheel synthetic journey and dependency compatibility check passed.
Installed `services/profile_preparation.py` matches source commit `3e2ad45` byte for byte. No migration was run.

Started the installed service detached with a private log/new access-key file; startup completed and HTTP root
returned **200**. Every SQLite table's canonical row hash and the private TOML path/content hash matched the stopped
baseline both after installation and after startup. No original/saved project configuration or private environment
was changed, no real preparation/provider/project command was invoked and no automatic retry or activation occurred.

The owner can sign in with the new key and repeat **Review preparation plan**. Success of their real workflow is
still unclaimed. Conditional release authorization is unchanged: only after they report success, prepare the separate
0.1.5 distribution archive, integration/release PR to main and GitHub publication. No push/merge/tag/release was done.

## Generic plan review display blocker (D249)

The owner's screenshot now loads the preparation preview, so the previous link-resolution blocker is passed for
that read. It does not establish successful preparation. File entries show `undefined` and the numbered step list
is empty. The current renderer assumes recipe `sha256`/`diff`/`content`, `step.label`/`id` and top-level `step.argv`;
generic plans instead supply `files = [{path, effect}]`, kind-based directories/executor/command/commit steps, and
`step.command.argv`. Generic mode text also incorrectly falls back to Django wheel installation.

Correct this bounded review surface under OT005's exact-confirmation acceptance (D249), preserving the existing
execution contract and separate confirmation/activation gates. No real preparation is run by this correction.

### D249 implementation and validation

Added a shared review renderer which distinguishes the existing generic contract from fixed recipes. Generic paths
show their possible write effect and explain that content is generated later; there are no fabricated file hashes,
diffs or full-content panels. Kind-based steps name the private directories, executor, preparation/validation commands
and technical commit. The executor's selection/reason/instructions/scope and each command's exact argv (including
argument boundaries), cwd/timeout, tool mapping/environment/limits are reviewable. Generic network/script declarations,
mode wording, plan evidence and consent use en/es text appropriate to an existing project. Journal step labels use the
same helper. Recipe v1/v2 labels, direct argv, fixed content/diff/hash review and all request gates are preserved.

- New regression initially reproduced the owner's `undefined` display in both languages (**2 expected failures**).
- Full frontend suite: **213 passed** (10 new component/request cases), including both languages, escaped argv,
  visible write effects/steps, generic modes, reason-plus-consent, renewed preview resets consent, exact saved
  configuration/preview hash/idempotency key, no activation, generic active journal and all four recipe versions.
- Typecheck and Vite build passed; the existing large-chunk advisory remains.
- Synthetic Chrome review: Spanish/light/default viewport and English/dark in a **390px content container** on the
  default viewport. Labels, scope, instructions and command arrays are readable; evidence expands with Return;
  reason plus consent enables confirmation. No confirmation was clicked. The synthetic harness blocks all real API
  actions; no actual provider, project command, service data or preparation was used for this visual QA. Temporary
  QA entry files/server/tab were removed/closed before packaging.
- Real mobile viewport/emulation, other browsers, screen readers, complete en/es/theme combinations and real
  preparation remain unverified. No fresh full Python/schema regression was run for this frontend-only correction;
  the D248 backend source is unchanged from its green 2140-case run. No API model/schema/generated types changed.
- Reviewed frontend/catalog/current-document diff; `git diff --check` passed. Local offline reinstall/package checks
  and the owner's repeat of the real review remain pending below; release authorization is still conditional.

### D249 local reinstall and readiness

Committed the source correction as **`be76164`** after the green frontend suite, reviewed diff and current task docs.
Continued the authorized local test workflow: verified the live launcher/listener and idle state (seven DONE jobs,
six STOPPED processes, no preparation, checkout lock or pending activation), stopped gracefully and captured a fresh
private canonical SQLite-table/TOML hash baseline. No real job was run or replayed.

The offline clone upgrade succeeded, retaining the previous generation and all data/configuration/cache locations.
Generation **`gen-d55da990c2734752bd9038a02b1b2cf3`** is READY, with 0.1.4 metadata plus the OT005 source fixes.
Exact artifact/license/checksum/member checks, isolated installed-wheel synthetic journey and `uv pip check` passed.
All **102 installed UI asset files** match `frontend/dist` byte for byte; the backend preparation source is unchanged
and matches the checkout. No migration, network download or configuration edit was performed.

The detached installed service started on loopback 8013. HTTP root and its entry JS return **200**, and the served
entry asset matches the qualified build. Every database-table/private-TOML hash matched the stopped baseline after
installation and startup. A new private session key is available for the owner's login. No real preparation/provider
or project command was invoked; no authorization checkbox or confirmation was submitted on the real project.

The owner should reload, sign in and review the now-visible scope/executor/commands. Their actual preparation success
is still pending; no archive/release PR/GitHub publication has been performed. OT005 remains in the delivery queue.

## Explicit 0.1.5 release authorization

The owner supplied a further screenshot showing active generic preparation: private directories DONE, executor
STARTED and later command/commit steps PENDING. They explicitly requested integration into the development branch,
a release PR to main, a distribution tar.gz and GitHub publication. This later instruction authorizes delivery now;
it supersedes the previous request to await their further success report. It is evidence that preview/confirmation
advanced into execution, **not** evidence of completed real commands, a successful receipt or activation. No private
project path, operation identifier, command content or run data is copied into release fixtures/notes.

Keep the installed service and its active preparation running. Release qualification uses only temporary synthetic
fixtures and fake clients; no new real command/provider, service restart, configuration edit or local reinstall is
part of publication. Prepare shared package/API/UI 0.1.5 metadata and lockfiles, OpenAPI/generated types, changelog
and English/Spanish download instructions on the topic branch. Integrate only after checks, and build/check final
publication artifacts from the release merge. Final PR/tag/archive/download verification evidence follows below.

### 0.1.5 candidate qualification

Shared 0.1.5 package/API/UI versions and lockfile project entries are prepared, with no dependency changes. Exported
OpenAPI differs only in `info.version`; client type regeneration completed with no type diff. CHANGELOG and en/es
README download/version instructions are in parity.

`build_distribution.py --offline` built `.local/releases/ot005-0.1.5-candidate` using the existing offline caches.
Typecheck/Vite build, exact distribution member/metadata/license/SHA256SUMS checks and `check_distribution.py`'s
isolated installed-wheel synthetic UI/API/session/definition/task/commit/restart/error/restored-evidence journey
passed. No Node is exposed to the installed synthetic service and no real provider is used. Frontend release suite:
**213 passed**; unittest **10 passed**; fresh temporary SQLite upgrade-to-head/Alembic check passed with no new
operations. The known large-chunk advisory remains. Final full pytest result and publication evidence follow.

Final pre-integration release regression: `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q`:
**2140 passed, 2 skipped, 29 subtests passed**, zero failures, **332.47 seconds**. The same 11 known TestClient and
intentional duplicate-ZIP warnings remain. Shared version/README/OpenAPI/client parity, local documentary links,
reviewed diff and `git diff --check` passed. No source, dependency or validation exception was needed for release.
The real-owner evidence remains ACTIVE preparation only; this qualification does not relabel it as completed.

## Published 0.1.5

- Release-preparation commit: `d25548d`; integrated into develop by `b50070d`.
- [PR #4](https://github.com/AcostaDDev/my-harness/pull/4), develop → main, merged with a merge commit at **`b0d035dfbbafc332d1bfb32e8644f76dfde6e1a6`**.
  The release tree matches the qualified integration tree exactly; parent one is the previous 0.1.4 release and
  parent two is the develop integration. Lightweight **`v0.1.5`** points to that exact release merge.
- Final distribution built offline from a clean detached worktree of the release merge, with the existing operator
  cache and no network installs. Exact artifact/member/metadata/license/checksum checks and isolated installed-wheel
  synthetic UI/API/session/definition/task/commit/restart/error/restored-evidence qualification passed again. The
  temporary build worktree was removed after verification; built artifacts remain outside tracked source.
- [GitHub Release v0.1.5](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.5) is published, not draft or prerelease. Assets:
  `my-harness-0.1.5-distribution.tar.gz` (**3,650,944 bytes**) and its `.sha256`.
- Archive SHA-256: **`0aef67c23548703e18c025170a2109f9bcaad216420b6fe2d44f72cf3db520ab`**.
  The `my-harness-0.1.5/` root contains exactly **13 files** matching the qualified distribution. Both GitHub assets
  match their local files byte for byte; the downloaded checksum and every archived file hash passed verification.
- main and develop were synchronized to the release merge; closing documentation is subsequently integrated on
  develop via a documentation topic. OT005 is removed from ONE_OFF_TASKS only after this published/downloaded
  verification. OT004 stays next for its own 0.1.6 patch; no P001 task is marked complete.

Final release qualification: **2140 pytest cases passed, 2 skipped, 29 subtests passed** (332.47 s); **213 frontend
and 10 unittest cases passed**; typecheck/build, OpenAPI/client/shared-version parity and fresh temporary Alembic
upgrade/check passed. The 11 known TestClient/intentional duplicate-ZIP warnings and Vite large-chunk advisory remain.
D249's synthetic Chrome scope/limits are recorded above; no new browser matrix or real-provider qualification is
claimed for publication.

The owner explicitly requested this release after reaching ACTIVE preparation. Neither that screenshot nor this
release qualifies its eventual real receipt/activation. Publication did not restart/reinstall the active operator
service, edit its TOML/data or start another real provider/project command; the same loopback listener remained
running afterwards. The separately installed 0.1.4-metadata build already contains OT005 code, and upgrading its
metadata/package to the published release awaits a future explicit operator request with stopped writers.
