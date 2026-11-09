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

Status: accepted at the owner's explicit authorization of P002-T001 (2026-10-29); implementation pending T002–T029
(plan v0.4, D303).
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

Status: accepted design in P002-T001 (owner direction); T009's judge foundation is implemented and integrated
into develop (D290). Native judge qualification and later permission/adoption effects remain pending.

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

Status: accepted design in P002-T001 (owner direction); implemented and integrated after technical re-review in T010
(D291). Extends SPECIFICATION §5 rule 6.

The five dimensions stay separate. An autonomous authorization declares active, delegable and owner-only tiers; manual
mode has no delegable tier. Grants are per-operation, time-limited or **permanent** (no time expiry, revocable), bound
to project, role, dimension, exact targets, purpose, origin, parent authorization and policy version. Permanence never
widens scope. Effective authority is the compound of grants within current ceilings, checked at every mediated command
and admission, and combinations never yield an owner-only capability. A grant applies only at a new attempt through a
frozen permission snapshot. Revocation is immediate for new commands and admissions; an active native writer is
stopped through process control and its effects settled, without claiming that cooperative containment prevents every
in-flight action (D064). Equivalent requests without new evidence do not reach the judge again. Cascade on
authorization end, use in manual mode and target normalization are G10.
G10 was subsequently resolved by the owner in D291; local source/verification and successful technical re-review
are recorded under T010, integrated as `d52fbb5` by the accompanying merge; release/publication/installation remain pending.

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

Status: accepted design in P002-T001 (owner direction); implementation pending T006–T008, T018–T025 (plan v0.4,
D303).

Requests, workflow runs, recoverable operations, agent invocations/attempts, observed turns and tool calls are
correlated by stable IDs, parent and causation links, ordered events and source labels (supplied, reported, derived,
measured, absent). Project task, operation and invocation are distinct (naming G08); no second scheduler is created.
A harness attempt, a revision round and a provider-reported turn are different counters; unobserved turns are never
manufactured and missing coverage stays visible. Each knowledge delivery records invocation, channel, entity, stable
ID, revision, sections, exposure level, digest and truncation; it shows availability, not comprehension. Native file
reads are recorded only when observed. Command outcomes and their events commit together.

## D278 — Global inbox and task-instance graph

Status: accepted design in P002-T001 (owner direction). T017 implements the inbox under D302 (integrated). T018–T024 own the pending map
(plan v0.4, D303).

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

## D288 — Frozen invocation context and exact exposure evidence

Status: implemented in P002-T007 under the owner's authorization to resolve technical details;
technical review passed and source is integrated into develop. Applies D270/D277/D285 and FL08 without another owner-policy gate.

The explicit canonical path uses a verified accepted revision and mandatory active instruction sections, ordered
by root/child position: `agents` first, then the selected client's target. Other relevant knowledge is selected by
stable identity; profile and Git/code captures remain separately attributed, noncanonical evidence. Rendering/start
check the captured profile against the actual frozen project context; launch also checks the instruction client target. Missing or
oversize mandatory context fails; generated files never fill it. This path supersedes D094's checkout read. Existing
projects/graphs and frozen catalogs/snapshots retain D094 until their explicit migration in T011–T016/T020.

Migration `0033_frozen_context` adds three insert-only tables: prepared source bytes (`context_snapshots`), the
boundary sealed with the fenced attempt/ledger/operation (`invocation_contexts`), and exact observed/returned
exposures (`knowledge_deliveries`). Preparation and intention assert no delivery. Initial receipts appear only
after the adapter observes the complete input write; known refusal before launch records failure without a delivery
digest. A crash or uncertain partial write stays unknown, with no automatic inference retry.

Shared-domain `knowledge.lookup`/`knowledge.search` add bounded exposure and revision-bound pagination without
changing historical catalogue entries or owner HTTP schemas. Queries and tools commit their response and receipts
before returning content. Stable request keys deduplicate within invocation and channel; replay rechecks caller
and current capabilities and returns the stored response, including a recorded read failure. Changed requests
conflict; a retry with a new key is a new delivery. No checkpoint or external transport transaction is claimed.

Additive `knowledge-delivery-2` envelopes carry locators and exact UTF-8 exposure digests independently of source
content hashes. Reconstruction bytes stay in scoped storage, never in trace payloads. Receipts mean availability,
not comprehension. Native file reads without observation remain unknown. Persisted project-scoped readers and
backup verification work without a checkout, including on a restored query-only database. No backfill, automatic
project conversion, new dependency, broker/resolver, grants, export or UI is introduced.

Limits, range units, failure/reentry semantics and synthetic evidence: [T007 record](phase/P002-T007-frozen-context.md)
and [context flow](flows/frozen-context.md). Checked source → develop → 0.2.0 through protected main →
distribution/publication → installation remains the delivery route. After successful technical re-review, the
owner authorized commit, merge into `develop` and push of `develop`; release/publication/installation remain pending.

T007 review corrections (same task): new `frozen-context-2` preparations deliver full instruction
headings at accepted tree depth plus verbatim bodies; receipts hash those actual rendered sections. Body-only v1
snapshots remain readable/backup-compatible without rewriting bytes, but cannot start a new canonical invocation.
An explicit before-spawn or before-GO refusal boundary supplies positive no-delivery evidence; stopping a process
or observing a partial write supplies none. Backup has no artifact references for a consistent before-spawn
refusal and retains the real prepared prompt for a before-GO refusal, while ordinary launched-process artifact
checks remain strict. Evidence: [T007 review corrections](phase/P002-T007-frozen-context.md#8-technical-review-corrections).

## D289 — Invocation-scoped broker binding, transactional exposure and independent relay control

Status: implemented in P002-T008 and integrated into develop at the owner's explicit authorization; the three
technical-review findings are corrected, without asserting a separate technical re-review. Completes the T008 implementation part of G04 within D275/D281;
does not extend the historical native qualification matrix. [Evidence](phase/P002-T008-scoped-tools.md).

Trusted assembly freezes `scoped-tools-1` exact catalogue refs, broker surface digest and client/version/role/evidence selection in the
existing native attempt request, alongside the canonical context marker. The caller resolver reconstructs and
reverifies invocation, attempt, operation, project, revision, role, policy, owner token, lease and checkout lock on
every command/replay. Model arguments never choose authority. No new table, migration or HTTP route is needed.

The per-invocation stdio MCP executable is a relay over a private invocation Unix socket to the supervisor's broker.
It runs with the supervisor interpreter's isolated `-I -m` launch: checkout, inherited Python import variables and
user-site paths cannot supply the module. The installed harness environment remains trusted, without OS isolation.
It receives no database connection; calls use the shared `DomainOperations.execute` and its transactions. Search
returns bounded scoped descriptors, description returns exact schemas on demand; no unscoped catalogue fallback.
Claude strict configuration and exact allowlist, Codex a single harness server with enabled_tools and server-local
approval, and the independent guard retain all historical file/network/session/memory/result restrictions.
Admission requires MC1–MC7 for an exact client/version/role/evidence cell; simulated evidence stays labelled.

Existing trace envelopes and tool-result storage persist descriptor/schema bytes and knowledge responses before
returning. Logical and broker calls/results are separate correlated events under the native invocation; commands
retain their own ID. Replayed commands recheck current capability targets, not only caller identity. Command effects
and outcomes commit first; their stable response receipt commits before transport return, with safe reentry between
those boundaries. No atomic transport acknowledgement or proof of comprehension is claimed.

The bridge registers PID/parent/process group, then confirms initialization protocol and exact surface digest in
a persisted readiness round trip; existing process specs and trace retain both boundaries and observed stop state.
A scoped invocation cannot complete without that availability evidence, even if the CLI returns a valid answer;
missing/failed startup is a persisted failure after an observed CLI launch, not proof of no inference. No logical
tool call is required. Cleanup of cancellation/prelaunch refusals does not assert readiness. EOF, parent loss or
supervisor disconnect terminates the relay even during a call, independently of CLI exit
status/group. Recovery refuses potentially live recorded bridge identities and never signals persisted PIDs.
Expected peer disconnects are classified only at socket I/O boundaries; service/persistence failures still surface
during cancellation. A settled transaction with a lost response proves no client delivery. An interrupted
deterministic transaction reconciles its domain outcome; uncertain inference is never reissued.
The production permission provider remains absent/denying (T010); positive/revocation checks are synthetic.
No judge/grant lifecycle, product graph, automatic migration, new dependency or OpenCode adapter is introduced.


## D290 — Judge duty contracts, G16 and optional profile formats

Status: G16's four prompts and synthetic E01–E21 minimum accepted explicitly by the owner on 2026-10-30;
implementation details authorized within T009's local scope; source commit `350073c` is integrated into develop
after successful technical re-review. The owner authorized the source commit, merge into `develop` and push of `develop`.
Source verification/delivery evidence:
[T009 record](phase/P002-T009-judge.md). No native qualification, productive delegation or later-task authority added.

`local-config-11` and `project-config-3` explicitly opt into an optional `agents.judge` provider/model/effort and
read-only CLI declaration. They retain the existing reviewer/executor billing metadata. No load-time conversion;
formats 1–10 and project formats 1–2 keep their rules/hashes. Project-owned copies select independently, the global
copy supplies new intake defaults, and no other role is used as fallback. Saving/compatibility checks are distinct
from exact judge-role qualification: the native matrix still contains reviewer cells only.

The accepted common preamble plus the four duty texts are packaged as version-1 prompts. New requests freeze
selection, template digest/version, accepted context revision, exact scoped catalogue refs and delegation evidence.
New lookup/search v2 entries add judge without changing the v1 schemas/digests. Each duty exposes only those two
queries and its own candidate submission command; an owner-only command may link an actual decision afterwards.
The service validates supplied/admissible choices, evidence identities, canonical requirement/criterion references,
intent bindings, typed proposals, exact permission targets, duration ceilings and compound-authority classification.
Free-text proposals still need the separate guarded adoption path; semantic truth is not proved by a schema.

Migration `0034_judge_contracts` adds immutable requests, invocation bindings, terminal rulings and explicit decision
links (83 tables). Fenced native start seals the binding with the existing attempt/context/operation/usage intent;
fenced settlement records the candidate/failure with existing accounting captures. No scheduler or second ledger.
Tool submissions are candidates until the native result settles and must agree with it. Invalid/malformed output,
refusal, abstention and missing evidence preserve native evidence and return an owner continuation. Operational
errors stop without retry. Equivalent subjects/evidence (including the canonical context digest) reuse the prior request; new evidence needs an explicit
reconsideration and a caller-supplied delegation bound, with no production default. Pending/uncertain inference
blocks another attempt; abstentions also consume the saved bound. Recovery observes the shared operation journal
and never launches it again. Exact qualification is rechecked in the native start transaction before its accounting
intent can commit. The job's frozen language pair is supplied at assembly and checked again at start.

`DomainOperations.authorizations` may supply the future `judge_policy` contract; the product provider has no such
policy and refuses inference. Synthetic tests supply labelled delegation/permission fixtures and exact simulated
judge cells. T010 owns normalized productive capability classification, effective grants and revocation; T014–T016
own workflow consumers, delegated adoption and autonomy bounds; T017 owns global owner inbox delivery. T009 returns
continuations for them and does not implement their effects. Following successful technical re-review, the owner
authorized the source commit, merge into `develop` and push of `develop`. Release, publication, installation,
service start and real agent/provider execution remain unauthorized.

## D291 — Permission ancestry, manual standing grants and exact targets

Status: accepted explicitly by the owner on 2026-10-30 for P002-T010; G10 resolved as design.
Local implementation/verification and successful independent technical re-review are recorded in the
[T010 record](phase/P002-T010-permissions.md). Source `d52fbb5` is integrated by the accompanying merge;
the owner authorized commit, merge and push of `develop`. Release/publication/installation remain pending.

The owner accepted §3 recommendations A/B/C, not their alternatives. All dependent authorizations and grants cease
to be effective when their parent ends or is revoked, recursively, including permanent grants. Independent
owner-confirmed permission authorizations retain their own validity. Histories and completed effects are preserved.
Manual mode supports explicit visible revocable permanent grants reused only at new frozen boundaries; grants
never replace action/content confirmations or introduce delegation. Targets are versioned, typed and exact across
files/tools/network/product/acceptance, with the representation/rejection rules and examples in the accepted record.
Service-derived equivalence survives rewording/broadening; those changes alone are not new evidence. Current
authority, ancestry, expiry and revocation are checked transactionally at commands and admission. Native side
effects remain cooperatively contained and uncertain effects require existing stop/reconciliation. No later-task
autonomy bounds, native judge qualification, network installation or operational delivery is authorized.

## D292 — Structured intake evidence and independent profile confirmation

Status: accepted implementation detail under the owner's P002-T011 authorization; source is complete and technical
re-review passed on 2026-10-31; source `616846d` is integrated into develop by the accompanying authorized merge. No new owner-policy gate is introduced. [Evidence](phase/P002-T011-db-intake.md).

Structured intake stages D284 knowledge through the shared domain service and adopts it only on an exact owner
preview. Before first adoption the accepted revision is explicitly absent. Historical documentary conversations
and their frozen records retain their lane. Structured profile proposals use `project-profile-proposal-2` with
exact proposed-knowledge and source bindings; `project-profile-proposal-1` remains unchanged for documentary
conversations. Full profile validation still determines whether a turn succeeds. Profile review/confirmation
binds the actual staged or separately accepted revision/hash/status, conversation version, question deferrals,
source ledger and candidate. Owner confirmation preserves that preview and its `owner_confirmed` origin.

An answered owner message remains evidence only in its own conversation, verified through its frozen request and
context hashes. Stable owner-turn locators, brief and inventory references survive subsequent turns without
invented sources. Deterministic instruction staging rereads frozen local HEAD, verifies any preserved original
members against exact identity/content/provenance and prior staging, and merges members/ordered links once.
A prefix alone establishes no identity or trust. Failed staging rolls back without replacing prior evidence.

Knowledge adoption, profile confirmation, private configuration, preparation, activation and readiness are distinct.
Export/commit is an explicit pending T013 continuation; profile confirmation does not depend on a fictional export.
T016 owns final readiness and T020 owns installed conversion. No dependency, new table, permission expansion,
automatic conversion, new inference launcher or rewrite of historical records is introduced.


T011 completion clarification (same owner-authorized scope): a profileless intake may keep a valid
`profile: null` response as a draft, but cannot adopt knowledge until a current valid profile proposal is
available. Adoption reuses the exact profile preview checks under its transaction and refuses with an
English/Spanish continuation diagnostic. This prevents closing the only conversation before a profile can
be obtained. It does not confirm the profile, and selected-profile intake is exempt. Separate profile
confirmation before or after knowledge adoption, idempotency and the post-adoption context guard remain intact.
## D293 — Owner knowledge consultation and exact adoption presentation

Status: implemented under the owner's P002-T012 authorization; independent technical re-review passed; source
`6643ada` is integrated into develop by the accompanying authorized merge. Push of develop is authorized. [Evidence](phase/P002-T012-knowledge-editing.md). No new policy authorization or design gate.

The knowledge UI has a persisted consultation lane at `/knowledge`, separate from checkout documentation and from
project action workspaces. Registered projects expose `/projects/{id}/knowledge` for shared-command drafting and
owner adoption. Restored and unconfigured consultation mounts neither project workspace nor mutation controls.
Owner-only history/inspection queries are additive catalogue entries; agent surfaces and historical digests remain
unchanged. Search exposes the existing revision-bound shared query.

Adoption presentation derives before/after members and added/removed typed links from the verified base and exact
draft in the preview transaction. It preserves historical content/revision/preview hash formats. Root/child order,
content, provenance and supersession are visible without requiring JSON. The sealed draft, not unsaved input, is
adopted. Editing invalidates the visible preview; stale head/draft/preview is refused without automatic rebase.
Pending envelopes retain their exact body/key across response loss and reload; recovery explicitly resends them.

Frozen context associations come only from persisted snapshot → invocation → attempt → run relations, bounded to
100 with explicit truncation. Advancing knowledge changes neither old contexts nor evidence. No revision-bound
READY association is provided by the current operational model; the view explicitly reports that absence and never
labels legacy READY as validation of a new revision. Product decisions and separately queried operational rulings
remain distinct. No table, migration, dependency, automatic conversion, drift watcher or delegated adoption is added.

## D294 — Versioned knowledge documents, explicit ownership and project transfer

Status: accepted by the owner on 2026-10-31 for P002-T013; resolves G09. Source `2c54fa9` is completed and integrated into develop by the accompanying authorized merge after successful independent technical re-review, including all four corrections. Push of develop is authorized. Release/publication/installation remain pending and unauthorized. [Accepted package A, §§3–6](phase/P002-T013-document-roundtrip.md).

`harness-documents-1` uses Markdown text fields and a JSON companion, rendered by
`harness-knowledge-markdown-1` from verified accepted knowledge. `harness-ownership-1` names exact whole-file
targets and optional D285 wrappers, acquired only by explicit owner adoption. AGENTS/wrapper budgets remain
60/15 lines; excess blocks export without dropping rules. D271 replacement policy remains unchanged.

Explicit UI import seals selected inputs, identity choices, loss resolutions and canonical preview before
owner-confirmed adoption. Updates resolve scoped identities without similarity; omissions retain knowledge.
`harness-project-1` transfers project knowledge with fresh local identities and explicit reference/version mapping,
not historical execution or authority. Losses are located and resolved explicitly; raw input is preserved.
Export intents and per-target outcomes support deterministic recovery without repeating inference.
T014/T015 consume the boundaries; T016 readiness/delegation and T020 installed conversion remain separate.

## D295 — Brief descriptive commit messages with implementation bullets

Status: accepted at the owner's explicit request on 2026-10-31; repository development guidance.

Commit messages are in English, with a brief descriptive subject following the recent `<kind>: <summary>`
pattern and a task ID when relevant. After a blank line, a short bullet list summarizes the implemented changes.
Merge commits retain their `Merge ... into ...` subjects and include the same brief bullet body. Messages describe
completed changes concisely. The canonical instructions are in [AGENTS.md](../AGENTS.md#commit-messages), already
imported by CLAUDE.md and GEMINI.md; existing commit messages are unchanged.

The owner authorized this documentation maintenance directly on develop, with commit and push. This is a
session-specific exception to creating a topic branch; D235/D261 remain the ordinary branch rules.
Branch cleanup and verification are recorded in [maintenance evidence](phase/2026-10-31-repository-maintenance.md).

## D296 — Owner-adopted task replacement lineage and shared correction budget

Status: accepted explicitly by the owner on 2026-11-03 during P002-T014 implementation.

The directed knowledge link `replaces` connects a replacement task to a predecessor task. The owner adopts
the link through the existing knowledge adoption path. Links form an acyclic graph and adopted links cannot
be removed. Existing accepted revisions and catalogue fingerprints remain unchanged. A new
`knowledge.draft.apply@2` schema permits proposals containing the new link while @1 retains its exact schema.

All tasks connected by adopted replacement links, including ancestors, descendants and branches, share
the smallest recorded local correction ceiling and the persisted executor intents of the whole family.
The initial execution plus that correction ceiling is the total allowed executor count. Failed, denied
and uncertain executor attempts consume that count. New runs, policy increases, restart and changes of
task identity cannot replenish it. Unrelated tasks retain independent budgets. The managed journal records
the bound family and consumption, and the supervisor and fenced attempt transaction enforce the budget.
This supplies T014's task boundary. Phase remediation admission and roadmap limits remain T015/T016 work.

Implementation and synthetic evidence are recorded in
[P002-T014](phase/P002-T014-task-execution.md).

## D297 — Work map visual direction and agent conversation entry points

Status: accepted explicitly by the owner on 2026-11-03 as the G14 visual direction (T018) and the G13 conversation
kinds (T017). T017 implements the inbox under D302. Plan v0.4 assigns the remaining visual work to
T018–T024 after T017 ([D303](#d303--t018-split-by-responsibility-and-later-p002-tasks-renumbered)). T018 completes G14 and binds T019–T024 through D304–D309 (accepted 2026-11-04).

The task-instance graph of D278 becomes a hand-drawn, zoomable work map and the home page, with the existing list
pages one toggle away as the accessible alternative. Clicking a node or zooming past a threshold enters it: projects →
phases → tasks (`depends_on` edges, `replaces` lineage) → steps of the latest run, with a selector for earlier runs →
the trace of one invocation. Every level is an existing or new URL. Circles R, E, J (only with a judge profile) and H
(Harness deterministic stages) sit on the element where work happens; the active one shows rays. Clicking or zooming
into a circle opens that invocation's trace. Status uses colour plus icon and text; polling remains the default.

The trace graph needs an additive observed-step projection of ordered native turns and tool calls, derived from the
sealed stream at settlement so that it survives stream retention; T018 defines it without reopening T006. The style
is generated at runtime with rough.js and a bundled hand-drawn font in SVG with theme tokens and stable seeds; their
exact versions, licences and packaging are a dependency decision at T018 before adding. A documentation drawer
shows the project documents read-only beside the map.

Unresolved owner requests attributed to an agent show a speech bubble that opens T017's conversation panel at any
level: permission request, blocking question, judge escalation and lifecycle confirmation; notifications have no
bubble. Only the reviewer offers free conversation (the project chat), from a separate talk button; opened from a
phase, task, run or step, it includes that element's context by default behind a removable tag, recorded as a
knowledge delivery. Every action is an ordinary guarded command with fresh checks; a bubble never carries approval.
Details and sketches: [visual direction](phase/P002-T018-visual-direction.md).

## D298 — Structured manual phase plans and sealed lifecycle exports

Status: accepted implementation refinement within the owner-authorized P002-T015 contract (2026-11-03);
local source and technical review status are tracked in the [T015 record](phase/P002-T015-phase-lifecycle.md).

An operational phase starts from a phase identity in accepted SQLite knowledge, pending planning. A confirmed
plan binds the complete accepted revision, phase/task/criterion identities and versions, dependencies and explicit
criterion-to-task coverage. Reviewer proposals are durable read-only results; staging validates a separate draft,
and adoption requires an independent exact owner preview/hash, CAS and idempotency key. Plan edits cannot alter
product meaning or erase identities. Owner changes to objectives/criteria use general knowledge adoption first;
subsequent phase-plan confirmation invalidates READY and batches. Replacement tasks retain D296 lineage/budgets.

READY additionally binds the accepted revision and documentary ownership manifest. A committed acceptance of an
older task version or task dependency/criterion contract is insufficient. Checks classify pending work,
reconciliation, unresolved questions and operational failure, attributing deterministic controls to Harness and
reporting actual reviewer participation/configuration. T009 planning-choice candidates are produced only after
plan validation; only explicitly classified planning ambiguity can supply a blocked-check candidate. Neither
candidate nor ruling authorizes adoption or replaces READY. Autonomous authorization policies remain T016 work;
T015 admits owner-confirmed effects and refuses absent or fabricated delegated authority.

Closure freezes the accepted domain, evidence, ownership, archive paths and generated files in the existing phase
operation and D294 exchange records. The existing writer reconciles one commit and an unmoved tag on the evaluated
HEAD. Committed artifacts are archived byte-for-byte, including nested binaries. Succession uses only the sealed
accepted roadmap; the result transaction creates one ACTIVE unplanned successor or explicitly leaves none.
Recovery needs confirmed stopped writers and a fresh explicit confirmation of the same operation; expiry alone
never releases a writer or retries inference. Origin, scope, fingerprint, validity and current knowledge are
rechecked under the database writer through Git reference effects.

The canonical D294 renderer and historical generations remain unchanged. `harness:phase-view-1` decoration adds
operational phase/plan/archive status beside canonical generated fields. Explicit import retains the raw input,
reports this decoration as `operational_view_not_imported`, and never adopts its execution/approval claims.
Owned targets are replaced from sealed inputs and committed prior bytes, with per-target recovery receipts;
there is no comparison of Markdown with SQLite and no automatic import. No schema or dependency change.

## D299 — Autonomous run authority, children and persistent bounds

Status: implementation refinement within the owner-authorized P002-T016 contract (2026-11-03). The owner accepted
revocation from `RECOVERY_REQUIRED` and root-scoped consumption with the gate decisions of
[D300](#d300--g11-g12-and-g17-accepted-with-conditions); the remaining representation awaits technical review.

Migration `0038_autonomous_runs` (93 tables) holds the authority of D276 runs: insert-only owner-confirmed
authorization revisions per lineage (exact preview, idempotency key and request digest, gate-policy stamp, T010
parent record), one run row per lineage with a partial unique index for one non-terminal run per root, insert-only
`owner_delegated` children per effect (operation key, subject digest, rule, optional ruling and permission record),
insert-only bound consumption keyed by root and stable identity, versioned owner questions bound to the
authorization and accepted revision, insert-only deduplicated events with references for T017, and insert-only
sealed reviews (`autonomous_reviews`: one G12 reviewer report per frozen revision and classifier version, owner
answers bound to that revision, and validated delegated task contracts, D301).

The T010 parent of a run is an owner-confirmed authorization with no targets that names the authorized phases and
delegable tiers. A task child is sealed only when its adopted contract exists, with the exact normalized write
paths of that contract, purpose `task:{phase}:{task}` and the parent; T014's existing delegated-scope check accepts
it unchanged. Ending the parent ends every child (D291), and the existing cancellation poll stops a delegated writer
whose authority is no longer active. Revocation is available from every non-terminal state, including
`RECOVERY_REQUIRED`; it ends authority, while uncertain effects still need stopped-writer evidence. Bound
consumption is never deleted and is scoped to the root, so no resume, revision, phase change, rename or split
refills it; a revision may raise bounds, never lower them. Scope is the digest of phases, criteria and
requirements; any other change than delegated task planning stops for a new authorization revision.

The roadmap graph `autonomous-roadmap@1` keeps only the run identity and a cycle in its state. One loop node
decides deterministically from SQLite observations and performs one effect through `run_operation`; a hold node
interrupts for owner stops and harness waits. Gate-owned values arrive through an explicit `GatePolicy`; the product
policy has none, so readiness never returns READY and confirmation is refused before anything is sealed.

## D300 — G11, G12 and G17 accepted with conditions

Status: accepted by the owner on 2026-11-03 for P002-T016, resolving G11, G12 and G17 of D276 with the conditions
below; the conditions are implemented in the [T016 record](phase/P002-T016-autonomous-roadmap.md#3-joint-gate-proposal-g11-g12-g17).

- **G11.** Defaults `task_attempts` 3, `judge_reconsiderations` 1, `replacement_plans` 2, `remediation_per_cause` 2 and
  `no_progress` 3 only prefill the preview and are confirmed by hash. Consumption persists for the same identity or
  cause across runs of the same project. The progress fingerprint (`g11-1`) uses canonical, deduplicated D296
  families, so a split without real progress does not change it; judge reconsiderations are counted per canonical
  stable subject (duty, phase identity and cause), never per operation.
- **G12.** The twelve structural predicates and the three gap classes (`blocking`, `owner_answer_required`,
  `advisory`) are accepted (`g12-1`). The reviewer is invoked only after every structural check passes. Its report is
  validated against the frozen revision the service holds: citations must name items that exist in it. Answers come
  only from current owner records bound to that revision, never from the report. The report is sealed once per frozen
  revision; confirmation reuses the sealed report of the preview, revalidates its bindings and never generates another.
- **G17.** Version `autonomy-ack-1` with the accepted English and Spanish texts; the sealed authorization binds the
  version and the digest of both texts, and a change of text disables it until a new version is accepted.
- Revocation from `RECOVERY_REQUIRED` is accepted: it ends authority at once, while recovering uncertain effects
  still requires evidence that the writer stopped.

## D301 — Delegated task contracts and effect-boundary verification

Status: implementation refinement within the owner-authorized P002-T016 route (2026-11-03); integrated after independent final
re-review. Evidence in the [T016 record](phase/P002-T016-autonomous-roadmap.md#6-integral-production-route).

Accepted D284 task content carries no write-path contract, while D291/D299 require exact write targets for a
delegated task child and T014 derives a delegated contract only from a deterministic plan text. Delegated task
planning (contracts §10) therefore proposes the contract through the versioned `roadmap-task-plan` reviewer prompt
in an ordinary accounted job. The objective is the accepted task content; the harness validates exact canonical
repository files (no directory, glob, alias, `.`/`..`, protected or harness-owned pattern), every accepted
criterion as its own exact item with no rewording, single-line text that cannot add fields, and validation commands
within the profile prefixes. It renders the plan section, compares T014's parsed contract field by field and seals
its digest in `autonomous_reviews`; admission re-parses and refuses on any difference. Only then is the task child
sealed with those exact paths; a refused contract stops for the owner. The G12 report uses `roadmap-readiness` the
same way.

Delegated plan adoption and closure reuse T015's operations with an explicit `delegated` argument. An adoption child
is sealed after preparation (staging and exact preview) and binds the proposal, draft, coverage, preview, accepted
revision and phase version, which the adoption transaction compares. Every delegated inference is admitted inside
the transaction that seals its attempt and ledger intent: current child authority, active T010 parent, a RUNNING
run and the caps from the existing ledger; a refusal persists its reason and launches nothing. Task contracts are
identified by the accepted task, criteria and relations, and are reused, admitted and committed only under that
identity; a failed contract job is a durable stop. Only runs admitted by this run's task
children for the current phase and task version are committed; failed delegated runs are durable stops readmitted
only after an explicit owner resume. Completion uses the READY check sealed by each closure and requires coverage of
every active requirement of the accepted revision. The sealed child is verified inside the effect's own writer
transaction (and, for closure, again under the writer fence of every Git
reference effect): its kind and untampered subject, a live run of the root under the latest authorization revision
with an active T010 parent, the phase inside the sealed scope and, for closure, the exact READY binding. Delegated
knowledge adoption is `owner_delegated` with the child as actor; activation and abandonment are never delegated.
A plan, a reviewer output or a ruling alone never passes. Commit of reviewed accepted content is
harness-deterministic under its child, and T014's reference guard rechecks the delegated authority. Judge requests
use the parent's T009 delegation contract through a `roadmap:` subject; a validated ruling is linked to the
resulting step's child. The supervisor continues runs whose graph waits on settled harness jobs; owner stops are
never continued automatically.

Third review (2026-11-04): the authoritative check of a delegated task admission, review continuation and commit
runs inside T014's own queue transaction (an optional `delegated` check after the idempotent replay), comparing the
sealed child, live authority, the digest of the contract T014 freezes and the contract identity read from accepted
knowledge in that transaction; checks made by the caller beforehand are only early refusals. A pause that held the
reviewer after the executor is identified by persisted evidence (state admission refusal of the reviewer, settled
attempts, the executor's evidence in the last review cycle). The explicit owner resume accepts exactly that
evidence instead of a clean checkout and continues the same T014 run once by revalidation, with no new child or
task-attempt consumption; any other change, stale evidence or writer doubt still refuses. The continuation job
persists that evidence, and the revalidation's first effective capture must equal it before validation or review;
otherwise the run stops durably with the files left for the owner (final review).

## D302 — G13 inbox notifications and guarded shortcuts

Status: accepted explicitly by the owner on 2026-11-04 for P002-T017, completing the G13 input that D297 began.

| Item | Confirmed source | Owner interaction |
|---|---|---|
| Task completed | Task execution's `commit_recorded` with a `COMMITTED` acceptance | Notification without a bubble. Open the execution evidence. |
| Phase closed | `phase_closed` with the phase in `CLOSED` | Notification without a bubble. Open the closure evidence. |
| Permission and blocking question | Current persisted request | Reuse the ordinary guarded response. Autonomous answer and resume are separate. |
| Lifecycle confirmation | Phase check entering `READY_TO_CLOSE` or autonomous stop in `LIMIT_REACHED`, `RECOVERY_REQUIRED` or `FAILED` | Show evidence and current state. Open the matching control with its existing confirmation. |
| Judge escalation | `judge.ruled`, `ESCALATED`, continuation `owner` | Open the request and ruling read-only. |

A later `judge.decision.link` records a reference to an already accepted decision and has no authority over the
blocker. The owner deferred direct judge responses until an authoritative command is agreed. This deferral is
outside T017's completion scope. D278 and D297 retain the observation, archive and T018 boundaries.

T017 uses the source ledgers as a read-through projection with stable source identities and keyset pages. Only
first-read timestamps are persisted by the inbox. The existing command boundary determines resolution and
the same projection can be read in a restored archive. The [flow](flows/global-inbox.md) names each source and
guarded route, and the [record](phase/P002-T017-global-inbox.md) tracks local verification and delivery.

## D303 — T018 split by responsibility and later P002 tasks renumbered

Status: accepted explicitly by the owner on 2026-11-04 as P002 plan revision v0.4, before T018 started. Planning only:
no source, schema, API or dependency change.

The former T018 (task graph and correlated trace views) becomes seven bounded tasks. Each one has its own focused
synthetic tests, task record and independent technical review with re-review of the corrections. The frontend tasks
(T021–T024) also end with an owner visual review in the browser over `scripts/dev` and a synthetic project.

| Task | Responsibility | Scope |
|---|---|---|
| T018 | Design | Work-map contract and rendering decision (owner-accepted; documentation only) |
| T019 | Backend | Observed-step projection from sealed native streams |
| T020 | Backend | Work-map and trace read projections and API |
| T021 | Frontend | Hand-drawn rendering foundation: rough.js and font installation, SVG map engine |
| T022 | Frontend | Map levels L0–L3 as the home page |
| T023 | Frontend | Agent trace graph (L4) and documentation drawer |
| T024 | Full stack | Contextual reviewer conversation |

The former T019–T023 keep their content and are renumbered:

| Former | New | Task |
|---|---|---|
| T019 | T025 | Accounting and efficiency analysis |
| T020 | T026 | Installed-state migration and integrated recovery |
| T021 | T027 | Integrated security and provider audit |
| T022 | T028 | Complete journeys and usability qualification |
| T023 | T029 | Release qualification and delivery disposition |

This is the single exception to the stable-ID rule of NEXT_STEPS and to the v0.3 statement of the T001 contracts
(§14) that no task ID is renumbered. Records written before this decision keep their text and their former
numbering, read through the table above. These records are the bodies of D268–D302, the T001 contracts, flows and
threat model, the design basis and discussion, the T002–T017 records, the T018 visual direction and source
comments. In those records every former T019–T023 means T025–T029: for example, G15's owners (T021, T022) are T027
and T028, and TM19's owner T023 is T029. The former T018's ownership (G14, D277, D278, D297, TM14) is distributed across T018–T024 as NEXT_STEPS
records. Living documents (STATE, NEXT_STEPS, ROADMAP, `docs/flows/` and decision status lines) use the new numbers.

G14's remaining owner input (cards, information, navigation) belongs to T018. D297's dependency is decided in T018
and installed in T021 with separate explicit network authorization. Dependencies follow the split: T025 adds T023,
T026 adds T019 and T024, and T027 adds T019, T020 and T024. No acceptance, requirement, gate, threat or pending
delivery is dropped, and T018 still follows T017.

## D304 — Work-map levels, cards, navigation and status classes

Status: accepted explicitly by the owner on 2026-11-04 in P002-T018 (answers Q5–Q15 and Q20); completes G14's remaining input
(cards, information, navigation) on D297's visual direction. L0–L3 are implemented and integrated in P002-T022 ([D314](#d314--work-map-levels-on-the-product-routes-refresh-client-and-read-only-archive-map)); L4, the drawer and the talk button are T023–T024. Contract:
[T018 §§3–5](phase/P002-T018-work-map-contract.md#3-levels-cards-and-inspector-g14).

The map keeps D278's read-only projection. Compact cards per level carry code, title, status, circles, one primary
counter (L0 phases closed/total, L1 tasks committed/total, L2 attempt/revision limit, L3 duration), an error mark and
bubbles. A side inspector holds the full fields, with sources and "not observed" labels. L1 cards show Plan · Check ·
Close slots with the actors that actually took part. L3 shows agent invocations and the Harness validate, format and
commit stages. Existing routes keep their meaning, and `/projects/:p` stays the project page. L4 is the new
`/projects/:p/invocations/:i` for every lane, with the breadcrumb derived from the owner. The same path renders map
or list (`?view=list|map`), with the last choice remembered per browser and the map as default. Six status classes
(done green, progress orange, waiting violet, failed red, pending neutral, inactive grey) plus `unknown` each carry
an icon and a label. The shared list `Status` component adopts them. A parity test fails on any unmapped persisted
value. R covers reviewer-agent roles, E executor and preparation, J judge (shown with a judge profile or where a
judge actually ran) and H Harness deterministic work. Rays mark every active invocation, including the chat lane on
its conversation scope. Bubbles sit on the circle of the actor that raised the T017 item (lifecycle confirmations on
H; unresolvable origins on H, labelled). The archive home becomes the read-only map beside the run-id entry, with
no actions or polling. The drawer reads the DB rendering for knowledge projects and the read-only checkout view for
legacy projects in ordinary mode.

## D305 — Observed-step projection from sealed native evidence

Status: accepted explicitly by the owner on 2026-11-04 in P002-T018 (answers Q1–Q2); binds T019. Implemented in P002-T019
and integrated as source `e19cea3` after independent final re-review on 2026-11-05
([evidence](phase/P002-T019-observed-steps.md); details in
[D310](#d310--observed-step-pending-marker-projector-and-reads)). Additive to D287; does not reopen T006. Contract: [T018 §6](phase/P002-T018-work-map-contract.md#6-observed-step-projection-t019).

Corrected premise: parsed native records of 16 KiB or less already persist verbatim and unsanitized as `agent_event`
rows that retention does not remove. Larger records exist only as references into `stdout.bin`, whose bytes
retention can remove. The visual direction's statement that the sequence exists only in retained bytes is therefore
inaccurate; the records written before keep their text. Each settled managed attempt, with or without a workflow
operation, receives `invocation.step` events (`observed-step-1`, source `measured`) and one `invocation.steps_sealed`
marker in `trace_events`. Steps are client-neutral turns (labelled `claude_message` or `codex_turn`), tool calls,
messages, reasoning and `not_observed` gaps. They carry order, parent turn, call id, tool and origin, masked
256-character argument summaries with digests, outcomes (completed, error, denied, cancelled in flight, not
observed, unclassified), chunk-receipt timing and parallel groups; result and message content is excluded.
Each step keeps `source_record` references to its original `agent_event` rows. These are read through the existing run event and
attempt-log routes, only in the authenticated UI, and an oversize record whose bytes retention removed shows "unavailable
after retention" (owner addition at acceptance). The
settlement transaction records a pending marker. A deterministic projector derives the steps idempotently from
`agent_event` rows, `stream_bytes` and verified stdout bytes, without inference. Retention refuses streams whose
projection is pending. Limits: 10,000 steps and 4 MiB per invocation, plus `trace-payload-1`. Runs settled earlier
are not backfilled. They show counters, an explicit "steps not projected" label and the run evidence link. Steps
survive retention, backups and query-only restore.

## D306 — Work-map read projections, polling refresh and archive map

Status: accepted explicitly by the owner on 2026-11-04 in P002-T018 (answers Q5 and Q16); binds T020 and T022. The
API side is implemented and integrated as source `b30a00c` in P002-T020 after independent final re-review
([D311](#d311--work-map-read-projections-tokens-and-indexes)); T022's polling client and archive map are implemented and integrated ([D314](#d314--work-map-levels-on-the-product-routes-refresh-client-and-read-only-archive-map)). Refines D278's
"polling remains the default" and keeps D029. Contract:
[T018 §§7–8](phase/P002-T018-work-map-contract.md#7-read-projections-and-api-t020).

Versioned read-only `GET` projections under `/api/managed/map/` serve L0–L4, related records and an activity
summary, with OpenAPI and client parity. Step pages resolve source records to existing routes with their
availability. They have no mutation routes and no execution through edges. Pages use
opaque keyset cursors bound to project, level, scope and version. Per-level caps apply (100 projects, 200 phases,
300 task nodes, 50 runs, 200 steps). Earlier runs, older steps and related records load lazily. Responses carry a
version token. The activity poll (≤ 8 KiB idle) runs every 2 s while work is active and every 10 s when idle; it
pauses in hidden tabs and is off in archives. Changed tokens reload level snapshots, and a stale cursor returns
`409 cursor_stale` for snapshot recovery. Streaming is not adopted without measured need. Queries are filtered by
project root, and foreign identifiers return 404. Bubbles aggregate T017's unresolved items by identity and count.
Query-only archives serve the same projections from SQLite alone, and the archive home renders the read-only map.

## D307 — Contextual reviewer conversation on the canonical chat boundary

Accepted explicitly by the owner on 2026-11-04 in P002-T018 (answer Q3). T024 source `c1f28ab` is integrated
into develop after independent technical re-review and owner visual acceptance on 2026-11-09
([evidence](phase/P002-T024-contextual-chat.md)). This decision refines D297's knowledge delivery rule for chat.
Contract:
[T018 §9](phase/P002-T018-work-map-contract.md#9-contextual-reviewer-conversation-t024).

In knowledge projects, the reviewer's separate talk button carries a removable tag naming the phase, task, run or
step in view. Its reference is a stable ID with the current accepted revision, or a run/step evidence digest.
Foreign or stale references are refused, and removing the tag sends no element context. A chat turn carrying element
context is sealed through T007: a single-node chat graph thread, an agent invocation operation and an invocation
context over the accepted snapshot. It keeps the read-only HEAD snapshot without the checkout lock, and `managed_jobs`
stays the scheduler. The bounded context is framed as evidence and delivered on `initial_context` with one receipt
per reference. Knowledge kinds use existing entity types. Run and step evidence uses an additive
`knowledge-delivery-3` envelope with entity type `run_evidence`; earlier formats are unchanged. Turns without
element context keep today's path. Legacy projects offer no tag. Executor and judge panels have no free composer.
Guards, confirmations and the archive refusal remain.

## D308 — rough.js 4.6.6 and Excalifont v0.18.1 for the hand-drawn map

Status: accepted explicitly by the owner on 2026-11-04 in P002-T018 (answers Q17–Q18); dependency decision required by D297
before adding. Installation belongs to T021 with its own explicit network authorization. T021 adopted both locally on
2026-11-06 (independent final re-review passed; source `6b6a0ee` integrated into develop; [record](phase/P002-T021-rendering-foundation.md)): the font files match
the recorded hashes. Their `name` tables keep only the copyright; the OFL 1.1 statement, licence text, designers and
trademark are preserved for the same two files under `Origin File Name Table` in the font's `index.ts` at tag v0.18.1
(clarification of T018's wording in the [T021 record](phase/P002-T021-rendering-foundation.md#123-licence-provenance-and-lock-description);
no owner decision pending), and the shipped notice carries them. Contract and evidence:
[T018 §10](phase/P002-T018-work-map-contract.md#10-rendering-dependency-decision-installation-in-t021).

`roughjs` 4.6.6 (MIT) becomes a direct frontend dependency pinned exactly. It and its four MIT dependencies are
already locked as mermaid dependencies with the same integrity, its notice is already recorded and its built chunk
already ships (27,109 B; 8,789 B gzip), so no download is needed and the bundle delta is about zero. The map label
font is Excalifont from `excalidraw/excalidraw` tag v0.18.1, SIL OFL 1.1 ("Copyright (c) 2024 by Excalidraw",
derived from Virgil), shipped unmodified as two subsets selected by `unicode-range`: Latin (24,956 B, sha256
`e4423b31…1c48`) and Latin Extended-A (12,220 B, sha256 `4fb8ad69…cc93`). The Latin subset alone covers the en/es
character set. Other scripts fall back to the UI font. An OFL licence text with copyright and attribution ships beside
the fonts and in `NOTICE-THIRD-PARTY.md`. Serving is offline from the package with no CDN, and wheel and sdist
members are verified. Virgil (OFL 1.1 with Reserved Font Name "Virgil", 61,248 B) is the rejected alternative.

## D309 — Accessibility and realistic-size budgets for the work map

Status: accepted explicitly by the owner on 2026-11-04 in P002-T018 (answers Q19–Q20); binds T019–T024. T019 measured its
step-page budget (p95 3.1 ms over a synthetic 5,000-step trace, [evidence](phase/P002-T019-observed-steps.md)); T020
measured the projection-page and idle-poll budgets on the §12 fixture (integrated source, final re-review passed;
[evidence](phase/P002-T020-work-map-api.md)); T021 measured the rendering budgets on its synthetic fixture in the browser
(80-node first render median 77 ms, pan and zoom 60 fps at 200 visible nodes) and again on the code corrected after
review (median 71.6 ms; 60 fps; independent final re-review passed, source `6b6a0ee` integrated,
[evidence](phase/P002-T021-rendering-foundation.md#127-browser-re-verification-of-the-corrected-code)); T022 measured the
80-node first L2 render of the product map separately in Node SSR and in the synthetic browser, and repeated the
browser pan/zoom measurement after updating shared label fitting
([evidence](phase/P002-T022-work-map.md#12-bounded-label-fitting-and-current-inspector-focus-2026-11-07)). Contract: [T018 §§11–12](phase/P002-T018-work-map-contract.md#11-accessibility-t021t024).

The map and trace meet WCAG 2.2 AA. Every SVG node is focusable with an accessible name (kind, code, title, status
text, actors, bubble count), and keyboard operation is complete. Status is never shown by colour alone, and label
contrast is ≥ 4.5:1 in both themes. There is no motion under reduced motion. Equivalent list views exist, a throttled
polite live region announces changes, and en/es parity holds. Evidence uses one deep synthetic path of per-level
maxima (25 projects; 40 phases; 80 tasks; 30 runs; 40 invocations; 5,000 observed steps; 300 open inbox items), with
leaf siblings, not a Cartesian product. Budgets: projection page p95 ≤ 150 ms, idle poll ≤ 8 KiB, first 80-node L2
render ≤ 500 ms, pan and zoom ≥ 50 fps at 200 visible nodes, and the 5,000-step trace usable through lazy pages of
≤ 200. Each owning task measures its budget; a miss is a finding, never a silent relaxation.

## D310 — Observed-step pending marker, projector and reads

Status: accepted within the latitude the owner delegated for P002-T019 (marker representation, code organization,
pagination, transactions and recovery); implemented and integrated as source `e19cea3` after corrections to the first
(2026-11-04) and second (2026-11-05) independent technical reviews. Independent final re-review passed on 2026-11-05. Implements [D305](#d305--observed-step-projection-from-sealed-native-evidence) within
[T018 §6](phase/P002-T018-work-map-contract.md#6-observed-step-projection-t019) and D309;
[evidence](phase/P002-T019-observed-steps.md).

- **Pending marker.** An insert-only `trace_events` row `invocation.steps_pending` (`steps_pending:{invocation_id}`,
  source `derived`, without thread or operation link, so thread traces keep their T006 shape) is written in the
  settlement transaction of the attempt result or `confirm_stopped`. No table or column is added. Pending means a
  marker without `invocation.steps_sealed`; attempts without a ledger row get none.
- **Projector.** `storage/observed_steps.py` reads the sealed evidence in plain read sessions, derives with the pure
  `core/engine/observed_steps.py` (derivation 3) and writes `invocation.step` events in batches of 250 per writer
  transaction, then the sealed marker. The repository calls a post-commit hook with the invocation ids it marked;
  the runtime starts a background `observed-steps` thread with the supervisor that is woken by that hook. Each pass
  walks every pending marker once in marker order (a keyset over marker ids, so persistent failures never hide later
  markers), checks the stop flag before each invocation and then waits up to 10 s. Inside a projection the same
  flag is checked before each batch and before the seal: a stopped projection writes nothing more and stays pending,
  and the next pass replays its written batches as no-ops and seals once. Restored archives compose no
  supervisor, and the projector refuses writes under `query_only`.
- **Derivation.** Every native record is validated against the shape it is read with before any step changes; a
  malformed record becomes an `invalid_record` gap and an unknown Codex item type an `unsupported_event` gap
  (`item:<type>`, one per item), and later records are still derived. Codex tool items read explicit fields only
  (command, MCP arguments, file-change path and kind, search query). A Codex message is final only when its own turn
  is observed to complete; a Claude final is the successful terminal result. Steps observed only at their end
  (Codex items seen only at completion, messages, reasoning, gaps) record that end with start and duration absent.
  Coverage is `complete` only without gaps, open turns or calls, missing final answer, uncorrelated results, denials
  or broker events, ambiguous broker calls or a bound; otherwise `partial` with `coverage_reasons`. A harness call is
  linked to broker events only when name and argument digest single out one native call in the whole invocation
  (calls past the bound included) and one broker call; an ambiguous call keeps no link and records
  `link_absent: ambiguous_broker_calls`; discovery only when one broker call was open. Codex call fields that a
  call's first records do not carry (MCP server, tool, arguments; a file-change list, null while in progress) come
  from the first later record that carries them and are never replaced; a call first seen at `item.updated` has no
  start or duration; the last message of a completed turn without text is not a final answer
  (`message_text_absent`). At most 10,000 steps are materialized; later ones are counted by kind, and their calls
  still absorb their results and keep only their tool and argument digest for broker attribution. Overlap is an O(n log n) sweep; broker and range matching are
  linear.
- **Integrity.** Under the writer lock, every batch and the seal first check that no terminal marker exists, so two
  projectors never leave both a sealed and a failed marker; the first terminal marker stands. The seal also requires
  the persisted step keys to equal the derived sequence: extra rows from an earlier, longer derivation are a
  divergence (`integrity_step_set`). A different payload under an existing key is `integrity_conflict`. Either
  writes one `invocation.steps_failed` event (`steps_failed:{invocation_id}`); it is not retried and nothing is
  overwritten. Retention treats it like pending (the evidence stays for investigation; any manual intervention is
  outside T019).
- **Oversize records.** Read only when present, from the sealed capture's `stdout.bin` only: without a capture
  artifact (path, size, digest) every range is `capture_absent`. The file is opened through the backup module's
  no-follow walk (no link in any component, regular, one link, size bound), read once against every chunk digest and
  the capture's digest and size, then each range is read at its offset, one at a time, against its own digest
  (≤ 4 MiB + 1 byte). Any failure makes the record an `oversize_record_unavailable` gap with its code, size and
  digest. `source_record` references only `agent_event` rows; a parser diagnostic keeps its position and its
  `stream_record` number with no reference.
- **Capture boundary.** The projection's evidence must reach the journal (D305): the live `metrics-1` counters read
  a non-list Claude `content` as no blocks instead of raising, so the chunk and the record are journaled and the
  projector marks the record `invalid_record`; every other record counts as before. If an unforeseen failure still
  interrupts the read, the chunk already written and the records read from it are flushed to the journal, best
  effort and without masking the failure, before the interrupted capture is written.
- **Thread traces.** The T006 thread event and artifact queries never serve `invocation.step` rows; steps are read
  only through their sealed reader, so a projection in progress is invisible there and thread cursors never pass over
  rows that appear later. The sealed and failed markers remain visible.
- **Reads.** `ObservedSteps.page(invocation_id, root=None, after=None, limit≤200)`: keyset by the step event id (step
  order equals `seq` order because steps are written in order), only below the sealed marker. Pending, failed,
  not settled, earlier (`not_projected`, with persisted or pure `trace-observation-1` counters and the run evidence
  link) and excluded-lane states return no items. Internal only; T020 owns the HTTP API.
- **Index.** `0040_observed_step_reads` adds `ix_trace_events_invocation` (invocation_id, kind, id). On the
  §12 trace alone pages took p95 3.1 ms without it. With 150,000 and 600,000 other step events the existing
  `(kind, root)` index and a sort gave 7.3 and 20.7 ms, linear in the installation's projected history. With the
  index the time stays at 1.6 ms; after the corrections the 5,000-step pages measure p95 1.8–1.9 ms.
- **Downgrades.** 0040 downgrades by dropping the index only; steps stay. Because every settled attempt now writes
  trace rows, D287's rule that downgrades below 0032 are refused while journal rows exist also covers databases with
  only ordinary (non-graph) runs. Tests of older revisions remove their synthetic step rows, as they already did for
  accounting rows.

## D311 — Work-map read projections, tokens and indexes

Status: accepted within the latitude the owner delegated for P002-T020 (endpoint and type names, module organization,
response representation, cursors, queries and justified indexes); source complete after corrections to the
first technical review (six findings), three re-review remnants and historical assistance ownership after registry
retirement. Independent final re-review passed on 2026-11-05; source `b30a00c` is integrated into develop. P002-T022's
review corrections add one read on the same tokens and attribution, the element request list `map/projects/{p}/bubbles`
(local source, pending re-review; [D314](#d314--work-map-levels-on-the-product-routes-refresh-client-and-read-only-archive-map)). Implements [D306](#d306--work-map-read-projections-polling-refresh-and-archive-map) under
[T018 §§5, 7–8](phase/P002-T018-work-map-contract.md#7-read-projections-and-api-t020), D304 and D309;
[evidence](phase/P002-T020-work-map-api.md), [flow](flows/work-map.md).

- **Routes and modules.** Nine `GET` routes under `/api/managed/map/`: `projects`, `projects/{p}/phases`,
  `…/phases/{code}/tasks`, `…/tasks/{task}/runs`, `projects/{p}/runs/{run}/steps`, `projects/{p}/invocations/{i}`
  with `…/steps` and `…/related?group=records|permissions`, and `activity?scope=`. Response types `Map*`, format
  `work-map-1`. Pure tables and tokens in `core/engine/work_map.py`; queries in `storage/work_map.py`; routes in
  `api/work_map.py`. No mutation route.
- **Project identity.** T017's project identity (knowledge project, else registered, else the first run or phase of
  the root) is the map key; every route also accepts its aliases. Registered (configured) id and knowledge id are
  separate fields; in archives nothing is configured. L0 is ordered by checkout root (stable and indexed); the root
  never appears in responses or cursors, which carry the last project key.
- **Statuses.** T018 §5.2 plus the persisted values it omitted: attempt `REPETITIVE` (output-guard stop) is failed;
  legacy permission `DENIED_CONSUMED` is inactive; legacy permissions show their effective `EXPIRED` as the existing
  permission view does. A T010 request shows its historical answer (GRANTED, DENIED) apart from the authority a grant
  confers now (`effective`, `expired`, `ended`, `invalid`, from `PermissionLifecycle.active` over the grant and its
  ancestry); an unanswered request whose own expiry or ancestry expired or ended is EXPIRED or REVOKED, no longer
  `answerable`, exactly when T017 resolves it. The acceptance decision is `absent`, `rejected` (with its deterministic
  reasons) or `eligible` from the run projection; eligibility is never a commit. Phase operations:
  READY, CLOSED, ADOPTED, RECORDED done; QUEUED, INTENT progress; PROPOSED, STALE waiting; BLOCKED, REVISE,
  NOT_READY, INTERRUPTED, FAILED, REFUSED failed (the raw verdict stays visible); ABANDONED inactive. A phase code that
  only has task runs is `unknown` with reason `no_phase_record`; a task a successor replaces (D296) is inactive and keeps
  its run status. Totals (phases closed/total, tasks committed/total) exclude inactive nodes. The project class follows
  §5.2's order (failed, waiting, progress, done, pending), the failure coming from the autonomous run, the open phase or
  a latest task run of the open phase. A phase question raised outside a check attaches to H, not attributed.
- **Harness steps.** Per review cycle (0-based, after its executor round): format (`passed` when a formatting record
  exists, else `not_recorded`; a formatter stop is failed; duration absent, `not_measured_separately`) and validate
  (from the projection's command and case counts; duration from the validation checkpoint to the next checkpoint,
  `includes: format`); then every commit record with its own times.
- **Tokens.** A scope id is the level and its arguments, opaque, validated for type, level and arity before use
  (422 `scope_invalid`). A version is a digest of the sources the scope's responses show. L0: the whole database's
  latest insert-only sequences (run, phase, trace and autonomous events, permission records), accepted revisions,
  registry and preparation versions, assistance in progress, configured agents and the registered map. L1/L2: the
  root's run, phase and autonomous counts and version sums, its latest trace event, accepted revision, permission
  sequence and registry versions, plus bubble ids, every active lane with its process state, deterministic work and the
  root's configured agents. Runs: the task's run counts and versions. L3: the run's version, open processes, the latest
  step marker, observation and related trace event per invocation, delivery counts, the root's permission sequence and
  bubbles. L4 header: the same for one invocation plus its ledger state. Trace: its step markers and whether retention
  removed its own attempt's streams (source-record availability), so other attempts never supersede it. Related:
  the latest event per related kind, or the attempt's permission requests with their versions, latest T010 sequence
  and how many requests, answer grants or their respective ancestors have expired by now (time alone changes validity). Cursors carry scope, version
  and a keyset key over stable values with a digest check: the last project key (L0), phase code (L1), plan position
  or task code within its group (L2: plan, accepted identities of the phase, run-only tasks), creation time and id
  (runs, permissions), attempt number and sub-step (L3: invocation, format, validate, then the tail), trace event id
  (L4). Malformed, tampered or other-scope cursors answer 422 `cursor_invalid`, superseded versions 409 `cursor_stale`.
- **Bounded reads.** A page selects only its rows (skip scans for distinct roots, phase codes and run-only tasks;
  indexed ranges with `LIMIT` elsewhere; L2 run-only exclusion uses a SQL anti-existence test against accepted
  phase membership, and identity selection returns codes only) and enriches only its items; whole-scope counters (phases closed/total, tasks
  committed/total, per-phase failures) are SQL aggregates. T017's unresolved items are read per request, bounded by
  open owner items, not by history.
- **Related records and evidence.** `records`: trace events of the invocation with allowlisted identity, code and
  digest fields per kind and links to the existing thread artifact route. `permissions`: the attempt's legacy and T010
  requests with their T017 item ids. Source records link to the existing run-event and attempt-log routes;
  availability is `unavailable_after_retention` when the retention audit records the attempt's stdout as removed,
  else `available`, labelled `derived` (the log route verifies bytes on read).
- **Lanes and circles.** Active invocations come from every attributable ledger: managed attempts (chat included),
  executor steps of a reserved preparation (E; command steps are H work) and configuration assistance scoped to a
  registered project (R or E); a global assistance has no project and is listed as `unscoped_invocations`. Their L4
  is `lane_excluded`; no managed attempt is manufactured. Each circle carries why it is shown (`always`,
  `judge_profile`, `judge_history`), its latest persisted invocation in the element (project, phase or task) as the L4
  target or `inert` without one, and `waiting` when unresolved owner items sit on it, with or without a running
  invocation. Slot actors name their invocation. Tasks carry their accepted `problem` and `expected_result`, bounded,
  or `absent`.
  Chat ownership comes from its persisted conversation: the phase instance code or the associated task run's
  phase and task, consistently with activity and L4. Project assistance resolves through its registered project and
  persisted ASSIST operation, including completed operations and logically retired registrations; global assistance
  stays unscoped. Historical resolution never requires operational ACTIVE status and does not reactivate or compose
  a project; admission of new operations remains unchanged. Candidate branches
  select at most one invocation per role and owner by `(started_at, id)`, then merge chronologically.
- **Activity.** At most 10 scopes per poll and 50 active invocations listed (with a truncation flag); polling metadata
  2 s / 10 s, paused when hidden, disabled in archives.
- **Latency evidence.** The 150 ms budget is asserted in a serial run (`scripts/check tests/product/test_work_map.py
  -- -n 0`), part of every closing; under parallel test workers the latency assertion is skipped with its reason
  while sizes, totals, statuses, poll size and paging are still asserted.
- **Indexes.** `0041_work_map_reads` adds `ix_managed_runs_scope` (root, purpose, phase_id, task_id, created_at),
  `ix_managed_attempts_open` (run_id) where `result_json IS NULL`, `ix_phase_operations_phase` (phase_id, kind,
  created_at) and, for the circle targets added in the review corrections, `ix_usage_invocations_circle_root`
  (root, role, started_at, id), `…_circle_phase` (root, phase_code, role, started_at, id) and `…_circle_task` (root,
  phase_code, task_id, role, started_at, id): without them the latest invocation per role reads and sorts the
  element's ledger range. On the §12 fixture alone the indexes change little; beside 20,000 other runs and attempts the L0 page
  p95 is 340 ms and the activity poll 199 ms without them (over budget) and 52 ms and 24 ms with them. Downgrade to
  0040 drops the seven indexes only. The re-review correction adds `ix_usage_invocations_circle_project`
  (project_id, role, started_at, id) for root-NULL assistance. Chat candidates seek the root/role time index and test
  conversation membership without loading candidate histories; regular lanes retain phase/task seeks. The plan
  regression checks ordered seeks without branch sorts; assistance adds a primary-key fetch of its chosen row.

## D312 — Work-map engine, interaction conventions and development fixture

Status: accepted within the latitude the owner delegated for P002-T021 (names, module organization, internal
interfaces and reversible details, including the arrow-key convention); refined by the corrections of the first
independent review rounds (zoom range, gesture guard and delayed keyboard repeats); independent final re-review passed
and the owner accepted T021 on 2026-11-06. Source `6b6a0ee` is integrated into develop; personal visual review is explicitly
deferred to T022 under D313 and confirmed at T022 integration. Implements [D297](#d297--work-map-visual-direction-and-agent-conversation-entry-points),
[D304](#d304--work-map-levels-cards-navigation-and-status-classes), [D308](#d308--roughjs-466-and-excalifont-v0181-for-the-hand-drawn-map)
and [D309](#d309--accessibility-and-realistic-size-budgets-for-the-work-map) under
[T018 §§4, 5.1, 10–12](phase/P002-T018-work-map-contract.md#4-navigation); [evidence](phase/P002-T021-rendering-foundation.md).

- **Structure.** `frontend/src/map/` holds pure modules (seeds, status classes, layered layout, camera, interaction
  controller, labels, router binding, motion) and a thin SVG view, `MapView`. rough.js is used only through its
  generator: path data is rendered as React SVG paths whose colours come from CSS tokens, so a theme switch redraws
  nothing. Seeds derive from identities (`card:<node id>`, `edge:<from>-><to>:<kind>` and similar); geometry is in world
  coordinates and the camera is one transform. No canvas, editor, layout or zoom library.
- **Navigation.** Enterable nodes are SVG links to the existing routes and navigate through the shared `navigate`
  (`pushState`). Levels: home L0, phases L1, phase L2, task and run L3; the parent of task and run is the phase (both
  are L3). The zoom range is half the fitted scale (never an absolute floor, so every accepted level fits) up to 4×.
  A zoom-in enters an enterable node once it covers half of the viewport; leaving needs an accumulated
  zoom-out of ln 0.7 beyond the minimum within 600 ms windows, Escape or "Up one level". With motion allowed a 220 ms
  camera transition finishes the zoom before navigating; under reduced motion navigation is immediate. After
  reporting a navigation the controller ignores further ones for 1.5 s or until the new level arrives, and a
  page-wide gesture guard, which survives the level change and a remounted view, ignores the rest of the gesture that
  navigated, so one gesture navigates once: wheel or Safari pinch events less than 300 ms apart (a pause or a new pinch
  ends them), and every auto-repeat of the key press that navigated, however late, until a fresh key press (no timeout
  for keys). Any pointer press also starts a new gesture. Drags start at
  5 px (mouse) or 10 px (touch), capture the pointer only once started, and cancel the click that ends them. Camera and
  focused node are remembered per path in a bounded in-memory map (64), never as authority; returning to a parent
  focuses the entered node and pulls a remembered camera back below the enter threshold.
- **Keyboard.** One node is tabbable (roving tabindex). Arrows move the focus to the nearest node in that direction
  and the camera follows, which satisfies both "arrows move between nodes" and "arrow keys pan" of T018 §§4 and 11;
  Shift+arrows pan without moving the focus. + and − zoom about the focused node, 0 fits, Home/End go to the first and
  last node in reading order, Escape leaves, Enter is the link's native activation; modified keys are left to the
  browser.
- **Fonts and tokens.** Excalifont is declared globally with `unicode-range` equal to each subset's cmap, but named only
  in the `.map` scope and used only by `.map-label`; the build emits the OFL text as `assets/Excalifont-OFL-1.1.txt`.
  New token pairs `--progress`/`--progress-soft` (orange) and `--waiting`/`--waiting-soft` (violet) exist in light and
  both dark declarations; inactive uses `--muted` with a dashed outline.
- **Development fixture.** `map-fixture.html` and `src/map/fixture/` are served by the Vite development server for every
  path under `/__map-fixture/` (a `serve`-only plugin) and are never built or packaged. The fixture drives the real view,
  router and history under that base with deterministic synthetic data and needs no API or session.
  `I18nProvider` accepts `fixed` to pin a language without reading or writing preferences, for this fixture only.

## D313 — T021 acceptance with owner visual review deferred to the real-data map

Status: accepted explicitly by the owner on 2026-11-06 after T021's independent final technical re-review.

The owner accepts P002-T021 and authorizes its source commit, merge into `develop` and push of `develop`. For T021
only, the personal visual review required before integration by D303 is deferred until T022 connects the map to real
data. T021's synthetic browser checks and corrected-code performance measurements remain evidence, not a substitute
claim that the owner reviewed the fixture. T022 must retain this pending visual review in addition to its own
acceptance; other tasks' review gates are unchanged. The T018 contract and historical review records are preserved.

This acceptance does not authorize T022 implementation, release/publication, installation, database migration or
real agents/providers. Source completion, develop integration and operational delivery remain separate under D242.
Evidence: [T021 final review and acceptance](phase/P002-T021-rendering-foundation.md#13-independent-final-re-review-and-owner-acceptance--2026-11-06).
On 2026-11-07 the owner confirmed the deferred T021 visual acceptance together with T022's.
[Acceptance and integration record](phase/P002-T022-work-map.md#13-final-review-owner-acceptance-and-integration--2026-11-07).

## D314 — Work-map levels on the product routes, refresh client and read-only archive map

Status: accepted within the latitude the owner delegated for P002-T022 (module organization, names, hooks, internal
representation and reversible details compatible with the contract); **complete and integrated as source
`1149765` after independent final re-review and owner visual acceptance on 2026-11-07**. The first independent technical
review found seven defects, corrected locally (2026-11-06); the re-review reproduced two remaining problems (a failed
run-selector reread hidden behind an earlier empty read; L3 chats taken from the truncated global activity list and
absent in archives), corrected locally; opening the synthetic frontend then showed two blocking browser defects
(status and counter overlapping on cards; a closed mobile inspector keeping hidden controls in the Tab order),
corrected locally on 2026-11-07 with browser evidence and the D309 browser measurements. The next re-review
reproduced quadratic label fitting and stale deferred inspector focus, both corrected and independently re-reviewed
(record §§12–13). The corrections needed two minimal read extensions, authorized for them by
the owner: the element request list and the run's chat lane in the steps read, both below.
Implements [D304](#d304--work-map-levels-cards-navigation-and-status-classes),
[D306](#d306--work-map-read-projections-polling-refresh-and-archive-map) and
[D309](#d309--accessibility-and-realistic-size-budgets-for-the-work-map) on T020's projections
([D311](#d311--work-map-read-projections-tokens-and-indexes)) with T021's engine
([D312](#d312--work-map-engine-interaction-conventions-and-development-fixture)); the owner's visual review, including
T021's deferred one ([D313](#d313--t021-acceptance-with-owner-visual-review-deferred-to-the-real-data-map)), is confirmed.
Evidence: [P002-T022 record](phase/P002-T022-work-map.md).

- **Routes and toggle.** `/`, `/projects/:p/phases`, `…/phases/:code`, `…/tasks/:task` and `…/runs/:run` render the
  map by default and the existing page with all its controls under `?view=list`; the check route is not a map level.
  The toggle writes the parameter as a history entry and remembers the choice in `localStorage` (try/catch). The
  choice made in this page wins over an older stored value, so a write that fails while reads work keeps the new
  choice; a parameter applies to its own URL only (corrected: a URL that names the view no longer becomes the
  remembered choice, so an evidence link does not turn the owner's map into the list for cards and breadcrumbs). `navigation.tsx`
  adds `useSearch` and compares path and query when deduplicating, while `usePath` keeps observing the path only.
  Entering a project card in ordinary mode uses its configured project id (the list pages need it); archives and
  unregistered projects use the map key, which T020 and T017 accept as an alias.
- **Cards and controls.** Cards draw T020's class, primary counter (or "not observed"), error mark, L0 mode badge and
  L1 Plan · Check · Close slots inside the card link. Rows (corrected after the browser review): code and badge, two
  title lines, the status and the counter each on a row of its own (cards 128 px high); every label is fitted to its
  row with a per-character width table that bounds both the map font and its fallback, the same on the server and in
  the browser, and cut with "…" only when it does not fit; an unknown status that does not fit as "Unknown: CODE"
  shows its raw code. The accessible name keeps the full status text and counter, the description the raw code. Circles, request bubbles and a details control are separate
  overlay controls outside the link, kept out of the tab order (the inspector offers each one to the keyboard), so
  choosing them never navigates the card. Circles are drawn on every project card and, deeper, only on the open phase
  or where a circle is active, waits or a task is in progress or waiting; the inspector always lists every circle.
  Several active invocations stay distinct (corrected): an active circle is one actor per active invocation of the
  element, from T020's `active_invocations`, each with its own persisted invocation as target and its own chat flag,
  so a task reviewer and a chat at once are two R circles; the circle's request count sits on its first actor; H stays
  one actor. At L3 an active chat attached to the run shown is a lane node of its own, with R lit and labelled "chat",
  no edge into the step sequence and no fabricated step. Its source is the run's own steps read (corrected after the
  re-review; never the global activity list, truncated at 50): `MapStepsRead.chats` lists the active chat invocations
  whose conversation is attached to the run (T020's `_active` for the run's root, `chat` and `scope.run_id`), oldest
  first, at most 20, with `chats_truncated` shown as a coverage hint; the list is the same on every page and part of
  the steps version (every attached chat's attempt and process), so a chat that starts, changes process or ends
  rereads the steps, and an archive's single read shows it. OpenAPI and the generated client are updated; no schema,
  persistence or authorization change.
- **Inspector.** Selection follows focus (and clicks on leaves); it is a side panel, or a bottom sheet below 880 px.
  Closed, the sheet shows its heading and *Show details* only: its body is not rendered (no Tab stop or accessible
  content); open, only the body scrolls, so the heading and the control stay in view (corrected after the browser
  review). The control names the body with `aria-controls`; wide screens always show the body. Narrowing the window
  with the focus in the inspector opens the sheet and keeps (or restores) that focus, never taking it from elsewhere.
  Fields keep their T020 source; harness attempts, revision rounds, native turns, requested and reported models are
  separate fields. Steps stay the deepest map level: the circle of an invocation opens `/projects/:p/invocations/:i`,
  which in T022 serves only T020's existing L4 header read (identity, owner breadcrumb, counters, observed-step
  state, run evidence link); the trace graph and drawer remain T023.
- **Requests.** Bubbles open T017's `InboxConversation` inside the inspector, carrying item identities only; the
  conversation re-reads the item. A single listed request opens directly. L0 aggregates (counts only) and
  `items_truncated` lists read the **element request list** `GET /api/managed/map/projects/{p}/bubbles` (corrected;
  T017's inbox items carry no circle or attempt, so filtering them could not keep the actor): T020's own attributed
  set (`_bubbles`, the one the counters come from) filtered exactly by `phase`, `task`, `run`, `attempt` and
  optionally `circle`, 50 per page keyset by item id, with the counts of the whole set. Its scope token carries the
  filters (`=value` or `~`), its version digests the filtered ids, so a cursor is bound to project and filters and a
  changed set answers `409 cursor_stale`; it polls like any scope, is isolated by the project root (foreign ids 404),
  reads SQLite only and is identical in restored archives; OpenAPI and the generated client are updated. No
  authorization semantics or persistence change; T017 stays the authority for resolution and actions. L0 reads no
  scope, L1 its phase, L2 phase and task, a step its run and attempt. Archives open it read-only.
- **Refresh.** One `LevelLoader` per level path: one request in flight (a reload asked meanwhile runs once after it),
  further pages on demand inside a window of five held pages (corrected: past it the oldest pages are dropped and
  counted, the first page is kept apart for its head fields, and "Back to the first page" reloads, so pages after the
  fifth stay reachable with bounded memory), `409 cursor_stale` returns to the first page and rereads it, and a
  disposed loader applies no late answer. One `ActivityPoller` per view sends one aggregated `map/activity` read for
  every scope known in view (level and run selector; corrected: a task without runs is followed through its run
  selector, so its first run appears without navigation), schedules the next read only after the previous one
  settled (2 s active, 10 s idle, as the response states), pauses while hidden and stops when a response disables
  polling. A changed or vanished scope reloads that level's first page. A failed first read offers "Read again"; a
  failed reread over a snapshot still shown, including a run selector read empty before (corrected after the
  re-review), keeps that snapshot as possibly out of date with the error and a mounted "Read again"; a failed poll
  shows that the map may be out of date until a read succeeds (retried at 10 s, one timer). Archives create neither a
  poller nor an announcer.
- **Announcements.** A polite live region summarises status changes of elements already shown (class and raw code,
  so a language switch is not a change) at most once every 10 s; a level's first read is never announced.
- **Status.** `frontend/src/status-classes.json` copies T020's run, attempt and phase tables; the shared `Status`
  shows the six classes plus `unknown` with an icon, translated text and the raw code for assistive technology, and
  `tests/product/test_frontend_status_parity.py` fails on any divergence from `core/engine/work_map.py` or the
  persisted vocabularies. The map shows T020's class as projected (`MapStatusBadge`).
- **Archives.** Map levels resolve in the query-only branch before any `ProjectWorkspace`: the archive home is the
  map L0 beside the run-id entry, map routes and the invocation header are unblocked, their list alternative is a
  table over the same projection whose rows (corrected) fill the inspector, link to each actor's invocation and open
  the element's requests from the keyboard, and every operational page stays blocked. "Run evidence" (L3 summary and
  invocation header) opens the run page with its evidence and controls (`?view=list`; `/runs/:id` keeps the query
  when it resolves) and the run consultation in archives.
- **Development review.** The T021 fixture gains a product source: the real map components under `/__map-fixture`
  with a fetch shim that answers from synthetic T020-shaped projections (`map/fixture/projections.ts`, also used by
  the Node tests) and refuses every mutation. `RouteBase` prefixes route links there; it is empty in the product.


## D315 — L4 trace consultation and canonical map documentation

Status: implemented and integrated into develop as source `4a09d5d` under the owner's P002-T023 authorization
on 2026-11-07. Independent technical re-review passed after the navigation, sequence-arrow, drawer-width and evidence-placement fixes.
The owner then authorized this session to finish the exact-original read (D316), which is locally verified and
self-reviewed, and accepted the synthetic desktop/mobile visual review. Final verification passed; push of
develop is authorized.
Evidence is in the [task record](phase/P002-T023-trace-docs.md).

L4 reuses the existing SVG, inspector, map/list preference, keyset loader and activity client. Each paged read is
capped at 200. All evidence holds up to five batches plus the head, with one new page per unfinished group in each
batch. Batches are read units, not temporal watermarks across group cursors. Native steps keep `seq` order.
Exact persisted `tool.links` event IDs associate a related record with an unambiguous step in that batch; a
labelled correlation link has no arrowhead and implies no causation. Other evidence, including permissions and
records with anchors outside the batch, is shown in a separate **Related evidence — position undetermined**
section in graph and list, preserving group read order. Receipt clocks, native/broker call IDs and cursor bounds
do not determine native position. Later pages never reposition already published items. The complete batch is
split into windows of at most 200 SVG/list items in total across both sections.
Navigation consumes every window before advancing and restores the exact preceding held window. A stale cursor
restarts the whole batch history at the first pages. A group filter starts its own history from the first page.
Turn arrows follow persisted step sequence. Turn membership, recorded event parentage and explicit causation
have distinct styles. If parentage and causation refer to the same pair, the graph draws the explicit cause once
and the inspector shows both fields. Source originals are explicit authenticated reads;
metadata never implies that the large record's bytes can be read.

The L1–L4 non-modal drawer reuses the existing documentation tree and protected Markdown/Mermaid renderer.
The map and drawer fit the shell's content area. The drawer places the tree beside the document when its own
width permits, and below the document in narrower drawers.
`GET /api/managed/map/projects/{p}/documents[?path=…]` resolves the map's persisted root identities and returns only
canonical accepted Markdown/tree/revision from SQLite using D294's renderer. It exposes no transfer payload and
never calls runtime project composition. A canonical error never falls back to checkout; legacy checkout reads
are offered only without structured knowledge in ordinary mode. Archives never use checkout reads. Editing,
export and adoption remain in their existing views. No schema, dependency or authority change is made.

The initial T018 §6.4 large-original contract discrepancy is resolved by the owner-authorized continuation
and [D316](#d316--exact-single-record-consultation-of-retained-agent-originals). Owner visual acceptance and
verification are recorded above. Source, integration,
protected-main 0.2.0 release, distribution/publication and installation are recorded separately (D242).


## D316 — Exact single-record consultation of retained agent originals

Status: implemented and integrated as source `4a09d5d` under the owner's 2026-11-07 instruction to finish
P002-T023 here, after the
independent technical re-review of the prior source passed. The optional-sequence proposal in T023 is adopted
within that authorization; the UTF-8 representation and reuse of T019's bound are implementation choices.
The owner accepted the visual review on 2026-11-07. Final verification passed; push of develop is authorized.

`GET /api/managed/runs/{run}/attempts/{attempt}/logs` retains its existing `ManagedLogRead[]` response when
`sequence` is absent. A positive run-event sequence selects exactly one oversize `agent_event` owned by that
attempt; a foreign or absent record answers the same 404. There is no caller-selected path, offset or range.
An inline original remains available through its existing run-event read.

The typed `ManagedOriginalRead` envelope names the run, attempt, sequence, stdout offset, byte size and SHA-256,
with `encoding: utf-8` and `limit_bytes: 4194305` (T019's 4 MiB plus one JSONL newline). Its `content` preserves
the exact UTF-8 record, including whitespace/newline, only when state is `retained`. A sealed STOPPED capture,
no-follow file opening, every recorded stream chunk, capture size/hash and the selected record's size/hash are
verified through the shared `StdoutRanges` descriptor. The range bound is checked before reading/allocating it.
A missing stream, pending seal/retention intent, authorized purge or verification failure yields
`missing`, `pending`, `purged` or `unverified`, respectively, with null content and an en/es diagnostic.

Restored consultation resolves only the verified bundle's copy, never its historical path or checkout. Session
and Host/Origin guards apply; reads write nothing. The inspector explicitly requests the selected original,
checks the response identity against its projection reference and renders text escaped. The ordinary metadata
button stays separate. OpenAPI/generated-client and work-map/backup flow parity are included. No model,
migration, dependency, provider or product execution change is involved.

## D317 — Contextual chat references and observed element evidence

Accepted technical implementation of D307 within P002-T024, authorized on 2026-11-09. Source `c1f28ab` is
integrated into develop after independent technical re-review and owner visual acceptance.
[Evidence](phase/P002-T024-contextual-chat.md).

`GET /api/managed/projects/{project}/chat-context` resolves an explicit phase/task identity or code, run ID, or run
ID plus T020 stable step key into a server-owned label and closed reference. The reference's `project` is the
persisted knowledge-project ID, not a browser label or filesystem path. Knowledge references contain `stable_id`
and the current `revision_id`; run references contain `run_id` and `evidence_digest`; step references additionally
contain `step_key`. The run ID plus stable key covers invocation steps and deterministic Harness stages. The
request cannot contain other identities, labels or content. Admission verifies membership and freshness in the
same managed write transaction that freezes the turn and prepares T007's accepted snapshot. A matching idempotent
replay returns the original job even after a later revision. `409 element_stale` requires an explicit tag refresh
or removal. Refresh never resubmits inference. Tag controls are locked while a submitted request is pending/uncertain, so
its immutable idempotent replay cannot secretly restore a removed selection. Commands require tag removal and retain their existing confirmation.

Map-created conversations have no implicit phase/task-run bindings. Their removable selection is held per project
and conversation in the browser session; only `element` is sent with the message. Clearing it also removes its
refresh locator. Existing manually bound conversations, explicit documents/run selections, previous-turn history
and untagged chat retain their contracts. Legacy projects explain the absence of canonical context. Restored maps
mount no talk control and the existing archive mutation middleware refuses submissions.

The existing canonical entity renderer supplies phase/task Markdown. Run/step evidence reads bounded T020
projections directly, never complete run histories or native originals. The reference, label and evidence frame count towards the
16 KiB UTF-8 ceiling; complete Unicode scalars, source and exposure digests, codepoint ranges, byte limit and
truncation are preserved. The selected element is a capture, never an instruction or permission. Ordinary accepted
instructions and the frozen profile remain T007 sources. Canonical renderer output and old snapshot formats are
unchanged.

No migration or new scheduler: `chat_turns.request` holds the bounded frozen selection and the canonical marker;
`context_snapshots` keeps its existing format. A single-node `chat-turn@1` graph wraps the claimed job and supplies
its `agent_invocation` operation. The existing native attempt creates exactly one accounting row. The execution
directory is still the read-only HEAD export; the request, knowledge project, operation and accounting retain the
original root. No checkout lock is acquired.

Only the existing completed-input adapter observation records `initial_context`: ordinary T007 entries plus
exactly one element exposure. Preparation, queueing and a model answer do not establish delivery. Pre-GO refusal
has failure receipts without delivery digests; partial input is unknown; receipt persistence failure cannot report
success; uncertain results are never retried automatically. Phase/task receipts keep `knowledge-delivery-2` and
their existing entity kinds. Only `run_evidence` uses additive `knowledge-delivery-3`; v1/v2 remain unchanged.
Readers and backup verification check the frozen turn, prompt, canonical source, exposures, receipt hashes and
journal correspondence, including without checkout in query-only restored copies. Trace events carry identities,
limits and hashes, never element text.

## D318 — Workflow attribution in invocation accounting

Technical implementation of D254–D262 and D287 in P002-T025. Independent technical re-review passed and source
`18bef36` is integrated into develop by the accompanying authorized merge.
[Contract and evidence](phase/P002-T025-accounting-efficiency.md).

Accounting resolves a workflow execution as the graph thread of the invocation's journal operation. The
operation must match the invocation, its native attempt and its root. Both IDs are nullable read fields
and filter/group dimensions, and presence of the link is independently filterable. Configuration assistance
retains its original `operation_id`. Trace and Accounting share the persisted link. L4 opens the exact
ledger detail using its invocation ID. No attribution is inferred from neighbouring trace events, run IDs
or later workflow activity. The archive resolves its project scope from persisted identities.

Page workflow/operation keys before accumulating their totals. Ranking uses the existing invocation
selection grain, including one count per cohort member even when multiple bases are selected. The
original admission valuation, named cohorts, coverage and decimal subtotal rules continue to apply.
An unclassified process intent becomes unknown when its native source settles. Preparation stopped-writer
paths settle recorded executor intents, and accounting excludes only proven launch refusals, including the
historical stopped identity-change gate. No schema migration, history rewrite or authority change.

The technical review tightened the launch and attribution boundaries. A gate wrapper identity and a closing
capture without target stdout or native telemetry leave execution unknown. The persisted refusal boundary
and the stopped historical identity-change gate still establish `not_invoked`. Partial native output remains
observed evidence. The supervisor starts the gate interpreter with `-I -S` to exclude Python startup hooks
from the capture while passing the configured environment to the CLI through exec. Previously sealed captures
keep their bytes and interpretation.

Accounting resolves the effective project root of a rootless configuration-assistance invocation through its
persisted registered project ID, including retired registrations during consultation. A global assistance
keeps an absent project. The native row and its configuration-assistance operation identity are preserved.

`autonomous_run_id` is a separate filter, grouping dimension and invocation read field. The projection matches
the exact job idempotency key of an inference-bearing delegated child, verifies the authorization's lineage
and project root and matches the managed run, native attempt and ledger root. Several matching jobs of one
execution collapse to one managed-run attribution. Conflicting parent identities leave attribution absent.
The immediate `workflow_id` retains its meaning. Historical reads can include closed executions and earlier
authorization revisions within the same lineage. Readiness work before delegation stays unlinked. Accounting
reads the existing ownership evidence independently of the live admission, cap and fencing checks.
