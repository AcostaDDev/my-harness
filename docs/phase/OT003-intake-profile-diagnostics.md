# OT003 — Intake profile rejection diagnostics

Completed in source on `fix/intake-profile-diagnostics`, 2026-10-27; **delivery pending**. Decision:
[D241](../DECISIONS.md#d241--actionable-intake-profile-rejections). This is a bounded correction outside P001,
assigned its own **0.1.4** patch. D242 records the owner's requirement to track source and delivery separately;
OT003 remains in ONE_OFF_TASKS until that delivery is completed or explicitly deferred.
The owner later extended OT003 with the adoption blockers found during manual testing (D244); that follow-up
is also implemented/tested, not installed by this work. No version bump, commit, installed-service upgrade,
restart, provider call, push or release was performed by this agent. A subsequently inspected operator turn used
the initial OT003 prompt/failure context; this does not establish full installed-distribution qualification.

## Problem and correction

An intake reviewer could copy operator-supplied installed paths into command `argv[0]` and `tools.name`, despite the
existing strict profile contract requiring logical aliases. Container-internal executables could also be listed as
additional direct tools. The normal parser rejected these proposals, but the outer validator replaced its error
with a generic invalid-profile message. A later reviewer received the previous turn's FAILED status without its
recorded reasons, making repeated invalid proposals harder to correct. The conversation rendered rejected document
lists under the same proposed-draft label as valid ones, although no proposals were created from those failed turns.

- The profile validator identifies invalid logical executable names in preparation, validation, prefix and formatter
  slots before the unchanged normal parser. Diagnostics include only a generated structural field/index, never a
  candidate name, installed path, argument, environment or body. It does not normalize or accept invalid candidates.
- Both current built-in intake prompts explain the existing alias syntax, private executable-path mapping and exact
  direct-tool membership. Nested/container tools belong in the direct tool's requirement, not extra `tools` entries.
- New planning contexts include the previous turns' recorded `reasons`. Failed output remains excluded from valid
  prior answers/proposals; previous requests, histories and frozen catalogs retain their original bytes.
- Rejected document lists now explicitly say they cannot be applied, in English and Spanish. Earlier valid proposals
  remain available under their existing review/CAS controls. No automatic retry or fallback was added.

No API response fields, operational schema or stored formats changed. The adoption follow-up updates descriptions
of `ProfileProposalPreviewRead.blockers` and `ready`; OpenAPI and generated client type comments were regenerated.
The added previous-turn field is internal frozen agent context for new requests. Current built-in prompts acquire
new content-based identities; stored prompt versions/catalogs are not edited.

## Validation

Only synthetic fixtures, temporary repositories/SQLite and fake agents were used for regression checks. A separately
requested local incident was inspected read-only to establish the cause; its contents, identifiers and project paths
were not copied into fixtures or this artifact. An in-memory validation of the returned candidate established the
alias/direct-tool mismatch without executing any proposed command or changing persisted records. Passing structural
validation does not qualify its technical preparation, dependencies, containers or business documentation.

- `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q tests/product/test_profile_proposals.py tests/product/test_prompts.py tests/product/test_service_texts_catalog.py`:
  **85 passed**. Covers both intake kinds, all four command slots, bilingual safe diagnostics, nested container tools,
  failed-turn feedback followed by a valid turn, unchanged failed history, no retry, and prompt/catalog compatibility.
- `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q tests/product/test_definition.py tests/product/test_onboarding_conversation.py tests/product/test_profile_preparation.py`:
  **116 passed**. Existing FastAPI test-client deprecation warnings in both pytest invocations.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: **10 passed**.
- `node --test frontend/tests/*.test.mjs`: **188 passed** before the two new rejection-label cases;
  `node --test frontend/tests/question-answers.test.mjs`: **13 passed** after adding those cases (en/es).
  Final `node --test --test-reporter=dot frontend/tests/*.test.mjs`: **190 passed**.
- `npm --prefix frontend run build`: TypeScript check and Vite build passed; existing large-chunk advisory.
- `git diff --check` passed; reviewed product changes and current documentation. Initial source completion
  prematurely emptied the queue; the follow-up under D242 restored OT003 delivery, followed by OT004, before P001-T001.

Not run: full Python regression suite, a migration check (no schema change), visual QA of the modified UI, installed
wheel qualification or any real reviewer/preparation/project command. Inspection of the running UI diagnosed its
existing behavior only; it does not count as visual QA of the changed source. No network installation/dependency change.

## Operator continuation

A failed turn remains failed and cannot be converted into success by editing its stored output. Existing answered
proposals are not lost. An explicit new message can request the corrected candidate with logical executable aliases,
exact direct-tool membership, and documents consistent with those commands, while retaining already supplied answers
and all isolation/offline conditions. This instruction works with the currently installed service as well; installing
this source correction is not a prerequisite for expressing the corrected contract in the next message.

After an ANSWERED result, review and apply each intended document proposal to the private draft area, then review and
adopt the exact profile proposal. Documentary preview/confirmation adopts P001 with its commit. Private tool-path
configuration, preparation and activation remain later, separate confirmed steps. Applying a private document draft
alone does not complete onboarding or execute project code. Do not apply older command documentation blindly when a
new proposal changes the intended environment. Open questions are derived from the latest answered turn, so rejected
answers do not close the previous questions. The correction does not bypass any of these gates.

## Ownership and delivery follow-up

All product changes in the current working diff belong to OT003: profile diagnostics, both intake prompts,
previous-turn failure feedback, the rejected-document label and their tests. Current docs/flows describe that fix;
D242 and the OT004 task/D243 record the owner's subsequent governance and priority choices. They add no OT004
product behavior. No unrelated Metrics Records implementation is present.

The agreed route is `fix/intake-profile-diagnostics` → `develop` → a separate 0.1.4 release PR/merge into `main`
→ verified package/distribution. Release-wide regression/qualification, version/changelog/package preparation and
integration remain pending. No commit/merge/push/publication or local installation was performed or authorized by
recording this target. The owner chose OT004 as the next separate 0.1.5 patch, before Metrics Records; its contract
lives in ONE_OFF_TASKS and implementation belongs on a separate topic after OT003's delivery.

The follow-up changed only governance/task/status documents and AGENTS instructions. Validation: compared the
current diff to the task scope and existing configuration editors/parsers; checked local document links and
`git diff --check`. Product tests above were not rerun for documentation-only changes.

## Owner-approved adoption follow-up (D244)

The owner included this second onboarding blocker in OT003 before commit. Reproduction used synthetic Go intakes
for both definition and onboarding, temporary SQLite/Git, and fake reviewers. No private proposal content or run
identifiers were added to fixtures. The eight new regression cases failed against the previous implementation and
passed after the correction.

- `pending` notices remain visible/recorded but no longer block profile adoption. Open blocking questions still
  block; explicit reasoned deferrals now satisfy the same rule used by documentary acceptance.
- Missing bound document paths tell the operator to review/apply document proposals to drafts first. Changed or
  extra admitted paths are reported separately. Invalid/foreign drafts retain the existing guard.
- Candidate revalidation occurs only against the exact complete applied documentary base. Missing/changed
  evidence no longer adds a misleading invalid-profile error. No hashes are rebound and the proposal is not repaired.
  Confirmation rechecks documents, context/version, HEAD/inventory and candidate validity against the exact preview.
- The existing UI explains the order: apply document proposals, then review/adopt the saved profile; save a new
  profile draft only after editing. An unchanged form disables redundant profile saves. A confirmation checkbox
  cannot override a blocked preview; a new conversation version needs a fresh preview and confirmation.
- API descriptions, OpenAPI/client comments, specification and affected flows are updated. No migration or new
  response field is needed. Existing turns, questions, notices, proposals and configuration data remain untouched.

Follow-up verification:

- New regressions alone: **8 failed before / 8 passed after** (missing/partial/changed applied documents, bilingual
  diagnostics, informational notices and explicit deferral, for both intake kinds).
- Profile/proposal, definition, onboarding-conversation, profile-preparation, service-text and prompt suites:
  **209 passed**. After adding the edit/adoption cases and strengthening the HTTP document/notice journey, the
  final profile-proposal suite passed **59 cases**, including those additional cases. No product code changed
  between these two successful runs.
- `node --test --test-reporter=dot frontend/tests/*.test.mjs`: **192 passed**; includes en/es profile preview tests
  that keep adoption disabled with document blockers, invalidate the old preview after document application and
  confirm only the new ready preview/hash/version. Editing/previewing starts no preparation or activation.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: **10 passed**.
- OpenAPI export and `npm --prefix frontend run generate:types` passed offline; generated changes are descriptions
  only. `npm --prefix frontend run build` passed (typecheck and Vite; existing large-chunk advisory).
- Reviewed the product diff and document links; `git diff --check` passed. Existing FastAPI test-client deprecation
  warnings remain. Full Python release regression, visual/browser QA and installed-wheel qualification were not run.

No service was installed/restarted and no operator document proposal/profile was applied or adopted. For a manual
retest, load the updated source/service, review/apply the existing document proposals to private drafts, then obtain
a fresh profile-adoption preview. The existing successful reviewer turn can be retained: informational notices no
longer require another generation. The documentary tree/commit, private TOML, preparation and activation remain
separate operator confirmations. OT003 stays in the queue for its 0.1.4 delivery; OT004 stays planned for 0.1.5.

## Owner-approved joint document review (D245)

The owner included joint review/application of document proposals in OT003 before commit. `ProposalBatch` is mounted
on the onboarding and definition conversation pages. It displays current draft-proposal diffs (complete before/after
text when the diff is oversized), allows exclusions, and resets consent when selection changes. A changed conversation
invalidates the review. Profiles, plans, history, closed work and queued turns are excluded.

The read-only review and application orchestration live in `frontend/src/proposal-batch.ts`; no new endpoint or
stored state was introduced. Before applying, the client rereads the exact conversation/proposals and all selected
document bases. Existing apply actions run sequentially with exact proposal hashes and the reviewed version advanced
only by own acknowledged writes. Stops show acknowledged applications separately from any unconfirmed item and
unattempted documents. There is no automatic replay, rebase, rollback or claim of batch atomicity. Reload consults
the persisted per-document statuses, including a write whose response was lost. Profiles and commits retain their
separate controls and gates.

Verification after the joint-review change:

- `node --test --test-reporter=dot frontend/tests/*.test.mjs`: **203 passed**. The 11 new synthetic batch tests cover
  filtering, read-only review, exclusions, exact hashes/versions, pre-existing conflicts, conversation/proposal/draft
  drift, a conflict after one application, lost responses, concurrent versions, one UI consent in en/es, consent reset
  after selection changes and double-click suppression. No model, real service or operator data was used.
- Related profile/proposal, definition, onboarding, profile-preparation, service-text and prompt suites: **211 passed**.
- `npm --prefix frontend run build`: typecheck and Vite passed; existing large-chunk advisory.
- Reviewed the diff and current task routing; `git diff --check` passed. Full Python release regression and visual
  browser/accessibility QA were not performed. The automated component checks are synthetic React server renders.

The owner explicitly requested reinstalling/restarting the local service after checks and stopped it in their
terminal. Pre-upgrade checks found no service/start process, all six jobs DONE, all recorded processes STOPPED, zero
checkout locks and zero reserved preparations. No document/profile adoption or real agent invocation is authorized
by the reinstall/restart. The installation result and preservation checks are recorded below after execution.

## Authorized offline installation and restart result

At the owner's explicit request, ran `scripts/install --clone "$PWD" --upgrade --writers-stopped --offline` after
verifying the service/writers were stopped and the queue idle. The retained installation/data/configuration/cache
locations were unchanged. The new generation `gen-495b3a1b4a3949c69cd3e83a16789de7` is READY, with source fingerprint
`291ab32cbb7b91f0a5b482efe179395b05a918cb9fec70608e380dfbc97604ac` and network disabled. The prior generation
was retained. Package metadata is still 0.1.3 with these uncommitted local changes; this is not the planned 0.1.4 release.

The installer rebuilt/checked exact artifacts and SHA256SUMS, ran isolated installed-wheel checks with synthetic
service/agents (UI/assets/API/session, definition/task/commit/restart, errors and restored evidence), and passed
`uv pip check`. No database migration was needed or run. Started `scripts/start --port 8013` detached with a private
0600 log and normal new session key. HTTP root returned 200; the installed planning source matches the checkout and
packaged JS contains the joint-review UI. No login key bytes were logged in this artifact.

Before/after canonical row hashes match for the requested conversation, all 33 proposal/history records, its empty
import-operation set and configuration revision references. The combined hashes of private TOML bytes/paths also
match. All six existing jobs remain DONE. No document/profile was applied/adopted, no new real provider invocation
was started, and no commit, merge, push, tag or publication was performed. The service is running on loopback 8013;
the operator must sign in again with the new key and explicitly review/apply their proposals.

Task docs now distinguish local installation from the still-pending 0.1.4 release. Final document links/catalog
parity and `git diff --check` were checked. Full Python release qualification and browser/accessibility QA remain
pending; isolated installed checks and automated component/request tests are not presented as those checks.

## Authorized 0.1.4 release preparation

The owner explicitly requested the repository commit, distribution, release PR to main and GitHub publication.
Prepared the shared 0.1.4 version in Python/API/UI metadata and lockfiles, regenerated OpenAPI/client types and
updated CHANGELOG plus English/Spanish download instructions. No dependency version changed. OT004 remains
planned, outside this implementation and delivery.

`build_distribution.py --offline` built the candidate under `.local/releases/ot003-0.1.4-candidate`.
`check_distribution.py --cache-dir .local/uv-cache` passed exact member/metadata/license/checksum checks and the
isolated installed-wheel UI/API/session/definition/task/commit/restart/error/restored-evidence journey. Node is not
needed by that installed service. Final publication artifacts will be rebuilt/verified from the release merge;
this candidate is not published as if it already came from main.

Additional checks: frontend suite **203 passed**; typecheck/Vite build passed (existing large-chunk advisory);
unittest **10 passed**; Alembic upgrade-to-head/check against a fresh temporary synthetic SQLite database reported
no new upgrade operations. Local links/shared-version parity and `git diff --check` passed. Full pytest result and
GitHub publication evidence are recorded below when those operations complete. No fresh browser/accessibility QA
or real provider validation was added to the previously documented scope.

Final pre-integration regression: `UV_CACHE_DIR=.local/uv-cache uv run --frozen --offline pytest -q` completed with
**2095 passed, 2 skipped, 29 subtests passed, 0 failed** in 253.72 seconds. The 11 warnings are the existing FastAPI
TestClient deprecations and the intentional duplicate-ZIP-member tampering fixture. Only current task/release files
were staged; frozen histories, catalogs and recipe sources were not rewritten. The release keeps schema 0027 and
all prior configuration formats.
