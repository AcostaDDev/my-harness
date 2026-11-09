# State — my_harness

No managed blocks: this repository is developed by hand and is not registered in a harness. The work done before the
first public snapshot is summarized below as the starting baseline; its decisions are in [DECISIONS](DECISIONS.md).
Detailed history up to the P001 closure is kept in the [P001 archive](archive/phase-001/STATE.md).

## Work routing

Read [ONE_OFF_TASKS](ONE_OFF_TASKS.md) before [NEXT_STEPS](NEXT_STEPS.md); the one-off queue is **empty**
([D237](DECISIONS.md#d237--one-off-development-queue-before-phase-work); later one-offs branch from the latest release
on `main`, D261). **P001 Metrics Records is closed** (D266): released as **0.1.9**, installed on the operator machine
and archived in [`archive/phase-001/`](archive/phase-001/SUMMARY.md). **Active phase: P002 Continuous Mode** (target
**0.2.0** at its closure, D253). The owner adopted the expanded autonomous-mode/database-authority plan as the
evolving baseline (**v0.4, 29 tasks**,
[D268](DECISIONS.md#d268--p002-scope-complete-roadmap-autonomy-and-evolving-plan-baseline);
T018 split by responsibility into T018–T024 and the former T019–T023 renumbered T025–T029, [D303](DECISIONS.md#d303--t018-split-by-responsibility-and-later-p002-tasks-renumbered)).
**P002-T001 is completed as design** ([contracts](phase/P002-T001-contracts.md), [flows](phase/P002-T001-flows.md),
[threat model](phase/P002-T001-threat-model.md), D268–D279) on `docs/p002-t001-contracts`, committed and merged
into develop at the owner's authorization. **P002-T002 is completed** ([feasibility](phase/P002-T002-feasibility.md);
D280–D281 accepted) on `docs/p002-t002-feasibility`, merged into develop and pushed with it. **P002-T003 is
completed** ([runtime record](phase/P002-T003-runtime.md); D282–D283 accepted) on `feat/p002-t003-langgraph-runtime`,
merged into develop and pushed: LangGraph 1.2.18 added under D280, schema `0029_graph_continuations`, a harness saver and
segment runner exercised by synthetic graphs only; no product behavior uses it yet. **P002-T004 is completed** ([knowledge record](phase/P002-T004-knowledge.md);
D284–D285 accepted) on `feat/p002-t004-structured-knowledge`, merged into develop and pushed: schema `0030_structured_knowledge` with
seven knowledge tables protected by triggers, a pure core and a repository exercised by synthetic knowledge only.
**P002-T005 is completed** ([record](phase/P002-T005-domain-operations.md); Q1(a) and D286 accepted) on
`feat/p002-t005-domain-operations`, merged into develop and pushed: schema `0031_domain_commands`, a typed command
service with catalogue, capability policy and outcome records, owner API routes and a graph binding, exercised by
synthetic data; agent calls and delegated adoption stay refused. **P002-T006 is completed**
([record](phase/P002-T006-operations-tracing.md); G08 resolved by the owner's acceptance of D287) on
`feat/p002-t006-operations-tracing`, with the review findings corrected, merged into develop and pushed: schema
`0032_operation_journal` (76 tables), an operation journal behind `OperationPort`, fenced invocation operations
linked to the existing ledger, insert-only trace events with stored artifacts and read-only trace routes, exercised
by synthetic graphs and fake CLIs; no product graph launches agents.
**P002-T007 is completed and integrated into develop** ([record](phase/P002-T007-frozen-context.md),
D288), on `feat/p002-t007-frozen-context` from `c0ffc85`: schema `0033_frozen_context` (79 tables), explicit
canonical context rendering and fenced invocation boundaries, bounded knowledge lookup/search and exact delivery
evidence. Three technical-review findings are corrected (instruction headings, refusal backup and
known pre-GO failure receipts; [corrections](phase/P002-T007-frozen-context.md#8-technical-review-corrections));
re-review passed with no outstanding findings. Reviewed source commit `d3c4345` is integrated by the accompanying
merge; the owner authorized commit, merge into `develop` and push of `develop`. Release 0.2.0,
distribution/publication and installation remain pending.
**P002-T008 is completed and integrated into develop** on `feat/p002-t008-scoped-tools` from `3ad54b5`
([record](phase/P002-T008-scoped-tools.md), D289): scoped MCP relay, persisted caller verification, lazy discovery
and controlled lifecycle. Three review findings are corrected: isolated imports, persisted availability and
EOF/cancellation recovery. Source commit `625253e` is integrated by the accompanying merge; the owner authorized
commit, merge and push of `develop`, without asserting a separate technical re-review. Native qualification is
unchanged and production permissions remain denied until T010. Release 0.2.0, publication and installation remain
pending. **P002-T009 is completed and integrated into develop** on `feat/p002-t009-judge`
from `9ac1449` ([record](phase/P002-T009-judge.md), D290). Technical review identified malformed native output misrouted as an operational stop;
the correction is implemented and technical re-review passed (T009 record §7). The owner accepted G16's four prompts and E01–E21;
optional judge configuration/UI, duty contracts, immutable requests/rulings and accounted scoped invocations are
exercised synthetically. Native judge qualification is absent and productive delegation/permissions remain denied.
Source commit `350073c` is integrated by the accompanying merge; the owner authorized commit, merge and push of
`develop` after successful technical re-review. Release/publication/installation remain pending and unauthorized.
**P002-T010 is completed and integrated into develop**, source `d52fbb5` on `feat/p002-t010-permissions` from clean `c7f35cb`.
[G10 A/B/C](phase/P002-T010-permissions.md) accepted explicitly by the owner (D291); local verification and diff inspection are complete. Schema `0035_permissions` (85 tables), persisted permission authority/provider and frozen boundaries,
owner controls and existing process cancellation integration; synthetic evidence only, no native judge qualification.
Technical review found three blockers (owner-only tools, inherited delegable tiers and post-executor revocation);
the corrections passed independent technical re-review with no outstanding relevant findings
([record §7](phase/P002-T010-permissions.md#7-independent-technical-re-review-and-authorized-source-commit)).
The owner authorized its source commit, the accompanying merge into `develop` and push of `develop`
([delivery](phase/P002-T010-permissions.md#8-source-integration-and-delivery-record)). Release 0.2.0,
publication and installation remain pending. **P002-T011 is completed and integrated into develop**, source `616846d` on `feat/p002-t011-db-intake`; technical re-review passed on 2026-10-31, including all four findings; [evidence](phase/P002-T011-db-intake.md). The owner authorized its source commit, the accompanying merge and push of `develop`. Release 0.2.0, distribution/publication and installation remain pending and unauthorized. **P002-T012 is completed and integrated into develop**, source `6643ada` on `feat/p002-t012-knowledge-editing`; independent technical re-review passed, including all five corrections ([evidence](phase/P002-T012-knowledge-editing.md)). The owner authorized its source commit, the accompanying merge and push of develop. Release 0.2.0, publication and installation remain pending and unauthorized. **P002-T013 is completed and integrated into develop**, source `2c54fa9` on `feat/p002-t013-document-roundtrip`; independent technical re-review passed, including all four corrections; G09 accepted as D294 ([record](phase/P002-T013-document-roundtrip.md)). The owner authorized its source commit, the accompanying merge and push of develop. Release/publication/installation remain pending and unauthorized. **P002-T014 is completed and integrated into develop**, source `624631e` on `feat/p002-t014-task-execution` from `5e0b804`. The synthetic managed HTTP path publishes task code and a new documentary generation in one commit, applies typed owner gap clarifications at fresh attempt boundaries, and preserves correction budgets across owner-adopted task replacement families (D296, schema `0037_task_lineage`, 86 tables). Technical review identified a single-identity budget reset across new runs. The correction preserves all prior consumption and the smallest ceiling before any replacement link exists. Independent technical re-review passed, including the singleton budget correction and final complete checks. The owner authorized source commit, merge into develop and push after successful review. The accompanying merge integrates the reviewed source; push of develop is authorized. T015 local source status is recorded below; phase release/publication/installation remain pending. See the [task record](phase/P002-T014-task-execution.md).
**P002-T015 is completed and integrated into develop**, source `f7c5ce3` on
`feat/p002-t015-phase-lifecycle` from `c707986` (D298). Independent technical re-review passed, including
published closure recovery, archive history, native planning contracts and the final tag publication guard.
The full synthetic check passed on the final product source. The owner authorized source commit, merge and push
of develop. Release 0.2.0, distribution and installation remain pending.
[Evidence](phase/P002-T015-phase-lifecycle.md#independent-technical-re-review).
**P002-T016 is complete and integrated into develop**, source `26ccd21` on `feat/p002-t016-autonomous-roadmap` from `91d3a74`. Schema `0038_autonomous_runs` (93 tables); sealed owner-confirmed authorizations with one active run per root; `owner_delegated` children verified at the adoption and closure boundaries; persistent bounds, caps before inference, durable stops, per-project controls and the `autonomous-roadmap@1` graph (D299); G11/G12/G17 accepted with conditions (D300); the production route over T014/T015 with versioned readiness and task-contract prompts, supervisor continuation and judge requests bound to the parent's delegation (D301), verified by a synthetic managed journey; five technical-review findings, three remaining blockers and two third-review blockers (held review resume, T014 transaction boundary) and the final held-review window corrected (record §§8, 10, 12, 14). Independent final re-review passed. Release 0.2.0, distribution and installation remain pending. [Record](phase/P002-T016-autonomous-roadmap.md).
**P002-T017 is complete and integrated into develop**, source `9ebb800` on `feat/p002-t017-global-inbox` from `9e8995b`.
The owner accepted G13 (D302) and deferred a direct response to judge rulings. The global and per-project inbox,
read receipts, reusable conversation panel and guarded shortcuts are implemented with synthetic evidence; owner technical review passed after one judge-resolution correction.
Schema `0041_work_map_reads` (94 tables) on develop. **P002-T018 is complete and integrated into develop as design**
(`559487b`): the owner explicitly accepted the [work-map contract](phase/P002-T018-work-map-contract.md) and D304–D309 on
2026-11-04, with the source-record links added. G14 is resolved; T018 implemented nothing.
**P002-T019 (observed-step projection) is complete and integrated into develop**, source `e19cea3` on
`feat/p002-t019-observed-steps` from `ce244e4`. Independent final re-review passed on 2026-11-05 after both rounds of
corrections. The owner authorized source commit, merge and push of develop: every settled managed attempt records a pending marker in its
settlement transaction and a background projector derives bounded, sanitized `observed-step-1` steps with source-record
references, a retention guard while pending, recovery after restart, integrity failure on divergent replay and keyset
reads that survive retention and query-only restore (D305, D310). Schema `0040_observed_step_reads` (index only,
94 tables). Rendering is T021–T024 (T021 below).
[Record](phase/P002-T019-observed-steps.md). Release 0.2.0 via protected `main`,
distribution/publication and installation are pending. The operator installation remains 0.1.9.
**P002-T020 (work-map and trace read projections) is complete and integrated into develop**, source `b30a00c` on
`feat/p002-t020-work-map-api` from `c993564`. Independent final re-review passed, including historical assistance
after logical registry retirement; 20 focal tests and all 124 exact recovery cases independently passed in series
([final review](phase/P002-T020-work-map-api.md#10-independent-final-re-review--2026-11-05)). The owner authorized
source commit, merge and push of develop (D311): read-only
`GET /api/managed/map/` projections for L0–L4, related records and the activity summary, with status classes and
`unknown` fallback, R/E/J/H attribution, T017 bubbles, opaque scope/version/cursor tokens with `409 cursor_stale`,
source-record resolution with availability, root isolation and query-only archive parity; schema
`0041_work_map_reads` (seven read indexes, 94 tables); OpenAPI and client types regenerated. Synthetic evidence only.
Release 0.2.0, distribution/publication and installation are pending.
[Record](phase/P002-T020-work-map-api.md).
**P002-T021 (hand-drawn rendering foundation) is complete and integrated into develop after independent final
re-review and owner acceptance**, source `6b6a0ee` on `feat/p002-t021-map-rendering` from `6ba19eb` (D312, D313): rough.js 4.6.6 as a direct exact
dependency sharing mermaid's locked copy; the two Excalifont v0.18.1 subsets unmodified (hashes verified), with the
OFL 1.1 notice, packaged in wheel and sdist and served offline; orange/violet status tokens; an in-house SVG engine
(seeded rough.js shapes, layered layout, camera with wheel/pinch/drag/keyboard, zoom-enter and leave through the
existing router and history, focusable labelled nodes, reduced motion) exercised by a development-only synthetic
fixture at `/__map-fixture/`. The first-round browser measurements met D309 (80-node first render median 77 ms;
60 fps at 200 visible nodes); the corrected code (fit on large levels and phones, one navigation per gesture across
levels, held keys) was re-verified in the browser with Vite authorized (median 71.6 ms; 60 fps; 40/40 cards fitted on
a phone; one history entry per gesture). The font licence provenance is documented from the font's `index.ts` at the
same tag; no owner decision is pending for it. Not wired into the product (T022). The owner accepted T021 and
authorized commit, merge and push of develop, with personal visual review explicitly deferred until T022 connects
the map to real data (D313). The accompanying merge integrates reviewed source `6b6a0ee`; push of develop is authorized.
The owner confirmed the deferred visual acceptance at T022 integration. Release 0.2.0, distribution/publication
and installation remain pending.
[Record](phase/P002-T021-rendering-foundation.md#14-source-integration--2026-11-06).
**P002-T022 (work-map levels and home page) is complete and integrated into develop** as source `1149765` on
`feat/p002-t022-work-map` from `4535804` (D314): the map L0–L3 is the home page and the entry of the phase, task and run routes, with the existing
pages one `?view=list` toggle away (remembered per browser); cards, inspector (bottom sheet on narrow screens),
R/E/J/H circles with rays and the chat lane, T017 bubbles opening `InboxConversation` over the map, a paged run
selector, activity polling with stale-cursor recovery, a throttled polite live region, the read-only archive map
beside the run-id entry, the invocation header behind circles, and the shared `Status` on the six classes plus
`unknown` with a Python parity test. Synthetic evidence only. The first independent technical review found seven functional
defects (no follow-up before a task's first run, request lists losing actor or scope, an archive table without
access to details, concurrent invocations collapsed into one circle and no L3 chat lane, a page cap that cut the
history, evidence links leading back to the map, a stale stored view winning over a failed write); they are corrected
locally with regressions (record §9). The corrections add one read, the element request list
`GET /api/managed/map/projects/{p}/bubbles` (T020 attribution, exact scope and circle, archive parity, OpenAPI and
generated client); no schema, persistence, authorization or dependency change. The independent re-review reproduced
two remaining problems (a failed run-selector reread hidden behind an earlier empty read; L3 chats taken only from
the truncated global activity list, and none in archives); both are corrected locally with regressions (record §10),
adding the run's chat lane to the steps read (`chats`, `chats_truncated`, part of its version; OpenAPI and generated
client updated). Opening the synthetic frontend then showed two blocking browser defects: status and counter
overlapping on cards, and a closed mobile inspector whose hidden controls stayed in the Tab order. Both are corrected
locally (record §11): separate fitted card rows, and a closed sheet whose body is not rendered while its heading and
toggle stay in view, with the focus kept when the window narrows; browser geometry, keyboard and screenshot evidence
from the synthetic fixture (development server only). Browser measurements: first L2 render of the product map with
80 tasks median 165.8 ms (≤ 500 ms), engine pan/zoom at 200 visible cards 60 fps mean, 5th percentile ≥ 53.8 fps
(≥ 50 fps). The subsequent re-review reproduced quadratic label fitting and stale deferred inspector focus.
Both were corrected with regressions and fresh browser measurements (record §12). Independent final re-review
passed, and the owner confirmed visual acceptance of T022 and T021's deferred review (D313). The accompanying
merge integrates the reviewed source. Next: **P002-T023**. Release 0.2.0, distribution/publication and installation
remain pending.
[Record](phase/P002-T022-work-map.md).
**P002-T023 is complete and integrated into develop**, source `4a09d5d` on
`feat/p002-t023-trace-docs` from `e831a67` ([record](phase/P002-T023-trace-docs.md), D315–D316).
L4 graph/list, bounded lazy history, truthful evidence placement and the L1–L4 canonical documentation drawer
passed independent technical re-review after the navigation, graph-edge, drawer-width and placement corrections.
The owner then authorized this session to complete exact large-original reads by persisted sequence, with
verified UTF-8 bytes, T019's bound, retention and checkout-free restored consultation; that addition was tested
and self-reviewed here. The owner accepted the synthetic desktop/mobile visual review on 2026-11-07.
Final checks passed: 10 unittest tests, Alembic without new operations, 3,254 pytest tests (3 skipped, 29 subtests),
409 Node tests, TypeScript/Vite, documentation and whitespace. The owner authorized source commit, the accompanying
merge and push of develop. **Next: P002-T024.** Release 0.2.0 through protected main, distribution/publication
and installation remain pending. The operator installation remains 0.1.9.


**P002-T024 is complete and integrated into develop** as source `c1f28ab` on `feat/p002-t024-contextual-chat` from clean `develop` at
`dcef8ee` ([record](phase/P002-T024-contextual-chat.md), D307, D317). The separate reviewer talk entry carries a
removable, server-verified phase/task/run/step tag. Admission freezes bounded evidence with a T007 accepted
snapshot; `chat-turn@1`, its invocation operation and the existing accounting row run on the managed chat lane over
the read-only HEAD export. Only adapter-observed input records the element receipt; run evidence adds v3 without
changing old formats. Guarded refresh/removal, failure/replay, archive readers and en/es interaction are covered
synthetically. The first independent technical review found a missing talk button before a task's first run;
the frontend correction and both subsequent fixture fixes passed independent technical re-review. The owner
confirmed visual acceptance on 2026-11-09 and authorized the source commit, merge and push of develop.
Release 0.2.0 through protected `main`, distribution/publication and installation remain pending. The recorded
installation remains 0.1.9. The one-off queue remains empty.

**P002-T025 is complete and integrated into develop** as source `18bef36` on
`feat/p002-t025-accounting-efficiency` from `45805c4` (D318). Independent technical re-review passed.
Accounting groups and filters by workflow execution, invocation operation and parent autonomous execution.
It preserves project-scoped assistance and partial launch evidence, and L4 opens the exact ledger record.
The gate interpreter starts in isolation while the CLI retains its configured environment. Synthetic
verification covered settlement, aggregate parity and restored consultation. The offline benchmark
records payload bytes, local timings, exchanges and simulated completion.
[Contract and verification](phase/P002-T025-accounting-efficiency.md#source-integration--2026-11-09).
Release 0.2.0 through protected `main`, distribution/publication and installation remain pending.
The recorded installation remains 0.1.9.

**P002-T026 is complete and integrated into `develop`** as source `2fe92a4` on
`feat/p002-t026-installed-recovery` from `cd85462` (D319). Installed 0.1.9 schema migration, explicit installed
knowledge conversion, integrated restart recovery and format-3 backup upgrade have synthetic evidence. Head remains
`0041_work_map_reads` with 94 tables. The archive interruption and remapped knowledge identity fixes passed
independent technical re-review. The owner authorized source commit, merge and push of `develop` after review.
Release 0.2.0 via protected `main`, distribution/publication and installation are pending. The recorded installation
remains 0.1.9. The one-off queue remains empty. **Next: P002-T027.**
[Evidence and delivery stages](phase/P002-T026-installed-recovery.md#source-integration--2026-11-09).

See the [T017 record](phase/P002-T017-global-inbox.md).

Historical starting context:
[P002 handoff](archive/phase-001/P001-T006-qualification.md#p002-handoff).
Develop with `scripts/check` and `scripts/check-docs` (D260) on topic branches from `develop` (D235).
Completed one-off records are in the [one-off archive](archive/one_off_tasks/README.md); earlier non-phase notes
are in [project history](archive/project-history/README.md). [D267](DECISIONS.md#d267--archive-completed-one-offs-separately-from-active-phase-work)
keeps main integration separate from pending publication/installation. `docs/phase/` now contains current P002 work.

## Releases

Each release went through a PR from `develop` to the protected `main`, a merge commit tagged `vX.Y.Z` and a GitHub
Release with the self-contained archive and checksum verified after download (D235, D239).

| Version | Content | Release merge | Evidence |
|---|---|---|---|
| 0.1.9 | P001 Metrics Records (D232–D266); includes OT008's development checks | [PR #8](https://github.com/AcostaDDev/my-harness/pull/8), `5cc1bc1` | [summary](archive/phase-001/SUMMARY.md) |
| 0.1.8 | OT007 managed-run lease renewal and stream journals (D252) | [PR #7](https://github.com/AcostaDDev/my-harness/pull/7), `c005298` | [OT007](archive/one_off_tasks/OT007-task-run-lease.md) |
| 0.1.7 | OT006 preparation consumption and output guard (D251) | [PR #6](https://github.com/AcostaDDev/my-harness/pull/6), `a3e9794` | [OT006](archive/one_off_tasks/OT006-preparation-consumption.md) |
| 0.1.6 | OT004 visual profile and agent configuration editor (D250) | [PR #5](https://github.com/AcostaDDev/my-harness/pull/5), `0319b66` | [OT004](archive/one_off_tasks/OT004-visual-profile-editor.md) |
| 0.1.5 | OT005 read-only preparation tool aliases (D247–D249) | [PR #4](https://github.com/AcostaDDev/my-harness/pull/4), `b0d035d` | [OT005](archive/one_off_tasks/OT005-preparation-tool-links.md) |
| 0.1.4 | OT003 intake diagnostics, adoption guards, joint document review (D241/D244/D245) | [PR #3](https://github.com/AcostaDDev/my-harness/pull/3), `9985b0a` | [OT003](archive/one_off_tasks/OT003-intake-profile-diagnostics.md) |
| 0.1.3 | OT002 question-first answers and live activity (D240) | `64c21d0` | [OT002](archive/one_off_tasks/OT002-question-answers.md) |
| 0.1.2 | OT001 live agent configuration (D238) | `c606116` | [OT001](archive/one_off_tasks/OT001-live-agent-configuration.md) |
| 0.1.1 | Model selectors (D231) | `e252fdc` | [notes](archive/project-history/v0.1.1-model-selectors.md) |

The bounded activation fix after an empty failed intake (D236) is documented in
[failed-intake-activation](archive/one_off_tasks/failed-intake-activation.md).

## Current operator installation

0.1.9 installed offline from the verified public package into the default paths: generation
**`gen-455d272577f142df8ba411dcce1c0b16`**, READY; earlier generations retained. The database was migrated
`0027_profile_proposals` → `0028_usage_accounting` with a verified snapshot under `My Harness/pre-migration/`; legacy
rows and configuration files are unchanged and the accounting tables start empty (no backfill, repricing or billing
profile). The service remains **stopped**; start it explicitly with `scripts/start`. The failed OT006 preparation
stays `FAILED` (retrying needs `Write`/`Edit` configured for the Claude executor, an operator action not performed).

## Accumulated baseline

What exists and works at the first public snapshot, verified offline with temporary Git repositories, SQLite and
processes, fake agents and synthetic data unless stated otherwise. First local version complete within the scope
described in the [supported scope](../README.md#supported-scope-and-limits); first published as `0.1.0`/`0.1.1`, now
`0.1.9` (see [Releases](#releases)).
The real validation originally deferred in D151 now has the bounded evidence below.

- **Engine.** Package `my_harness` with an explicit context per project, frozen task contracts, planning by the
  reviewer or deterministic from `NEXT_STEPS`, the execute → format → validate → review loop with a correction limit,
  acceptance bound to the exact content and a reconcilable commit made by the harness (D052, D056, D129, D133).
- **Persistence and recovery.** SQLite schema `0028_usage_accounting` managed by Alembic (released in 0.1.9; the
  operator database is migrated; unreleased develop adds P002-T003's `0029_graph_continuations` and P002-T004's
  `0030_structured_knowledge`; P002-T005's `0031_domain_commands`; P002-T006's `0032_operation_journal`;
  T007's `0033_frozen_context`; T009's `0034_judge_contracts`; later tasks through T014's `0037_task_lineage`;
  T016 adds `0038_autonomous_runs`; T017 adds `0039_inbox_read_marks`; the T019 topic adds the index-only
  `0040_observed_step_reads`; the T020 topic, not yet integrated, adds the index-only `0041_work_map_reads`); idempotent job
  queue
  with leases, a lock per checkout, quarantine when frozen versions change and explicit confirmation of a stopped
  writer. Backup and query-only restore, explicit stream retention, explicit migration of existing databases with
  a verified snapshot (D150). Derived run projection written with each history (D144).
- **Agents.** Reviewer and executor, Codex or Claude Code in any combination, per-project presets; read-only
  reviewer with a typed output schema; automatic memory disabled; Codex writer limited to the checkout. Clients are
  discovered on an explicit `PATH`, checked against minimums (Codex 0.163.0, Claude Code 2.1.304) and a packaged
  capability policy, frozen per job and revalidated before every attempt (adapter `cli-14`, D173, D174). Native
  validations with JUnit reports; declared profiles in the operator TOML (D095), including the optional native
  formatter in `local-config-8` (D194). Formats 1–7 retain their rules. Explicit capability lists wrapped across
  help lines are read within their option; missing required values still block admission.
- **Phases and documents.** Unified documentation layout (D088): `AGENTS.md`, single `DECISIONS.md` with an index,
  managed blocks regenerated on every task commit, confirmed edits, READY check, unattended task batches,
  amendments, abandonment and a unified closure that archives the phase in `docs/archive/phase-NNN/` and opens the
  next one without tasks until its plan is confirmed (D034, D089, D091). `AGENTS.md` is injected into every frozen
  prompt (D094).
- **Creation and chat.** New projects through a definition conversation with drafts on disk and compare-and-swap
  writes (D075); conversational phase planning; chat over a read-only HEAD snapshot with deterministic commands and
  proposals that become confirmed tasks (D083). Projects folder chosen in the UI and creation intents with recovery
  (D116).
- **Recipes.** Confirmed, recoverable preparation of new Django (D119) and TypeScript web (D143) projects with a
  separate technical commit; v2 recipes follow the project's work language (`local-config-6`–`8`, D168).
  Resolving agent clients rebinds compatible completed receipts before admission, preserving the exact
  `project_environment_sha256`; missing or drifting receipts still block work.
- **Onboarding.** Static inventory of a committed tree, read-only conversation with private drafts, confirmed
  profile and documents, and a reconcilable documentation commit that adopts `P001` (D102). Support for the
  previous harness format is retired; earlier data stays readable and old jobs are quarantined (D161).
- **Languages.** Global interface language and default work language with version checks (D166); immutable work
  language per project root (D167); both frozen per job and attempt and sent to the agents as a sealed directive;
  generated documents in the work language (D169); interface, service and CLI texts in English and Spanish
  (D170–D172).
- **API and UI.** `/api/managed` behind a local session, Host/Origin checks and a CSRF header; React UI with URLs for
  projects, registry, creation, onboarding, documentation, phases, tasks, runs with paginated diffs, chat,
  statistics, settings and preferences; per-attempt metrics with provenance (D074). Query-only copies expose
  `read_only_archive` from their persistent mark and a standalone `/runs/:id` view with evidence, diff, JUnit and
  metrics, without project configuration, a checkout, execution polling or mutation controls
  ([flow](flows/backup-consultation.md)).
- **Distribution and operation.** Wheel and sdist with UI, migrations, catalogs and license/notice files, checked
  member by member with `SHA256SUMS`; `init-db`, `serve`, `migrate`, `check-config`, backup/upgrade, retention,
  `metrics-backfill`, explicit accounting operations (T003) and `diagnose-cli`; `scripts/dev` for development (D043, D051). No hosted CI: the suites and
  package checks run locally (D230); versioning policy in the [changelog](../CHANGELOG.md). The repository is public;
  the protected `main` only carries releases merged from `develop` by pull request, and work goes through topic
  branches into `develop` (D235).
- **Usage accounting (P001, 0.1.9).** One invocation record per managed attempt, executor preparation step and
  configuration assistance with an allowlisted `usage-capture-1`; pinned `metrics-reference-1` references and a pure
  Decimal calculator; optional `local-config-10`/`project-config-2` billing profiles frozen at admission; explicit
  previewed reference import, backfill and repricing cohorts; read-only `/api/managed/accounting/*` and the
  **Accounting** page (also on archives); format-3 backups with `backup-upgrade`. `metrics-1` and its endpoints are
  unchanged. Synthetic evidence only; missing evidence stays unknown (D254–D266,
  [summary](archive/phase-001/SUMMARY.md)).
- **Real-provider evidence.** Historical evidence before `cli-14`: first real use to a closed phase, four
  reviewer/executor combinations COMMITTED (D071), and Django recipe creation through four tasks and phase closure
  on macOS ARM64/Python 3.13. Current-adapter evidence (October 2026, same platform): Claude Code 2.1.310 reviewer
  and Codex 0.164.0 executor, installed wheels and disposable synthetic projects. Two existing Django repositories
  were onboarded with originals intact and idempotent confirmation; a documented clone reached COMMITTED using a
  v8 declared profile, six validations/13 JUnit cases and native formatting (two files unchanged). Spanish
  TypeScript v2 creation, offline preparation, one task COMMITTED, a valid READY check, closure/tag/archive and an
  empty active successor were verified. Two chat answers, a deterministic command without a model and a confirmed
  proposal left QUEUED without execution were verified. Backup/restored API and Chrome UI preserved run/diff/JUnit/
  metrics evidence. No real Django v2 creation, other current-adapter pair or full language matrix is claimed.
- **Preserved failures and limits of that evidence.** Two Django task attempts ended at REVISION_LIMIT; no failed
  result was repaired or relabelled as success. Two TypeScript phase checks failed before a separately authorized
  document edit and a valid check. The chat proposal remains QUEUED. Restored consultation leaves historical
  process identity uncertain and does not certify stopped writers. These runs do not qualify production projects,
  compare model quality or prove undocumented CLI effects; conditional compatibility is unchanged.
- **Limits.** Cooperative containment without operating-system isolation (D064); validations without timestamps;
  recipe manifests fixed after preparation; only macOS ARM64 tested; first use from a clean clone rehearsed
  with fake CLIs only (no sign-in or real model calls); installed UI reviewed in Chrome only (en/es, light/dark,
  desktop/mobile), without other browsers or screen readers.

## Guided installation and configuration baseline

- `scripts/install` builds from a clone or consumes a self-contained package, creates a venv per generation and
  verifies the isolated installed wheel before publishing READY. Paths/caches are chosen explicitly, with spaces
  supported; offline is default and network downloads require `--allow-network`. `scripts/start` verifies the
  receipt, initializes only an absent database, keeps instance locks/signals and serves the packaged UI without Node.
- Authenticated `/setup` works without TOML or inference. Global v9/project v1 private TOML versions live outside
  checkouts; SQLite owns saved/active/pending references and recoverable CAS intentions. Form/TOML editors show
  exact diffs; saving and activating are separate. Since `0.1.2` a confirmed global or project set applies in the
  running service at an idle boundary (D238); only worker-loop service fields under a running supervisor and legacy
  import promotion still need a restart.
- Creation from documents and onboarding from a static committed inventory can start without a stack composition.
  The reviewer proposes a profile after context; confirmed documentary commit/P001, saved tool paths, bounded
  preparation, fresh validation receipt and separate activation precede the first task. Other stacks are supported;
  Django/TypeScript recipes remain optional. Later manual editing and optional assistance retain those gates and
  freeze active clients/context; they cannot change machine-wide settings or earlier job snapshots.
- Formats 1–8 preserve entry and hashes. Explicit conversion keeps legacy authority until converted profiles are
  newly prepared and the complete set is confirmed/promoted. Backup format 2 includes configuration versions,
  working copies, intents and referenced evidence; T003's format 3 adds verified accounting records and an explicit
  `backup-upgrade` copy for older bundles. Query-only restore uses bundle bytes without original roots, clients or
  execution authority. Schema 0028 has 62 tables; data/flows are documented alongside the implementation.
- Installed first-use checks use fake Claude and Go tools, disposable projects and temporary Git/SQLite on macOS
  ARM64. Browser setup, protected HTTP journeys and visual checks are synthetic evidence; the real-provider scope
  above is unchanged. Release evidence is recorded per version below.

## Active phase — P002 Continuous Mode (target 0.2.0)

Automate closing/archiving a completed phase and opening/planning its successor under one explicit bounded
authorization, retaining stop conditions, READY and recovery guarantees ([ROADMAP](ROADMAP.md#p002--continuous-mode),
[D156](DECISIONS.md#d156--continuous-mode-between-phases-reserved-for-v020),
[D233](DECISIONS.md#d233--metrics-records-first-in-012-continuous-mode-second-in-020)). Opened at the P001 closure
without tasks. The owner broadened it to whole-roadmap autonomy with LangGraph orchestration, database-owned
structured knowledge, generated documents with explicit UI import, client-neutral discoverable tools, a configurable
judge, permanent revocable grants, correlated tracing, a global inbox and a task-instance graph; D268 supersedes
D156. The [discussion](phase/P002-autonomous-mode-discussion.md) and [design basis](phase/P002-design-basis.md) are
preserved. **T001 (completed as design, integrated into develop)** formalized the supersession map, authority invariants,
judge/permission/tool/autonomy/trace contracts, flows FL01–FL14 with guards and recovery, threats TM01–TM20, gates
G01–G17 with owning tasks and requirement coverage; SPECIFICATION §14 and ARCHITECTURE §13 distinguish the
remaining design from implemented foundations. **T002 (completed, integrated)** characterized LangGraph 1.2.18 (lockable with 27
additions and no pin change, offline install, re-executed nodes, silent graph-version drift, hosted tracing by
inherited environment) and the per-invocation MCP broker on Claude Code 2.1.312 and Codex 0.165.0 with 14 bounded
real runs; D280 (dependency set and placement) and D281 (transport and minimum capability contract) are accepted.
[NEXT_STEPS](NEXT_STEPS.md) holds plan v0.3. **T003 (completed, integrated)** added the LangGraph runtime foundation
(D282–D283), the only dependency adopted (D280); **T004 (completed, integrated)** adds structured knowledge
with immutable accepted revisions (D284) and canonical database instructions (D285); **T005 (completed, integrated)** adds typed
domain commands (D286); **T006 (completed, integrated)** adds the operation journal and
correlated trace events (D287); **T007 (completed, integrated)** adds frozen contexts,
canonical prompt rendering and exact receipts (D288). **T008 (completed, integrated)** adds (D289):
scoped tools and caller binding exercised with synthetic clients/permissions. T009 is completed and integrated (D290): optional judge profiles and duty contracts exercised synthetically; T010 is completed and integrated after technical re-review (D291); T011 is completed and integrated after technical re-review (D292; see its evidence); T012 is completed and integrated after independent technical re-review (D293); T013 is completed and integrated after independent technical re-review (D294); T014 is completed and integrated after independent technical re-review; T015 is completed and integrated after independent technical re-review; T016 is complete and integrated after independent final re-review (D299–D301); T017 is complete and integrated after owner technical review (D302). T018 is complete and integrated as design (D304–D309; the owner accepted the work-map visual direction as D297, [visual direction](phase/P002-T018-visual-direction.md)). T019 is complete and integrated as source `e19cea3` after independent final re-review (D305, D310). T020–T024 are complete and integrated. T025 is complete and integrated as source `18bef36` (D318). T026 is complete and integrated as source `2fe92a4` after independent technical re-review (D319). T027–T029 remain planned (plan v0.4, D303). No OpenCode adapter exists, and installed behavior remains 0.1.9.
