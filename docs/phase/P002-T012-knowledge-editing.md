# P002-T012 — Authoritative knowledge and decision editing

Status: source `6643ada` completed and integrated into develop by the accompanying authorized merge; independent
technical re-review passed (2026-10-31). Push of develop is authorized. Release/publication/installation remain
pending and unauthorized.

## Contract and delivery

Owner: P002-T012, authorized locally on 2026-10-31. Base: clean `develop`,
`ad7ce79fd756c187e0f6be9682e7effade4420f9`; branch `feat/p002-t012-knowledge-editing`.
Route: reviewable local source → future integration into develop → release 0.2.0 through main →
distribution/publication → installation. The owner has now authorized source commit, merge into develop and push
of develop after successful technical re-review. Source `6643ada` is integrated by the accompanying merge; push
of develop is authorized. Release/publication/installation remain pending and unauthorized.

Preserve D270/D272/D284–D288/D292: shared domain commands, exact preview consent, immutable accepted
revisions and decisions, explicit supersession, independent intake/profile confirmation and frozen contexts.
Provide owner consultation/search/history and structured/rich editors, with useful sealed comparisons.
Restored consultation uses persisted records without checkout or action workspace. No automatic rebase,
drift detection, import/export, productive graph, delegated adoption or installed conversion.

## Evidence

Synthetic offline checks and diff review will be recorded here. Schema remains `0035_permissions` (85 tables).

## Implementation and review map

- `api/knowledge.py`: persisted history, full verified revision inspection and revision-bound search; a registered
  project head lookup also handles absence without creating a knowledge project. All queries use the shared
  command dispatcher, local guards and project isolation. Accepted metadata includes actual actor, reason and base.
- `services/domain_operations.py`: additive owner-only consultation entries, verified history, transaction-derived
  before/after member comparison and added/removed relationships. Historical hashes and catalogue entries are
  unchanged. Context associations follow persisted snapshot/invocation/attempt/run keys only (first 100, explicit
  truncation); there is no available READY association to assert.
- `pages/Knowledge.tsx`: standalone persisted consultation and a registered-project editor; six kinds, typed links,
  order, rich document/instruction sections, supersession, history, actual provenance and adoption metadata.
  Separately labelled operational rulings use the existing judge reader; no conversion into product decisions.
  Markdown/Mermaid reuse the protected renderer without requiring an action workspace; checkout-relative resources
  are refused when no checkout is bound. Documentation/file drift stays in its existing lane.
- Input fields are retained on refusal and in browser session storage when available. A lock prevents overlapping
  local submissions; the shared confirmation envelope preserves exact key/body across response loss and reload.
  Explicit recovery handles opening, edits, adoption and discard. Consent is discarded after input edits or
  refusals; no rebase, approval recalculation or silent mutation retry occurs. Unsaved content blocks preview.
- OpenAPI and generated client types are regenerated. No model/migration change: `0035_permissions`, 85 tables.
  D293 records the reversible representation choices; no new dependency or owner-policy authorization.

## Acceptance evidence and limits

Synthetic API/domain tests exercise all six kinds and relationships, classification and reason requirements,
exact before/after/adopted content, stale draft/head/preview, concurrent writers, idempotency, immutable decisions,
supersession and historical reads. The restored API journey now also covers history, full inspection and search
without writes or configured projects. The frozen-context journey checks that the old attempt/run association
remains on its original revision after adoption and the new revision has neither that association nor READY.

The interaction driver executes editing of all six kinds, rich instruction input, preview, reason gating,
response loss, page remount and recovery with the identical adoption body/key in English and Spanish. A separate
consultation journey selects persisted knowledge, reads history, searches, handles a failed read and retries,
using GET only with no workspace or mutation controls. Existing Markdown hostility and router tests remain in scope.
These are React interaction drivers and TestClient journeys; no real browser, provider or installed UI is qualified.

The complete `scripts/check --frontend` was executed once. Unittest, schema, Node (254 tests) and build passed;
restricted pytest reported 98 failures/26 errors, 2712 passes, 2 skips and 29 subtests, with process inspection
and local socket permission refusals among the failures. Pytest was then repeated with the required local test
permissions, rather than treating those refusals as a product pass. Final results are recorded below.

The source diff (including new files and regenerated contracts) is inspected locally; that is not independent
technical review. T013 export/import/portable format, T014–T016 productive workflows and final readiness/delegated
adoption, T017/T018 inbox/graph layout and T020 installed conversion remain pending. Context association lists are
bounded to 100; no task/run relation is inferred from a matching code. This UI never certifies READY.

## Final local checks (2026-10-31)

- Focused knowledge/API/domain/frozen-context checks: 110 passed; the final strict-query/API follow-up: 4 passed.
- `scripts/check --frontend`: unittest 10 passed; alembic no new operations; Node 254 passed; TypeScript/Vite passed.
  The restricted pytest failures above were followed by `scripts/check tests` with local test permissions:
  **2836 passed, 2 skipped, 29 subtests passed**, with one expected warning from the deliberately duplicated ZIP
  fixture. The two skips are not claimed as qualified behavior. Full result saved in
  `.local/check/p002-t012-full-pytest.log`.
- After the final recovery/accessibility/presentation adjustments: targeted Node journeys passed (57 including
  router/Markdown, then the final 3 editor/consultation journeys); final frontend build passed. Vite reports its
  non-blocking large-chunk advisory. Result: `.local/check/p002-t012-final-build.log`.
- OpenAPI/client types regenerated offline after the final API changes. New queries reject unexpected and duplicate
  parameters using the existing localized domain diagnostic. No new backend message key is needed.
- `scripts/check-docs`: all 108 tracked Markdown documents and the explicitly named new T012 record pass;
  en/es catalogue parity, schema parity and `git diff --check` pass. ONE_OFF_TASKS remains empty.
- Complete local diff inspected, including new UI/tests/evidence and generated API parity. Branch remains
  `feat/p002-t012-knowledge-editing`; HEAD/develop/local origin-develop remain `ad7ce79`. No remote was consulted.

Delivery: reviewable local source is complete. Independent technical review, source commit, integration into
`develop`, release 0.2.0 through `main`, distribution/publication and installation remain pending; none is asserted
or newly authorized. No real provider, network installation, service launch or harness run on this repository.

## Technical-review corrections (2026-10-31)

The independent review found five defects in the local source. This round preserves the topic branch and all
previous implementation work, with HEAD still `ad7ce79`. It authorizes corrections and local verification only;
no commit, merge, push or other delivery is performed. The earlier checks above are historical evidence, not proof
that they covered these regressions.

1. **Project lane with a null configuration mode.** `Page` now uses the existing admission condition: both null
   and READY permit the registered-project editor, while archives and genuinely blocking configuration modes
   retain standalone consultation. The new interaction test mounts `Page` with ServiceModeContext, crosses its
   lazy route and checks the actual registered-head requests and controls for null, READY, UNCONFIGURED, INVALID
   and archive modes. It does not substitute a direct KnowledgePage mount for this regression.
2. **Initial-load recovery.** Initial loads and the reload button share a complete read path: persisted project
   index, registered-project resolution when applicable, head, history, rulings and selected inspection. A failed
   index or registered-head request is retried explicitly without reloading the browser. Input fields, saved draft
   work and the exact pending mutation envelope are preserved. Read results publish together only if their
   generation is still current; older project/revision responses and errors cannot replace the new selection.
   Loading and mutation state are separate, and reload also clears the old visible adoption preview.
3. **Revision-bound search pagination.** Project, revision, query and reload changes clear matches and cursor
   and invalidate outstanding searches. Only the current search generation may publish results or a next cursor.
   Tests traverse multiple pages with a mock that verifies each cursor against project/revision/query; they also
   defer search and inspection responses across project, revision and query changes to check stale-response refusal.
4. **D170 presentation.** `knowledge-labels.ts` maps known fields, entity/document/relationship names, targets,
   formats, statuses, provenance, origins and classification text to checked MessageKey entries in en/es. Unknown
   content-field headings use the catalog's Details label. Controls have explicit original contract values;
   project text, identity codes, source values and work language remain unchanged. Consultation and comparison
   use those labels as well as forms. History, draft and inspection timestamps reuse the shared localized `when`
   renderer, retaining the original timestamp in its time element. Spanish assertions cover visible headings,
   options, relations, preview, work-language content and localized dates.
5. **Truncated preview associations.** The adoption preview now displays the existing truncation notice when
   impact.contexts_truncated is true, alongside the persisted context/run links and the explicit lack of a READY
   association. A separate preview test exercises this flag without relying on the consultation notice. The
   backend's limit of 100 and the frozen-context/readiness contracts are unchanged.

Verification for this correction round:

- Before product corrections, the initial new regression group produced **5 failures and 3 passes** on the prior
  source (`.local/check/t012-review-before.log`), demonstrating the uncovered admission, initial retry, cursor and
  presentation defects. Further targeted cases isolate truncation and delayed responses.
- Focused editor/review/router/Markdown journeys: **70 passed**, including **13 new review regression tests**
  (`.local/check/t012-review-focused.log`). Existing English/Spanish mutation journeys still verify original
  request values and identical pending adoption body/key across response loss and remount.
- Complete Node suite: **267 passed**, no failures or skips (`.local/check/t012-review-node.log`).
- `npm --prefix frontend run build`: TypeScript and Vite pass (`.local/check/t012-review-build.log`); the existing
  non-blocking chunk-size advisory remains.
- No backend, shared API contract, schema, dependency or generated-client changes in this correction round;
  Python suites and API generation were not repeated. Their earlier results remain above with their original scope.
- Documentation checks include the new/untracked T012 record explicitly; en/es catalog parity and whitespace are
  checked. The accumulated diff, including the new label map and regression driver, is reviewed locally.

These checks use synthetic fixtures and the existing React interaction driver; they do not qualify a real browser,
installed application or provider. T013 and later scopes remain excluded. D170/D293 already specify the behavior;
no new durable policy decision or owner authorization is introduced. Technical re-review and integration remain
pending, followed separately by release 0.2.0, distribution/publication and installation.


## Independent technical re-review and authorized delivery (2026-10-31)

The accumulated T012 source, API contracts, flow changes and five review corrections were independently
reviewed. No outstanding relevant finding remains. The owner authorized a brief descriptive source commit
with bullets, merge into develop and push of develop conditional on successful re-review; that condition is met.
Earlier pending-review/authorization statements above describe their original implementation or correction round
and are superseded by this delivery record.

Independent checks on the corrected source:

- Focused editor/review/router/Markdown journeys: **70 passed**, including the route-level null/READY/archive
  guards, initial recovery, revision-bound cursors, delayed responses, bilingual presentation and preview truncation.
- Complete Node suite: **267 passed**, no failures or skips (`.local/check/t012-rereview-node.log`).
- TypeScript/Vite build passed; only the existing non-blocking chunk-size advisory remains.
- The current application OpenAPI matches `frontend/openapi.json`; offline generation of the client into a
  temporary file matches `frontend/src/api.generated.ts` byte for byte.
- Documentation checks passed for all tracked Markdown and the explicitly named new T012 record; whitespace clean.

The previous independent backend review passed **80 focused Python tests** (knowledge API/domain/frozen context).
The backend is unchanged in this correction round. Preserved full-run evidence reports **2836 Python passed,
2 skipped, 29 subtests passed**, plus unittest/schema checks; it was inspected rather than repeating the Python
suite for frontend-only corrections. No real browser, provider or installed UI qualification is claimed.

Remote develop was read as `ad7ce79fd756c187e0f6be9682e7effade4420f9`, equal to the local base, before integration.
Source commit and integration are pending at this source-completion boundary; the accompanying merge will record
the source commit and update current delivery status. Push of develop is authorized without force.
Release 0.2.0 through protected main, distribution/publication and installation remain pending and unauthorized.
T013 is the next implementation task; exports/imports, productive workflows, final readiness and installed
conversion remain with their owning later tasks.


## Source integration record (2026-10-31)

Reviewed source commit `6643ada5bfc6aab2187121a4e9135ebafad7310e` was created on the existing
`feat/p002-t012-knowledge-editing` branch with the requested brief descriptive title and bullet list. It is
integrated into develop by the accompanying no-fast-forward merge. The merge updates current delivery/status
documentation only; product, test and generated API files match the independently reviewed source commit.
Documentation and whitespace checks are repeated for this closure; product suites are not repeated for status-only
edits. The owner authorized pushing develop without force.

Source completion, source commit and integration into develop are complete. Release 0.2.0 through protected main,
distribution/publication and installation remain separately pending and unauthorized. ONE_OFF_TASKS remains empty;
P002-T013 is the next implementation task and has not been started. No service launch, harness run, real provider
call or installed-state change was performed.
