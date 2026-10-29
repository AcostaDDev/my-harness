# Specification — My Harness

Functional requirements and business rules in force. Technical detail is in [ARCHITECTURE](ARCHITECTURE.md), data in
[DDBB-DIAGRAM](DDBB-DIAGRAM.md), behavior step by step in [flows](flows/task-run.md), and progress in
[ROADMAP](ROADMAP.md) and [STATE](STATE.md). Decisions are cited as `DNNN` from [DECISIONS](DECISIONS.md).

## 1. Purpose and scope

A local application to configure, run, observe and control a development harness assisted by AI agents, on new or
existing repositories. Its goal is to shorten the time from an idea to a verifiable version without losing control:
the harness prepares decisions and shows evidence; the user accepts requirements, architecture, sensitive
permissions and results.

- Single user, local, initially for macOS. The UI runs in the browser; a local service accesses the repositories and
  launches the tools. Models may need a connection: local does not mean offline inference.
- The user's subscriptions are used through the Codex and Claude Code CLIs; API access is not assumed.
- Out of scope: multiple users, cloud, parallel writers on one checkout, a plugin marketplace, a visual flow editor,
  a generic web terminal and automatic deployment (see §10).

## 2. Domain concepts

| Concept | Meaning |
|---|---|
| Project | Registered Git checkout with policy, work language and documents; executable profile after confirmed activation |
| Phase | ROADMAP milestone (`PNNN`) with objective, exit criteria and tasks; a SQLite record |
| Task | Bounded unit (`PNNN-TNNN`) with a frozen contract: objective, paths, criteria and validations |
| Run | Tracking of a task or operation (check, closure, transition, chat, definition, document edit) |
| Attempt | One concrete invocation of an agent; never overwritten |
| Review | `ACCEPT`, `REVISE` or `BLOCKED` verdict on an exact version of the work |
| Validation | Profile and task commands, with JUnit reports when they exist |
| Permission | Exact request by category (files, tools, network, product, acceptance) and its resolution |
| PromptVersion | Immutable template, resolved by scope and frozen in each attempt |
| Conversation | Project chat, definition of a new project, onboarding of an existing one or planning of a phase |
| Managed document | Markdown of the documentation contract (§6); its managed blocks are projections of SQLite |
| Artifact | Diff, stream, contract, report or copy, referenced by path and hash |

Relations: project → phases → tasks → runs → attempts. Reviews, validations, permissions and artifacts are bound to
the run and, when relevant, to the exact attempt.

## 3. Roles

- **Reviewer** (Codex or Claude Code, chosen by the user): plans tasks, reviews, evaluates phases, answers in the
  chat and leads definition, onboarding and phase planning. Always read-only
  ([D052](DECISIONS.md#d052--reviewer-and-executor-with-provider-model-and-effort-chosen-by-the-user)).
- **Executor** (Codex or Claude Code): the only writer of the checkout. The reviewer sets its model and effort per
  task, within a catalog or in open mode depending on the project.
- **Harness**: decides states, gates, commits, tags, archives and managed blocks deterministically. No agent changes
  mechanical states or makes commits.
- **User**: accepts definitions, plans, permissions, commits, closures and document edits by their exact hash.

## 4. Functional requirements

All the requirements below are implemented. Evidence with real providers is limited as described in the README's
[supported scope](../README.md#supported-scope-and-limits): the current adapter has been exercised on synthetic
Django onboarding/declared-profile work, Spanish TypeScript v2 through phase closure, chat and backup/restore
consultation with a Claude Code 2.1.310 reviewer and Codex 0.164.0 executor. Four-combination evidence predates the
current adapter; Django v2 creation and a full language matrix have offline evidence only.

| ID | Capability | Observable result |
|---|---|---|
| F01 | Register a project | From UI with canonical root, trust and work language; v9 can begin without profile/composition; legacy `[[projects]]` remains supported |
| F02 | Create a project from scratch | Projects folder chosen in the UI, brief, conversation with the reviewer, drafts on disk with CAS, acceptance and root commit with P001 ([flow](flows/project-creation.md)) |
| F03 | Onboard a repository without a harness | Static inventory of HEAD, reverse-engineering conversation with private drafts, confirmed documents and profile, documentation commit that adopts P001 ([flow](flows/project-onboarding.md)) |
| F04 | Navigate projects, phases, tasks and runs | Own URL per resource, bounded and paginated loading |
| F05 | Run a task | Planning → execution → validation → review → acceptance or correction → harness commit ([flow](flows/task-run.md)) |
| F06 | Manage prompts | Versions, diff, validated variables, activation and rollback; snapshot per attempt |
| F07 | Resolve blockers and permissions | Reason and evidence; grant or deny an exact request; revalidate or retry |
| F08 | Control phases | Check, reconciliation, questions, unattended batch, amendment, abandonment, closure with a tag |
| F09 | Close and archive a phase | The protocol of §7 in a single flow after READY ([flow](flows/phase-lifecycle.md)) |
| F10 | View and edit documentation | Safe viewer and edits with a confirmed diff and a harness commit ([flow](flows/documents.md)) |
| F11 | Talk to the reviewer | Chat over HEAD without waiting for the executor; proposals → confirmed tasks; deterministic commands ([flow](flows/chat.md)) |
| F12 | Inspect tests | JUnit suites and cases, pass/fail per task and evolution per phase |
| F13 | Metrics and statistics | Tokens, turns, models, efforts, durations and equivalent cost with provenance |
| F14 | Recover and preserve | Backup and query-only restore with standalone run evidence UI without a checkout, explicit log retention, recovery after a crash |
| F15 | Local distribution | Wheel with UI and migrations, `init-db`, `serve`, explicit `migrate`, local session |
| F16 | Declared profiles | Own profile proposed after context, edited/saved/prepared/activated through UI; legacy declared TOML profiles remain supported ([D095](DECISIONS.md#d095--declared-profiles-in-local-config-4)) |
| F17 | Project instructions for the agents | `AGENTS.md` included in the frozen context of every attempt ([D094](DECISIONS.md#d094--agentsmd-in-every-frozen-prompt)) |
| F18 | Choose a projects folder | Root chosen explicitly in the UI and persisted; lets the service create new children without the AI deciding their location |
| F19 | Agents configurable per project | Providers and the reviewer's model and effort in the UI; the concrete executor selection is made by the reviewer ([flow](flows/project-agents.md)) |
| F20 | Prepare a stack from scratch | New child with Django or TypeScript web scaffold, environment, dependencies and validations through a confirmed recipe ([flow](flows/project-preparation.md)) |
| F21 | Interface and work language | Global defaults in en/es: a mutable global interface language for UI and conversation, and an immutable work language per project for documentation and code, both frozen per job and attempt ([flow](flows/project-work-language.md)) |
| F22 | Extensible CLI compatibility | Automatic discovery without a pin; minimums and capabilities per provider and role, diagnostics, verified and candidate versions ([flow](flows/cli-compatibility.md)) |

Project mode: **managed**. Projects are only created from scratch or onboarded from code without a harness;
registering or reopening a project that is already managed keeps its authority. Two engines never write the same
checkout. Earlier harness formats are not observed or imported
([D155](DECISIONS.md#d155--two-entries-to-start-a-project), [D161](DECISIONS.md#d161--retirement-of-the-previous-harness-support)).

## 5. Business rules

1. A single writing execution per checkout; chat turns read a HEAD snapshot without taking the lock.
2. Contract, context, prompts, policies, profile, versions and language pair are frozen per attempt; each attempt is
   a new session. Resuming work does not resume a conversation.
3. Review, validation and acceptance are bound to the exact content (base, tree, diff, index). A later change
   invalidates the evidence before the commit; the commit contains only what was reviewed plus declared mechanical
   updates.
4. No model fallback, retry or additional consumption behind the user's back. An authentication, quota or environment
   error stops.
5. Requested, reported, derived, measured and absent data are distinguished; null is not zero; cumulative and
   incremental values are never added together, and quota is never inferred.
6. Five separate decisions: file scope, tools, network, product or architecture changes and acceptance. One grant does
   not widen another, and prompts cannot grant them.
7. Intent persisted before every external effect and reconciliation after a crash. An expired lease does not prove
   the process died: releasing it requires confirming that the writer stopped.
8. Every document write of the harness (edit, export, creation, transition, onboarding) is confirmed by the hash of its
   preview and never overwrites foreign bytes (CAS).
9. A phase closes only with a current READY check and its own authorization; the unattended batch never checks or
   closes.
10. Service on loopback only, with a local session, exact Host/Origin and CSRF; Markdown and logs without executable
    HTML.
11. Profiles declare commands and paths; an allowed prefix is not a security boundary. Containment is cooperative:
    there is no operating-system isolation ([D064](DECISIONS.md#d064--cooperative-containment-without-operating-system-isolation)).
12. Interface language is global and governs UI, messages and human-facing answers; the work language is chosen when a
    project is created or onboarded, is immutable and governs documentation and code. Changing a default affects only
    future projects; changing the interface language affects only new interactions.

## 6. Documentation contract of managed projects

Mandatory structure for every project, this repository included
([D088](DECISIONS.md#d088--unified-documentation-contract), [D089](DECISIONS.md#d089--mandatory-layout-and-template)).

| Path | Content | Authors |
|---|---|---|
| `AGENTS.md` | Canonical source for agents (≤60 lines): discovery order, unbreakable rules, base test and lint commands | Creation, onboarding and user |
| `CLAUDE.md`, `GEMINI.md` | Wrappers (≤15 lines) that import `AGENTS.md` | Creation, onboarding and user |
| `README.md` | For people: what it is, installation, use, tests, documentation map | Tasks, reconciliation and user |
| `docs/SPECIFICATION.md` | Functional requirements and business rules | Creation, authorized tasks and user |
| `docs/ARCHITECTURE.md` | Stack, patterns, modules and conventions | Creation, authorized tasks and user |
| `docs/ROADMAP.md` | Phases `## PNNN — title` with objective and exit criteria; status and archive link of closed ones | Creation, planning, user; status by the harness |
| `docs/STATE.md` | Snapshot of the current phase: accumulated baseline (≤12 KiB) and active phase (total ≤24 KiB) | Harness, reconciliation and user |
| `docs/NEXT_STEPS.md` | Tasks `## PNNN-TNNN — title` of the active phase (≤48 KiB) | Phase planning and user |
| `docs/DECISIONS.md` | Single record `## DNNN — title` with an index | Reconciliation, reviewer (approved proposals) and user |
| `docs/DDBB-DIAGRAM.md` | Entity-relationship schema in Mermaid `erDiagram`, or "No persistence" | Executor (parity) and user |
| `docs/flows/*.md` | Mermaid diagrams per module or feature (`stateDiagram-v2`, `sequenceDiagram`, `flowchart`) | Executor (parity) and user |
| `docs/phase/` | Work artifacts of the current phase | Executor and user |
| `docs/archive/phase-NNN/` | Closed phase: STATE, NEXT_STEPS, REVIEW, SUMMARY and whatever was in `docs/phase/` | Harness only |

Rules:

- **Discovery.** A session starts by reading `AGENTS.md`, then STATE, NEXT_STEPS, the active phase's section of
  ROADMAP and the relevant parts of SPECIFICATION and ARCHITECTURE. From DECISIONS only the decisions the task cites,
  or the index to look for precedents. `DDBB-DIAGRAM.md` and `flows/` when the task touches data or flows. The
  archive only when cited.
- **No invention.** Nothing beyond the specification; on an inconsistency between documents or with the code, ask
  before deciding.
- **Diagram–code parity.** A change to data models or business flows updates `DDBB-DIAGRAM.md` or `docs/flows/` in
  the same task; the reviewer rejects a delivery that does not. If the profile declares `data_model_paths`, a diff
  that touches them without the data diagram is not accepted even if the reviewer accepts
  ([D090](DECISIONS.md#d090--executor-paths-diagram-parity-and-decision-proposals)).
- **Decisions.** The executor does not add decisions: it proposes them in its output and the reviewer or the
  reconciliation consolidates them.
- **Protected.** STATE, NEXT_STEPS, ROADMAP, DECISIONS, `docs/archive/**`, AGENTS, CLAUDE and GEMINI are outside
  executor contracts; the reconciliation edits the prose of STATE, NEXT_STEPS, ROADMAP and DECISIONS.
- **Managed blocks.** Blocks between `harness-local:managed-*` comments are written only by the harness; the
  surrounding prose is kept. Exceeding a budget produces a warning and a reconciliation, never a truncation.
- **Languages.** Canonical file names and markers are English; the parsers accept English and Spanish headings and
  labels. Documents generated by the harness follow the project's work language.

## 7. Phase closure

After a READY check and the closure authorization, in a single deterministic flow
([D091](DECISIONS.md#d091--unified-closure-and-archive-with-later-planning)):

1. Tag on the evaluated HEAD ([D032](DECISIONS.md#d032--phases-in-sqlite-and-ready-bound-to-exact-content)).
2. `docs/archive/phase-NNN/` with the final snapshot of STATE and NEXT_STEPS, REVIEW and SUMMARY generated from
   SQLite, and all the content of `docs/phase/`.
3. STATE reset to the compact accumulated baseline and the active phase N+1; NEXT_STEPS with the objective of N+1
   taken from ROADMAP and no tasks until it is planned; `docs/phase/` empty.
4. ROADMAP marks N as completed with a link to `archive/phase-NNN/`.

Everything happens in one reconcilable commit; if anything does not match (dirty checkout, documents different from
their baseline, existing archive, pending work), it is refused before writing. If ROADMAP has no more phases, the
phase is only archived. Abandonment uses the same reconcilable archive without READY or tag. A check returns
`NEEDS_RECONCILIATION` if STATE exceeds 24 KiB or its accumulated baseline exceeds 12 KiB. The later plan of N+1 is
confirmed by hash: it writes NEXT_STEPS, regenerates the state blocks and creates a new version of the phase
definition, keeping the previous one ([D034](DECISIONS.md#d034--unattended-batches-versioned-definitions-and-deterministic-annotated-tags)).

## 8. The two entries

The product has two entries: create from scratch (F02) and onboard existing code without a harness (F03). Registering
or reopening a project already managed is a normal operation on its existing authority. A repository with documents
or history of another harness is refused; it is never silently converted.

Onboarding inventories a non-empty HEAD (stack, entities, routes, tests and CI) and proposes a declared profile that
the operator adopts after reviewing documents and command evidence. The reviewer reads a read-only export of the frozen HEAD and proposes the
eleven contract documents and flows, citing facts and inferred decisions, and asks about what cannot be deduced. Its
proposals are applied with CAS to private drafts next to SQLite, without writing the checkout or running code or
commands ([D102](DECISIONS.md#d102--onboarding-by-reverse-engineering-over-head-with-private-drafts)).
In onboarding, definition and phase planning the reviewer's open questions come first: each has its own answer field,
and one answer, a selection or all prepared answers are sent as one explicit turn with the exact composed message.
Sending answers neither resolves a blocking question nor enables confirmation; only a later answered turn that stops
asking it, or an explicit deferral with a reason, does
([flow](flows/project-onboarding.md#answering-the-reviewers-questions),
[D240](DECISIONS.md#d240--question-first-answers-and-the-live-activity-rail)).

The preview requires the documents, P001 and its criteria, blocking questions resolved or deferred, and a clean
checkout and index on the original HEAD. It confirms documents and profile by hash, reason and Idempotency-Key; it
keeps the inventory, the summary and the replaced originals byte for byte in `archive/phase-000/`. It seals an intent
before writing and creates a single reconcilable documentation commit, adopting P001 ACTIVE atomically. Repeating the
confirmation does not duplicate operations; a crash requires confirming that the writer stopped and reconfirming the
exact intent. The documentary commit does not install or run project tools. In v9, the application then saves
private project TOML through a separate confirmed operation, prepares the exact plan and activates only after
a verified receipt. Legacy composition configuration remains operator-owned. See [§12](#12-guided-configuration).

The Git boundary requires complete local objects and `--no-lazy-fetch` from the first command; it refuses clean or
process filters (includes too) before capturing and sealing, refuses gitlinks in HEAD or the index before querying
children, checks ignored targets and compares blobs by hash. Recovery repeats the same guards without modifying the
intent.

Data and queued work of the retired support for earlier harness formats are kept inert: old routes answer 404 after
the access guards, old commands fail on argument parsing without opening data, and retired or ambiguous jobs are
quarantined before any invocation or write ([compatibility](flows/legacy-compatibility.md)).

## 9. Non-functional requirements

- Browsing recorded data never invokes models or needs the network. The frontend does not access the disk or run
  commands.
- Lists, logs and diffs are paginated with explicit limits; nothing reads a whole history to paint a view.
- Reproducible installation with lockfiles and exact versions; distribution as a wheel with assets and migrations;
  Node only to build the UI.
- Logs with explicit retention that keeps contracts, permissions, verdicts and metrics.
- Consistent backup of SQLite and artifacts verified by hash; restore into a new folder, query-only. The persistent
  restore mark enables a standalone `/runs/:id` view (evidence, diff, JUnit, jobs, attempts, events and metrics),
  without project configuration, checkout reads, supervisor, pending submission replay, execution polling or mutation
  controls. API mutations still return 409; consultation never confirms stopped writers or resumes historical jobs
  ([flow](flows/backup-consultation.md)).
- Declared-profile formatting is optional in `local-config-8`, uses authorized commands and contract-allowed files
  before validation/review, and does not run on revalidation; older formats retain their rules (D194).
- Resolving agent clients for a prepared project rebinds the compatible receipt from its existing authority before
  admission. It preserves the exact environment digest and work language; missing receipts, changed recipe config
  or protected/tool drift still block before queuing ([preparation](flows/project-preparation.md)).
- Explicit migrations with a prior snapshot; CLIs below the minimum or with incompatible capabilities are blocked with
  a diagnostic, and later releases that meet the known contract are admitted with conditional compatibility
  ([D174](DECISIONS.md#d174--automatic-clients-and-conditional-compatibility)).
- The history is traceable at the application level; it is not a tamper-proof record against the machine's owner.

## 10. Global acceptance criteria

1. Repeating the creation from scratch or the onboarding and their confirmations does not duplicate projects, phases,
   jobs or commits, and does not invent absent data.
2. A task goes through execution, a failing test, correction, review and commit with a complete history.
3. Two simultaneous requests do not create two writers on the same checkout; neither does a restart with a live
   process.
4. A denial does not run the tool; an expired or duplicate approval is not reused.
5. Restarting the service during an execution keeps the evidence and does not repeat effects blindly; a crash after
   the commit reconciles it.
6. Editing prompts does not change the version recorded in a past attempt.
7. A change after the reviewed diff invalidates the acceptance before the commit.
8. Closing a phase requires current validation and authorization, and archives the phase without losing bytes (§7).
9. A different stack profile works without changes to the core.
10. A chat request ends linked to a task and its result.
11. Creating an empty project produces documents, structure and a first runnable task; onboarding code without a
    harness adopts P001 and the documentation contract while keeping the code and the originals. Both continue as
    managed projects.
12. Backup and restore recover states, references and evidence verified by hash.
13. An agent answer outside its schema stops the run with a diagnostic and keeps the output. Cycles without changes
    stop with a reason. Watching a managed run resumes its event cursor without gaps or duplicates.

Product metrics: setup time, time to the first accepted task, manual interventions, recovered errors, consumption per
task including failures, and corrections after acceptance. A speed improvement without equivalent quality does not
prove a shorter time to market.

## 11. Out of scope

Multiple users, cloud, parallel writers in one project, App Server or Agent SDK integration until compatibility and
authentication are verified, a portable `project.yaml`, physical operating-system
isolation, and providers other than Codex and Claude Code (Gemini CLI only gets the `GEMINI.md` wrapper). Any real use
of providers by the harness on a project requires the user's own configuration and confirmations.

Autonomous execution of a whole authorized roadmap, database-owned project knowledge and the related authority
redesign are accepted design for v0.2.0 and are not implemented
([§14](#14-p002-autonomous-mode-and-project-authority-accepted-design-not-implemented),
[D268](DECISIONS.md#d268--p002-scope-complete-roadmap-autonomy-and-evolving-plan-baseline), [ROADMAP](ROADMAP.md)).

## 12. Guided configuration

The installed application offers deterministic authenticated setup before any client or stack composition exists.
Users choose clients, Git identity and allowed roots in forms or validated TOML; version/help checks are explicit
and never prove inference or undocumented client effects. Local credentials stay with their provider clients.

Global `local-config-9` and own `project-config-1` are private versioned files outside checkouts. Save, prepare and
activate are separate exact-preview confirmations. SQLite owns revision references; CAS and durable intentions
support reconciliation without replacing earlier snapshots. Global changes cover derived project copies; a
confirmed set applies in the running service without restart or new login ([D238](DECISIONS.md#d238--live-configuration-switch-at-an-idle-boundary)): before confirmation
the preview stages the complete candidate (client preflight with exact PATH/environment and every registered
project) and names refused settings. With no current work it switches at once; otherwise it shows **Apply when
current work finishes** with the waiting jobs, preparations, phase operations, acceptances, commits or assistance,
and switches at the first idle boundary, while admitted work keeps its frozen settings and new work uses the active
set until then. A failed switch is withdrawn and leaves the previous set active. Only worker-loop service fields
under a running supervisor or a legacy import need restart, named before confirming. Project changes keep their
documentary barriers. Empty failed intake conversations with no output, draft changes or surviving proposals/edits
are not pending adoptable work; answered, uncertain or substantive intake work retains the project barrier
([D236](DECISIONS.md#d236--empty-failed-intake-turns-are-not-pending-configuration-work)).

Definition and onboarding can converse without a stack profile. Documentary context/static HEAD inventory precedes
proposals with meaningful validations and evidence per command. Proposal adoption, documentary commit/P001,
completed private tool configuration, bounded technical preparation and independent activation precede task admission.
Profile adoption requires the exact bound documents already applied to drafts. Its preview identifies missing or
changed document paths without labelling a valid candidate invalid solely because documents are not yet applied.
Informational pending notices do not block adoption; blocking questions must be resolved or explicitly deferred
with a reason. Frozen context/versions, HEAD/inventory, valid drafts/candidate and exact confirmation remain required
([D244](DECISIONS.md#d244--ot003-includes-the-profile-adoption-blockers-found-in-manual-testing)).
Definition/onboarding offer a joint review of current document proposals, with exact diffs, optional exclusions and
one explicit consent to apply the selected documents to drafts. Existing per-document CAS actions run in order;
errors/uncertainty stop the sequence and report acknowledged progress without automatic retry or rollback. The
profile and documentary commit remain separately confirmed (D245).
The reviewer stays read-only; the executor has only the confirmed preparation scope and no general global writes.
A receipt binds configuration, tools, commands, protected content and stable environment; failures do not qualify it.
New generic preparation plans also bind pre-existing read-only file-link chains outside private local paths when
these resolve to an explicitly declared, hash-bound executable (D247/D248). Exact chain paths/link bytes/modes are
preserved through preview, execution, recovery and receipt verification. New plans explicitly bind external directory
aliases only along that tool chain (D248); checkout directory links, unbound targets, broken/looping chains and
protected-path links are refused. The 40-link ceiling counts both file and external directory aliases. This grants
no writes or accreditation of the rest of an existing environment; stable environment evidence still comes only from declared `environment_paths`.
Old plans/receipts retain their policy and frozen bytes.
Generic preparation review shows writable path/effect pairs, the executor scope/instructions and exact nested commands
with cwd/timeouts/environment; it does not fabricate recipe content, diffs or file hashes. Generic network modes have
profile-specific wording. Fixed recipe review and reason/consent/hash/configuration gates remain unchanged (D249).

Later editing preserves active authority until confirmed activation. Technical changes require committed current
documents and new preparation; optional assistance uses frozen active clients and only authorized context. Applying
a suggestion changes the draft. Legacy formats 1–8 retain original entry/hashes; explicit conversion requires newly
prepared converted profiles before activation. Configuration backup includes bytes/intents/evidence; query-only
restore reads its bundle without original paths or clients and rejects editing, preparation, assistance and activation.
See the [configuration flow](flows/configuration-setup.md) and [README](../README.md#configure).

## 13. P001 accounting design (capture/storage, queries/API, accounting page and billing controls implemented)

F13's visible statistics still use `metrics-1` per-attempt metrics. [D254–D257](DECISIONS.md#d254--native-invocation-accounting-and-immutable-evidence)
and the [T001 contract](archive/phase-001/P001-T001-accounting-contract.md) define the additions for T002–T005.
T002's [pure library/references](archive/phase-001/P001-T002-reference-calculator.md) (D258) and T003's
[native capture, records, billing binding, explicit operations and format-3 archives](archive/phase-001/P001-T003-capture-storage.md)
(D259) and T004's [bounded read-only accounting queries/API](archive/phase-001/P001-T004-aggregates-api.md) (D262) are implemented.
The read-only accounting page (T005a, [D264](DECISIONS.md#d264--accounting-page-routes-exact-amounts-and-derived-reference-period),
[evidence](archive/phase-001/P001-T005-metrics-ui.md#t005a--accounting-ui)) is implemented, and so are T005b's billing/reference
controls and reference API ([D263](DECISIONS.md#d263--p001-t005-split-accounting-page-and-billingreference-control-contracts),
[D265](DECISIONS.md#d265--billing-controls-reference-listing-and-save-time-billing-review),
[evidence](archive/phase-001/P001-T005-metrics-ui.md#t005b--billing-profile-and-reference-controls)): explicit v10/v2 conversion,
guided profiles/defaults/selections, save-time refusal of unavailable bundles and of missing or provider-mismatched
explicit selections (naming affected projects), reported unknown inherited defaults, and a bounded reference list with
an idempotent previewed import that activates nothing.
T006 [qualified the whole chain](archive/phase-001/P001-T006-qualification.md) with synthetic evidence only and prepared the
0.1.9 candidate; real CLI emission and account billing remain unvalidated. P001 was released as **0.1.9** and closed
(D266); P002 targets **0.2.0** (D253).

- Account for native managed attempts, preparation executor steps and configuration-assistance calls, with
  expected-row coverage and no fictitious attempts for deterministic operations. Failed/interrupted or unknown
  calls are not free. Requested/effective models, terminal/constituent totals and inclusive delegated totals remain
  distinct; incomplete partitions carry reasons rather than invented splits.
- Separate reported estimates, exact local USD/credit valuations, subscription-equivalent scenarios and any future
  confirmed billing evidence. P001 has no producer of confirmed bills or balances. No API credentials are required
  to capture consumption; billing profiles cannot alter authentication. No universal credit/USD conversion or
  subscription-fee allocation is inferred.
- Freeze explicit billing profiles and immutable model/tariff references at admission, through new configuration
  versions with existing save/activation gates. Preserve old bytes/hashes and jobs lacking billing bindings. Use
  disjoint token categories, evidenced cache lifetimes/request tiers/modifiers and decimal-string amounts with
  exact line arithmetic and one half-even rounding to 12 places per invocation valuation.
- Unknown quantities, model, scheme, effective period or charges produce visible incomplete/unsupported results.
  Group only compatible units/bases, count each invocation once, and show priced/unpriced/missing-row coverage.
  Subscription equivalents remain counterfactual values, not additional charges or quota measurements.
- Preserve histories, `metrics-1`, frozen summaries/catalogs and recipes. New interpretations/repricing are explicit
  append-only operations; ordinary reads never price, backfill or fetch. Additive migration, retained evidence and
  verified offline query-only archive consultation must ship together with data/flow/API/type/en-es parity.

## 14. P002 autonomous mode and project authority (accepted design; not implemented)

[D268–D279](DECISIONS.md#d268--p002-scope-complete-roadmap-autonomy-and-evolving-plan-baseline), the
[T001 contracts](phase/P002-T001-contracts.md), [flows](phase/P002-T001-flows.md) and
[threat model](phase/P002-T001-threat-model.md) define the 0.2.0 target. Sections 1–13 remain the contract of the
released 0.1.9 product; each owning P002 task updates them, the flows, data diagram and API with parity when it
implements a change. The [supersession map](phase/P002-T001-contracts.md#2-supersession-map) lists which sections and
rules change.

- **Autonomy.** Optional execution of the whole authorized roadmap without a phase-count cap, from a readiness preview
  and an owner-confirmed authorization with delegation, finite local bounds and optional caps; explicit stop classes
  and resume; completion only with every authorized phase CLOSED and its criteria evidenced. Manual mode keeps its
  confirmations and uses the same domain commands.
- **Authority.** LangGraph orchestrates stages and waits; SQLite owns structured knowledge, accepted revisions,
  decisions, grants, rulings and operation outcomes; typed services perform every effect; one writer per checkout.
  Delegated approvals carry their origin and are never shown as owner approvals. The typed command service exists for
  knowledge (P002-T005, D286): owner API routes and synthetic graphs share one pipeline with catalogue digests, caller
  binding, per-operation capabilities within every permission ceiling, idempotent outcome records and owner-only
  adoption of previewed drafts; agent calls and delegated adoption stay refused until T006–T010/T016.
- **Knowledge and documents.** Definition and reverse-engineering onboarding produce database knowledge. Markdown is a
  generated view replaced at defined boundaries without drift detection; IDE edits matter only through an explicit,
  previewed UI import, which never fabricates execution, approval or usage history. The knowledge model is D284:
  requirements, criteria, phases, tasks, decisions and sections of logical documents, with immutable accepted
  revisions protected in the database. Instructions are canonical knowledge exported as `AGENTS.md` and derived
  wrappers, editable in the UI or imported explicitly through an authorized adoption (D285). Only the storage and
  core of that model exist (P002-T004); no product path uses them yet, and D094 still governs instructions.
- **Roles and permissions.** Reviewer, executor and judge are configured by provider, model and effort; the judge has
  duty-specific contracts and cannot grant owner-only capabilities. The five permission dimensions gain per-operation,
  time-limited and permanent revocable grants, enforced outside the model.
- **Tools and traces.** A client-neutral discovery/description/invocation contract, independent of native tool search,
  prepares future clients such as OpenCode without implementing them. Requests, operations, invocations, observed
  turns, tool calls and delivered knowledge are correlated with exact revisions and explicit coverage.
- **Observation.** A global inbox for both modes and a read-only task-instance graph; their taxonomy and visual design
  come later from the owner.
- **Preserved.** Acceptance by exact content, READY binding, single writer, intent before effect, conservative recovery,
  no hidden fallback or retry, unknown is not zero, frozen histories and cooperative containment without isolation.
