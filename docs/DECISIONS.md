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

Status: accepted; not implemented.

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

Status: accepted.

Protected deterministic form/TOML endpoints validate, preview, save, activate for restart, cancel and recover.
Client discovery uses explicit PATH; version/help probes do not invoke inference. Authority is selected and
verified before composing runtime clients; setup/invalid states reject managed work. Query-only restore disables
this operating lane before any original path or client is used.

## D223 — Guided UI with exact confirmations

Status: accepted.

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

Status: accepted.

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

The [phase handoff](phase/P001-metrics-records.md) and [reference notes](phase/P001-metrics-records-references.md)
are planning artifacts. Their task breakdown, candidate record fields and calculation policy require technical
decisions during P002-T001; they are not a new schema, API, billing configuration format or implemented feature.
No real calls, network installation, global configuration change, commit or publication is authorized by this plan.

## D233 — Metrics Records first in 0.1.2, Continuous Mode second in 0.2.0

Status: accepted (roadmap order and release targets; implementation pending).

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
