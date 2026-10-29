# Decisions — my_harness

Single record: one section per decision with a level-two heading `DNNN — title` and a first `Status:` line (proposed,
accepted, superseded by DMMM or rejected). Decisions are never deleted: they are superseded.

## Starting baseline

The decisions below were taken before this repository's first public snapshot, while My Harness was developed
privately. They are restated here in English, self-contained and in their current form; the original records,
phases and evidence are not part of this repository and are not needed to work on it. Their numbers are kept because
the code cites them (`D088`, `D167`…), so gaps are expected: the missing numbers were superseded, internal to the
private process or not relevant to the public code. **The preserved baseline also includes D216–D228. New decisions start at D230; gaps remain reserved.**

Other identifiers that appear in code comments and tests:

- `Hn.m` and `PNNN-TNNN` name milestones, phases and tasks of the pre-release work. They are not phases of this
  repository; the decisions below give the technical context where it matters.
- `cli-N`, `local-config-N`, `metrics-1`, `run-projection-1`, `language-context-1` and similar names are versions
  of frozen formats and adapters: they are part of the persisted data and are never renamed.
- Tests use decision numbers such as `D001`, `D002` or `D007` as synthetic sample data for the document parsers;
  those are not references to this file.

## D001 — Local scope and base architecture

Status: accepted.

Single-user local use. A Python engine, a FastAPI API, SQLite persistence and a React/TypeScript UI. A cloud
deployment is left open, without preventive implementation.

## D003 — Local queue without Celery

Status: accepted.

The supervisor runs jobs persisted in SQLite inside the service process; long tasks keep running when the browser
closes. A broker such as Celery is reconsidered only for a demonstrated need of independent or distributed workers,
and that change would also have to settle delivery semantics, idempotency, cancellation, recovery and storage
migration.

## D004 — Native service; containers only in project profiles

Status: accepted.

API, supervisor and agent CLIs run directly on the host. In development Vite serves the UI; the package serves the
compiled assets. Docker is optional and belongs to a managed project's profile (for example a database its
validations need), never to the core. Containerizing the service would first need CLIs, credentials, mounts, file
ownership and process control solved; the Docker socket or global credentials are never mounted for convenience.

## D024 — Agent environment with USER checked against the UID

Status: accepted.

Agent processes receive a complete explicit environment (`HOME`, `PATH`, `USER`, `LANG`…) and inherit nothing from
the service. `USER` must be non-empty and equal to the account name of the process UID; otherwise the configuration
is rejected before any process starts. Credentials, selectors and configuration sources are never copied in.

## D029 — UI by polling, preserved submissions and frozen evidence

Status: accepted.

The UI consumes the generated `/api/managed` contracts and never decides acceptance, recovery or execution. It polls
run details and reads confirmed events by cursor, paginated and deduplicated by sequence; there is no server-sent
event stream. Every job submission stores its route, body and idempotency key in session storage before sending: a
network or 5xx failure keeps it for an explicit retry, never an automatic resend; a definitive 4xx drops it; a 409
shows code and diagnostic and reloads. A commit requires the reviewed evidence of the shown version, and consents
reset when the version changes.

## D032 — Phases in SQLite and READY bound to exact content

Status: accepted; the closure part is superseded by D091.

A phase is SQLite authority: a frozen, versioned definition (criteria, tasks, documents, optional tag), documents
adopted by hash, questions, operations, authorizations and events. Check and closure are runs on the same queue and
checkout lock. READY binds the definition, HEAD, a clean Git fingerprint, the documents, the commits of accepted tasks
and the answered questions; the closure observes that binding again before any effect, and a stale READY becomes
`NEEDS_RECONCILIATION`. Pending questions block check, closure and batches. A tag is created from a prior intent with
compare-and-swap, reconciled if it already points to the READY commit, and never moved.

## D033 — Local guard, unattended batches and chat

Status: accepted; implemented by D034, D035 and D083.

The Host/Origin/`X-My-Harness` guard protects every mutation. An unattended batch authorization may chain exact
tasks and confirm the commit of each eligible acceptance, stopping at the first block, question, expiry or
revocation, and never checks or closes the phase. Chat runs as new read-only turns with structured output.
Reconciliation by an agent is a normal task limited to the phase documents. The tag kind is configurable per project
(lightweight by default). Phase definitions are amended by versions with a reason and a confirmation. Pushes are made
by the user, never by the harness.

## D034 — Unattended batches, versioned definitions and deterministic annotated tags

Status: accepted.

The batch authorization (scope `chain_commits`) freezes tasks, plan, definition, context and versions. The supervisor
advances it one step per tick, derived from SQLite state, with deterministic idempotency keys and without threads or
another queue. It stops at the first block, question, expiry, revocation, definition change, non-ACTIVE phase,
quarantine or incomplete commit. An amendment creates a new definition version, requires a reason and a
confirmation, and invalidates READY and active batches. `ABANDONED` is an explicit terminal state that frees the
checkout. An annotated tag's message, Git identity and date are sealed with its object id before the effect, so a
retried closure produces the same object; no tag is ever moved or overwritten. Agent reconciliation is a normal
`<phase>-RECONCILE-<n>` task with a server contract restricted to the phase documents and the `reconcile-phase`
template.

## D035 — Chat as new read-only turns with confirmed proposals

Status: accepted; its execution lane is superseded by D083.

Conversations, turns and proposals are SQLite authority, separate from task execution. Each turn freezes its explicit
context (project, phase, bounded documents by hash, run evidence and earlier turns) when queued, and persists the
rendered `chat-turn` prompt before invoking a new read-only session of the reviewer. The output has a strict schema;
a failure stops the turn without fallback or retry. A proposal executes nothing: accepting it requires a
confirmation, the version and the exact hash, and queues a normal task whose contract the planner fixes. Chat grants
no permissions and has no side path to write.

## D036 — Managed document blocks and reconcilable document writes

Status: accepted; the block format is refined by D073 and D088.

The harness writes only between `harness-local:managed-<name>:start` and `…:end` HTML comments; the prose outside and
its line endings are preserved, and partial, repeated or misplaced markers are rejected. Free values are escaped so
they cannot open headings, fences, HTML or markers, and blocks contain no clock or self-referencing data. A document
write is a run that reuses jobs, locks and quarantine: it previews the diff, requires its SHA-256, a reason and a
confirmation, and seals a commit intent (tree, message, identity, date and commit id) before writing with
compare-and-swap. After a crash, reconciliation reuses the same intent and never creates a second commit; foreign
bytes invalidate the operation without being overwritten.

## D037 — Root commit intent for new projects

Status: accepted; the original creation template and its discovery are superseded by D075, D088 and D089.

Creating a project ends in a root commit (no parent) whose bytes, tree, identity, message, date and id are sealed in
an intent before the effect. New files are created exclusively and an own mark inside `.git` lets the operation be
reconciled after an explicit reconfirmation with the same run, intent and commit; without a reliable mark it requires
manual recovery. External data is never restored, merged or discarded. The phase, versions and adopted documents are
recorded in the same transaction as the job result. Today the input is the accepted definition of D075 with the
D088 layout and `P001` ACTIVE.

## D042 — Explicit CLI diagnostics and shared preflight

Status: accepted; the compatibility policy is superseded by D173 and D174.

`diagnose-cli` validates one explicit agent configuration without SQLite, jobs or authentication state, and never
prints its values, paths or argv. The adapter's preflight runs `--version` and help with closed stdin, a complete
explicit environment, a temporary cwd, 10 seconds and 256 KiB of output per command, and kills only its own process
group. Failures are reported as unknown or incompatible, without retry, fallback or correction. A match is a bounded
local check, never a certification of authentication, quota, models or internal behavior; the executable must be
trusted.

## D043 — Local distribution with assets and migrations; explicit start on loopback

Status: accepted; existing databases are upgraded through D150.

`scripts/build_distribution.py` builds the UI from the npm lock offline and stages an sdist and a wheel with the UI
assets, templates, migrations and license files, plus the production dependencies exported from `uv.lock` as a
`pylock.toml` (PEP 751: URL and hash of every wheel, installable offline from the cache) and `SHA256SUMS`.
`my-harness init-db` creates a new SQLite database at an absolute path and refuses existing targets.
`my-harness serve` requires a prepared schema and assets, and serves UI and API through Uvicorn on `127.0.0.1` with
one worker; it never creates or migrates a database on startup and needs neither Node nor the checkout.

## D051 — Real use from the installed wheel, never from the development checkout

Status: accepted.

`serve` requires the packaged web assets, which an editable development install lacks. Real use builds and verifies
the package (`build_distribution.py`, then `check_distribution.py`), installs it offline by hashes into a new
virtual environment, and runs `check-config` and `serve` from that environment, outside the product checkout. A
checkout's `dist/` is not authoritative. Frozen versions include the package version, not the installation path.

## D052 — Reviewer and executor with provider, model and effort chosen by the user

Status: accepted.

Two agents: the reviewer (planning, review, phase evaluation, chat and definition; read-only) and the executor (the
only writer). Each can be Codex or Claude Code, in any combination. The user sets the reviewer's provider, model and
effort; the reviewer sets the executor's model and effort for each task and revision, from a catalog bounded by the
user or freely, per project. Deterministic planning remains a project setting: the executor then receives the
contract and selection straight from `NEXT_STEPS`, and the reviewer still reviews. A change of adapter version
quarantines pending jobs; frozen histories are never rewritten.

## D054 — Project registration in SQLite from the UI

Status: accepted; its form is set by D076 and D078.

Projects can be registered from the UI in SQLite, versioned and audited, with explicit trust, a canonical root and a
profile. Executables and agent environments are never granted over HTTP: they stay in the operator's TOML.

## D055 — First real run of the four combinations stopped by an ambiguous contract

Status: accepted; historical evidence that motivated D056.

In the first real run of the four reviewer/executor combinations, a real planner returned `validation_commands` as
argv arrays instead of shell-free strings. The run was stopped to correct the contract instead of being retried.

## D056 — Agent output shapes aligned with the engine validators

Status: accepted.

The fixed engine schemas type every list element, and `plan-task` asks for one shell-free string per command (`[]`
when the profile validations suffice). Because templates are user-editable, `task_contract` also normalizes an argv
array in `validation_commands` into the equivalent `shlex.join(argv)`; any other shape is rejected. The frozen
contract stores strings, and the original output stays in the attempt.

## D057 — Second real run of the four combinations

Status: accepted; historical evidence that motivated D058 and D059.

After D056, Codex→Claude reached COMMITTED, while the Codex writer did not edit (revision limit) and the Claude reader
serialized lists as text because its `--json-schema` declared only the required keys.

## D058 — Typed `--json-schema` for Claude read-only roles

Status: accepted.

The Claude reader receives as `--json-schema` the engine output schema frozen in the attempt's prompt snapshot
(checked against its hash), the same schema the agent reads, with `additionalProperties: true`. Lists or objects
serialized as strings are still rejected, never normalized. The engine validators remain the authority.

## D059 — Codex writer with explicit writable roots

Status: accepted.

The Codex executor declares `sandbox_workspace_write.writable_roots` with the canonical checkout and
`sandbox_workspace_write.exclude_slash_tmp = true`, and its transport input states that the granted access includes
subdirectories. The task contract and policy still bound what may be edited, and real denials must be respected.
Network access and approvals are not widened, and global settings are untouched.

## D064 — Cooperative containment without operating-system isolation

Status: accepted.

An additional operating-system sandbox around the CLIs was evaluated with synthetic probes and not integrated: it
showed escapes through inherited descriptors, pre-existing hard links and delegation to external helpers, and did
not compose with the CLI's own sandbox for every role. The harness relies on cooperative containment: each CLI's
sandbox and tool limits, explicit environments, path policies, locks, and content checks before and after each
effect. This is not isolation; only trusted repositories and tools should be registered.

## D065 — Nested sandbox profiles not qualified

Status: accepted; complements D064.

Further probes showed that nested sandbox profiles compose only in some combinations and that a hard link introduced
after admission can still reach a file outside the checkout: prechecks, same-UID permissions and cooperative locks do
not exclude races. No general inter-process isolation is claimed.

## D066 — Automatic agent memory disabled; durable context in documents

Status: accepted.

Agents must not keep a global project memory: durable context lives in the project's Markdown documents and
operational state in SQLite. Codex runs with memory generation and injection disabled, `history.persistence = "none"`
and ephemeral sessions; Claude Code receives `autoMemoryEnabled = false` inline and no session persistence. A declared
`CLAUDE_CODE_DISABLE_AUTO_MEMORY` other than `1` rejects the configuration. Credentials, `HOME` and existing memories
are never copied or deleted. This does not certify the absence of every auxiliary file a CLI may write (logs, caches,
authentication refresh).

## D068 — Codex writer trust entry

Status: accepted; later releases are admitted under D174.

Codex persists a project trust entry when a thread starts with an explicit cwd, no configured trust and permissions
that allow writing the cwd. The executor therefore receives an inline `untrusted` trust entry for its checkout, as a
complete inline `projects` table, which avoids writing global configuration and loading local config or hooks;
`workspace-write`, the D059 roots, disabled network and `approval never` stay explicit. Global configuration is never
edited, pre-created or restored.

## D071 — Real check of the four combinations

Status: accepted; historical evidence.

With the corrections of D056–D068, Codex→Codex, Claude→Claude, Claude→Codex and Codex→Claude each reached COMMITTED
on a synthetic disposable project: typed plans, passing validations and JUnit reports, review ACCEPT, acceptance by
exact content and the mechanical commit by the harness, with sampled global configuration unchanged. The retained
streams were later used offline to characterize the metrics catalog (D074). No claim is made about OS containment,
auxiliary files, quota or the providers' internal retries.

## D072 — Per-phase documentation and product structure

Status: accepted in part; the layout is superseded by D088.

SQLite governs operational state and Markdown governs intent; managed blocks are projections compared with their
regeneration and never read back as a source. Projects are created from a brief through a conversation with the
reviewer; the roadmap fixes the phases and `NEXT_STEPS` the tasks of the active phase; each phase is archived; people
edit documents through confirmed jobs; every project, phase and task has its URL; metrics cover agents, tokens,
turns, model, effort and tests.

## D073 — Phase documents and mechanical progress

Status: accepted; folders and the optional layout are superseded by D088.

The phase documents are ROADMAP, DECISIONS, STATE and NEXT_STEPS. Executors do not edit them: progress is mechanical
and prose is written during reconciliation. Blocks are readable Markdown with inline escaping, and every task commit
regenerates them and adopts them in its result transaction. Human edits are `document_edit` jobs with a confirmed
diff and compare-and-swap, rejected while work is pending in the checkout. Size budgets produce warnings without
affecting the check. Parsers accept English and Spanish labels.

## D074 — Per-attempt metrics with provenance and no double counting

Status: accepted.

Catalog `metrics-1`: every field carries its provenance (`requested`, `reported`, `derived`, `measured`, `absent`)
and null is never zero. There is one accounting per attempt: the terminal total or, for Claude without a terminal,
the deduplicated per-message usage. Aggregates add the input without cache rather than raw input, because providers
count it differently; turns reported by Claude and turns derived from Codex items are never added together. Rows are
inserted with the attempt result, survive stream retention and can be completed by the explicit, idempotent
`metrics-backfill`. Read-only aggregates live under `/api/managed/metrics/*`. Quota is never inferred.

## D075 — Conversational creation and planning with drafts on disk

Status: accepted.

Two conversations reuse the chat infrastructure: `definition` (a new project from a Markdown brief) and
`phase_planning` (the next phase's plan), with their own SQLite tables, read-only reviewer turns and the versioned
templates `define-project` and `plan-phase`. The agent never writes: the target is observed before and after each
turn and any change discards the answer. Applying a draft requires the shown hash and writes with compare-and-swap;
user edits are detected by hash. Blocking questions are answered or explicitly deferred with a reason. Accepting the
definition becomes the root commit of D037 with `P001` ACTIVE.

## D076 — Hybrid registration, safe Markdown and an own router

Status: accepted.

The operator TOML remains the authority for agents, Git, executables and environments, grouped in named
compositions; the UI registers projects in SQLite (root, trust, composition, documents, bootstrap, policy), and
nothing executable is granted over HTTP. `markdown-it` (`html: false`) and Mermaid (`securityLevel: "strict"`, loaded
lazily) are the only client rendering dependencies. A minimal router over the History API and own CSS tokens with a
dark mode add no dependencies; paths outside `/api/` fall back to `index.html`. Phase codes (`P001`) and task codes
(`PNNN-TNNN`) are unique per checkout and used in URLs.

## D078 — `local-config-3` and registration from the UI

Status: accepted.

`[registration]` holds `roots` and the `bootstrap_enabled` ceiling; compositions fix the profile and a project only
names one. Confirmation is bound to a preview hash (action, expected version, rows before and after, frozen
versions), and trust is confirmed separately for the exact canonical root. The root never changes after
registration; equal or nested roots, roots that contain the service state and roots with links are rejected.
Retirement is logical: the id stays reserved with its history. The registry row's version and hash enter the frozen
configuration hash, and changes or retirements with unfinished jobs are rejected.

## D079 — Cross-site navigations rejected

Status: accepted.

The session guard rejects every request marked `Sec-Fetch-Site: cross-site`, including page loads outside `/api/`. A
link to the UI clicked on another site does not open it; typing the URL, a bookmark or a reload still work.

## D081 — Profile protected paths limit the executor, not confirmed document writes

Status: accepted; adjusted by D090.

A profile's protected paths limit the executor, the permissions that can be granted to it and agent reconciliation.
Harness writes that the user confirmed on the exact content of the documentation contract (README, editable
documentation and the phase archive) are governed by that contract — editable paths, read-only archive, managed
blocks and compare-and-swap — not by the profile. A single function decides: `documents.protected_write`.

## D083 — Chat over a HEAD snapshot in its own lane

Status: accepted; supersedes the execution lane of D035.

New chat questions freeze HEAD and read a bounded, read-only export of that tree (no `.git`, links or submodules) in a
private folder next to SQLite, with evidence before and after and without the checkout lock: the service has a
writer lane and a chat lane. Slash commands use a closed grammar and an effect-free preview, and invalid commands
never reach the model. Codex receives `--skip-git-repo-check` only when reading such an export. Accepted proposals
still create normal tasks.

## D085 — Paginated diffs and idempotent conversation creation

Status: accepted.

Run details do not embed whole diffs: the reviewed diff of each cycle is read in pages. Creating a conversation,
which has no job, is idempotent: the client keeps its key while the same body has no acknowledged answer, a repeated
key returns the original conversation and the same key with a different body gets 409.

## D088 — Unified documentation contract

Status: accepted.

Every managed project, and this repository, uses one layout: a canonical `AGENTS.md` (at most 60 lines: discovery
order, unbreakable rules, test and lint commands) with `CLAUDE.md` and `GEMINI.md` wrappers of at most 15 lines that
import it; a `README.md` for people; and in `docs/` SPECIFICATION, ARCHITECTURE, ROADMAP, STATE, NEXT_STEPS,
DECISIONS, DDBB-DIAGRAM (a Mermaid `erDiagram`, or "No persistence"), `flows/`, `phase/` (work files of the active
phase) and `archive/phase-NNN/`. DECISIONS is a single file of `## DNNN — title` sections with a first `Status:`
line; the harness generates its index. Phases are `PNNN` and tasks `PNNN-TNNN`. Executors may write the flows, the
data diagram, ARCHITECTURE, SPECIFICATION and `docs/phase/**` when their contract allows it; STATE, NEXT_STEPS,
ROADMAP, DECISIONS and the archive belong to the harness. A data model or business flow change requires its diagram.
STATE keeps a compact accumulated baseline; budgets (warnings, never truncation): STATE 24 KiB, its baseline 12 KiB,
NEXT_STEPS 48 KiB. Parsers accept English and Spanish labels.

## D089 — Mandatory layout and template

Status: accepted.

`skeleton()` generates AGENTS, CLAUDE, GEMINI, README, SPECIFICATION, ARCHITECTURE, ROADMAP, STATE, NEXT_STEPS,
DECISIONS and DDBB-DIAGRAM; `flows/` and `phase/` have no template. The DECISIONS index comes from the file's own
headings and status lines and rejects repeated numbers, also with a different zero padding. The layout is mandatory
(`documents = "v2"`, the default), and frozen versions include `document_layout`, so a job admitted under an earlier
layout is quarantined. The earlier one-shot creation template is retired.

## D090 — Executor paths, diagram parity and decision proposals

Status: accepted.

Harness-owned paths are forbidden to the executor: the archive, STATE, NEXT_STEPS, ROADMAP and DECISIONS outside
reconciliation, and AGENTS, CLAUDE and GEMINI always. One function, `documents.executor_protected`, applies the
profile to the executor. Data parity is deterministic: touching a profile's `data_model_paths` without
`docs/DDBB-DIAGRAM.md` stops acceptance and rejects the commit. Flow parity is checked by the reviewer, which receives
the documentation changes. Executors and reviewers propose new decisions in their output instead of writing
DECISIONS.

## D091 — Unified closure and archive with later planning

Status: accepted; supersedes the closure of D032.

After READY and the closure authorization, one job observes the binding again under the lock, seals the commit and tag
intents, creates the optional tag on the evaluated HEAD and makes a single archive commit: STATE and NEXT_STEPS are
archived by bytes, REVIEW and SUMMARY are generated from SQLite, and all of `docs/phase/**` moves into
`docs/archive/phase-NNN/`. The same commit leaves STATE with the accumulated baseline, NEXT_STEPS with the next
phase's objective and criteria but no tasks, and ROADMAP with the phase completed and linked. The result transaction
closes the phase and creates the next one ACTIVE; its plan is confirmed afterwards. The check returns
`NEEDS_RECONCILIATION` when STATE exceeds 24 KiB or its baseline 12 KiB. Abandonment uses the same operation.

## D093 — API and UI of the unified contract

Status: accepted.

The API classifies documents by the configured layout (phase, product, instructions, diagram, flow, phase work,
archive, other) and lists the instruction files without adding them to the adopted phase hashes. The decisions index
exposes only id, title and status. The one-shot creation and separate transition endpoints are removed;
`GET /api/managed/projects/{id}/bootstrap` reports the state of the conversational definition. The next phase is
planned on its own page with a preview, diff, hash, reason and an idempotent confirmation.

## D094 — `AGENTS.md` in every frozen prompt

Status: accepted.

Neither CLI loads the checkout's instructions by itself: Claude Code runs with `--setting-sources ""` and Codex with
a project-doc budget of 0. On every attempt the engine reads `AGENTS.md` from the checkout root (a regular file, no
links, UTF-8, non-empty, at most 32 KiB, never truncated), injects it through `{{PROJECT_INSTRUCTIONS}}` and records
its path, SHA-256 and size in the prompt snapshot; if it is missing or invalid, the attempt stops before invoking. The
definition and onboarding roles do not receive it, because it is part of what they write or analyze.

## D095 — Declared profiles in `local-config-4`

Status: accepted.

`[profiles.<name>]` declares a project's stack: `preparation`, `validations` (at least one),
`allowed_command_prefixes`, `protected_paths`, `sensitive_paths`, `data_model_paths`, `executor_instructions` and the
optional `sensitive_allowlist`. Each command is a table with `argv`, `timeout_seconds` and optional `cwd` and
`environment`; a JUnit report is declared with its validation. Commands are argv without a shell: the first element
names an entry of the composition's `executables`, never a shell, and no argument may be a shell operator or contain
`` ` `` or `$(`. A prefix never authorizes execution by itself. The whole profile enters the frozen configuration
hash, so changing it quarantines pending jobs. Built-in profile names are reserved.

## D099 — Managed-mode marker stays untracked

Status: accepted; applies only to installations that activated the mode retired by D161.

The local marker `.harness/managed-mode.json` of an earlier activation is installation state: commits never version
it and never edit a project's `.gitignore` to hide it. It is tolerated as an untracked file only while SQLite and the
filesystem agree on a live activation; any other untracked change still blocks.

## D102 — Onboarding by reverse engineering over HEAD with private drafts

Status: accepted.

The `onboarding` conversation freezes the static inventory, HEAD and the complete tree of a non-empty Git repository
without a harness, and reads a bounded private export (no `.git`, links or submodules; 20,000 files, 16 MiB per file,
128 MiB in total) even if the worktree changes later. A read-only `definition` role with the `onboard-project`
template asks for the eleven layout documents and the flows, a data diagram from concrete models, decisions observed
in the code marked as inferred, and questions where requirements cannot be deduced. Existing root files are
evidence. Drafts live next to SQLite under compare-and-swap, and no project code runs. The confirmation, bound to the
documents and the profile hash, makes one reconcilable documentation commit that adopts `P001`.

## D116 — Creation authority, per-project presets and separate preparation

Status: accepted.

One projects folder per installation, chosen and confirmed in the UI with a revision, its filesystem identity and
append-only events, authorizes creating new children only; it does not widen `[registration].roots` or the bootstrap
ceiling, and removing it invalidates pending creations without deleting anything. Each creation reserves its id and
target and seals an intent before `mkdir`; a crash between `mkdir` and persisting the identity leaves it uncertain,
never adopted just because the folder is empty. `local-config-5` adds `[agent_presets.*]`: the client selects preset
ids, the reviewer model and effort and the executor policy, while executables and environments stay with the
operator. Role changes are confirmed by version and hash and blocked by pending work. Stack preparation is a separate,
confirmed step.

## D119 — Django recipe preparation

Status: accepted.

The packaged `django-recipe-1` prepares only a new child created by the service, after its documentation root commit.
Its read-only preview shows full contents and hashes, templates, lock, versions, HEAD, executables accredited by hash,
argv, public environment, per-step limits, network mode and the planned commit; confirming binds that plan by hash.
It needs CPython 3.11–3.13 with an exact patch and the operator's uv with an exact version, pins every direct and
transitive dependency by wheel hashes and keeps them out of the harness dependencies. The venv has no pip; it is
offline by default, from an explicit wheelhouse or a private cache, with network only under the operator's ceiling
and the confirmed plan; HOME, cache and temporary files stay inside the child. An environment receipt is checked
before later work. Both roles must declare `PYTHONDONTWRITEBYTECODE=1`. The recipe fingerprint binds issued
receipts, so its source is frozen byte for byte.

## D121 — Claude executor without a shell

Status: accepted.

The reference Claude Code executor receives only `Read`, `Edit`, `Write`, `Glob` and `Grep`: no shell. Commands run
only as the harness's native validations, so a formatting rule must be applied by the harness (D133).

## D122 — Codex 0.163.0 and Claude Code 2.1.304 characterized

Status: accepted; these releases are the minimums of D173.

Bounded probes (`--version` and help) of fixed binaries and a source comparison with the previous releases showed,
for Codex 0.163.0, the same flags, trust guard, override parser, event stream, effort vocabulary, memory controls and
instruction loading, also as a writer with the same trust handling; and for Claude Code 2.1.304, the same flags,
`--restricted` semantics, effort vocabulary, memory and hook controls and terminal results. No model was called.

## D123 — Codex refuses a working directory outside Git

Status: accepted; historical evidence corrected by D124.

During a real creation, Codex 0.163.0 refused the first definition turn: a new child has no `.git` until its root
commit, and Codex requires `--skip-git-repo-check` outside a repository. The fake CLIs did not reproduce that check.
The run stopped without a retry.

## D124 — Codex defines a new project outside Git

Status: accepted.

Codex receives `--skip-git-repo-check` in the `definition` role when the frozen prompt is the `define-project`
template (a new folder), besides the read-only exports of D083 and D102. The condition comes from the frozen request,
not from the disk. A definition never targets Git: the turn is rejected if the target belongs to a repository and
fails before invoking if `.git` appears later. The `read-only` sandbox, disabled memory and the project-doc budget
are unchanged.

## D125 — Parallel pytest suite and fork-free Git

Status: accepted.

The pytest suite runs in parallel by default with pytest-xdist (`-n auto --dist worksteal`); `-n 0` runs it serially.
Test matrices are trimmed only while every axis stays covered. The Git adapter batches index updates and hashing and
runs `git -C <root>` with an absolute path, without changing trees, commits, errors or messages.

## D126 — Package verification through the definition flow; private TMPDIR

Status: accepted.

`scripts/check_distribution.py` verifies the installed wheel through the current HTTP path: a definition conversation
with a synthetic agent, confirmed drafts, the root commit and the first task, plus session, assets, restart,
configuration and schema errors, backup and query-only restore. `serve` writes the session key and temporary Git
indexes under the process `TMPDIR`; running it with `TMPDIR` set to a private directory keeps them in the operating
area. Recipe commands get their own `HOME` and `TMPDIR` inside the child.

## D129 — Directory paths frozen as `dir/**`

Status: accepted.

`task_contract` freezes every `allowed_paths` or `forbidden_paths` entry that ends in `/` as `dir/**`, so the
executor, the reviewer, the path policy, grants and contradiction checks read the same scope. Exact paths and globs
are unchanged, and contracts already frozen keep their bytes.

## D130 — Preparation receipts compare the inode, not the device

Status: accepted.

macOS may renumber `st_dev` when it remounts a volume, for example after a reboot. Receipt verification compares the
inode of the checkout and its environment, and still verifies protected files and the environment byte by byte.
In-progress operations (creation, preparation and the projects folder) keep comparing device and inode, so after
such a reboot the projects folder must be chosen again.

## D132 — A shell-less executor cannot satisfy a formatter check

Status: accepted; historical evidence corrected by D133.

A real run reached its revision limit because `ruff format --check` failed on a line that the Claude executor,
without a shell, had formatted by hand with another line length; neither agent could see what the formatter would
change.

## D133 — The harness runs the profile formatter after each executor turn

Status: accepted.

After each executor turn and before capturing evidence, the engine runs the profile formatter (`formatter_argv` plus
paths) on the changed paths that match `formatter_paths` and that the contract allows; never when revalidating. The
native runner authorizes that argv only with existing regular files of the checkout. A non-zero exit reaches the
validation and the reviewer; each cycle records its `formatting`, which the API and UI show. A formatter needs an argv
ending in `--` and `authorize_profile_commands = true`; the Django recipe profile declares `ruff format --` for
`*.py` outside the fingerprinted recipe source.

## D142 — TypeScript web recipe and run projection

Status: accepted; implemented by D143 and D144.

A second packaged recipe, `typescript-web-recipe-1`, writes the initial `package.json` of a new TypeScript web
project within the D119 framework. Run views read a derived projection written in the same transaction as the
history, which remains the authority; the engine, recovery, checks, chat and permissions keep reading the history.

## D143 — `typescript-web-recipe-1`

Status: accepted.

`[recipes.typescript-web]` declares absolute node and npm executables with exact versions, a canonical npm cache
outside the state and the checkouts, timeouts, output limits and a network ceiling; its composition uses the
built-in `typescript-web` profile with `npm_config_cache` equal to that cache. Steps: files → exact versions →
`npm ci --ignore-scripts` (offline from the cache only) → `npm run check/test/build` with JUnit → technical commit.
The receipt fixes the identity, the protected manifest and node/npm by hash, not `node_modules`. An empty cache fails
offline without downloading.

## D144 — Run projection `run-projection-1`

Status: accepted.

Additive migration `0023_run_projection` adds derived tables (summary, stops, cycles, diff segments, JUnit reports
and cases) filled from every existing history without modifying it. The projection is written in the same
transaction as the history, and the reviewed diff is stored in fixed 64 KiB segments so a page reads only what it
covers. Run views, metrics and export previews never decode the history; backups check the projection's consistency.

## D150 — Explicit migration from the installed CLI

Status: accepted.

`my-harness migrate --database PATH --snapshots DIR --writers-stopped` upgrades an existing database of a known
revision: absolute paths without links, a snapshot directory outside Git checkouts and persisted roots, a
declaration that the service and the writers are stopped (checked against persisted owners of jobs, preparations,
CLI groups and validations), a verified `premigration-1` SQLite snapshot (integrity, revision, SHA-256, fsync) before
Alembic, and a final schema check. An up-to-date database is left untouched. A failure keeps the database and the
snapshot, without automatic restore. `init-db` and `serve` keep D043.

## D151 — Real validation of onboarding and declared profiles deferred

Status: accepted.

The first local version was declared complete with the onboarding of existing repositories and declared profiles
verified only offline, with fake agents and tools. A real validation needs its own task and consent; until then the
documentation states the limit. The real evidence of the Django recipe (macOS ARM64, Python 3.13) is not
extrapolated to declared profiles.

## D155 — Two entries to start a project

Status: accepted; implemented by D161.

The product offers exactly two entries: create a new project from scratch, or onboard an existing repository without
a harness. Viewing, observing, importing or normalizing projects of an earlier harness is not supported. Registering
again a project already managed by this harness is a normal registration.

## D156 — Continuous mode between phases reserved for v0.2.0

Status: superseded by D268 (scope and stop conditions); it was never implemented. The 0.2.0 target is retained.

An optional continuous mode — tasks, commits, check, closure and archive, then planning and execution of the next
phase — is reserved for v0.2.0, after the first public release. It will start from a bounded initial authorization
with scope and budget, stop on errors, blocks, questions, out-of-scope changes or consumption limits, and keep READY,
acceptance by content and intent and recovery. Until then task batches, checks, closures and next-phase plans keep
their explicit authorizations (D034, D091).

## D157 — Public repository as the primary source

Status: accepted.

The public repository starts from a reviewed snapshot with a new Git root and new documentation; the earlier
history, phase records and evidence stay private and are not needed to work here. From the opening, code,
documentation, decisions and phases are developed in the public repository, without a second active copy
synchronized over it.

## D158 — Global interface language and immutable work language

Status: accepted; implemented by D166–D172.

Two global settings, `ui_language` and `default_work_language` (en/es, initially en). The interface language is global
and mutable: UI, messages, conversation with the agents, their answers and questions. The work language is chosen per
project at creation or onboarding from the default and is then immutable: documentation, plans, decisions, code and
comments. Both are frozen when each job or turn is admitted. Original prompts stay in English; keywords, public
names, formats, canonical paths, commands and technical codes are never translated; existing files and user data
are not translated automatically; the child application's functional language is not imposed.

## D159 — Language contract and frozen sources

Status: accepted.

Preferences live in SQLite per installation with compare-and-swap and audit, not in the TOML or the browser. Messages
use JSON catalogs per scope (React and Python) with controlled keys and parameters and English fallback, without new
dependencies. The work language is bound once to the project's identity and root, also for TOML projects, and SQLite
rules after that. New shapes are versioned and old snapshots are read without inventing values. v1 recipe sources and
other fingerprinted resources stay byte for byte as historical compatibility; v2 recipes are added beside them.

## D160 — MIT license

Status: accepted.

My Harness is licensed under the MIT license, copyright 2026 David Acosta. Third-party components keep their own
licenses and notices (`NOTICE.md`, `NOTICE-THIRD-PARTY.md`). Vulnerabilities are reported through GitHub's private
vulnerability reporting, as described in `SECURITY.md`.

## D161 — Retirement of the previous harness support

Status: accepted.

The viewer, index, observation and event streams of the previous harness, managed-mode activation and reversal, and
its import flow are removed with their routes, commands, conversation, template and UI: old URLs show not found, the
old API answers 404 after the guards and old CLI commands fail on argument parsing before opening SQLite. Tables,
revisions and data are kept, and onboarding still uses `project_imports` and `purpose=import_commit`. Jobs of the
retired flow, or ambiguous ones, are quarantined before any effect and are resolved only after confirming that the
writer stopped, without executing their intent. Incomplete earlier activations block for manual resolution; an
earlier ACTIVE activation only admits managed work with an intact marker and manifest. Old catalogs that contain the
retired template are readable as data, never rendered for invocation.

## D163 — Code in English and v2 recipes

Status: accepted.

Comments, docstrings and API descriptions are in English; Alembic revision ids and operations, formats and external
codes are unchanged. v1 recipe sources keep their bytes and fingerprints, checked by tests. `django-recipe-2` and
`typescript-web-recipe-2` are self-contained English sources whose technical scaffold text follows the work
language; with Spanish (Django) or English (TypeScript web) they reproduce the v1 bytes. The child application's
functional defaults, such as Django's `LANGUAGE_CODE` or `<html lang>`, are kept and never derived from the interface
language.

## D166 — Global language preferences and catalogs

Status: accepted.

Migration `0024_product_preferences` adds a singleton row `product-preferences-1` (en/es check, seeded en/en at
version 1) and hash-chained events with idempotency keys. Reading never creates or repairs it; an invalid row reads
as English with status `invalid` and blocks admissions (409 `preferences_invalid`) until it is saved again.
`GET/PUT /api/managed/preferences` use compare-and-swap. Every new action captures the current interface language in
its job; continuations of the same run copy the first job's value. JSON catalogs in Python (`my_harness/i18n`)
and React (typed keys, interpolation as text, `Intl` formats) fall back to English.

## D167 — Immutable work language per root; language pair per job and attempt

Status: accepted.

Migration `0025_project_work_languages` adds one row per canonical root (`work-language-1`: value, project id, source
`registration|creation|toml|migration`, confirmation and hash), written once and never updated or deleted.
`work_language` is required to register or create a project; the preview hash seals the chosen value and the row is
written in the same transaction as the registration. A root already bound accepts only its value, and changes or
retirements carrying `work_language` get 409 `work_language_immutable`. A `local-config-6`/`7` project declares it in
`[[projects]].work_language` and the service binds it once at startup; a different value stops the startup. A project
without a value needs an explicit confirmation (absent → value) before new work; until then every admission answers
409 `work_language_required`. Jobs seal the pair `language-context-1`, and every attempt copies it.

## D168 — v2 recipes in `local-config-6`

Status: accepted.

The same `[recipes.django]` and `[recipes.typescript-web]` keys select v1 in `local-config-5` and v2 in
`local-config-6`/`7`; there is no version choice in the TOML and no migration from v1 to v2, and both are read and
reconciled with the class of their sealed version. The composition hash binds the operator configuration and the v2
fingerprint for both languages; the preparation plan seals the project's work language, its row hash and the
language-specific fingerprint, and the receipt copies them. A v2 preview without the project's work language answers
409 `work_language_required`, and each step compares value and hash with the plan again.

## D169 — Sealed language directive; generated documents in the work language

Status: accepted.

`language-directive-1` is engine text appended after the editable template and before the output schema. It states
the interface and work languages, the per-role map of human fields (interface language), technical artifacts (work
language) and literal technical values, how to read mixed-language sources without translating them, and the
documentation labels of the work language. The pair comes only from the claimed job's `language_context`; no template
variable can replace it. Both providers receive it in the stdin prompt, with no new flags or permission changes, and
the attempt snapshot records it with its hash. Jobs without a pair render as before. Documents generated by the
harness (blocks, templates, archive and records) follow the project's work language; commit messages and trailers
stay technical.

## D170 — Interface in English and Spanish through typed catalogs

Status: accepted.

Every React text comes from typed en/es catalogs; sentences with elements split the template before inserting values;
numbers, dates, sizes and costs use `Intl` for the language. HTTP diagnostics of the API's own guards and router are
emitted in the saved interface language; codes and statuses do not change. The line
`My Harness: access key at <path>` is fixed technical output read by scripts.

## D171 — Service and CLI texts in the language of each emission

Status: accepted.

`i18n.emission()` fixes the interface language of an emission and `tr()` uses it: an HTTP request uses the saved
preferences, a claimed job its frozen language (or the saved one if it was admitted without it), a preparation the
saved one, and the CLI `--ui-language`, the database or English. What is persisted stays in the language it was
emitted in. Hashes do not depend on the language: retention previews seal their diagnostics in English, and
registration or creation previews seal the shown declaration, so changing the language between preview and
confirmation requires a new review.

## D172 — Service texts in both languages; rejections distinguished by code

Status: accepted.

Every diagnostic the operator causes or resolves goes through `tr()`. Internal invariants, corrupted persisted data
and text that enters an agent's input stay technical English, listed by category (`invariant`, `agent-input`,
`technical`) in `tests/fixtures/service_texts/english.json`; a test requires every own diagnostic to be one or the
other. Metrics group stop reasons by the emitted text. Clients distinguish rejections by `code`, never by the
diagnostic text.

## D173 — Automatic CLI discovery, minimums and capability contract

Status: accepted; implemented by D174.

Users do not declare CLI versions: the service discovers the selected providers on each role's explicit `PATH`, or
an optional path for non-standard installations, observes `--version` and help within bounds and compares them with
capability profiles packaged with the application. Common minimums for reading and writing are Codex 0.163.0 and
Claude Code 2.1.304; older versions get an update instruction for new work, while history and old configurations
stay readable. A later stable release, including another minor or major, is admitted when it matches the applicable
profile: there is no numeric ceiling or per-patch allowlist. No shell, disk-wide search, auth/login/status calls,
auto-update or provider/model switch. Parsing the TOML runs no process; the real version is frozen per job, never
`auto`.

## D174 — Automatic clients and conditional compatibility

Status: accepted.

No public probe without inference can prove, for every later release, the internal Codex condition that suppresses
global trust writes. Later compatible releases are therefore admitted automatically under the known contract with
**conditional compatibility**, without claiming verified internal effects. Sandbox, memory, trust and permission
controls are never relaxed: missing or altered controls or an observable incompatibility block before invoking.
`local-config-7` extends v6 with optional `executable` and `cli_version`; environment, timeout and the
provider/model/effort selection stay explicit. Adapter `cli-14` uses the packaged policy `cli-capabilities-1`: each
attempt runs a fresh preflight and checks the launch identity before starting, and drift rejects or quarantines
without retry or provider substitution. Formats 1–6 and their pins keep their hashes; an explicit pin that differs
from the installed client is diagnosed.

## D194 — Optional formatter for declared profiles

Status: accepted.

`local-config-8` extends v7 with optional `formatter_argv` and `formatter_paths` in `[profiles.*]`. The pair must be
present together and non-empty: argv without a shell, mapped executable and final `--`, unique relative patterns,
and `authorize_profile_commands = true`. Omitting it preserves the effective profile hash; v1–v7 keep their rules
and fingerprints. v8 retains automatic CLI discovery, per-project presets, work languages and v2 recipes.
The existing D133 engine/runner formats only contract-allowed changed files before validation and review, never
on revalidation. Evidence and acceptance bind the resulting bytes. Configuration changes quarantine frozen jobs.
A real task on a documented synthetic Django clone exercised the declared formatter (two files unchanged), six
validations and 13 JUnit cases through COMMITTED; this supplies the bounded declared-profile evidence deferred in
D151, superseding that deferral only within this fixture scope, without extending it to production projects or
proving automatic repair of a formatting failure.

## D216 — Isolated installation and setup session

Status: accepted.

Install into private generations with separate data, configuration and selectable caches; verify before publishing
READY. Run the installed wheel, without Node at runtime. A missing/invalid configuration opens authenticated setup
with task admission closed. Global changes require a restart; migration remains explicit with a prior snapshot.

## D217 — Versioned files and configuration activation

Status: accepted.

Private immutable global v9/project v1 TOML outside checkouts holds content; SQLite owns saved/active/pending
references. CAS, exact preview hashes, idempotency keys and intentions guard atomic publication/recovery. Save
never activates. Global activation promotes the verified set on restart; project activation requires the work
barrier and exact preparation evidence. Earlier snapshots and formats 1–8 keep their bytes/hashes.

## D218 — Profile after context and preparation before activation

Status: accepted.

A documentary intake can converse before having a stack profile. The reviewer proposes tools, validations and
technical scope from documentation/architecture or static inventory. Proposal adoption, confirmed documentary
commit/P001, completed private configuration, bounded preparation and independent activation precede task work.
Recipes are optional. Agents receive no general authority to write global settings.

## D219 — Generation installer and self-contained package

Status: accepted.

`scripts/install` accepts a clone or self-contained distribution, validates exact artifacts and creates a venv per
generation. READY receipt and atomic `current.json` follow installed synthetic verification. Offline is default;
network is explicit. Matching replay verifies existing bytes; updates preserve prior generations and require
stopped writers. Failures keep diagnostics and never publish partial installation or migrate data.

## D220 — Installed startup and instance exclusion

Status: accepted.

`scripts/start` verifies receipt/distribution/venv and uses installed Python in isolation, with explicit data,
configuration, port and private temporary paths. Only an absent database without auxiliary files is initialized;
existing schemas require a separate migration. OS locks are inherited by the child; signals and exit codes are
preserved. Restart does not reinstall, overwrite TOML or certify that an uncertain writer stopped.

## D221 — Configuration journal and references

Status: accepted.

Three additive tables store scopes, immutable revision metadata and operation intentions. Private files use
atomic publication, strict path/owner/permission checks, CAS and explicit byte reconciliation. Recovery cannot
invent missing content or overwrite conflicting external edits. Drafts cannot activate; pending work is a barrier.

## D222 — Setup API and global authority at startup

Status: accepted; activation for restart superseded by D238 for live fields.

Protected deterministic form/TOML endpoints validate, preview, save, activate for restart, cancel and recover.
Client discovery uses explicit PATH; version/help probes do not invoke inference. Authority is selected and
verified before composing runtime clients; setup/invalid states reject managed work. Query-only restore disables
this operating lane before any original path or client is used.

## D223 — Guided UI with exact confirmations

Status: accepted; the restart step is superseded by D238 for live fields.

`/setup` and `/settings/configuration` share the en/es editor. Server-validated form/TOML conversion preserves
advanced fields. Saving and activation have separate exact previews and confirmations. Browser-tab draft/base and
idempotent request survive conflicts/reload; polling never rebases or resends. There is no HTTP restart endpoint.
Storage is fixed by startup; credentials remain outside the product.

## D224 — Documentary context and own profile proposals

Status: accepted.

`IntakeContext` has no runnable profile; registry composition/profile can be null (migration 0027). Planning stores
structured profile proposals with command/tool evidence bound to frozen documents/inventory/HEAD. Functional
validations must be meaningful. Adoption only records PROFILE_PROPOSED: no TOML writes, preparation or activation.
Stale context or open questions block adoption. Formats 1–8 retain their contract.

## D225 — Confirmed generic preparation and own receipt

Status: accepted.

`project-profile-preparation-1` reuses preparation locks/leases/journals with exact saved configuration and confirmed
documentary handoff. The frozen executor writes only the technical scope; the harness runs exact argv, validates
fresh JUnit, checks guards and makes a reconcilable technical commit if content changes. A receipt binds tools,
configuration, protected content and stable environment. Failure does not qualify a receipt or activate a profile.
Recovery needs verified stopped writers and an exact accredited prefix, with no automatic replay.

## D226 — Documentary intake and profile activation

Status: accepted.

Both UI entries preserve trust, immutable work language and Git guards without requiring a composition. The
confirmed documentary commit seals the accepted profile; the application then saves private project TOML.
Preparation and activation remain separate. Activation verifies the saved version, exact compatible receipt,
clean technical HEAD and work barrier, precomposes and publishes the SQLite reference between tasks. Jobs seal
configuration revision/hash and receipt; replay cannot duplicate intake, preparation or commits.

## D227 — Later editing, frozen assistance and joint impact

Status: accepted; joint activation on restart superseded by D238 for live fields.

Global SAVE derives private copies of active project profiles bound to its exact global version, with joint
activation/cancellation on restart. Technical project edits need current committed documents and a new receipt;
nontechnical edits can retain exact verified evidence. Assistance freezes currently active clients and authorized
context. Applying its result changes only the draft; it grants no write access to machine-wide settings. Its own
process journal supports stopped-writer recovery without inventing managed runs or replaying model calls.

## D228 — Explicit conversion and configuration backup

Status: accepted.

Importing product TOML 1–8 is separate from onboarding a code repository. Explicit preview/save preserves source
bytes/hashes and legacy authority; converted project drafts require current documents, a plan and new preparation
before confirming/promoting the whole set on restart. Historical recipes/receipts are not converted. Format-2
backup inventories TOML versions, working copies, partial intents and referenced evidence. Query-only restore
reads bundle bytes without original roots/clients and rejects all configuration effects. Format 1 without the new
configuration remains readable.

## D230 — Public name My Harness and no hosted CI

Status: accepted.

The product is published as **My Harness**: distribution and CLI `my-harness`, Python package `my_harness`, default
directories `~/Library/Application Support/My Harness` and `~/Library/Caches/My Harness`, CSRF header `X-My-Harness`
and release asset `my-harness-<version>-distribution.tar.gz`. Identifiers persisted in existing data keep the earlier
name and are never renamed: the managed block markers `harness-local:managed-<name>`, the formats
`harness-local/onboarding-inventory/1`, `harness-local/managed-mode/1` and `harness-local/migration-manifest/1`, and
the engine version `harness-local-<engine>` frozen in job contracts.

The repository has no hosted CI. The offline suites and package checks listed in the README run locally before each
change, and the release package is built and verified locally from the tagged commit.

## D231 — Packaged model suggestions and small UI patch releases

Status: accepted.

Model choice in the UI starts from a list packaged with the interface, per provider, next to the effort vocabulary:
Codex `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-astra`, `gpt-6-luna`; Claude Code `claude-opus-5-5`, `claude-sonnet-5-5`,
`claude-haiku-5-5`, `claude-fable-5-1`. The list only suggests: it is not a capability check, it never queries a
client or provider (D173) and it does not change formats, hashes or the API. Models stay free text with the accepted
shape and the server keeps validating them.

- The reviewer's model in the global setup is a selector of the provider's suggestions with an **Other** choice
  that keeps a hand-written model. A saved model outside the list stays visible and editable; a suggested model is
  cleared when the provider changes, while a hand-written one is kept.
- The executor's models in a project policy are checkboxes. In `catalog` mode with a project preset they are the
  preset's models, as the server requires; otherwise they are the suggestions for the executor's provider plus any
  model added by hand. Models already in the policy are always shown checked. The reviewer still chooses one of the
  checked models per task and revision (D052).

Updating the list is a release of the interface. A patch release (`0.x.y`) may carry such small interface
improvements as well as defect fixes, provided it changes no configuration format, API contract or stored data.

## D232 — Metrics Records phase and accounting boundaries

Status: accepted (accounting boundaries; phase order and release assignment superseded by D233).

P002 **Metrics Records** is added after P001 to cover detailed provider/model consumption, cost analysis and
versioned reference data. The user requested a self-contained documentation handoff before implementation.
Claude Code and Codex are the initial execution clients; extensibility of the accounting data does not authorize
another provider integration. P001 stays active and no release version is assigned by this decision.

The phase must distinguish amounts reported by a client, valuations calculated from an identified tariff, credits
and authoritative billing evidence. Token-based valuations do not establish subscription allowance consumption,
remaining quota or the user's final invoice. Missing model, usage or tariff conditions remain explicit uncertainty,
never free usage or a silently chosen substitute. Historical metrics, histories and frozen catalogs retain their
meaning and bytes; subsequent references or calculations must be separately identifiable.

The [phase handoff](archive/phase-001/P001-metrics-records.md) and [reference notes](archive/phase-001/P001-metrics-records-references.md)
are planning artifacts. Their task breakdown, candidate record fields and calculation policy require technical
decisions during P002-T001; they are not a new schema, API, billing configuration format or implemented feature.
No real calls, network installation, global configuration change, commit or publication is authorized by this plan.

## D233 — Metrics Records first in 0.1.2, Continuous Mode second in 0.2.0

Status: accepted (roadmap order and release targets; implementation pending); the `0.1.2` target is superseded by D239
and the Continuous Mode description by D268.

At the user's explicit direction, P001 is **Metrics Records**, targeting `0.1.2`; P002 is **Continuous Mode**,
targeting `0.2.0`. This supersedes the initial ordering and unassigned metrics release in D232. P001 is the active
documentation phase with its detailed task plan still pending adoption; Continuous Mode follows it. The metrics
handoff, reference notes and proposed task identifiers are renamed from P002 to P001. These are unfrozen planning
documents; no persisted project phases, histories, catalogs or recipe fingerprints are renumbered.

Continuous Mode automatically closes/archives a completed phase and opens/plans its successor within the optional,
explicit bounded authorization described by D156, preserving READY, acceptance, intent/recovery and stop conditions.
No automatic phase transitions are implemented by this documentation change.

The `0.1.2` assignment is a specific user-authorized exception to the patch scope in D231 and the changelog's
general versioning policy: Metrics Records may include the additive metrics data/API/configuration changes adopted
in its technical design. Existing compatibility, explicit migration and snapshot guarantees still apply. It is not
an interface-only patch. No general relaxation for other patch releases is implied.

Package/API/UI version strings remain `0.1.1` until the corresponding implementation/release task changes them
together. Target versions are not published releases, and this decision authorizes no commit or publication.

## D234 — P001 task plan in NEXT_STEPS

Status: accepted (task breakdown and documentation placement; implementation pending).

At the user's request, NEXT_STEPS contains the actual P001 Metrics Records task plan, rather than only linking to
an outline in the phase handoff. Six ordered tasks specify status, dependencies, objective, allowed paths,
acceptance criteria, validation and deliverables. All are pending; the next is P001-T001, the accounting contract
and evidence inventory. Recording this plan resolves the pending task-breakdown step in D233, not the technical
decisions reserved for T001, and does not start implementation or authorize external effects.

The handoff is supporting scope/code/reference context; task status and contracts are maintained in NEXT_STEPS
to avoid competing plans. The layout follows the explicit task sections in the base project's archived P013
NEXT_STEPS (with P012 as another example), adapted to this repository's English work language. The base archive
was consulted read-only for structure; none of its run data, private evidence, managed blocks or closed snapshots
is imported or modified, and the new plan does not require access to that checkout.

## D235 — Release branch, integration branch and topic branches

Status: accepted.

Development moves off `main` so that `main` only carries published versions:

- `main` receives one `--no-ff` merge from `develop` per release, with the version bump and changelog already on
  `develop`. That merge commit gets the tag `vX.Y.Z`, and the distribution package is built and checked from it
  (D230). `git log --first-parent main` therefore lists releases. No work is committed directly to `main`.
- `develop` is the integration branch and the target of pull requests. Phase tasks, documentation and fixes land
  there once their checks pass.
- Each bounded task uses a short-lived topic branch from `develop`, named `<kind>/<topic>` with `feat`, `fix`,
  `docs`, `chore` or `test` (for example `feat/p001-t001-accounting-contract`), merged into `develop` and then
  deleted.
- A fix for a published version branches from its tag, is released through `main` like any version and is merged
  back into `develop`.

GitHub's default branch stays `main`, so visitors see the released state. Commits already pushed to `main` after
`v0.1.1` are not rewritten; the next release merge brings `main` forward. Agents check the current branch at the
start of a session and never work on `main`.

The repository is public since 2026-10-27, and GitHub protects `main`: changes need a pull request (no required
approvals, as there is a single maintainer), the rule also applies to administrators, and force pushes and deletion
are refused. A release is therefore a pull request from `develop` to `main` merged with **Create a merge commit**,
which is the `--no-ff` merge above; squash or rebase would break the shared history with `develop`.


## D236 — Empty failed intake turns are not pending configuration work

Status: accepted.

Clarification of the D221 work barrier: a definition/onboarding conversation whose
turns all ended FAILED with no result, unchanged observations and no observed drafts
is not adoptable work when it also has no known drafts, edit log, deferrals or
proposals. Its historical rows remain intact; the next explicit turn freezes the
then-active configuration through the normal path. This permits an operator to
confirm and activate a corrected client timeout after an empty intake failure.

Answered, queued, unknown or unobserved turns, partial results, observed/known
drafts, edit history, deferrals and proposals keep the conversation barrier. Job,
writer/checkout, preparation, acceptance, commit-intent and phase-operation barriers
remain independent and unchanged. Save, activation preview, confirmation and restart
remain separate; this exception neither activates configuration nor retries a model.
No API, schema, frozen format, source snapshot or previous run is rewritten.


## D237 — One-off development queue before phase work

Status: accepted.

At the owner's request, `docs/ONE_OFF_TASKS.md` is a manual development priority
queue, read after STATE and before NEXT_STEPS. It holds bounded fixes, improvements
and design changes that do not require a complete roadmap phase. It is normally
empty; an empty queue means resume the active phase's existing next task.

Entries use stable phase-independent OTNNN IDs and NEXT_STEPS-style scope,
acceptance, checks and deliverables. Work stays one bounded task at a time. Before
removing a completed entry, record checks, omissions and outcomes in
`docs/phase/OTNNN-<topic>.md`, retain durable decisions in this log and reconcile
current documents. Then remove its whole task section and update Queue/Next;
completed records do not accumulate in the queue and IDs are not reused.
Blocked work remains explicit rather than silently yielding to the roadmap.

This does not add a phase, alter Metrics Records/Continuous Mode numbering or
introduce a managed-project document, parser, API or automatic scheduler. The
harness is not run on this repository. OT001 records the requested live agent
configuration behavior for a later session; the concrete technical design remains
to be settled in that task and is not already implemented or an amendment to
D222/D223/D227 in this documentation-only change. D236's failed-intake fix is
already committed and must not be implemented again as pending work.


## D238 — Live configuration switch at an idle boundary

Status: accepted. Supersedes the restart rule of D222/D223/D227 for global agent settings and the outright
refusal of activations with pending work (D221/D226); every other rule of those decisions stands.

A confirmed global activation is applied by the running service without restart, a new login or reinstallation,
unless it changes a field the process cannot switch. Restart-only: `service.supervisor`, `service.lease_seconds`
and `service.poll_seconds` while a worker thread runs (with no worker the switch starts one with the new values),
and any activation under legacy authority or a legacy import promotion (D228). `service.state_dir` stays fixed at
startup; listener, database and configuration directory are startup arguments. Agents, presets, Git, registration,
profiles, compositions and recipes are live. The preview names `apply` (`live` or `restart`) and `restart_fields`.

Before confirmation, the preview stages a complete candidate runtime outside write transactions: the global
composer, a version/help preflight of both roles with exact executable/PATH/environment (no inference) and the
recomposition of every ACTIVE registered project with the set's own project revisions and selected receipts. A
failure is `live_configuration_refused` with structured corrections (project or role, setting, code, diagnostic);
a project already failing under the active authority is reported without blocking the fix.

Waiting reasons are current work: unfinished jobs of both lanes, checkout locks, reserved preparations, phase
operations, reserved creation, unfinished documentary commits, runs awaiting acceptance, commit intents and
unresolved assistance. With none, the set switches immediately; otherwise its references stay pending with
`apply: live` and status APPLY_PENDING (**Apply when current work finishes**). Work continues and new admissions
use the active configuration until the switch; nothing is terminated, retried, advanced or rebound. Documentary
conversations and chat/profile proposals are not waiting reasons for a global set, since each later turn or
accepted proposal freezes the then-active configuration (generalizing D236); project-only sets keep refusing them.

The runtime promotes a pending live set at the first idle boundary (writer worker idle, after a confirmation, on
reads of the configuration state, at startup). It restages the candidate; a failure withdraws the pending
references with a PROMOTE operation whose result is FAILED, leaving the previous authority active. Promotion
rechecks references, evidence and waiting reasons in one write transaction and installs the staged objects
(configuration, project map, unavailable projects, loaded reference) by pointer swaps before it commits; workers
read the factories on every claim. A crash before promotion keeps the pending set and loads the previous one; after
it, startup loads the new one. Cancellation uses the existing CAS cancel. No schema change: the existing pending
columns, operation kinds and statuses carry the state.

Admission of a project task binds the exact receipt selected for the job's frozen project revision (its own, or
the one a confirmed activation retained for a nontechnical or derived revision), instead of requiring the receipt
to carry that revision's hash, which refused every task after a derived or agent-only revision.

## D239 — One-off tasks released as patch versions

Status: accepted. Supersedes the `0.1.2` assignment of D233.

At the owner's direction, each completed one-off task (D237) that changes the product is released on its own as
the next patch version: OT001 is `0.1.2`, OT002 is expected as `0.1.3`. Like D233's exception, such a release may
carry additive API/UI changes needed by its task, with the existing compatibility, explicit-migration and snapshot
guarantees; it changes no stored data format or frozen identity without a migration and decision. P001 **Metrics
Records** keeps its scope and task plan and targets the next patch version after the one-off queue empties;
P002 **Continuous Mode** keeps `0.2.0`.

## D240 — Question-first answers and the live activity rail

Status: accepted. Implements OT002; the full-width layout and the live activity rail were added to its scope at the
owner's explicit request in the implementation session, replacing OT002's exclusion of a global redesign for these
two changes only.

**Answers.** In onboarding, definition and phase planning conversations the reviewer's open questions are rendered
before the conversation history and its free composer, blocking first, with declared pending items apart. Each
question has an answer field whose draft is kept in browser local storage under
`harness-planning-answers-v1:<project>:<conversation>`, keyed by question id and bound to the question text and the
answered turn that asked it; typing calls nothing. One answer, the selected answers or all prepared answers are sent
only through an explicit review of the exact message, as one `PlanningMessageCreate` through the existing endpoint,
with its `expected_version` and the workspace's `Idempotency-Key`: one turn per submission. The message repeats each
question's text after a language-neutral marker `[q:<first 12 hex of the question id>]`; the UI derives the states
draft, waiting (queued turn), resolved (answered turn that no longer asks it), still asked and not reviewed (failed
turn) from the turns' messages and results, and drops a draft only when its question was resolved and its text was
sent unchanged. Drafts for questions no longer asked are offered for an explicit decision (include as earlier answers
or discard). The 20,000-character limit applies to the whole composed message, without truncation or splitting.
Question derivation, blocking, deferral and adoption rules are unchanged (D075/D102); deferral remains a separate
action with a reason. No API, schema or stored format changes.

**Layout and live activity.** Content uses the full window width instead of a 1120 px strip. A `Workbench` adds a
sticky right rail through a container query (side by side from 800 px of body width, stacked below otherwise), with
the main column first in reading order. The rail of project, phase, task, run, chat and planning pages shows the live
activity of the relevant run (latest run of the project, phase or task; the run itself; a conversation's latest
turn). It reads only `GET /runs/{id}/events`: windows below the run's version, then the forward cursor, and folds the
recorded `agent_event` records (Claude `stream-json` and Codex `exec --json`), lifecycle, validation and recovery
events into plain-language steps, newest first, with the block being streamed as a "now" line. Unknown events are
ignored and nothing is inferred beyond the records; the run page keeps the complete events and evidence.

Limits: drafts do not follow the user to another browser; states read from markers assume messages composed by this
UI; the rail shows at most the latest 60 steps and keeps 1,500 relevant events in the page.

## D241 — Actionable intake profile rejections

Status: accepted. Implements OT003 without changing D224's profile contract or D102's failed-turn rules.

Documentary profile commands use logical executable names in every direct `argv[0]`, with installed paths supplied
later by private configuration. `tools` is exactly the set of direct executable names, not tools invoked inside a
container or other command. Current intake prompts state this explicitly. A malformed executable name reports the
structural command field/index and the correction, without reflecting candidate paths, arguments or environment.
The existing strict parser remains authoritative and rejected output is never normalized or adopted automatically.

New planning contexts include each previous turn's recorded failure reasons alongside its status, so a later
reviewer can address the actual rejection. Failed answers still do not become prior valid answers or proposals.
The UI labels document lists from rejected responses as unavailable to apply. Earlier answered proposals and open
questions retain their existing behavior. No automatic retry, provider invocation, history rewrite, schema migration
or API contract change is introduced. Frozen requests and catalogs keep their original bytes; only newly frozen
contexts and current built-in prompt identities change.

## D242 — Task ownership and delivery disposition before product changes

Status: accepted at the owner's request. Clarifies D237/D239 and the completion rule for the one-off queue.

Every product change must have a recorded owning phase/task or one-off ID before implementation, with an agreed
delivery disposition: roadmap work under its phase or a bounded out-of-roadmap fix/development needing its own
distribution. Record the topic branch, target version/route and unfinished delivery steps. Do not silently attach
an unrelated change to the active phase or hide it among another task's implementation.

Source implemented/tested, integrated into `develop`, release-merged into `main`, packaged/published and installed
locally are separate states. A source-complete one-off with agreed delivery outstanding stays in ONE_OFF_TASKS
until delivery is completed or the owner explicitly defers it to a recorded destination. This corrects the premature
removal of OT003 from the queue; its source evidence and historical checks remain valid. OT003 owns the intake
diagnostic/prompt/context/UI-label changes on `fix/intake-profile-diagnostics` and targets 0.1.4 outside P001.

D235's topic → `develop` → release PR/merge into `main` route and D239's separate patch-per-one-off rule remain.
A recorded target/priority is planning, not permission to commit, merge, push, publish, restart or install. Those
actions retain the session's authorization requirements. Documentation must report the actual reached state.

## D243 — Visual profile editing as OT004 before Metrics Records

Status: accepted for implementation, not implemented. Release target/order superseded by D246; scope unchanged.

The owner chose OT004 before Metrics Records, with its own patch after OT003: target 0.1.5 after OT003's 0.1.4.
The contract in ONE_OFF_TASKS is authoritative; P001/P002 and the six Metrics Records tasks keep their scope.
OT004 is a separate topic and delivery, not an extension of OT003's fix.

Extend the existing global/project versioned configuration editors with interactive forms for the currently
supported profiles, commands, paths, environment and per-agent configuration/tool capabilities. Expose effective
scope/inheritance and explain fixed provider/role restrictions, including the read-only reviewer. Applicable
global defaults/reusable profiles and per-project values/overrides must be distinguishable. Preserve existing
TOML interoperability, exact review/CAS, separate save/preparation/activation, immutable job settings and archive
behavior. This accepts making supported settings visible, not inventing general permission grants or changing
agent containment. Any required permission-contract change needs its own recorded design decision first.

## D244 — OT003 includes the profile-adoption blockers found in manual testing

Status: accepted at the owner's request, before OT003's commit/release. Extends OT003, not OT004 or P001.

The profile-adoption preview must distinguish informational `pending` notices from blocking questions, consistently
with the documentary acceptance rules and the UI's existing explanation. Notices are retained in the conversation
but do not prevent adopting a profile. A blocking question prevents adoption until resolved by a later answered
turn or explicitly deferred with its reason. Missing/changed applied documents, invalid/foreign drafts, changed
HEAD/inventory, frozen context/versions, candidate validity and exact confirmation/CAS remain gates.

When a proposal's bound documents have not been applied, identify the missing document paths and tell the operator
to review/apply them to drafts first. Identify changed/extra document paths separately. Revalidate the immutable
candidate against current document bytes only when that exact documentary base is present, so missing evidence is
not misreported as a malformed candidate. This changes no proposal bytes, binds no replacement documents and
grants no fallback or automatic adoption. Confirmation repeats all guards.

The existing profile UI explains document application before profile adoption, and saving a new profile draft only
for edits. An unchanged form does not enable redundant draft creation. The API keeps its response shape; OpenAPI
and generated types document the corrected `blockers`/`ready` meanings. This follow-up is part of the same 0.1.4
delivery and needs no provider invocation, historical rewrite, schema migration or new dependency.

## D245 — OT003 includes one confirmation for selected document proposals

Status: accepted at the owner's request, before OT003's commit/release. No OT004 implementation is included.

Definition/onboarding show a joint review of all currently applicable document proposals, with exact diffs and a
checkbox to exclude each document. One explicit confirmation covers only the selected reviewed proposal identities,
hashes, document bases and conversation version. Profiles, plans and historical/closed proposals are excluded.
Selection changes invalidate consent; a changed conversation requires a fresh review. The application rereads the
conversation and all selected document bases before applying, then reuses the existing CAS apply endpoint in order.

The sequence is not a filesystem transaction: stop at the first conflict/error or uncertain response. Report
acknowledged applied documents separately from the stopped/unconfirmed item and remaining documents; retain earlier
applied drafts and never retry, roll back or continue automatically. Reload reads authoritative per-document states;
the operator explicitly reviews the remaining proposals again. Each subsequent apply uses the reviewed version
advanced only by acknowledged own writes, never silently adopting a concurrent version.

This is UI orchestration over existing endpoints: no new API/schema, batch job, provider call or execution authority.
Documents go to the same draft area as individual apply (private for onboarding). Profile adoption, documentary
tree/commit, private configuration, preparation and activation keep separate confirmations and gates.

## D246 — OT005 preparation tool aliases before the visual editor

Status: accepted at the owner's explicit confirmation. Supersedes only D243's target/order, not its editor scope.

After OT003 was published as 0.1.4, the operator encountered `Unexpected symlink: .venv/bin/python` while reviewing
generic preparation. Read-only diagnosis traced it to the whole-checkout snapshot and `_links`' additional
`local_paths` requirement for otherwise declared byte-bound tool aliases. The configured executable loader itself
accepts symlinks. This is a new bounded preparation hotfix, not an amendment/rewrite of published OT003.

Record **OT005 → 0.1.5**, before **OT004 → 0.1.6**, then resume the unchanged P001 Metrics Records plan. Both are
outside the roadmap and retain separate topic/integration/release routes under D235/D239/D242. The proposed fix is
limited to read-only pre-existing aliases of explicitly declared, resolved and content-bound tools, retaining
write-scope, external-target, change-detection and receipt guarantees. It does not authorize arbitrary symlinks or
adding an existing environment to writable scope. Exact compatibility/receipt handling remains implementation work.

At the owner's request this session changes documentation only and leaves a handoff for another session after
`/clear`. OT005 and OT004 are not implemented. No new code/test, version bump, commit, merge, push, publication,
reinstallation, service restart, operator configuration change or real preparation/provider invocation is authorized
by this documentation-only instruction. The next session must preserve the uncommitted task documents, review the
handoff and work within OT005 before starting OT004; release/operation authorization must be established separately.

## D247 — Frozen read-only tool-link evidence in generic preparation

Status: accepted within OT005's implementation scope; no new write authority. D248 amends external directory
alias handling only for newly marked plans/receipts; the original policy remains for older evidence.

The owner resumed OT005 after the documentation-only handoff and authorized implementation and a source commit.
D246's separate release order/targets remain; publication, installation and operator actions are still separate.

New generic previews may admit pre-existing file-link chains outside `local_paths` only when the final regular
executable is an explicitly configured resolved/hash-bound tool. Resolve at most 40 file links with no directory
symlink traversal. Capture the exact chain paths, link text and modes as `read_only_tool_links` in the plan and
receipt. The whole-checkout snapshot remains bounded and never descends through directory links. Verify tools
against their frozen evidence before accepting these links, including after executor/native-command effects.
Existing private-local link rules and recipe sources remain unchanged.

This is additive inline journal/receipt evidence under `project-profile-preparation-1`, with no schema, TOML or
API request/response model change. Only plans/receipts carrying the new evidence opt in; older ones retain their
old link policy and bytes, including linked recovery. No history is backfilled. New evidence is immutable through
execution, recovery and receipt verification; missing, added or changed outside-local aliases are refused.
Protected-path links remain refused. Read-only aliases never extend write/local/environment paths and do not
accredit the rest of an existing environment: stable environment accreditation still uses `environment_paths`.
The cooperative before/after guards detect persistent changes; they do not provide OS isolation or rollback.

## D248 — External directory aliases only along frozen tool resolution

Status: accepted by the owner's explicit approval after the OT005 manual preview failure. Amends D247's
no-directory-alias rule only outside the checkout, for resolution of the explicitly declared executable.

A declared Homebrew interpreter may pass through `/opt/homebrew/opt/python@3.14`, an external directory alias.
Rejecting every such component prevented the original environment from reaching preview even after D247. New
previews opt in with `tool_link_policy = external-directories-1`; bounded component-by-component resolution records
file and external directory links (exact path, text and mode) along the tool chain, and the final executable/mode.
Every link counts against the same 40-link ceiling. Parent access still uses O_NOFOLLOW: directory aliases are read
and resolved explicitly, never silently traversed. The final regular executable must equal a declared frozen
resolved path and pass its frozen SHA-256 check. No external directory is enumerated and no extra writes are granted.

Directory links within the checkout remain refused, including a hop later cancelled by `..`. Broken/looping chains,
unbound targets, added/removed/changed aliases and protected checkout links remain refused. Scope and receipt guards
preserve the exact evidence; no silent rebinding, retry, environment accreditation or activation is introduced.
Plans/receipts without the marker keep D247's strict parent-directory policy (or its historical predecessor), including
explicit recovery. Existing evidence is not rewritten. The marker/evidence remain inline JSON under the existing
contract; no ORM/schema, configuration format, API model, dependency or recipe fingerprint changes.

## D249 — Complete generic preparation review within OT005

Status: accepted within OT005's existing exact-preview criterion; no execution/configuration authority change.

The owner's next manual screenshot shows that the plan now loads, but the UI prints `undefined` for file hashes and
blank step labels. The recipe renderer assumed fixed file bytes and top-level argv/labels; the existing generic
contract instead declares writable path/effect pairs and kind-based steps with nested commands. Include this bounded
review correction in OT005/0.1.5 before declaring the manual workflow successful; it is not OT004's visual editor.

Render generic write scope as possible effects, without inventing fixed content, diffs or hashes. Show private
directories, executor selection/instructions/write scope, exact declared argv and command cwd/timeouts/environment,
network/scripts and the technical commit. Give generic modes their own wording instead of Django wheel promises.
Preserve recipe v1/v2 review, journal labels, raw evidence, exact preview hash/configuration binding, reason and consent,
idempotency and separate activation. Only frontend presentation/catalogs and current parity/evidence change; no API,
schema, saved profile, provider execution or earlier plan/receipt rewrite. Reinstall locally for the owner's retest;
release remains conditional on their success report.

## D250 — Guided profile and agent forms over the existing configuration contract

Status: accepted within OT004's scope (D243/D246); no permission, API, schema or configuration-format change.

The owner resumed OT004 and authorized implementation, commits and its 0.1.6 delivery. The guided forms are UI over
the existing `local-config-9` global and `project-config-1` project tables; they introduce no settings store.

- **Global editor.** Agents keep their fields and also show other environment variables, an optional pinned client
  version and their tool capabilities. Reusable `profiles`, `compositions` and `agent_presets` get add/edit/remove
  forms. A profile still used by a composition cannot be removed from the form. Recipe compositions stay read-only
  (their executables/authorization are fixed by the recipe) and `recipes` remain TOML-only, preserved unchanged.
- **Project editor.** Mounted in the project's Settings as well as its overview, with the same save, preparation and
  activation gates. Editability mirrors `check_candidate`: before the first activation the profile, agents and policy
  stay those of the adopted proposal and admitted pair, and only installed paths of the proposal's tool names,
  command environment, authorization and limits are editable. Later, commands and agents (not provider) are editable;
  the profile requires the editing base bound to the committed documents. Policy is shown read-only (TOML edits it).
  Project identity, global reference, provenance and editing base are carried over unchanged.
- **Values.** Every control replaces only its own key, so values without a control survive form edits, conversion
  and conflicts. Argv, patterns and tool lists are one exact value per line; blank lines are removed only on blur and
  values containing a line break are read-only (edit them in TOML). Named values (environment, executables) are added
  under a checked name and removed explicitly; existing names are not renamed in place.
- **Capabilities.** Tool lists (`tools`, `allowed_tools`, `grantable_tools`) are offered only for a Claude Code
  executor, described as explicit CLI tool permissions rather than a file/network/sandbox switch. The reviewer is
  explained as fixed read-only and Codex as checkout-limited without lists. Lists made unsupported by a provider or
  role change are kept visible, block validation and are removed only by an explicit action: never silently dropped
  or granted.
- **Validation and preview.** Client checks mirror the server's strict rules (shell-free argv with a logical name,
  relative patterns/cwd, JUnit/formatter rules, absolute installed paths, exact authorization, limits, memory-disabled
  Claude environment, version form) to focus the field to correct; the server remains authoritative. Projects check
  only the sections their stage can change. Save reviews render the existing preview `effects`: per project whether a
  new preparation is required, derived global copies (only their global reference changes) and admitted work kept
  frozen. Editing calls nothing; save, preparation and activation keep their separate exact confirmations.

Unchanged: the profile proposal editor in planning, legacy/query-only gates, OpenAPI/client types (version only).

## D251 — Writer tool admission, bounded repetitive output and lease-renewal evidence

Status: accepted within OT006's scope; released as patch 0.1.7 under D239. No schema, migration, API contract,
configuration format, dependency or adapter version (`cli-14`) change.

OT006's failed real preparation launched its Claude executor with `--tools ''` and `--allowedTools ''` while asking
it to write files. With no usable tool, the model streamed text imitating tool markup (`<invoke`/`parameter` tags)
until Harness lost the preparation lease. Separately, the heartbeat thread exited on its first exception, so one
transient write failure (for example SQLite busy while every stream record was a separate write transaction) ended
renewal for good. A synthetic reproduction of that path yields the incident's exact `OwnershipLost` diagnostic. The
specific exception in the real incident was not recorded and remains unproven.

- **Writer tools.** A generic preparation whose executor has write scope and is a Claude CLI needs at least one of
  `Write`, `Edit` or `MultiEdit` both in the launch inventory and in the allowed rules, computed exactly as the argv
  (grantable tools stay absent without an explicit rule). Otherwise preview refuses with
  `profile_preparation_executor_tools`, and a plan queued earlier fails before any launch. Nothing is granted
  automatically. Codex keeps its workspace-write sandbox. Task executors and other roles are unchanged.
- **Output guard `output-guard-1`.** Claude assistant `text_delta` text is split into lines. Across the last 400
  completed non-blank lines, 20 or fewer distinct lines stop the owned process group (`repetitive_output`), and so
  does one unterminated line over 262,144 characters (`line_limit`). Native `tool_use` input (where file contents
  travel), thinking and Codex items, which `exec --json` does not stream as partial text, are not inspected. The
  attempt ends with status `repetitive`; generic preparation reports `profile_preparation_executor_repetitive` and
  issues no receipt. The capture keeps the raw artifacts and reports guard counters: text characters/lines,
  native tool uses and textual `<invoke` markers, kept apart. There is no retry, model/effort change or wider
  permission.
- **Usage honesty.** Captures add `final_usage_observed`: false unless one terminal result arrived. Message-start
  counters stay reported as initial values, never completed or summed into a total; `metrics-1` is unchanged.
- **Lease renewal.** The fencing guard (`owned()`) is unchanged. A non-ownership heartbeat exception is counted and
  retried within one second while the lease lasts; only `OwnershipLost` ends renewal. Settlement records
  `{failures, last_error, lost}` and, when ownership was lost, a diagnostic naming the renewal failure instead of a
  bare `OwnershipLost`. The lease length is not increased.
- **Write pressure.** The preparation agent journal writes each read chunk's events (bytes plus parsed records) in
  one guarded transaction instead of one per record. Event content and order are unchanged. The managed run
  journal still writes per record; that wider question is left to a later task.
- **Interrupted evidence.** When an invocation raises after spawning (for example lost ownership), the adapter stops
  its group and writes `capture.json` (status `interrupted`) beside its artifacts, because the fenced journal may
  refuse the write. The closing owner then settles its own still-`RUNNING` process rows before `owner_closed`. It
  sets status from an independent group-liveness check (`STOPPED`/`UNCERTAIN`), keeps the reported state and that
  partial capture, never replaces a stored capture and never completes a step. Lease expiry or a stale row is
  never treated as proof that a writer stopped. Recovery still uses the existing confirm-stopped/linked-successor
  route.

## D252 — Managed-run lease renewal, chunk journals and interrupted process evidence

Status: accepted for OT007; released and installed as patch **0.1.8** through
[PR #7](https://github.com/AcostaDDev/my-harness/pull/7), merge/tag `c005298` / `v0.1.8`.
Extends D251's runtime reliability treatment to the shared managed supervisor (task, phase, chat and definition
lanes). No schema, dependency, configuration, API contract or frozen adapter/version change.

- A non-ownership heartbeat exception is counted by exception class and retried within one second. Successful
  renewal restores the normal lease/3 cadence; `OwnershipLost` stops renewal and the next journal operation.
  Every write retains the original token/status/lease/checkout fencing. Exhaustion also stops the attempt through
  that guard; no lease is lengthened and no provider invocation is retried. `process_owner_closed` records
  `{failures, last_error, lost}` when renewal encountered trouble, including recovered failures. A fenced journal
  failure after renewal trouble names the last renewal exception in an en/es diagnostic, without raw SQL or values.
- Managed `process_updates` records the bytes and parsed events of each CLI read chunk in one guarded transaction.
  The single-event entry point delegates to it. Contents, ordering, per-event sequences, history/projection and
  metrics semantics remain unchanged; an invalid batch rolls back in full.
- The closing owner settles only its own still-`RUNNING` process rows with no stored capture, before marking its
  owner scope closed. Independent group liveness selects `STOPPED` only for `dead`, otherwise `UNCERTAIN`.
  The adapter's partial `capture.json`, when readable as an object, is retained with its reported group state
  separate from the observed state. Missing/malformed capture leaves explicit interrupted evidence. No stored
  capture is replaced, attempt is completed, history is rewritten, lock is released or stopped writer is inferred
  from lease expiry. Quarantine and explicit confirm-stopped remain the recovery route.
- `output-guard-1` already surfaces in the managed attempt status (`repetitive`), stop reason and process/attempt
  metadata. Synthetic coverage verifies this path; no new API/UI or output-guard policy is needed.

The owner explicitly authorized commit, integration/push, release PR/draft and verified archive/checksum, merge,
publication/public verification, offline installation with the service stopped, and closure. This does not authorize
real providers, a project retry or service start. Evidence: [OT007](archive/one_off_tasks/OT007-task-run-lease.md).

## D253 — Phase release targets after 0.1.8

Status: accepted at the owner's explicit confirmation during P001-T001.

P001 Metrics Records targets **0.1.9**, published at phase closure; P002 Continuous Mode retains **0.2.0**,
published at its closure. The initial request named 0.1.8, but OT007 already published that version; the owner
confirmed 0.1.9 after this discrepancy was raised. Released tags/assets and their evidence are not rewritten.
This fixes P001's current target under D239 and retains D233's specific allowance for additive metrics changes
in that patch. Package/API/UI version metadata stays 0.1.8 until T006 qualifies the release candidate.

Each phase task uses a topic branch from `develop`, with checked source integrated there. The owner authorized
commit, merge where necessary and push for this session's task. That task delivery is separate from release PR,
merge/tag on `main`, distribution verification/publication at closure, and local installation (D235/D242).
T001 completes design only; it neither closes P001 nor publishes or installs anything.

## D254 — Native invocation accounting and immutable evidence

Status: accepted design in P001-T001; implementation pending T003–T004.

The [accounting contract](archive/phase-001/P001-T001-accounting-contract.md#4-record-grain-identity-and-completeness-d254)
adds a shared invocation ledger keyed by native source kind/ID: managed attempt, generic preparation executor step,
or configuration-assistance operation. Assistance/preparation retain their own journals without fabricated managed
attempts. Deterministic work has no model invocation; expected but result-less invocations stay visible in coverage.
Intent identity is persisted before launch; absent process evidence alone does not prove zero consumption.

Versioned captures, evidence interpretations and model/request components are append-only and digest-bound. Terminal
totals, constituent messages, model partitions and inclusive delegated parents are alternative views, not amounts
to add together. Unknown model association, partition, inclusion or final usage leaves an explicit incomplete case.
Requested model/effort never certifies reported selection. `metrics-1` and its historical semantics remain intact;
new normalization is `usage-accounting-1`. D251/D252 fencing and independent stopped-writer rules remain authoritative.

## D255 — Versioned billing profiles and offline reference binding

Status: accepted design in P001-T001; implementation pending T002–T005.

Global `local-config-10` will own named `billing-profile-1` definitions/defaults; `project-config-2` may select them
per configured role. Existing versions retain bytes/hashes and load with unknown billing metadata. New-format save
and activation remain explicit CAS confirmations with D238 boundaries; billing-only metadata must not invalidate
otherwise compatible technical receipts. Admission/assistance/preparation freeze the resolved profile and reference
bytes/digests. Existing queued jobs/plans without a binding stay unknown, not rebound to current settings.

Model identity and tariff references are separate content-addressed `metrics-reference-1` documents, pinning exact
identifiers, product/scheme/unit, source/locale/observation, effective interval or explicit unknown, conditions and
structured overrides. T002 packages immutable seed data; T003 stores referenced bytes; T005 offers explicit bounded
JSON import through configuration. No network refresh on reads or calculation. Conflicting identity/content or
unresolved applicability cannot silently select a tariff. Subscription-equivalent scenarios are labelled separately
from API USD, Enterprise USD, credits and reported estimates. Billing metadata never changes CLI authentication;
there is no invoice/balance integration, billed-amount editor or universal credit/USD conversion in P001.

## D256 — Disjoint quantities and exact decimal valuations

Status: accepted design in P001-T001; implementation pending T002–T005.

The [calculation contract](archive/phase-001/P001-T001-accounting-contract.md#6-normalization-calculation-and-discrepancy-d256)
defines `valuation-1`: disjoint uncached input, cache reads, writes by evidenced lifetime, output and separately
evidenced tool charges. Reasoning remains inside output. Claude excludes cache from raw input; the established
Codex CLI baseline includes reads, while nonzero-write semantics remain uncharacterized. Responses API write
partition documentation is not evidence of CLI emission and cannot change `metrics-1` in place.

Rates/amounts use decimal strings and bounded Decimal arithmetic with precision 160; exact line sums are rounded
once per invocation to 12 places with ROUND_HALF_EVEN. Aggregation sums persisted rounded totals exactly. Modifiers
are reference/category-specific, never inferred from effort or speed. Missing TTL, request tier, model, scheme or
charge evidence yields complete/incomplete/unsupported results with coverage and stable reasons; no zero/default
tariff fallback. Comparable reported estimates keep a signed delta and evidence-based precision tolerance; unknown
bases are not comparable. Existing float records are preserved. Full details and synthetic boundary/rounding cases
are in the contract; T001's arithmetic checks are documentation evidence, not an implemented calculator.

## D257 — Additive accounting history, explicit cohorts and archive parity

Status: accepted design in P001-T001; implementation pending T003–T006.

New invocation/capture/component/reference/valuation/cohort tables are additive; T001 changes neither schema nor
API. T003 uses D150 snapshot-before-migration, native-source transactions and unique digest keys. Legacy results,
metrics/configuration hashes, run projection, frozen summaries/catalogs and recipes are never overwritten. Preserve
`metrics-backfill`; add explicit, previewed accounting backfill/repricing with bounded cohorts and reports.
New interpretations/values append records. Ordinary totals use original admission-bound valuations; explicit
analysis selects one closed cohort, counting each invocation once. No implicit latest-price selection or GET-time
backfill/recalculation. Incomplete cohort construction cannot advertise full coverage.

Retention preserves sufficient accounting evidence and all referenced bytes. T003 adds backup format 3 with digest
and native-link verification; older formats retain their supported matching-schema contract. Old archive upgrades
need a documented explicit copy/new-bundle path, not in-place query-only mutation. Restored consultation works
without roots, clients, network or executable authority. T004 adds bounded decimal-string API contracts alongside
unchanged legacy fields; T005 keeps en/es and archive controls in parity. All planned data/flows are labelled
unimplemented until the corresponding task provides code and evidence.

## D258 — Pinned reference cases and the pure valuation boundary

Status: accepted implementation detail in P001-T002, within D255/D256; operational integration pending T003–T005.

`metric_references.py` validates separate canonical `metrics-reference-1` identity/tariff documents and content-addressed
bundles. Tariffs enumerate exact condition combinations, request intervals, category rates/factors, already included
adjustments and exclusions. The reference language is data only. Overrides require a new sourced reference; no ad hoc
factor, implicit Standard case, network refresh or mutable model-name identity is used. Ambiguous overlapping versions
cannot share a bundle; a different unknown-period observation uses another bundle, preserving the original bytes.

The packaged `metrics-2026-10-27-v1.json` derives from the immutable T001 observation, including its source URLs/digest.
It covers the eight suggested models plus Terra, with known conditions/unknown historical effective periods retained.
It does not certify current prices, account eligibility, agreement terms or historical tariff validity. Explicit
retrospective scenarios retain an unknown-period warning; ordinary historical valuations remain incomplete.

`valuation.py` takes JSON-safe `usage-accounting-1` evidence, a `valuation-scenario-1` input and a validated pinned
bundle. The scenario is a pure calculation input, not a new operational configuration format. The caller must supply
a reconciled single view or disjoint request/model partition, model-response provenance and reported/asserted
conditions; T003 owns capture reconciliation and frozen billing-profile binding. Responses API semantics remain
separate from Codex CLI semantics. Charged tools use independently evidenced quantities/references, never client
activity counts. Exact Decimal lines and once-per-invocation rounding follow D256. Result digests, line evidence,
unknown reasons and separate estimate comparisons support later immutable persistence; no operational caller,
database, API, configuration, frontend, version bump, distribution publication or installation is added here.

Evidence and task delivery: [P001-T002](archive/phase-001/P001-T002-reference-calculator.md).

## D259 — Native accounting capture, frozen revision binding and format-3 archives

Status: accepted implementation detail in P001-T003, within D254–D257; queries/API remain T004, controls/UI T005.

The adapter keeps `cli-14`/`terminal-2`; its stream summary gains an additive `usage-stream-1` section with Claude
requests keyed by message id (a repeated start with different evidence is a conflict, a delta replaces the current
message's counters) and the terminal's exact cost lexemes. `metrics-1` never reads it. `usage-capture-1` is an
allowlisted, float-free document built from the native source's sealed process evidence: client/version, requested
selection, native status, reported selection, response/model-usage models, raw counters, reported amounts as lexeme
or labelled legacy float, activity, timing and artifact digests, never prompts, argv, environment or paths. One
terminal is final usage even when the structured payload was invalid. The launch gate is `not_invoked` only on a
refused launch (no permitted launch or a stopped gate wrapper) and `unknown_execution` without positive evidence.

Evidence selection prefers a complete request partition that reconciles with the terminal, then a reconciled
`modelUsage` partition (the lone cache writer inherits the terminal lifetimes), then a single response model, else
`model_unreported`/`model_partition_unknown`. Delegation tools (`Task`, `Agent`) leave the boundary unknown; server
tool activity or nonzero server-tool counters leave charges incomplete. Absent Codex write counters stay absent.

Admission already seals exact immutable configuration revisions (job `versions_json`, preparation plan data,
assistance preview source). The invocation intent dereferences those revision bytes into a content-addressed
`billing-binding-1` (profile with asserted conditions, or an explicit unknown reason), never the active/working
configuration. `local-config-10`/`project-config-2` add only `billing` profiles/defaults/selections; billing is
validated separately, removed before composing the runtime (v10 runs exactly as v9) and outside `technical()`.

Migration `0028_usage_accounting` adds eight tables (62 product tables). Invocation IDs are `<source_kind>:<id>`; its
downgrade refuses while accounting rows exist. Backfill materializes settled native sources (legacy metrics-only
attempts as `legacy-metrics-1` evidence) with `backfill` valuations, never admission-bound ones; repricing applies a
stated scenario. Both freeze at most 10,000 members at preview, build in bounded transactions, resume by
idempotency key from their frozen selection and only then close. Reference import validates a bounded canonical
bundle. CLI: `accounting-references`, `accounting-backfill`, `accounting-reprice`, `backup-upgrade`.

Backup format 3 records the accounting inventory and recomputes reference, capture, binding, valuation (identity and
exact line sum) and cohort digests in the same snapshot. Bundles of an older schema require `backup-upgrade`, which
migrates a private copy into a new query-only format-3 bundle and leaves the original bytes unchanged.
Evidence: [P001-T003](archive/phase-001/P001-T003-capture-storage.md).

## D260 — Quiet development checks and economical agent workflow

Status: accepted for OT008 at the owner's request. Development tooling for this repository only; not a product
feature and outside the distribution.

`scripts/check` (standard library) runs the AGENTS command sets through the pinned offline `uv` invocation and prints
one line per suite with its counts, then failing IDs with their first error line (at most 20 entries, each line
clipped). Default suites are unittest, `alembic check` and full pytest; given paths, only pytest runs over them, with
options after `--`; `--frontend` adds the Node tests (TAP reporter) and `npm run build`, which already runs `tsc
--noEmit`. `alembic check` upgrades and checks a fresh temporary SQLite (`HARNESS_DATABASE_URL`), never the
development database. Each suite's full output replaces `.local/check/<suite>.log` (written to a per-process file and
renamed, so concurrent runs never interleave); the exit status is nonzero on any failure. `scripts/check-docs` checks
tracked Markdown (or given files) for local link targets and anchors (GitHub heading slugs with `-N` duplicates and
explicit `<a id>`/`<a name>`; external URLs are not fetched), unclosed fences, en/es key parity in both catalog pairs,
and every "head `…`, N tables" statement in `docs/DDBB-DIAGRAM.md` against `SCHEMA_REVISION`, the migration chain head
and the mapped `__tablename__` count.

AGENTS.md tells every client (Claude Code, Codex) to use these wrappers, to choose the cheapest sufficient check,
and to read files by range or after `grep`. CLAUDE.md stays a thin import. At the owner's choice, no project
`.claude/settings.json` (permissions or hooks) is added, so both clients follow the same text-only guidance. The
managed-project isolation is unchanged: adapters still disable client hooks and project configuration, and managed
projects keep the engine's deterministic, journaled formatter/validation/JUnit steps. The new scripts are not in
`BUNDLE_SCRIPTS` or the wheel/sdist, so delivery is source-only into `develop` with no patch release (D239 applies
to product changes). Evidence: [OT008](archive/one_off_tasks/OT008-development-checks.md).

## D261 — One-off tasks branch from the latest release, not from `develop`

Status: accepted at the owner's request on 2026-10-28. Refines D235/D237/D239/D242 for one-off tasks.

`develop` carries phase work that is not yet released. A one-off task therefore never branches from or merges into
`develop` alone. Its topic branch (`<kind>/<topic>`) starts from the latest release tag on `main`. A one-off that
changes the product is released from that branch through `main` as its own patch version (D239), and `main` is
then merged back into `develop`, as D235 already does for fixes to a published version. A one-off that changes
nothing released (development tooling, documentation only) waits on its branch and reaches `main` with the next
release. Its delivery route is recorded and confirmed before edits (D242) against this rule.

OT008 was registered with the route topic → `develop` and was merged there (`eb80123`, pushed) before this rule was
written down. It is development tooling outside the distribution, so it stays in `develop` and reaches `main` with
the P001 closure release (0.1.9). Its history is not rewritten or reverted.

## D262 — Bounded accounting aggregates and the read-only accounting API

Status: accepted implementation detail in P001-T004, within D254–D257 and the T001 §8 aggregation contract; controls
and UI remain T005.

`storage/accounting_views.py` reads the T003 ledger only. One SQL row per native invocation joins its latest
append-only capture (the newest evidence, as repricing already selects) and the valuation(s) of one explicit
selection policy: the original admission-bound valuation (earliest `admission` row) by default, or the frozen
membership of one named cohort. In a cohort analysis non-members in the filters are counted as `outside_selection`
only; a `BUILDING` cohort yields known subtotals but no full amount. Run histories are never decoded; nothing prices,
backfills, launches a client or writes, so the same reads work on a restored query-only archive.

Derived per invocation: provider (the agent's frozen `<agent>_provider`, else the capture client), effective model
from the selected evidence components (`reported` when every component names the same model, `mixed` for several,
`unknown` otherwise; mixed/unknown are visible groups, so each invocation enters exactly one group), UTC start day,
and work class: `task_first_pass`, `task_rework` (a later run of the same task, or the run's second execution
and every attempt after it), `phase`, `conversation`, `setup` (preparation and configuration assistance) or `other`. A phase
filter without an explicit work selection uses the phase-work default (conversations and setup excluded) and names it
in the response. Filters: provider, role, purpose, source, outcome, launch, requested/effective model and kind, work
and UTC start `[from, to)`; root/phase/task come from the existing project scope.

Coverage counts expected invocations (not-invoked excluded and shown), launch states, captures, complete/partial/
absent usage, complete/incomplete/unsupported/unpriced valuations and grouped unpriced reasons. Amount buckets add
only identical unit/platform/product/scheme/basis/counterfactual/retrospective valuations as exact decimal strings;
`amount` is null unless every valuation in the bucket is complete, no expected invocation is unpriced and the
selection is complete, while `known_subtotal` always shows what is known. Token sums are per category with
contributor counts and partial contributors; Codex uncached input is input minus cache reads. Cache hit and wall
throughput use only complete usage with every needed quantity known and report the excluded count. Task indicators
divide the bucket total of every attempted task invocation by verified-COMMITTED tasks (null while any task's
commit is only an `INTENT`) and by attempted tasks, rounding half-even to 12 places, with committed-only work
separate. Groups and invocation pages are offset-paginated over a stable order; pagination never changes totals.

API (additive, `accounting-aggregate-1`): `GET /api/managed/accounting/{summary,groups,tasks,invocations,cohorts}`,
`/accounting/invocations/{id}` and `/accounting/invocations/{id}/valuations` (lines, reference identity, discrepancy
and cohort memberships). Existing `/metrics/*` endpoints, `metrics-1` floats and frozen phase summaries are unchanged.
Evidence: [P001-T004](archive/phase-001/P001-T004-aggregates-api.md).

## D263 — P001-T005 split, accounting page and billing/reference control contracts

Status: accepted design before P001-T005 implementation, within D254–D257, D259 and D262; nothing here is implemented.

The owner split T005 into two bounded, sequential deliveries, each on its own topic branch from `develop` →
`develop`/`origin`: **T005a** (accounting UI, read-only over the D262 API, no API change) and then **T005b**
(billing-profile and reference controls, with an additive API). D234's six-task plan is otherwise unchanged; both
record evidence in `docs/phase/P001-T005-metrics-ui.md`, and T005 completes when both are delivered.

- **Accounting page (T005a).** A new page, global and per project and available on query-only archives, consumes
  only `/api/managed/accounting/*`. The existing Statistics page stays on `metrics-1` (its cost is the reporting
  client's estimate) and links to it, so reported estimates and calculated valuations never share a figure. Backfill
  and repricing stay CLI-only (`accounting-backfill`, `accounting-reprice`): the page lists and selects cohorts and
  names the command, as Statistics does for `metrics-backfill`. Archives show no mutation control and do not poll.
- **Reference API (T005b).** The configuration router (`/api/managed/configuration`) gains
  `GET /references` (bounded page of available bundles: packaged and imported, with source, provider/product/models,
  observation date and effective-period state), `POST /references/preview` and `POST /references/import` over the
  T003 backend. The import writes immutable accounting reference rows, not a configuration revision, and activates
  nothing; a profile adopts a bundle only through a confirmed configuration save/activation. The list reads stored
  rows and the packaged bundle without inserting them and does not depend on the configuration setup, so it also
  works on a restored archive; both POSTs keep the restored-archive refusal.
- **Idempotent import.** Importing equal bytes is idempotent (D255), so a retried confirmation must not fail as
  stale: the preview digest seals the bundle id, raw-byte digest, reference count and conflicts, while new/existing
  row counts are informative and outside it. Confirming after the rows already exist returns the same report with
  zero inserted rows; a conflicting id still refuses. The CLI keeps the same preview → confirm contract.
- **Save-time billing validation (T005b).** Server previews refuse what would otherwise surface later as
  `billing_profile_unknown`: a global profile whose `references` bundle is not available (packaged or imported); a
  project's explicit `project-config-2` selection that its referenced global revision lacks or whose provider
  differs from the project's agent for that role; and a global save that removes or changes the provider of a
  profile still selected by a derived project copy (the affected projects are named, like a profile used by a
  composition). Inherited global defaults are not refused for projects, since `project-config-1` bytes keep their
  meaning: the preview effects report each role whose default would resolve as unknown.
- **Formats.** Billing controls appear only after an explicit conversion to `local-config-10`/`project-config-2`
  shown in the save preview; loading never converts. Billing-only saves keep the technical receipt (D259); frozen
  jobs keep their binding. Guided forms follow D250 (controls replace only their own keys; TOML remains complete).

## D264 — Accounting page routes, exact amounts and derived reference period

Status: accepted implementation detail in P001-T005a, within D262 and D263; no API change.

The page lives at `/accounting` (sidebar) and `/projects/:p/accounting` (project navigation), and Statistics links to
the matching scope. Like Statistics, only the global page is mounted on a query-only archive and while configuration
is not ready; project routes stay blocked there. Live reads refresh every 15 s; the invocation detail and its
valuations are read once; an archive never polls. Filters, cohort selection and pagination are client state, not URL.

Amounts are formatted from the API's exact decimal strings by regrouping their digits in the visual language, never
through a binary float: trailing zeros after the last significant decimal are dropped (two decimals at least for an
ISO currency) and the exact string stays in the tooltip. A bucket shows `amount` only when the API gives it; otherwise
its `known_subtotal` with a "partial" mark. Units without an ISO code are named (`chatgpt_work_codex_credit` →
credits); unknown units and codes are shown as is.

The API's reference rows carry no effective period, so a valuation's period state is derived from the calculator's
codes (D258): `reference_out_of_period` or a blocking `effective_period_unknown` reason, the retrospective warning, or
"applies" when neither is present and references were used. The client-reported cost appears only in the invocation
detail (from the allowlisted capture) and in each valuation's comparison, labelled as an estimate of unknown basis.
Evidence: [P001-T005a](archive/phase-001/P001-T005-metrics-ui.md#t005a--accounting-ui).

## D265 — Billing controls, reference listing and save-time billing review

Status: accepted implementation detail in P001-T005b, within D250, D255, D259 and D263.

- **Reference API.** `GET /api/managed/configuration/references` pages (≤ 50) the packaged bundle first, then imported
  bundles newest first, each with its source, stored time (none while the packaged bundle is unused), counts,
  providers/models, observation range, effective-period state (`unknown`/`known`/`mixed`) and tariff schemes with
  bases, models and case-condition values, so a profile can be filled from a listed scheme. A row that no longer
  loads stays listed as unavailable. It reads through the runtime engine, not the configuration setup, and never
  inserts rows. `POST …/references/preview` and `…/import` take the bundle as JSON text (UTF-8 bytes, ≤ 1 MiB);
  invalid or oversized bundles answer 422, stale previews and conflicts 409. The import needs no idempotency key:
  equal bytes are idempotent by content, so the preview digest now seals only bundle id, raw digest, reference count
  and conflicts (D263) and a store-time conflict race is refused as `reference_conflict`.
- **Save-time review.** Validated save previews call `billing_review` before sealing: refusals (an unavailable pinned
  bundle; an explicit project selection the referenced global revision, or the global candidate of the same save,
  lacks or whose provider differs from the project's agent) raise `billing_configuration_refused` with path-free
  `{project, role, setting, code}` details, using the D238 detail shape. Derived copies carry their selections, so a
  global save that removes or re-providers a selected profile names those projects. Roles that would resolve as
  unknown through an inherited default are reported as `effects.billing_unknown`. The same pure `choose` drives the
  frozen binding (D259), so a refusal matches what admission would resolve. Drafts are not reviewed.
- **Controls.** Conversion is one explicit button that changes only `format`; billing controls appear after it. The
  global form edits profiles (identity, basis, pinned bundle, sourced conditions) and per-role defaults offering only
  profiles of the role's provider; a profile used by a default cannot be removed there. A listed scheme fills only
  identity, basis and bundle: conditions are never prefilled, and missing required ones are named as making
  valuations incomplete. The project form selects per role among the referenced global revision's profiles or
  inherits its default, showing what each role resolves to. Refusal details appear in the save review and in toasts.
- **Where the list appears.** Import controls live only on the global configuration page. The read-only list also
  appears on the global accounting page, which is mounted on query-only archives (D264); the configuration page is
  not, and archives keep refusing both POSTs.

Evidence: [P001-T005b](archive/phase-001/P001-T005-metrics-ui.md#t005b--billing-profile-and-reference-controls).

## D266 — Manual phase closure and archive in this repository

Status: accepted at the owner's explicit authorization of the P001 closure (2026-10-29).

This repository follows the D088 layout but is developed by hand, so the harness's unified closure (D091) cannot run
on it. P001 is closed by hand with the same result, adapted where D091 relies on the harness's SQLite:

- `docs/archive/phase-001/` receives STATE and NEXT_STEPS as they stood at closure and every P001 work file from
  `docs/phase/` (handoff, references, observation JSON, task evidence). Their text is kept; only relative link targets
  are re-based to the new location so local links stay checkable. Work files of other owners (one-off evidence,
  bounded fixes, earlier patch notes) stay in `docs/phase/`.
- REVIEW is not produced (there is no harness review history for a hand-developed phase); a hand-written `SUMMARY.md`
  lists the tasks, decisions, release, installation and evidence instead.
- The same commit leaves STATE with the compacted accumulated baseline (the 24 KiB budget), NEXT_STEPS with P002's
  objective and criteria but no tasks, and ROADMAP with P001 completed and linked. P002 becomes active without a plan;
  its design and task plan need the owner's confirmation before any code (as D234 did for P001).
- Closure happens only after the phase release is published and verified (D253/D235) and its delivery states are
  recorded (D242); in P001 the operator installation also preceded the closure record. Archived files are not
  rewritten afterwards; later facts go to current documents.

Evidence: [P001 summary](archive/phase-001/SUMMARY.md),
[T006 release, installation and closure](archive/phase-001/P001-T006-qualification.md#release-installation-and-closure).

## D267 — Archive completed one-offs separately from active phase work

Status: accepted at the owner's request on 2026-10-29; repository documentation/workflow only. Refines D237/D242
and the placement of non-phase records retained by D266. No managed-project schema, flow or runtime is changed.

Keep active work evidence in `docs/phase/`. Once a one-off's change reaches `main`, move its completed record to
`docs/archive/one_off_tasks/`, update the archive index and current references, and preserve its historical
text/results. Main integration is the archival gate; it does not imply publication or installation. Any remaining
agreed delivery stays visible in ONE_OFF_TASKS with the archive link until completed or explicitly deferred under
D242. A source-only change still waiting to reach main is not archived merely because its topic work finished.
One-off branch/release routing remains D261; this policy performs no Git merge, publication or installation.

The initial cleanup relocates OT001–OT008, their queue/OT002 handoffs and the pre-numbering activation fix to that
archive, and the earlier model-selector/npm-baseline notes to `docs/archive/project-history/`. The 13 records are
already present in the recorded `origin/main` release at `5cc1bc1`; local `main` is not advanced and no fetch occurs.
Only relative Markdown navigation destinations change during relocation; no statuses, results, dates, release
claims or source evidence are rewritten, and no new OT identifier is assigned retroactively.

**Explicit, bounded D266 exception.** The owner separately authorized only the 17 navigation-target updates needed
in `docs/archive/phase-001/STATE.md`, `NEXT_STEPS.md` and `P001-metrics-records.md` so their references follow the moved
records. Their historical prose/results and all other P001 artifacts stay unchanged. This is not permission to
rewrite archived facts, frozen histories, fingerprints, catalogues, recipe sources or published release contents.

Evidence: [P002 planning maintenance](phase/P002-portable-tools-and-archive-maintenance.md) and the
[archive index](archive/README.md).

## D268 — P002 scope: complete-roadmap autonomy and evolving plan baseline

Status: accepted at the owner's explicit authorization of P002-T001 (2026-10-29); implementation pending T002–T023.
Supersedes D156 and D233's Continuous Mode description; the 0.2.0 target of D253 is retained.

P002 delivers optional autonomy over the **whole authorized roadmap** of a defined or onboarded project, without a
phase-count cap, together with the authority redesign the owner requested: LangGraph orchestration, database-owned
structured knowledge, generated documentation with explicit import, portable tool discovery, a configurable judge,
standing revocable grants, correlated tracing, a global inbox and a task-instance graph. Manual mode remains and
shares the same domain operations. No new objective, extra roadmap phase, push, release, publication or deployment
follows from autonomy; completion means every authorized phase CLOSED with satisfied criteria.

The draft v0.2 plan and the [design basis](phase/P002-design-basis.md) are adopted as the evolving baseline; the
[T001 contracts](phase/P002-T001-contracts.md) refine the plan to v0.3. Tasks keep stable IDs and may be refined,
split or added with recorded reasons, without dropping acceptance, qualification or pending delivery. Accepted
design binds implementing tasks but is never reported as implemented; SPECIFICATION §§1–13, ARCHITECTURE §§1–12
and `docs/flows/` describe 0.1.9 until each owning task replaces them with parity. Adoption authorizes no source work,
dependency, harness or agent execution, commit or delivery.

## D269 — LangGraph orchestration over SQLite domain authority

Status: accepted design in P002-T001 (owner direction); dependency adoption pending T002, implementation T003–T006.

LangGraph is the orchestration direction: a versioned graph definition decides stages, branches and resumable waits.
SQLite domain records own project knowledge, accepted revisions, decisions, grants, rulings and operation outcomes;
trusted application services validate and perform effects behind typed commands. Graph state holds identities and
revision references, never an editable copy of authority. The supervisor stays the only process launcher with one
writer per checkout; a replayed node reconciles the same operation instead of creating a new effect.

The invariants INV-01–INV-12 of the [contracts](phase/P002-T001-contracts.md#3-authority-model) bind every task. The
exact version, locked dependency set, offline packaging, placement relative to the standard-library-only core and the
continuation/journal consistency contract are gates G01–G03; a feasibility blocker returns to the owner rather than
silently selecting another runtime. Adding the dependency needs its own recorded decision with exact versions.

## D270 — Database-owned project knowledge and immutable accepted revisions

Status: accepted design in P002-T001 (owner direction); implementation pending T004, T007, T011–T013. When implemented
it replaces the Markdown authority of SPECIFICATION §§2/6 and ARCHITECTURE §5 for managed projects.

Requirements and criteria, phases, tasks and dependencies, product decisions and supporting rich content become
structured, related and revisioned database records. Concepts that need identity, constraints, querying or history
are normalized; descriptive prose and Mermaid stay versioned rich content. Adoption creates an immutable accepted
revision against an expected revision; history is never rewritten. Each invocation freezes the revision it receives
and its tool reads default to it; later revisions apply at a new invocation or attempt. Validation, review,
acceptance, READY and closure bind that revision with the exact code content.

Both entries are kept: definition creates database drafts and accepted knowledge; onboarding keeps static inventory
and reverse engineering, storing known, inferred and unknown provenance in the database. Entity boundaries (G06) and
the authority of instruction files (G07, D094 meanwhile) remain open. This repository keeps Markdown authority.

## D271 — Generated documentation targets and explicit manual import

Status: accepted design in P002-T001 (owner direction; replacement policy as a T001 resolution); implementation
pending T013–T015. It redefines SPECIFICATION §5 rule 8 for owned generated targets only.

Exported Markdown is a generated view. The harness never compares exported files with the database, warns about drift,
creates conflict items or imports IDE edits automatically. A versioned ownership manifest declares the generated
targets; at task commit, closure, owner regeneration or manual adoption the harness renders the accepted revision and
replaces them. The expected prior state of an owned target is HEAD's committed bytes or absence on a clean baseline;
uncommitted edits refuse the operation, so no uncommitted bytes are discarded. Root, link, traversal and
unowned-collision guards remain. Export intents, per-target outcomes and generation manifests make partial exports
recoverable without rerunning inference; a task commit requires its required generated documentation. Agents never
write owned targets.

An explicit UI import parses a supported format, stages proposals, reports unsupported or lossy content and adopts a
previewed canonical change by hash. Imports never create runs, approvals, grants, rulings, usage or execution states.
Document import, portable project transfer and evidence-bearing backup/restore are separate capabilities. The format,
manifest and identity mapping are G09
([contracts §6](phase/P002-T001-contracts.md#6-generated-documentation-and-explicit-import)).

## D272 — Authorization origins, product decisions and operational rulings

Status: accepted design in P002-T001 (owner direction; origin vocabulary as a T001 resolution); implementation pending
T004, T005, T009, T010, T012, T016.

Every authorization, adoption, grant and effect records its origin: `owner_confirmed` (exact preview hash in the UI
or inbox), `owner_delegated` (derived by the harness from an active autonomous authorization for a concrete sealed
preview, naming the parent, policy rule and any ruling) or `harness_deterministic` (mechanical effects already
covered). A parent authorization never confirms future content; children never exceed it. Delegated approvals are
never shown as owner approvals.

Product decisions are canonical versioned records exported to the project's `DECISIONS.md`, adopted through
propose/adopt and superseded, never rewritten. Operational rulings (permission outcomes, planning choices, gap
resolutions, blocked-check classifications, owner answers) are append-only workflow audit records in SQLite. A ruling
that establishes a durable product choice links to a decision adopted through the decision path, never implicitly.

## D273 — Judge role and duty-specific contracts

Status: accepted design in P002-T001 (owner direction); implementation pending T009.

A judge joins reviewer and executor, with its own owner-selected provider, model and effort; provider diversity is
optional and there is no fallback. One configuration serves several duties — `permission`, `planning_choice`,
`spec_gap`, `blocked_check` — each with its own prompt, typed inputs and outputs, scoped tools, validation and failure
routes. Each request is a fresh, accounted invocation with read-only code access and only its duty's ruling command;
the service validates the outcome. The judge may abstain, never overrides integrity, acceptance or READY, never edits
its policy and cannot grant owner-only capabilities (secrets, global configuration, outside-root writes, policy or
prompt changes, destructive Git, push/publication/deployment, undelegated network installs, changes to objectives,
phases, requirement meaning or criteria). Malformed output, refusal and missing evidence escalate; provider, quota,
authentication and timeout failures stop without retry
([contracts §7](phase/P002-T001-contracts.md#7-roles-and-judge-duties)). Prompts and the evaluation corpus are G16.

## D274 — Permission dimensions, standing grants and revocation

Status: accepted design in P002-T001 (owner direction); implementation pending T010. Extends SPECIFICATION §5 rule 6.

The five dimensions stay separate. An autonomous authorization declares active, delegable and owner-only tiers; manual
mode has no delegable tier. Grants are per-operation, time-limited or **permanent** (no time expiry, revocable), bound
to project, role, dimension, exact targets, purpose, origin, parent authorization and policy version. Permanence never
widens scope. Effective authority is the compound of grants within current ceilings, checked at every mediated command
and admission, and combinations never yield an owner-only capability. A grant applies only at a new attempt through a
frozen permission snapshot. Revocation is immediate for new commands and admissions; an active native writer is
stopped through process control and its effects settled, without claiming that cooperative containment prevents every
in-flight action (D064). Equivalent requests without new evidence do not reach the judge again. Cascade on
authorization end, use in manual mode and target normalization are G10.

## D275 — Client-neutral tool discovery and invocation contract

Status: accepted design in P002-T001 (owner direction); characterization T002, implementation T005 and T008.

The harness owns a versioned logical catalogue and a small discovery surface (illustratively `search_tools`,
`describe_tool`, `invoke_tool`) over an existing suitable transport, so model contexts load only scoped definitions on
demand. Discovery is not a grant: unscoped tools are not disclosed, and every invocation binds the caller from the
transport session and revalidates schema digest, authority, expected revision and idempotency as the underlying
command. No SQL, arbitrary code or full-catalogue fallback; broker and logical tool identities are both traced.
Anthropic's native Tool Search or other native deferred loading may optimize the same semantics but is never required.
Client kind, inference provider and model are separate dimensions. Claude Code and Codex are the 0.2.0 clients;
OpenCode is future work with an extension point and a synthetic conformance fixture, not an adapter. A client that
lacks the minimum capability contract (G04) is blocked at admission.

## D276 — Autonomous roadmap runs, local bounds and stops

Status: accepted design in P002-T001 (owner direction; optional-cap semantics and stop classes as T001 resolutions);
implementation pending T016, with T014/T015.

A run starts from a readiness preview and an owner-confirmed authorization binding the accepted roadmap revision,
delegation policy, finite local bounds, optional caps and risk acknowledgement. There is no phase-count cap; adding
phases or changing objectives, criteria or requirement meaning is an owner amendment. Local bounds cover task attempts
across lineage, judge reconsiderations, replacement plans, remediation per cause and no-progress fingerprints; they
survive resume, phase change, split and rename. Optional caps (deadline, invocations, observed tokens, valuation on
one basis) are checked before each inference, stop on unknown usage when set and may be exceeded by an in-flight
call. Stops are `WAITING_FOR_OWNER`, `PAUSED`, `LIMIT_REACHED`, `FAILED`, `RECOVERY_REQUIRED`, `REVOKED` and
`COMPLETED`; resume is explicit and revalidates. Defaults (G11), readiness criteria (G12) and the acknowledgement text
(G17) are open ([flows FL01–FL03](phase/P002-T001-flows.md#fl02--autonomous-run-states)).

## D277 — Correlated traces, operations and knowledge-access receipts

Status: accepted design in P002-T001 (owner direction); implementation pending T006–T008, T018, T019.

Requests, workflow runs, recoverable operations, agent invocations/attempts, observed turns and tool calls are
correlated by stable IDs, parent and causation links, ordered events and source labels (supplied, reported, derived,
measured, absent). Project task, operation and invocation are distinct (naming G08); no second scheduler is created.
A harness attempt, a revision round and a provider-reported turn are different counters; unobserved turns are never
manufactured and missing coverage stays visible. Each knowledge delivery records invocation, channel, entity, stable
ID, revision, sections, exposure level, digest and truncation; it shows availability, not comprehension. Native file
reads are recorded only when observed. Command outcomes and their events commit together.

## D278 — Global inbox and task-instance graph

Status: accepted design in P002-T001 (owner direction); implementation pending T017 and T018.

One global inbox serves manual and autonomous modes. Items are derived and deduplicated from committed events, name
the project and optional phase, task, run, operation or request, and keep read and resolved states separate. Actions
call the ordinary guarded commands with fresh checks; an item never carries an approval; query-only archives stay
read-only; optional OS notifications carry no sensitive content. The graph is a read-only projection of persisted
phases and task instances with their actual reviewer, executor, judge and Harness involvement, including phase
opening, check and closure; it is neither a workflow editor nor the runtime topology. Polling remains the default.
Inbox taxonomy and shortcuts (G13) and the visual direction (G14) come from the owner.

## D279 — P002 threat model, coverage and design-record placement

Status: accepted in P002-T001; repository documentation practice for P002.

The [initial threat model](phase/P002-T001-threat-model.md) (TM01–TM20) assigns each threat a control and owning
tasks; each implementing task cites the threats it controls, and T021 audits the integrated result. The
[requirement coverage](phase/P002-T001-contracts.md#15-requirement-coverage) maps owner requirements and exit criteria
to implementing and qualifying tasks; the [gate register](phase/P002-T001-contracts.md#12-open-gate-register) gives
each open question one owning task. Accepted P002 design lives in `docs/phase/` and in SPECIFICATION §14/ARCHITECTURE
§13 labelled as not implemented; `docs/flows/`, DDBB-DIAGRAM, OpenAPI and client types change only with the
implementation, in the same task. These records follow the phase into its archive at closure.

## D280 — LangGraph 1.2.18 dependency set, placement and runtime hygiene

Status: accepted in P002-T002 (owner, 2026-10-29); the dependency is added in T003, not before.
Resolves G01 and bounds G02; evidence in the [T002 feasibility record](phase/P002-T002-feasibility.md#2-langgraph-feasibility-g01-g02-feasibility).

Adopt `langgraph==1.2.18` as a runtime dependency in T003, locked with exactly the 27 additions measured in T002
(`langgraph-checkpoint` 4.3.1, `langgraph-prebuilt` 1.1.1, `langgraph-sdk` 0.4.10, `langchain-core` 1.7.1,
`langchain-protocol` 0.0.20, `langsmith` 0.14.15 and their transitive set) and no change to existing pins; offline
installation through the existing `pylock.toml` route; `NOTICE-THIRD-PARTY.md` updated in the same task. Do not add
`langgraph-checkpoint-sqlite`; T003 implements continuation as a harness saver over Alembic-managed tables unless the
owner later decides otherwise. The standard-library-only core never imports LangGraph: one orchestration package,
owned by the supervisor runtime, is the only importer, enforced by an import-boundary test.

Runtime hygiene: the service neutralizes inherited `LANGSMITH_*`/`LANGCHAIN_*` tracing variables and runs graphs
inside a disabled LangSmith tracing context, with a blocked-network test; checkpoints use a strict serializer and
`durability="sync"`; graph state holds only identities and revision references. Because a resumed or replayed node
re-executes from its start and LangGraph silently ignores graph-version drift, every effect goes through a journaled
deterministic operation identity (INV-02, INV-05) and the harness checks a stamped graph version before resume.

## D281 — Per-invocation MCP broker transport and minimum client capability contract

Status: accepted in P002-T002 (owner, 2026-10-29); implementation in T008 (transport), T006 (observation records)
and T021 (audit). Resolves the T002 part of G04 and G05; evidence in the
[T002 feasibility record](phase/P002-T002-feasibility.md#3-tool-transport-per-client-g04).

The 0.2.0 transport is a harness-owned stdio MCP server exposing only the D275 broker tools, launched per invocation
with the caller bound in its launcher-set environment. Claude Code receives it through `--strict-mcp-config
--mcp-config` and `--allowedTools mcp__<server>__<tool>`; Codex through `-c mcp_servers.<server>.*` with
`enabled_tools` and `default_tools_approval_mode="approve"` scoped to that server only; neither reads or writes user or
global configuration. Claude's native ToolSearch stays an optional optimization behind the same semantics, not the
default. The bridge runs outside client confinement, so it carries no authority beyond the broker; it exits on stdin
EOF or parent loss, and the supervisor records and reaps it because Codex leaves it orphaned on cancellation.
Cancellation is classified from the supervisor's record, never from the exit status; an in-flight invocation is
uncertain and reconciled, never reissued.

Admission requires evidence of capabilities MC1–MC7 of the
[minimum contract](phase/P002-T002-feasibility.md#5-minimum-client-capability-contract-d281) per client,
version and role; a missing one blocks admission. Usage, reported model and cancellation telemetry are recorded where
the client provides them and stay unknown otherwise (Codex reports no model and no usage after cancellation).

## D282 — Harness checkpoint saver and continuation/journal consistency contract

Status: accepted in P002-T003 (owner, 2026-10-29); implemented in T003. Resolves G02 within D280 (option B);
evidence in the [T003 record](phase/P002-T003-runtime.md).

Continuations persist through `HarnessCheckpointSaver`, a synchronous LangGraph 4.3.1 saver over three
Alembic-managed tables of the harness database (`0029_graph_continuations`): `graph_threads` (stamp and status),
`graph_checkpoints` and `graph_checkpoint_writes`. It uses the strict serializer, accepts only primitive state with
string keys outside LangGraph's own special write channels, refuses a checkpoint for an unstamped thread and never
rewrites a stored checkpoint; pruning, copying and per-run deletion are not supported. Writes are serialized per saver
because LangGraph writes from its background executor.

Consistency: the domain journal is the authority and the checkpoint is routing progress only; no atomicity between
them is assumed. A node performs effects only through an `OperationPort` with a deterministic key (thread, step, node,
task path, name, references): the intent is sealed before the effect, a replay of a completed operation reconciles,
and a sealed intent without an outcome stops the thread `RECOVERY_REQUIRED` and is never reissued (INV-02, INV-05,
INV-06). Continuing a `RUNNING` thread after a crash requires explicit confirmation that the previous writer stopped.
T003 provides the port and a synthetic journal for tests; the production journal and reconciliation of uncertain
operations are T006/T020.

## D283 — Durable segments, graph-version stamping and quarantine

Status: accepted in P002-T003 (owner, 2026-10-29); implemented in T003. Resolves G03; evidence in the
[T003 record](phase/P002-T003-runtime.md).

A durable segment runs from a start, resume or recovery until the graph waits, ends or reaches its definition's
`segment_limit` (LangGraph `recursion_limit`, default 50); at the limit the runner opens a new segment from the last
synchronous checkpoint, so graph recursion never caps the length of a valid run; the roadmap bounds are T016's.
Each thread is stamped with `graph_id`, declared `graph_version` and a structural fingerprint (nodes, edges, branches
with declared ends, joins, state channels). Before any node of an existing thread runs, all three are compared with
the registered definition; a difference or an unknown graph sets `QUARANTINED` with both stamps and runs nothing.
Releasing a quarantine is a later explicit owner action (T016/T020); there is no automatic continuation migration.
Thread statuses: `RUNNING`, `WAITING`, `COMPLETED`, `CANCELLED`, `REVOKED`, `QUARANTINED`, `RECOVERY_REQUIRED`,
`FAILED`. Cancellation and revocation are recorded first; a waiting thread stops without running a node and an active
segment observes the stop at the next superstep boundary.

## D284 — Structured knowledge entities, revisions and immutability

Status: accepted in P002-T004 (owner, 2026-10-29); implemented in T004 (storage and core only; no product path uses
it yet). Resolves G06 within D270; evidence in the [T004 record](phase/P002-T004-knowledge.md).

Project knowledge has six item kinds — `requirement` (`RNNN`), `criterion` (`CNNN`), `phase` (`PNNN`), `task`
(`PNNN-TNNN`), `decision` (`DNNN`) and `section` — each with a stable identity, an immutable kind and a code never
reused in its scope. A criterion is one checkable condition with exactly one owner: a requirement, a phase or a task.
A section belongs to exactly one logical document of a closed list (`specification`, `architecture`, `data_model`,
`flows`, `instructions`), fixed at creation; its slug is unique within that document. Execution and lifecycle states
stay in the operational tables; rulings, grants, questions and operations are not knowledge. No product one-off
entity exists.

Item versions are immutable content (`knowledge-content-1`) with provenance `known`, `inferred` or `unknown` and an
optional source; no date or actor is invented. A revision is the complete copy-on-write manifest of members (item →
version) and typed links (`part_of`, `criterion_of`, `depends_on`, `addresses`, `supersedes`). The order of children
is a dense link position and the order of each document's root sections is an explicit per-revision member position.
Drafts are mutable; adoption is a compare-and-set against the current accepted head that assigns the next number on a
linear history and records origin (D272), actor, reason and a change summary listing requirements, criteria and
instructions sections as sensitive. There is no rebase (T012).

Hashes use the canonical JSON: `content_sha256` per version; `knowledge_sha256` over members (identity, kind,
document, code, version, content hash, root position) and links (kind, endpoints, position, qualifier);
`revision_sha256` over the knowledge hash, number, base revision hash and adoption record, chaining the history.
Retrieval recomputes the hashes, chain and rules back to the root and serves nothing that does not match.

Accepted state is immutable in the database: migration `0030_structured_knowledge` adds triggers that refuse updates
and deletes of projects, items, versions and identity mappings, insertion over an existing key (so REPLACE and upsert
cannot substitute), any change to members or links of a non-draft revision, any revision change other than one
`DRAFT` → `ACCEPTED`/`DISCARDED` transition, and an adoption whose number is not its base's plus one; partial unique
indexes keep one accepted successor per base. Schema checks, backup, bundle verification and restore refuse a
database whose trigger set differs from the expected digest.

Decision status is `accepted`, `rejected` or `retired`; `retired` is only the first version of an imported or migrated
record without an identifiable superseder. Supersession is a `supersedes` link qualified `full` (at most one) or
`partial`; the displayed state is derived and an accepted decision is never re-versioned, removed or un-superseded.
`proposed` exists only in drafts. Import (T013) and installed migration (T020) map historical status lines with the
tested mapping of the record: progress notes stay in `historical_status`, "superseded by" clauses become links when the
superseder is in the set, an ambiguous extent or an unrecognized status needs the owner's choice, and nothing defaults
to `accepted`.

## D285 — Canonical database instructions and generated instruction files

Status: accepted in P002-T004 (owner, 2026-10-29); representation and staging implemented in T004; context delivery
pending T007 and file generation pending T013. Resolves G07. D094 remains the implemented behavior until T007
replaces it.

Project instructions are sections of the `instructions` logical document, revisioned like other knowledge. `AGENTS.md`
becomes the canonical generated view of the `agents` sections; `CLAUDE.md` and `GEMINI.md` become derived wrappers: the
fixed import of `AGENTS.md` followed by the sections whose target is `claude` or `gemini`. Only instructions sections
may target a client, and a child keeps its parent's target. When and whether a wrapper is generated, the renderer and
the size budgets are T013's export manifest.

Existing rules are kept through a deterministic, model-free staging that splits the files by headings outside code
fences, keeps text verbatim with its root and child order, removes only the `@AGENTS.md` directive from wrappers and
reports irregular headings; it creates a draft only, and the rules become canonical through an explicit adoption of
the previewed result. The owner can also edit the canonical instructions in the UI through the corresponding
authorized adoption (T012), as for other knowledge. Exported files remain generated views, protected from agents and
changed only by regeneration or explicit import (D271). Changes to instructions are sensitive in the change summary
for T005's owner-only enforcement. T007 supersedes D094 when it delivers the accepted instructions in context; until
then the engine still injects the checkout's `AGENTS.md`.

## D286 — Typed domain operation service, capability policy and command outcome record

Status: accepted in P002-T005 (owner, 2026-10-29, with Q1 option (a)); implemented in T005 for the knowledge
operations. Evidence in the [T005 record](phase/P002-T005-domain-operations.md); binds T006–T016 to its interfaces.

UI/API, deterministic graph nodes and (from T008) the tool broker reach domain mutations only through one
`execute` pipeline over a versioned logical catalogue (`domain-catalogue-1`): entry and schema digest without
fallback, closed arguments, caller principal/role/frozen tool policy, then in one transaction query-only refusal,
caller re-verification, project membership, idempotency, per-operation capabilities, preconditions, the handler and
an insert-only outcome row in `domain_commands` (`0031_domain_commands`). Caller identity, project and origin are
bound by trusted infrastructure, never by arguments; foreign identifiers answer like missing ones. T005 catalogues
ten knowledge operations (head, list, get, projects, draft get/open/apply/discard, adoption preview, adopt).

Agents never adopt; the owner adopts the exact previewed draft (`owner_confirmed`), with a reason for sensitive
changes; delegated and deterministic adoption fail closed until T016. Every change is classified with a class
(`owner_only`, `product`, `planning`) and a separate sensitivity; owner-only changes (requirements, criteria other than
those created with a new task, phases and their addresses, instructions, supersession of accepted decisions) map to
a target no grant can satisfy. Agent capabilities need, per operation, an exact unrevoked grant of the frozen snapshot
within all four 0.1.9 `permission_authority` layers (frozen and current copies intersected) and the role ceiling,
read by `PermissionProvider` in the command's transaction; path rules, the client capability contract, the tool
policy and the 0.1.9 permission ledger keep their own evaluation. Agents see only their frozen revision. Idempotency
keys are scoped by project and principal; a repeat returns the stored outcome without executing again. Reads resolve
persisted knowledge projects and serve restored query-only copies. Product composition has no agent resolver,
permission provider, authorization provider or receipt sink: agent calls and delegated adoption are refused until
T006–T010/T016 provide them.

## D287 — Operation journal granularity and recovery contract

Status: accepted in P002-T006 (owner, 2026-10-29); implemented in T006. Resolves G08; proposal and evidence in the
[T006 record](phase/P002-T006-operations-tracing.md#3-g08-contract-accepted-as-d287).

Project task, workflow run, operation, invocation and attempt stay distinct. A new `workflow_operations` journal holds
one recoverable operation per `OperationPort` key inside a graph thread, with kind, parent/causation, origin and
bounded references, writer fencing and result/error links. The invocation is the existing `usage_invocations` ledger
row, the only source of charges; the attempt is its existing native source; `managed_jobs` stays the only scheduler.
0.1.9 runs keep their journals without synthetic operations or backfill. Statuses `INTENDED`, `COMPLETED`, `FAILED`,
`UNCERTAIN` and owner-only `ABANDONED`; domain-command operations are written `COMPLETED` in the command's
transaction and refusals create only an event. Agent invocations are sealed in the fenced attempt-start transaction
with the ledger intent and completed with the fenced attempt result. Recovery classifies by evidence; an expired
lease never completes an operation or proves a stopped writer; uncertain inference is never relaunched. Ordered,
deduplicated `trace_events` share each transition's transaction and rebuild the status projection.
Implementation: migration `0032_operation_journal` (75 tables), `storage/operation_journal.py`, `JournalPort`, the
T005 audit sink in outcome and refusal transactions, `agent_started(..., InvocationOperation)` and read-only trace
routes under `/api/managed/knowledge/projects/{k}/traces/{thread}`.
Review corrections (same task, before integration; contract unchanged): the generic port seals and completes only
`sealed_effect`; every port path checks the project root; results are kept verbatim within 16 KiB; `refs`/`origin`
are validated; offloaded event content is stored in a third table, `trace_artifacts` (76 tables); Codex turns are
counted from native terminals. Details in the [T006 record](phase/P002-T006-operations-tracing.md#9-review-findings-and-corrections).
