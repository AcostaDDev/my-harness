# P002-T011 — Database-owned creation and reverse-engineering intake

Current status (2026-10-31): **source `616846d` completed and integrated into develop by the accompanying
authorized merge; independent technical re-review passed; push of develop authorized by the owner**. The reports below retain prior
implementation/correction evidence; the final technical re-review section records the current result and
authorization. Release 0.2.0, distribution/publication and installation remain pending and unauthorized.

## Contract and delivery

Owner: P002-T011. Local source work, synthetic offline verification and documentation were authorized; the owner
subsequently authorized source commit, merge and push subject to successful technical re-review (now passed).
Base: clean `develop` at `40027f8490f2d26dd68725739617a4b1d6bdb258`, matching local `origin/develop`;
no remote queried. Branch: `feat/p002-t011-db-intake`.

New intake uses D284 entities, versions and relations, not whole-document JSON authority. Brief and static
HEAD inventory remain untrusted evidence. Before a first adoption there is no accepted revision; none is
fabricated. Owner confirmation binds the exact structured draft, conversation/questions and source evidence.
Models propose only. Historical conversations and originals remain unchanged. Profile, preparation and
activation remain independent gates. T013 owns generated export/commit; T016 owns readiness; T020 owns
installed conversion. No automatic conversion, project execution, provider call or permission expansion.

Acceptance: synthetic definition and onboarding through canonical adoption; exact previews, provenance,
structural completeness, question deferral, stale/concurrent refusal, idempotency, query-only/project isolation,
and recovery without repeating inference. API and bilingual UI must expose the review.

Delivery stages (tracked separately):

- Local source implementation/verification: complete; independent technical re-review passed.
- Source commit: `616846d`, completed on `feat/p002-t011-db-intake`.
- Integration into develop: completed by the accompanying authorized merge; push of develop authorized.
- Release 0.2.0 through protected main: pending, unauthorized.
- Distribution/publication: pending, unauthorized.
- Installation: pending, unauthorized.

## Implemented local boundaries

`structured-intake-1` is an explicit per-conversation opt-in; the creation/onboarding UI selects it for
new conversations. Existing conversations retain their frozen documentary path. API clients select
`structured=true`; omitting it preserves the historical API lane. A structured invocation uses the
existing accounted/journalled planning turn and read-only HEAD export, with a sealed structured response
schema. No tool calls, SQLite access, permission grants or new inference retry path are introduced.
Before adoption, `accepted_revision=null` explicitly labels the first-turn absence of canonical knowledge.
A new structured intake is refused if an accepted knowledge revision already exists at that root.

The owner stages the exact answered-turn proposal via `intake.stage`; its shared domain transaction
creates D284 item identities, immutable versions, members and typed links. The conversation log stores
references and source fingerprints, not the authority itself. Re-staging a later turn discards the earlier
draft without changing its versions or proposal evidence. A response from an interrupted/failed turn is
never adoptable. Staging and owner adoption are idempotent domain outcomes; recovery reconstructs a preview
from persisted records without an inference call. The existing conversation version fences concurrent
turns, questions and adoption. Link endpoints in model proposals use `kind:document:code` (empty document
for nonsections); persistent links use real D284 identities.

`intake.preview` validates D284 rules and requires requirements, criteria, phases, tasks and rich sections,
with all five logical documents and criteria for each requirement/phase/task and no unresolved nondeferred blocking questions. It returns
full content/provenance, relationships, sensitive changes, open reviewer gaps and independent future gates.
`intake.adopt` rechecks the preview, conversation version, exact draft and current HEAD/inventory and creates
an immutable `owner_confirmed` revision. The domain outcome retains the full preview, including questions,
deferrals and gaps. Adoption does not create operational ACTIVE phases or assert profile readiness.

The UI separates conversation, staging, preview and explicit confirmation with a reason. Full fields,
Markdown/Mermaid, relations and provenance are reviewable. Documentary mutation/commit routes reject
structured intake. All original files remain untouched. Export/commit explicitly reports
`export_commit_pending_T013`; no full operational creation/onboarding journey is claimed.

## Interfaces reserved for later tasks

- T012: accepted D284 identities/versions and linear history; no general editor or rebase implemented here.
- T013: accepted revision ID/hash plus frozen source inventory, original HEAD/tree, conversation/turn and
  proposal hash. No export manifest or portable format is chosen here. Export/commit remains pending.
- T016/G12: validated members/relations plus cited reviewer gaps, questions/answers and explicit deferrals.
  Structural intake validation is not the final readiness contract or permission to execute.
- T020: source root, conversation ID/kind, brief hash/bytes, HEAD/tree/inventory, turn request/result hashes,
  original documentary proposals/edits, profile decisions, bootstrap/import intents and outcomes, accepted
  revision/item/version IDs and provenance. Conversion must map those references explicitly and preserve
  old originals/history; this change never converts installed conversations or invents old execution evidence.

## Initial implementation verification and outstanding scope (superseded below)

Final focused command:
` scripts/check tests/product/test_structured_intake.py tests/product/test_domain_operations.py tests/product/test_prompts.py tests/product/test_definition.py tests/product/test_onboarding_conversation.py tests/product/test_profile_proposals.py `
passed **223 tests**. Log: `.local/check/p002-t011-final-focused.log` (local, not distributed).
The eleven new intake regressions cover definition and onboarding through owner adoption, owner HTTP adoption,
exact/stale previews, stale HEAD, project isolation, questions and reasoned deferral, idempotency, service reopening,
new-turn draft replacement, preservation of original/adversarial instructions, staging rollback, concurrent adoption
and query-only refusal. The final follow-up also freezes the current database draft through the shared
`knowledge.draft.get` query in subsequent turns; generic mutation/adoption routes refuse intake-owned drafts.
Prior unstaged proposals stay explicitly noncanonical in conversation context. Legacy creation request digests
are unchanged when structured intake is not selected.

One closure `scripts/check --frontend` ran: unittest **10 passed**; Alembic **clean**; pytest **2,680 passed,
99 failed, 26 errors, 2 skipped**, 29 subtests passed; Node **250 passed**. The reported Python failures included
process-inspection and temporary-socket restrictions. All **125** cached full-run failures/errors subsequently
passed with access to those local facilities (`scripts/check tests/product -- --lf`); the complete Python suite
was not repeated. The two frontend type errors were corrected and the build-only check passed (**tsc + Vite**).
Changes after that closure run received the final focused checks above; no clean single full-suite run of the
final tree is claimed.

A focused wrapper completed while the full wrapper was running and replaced the common pytest log; the complete
original failure log was not retained. Compact full-run results and cached failing IDs were inspected, followed
by the failing-case recheck. The log copy of that recheck was also overtaken by a focused run; its tool result
records 125 passing cases. These are verification-evidence limitations; only the final 223-case log is retained
reliably. `scripts/check-docs`: **107 Markdown files, zero errors**; `git diff --check`: **clean**.
OpenAPI/client were regenerated with the README commands. Source diff and added files were inspected locally;
this is not an independent technical review. ONE_OFF_TASKS remains empty.

**T011 remains in progress.** Structured profile proposal/confirmation binding is still missing; the new
structured response currently proposes knowledge only. Existing profile, preparation and activation gates are
preserved and unsatisfied, rather than implicitly passed by adoption. Additional fault injection/UX coverage
remains desirable before acceptance; no browser, real provider or native qualification was performed. This gap
belongs to T011 and is not reassigned to T013 or T016. The UI currently selects the structured lane for new intake;
reviewers must account for its explicit pending profile/export continuation before any integration.

Delivery remains: local source **in progress** → develop **pending** → release 0.2.0 through protected main
**pending** → distribution/publication **pending** → installation **pending**. No commit, merge, push, release,
publication, installation, network download, global configuration change, real agent/provider launch or service
startup occurred. All fixtures and temporary Git commits are synthetic.

## Technical review correction round

The owner requested all three findings corrected on the existing uncommitted branch: structured profile
proposal/confirmation, historical owner evidence and preserved deterministic instructions. Review has not passed;
commit/merge/push are prohibited in this round. Delivery stages above remain separate. Corrections and synthetic
verification below will replace no frozen conversation, prompt snapshot or historical result.


### Corrections implemented for new review (D292)

1. **Structured profile (P1).** Profileless definition/onboarding require the existing nullable profile schema
   alongside knowledge. The normal profile parser, executable aliases, tool/evidence/validation and preparation-plan
   checks still validate the entire turn before producing proposals. `project-profile-proposal-2` binds exact
   proposed knowledge and conversation-scoped source hashes instead of requiring fictional document files.
   Owner profile preview/confirmation requires the exact staged knowledge; it also works after separate knowledge
   adoption, without an export. Preview seals actual revision/hash/status (including deterministic originals),
   source ledger, conversation version, candidate, questions and deferred reasons; stale knowledge, HEAD/inventory,
   source, runtime versions and previews refuse confirmation. The existing profile editor and explicit confirmation
   are exposed in IntakeReview. Owner decision evidence retains the full preview/binding and origin. Private
   configuration, preparation and activation remain separate; documentary rendering/export still refuses pending T013.
2. **Historical sources (P1).** A read-only source ledger selects only ANSWERED messages in the same conversation
   through the proposing turn, verifies their frozen request/context digests and retains stable owner-turn locators.
   Brief and frozen read inventory sources remain available. New invocations freeze this ledger; staging and previews
   verify its exact digest. Content hashes cannot come from another conversation/project; explicit source paths and
   owner-turn locators must also match. Nothing rewrites a historical source to the current message.
3. **Original instructions (P2).** Each staging deterministically rereads original instruction blobs from frozen
   local HEAD, with byte/UTF-8 bounds and no project execution. Preserved members are recognized only when exact
   identity, content, provenance, source and previous staged position match that trusted reconstruction. Their
   ordered links are checked and merged once, with root positions compacted around deterministic originals.
   Changed or forged members/links are refused; code prefixes alone grant no trust. Originals and prior evidence
   remain intact, including after failed staging rollback.

Maintained regressions: `test_structured_intake_review.py` includes both supplied reproductions and profileless
synthetic definition/onboarding with profile review, confirmation, idempotency, edit and HTTP paths; invalid profiles
refuse the whole turn. It covers stale versions/knowledge/sources, question deferral, cross-conversation/forged
sources and modified original sections/provenance. Existing eleven intake tests and documentary profile regressions
remain in the focused checks. Focused correction check: **163 passed** before final verification.

Final verification is pending below. No independent technical re-review or integration is asserted. The owner has
explicitly prohibited commit/merge/push in this correction round. No dependency, schema migration or new inference
launcher was added. The one-off queue is still empty.


### Final correction-round verification

A single, sequential `scripts/check --frontend` on the corrected product/test tree passed:

- unittest: **10 passed**.
- Alembic: **no new upgrade operations** (schema remains `0035_permissions`, 85 tables).
- pytest: **2,829 passed, 2 skipped, 29 subtests passed**, one warning (228.7 s).
- Node: **250 passed**.
- Frontend: **tsc + Vite build passed**.

The warning is the intentional duplicate ZIP member in the synthetic artifact-tampering refusal test,
`test_self_contained_artifact_verifier_rejects_tampering[duplicate]`; it is not an intake failure. This run used
access to local process inspection and temporary sockets from the outset; no restricted-run failure/recheck or
parallel wrapper was needed. Every suite log was preserved before any further check as
`.local/check/p002-t011-corrections-final-{unittest,alembic,pytest,node,build}.log`. The 163-case focused result is
preserved in `.local/check/p002-t011-corrections-focused.log`. The final modified-file SHA-256 inventory is
`.local/check/p002-t011-corrections-tree.json`; these are local evidence, not distributed product artifacts.
OpenAPI and generated client parity used the README commands. Full diff and added files were inspected locally.
Final `scripts/check-docs` and `git diff --check` results are recorded below after documentation closure.

All three technical-review findings are implemented and locally verified; **technical re-review has not yet
passed**. No known source implementation gap remains from these findings. No browser interaction or real
provider/native qualification was performed. T013 export/commit, T016 final readiness and T020 installed
conversion remain outside this task. Knowledge/profile confirmation never supplies their gates implicitly.

Delivery: locally verified source **complete** → develop **pending** → protected-main release 0.2.0 **pending** →
distribution/publication **pending** → installation **pending**. The work stays uncommitted on the existing
`feat/p002-t011-db-intake` branch at base `40027f8490f2d26dd68725739617a4b1d6bdb258`. ONE_OFF_TASKS is still empty.

Final documentation closure: `scripts/check-docs` passed (107 Markdown files, zero errors);
`git diff --check` passed. No product or test changes followed the complete verification run.

## Completion-blocker correction round

The owner confirmed a further P1: a profileless intake could adopt knowledge with `profile: null`, closing
its conversation before any profile could be proposed. Work continues on the existing uncommitted topic branch
and base, preserving the three earlier corrections. This round implements the minimal server-side prevention:
knowledge adoption needs an available valid profile proposal when the frozen context has no selected profile.
Profile confirmation remains separate and may happen before or after knowledge adoption. No post-adoption
inference continuation, implicit confirmation or T013/T016/T020 work is added. Review remains unpassed;
commit/merge/push are prohibited. Delivery stages remain separately pending as recorded above.


### Completion guard and maintained regressions

`intake.adopt` now reconstructs the actual frozen run context. An existing selected profile preserves its
adoption path. For profileless IntakeContext, adoption requires a current same-conversation/same-turn
PROPOSED or ACCEPTED profile passing the existing structured profile preview checks (exact knowledge,
source ledger, candidate, questions, versions and HEAD/inventory). A row alone cannot waive those checks.
The shared adoption transaction refuses with `intake_profile_required` (409) and an actionable en/es
message if no continuation exists; neither accepted knowledge nor a profile confirmation is created.
The conversation retains `created=false` and the message action so the owner can request and stage a
valid proposal. The existing post-adoption guard and `accepted_revision=null` first-turn semantics are
unchanged; no alternative accepted-context inference or knowledge mutation path is introduced.

Both definition and onboarding regressions cover `profile: null`, refused adoption via domain/API,
continued explicit inference with preserved prior sources, stale preview refusal, a later valid profile,
both orders of independent confirmation, idempotent replay and one accepted revision. They assert no
configuration operation, no preparation and no extra queued worker run. Existing selected-profile intake,
profile validation, historical-source and original-instruction tests remain in the focused suite.

No request/response schema, catalogue digest, table or dependency changed in this round. The new typed
409 diagnostic uses the existing generic problem envelope and existing frontend error display; OpenAPI
and client shapes are unchanged. The historical review reproduction is addressed by preventing the
premature adoption, rather than enabling inference after adoption. The full-round results below supersede
prior tree verification; earlier named logs and hash inventories remain unchanged.


### Final completion-round verification

Sequential focused check: **133 passed** across structured intake review/intake, profile proposals and domain
operations; retained as `.local/check/p002-t011-completion-focused.log`. The added six cases exercise the two
entry paths, both confirmation orders and the actual HTTP 409 diagnostic, not only the UI button state.

One sequential `scripts/check --frontend` passed on the final product/test tree:

- unittest: **10 passed**.
- Alembic: **no new upgrade operations**; no model/migration change.
- pytest: **2,835 passed, 2 skipped, 29 subtests passed**, one warning (224.1 s).
- Node: **250 passed**.
- Frontend: **tsc + Vite build passed**.

The warning again belongs to the intentional duplicate ZIP member in the synthetic artifact-tampering
refusal test. Process inspection and temporary local sockets were available for the full run; no restricted
retry or second full suite was needed. Suite logs were copied, sequentially, to
`.local/check/p002-t011-completion-final-{unittest,alembic,pytest,node,build}.log`. No product/test changes followed
that run. The prior correction-round logs and hash inventory remain untouched. Final documentation checks and
`git diff --check` are recorded below; the final SHA-256 inventory is
`.local/check/p002-t011-completion-tree.json` (including log digests).

The complete cumulative diff was inspected, including the intended changed paths relative to the
previous verified tree; other earlier work is preserved. No browser interaction or native/real-provider
qualification is claimed. Independent technical re-review remains pending/unpassed; no commit, merge, push,
integration, release, publication or installation occurred. The next gate is T011 technical re-review, not T012
implementation. Source locally verified → develop pending → protected-main 0.2.0 release pending →
distribution/publication pending → installation pending. ONE_OFF_TASKS remains empty.

Final completion-round closure: `scripts/check-docs` passed (107 Markdown files, zero errors);
`git diff --check` passed. Only documentation closure followed the complete verification run.


## Independent technical re-review and authorized delivery (2026-10-31)

The owner requested technical re-review and, if successful, a brief descriptive source commit with bullets,
merge into develop and push. The complete cumulative diff and prior corrections were reviewed; no relevant
outstanding finding remains. The profileless completion guard now refuses adoption before any accepted
revision is created, retains the conversation for a later valid proposal, and keeps profile confirmation
independent. Both intake paths, both confirmation orders and selected-profile compatibility are covered.

Independent verification: `scripts/check tests/product/test_structured_intake.py
tests/product/test_structured_intake_review.py tests/product/test_profile_proposals.py
tests/product/test_domain_operations.py` passed **133 tests**. The 35 source/document/test files and all five
suite logs matched `.local/check/p002-t011-completion-tree.json` before documentation closure. The preserved
full-run logs confirm **2,835 Python passed, 2 skipped, 29 subtests passed; 250 Node passed; 10 unittest passed;
Alembic clean; tsc and Vite passed**. The known synthetic ZIP warning and build chunk-size advisory do not
represent test failures. The full suite was not needlessly repeated; only status/delivery documentation
changed after these checks. Documentation and whitespace checks are repeated for that closure.

Remote develop was verified at `40027f8490f2d26dd68725739617a4b1d6bdb258` before integration, equal to the
local base. Source commit `616846da8df315110cb64dcfff04de5cbd73442c` was created on the existing
`feat/p002-t011-db-intake` branch and is integrated by the accompanying no-fast-forward merge into develop.
That merge updates current documentation only; its product/test tree matches the reviewed source commit.
The owner authorized pushing develop without force. Documentation closure passed `scripts/check-docs`
(108 Markdown files, zero errors) and `git diff --check`.
No other branch, release, publication, installation or service operation is authorized. The next
implementation task after integration is T012; T013 exports, T016 readiness and T020 installed conversion
remain separate. No browser or real-provider/native qualification was performed.
