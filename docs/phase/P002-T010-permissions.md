# P002-T010 — Permission lifecycle and standing grants

Status (2026-10-30): **source complete; technical re-review passed; source commit authorized; integration pending; G10 A/B/C accepted by the owner**.
The owner accepted §3 recommendations, not their alternatives, and authorized continued local implementation.
G10 is resolved as design; implementation and verification remain separate. See D291.
Sections 5–6 retain the implementation/correction-stage evidence; §7 records the current re-review and source delivery.

## 1. Ownership, minimum contract and delivery

Owner: the repository owner; programmer: this session; subsequent technical reviewer: Codex. These are development
roles, independent of the product's reviewer/executor/judge. Task: P002-T010, dependencies T005/T006/T008/T009 integrated.
Branch: `feat/p002-t010-permissions`, created from locally checked clean `develop`
`c7f35cb4144ee97c5c6b9b83c8d9dc0b168a5a16`, identical to local `origin/develop`; no remote consulted.
One-off queue empty. Local source/document changes and synthetic offline checks are authorized; G10 recommendations A/B/C are accepted.

Minimum delivery contract: five independent dimensions; request/owner response/validated judge proposal consumption;
operation, temporary and permanent grants; deny/escalate/supersede/revoke; persisted authority and frozen effective
snapshots; current authority checks inside command/admission transactions; equivalent-request reuse; guarded owner
inspection and process-stop/reconciliation. No grant bypasses owner-only exclusions or changes a live attempt.
Reuse the domain pipeline, broker, frozen context, operation journal and accounting ledger; no new dependencies,
native judge qualification, scheduler, global inbox or T011–T023 workflow implementation.

Agreed route: **verified source → integration into develop → release 0.2.0 through protected main →
distribution/publication → installation**. Source is completed and technically re-reviewed; the owner authorized
the source commit after a successful re-review. Integration and all later delivery stages remain pending.
No release/publication/installation/service start or real agent/provider execution is authorized.
Operator installation remains 0.1.9. Local source adds `0035_permissions`, 85 tables; no operator migration occurred.

## 2. Code evidence and implementation seams

- [`domain_policy.py`](../../src/my_harness/core/engine/domain_policy.py): `PermissionState` and `evaluate` already
  intersect exact frozen grants with current unavailability and frozen/current four-layer plus role ceilings.
  Missing state denies; accumulated grants cannot satisfy `EXCLUDED`. T010 must supply persisted state and complete
  trusted owner-only classification, rather than relying on model-supplied labels.
- [`domain_operations.py`](../../src/my_harness/services/domain_operations.py): `PermissionProvider.state` reads in
  the command session; `_transaction` takes the write lock before agent reads and reauthorizes command replay.
  [`managed_runtime.py`](../../src/my_harness/services/managed_runtime.py) composes unavailable permissions in both
  domain operations and tool bridges. Both compositions must use the same persisted provider after G10.
- [`judge.py`](../../src/my_harness/services/judge.py): `create` reuses trusted subject/evidence/context identities,
  refuses unresolved inference and requires explicit bounded reconsideration. `await_permission_application` is a
  continuation from a proposal, never authority. T010 must revalidate and consume a ruling once transactionally;
  its trusted equivalence subject must survive rewording/broadening, not derive solely from a new target string.
- [`core permissions`](../../src/my_harness/core/engine/permissions.py),
  [`legacy ledger`](../../src/my_harness/storage/permissions.py) and
  [`Permissions.tsx`](../../frontend/src/Permissions.tsx): run-bound ledger, TTL 1–86400 seconds, `once`/`task`,
  stopped-run version/fingerprint guards and next-executor snapshot consumption. Product/acceptance rows do not
  unlock an executor or commit. Preserve those semantics and historical fingerprints; label legacy provenance,
  never backfill/promote old rows into standing grants or combine both ledgers to widen authority.
- Existing process evidence/stop controls and `ManagedRepository.confirm_stopped` remain the recovery path;
  revocation must persist denial before requesting stop, preserve uncertain effects and never signal an unverified
  persisted PID. Query-only reads must work without checkout/clients and never expire or rewrite history.

Design references: [T001 §§3–4, 7–9 and G10](P002-T001-contracts.md),
[FL04–FL06/FL13](P002-T001-flows.md), [TM01/04/06/07](P002-T001-threat-model.md),
[T005 §5.2](P002-T005-domain-operations.md#52-per-operation-capabilities-and-current-ceilings),
[T008 §3](P002-T008-scoped-tools.md#3-scope-validation-persistence-and-recovery),
[T009 §3](P002-T009-judge.md#3-implemented-local-boundary),
[SPECIFICATION §§5/14](../SPECIFICATION.md), [ARCHITECTURE §13](../ARCHITECTURE.md), D272–D275/D286–D290.
Decision index inspected before allocating D291; the owner explicitly accepted this proposal after inspection.

## 3. G10 — accepted recommendations and retained alternatives

The owner accepted recommendations A/B/C and examples on 2026-10-30; alternatives below were not accepted.

### A. Parent lifecycle and origin

Recommend checking the complete authority ancestry on every use. Normal completion, expiry, supersession or revocation
of a parent makes all dependent grants and child authorizations ineffective, recursively, regardless of duration
(`operation`, temporary, permanent) or child origin. An `owner_confirmed` child explicitly bound to that parent still
depends on it; origin alone never breaks ancestry. Deterministic effects inherit the authority they consume.
Keep records/snapshots unchanged and append the end/revocation evidence; do not resurrect children on a later parent.

An independently confirmed standing grant has its own owner-confirmed permission authorization, not the autonomous
run as parent. It survives run completion/revocation, subject to its own revocation/expiry and current ceilings.
No delegated grant is silently converted to this independent form. A fresh owner preview may create a replacement
with independent authority and a supersession/provenance link. Completed effects are not undone; future commands
and admissions deny, and an affected active writer is stopped/reconciled even on normal parent end.

Example: authorization A delegates permanent access to `src/a.py`; grant G and child authorization B cease to work
when A ends, even if G has no timestamp expiry. Independent owner grant H for the same file survives A. A command
serialized before revocation may finish; commands serialized after it deny, and native in-flight effects can remain
uncertain. Per-operation grants bind one logical operation identity, with atomic consumption and idempotent replay;
a second operation cannot consume them. Temporary validity uses an exclusive expiry boundary (`now < expires_at`).

Alternative: delegated permanent grants survive normal completion but not revocation of A. This reduces repeated
approvals across runs, but leaves lasting delegated authority after its originating run ends and needs an explicit
survival tier and distinction between ending and revoking. Recommendation favors one auditable ancestry rule;
permanence removes time expiry, not authority dependencies.

### B. Permanent permissions in manual mode

Recommend allowing independent permanent grants only through an exact owner preview with an explicit permanent
selection (no default), project/role/dimension/targets/purpose, policy version, reason and fresh version/hash guards.
Display origin, parent/dependency, no-expiry status, effective restrictions, supersession and revoke controls in
project permission inspection; show applicable grants and denials at each new attempt/start preview. Changed
responses are stale and refused. Manual requests always go to the owner; no judge delegation is enabled.

Reuse an eligible standing grant automatically only in the next frozen attempt/boundary, while keeping existing
explicit confirmations and content/authority guards for execution, adoption, acceptance and mechanical effects. A stored capability never
confirms future content. Example: permanent tool permission for one validation argv avoids another identical
permission question on the next task; it does not start that task or accept its output. Narrowing ceilings blocks
use immediately; a later widening requires a fresh snapshot. Revocation does not rewrite older snapshots.

Alternative: require reconfirming the permanent grant at every manual start. This adds an approval click and makes
reuse easier to overlook, but gives a fresh explicit permission choice each time. Recommendation keeps that choice
at grant creation and presents reuse visibly alongside the still-required action confirmations.

### C. Typed exact targets, comparison and equivalence

Recommend a versioned canonical target envelope, dimension-specific, bound to persisted project identity and role.
Keep submitted spelling as audit evidence; compare canonical serialized values, never display strings, substrings,
glob matches or model assertions. Existing `domain:<id>@<version>` and product capability tokens remain exact
catalogue tokens; adapt to their existing string requirements without rewriting historical catalogues/digests.

| Dimension | Proposed representation and rejection rules | Concrete examples |
|---|---|---|
| `files` | Registered root identity + exact root-relative POSIX path + operation. Permit harmless repeated `/` and `.` component collapse; reject empty/root targets, absolute paths, `..`, backslashes, control characters, glob syntax and symlink components. Preserve case and Unicode bytes; require actual filesystem spelling and reject observed case/Unicode aliases instead of silently merging. For creation verify existing ancestors and exact intended final name. Recheck containment/links at use; retain task/profile sensitive and protected-path checks. | `src//./a.py` equals `src/a.py`; `src/../secret`, `SRC/a.py` aliasing `src/a.py`, and a link into another root are refused. Same path in projects P and Q is never the same authority. |
| `tools` | Tagged catalogue ID/version/schema identity **or** resolved absolute executable identity (real path + content digest), root-relative cwd, argv as an ordered vector and explicit environment binding. No PATH lookup at use, shell-string parsing, expansion or quoting normalization. Use an argv prefix only with an explicit closed suffix rule; initial minimum is a full vector with empty suffix. Reject arbitrary shell/interpreter/code-evaluation targets and undeclared environment/arguments. Recheck executable drift. | `domain:knowledge.lookup@2` differs from version 1. `['pytest','-q']` differs from `['pytest','-q','--plugin=x']`; changing executable bytes invalidates the target. Granting a command still does not grant its files/network/product effects. |
| `network` | Explicit scheme + DNS ASCII A-label or IP literal + numeric port; lowercase scheme/DNS, canonical IPv4/IPv6, explicit default port. No DNS resolution as equivalence: names and IPs remain distinct. Reject userinfo, wildcards, URL paths/query/fragment, percent escapes, zone IDs, trailing-dot names, non-ASCII host input and noncanonical numeric-host spellings. Redirects require separate destination authorization. | `https://EXAMPLE.test` equals `https://example.test:443`; HTTP, port 444, an IP address and another host are different. `127.1`, `user@host`, `host/path` and `*.test` are refused. No private/public-address exemption is inferred. |
| `product` | Exact catalogue capability token plus project/domain entity identity and accepted revision or sealed preview binding where content-specific; verify membership server-side. No free-text/fuzzy equivalence. Owner-only classification still precedes grants. | `knowledge.propose:task` differs from `knowledge.adopt:planning`; a requirement-meaning change cannot be laundered through either or through multiple grants. |
| `acceptance` | Exact action token + task/domain revision + code-content/acceptance evidence identity. No wildcard or generic “accept all”; no delegated acceptance override. Permission never constitutes actual acceptance or READY. | Acceptance evidence for tree X never applies to tree Y; a tool grant plus a product grant cannot accept either tree. |

Request identity includes project, role, dimension, sorted/deduplicated canonical targets, purpose **class**, duration,
parent/revision and policy version; evidence/context digest is separate. A stable service-derived blocker/subject
groups equivalent, rephrased and broadened requests using T009's trusted subject. Changing prose, target spelling,
duration or adding a target is not new evidence and cannot evade a denial or trigger another inference. Fresh
authority/expiry is still checked when reusing an outcome; an old ruling is never a new grant. New evidence needs
explicit reconsideration under the supplied bound, with no T016 defaults, hidden retries or new accounting entry
for reuse. Exact equivalence is distinct from this broader no-progress lineage.

Alternative: accept loosely normalized strings, resolve filesystem/DNS aliases or allow unconstrained argv prefixes.
This is more convenient but creates authority aliases, ambient PATH/DNS dependencies and argument escalation.
Recommendation rejects unsupported/ambiguous inputs rather than guessing intent. Cooperative containment remains;
these checks do not claim operating-system isolation or elimination of filesystem/native races.

## 4. Implemented local boundary

G10 was the only design blocker; the owner accepted A/B/C and authorized continuing this same local task.
Migration `0035_permissions` adds `permission_records` and `permission_boundaries` (85 tables), with six immutable
triggers and no legacy backfill. Records represent authorization, request, response, grant, end/supersession,
frozen snapshot and operation consumption; hashes, project sequence and stable keys preserve audit and recovery.
`PermissionLifecycle` supplies the persisted provider to both runtime domain operations and tool bridges. Its
trusted authorization/prepare/seal/consume interfaces serve later consumers without implementing their workflows.
The runtime's native judge qualification remains unchanged and productive delegation still has no default provider.

Owner API controls use additive `permissions.inspect/request/preview/respond` catalogue entries through the existing
DomainOperations transaction, idempotency, catalogue and trace pipeline. Inspection by persisted project ID serves
archives. The project UI shows requests, origins, ancestry, durations and revoke/response previews; duration requires
an explicit selection, including permanent. Existing action/content confirmations remain. Source-attempt settlement,
record revision, preview hash, current authority and canonical identity guard owner answers.

Targets normalize through `core/engine/permission_targets.py`; raw submitted targets and canonical values are retained on permission records;
the domain command preserves its request fingerprint. Catalogue tokens preserve existing versions/digests; exact file-operation,
executable/argv/environment and network targets use versioned digest tokens. Product targets verify persisted
project/entity/revision membership; their effective command scope currently supports project-wide capability groups
at the caller's exact frozen revision. Finer entity-specific grants are retained but do not broaden a group operation.
Acceptance targets remain owner-only and never bypass acceptance/READY. There is no new arbitrary native command,
network or file-effect tool; later consumers must use the existing protected file/native effect boundaries.

New snapshots contain only currently eligible grants within frozen/current ceilings. A marker seals the snapshot
with the native attempt/usage/context/operation transaction; per-operation consumption rolls back with admission.
Current expiry/ancestry/revocation/ceilings are rechecked on each mediated command, including outcome replay.
T009 ruling application is explicit, revalidates stored policy/input/evidence and current scope, and deduplicates
concurrent consumers without another inference/usage row. Manual requests never delegate; service-bound equivalent
requests reuse prior outcomes. Existing T009 explicit reconsideration/no-progress bounds remain unchanged.

CLI/native-command cancellation reads persisted end/expiry/ceiling evidence through the existing journal. Only the
adapter's live handles are stopped; normal native capture/settlement/recovery preserves uncertain effects and does
not retry inference. Legacy run grants, TTL, scopes, frozen histories and adapter flags stay separate; no legacy
row becomes new authority. Query-only inspection does not require a checkout and never rewrites expiry.

## 5. Verification and delivery

Synthetic tests cover exact/adversarial paths, links/case aliases, executable identity/argv/drift, network identity,
manual permanent and temporary lifetime, parent cascade and independent grants, stale responses, supersession,
dimension/compound checks, frozen snapshot/current ceilings, failed admission rollback, concurrent ruling/owner
consumption, serialized revocation, query-only backup inspection and immutable evidence. Positive judge rulings are
explicit synthetic fixtures; fake-process checks exercise existing cancellation without native qualification.
The initial restricted check could not bind AF_UNIX channels used by fake processes; the authorized local retry
resolved those environment failures. An actual port-zero normalization defect and additive-catalogue expectations
were corrected after inspecting logs. A mistyped test path ran no tests and was corrected. No provider ran.

Executed checks (all offline, synthetic):

| Check | Result |
|---|---|
| Initial required focused permissions/domain/judge/bridge paths | Restricted AF_UNIX failures; after local access, 294 passed and three additive-contract expectations failed; expectations corrected |
| Expanded focused permissions/domain/judge/bridge/context/journal/commands | 403 passed |
| One general `scripts/check --frontend` | unittest 10 passed; Alembic no drift; pytest 2759 passed, 2 skipped, 29 subtests passed, 2 failed, 1 warning; Node 250 passed; build failed on import case |
| General-run corrections | Updated 85-table metadata expectation; localized target/archive diagnostics in en/es; corrected `workspace` import case |
| Focused correction check | 95 passed |
| Final expanded focused paths, including configuration and service-text parity | 469 passed |
| Last adversarial targets/identity and nearby domain/service-text tests | 82 passed |
| Final frontend build (includes tsc) | Passed; existing large-chunk advisory remains |
| `scripts/check-docs` plus explicit new record/flow paths; `git diff --check` | Passed; new untracked source also checked with Git's no-index whitespace check |

The general suite was run once; after inspected failures, only affected checks were repeated. No second full-suite
pass is claimed. Native judge qualification, real providers, installed-package/operator migration and browser
interaction/accessibility were not tested. The two general skips remain unqualified; positive judge application
uses persisted synthetic ruling fixtures, and process cancellation uses a fake CLI. No harness/service was started
on this repository. ONE_OFF_TASKS remains empty; no commit/merge/push/global configuration/network installation occurred.

Local source is ready for the requested subsequent technical review; this session reviewed the diff, not an
independent reviewer approval. Integration into develop, protected-main 0.2.0 release, distribution/publication and
installation remain pending and unauthorized. Product graphs, finer entity-specific product effect consumers and
new arbitrary native/network/file effect tools remain outside this task; existing guarded paths and later-task
interfaces retain those responsibilities. Native containment remains cooperative and in-flight effects can remain
uncertain. G10 has no pending owner decision.

## 6. Technical review corrections — owner-only tools, inherited tiers and post-executor revocation

Owner-authorized local corrections in P002-T010 on the same uncommitted branch from `c7f35cb`; G10 A/B/C and
D291 stay accepted. The three blocking findings were reproduced by independent synthetic probes retained at
`/private/tmp/p002-t010-review/test_t010_review.py` (auxiliary only). Regression coverage now lives in
`tests/product/test_permission_review.py`. Source/review/integration/release remain separate; commit, merge and
push await successful re-review. The agreed delivery route in §1 remains unchanged. This section records corrections, not a successful re-review.

### 6.1 Owner-only classification at authorization and consumption

Defect: `owner_only` omitted tool targets, allowing a synthetic Git-push identity and a permissive policy/candidate
to yield an `owner_delegated` grant. Correction: catalogue tools are classified from exact service-owned entry
identity/schema and permitted principals; owner-only catalogue controls stay owner-only. An opaque native
executable's path/content digest/argv proves identity, not absence of secrets, publication, destructive Git, policy
changes or other owner-only effects. Such targets therefore cannot be delegated. This is a conservative refusal
of unverified effects, not an executable-name denylist or a containment claim; renamed programs and wrappers get
the same treatment. Existing exact owner-authorized native validation/formatter commands keep the independent
ManagedCommandRunner route, trust/profile/environment/file/network controls and explicit confirmation requirements.
No native target representation, catalogue digest or historical permission record is rewritten.

Authorization admission refuses these targets in delegated scopes; current ancestry validation also invalidates
previously persisted unsafe delegated authority before ruling consumption, snapshot use or admission. Ruling
consumption retains its own target classification check. Regressions exercise synthetic push/destructive Git,
publish/deploy/install, credential/global-config and policy-edit argv, including unrelated wrapper names. They
reach the consumer using synthetic pre-correction persisted authorizations/requests and VALIDATED T009 proposals,
and assert no forbidden grant. A legitimate catalogue permission still consumes successfully; native command
regressions preserve valid owner-authorized execution. No Git/native capability is inferred from model labels.

### 6.2 Descendants cannot promote active scope into the delegable tier

Defect: child targets were checked against overall parent scope, but child `delegable` could promote a target absent
from the parent's delegable set. Correction: each dimension's child set must be a subset of the parent's set.
The shared inherited-bound comparison also narrows duties, duration, reconsiderations, admissible alternatives,
intent references and effective-grant evidence, preserves policy identity/revision and cannot turn inactive or
unsafe compound evidence into eligibility. Existing project/role/purpose/target checks and recursive expiry/end
rules remain. Current ancestry rechecks the same restriction, so an old widened child cannot feed a ruling.
Tests cover each widening, valid children/grandchildren and rejected re-expansion; independent owner-confirmed
authority retains its own lifetime as D291 requires.

### 6.3 Commands retain their source authority after executor settlement

Defect: `cancelled()` filtered out attempts with a persisted result, losing the authority consumed by subsequent
format/validation stages. Correction: at `command_started`, the existing fenced event records the current executor
attempt identity as `permission_attempt_id`, including a settled executor. Command checks resolve that pinned
attempt/boundary; they do not scan or union historical snapshots. Before the command intent commits, the write
transaction rechecks that same authority. Before spawn and during the process loop, the runner asks the journal
about the command ID. New executor stages use their new authority, while already-started commands never silently
rebind. An unmarked current legacy attempt does not inherit an older revoked boundary. No schema/API or frozen
snapshot change is needed; historical command events remain unchanged.

Tests settle an executor, then revoke and assert no native launch; revoke during a synthetic command and assert
live-handle stop, capture and one retained usage intent; race revocation against intent admission; and prove a new
valid executor (or current legacy executor) is not indefinitely cancelled by an older revoked grant. Existing
process/journal recovery preserves uncertain effects and never relaunches automatically.

### 6.4 Correction verification

Initial required focused check: 296 passed, 45 failed. Logs showed 44 AF_UNIX channel failures caused by restricted
local socket creation and one new test fixture incorrectly reusing a sealed legacy snapshot. The fixture now
requests a fresh legacy snapshot at the new admission; production guards were preserved. With authorized local
channels, the same focused paths passed (341 tests); the next expanded check passed 344 tests. Final review-only
regressions passed 34 tests before closure. The single general closure `scripts/check` passed unittest (10) and
Alembic (no drift), then reported 2677 pytest passes, 122 failures, 2 skips, 29 passing subtests and one warning.
The failures were in eight preparation/configuration/journey files: the modified shared runner passed a command ID
to `PreparationCommandRunner.cancel_requested()`, whose existing separate-authority hook takes no arguments.
After inspecting the log and subclass, the runner now uses a separate private command-specific check and preserves
the argumentless fallback. A regression exercises the real preparation runner with its separate journal. All eight
failing files plus permission lifecycle/review, domain, judge, CLI and command paths were rechecked: **612 passed,
2 skipped** (104.2s), including the 35 new parametrized correction cases. The general suite was run once; its
122 failures are recorded as failures, followed by the successful targeted correction check, not relabelled as a
full-suite pass. The general failure log is retained locally as
`.local/check/p002-t010-corrections-general-pytest.log`. No frontend was modified by these corrections; the earlier general run with failures
in §5 is historical and is not presented as a successful closure.

The four retained auxiliary review reproductions also passed via `scripts/check` (4 passed, 1.2s).

Correction closure: source/diff inspected; `scripts/check-docs` passed for 105 tracked Markdown files and the two
new record/flow files explicitly; `git diff --check` and new-file whitespace checks passed. Changes
remain uncommitted for technical re-review. No new schema/migration, API/client contract, catalogue/fingerprint,
frontend, dependency or message key was needed for these corrections. The original uncommitted T010 work is
preserved. Data/flow parity for the additive command event reference is documented in the permission flow;
existing histories/snapshots are not rewritten. G10 is not reopened. No provider/service/harness or operator
installation was run. Native qualification, real-provider/installed-package validation and successful re-review
remain absent. Native containment remains cooperative; opaque native effects are owner-only, while the existing
owner-authorized command path and independent dimension checks remain in place.

## 7. Independent technical re-review and authorized source commit

Codex re-reviewed the complete T010 diff and the three corrections on 2026-10-30. The original four independent
reproductions and the repository's permission lifecycle/review suites pass together: **78 tests**. Tool classification
now refuses opaque native delegation and uses verified catalogue entries; descendant delegation stays within inherited
tiers; postprocessing commands retain their own source boundary after executor settlement, without inheriting older
revocations. No outstanding relevant finding remains. No product source was changed during this re-review.

One general `scripts/check --frontend` passed unittest (10), temporary Alembic upgrade/check, Node (250) and
TypeScript/Vite build. Pytest passed **2677 tests**, with **2 skips**, **29 passing subtests** and the existing synthetic
duplicate-ZIP warning; **97 failures and 26 setup errors** were caused by restricted local socket/process access.
The log was inspected and retained at `.local/check/p002-t010-rereview-restricted-pytest.log`; a direct disposable
AF_UNIX probe also reproduced `PermissionError`. Only the four affected files (`test_cli_diagnostics.py`,
`test_tool_bridge.py`, `test_judge.py`, `test_start_command.py`) were repeated with authorized local socket/process
access: **311 passed**, retained at `.local/check/p002-t010-rereview-local-pytest.log`. This is a general run plus
successful targeted environment retry, not a claimed single unrestricted full-suite pass. No tests or product
guards were weakened to bypass the restriction.

The exported OpenAPI matches the current application source; regenerating client types to a temporary file produced
identical bytes. Documentation/English-Spanish/schema parity and diff whitespace checks pass. The final staged diff,
including new files, is reviewed before the commit. ONE_OFF_TASKS remains empty. No browser/native-provider
qualification, installed-package/operator migration, service or harness execution was performed; earlier limitations
remain explicit. G10 and D291 are unchanged.

The owner requested a source commit if this re-review passed. The accompanying source commit contains T010,
the corrections, regression tests and this review evidence on `feat/p002-t010-permissions` from `c7f35cb`.
Integration into `develop`, push, protected-main release 0.2.0, distribution/publication and operator installation
remain unperformed. The next implementation task is T011; it is not started by this source delivery.
