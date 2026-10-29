# P002 planning — portable tools and archive maintenance

Date: 2026-10-29. Scope: documentation-only planning and the owner's requested repository archive cleanup on
docs/p002-plan. No P002 product task starts, no new dependency is adopted and no commit/delivery is performed.

## Portable discovery direction

The owner requests future OpenCode compatibility. The draft design/plan v0.2 now calls for a harness-owned,
versioned client-neutral discovery/description/invocation contract over suitable existing transports. A small
static broker surface can search a trusted catalogue and invoke a selected logical tool with server-side schema,
scope, revision and idempotency validation. Native tool search may optimize the same semantics but is not required
for the baseline. Generic dispatch cannot authorize arbitrary SQL or bypass the underlying domain command.

The [design basis](P002-design-basis.md#b08--tool-discovery-on-demand) and proposed T002/T005/T008/T021 cover that
boundary, conformance and audits. Client kind and inference provider remain distinct. OpenCode's documented
[MCP](https://opencode.ai/docs/mcp-servers/) and [custom-tool](https://opencode.ai/docs/custom-tools/) interfaces are
candidate surfaces, not qualification of an installed adapter, subscription mode or trace coverage. OpenCode
implementation remains future work; there are still 23 proposed P002 tasks, none started.

## Archive ownership and navigation

[D267](../DECISIONS.md#d267--archive-completed-one-offs-separately-from-active-phase-work) records the repository-only
policy. The 13 historical records already exist in recorded origin/main at 5cc1bc1. OT001–OT008, the queue setup,
OT002 handoff and pre-numbering activation fix move to `docs/archive/one_off_tasks/`; the model-selector/npm-cache
notes move to `docs/archive/project-history/`. The narrower P002 proposal and all current P002 design files remain
in phase/. Main integration is distinct from pending release/publication/installation, which remain in the queue.

The owner explicitly authorized a navigation-only exception to D266: 17 link destinations in archived P001 STATE,
NEXT_STEPS and P001-metrics-records may follow the moved records. No historical text/results or other P001 artifacts
may change. Existing current-document links and moved records' relative links are rebased as well. Frozen formats,
published contents and source fingerprints are not rewritten.

## Verification

Archive relocation, prose preservation, approved-only P001 changes, local link/fence checks, draft task integrity
and reviewed diff are checked before closing this documentation pass. Product tests, browser/runtime integration,
real agents/providers, harness execution, installs, Git ref/index mutations, publication and operator changes are
outside this pass. Results and omissions are recorded below after verification.

Results: all 83 current Markdown files pass `scripts/check-docs` when explicitly including untracked/relocated
files; the ordinary tracked-file check also passes its catalogue/data parity checks. The 13 relocated records have
identical content after masking only Markdown navigation destinations. Across relocation/current references,
52 relative targets were rebased in 15 files; the closed P001 subset is exactly the 17 explicitly authorized
targets in three files. All other P001 Markdown and its observation JSON remain byte-identical to the pre-edit
baseline. Prior P002 discussion and the narrower proposal are preserved. Draft v0.2 retains 23 unique tasks,
69 subtasks and matching acyclic dependencies. `git diff --check` passes and the diff was reviewed.

## Authorized integration and next task

After the documentation review, the owner authorized committing docs/p002-plan, merging it into the repository's
actual integration branch `develop` (called "development" in the request), and pushing develop to origin. Git
history and the verified remote ref record the resulting source/merge identities; this does not authorize a main
release, publication, installation or product execution. The pre-commit check includes all 83 current Markdown
files, including the new/relocated records, and the ordinary catalogue/data documentation checks.

The next task is P002-T001: review/adopt the evolving design baseline, formalize authority contracts and proposed
flows/guards, record durable decisions and the threat model, and maintain the requirement/task coverage. It is a
design/documentation task; P002-T002 dependency/provider feasibility and product implementation have not started.
The task plan remains a proposed v0.2 baseline until its explicit adoption; committing the draft is not a claim
that any new runtime behavior exists. The next session must follow AGENTS discovery and use a new topic branch
from the integrated develop. This integration authorization is for the current documentation changes only.
