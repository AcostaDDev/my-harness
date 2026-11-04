# P002-T017 — Global inbox and guarded shortcuts

## Ownership and delivery

P002-T017 owns the inbox and reusable conversation panel under D278 and D297. Topic
`feat/p002-t017-global-inbox` starts from `develop` at `9e8995b`. The one-off queue is empty.

Minimum contract: bounded global and per-project views of committed, deduplicated owner requests,
stable references, durable read state distinct from domain resolution, and query-only archive reads.
Responses use ordinary guarded controls with current authority, revision, readiness and explicit
confirmation as applicable. Autonomous answer and resume are distinct. The reviewer chat remains separate.
T018 owns the map, bubbles, contextual chat and graphical traces. OS delivery, T019 accounting and T020
installed migration qualification are outside this task.

G13 was accepted by the owner on 2026-11-04 ([D302](../DECISIONS.md#d302--g13-inbox-notifications-and-guarded-shortcuts)).
Task completion and phase closure are notifications. Current permission and blocking-question requests use the
ordinary guarded controls, with autonomous answer and resume kept separate. Lifecycle items link to existing
controls for current evidence and state. Judge escalations open read-only evidence. The owner explicitly deferred
direct judge answers until a command with authority over the blocker is agreed.

| D242 stage | Status |
|---|---|
| Source | Complete and locally verified. Uncommitted for owner diff review. |
| Integration | Pending in `develop` |
| Release | Pending 0.2.0 via protected `main` |
| Distribution/publication | Pending |
| Installation | Pending; recorded installation 0.1.9 |

## Implementation and evidence

The [global inbox flow](../flows/global-inbox.md) records each source and its resolution rule. Schema
`0039_inbox_read_marks` adds one table (94 total) and source indexes. Source events and histories are unchanged.
The API and generated client expose the scoped list, item and first-read receipt. The autonomous run status and
revision preview are addressable by exact run ID. A task clarification also exposes a separate, confirmed retry
using its exact resolution ID and the current run version. The revision preview includes the shown run version in its
hash. Standing responses recheck service readiness inside the command transaction. Autonomous answers recheck
the accepted revision and authority under the writer lock. Stopped-writer recovery settles the journal, graph
thread and run state in a single transaction.

| Coverage | Synthetic evidence |
|---|---|
| Manual facts, repeated commit delivery, phase trace mirror, pagination and project isolation | `test_inbox.py` follows real task acceptance and a structured phase check and closure. The old READY proof is refused, and only the confirmed closure produces a notification. |
| Read versus resolved, restart and query-only restore | `test_inbox.py` repeats a receipt, answers a separate blocker, restarts the API, then queries a restored file and checks its byte hash. Both the receipt mutation and ordinary phase answer return 409 on the archive. |
| Scoped actions, expiry and local HTTP protection (TM13, TM17, TM18) | `test_inbox.py` covers missing session and CSRF, foreign Host/Origin, foreign project and cursor, expiry, replay, masked credential-shaped question text and bounded filters. `test_managed_api.py` verifies typed task gaps and exact proof reuse. |
| Standing permissions and judge evidence | `test_permission_lifecycle.py` exercises current preview, stale revision, readiness refusal, confirmation and idempotent replay through HTTP. `test_judge.py` checks the exact ruling and shows that a linked decision, opening the item and a read receipt leave the escalation unresolved. A manual `blocked_check` escalation of a structured BLOCKED check stays open until a later READY check supersedes it, and remains resolved after the confirmed closure. |
| Autonomous question, stop, resume and authorization revision | `test_inbox.py` checks that the answer remains separate from resume and rejects stale or foreign references. `test_autonomous_journey.py` projects delegated task and phase notifications from real production effects using synthetic ports. Its judge case drives a BLOCKED `planning_ambiguity` check through the real judge effect to the owner stop: the judge item and the autonomous question keep distinct identities, and the judge item stays unresolved while the question is open, then resolves after the answer or after revocation. `test_autonomous_roadmap.py` verifies rollback after an injected recovery failure and stale recovery refusal. |
| Frontend route and archive gates | `inbox.test.mjs` exercises exact command composition, route round-trips and a rendered archive conversation with neither controls nor a polling timer. |

Focused backend verification passed 16 tests in the final selection, plus the earlier autonomous and journal
guard checks. The standing-permission projection and schema selection passed 5 tests. The final task-clarification
and schema selection passed 8 tests. Focused frontend verification passed 37 tests. The exported OpenAPI was regenerated with the
frontend types and checked against the runtime schema. Diff review covered tracked changes and the new source
files, with semantic comparison of the OpenAPI export. Existing routes retain their schemas except for the
optional run-version field in the autonomous preview response.

Scope of evidence: temporary databases and checkouts, synthetic ports, test clients and frontend server renders.
Manual browser verification against a running service, real providers, native qualification and migration of
installed data were outside the verification. T018 owns map integration and graphical traces. OS delivery and
T019 accounting remain separate. The owner deferred direct judge responses. The source is uncommitted for
owner review, and the delivery stages above remain pending.

## Closure checks

The first complete `scripts/check --frontend` ran in the restricted execution environment. Unittest, Alembic,
the 279 Node tests and the build passed. Pytest reported 99 failures and 26 setup errors, primarily from denied
local sockets. A focused tool-bridge reproduction identified `socket.bind` returning `PermissionError`.
The same 16 synthetic transport cases passed when local sockets were allowed. A current-table assertion also
needed updating for the additive migration and passed its focused check after correction.
The complete offline check was then repeated with local sockets allowed.
That run found a literal pre-T017 table count and a knowledge-reader boundary assertion. The count now verifies
the current model set, and the accepted-revision read reuses the existing knowledge service. Their focused
checks and the delegated production journey passed together (3 tests). A final complete check follows these
corrections and the separate task-clarification retry.

The final complete check passed on the product source delivered for review.

A later review found that judge escalations could only be resolved by an answered correlated permission
escalation, so an autonomous judge stop or a manual `blocked_check` escalation stayed unresolved indefinitely. The
projection now derives resolution from the originating blocker under D302 (see the [flow](../flows/global-inbox.md)).
A decision link, read receipt or opening the item still does not resolve it. Without the correction the three new
cases fail. The focused selection of `test_autonomous_journey.py`, `test_judge.py` and `test_inbox.py` passed
(187 tests). After the correction, the complete `scripts/check --frontend` passed: unittest, Alembic, pytest
(3166 passed, 2 skipped), 280 Node tests and the build. `scripts/check-docs` and `git diff --check` passed.

| Check | Final result |
|---|---|
| `scripts/check --frontend` | Exit 0. Unittest 10 passed, Alembic metadata matched, pytest 3164 passed and 29 subtests passed with 2 skipped, Node 280 passed, TypeScript and Vite build passed. |
| `scripts/check-docs` | 120 Markdown files, 0 errors. |
| `git diff --check` | Exit 0. |
| Diff and work routing | Reviewed product, schema, generated contract, tests and documentation. HEAD remains `9e8995b` on the topic branch. The one-off queue is empty. |

The pytest warning comes from a deliberately duplicated ZIP member in the existing tampering fixture.
The build reports JavaScript chunks above 500 kB. No manual browser layout verification was performed.
Source completion does not complete owner review, integration or any later delivery stage in the table above.
