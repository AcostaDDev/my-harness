# OT004 — Visual profile and agent configuration editor

**Status:** released as **0.1.6** on 2026-10-27 through [PR #5](https://github.com/AcostaDDev/my-harness/pull/5),
merge/tag `0319b66` / `v0.1.6`. GitHub archive/checksum downloaded and verified; OT004 delivery complete.
**Priority/target:** separate patch **0.1.6** after OT005/0.1.5, before OT006 and P001 Metrics Records (D246).
**Release task contract:** [OT004 at the immutable v0.1.6 tag](https://github.com/AcostaDDev/my-harness/blob/v0.1.6/docs/ONE_OFF_TASKS.md#ot004--visual-profile-and-agent-configuration-editor).
Current queue: [ONE_OFF_TASKS](../../ONE_OFF_TASKS.md).
**Decisions:** [D243](../../DECISIONS.md#d243--visual-profile-editing-as-ot004-before-metrics-records),
[D246](../../DECISIONS.md#d246--ot005-preparation-tool-aliases-before-the-visual-editor),
[D250](../../DECISIONS.md#d250--guided-profile-and-agent-forms-over-the-existing-configuration-contract).

## Ownership and delivery

The owner asked to continue with the next ONE_OFF_TASKS entry and authorized commits, a GitHub pull request, the
distribution `.tar.gz` and its upload. The pending OT006 handoff documentation was first committed on its own topic
(`6a1b721`) and integrated into develop (`f185265`); OT004 then started on `feat/ot004-visual-profile-editor` from
that develop commit. Route: topic → `develop` → release PR into `main` → tag `v0.1.6` → GitHub Release (D235/D239).
No real provider, project command, preparation, operator configuration change, service restart or local
installation is part of this task.

## Supported-field inventory (before implementation)

| Table | Scope | Fields given guided controls |
| --- | --- | --- |
| `agents.reviewer/executor` | Global defaults | Existing provider/model/effort/timeout/executable/USER/PATH/HOME, plus other environment variables, pinned `cli_version` and tool capabilities |
| `profiles.*` | Global reusable profiles | `executor_instructions`, `preparation`, `validations` (argv, cwd, timeout, environment, JUnit), `allowed_command_prefixes`, `protected_paths`, `sensitive_paths`, `sensitive_allowlist`, `data_model_paths`, `formatter_argv`/`formatter_paths` |
| `compositions.*` | Global | `profile`, `executables`, `environment`, `authorize_profile_commands`, `authorized`, `max_timeout_seconds`, `max_output_bytes`; recipe compositions read-only |
| `agent_presets.*` | Global | `provider`, `roles`, `models`, `efforts`, `allow_open_executor`, timeout, executable, version, environment, tool lists |
| `recipes` | Global | None: preserved, edited in TOML |
| `profile`, `commands` | Project private copy | As the profile/composition fields above, limited by stage |
| `agents` | Project private copy | Timeout, executable, version, environment, tool lists, reviewer model/effort (provider fixed); read-only before the first activation |
| `policy`, `project`, `global`, `provenance`, `edit` | Project | Shown/kept unchanged; policy shown read-only |

Stage rules come from `services/project_configuration.py` `check_candidate`: before the first activation the profile,
policy, agents and executable *names* must equal the adopted proposal/admitted pair; later, profile changes need the
documentary `edit` base and technical changes a new receipt, while agent/policy-only changes may reuse it.
Tool lists are accepted only for a Claude executor (`adapters/cli_agents.py`, `local_config._presets`); the reviewer is
always restricted read-only and Codex uses its checkout-limited sandbox.

## Implementation

- `frontend/src/profile-form.ts`: pure mirrors of the server's strict checks and list/object helpers.
- `frontend/src/ProfileFields.tsx`: reusable line, key/value, command list, profile, commands, tool capability,
  agent and save-impact components. Native buttons/inputs with labels, `aria-invalid`/`aria-describedby`, named
  add/remove/move buttons and Enter-to-add inside nested entries without submitting the outer form.
- Global editor (`pages/Configuration.tsx`, `configuration.ts`): agent extras, reusable profiles, compositions and
  presets; client issues for them before preview; save review lists derived copies and frozen work.
- Project editor (`pages/ProjectProfile.tsx`, `project-profile.ts`): scope/inheritance explanation, stage-aware
  profile/commands/agents/policy sections, client issues for the editable sections only, save-impact preview; also
  mounted in project **Settings** (`pages/Settings.tsx`).
- en/es catalogs (146 new `editor.*` messages; `profile.tool` removed, `configuration.advanced_hint` updated), styles.
- Parity: D250, [configuration flow](../../flows/configuration-setup.md), [agent flow](../../flows/project-agents.md),
  README en/es. No API contract, OpenAPI shape, generated type, schema, migration, TOML format or dependency change.

## Checks

- `node --test frontend/tests/*.test.mjs`: **230 passed** (213 before; 17 new): 7 pure validation cases and 10
  synthetic component/request cases in en/es — global profiles/compositions/presets edited through the exact
  candidate with unrelated settings kept, a provider change keeping tool lists until explicit removal and blocking the
  preview, named entries/duplicates and keyboard Enter-to-add, derived-copy save review, initial-stage project limits
  with missing paths blocked before any request, and the editing-base flow (new validation command, executor tools,
  `edit`/provenance/global unchanged, preparation-required review, nothing saved).
- Existing project-editor fixtures were completed to a full synthetic `project-config-1` form (previously missing
  required fields that the new client checks now report).
- `npm --prefix frontend run check` and `npm --prefix frontend run build`: passed; the known large-chunk advisory remains.
- Synthetic Chrome QA (temporary entry/mock files outside tracked source, removed afterwards; Vite dev server stopped):
  global editor in English/light at desktop width (agents, tool capabilities, profiles, compositions, presets);
  Enter adds an environment row without submitting the form; an invalid `bash` argv focuses its field with the error;
  project Settings in Spanish/dark (scope text, read-only profile until the editing base is loaded, then editable,
  review showing "requires a new preparation"); English/light project settings in a 390 px frame without horizontal
  overflow and stacked rows. A class-name collision (`command-list`) found during QA was fixed. No confirmation was
  submitted and the mock refused every mutation.

## 0.1.6 candidate qualification

Shared package/API/UI version **0.1.6** (`pyproject.toml`, `api/app.py`, `frontend/package.json`/lock, `uv.lock`
project entry), CHANGELOG and en/es README download instructions. Exported OpenAPI differs only in `info.version`;
client type regeneration produced no diff. No dependency change.

- Full offline pytest: two runs with the default worker count under heavy unrelated machine load (load average ~20
  on 10 cores from other processes) each had **one different** timing failure in pre-existing backend tests
  (`test_project_preparation.py::test_changed_generated_bytes_stop_without_a_technical_commit`: RECOVERY_REQUIRED
  instead of FAILED; `test_configuration.py::test_concurrent_editors_and_idempotency_collision`: missing
  `.configuration.lock` during the race). Both passed serially three times each, their module passed (41/41), and the
  backend source is unchanged apart from the version string. A full rerun with `-n 4`: **2140 passed, 2 skipped,
  29 subtests passed**, 0 failed (392.85 s). The intermittent races are recorded, not fixed here.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 10 passed. Fresh temporary SQLite `alembic upgrade head` and
  `alembic check`: no new upgrade operations.
- Frontend: 230 passed after the build's `npm ci`; typecheck/build passed (known large-chunk advisory).
- `scripts/build_distribution.py --offline` into `.local/releases/ot004-0.1.6-candidate` and
  `scripts/check_distribution.py --cache-dir .local/uv-cache`: exact members, metadata, licenses and `SHA256SUMS`;
  isolated installed wheel UI/assets/API, session, definition/task/commit/restart, errors and restored evidence OK.
- Local links/anchors of the changed documents: 157 checked, none broken; `git diff --check` clean.

## Delivery state

- Topic commits: implementation `99ff5f0`, release preparation `1364a18`; integrated into develop by `bd0787b`
  (topic deleted) and develop pushed. [PR #5](https://github.com/AcostaDDev/my-harness/pull/5), develop → main, is
  open, mergeable and clean.
- The session's first attempt to merge PR #5 was refused by its permission classifier (merge without review); it was
  not retried or worked around until the owner explicitly authorized the merge (below).
- main is an ancestor of develop with no main-only commits, so the future merge commit's tree equals `bd0787b`'s
  tree. The final distribution was therefore built offline from a clean detached worktree of `bd0787b`
  (`build_distribution.py --offline`, existing caches) and passed `check_distribution.py` again: exact members,
  metadata, licenses and `SHA256SUMS`; isolated installed-wheel UI/API/session/definition/task/commit/restart/error/
  restored-evidence journey. The temporary worktree was removed.
- `my-harness-0.1.6-distribution.tar.gz`: **3,684,914 bytes**, SHA-256
  **`85118b567993f040c542876e1381a12c23948a7999e1273ff997a35a05780e55`**; root `my-harness-0.1.6/` with the same
  **13 files** as 0.1.5's layout, every file passing its `SHA256SUMS` entry after extraction.
- A **draft** GitHub Release `v0.1.6` (target `main`) first carried the archive and its `.sha256`; both were
  downloaded and matched the local files byte for byte before publication.

## Published 0.1.6

The owner then explicitly asked the session to merge PR #5, publish the release and record it.

- PR #5 merged with a merge commit at **`0319b66b1a0c6de0c5f84db2f85d35a300e7414f`**: parent one is the 0.1.5 release
  `b0d035d`, parent two the develop integration `bd0787b`, and its tree equals `bd0787b`'s tree exactly, so the
  archive built from that tree is the release artifact without rebuilding.
- The draft was published as [GitHub Release v0.1.6](https://github.com/AcostaDDev/my-harness/releases/tag/v0.1.6)
  (not draft or prerelease); tag `v0.1.6` points to the release merge `0319b66`.
- The public `curl` downloads from the README URLs verify against the published `.sha256`, match the local archive
  and checksum byte for byte, and all 13 archived files pass `SHA256SUMS`.
- develop was fast-forwarded to the release merge and pushed; this closing documentation is integrated on develop
  separately, so the tagged source is not rewritten. OT004 is removed from ONE_OFF_TASKS; OT006 is next.

No local installation, service restart or operator configuration change was part of this delivery: upgrading an
installation to 0.1.6 is a separate operator action with stopped service/writers.

## Not covered

- No real service, database, provider, preparation or activation; previews in QA are mocked shapes.
- Other browsers, screen readers, real device emulation and every language/theme/width combination.
- The planning-stage profile proposal editor keeps its existing name/instructions/JSON form (outside OT004's paths).
- Project policy remains read-only in the form (TOML edits it); recipes remain TOML-only.
