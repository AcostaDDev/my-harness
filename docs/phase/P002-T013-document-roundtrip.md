# P002-T013 — Exports, manual import and portable document format

## 1. Status, ownership and delivery

2026-10-31. **G09 accepted; source `2c54fa9` completed and integrated into develop by the accompanying authorized merge; independent technical re-review passed.** This record owns the
accepted format, integration analysis and acceptance matrix; implementation evidence is recorded separately below.
The session editor is independent of the product's reviewer/executor roles.

Revalidated locally: clean `develop` at `1b0b7555266e158a1390283d7844e457baf8e140`, equal to local
`origin/develop`; no fetch or remote consultation. T012 source `6643ada` is integrated by that merge;
T004/T005/T006/T011/T012 are available. ONE_OFF_TASKS is empty. Created
`feat/p002-t013-document-roundtrip` from that base. The starting schema was `0035_permissions`, 85 tables; T013 adds `0036_knowledge_exchange`, 86 tables.

| Delivery stage (D235/D242/D253) | Actual state |
|---|---|
| Local reviewable source | Complete; independent technical re-review passed, including all four corrections |
| Source commit | Completed as `2c54fa9` on the recorded topic branch |
| Integration into develop | Completed by the accompanying authorized merge; push of develop authorized |
| Release 0.2.0 through main | Pending and unauthorized |
| Distribution/publication | Pending and unauthorized |
| Installation | Pending and unauthorized |

Product source and parity documents are changed locally. Frozen histories, existing catalogue entries and recipe
sources are preserved. No service, harness, provider, network installation or real agent is run.
Documentation travels with the T013 source; no separate integration is requested.

## 2. G09 — owner acceptance

Authority: [T001 §12](P002-T001-contracts.md#12-open-gate-register) assigns format/version, ownership manifest,
renderer, identity mapping, new/update imports and loss reporting to T013. [T011](P002-T011-db-intake.md#interfaces-reserved-for-later-tasks)
expressly chose neither format nor manifest. D271's replacement policy is already accepted and is not reopened.

**Accepted package A:** the owner accepted §§3–6 together: Markdown plus JSON metadata v1, fixed explicit target list,
deterministic renderer v1, explicit ownership adoption, ID-based update and fresh-identity portable import,
blocking unresolved losses with exact canonical owner preview. Instruction wrappers follow D285 and the budgets
below. This acceptance does not authorize later delivery stages.

The owner explicitly accepted package A (§§3–6) on 2026-10-31 in this session: G09 is resolved as D294.
Local implementation, tests, parity and documentation are authorized. Commit, merge, push, publication, installation,
service startup and real agents/providers remain unauthorized. Source completion and delivery remain separate.

## 3. Recommended document, metadata and renderer contract (accepted G09)

- Format `harness-documents-1`, ownership `harness-ownership-1`, renderer `harness-knowledge-markdown-1`,
  portable envelope `harness-project-1`. Standard-library JSON and Markdown only; no new dependency.
- UTF-8 rendering, LF framing, deterministic ordering, no wall clock, machine root, absolute paths or mutable
  operational state. Render only verified accepted members/versions/links, plus the adopted manifest and immutable
  work language. Same inputs produce identical target bytes and digests.
- One JSON companion at `docs/.harness/knowledge.json` contains format/renderer, source project and revision
  ID/hash, work language, adopted ownership digest, complete member identities/version numbers/content hashes,
  scalar fields, ordered-array fields (task subtasks), provenance/source, root positions and typed links.
  Text fields rendered in Markdown have locators rather than a duplicate authoritative body in JSON.
- Markdown text fields use paired reserved HTML comments carrying item ID, field name and a deterministic token.
  Content between them is the field verbatim, including prose and Mermaid fences. Exactly one LF of framing on
  each side is excluded from the value; retained newlines inside are content. Choose the first deterministic token
  absent from all field bodies. Heading/index text outside fields is derived decoration, checked during import;
  edits there are reported, never silently substituted for a canonical field. Titles/status/scalars are edited in
  metadata. No Markdown AST conversion, heading-based identity inference or prose summarization.
- This supports arbitrary fenced source and ordered rich sections without normalizing their bodies. Unknown or
  duplicate markers, malformed metadata, changed decoration, uncontained text and missing fields produce located
  diagnostics. A user can explicitly preserve uncontained prose as a new section, then review a new preview.
- Baseline content hashes describe the exported versions, not trust in edited files. On explicit import compute
  hashes of selected bytes, parse proposed values, and report changed fields; legitimate IDE edits need not match
  baseline hashes. Metadata claims never bypass current database validation or project ownership checks.
- Limits: 512 KiB per non-instruction target (including metadata), 4 MiB aggregate selected input/output,
  existing knowledge field/schema limits unchanged. Oversize or unsupported version refuses staging/export before
  writes, with no truncation. JSON duplicate keys, invalid UTF-8 and ambiguous framing refuse parsing.

Representative synthetic section in `docs/ARCHITECTURE.md` (IDs abbreviated only in this illustration):

````markdown
# Architecture

## Queue
<!-- harness:field k-section-queue body f0 -->
Preserve order and retry only deterministic effects.

```mermaid
flowchart LR
    Draft --> Accepted
```
<!-- harness:end k-section-queue body f0 -->
````

Companion excerpt (illustrative hashes/IDs; a complete file also contains all members and links):

```json
{
  "format": "harness-documents-1",
  "renderer": "harness-knowledge-markdown-1",
  "source_project_id": "synthetic-project-a",
  "revision": {"id": "synthetic-revision-2", "number": 2, "sha256": "<revision digest>"},
  "work_language": "en",
  "ownership_sha256": "<adopted manifest digest>",
  "members": [{
    "item_id": "k-section-queue", "kind": "section", "document": "architecture", "code": "queue",
    "version": 1, "content_sha256": "<exported content digest>", "root_position": 0,
    "content": {"title": "Queue", "format": "markdown", "target": "agents", "status": "active"},
    "fields": {"body": {"path": "docs/ARCHITECTURE.md", "token": "f0"}},
    "provenance": "known", "source": null
  }],
  "links": []
}
```

Every D284 kind is represented, including retired/withdrawn knowledge and decision supersession links; no historical
revision chain is exported as local adoption authority. Canonical JSON hashing follows existing `freeze` rules.
Generation receipts are separate: intent ID, accepted revision/hash, renderer, ownership digest, expected Git
HEAD/tree/index, per-target baseline blob/absence and rendered digest, outcome and final commit reference. Receipts
live in durable storage, not the companion (avoiding self hashes and commit/hash cycles).

## 4. Recommended targets, ownership and instructions (accepted G09)

| Exact target | Rendered knowledge |
|---|---|
| `docs/SPECIFICATION.md` | Requirements, their criteria, specification sections |
| `docs/ARCHITECTURE.md` | Architecture sections |
| `docs/DDBB-DIAGRAM.md` | Data-model sections, including Mermaid source |
| `docs/flows/knowledge.md` | Ordered flows sections |
| `docs/ROADMAP.md` | All phase definitions and their criteria/addresses |
| `docs/NEXT_STEPS.md` | All task definitions, subtasks, criteria and dependencies; no execution status |
| `docs/DECISIONS.md` | Product decisions, historical status text and explicit supersession |
| `docs/STATE.md` | Accepted knowledge revision reference and definition summary; no invented operational progress |
| `AGENTS.md` | Instructions with target `agents` |
| `CLAUDE.md`, `GEMINI.md` | Optional D285 wrappers, separately selected in ownership preview |
| `docs/.harness/knowledge.json` | Companion described above |

The proposed initial manifest requires every non-wrapper target above; wrappers are the only optional targets.
For example, a selected Claude wrapper adds
`{"path":"CLAUDE.md","role":"instructions:claude","required":true}` to the manifest's target array.
The manifest envelope contains `format`, `renderer`, destination knowledge project ID, work language and this exact
array sorted by path; its canonical digest covers all fields. The adopted record binds that digest to the owner's
preview/consent. Source metadata cannot install this destination ownership record.

Own whole files, not the old managed blocks. The manifest is persisted authority with version, renderer, exact
paths, roles and wrapper selections. Its preview lists every path's ownership transition, HEAD blob or absence,
replacement bytes/hash and original-preservation receipt. The owner explicitly adopts it during creation,
onboarding, import or a format revision. Neither a matching filename, metadata claim nor an accepted knowledge
revision grants file ownership. Existing unowned files require explicit takeover in that preview; otherwise
collision refuses. Preserve replaced committed originals by Git blob/tree references and durable verified bytes
before first replacement. Empty-root creation seals absence instead. No ownership of README, arbitrary docs,
`docs/phase/`, archive files or other flows; do not enumerate/delete files by glob. A format change/removal needs a
new explicit manifest preview; this version never silently deletes former targets.

Absent selected owned targets are regenerated. Dirty worktree/index refuses a new export; committed IDE changes may
be replaced under D271. No current Markdown bytes feed rendering. Root, every ancestor, final file type, Git path
mode and target alias/case collisions are checked; refuse symlinks, hard-link aliases, traversal, absolute paths,
special files and paths outside the root. Acquire/fence the checkout writer; validate again at the effect boundary.
Cooperative same-user races retain D065's residual limit; no claim of OS isolation.

D285 instructions use the existing deterministic heading staging for explicit imports: preserve bodies, order and
provenance, remove only the fixed `@AGENTS.md` directive from wrappers and report its removal/irregular headings.
Instruction files use plain headings/bodies rather than field markers, with section identities/order in the
companion; ambiguous edited structures require explicit mapping in preview. Render `AGENTS.md` from `agents`
sections; selected wrappers start with `@AGENTS.md` followed by that client's sections. Generate a wrapper only
when explicitly selected; nonempty client sections with an unselected wrapper block export until resolved.
Proposed budgets retain ≤60 lines for AGENTS and ≤15 for each wrapper, additionally ≤64 KiB per file. Count the
directive and framing lines. Exceeding a budget blocks export and reports the complete preserved content; no
automatic condensation or dropped rules. Instructions remain sensitive owner-only changes. These files never
replace T007's accepted database context, and imports never execute directives or fetch referenced files.

## 5. Recommended identity, update and portable rules (accepted G09)

- Update is explicitly selected for the registered destination. Resolve IDs only within that project and verify
  immutable kind/document/code and base version/hash against persisted history. A stale exported base is reported;
  changes stage on the explicitly reviewed current head, without automatic rebase or overwriting concurrent work.
  Same code/title/content is never identity evidence. Duplicate IDs, code collisions and foreign IDs block until
  explicit resolution. Unknown IDs need owner choice: create a fresh identity with an available code, explicitly map
  to a compatible existing item, or exclude with reported dependent effects. Never reuse an unknown supplied ID.
- Partial document import patches only selected mapped items/fields and explicitly selected links. Omitted files,
  fields, members or links retain destination knowledge; omission never means removal. Retire/withdraw/remove only
  as an explicit canonical change allowed by D284. Accepted decision content cannot be revised: preserve it and
  propose a new decision with a reviewed supersedes relation. Historical statuses use T004's tested mapping;
  unknown/proposed/ambiguous statuses require resolution, never default to accepted.
- New-project transfer is a separate UI mode into a destination without accepted knowledge. `harness-project-1` is
  one closed JSON envelope containing the complete project-scoped knowledge snapshot, text values, links, source
  version identities and payload digest, not a ZIP or path extraction operation. Fresh local item/version/revision
  IDs are allocated and the complete source-to-destination map is sealed; codes and ordering are preserved if valid.
  Foreign source revision/version numbers remain provenance, not local history or approval. Import creates one
  actual owner-confirmed revision; it neither registers execution authority nor creates an operational phase.
- A repeated transfer/update uses a persisted mapping scoped by source project, source item and destination;
  collisions require choice. References rewrite through that exact map before D284 validation. Every endpoint must
  be present in the resulting destination revision, with correct kinds, dense positions and no forbidden cycles.
  Missing references block adoption; never match by similarity or silently drop dependencies.
- New destinations explicitly choose their immutable work language; updates keep the destination's existing
  language. A source-language mismatch is reported, never translated or used to alter destination configuration.
- Portable sources contain project-relative locators/digests only. Keep exact original source objects privately
  with input artifacts; show any redaction/relocation in the loss report. No local absolute roots, unrelated
  projects, configuration, credentials, invocations, artifacts of execution or ledger data enter the envelope.
  Knowledge may itself contain owner-authored sensitive text: show the exact export scope, do not claim automatic
  secret removal. Reject credential/configuration fields outside the closed schema.
- Portable digest verifies integrity, not sender authenticity. Imported attribution is labelled source-claimed;
  record the real local actor/reason separately. Local import provenance uses existing supported source kinds and
  locators to retained input bytes; do not invent author/date. No runs, approvals, grants, rulings, usage/costs,
  READY, lifecycle progress or stopped-writer evidence can be imported. Backup/restore preserves historical
  evidence under its separate format and query-only rules; this knowledge transfer cannot restore it.

## 6. Recommended staging, loss and recovery rules (accepted G09)

UI: select files/envelope → parse → validate/stage → located report → exact canonical before/after preview → explicit
`owner_confirmed` adoption. Report each unsupported, absent, ambiguous, transformed or excluded input with source
path/field, retained input digest, proposed result and severity. Missing selected input, unresolved identity/link,
malformed framing or forbidden operational fields block adoption. Acknowledged exclusions/representational changes
must be explicit selections in the hashed preview; they cannot bypass core invariants. Unselected documents are
reported as retained, not missing. Keep raw selected bytes for inspection/recovery; nothing is silently discarded.

Seal input hashes, import mode, mapping, report/resolutions, expected head/draft, manifest choices, actor and reason
in the consent envelope. Preview displays full text, Mermaid source, order, links, provenance, sensitive changes and
ownership/export consequences. Editing inputs invalidates consent. Adoption rechecks CAS/current authority and all
bindings in one domain transaction. Lost response/reload recovers the same persisted outcome using identical
key/body; concurrent adoption refuses stale consent. No fresh inferred proposal, silent retry or new approval.

Knowledge adoption and export delivery are separate facts. A pending/failed export remains visible without rolling
back accepted history. Seal intent before writes and retain exact rendered bytes/versioned inputs; outcomes are
recoverable per target. A retry first proves writer stopped/fencing and distinguishes original HEAD bytes/absence,
already written sealed output and unrelated modifications. Recognize own partial writes instead of applying the
fresh clean-baseline guard blindly; any other bytes/index/HEAD change refuses reconciliation. Reuse the same sealed
rendering, write remaining targets, reconcile the exact commit if already created, and never rerun inference.
Required target failure blocks the owning commit while preserving acceptance. A version mismatch cannot select a
new renderer implicitly. T014/T015 will consume the receipt; their task acceptance/closure workflows stay deferred.

## 7. Integration analysis prepared before G09 acceptance

| Existing boundary inspected | T013 integration required after acceptance |
|---|---|
| `core/engine/document_export.py`, `storage/document_export.py` | Legacy delimited-block/projection export uses current text and baseline comparisons; retain its lane/regressions. It is not the P002 renderer and must not acquire the new ownership policy implicitly. |
| `core/engine/knowledge.py`, `storage/knowledge.py` | Reuse six kinds, closed content schemas, verified Revision reads, instruction staging, status mapping, immutable versions and linear adoption CAS. Persist new transfer mappings without rewriting existing legacy maps/hash formats. |
| `services/domain_operations.py` | Reuse caller/project binding, query-only refusal, transaction, classification, preview comparison and outcome idempotency. Add versioned commands rather than alter frozen catalogue entries; keep agents unable to adopt/import. |
| `storage/operation_journal.py` | Generic sealed effects classify missing outcomes conservatively; they do not supply an exporter or per-target reconciliation. Add deterministic effect receipts under existing writer/job fencing; do not equate an expired lease with a stopped writer. |
| `api/knowledge.py`, `Knowledge.tsx` | Registered-project mutation routes and standalone query-only consultation stay distinct. Extend full preview and retained consent recovery; no mutation controls in restored consultation. New endpoints require OpenAPI/client parity and en/es diagnostics. |
| `services/intake.py`, `storage/profile_intake.py` | Replace `export_commit_pending_T013` only after actual structured export/commit outcome. Bind accepted revision/hash, original HEAD/tree/inventory, conversation/turn and proposal. Preserve onboarding originals and empty-root creation intent. |
| T012 adoption / owner regeneration | Schedule a visible deterministic export continuation at the manual boundary; database success is not delivery success. Explicit initial ownership adoption is necessary even when knowledge already exists. |
| T014/T015 consumers | Expose sealed revision/manifest/renderer, required targets, digests and recoverable result/commit reference; no task-run loop, READY check, archive/tag or closure implementation here. |
| T016/T020 | Keep final readiness/delegation and installed conversion/integrated recovery pending. Import/new-project transfer does not satisfy either. |

At proposal time the schema was unchanged. Storage design for manifests, import artifacts/maps and delivery receipts had to
follow accepted G09 and update DDBB-DIAGRAM with any migration; no speculative tables or generic infrastructure are
introduced during this gate. Flows `documents`, `domain-operations`, `project-definition`, `project-onboarding` and
configuration/intake continuations need parity when behavior changes. T001 FL10 remains the accepted outline.
No independent product fix is demonstrated by this analysis: code changes at these boundaries would embed G09
choices or alter a working predecessor. The independent deliverables are this analysis and the matrix below.

## 8. Acceptance matrix (requirements; implementation evidence below)

| ID | Synthetic evidence required | Boundary |
|---|---|---|
| A01 | Six kinds, rich prose/Mermaid, nested/root order, subtasks, provenance and all link kinds survive export/import/export; identical accepted inputs render identical bytes | Pure format + knowledge |
| A02 | Optional/empty/over-budget wrappers; fixed import removal reported; irregular headings and ambiguous identities require choice; no rule truncated | D285 |
| A03 | Ownership absent, adopted takeover, unowned collision, missing file, committed IDE edit, dirty/staged/untracked edits, absent empty-root HEAD | Export safety |
| A04 | Traversal, absolute/case aliases, symlink ancestors/targets, hard links, special files, invalid encoding, duplicate JSON keys/IDs, framing injection, large/unsupported input, hostile Mermaid/HTML | Parser + filesystem + protected UI renderer |
| A05 | Foreign project IDs, same-code impostors, unknown-ID choices, stale source versions, new destination mapping, missing/cyclic/cross-project references | Identity + TM09/TM17 |
| A06 | Omission retains members/links; explicit exclusions/losses visible; accepted decisions immutable; historical states do not invent approvals | Stage + preview |
| A07 | Changed bytes/mapping/report/head/draft after preview refused; two concurrent adopters; response loss/reload repeats identical consent once | API/domain + Node interactions en/es |
| A08 | Query-only reads remain available; parse/stage/adopt/ownership/export mutations refuse without writes; local session/CSRF/project guards | API/archive |
| A09 | Crash before/after each target write, partial manifest, lost result and commit response; same intent recovery recognizes own bytes, refuses unrelated edits, no duplicate effects/inference | Export journal + temporary Git |
| A10 | Intake adoption → ownership/export/commit continuation; profile before/after knowledge remains independent; preparation/activation/READY never inferred | Structured intake |
| A11 | Portable new/update mappings preserve references and versions as source only; closed schema rejects operational history and foreign/config/private fields; transfer cannot restore runs | Portable versus backup |
| A12 | Legacy document export and backup/query-only regressions; T007 frozen context unchanged by imported instructions; later consumers receive receipts without productive execution | Compatibility |

Start with `scripts/check` on focused knowledge/export/intake/journal/API tests and the pertinent Node editor/review
and import interaction tests. Use temporary synthetic Git roots, fake effects and fault injection only. At
implementation closure run `scripts/check --frontend` once and `scripts/check-docs`; inspect failures in saved logs.
Do not rerun predecessor suites merely to recover context.

## 9. Proposal-only verification (before G09 acceptance)

Local inspection covers the entire new record and the STATE/NEXT_STEPS diff; `git diff --check` passes.
Focused `scripts/check-docs` over these three files passes (3 Markdown files, 0 errors), including explicit
validation of this new untracked record. ONE_OFF_TASKS was rechecked and remains empty/unmodified.
No product tests, Node suite, browser, migration, installed journey or independent technical review is claimed for
this documentation-only proposal. No general suites were repeated to recover context.
That handoff completed the proposal only. The subsequent explicit owner acceptance resolved G09;
current implementation evidence follows.

## 10. Local implementation and review map

G09 is resolved as D294. The source remains uncommitted on the recorded topic branch.

- `core/engine/knowledge_documents.py`: pure v1 renderer/parser, Markdown field framing, instruction
  framing/spans, Mermaid source, portable integrity, strict input/path/size checks and loss diagnostics.
- `services/knowledge_exchange.py`: owner-only staged bytes, explicit scoped mapping, located reports and
  acknowledgements, immutable decision/reference validation, full canonical preview, adoption/outcome CAS.
  Uncontained documents may be explicitly preserved verbatim as a new rich section while existing knowledge
  remains unchanged; this choice is reported and bound to consent.
- `storage/knowledge_exchange.py`, migration `0036_knowledge_exchange`: insert-only artifacts/manifests,
  source maps, delivery requests/intents and per-target/commit receipts; 86 product tables. The shared root
  writer lock adds an exchange owner; the trigger digest and backup verifier cover this new evidence.
- `services/knowledge_delivery.py`: regular/absent target guards, committed/actual byte checks independent of
  Git status, sealed baseline/output CAS, persistent checkout lock and cross-process nonblocking exclusion,
  per-target results, deterministic Git commit/ref reconciliation and conservative stopped-writer recovery.
  Failure retains the intent/lock and a pending outcome; no inference is launched.
- Owner API and `KnowledgeDocuments.tsx`: select/parse/stage/report/preview/adopt, exact target takeover preview,
  document/portable download, regeneration, receipt inspection and exact request recovery after response loss.
  English/Spanish copy, protected rich rendering and raw text inspection are retained. OpenAPI/client types
  are regenerated; no new dependency is introduced.
- T011 source bindings continue through explicit ownership/export/commit. Profile confirmation before/after
  delivery remains independent. Completed structured delivery can supply the existing preparation boundary
  without inventing a phase; no preparation, activation, READY or operational history is fabricated.
- Owned paths are included in the registered project's agent protection. Retained legacy Markdown-authority
  edit/export/task/closure entry points refuse newly owned projects until T014/T015 integrate their workflows;
  legacy projects keep their existing behavior. Manual knowledge adoption persists a visible export request
  and leaves delivery pending until the explicit owner generation action completes.

Reversible format details: instruction metadata includes exact spans to preserve bodies containing headings;
ambiguous structural edits use explicit instruction mapping instead. Mermaid bodies receive reversible display
fences outside their canonical source. A v1 manifest cannot silently remove previously owned targets. Portable
input verifies each content hash as well as its envelope digest; digests are not sender authentication.

## 11. Local verification before independent review (2026-10-31)

The required `scripts/check --frontend` ran once: unittest (10), Alembic comparison, Node (269/269) and
TypeScript/Vite build passed. Restricted pytest reported 98 failures/26 errors, 2737 passes, 2 skips and
29 passing subtests. Its log showed process inspection/socket permission refusals in the synthetic relay/start
suites and one own T013 failure: Spanish generated headings outside the message catalogs. The heading strings
were moved into the en/es catalogs; focused service-diagnostic checks passed.

Pytest was then repeated offline with the required local synthetic process/socket permissions through
`scripts/check tests`: **2866 passed, 2 skipped, 29 subtests passed**, one expected warning from the duplicate-ZIP
member tampering fixture. No real agent/provider or application instance on this repository was launched.
Restricted/full logs are retained under `.local/check/t013-full-restricted-*.log` and
`.local/check/t013-full-pytest.log`.

Subsequent local hardening of input framing, same-consent preview recovery, delivery exclusion, explicit
preservation and UI presentation was checked with focused suites. The last broad focused run had 186 passes and
one architectural-boundary failure (an API read imported KnowledgeSession); that read was changed to a scoped
query without bypassing the shared mutation service. The corrected API/domain/knowledge/service-diagnostic
selection passed **84 tests**. The final pure format/state-summary adjustment and its complete T013 suite passed
**34 tests**, saved as `.local/check/t013-final-documents.log`. The final Node editor/import/consultation selection
passed **18/18**, and TypeScript/Vite build passed after correcting an initial-load undefined-inspection access.
These results are in `.local/check/t013-final-node.log` and `.local/check/t013-final-build.log`.

`scripts/check-docs` passed over all 109 tracked Markdown files plus an explicit pass over the two new Markdown
files (not yet tracked); the final documentation state is checked again at handoff. The migration comparison is
clean; schema is `0036_knowledge_exchange`, 86 product tables. ONE_OFF_TASKS remains empty/unmodified.
The entire source diff, new files, migration/parity and generated contract changes were inspected locally;
`git diff --check` passes. Existing catalogue entry digests and historical document/hash formats are unchanged.
This inspection and local testing are **not independent technical review**.

| Acceptance | Local evidence |
|---|---|
| A01/A02 | Rich six-kind round trips, Mermaid display/source, instruction bodies with embedded headings, exact re-render, budget refusal and plain instruction source/mapping reports |
| A03/A04 | Empty-root creation, committed IDE replacement/deletion recovery, dirty and assume-unchanged refusal, hostile paths/JSON/framing/schema fields and link guards; inherited protected Markdown rendering regressions |
| A05/A06 | Fresh portable identities/reference mapping, unknown/foreign-ID refusal, explicit preservation/exclusion reports, partial selection retains knowledge, malformed raw input retained without partial draft |
| A07/A08 | Competing previews admit only one successor; same adoption result on replay; HTTP local guards/project isolation/query-only archive; Node exact consent recovery after remount in en/es |
| A09 | Failure after a target retains its lock/result; explicit stopped-writer retry, live recovery exclusion, unrelated edits refused, lost commit response reconciles exactly once, delivery-key mismatch refused |
| A10 | Synthetic definition/onboarding through export/commit, profile confirmed before/after separately, no operational phase/private configuration created; downstream preparation uses the exact completed receipt |
| A11/A12 | Portable per-content/envelope integrity, forbidden operational fields, actual backup/restore query-only journey with exchange evidence, old documentary/knowledge/context/journal regressions in the full suite |

Source is ready for technical review, not integrated. Commit, merge, push, release 0.2.0, distribution/publication,
installation and service startup remain pending and unauthorized. No real browser/native provider, installed
conversion, full installed journey or independent review is claimed. T014/T015 productive workflows, T016 final
readiness/delegation and T020 installed/integral recovery remain excluded. A conflicting external HEAD/index/target
change refuses recovery and retains the writer lock; it must be resolved to the sealed baseline before retry.
Cooperative same-user filesystem races retain D065's limit; no OS isolation is claimed. A v1 ownership manifest
cannot remove a formerly owned target. Unknown instructions with ambiguous structure require explicit mapping;
unsupported non-instruction documents require supported metadata or explicit whole-document preservation as a
rich section. Portable transfer never substitutes for an evidence-bearing backup.

## 12. Independent-review correction round

The independent technical review found four blockers: current delivery ignored a changed ownership manifest;
partial document imports could replay omitted links; newly created roots/children could collide with existing
order; and portable download depended on Markdown generation. The owner's correction request keeps G09/D294
accepted and authorizes these local T013 fixes on the same branch/base and delivery route. Existing work is
preserved. No commit, merge or push has occurred; their authorization remains conditional on satisfactory review.
The earlier local evidence above remains historical and does not establish a passed independent review.

Regressions were added first in `test_knowledge_documents_review.py`. The corrections, interactions and final
local results are recorded below. These fixes introduce no schema change, dependency or later workflow scope.

### Corrections and regression coverage

1. **Current delivery (P1).** `completed_for_project` is the single predicate behind service delivery and
   `completed_at_root`, checking the referenced intent's kind, revision ID/hash, exact adopted ownership ID,
   complete manifest (including renderer) and target set. New ownership invalidates only current delivery;
   historical receipt inspection is preserved. Continuation `status=export_committed` is separate from
   `effect_status=COMPLETED`. Definition/onboarding tests verify profile continuation, configuration and
   preparation before/after adding a wrapper and after its new delivery. The onboarding consumer uses the
   sealed conversation/source binding across subsequent generated commits rather than requiring every export
   to start directly from the original inventory HEAD. Service and protected API regressions cover this sequence.
2. **Partial relationship scope (P2).** The parser returns outgoing links of selected source entities only;
   staging enforces that scope and resolves unselected targets as references to destination knowledge. Omitted
   links are retained, never deleted or replayed. The stale-companion regression adopts an edited requirement
   and proves that unselected task members and destination links are exactly unchanged after removing a
   dependency in the destination.
3. **Ordered merging (P2).** New roots and children append in source order after existing entries. A selected
   existing subset may reorder its existing slots; unselected slots stay fixed. Ordered draft groups are
   rebuilt transactionally to respect the unique position index, without changing accepted evidence. Root
   positions and link order are shown in the exact preview and covered by consent. Regressions exercise
   instructions, other document sections, mapped parents, new children and an independent new instruction root.
   Node interactions explicitly choose create, acknowledge the report, inspect order 1 and adopt in en/es.
4. **Independent downloads (P2).** The additive `documents.bundle@2` returns nullable files/portable with
   separate `render_error`/`portable_error` codes. Wrapper/budget/ownership requirements still apply to disk
   generation; a valid portable snapshot does not require those targets. The API response is typed and
   OpenAPI/client types are regenerated. UI messages distinguish both capabilities in en/es; API/UI cases
   cover client-specific instructions and budgets without ownership, and the reverse portable-refusal case
   preserves valid Markdown output.

The first focused regression run reproduced all six parameterized failures. After corrections, the focused
T013/core/domain/intake selection passes **108 tests**; **8 Node interactions** pass in en/es. These use synthetic
SQLite/Git and injected configuration adapters only; no actual preparation commands or providers are launched.

### Final correction-round local checks

- `scripts/check --frontend` ran **once in this correction round**, with the synthetic local process/socket
  permissions already demonstrated necessary by the previous evidence. Unittest: **10 passed**; Alembic: no
  pending model/migration differences; pytest: **2881 passed, 2 skipped, 29 subtests passed**; Node: **275/275**;
  TypeScript/Vite build passed. The one expected warning is the existing duplicate-ZIP-member tampering fixture.
  Complete logs are `.local/check/t013-review-full-{pytest,node,build,unittest,alembic}.log`.
- Focused regressions and shared intake/domain checks passed **108 tests** before the general suite;
  `.local/check/t013-review-focused.log` retains that output. The two new Python parameterized groups also
  exercise configuration/preparation consumers using real persisted knowledge/profile/receipt records, without
  executing technical preparation. The Node file now has **8** import/download interactions (en/es).
- `scripts/check-docs` passes for all **109 tracked Markdown files** and an explicit pass for the two new
  Markdown files. `git diff --check` is clean. Schema remains `0036_knowledge_exchange`, **86 tables**;
  ONE_OFF_TASKS remains empty and unmodified. OpenAPI and generated client types are regenerated for the typed
  bundle response and independent capability errors. Existing frozen catalogue entries remain unchanged.
- Local inspection covers the full existing T013 diff, the correction logic/tests, generated contracts and
  new files. A complete review patch, including untracked new files, is provided at
  `.local/check/t013-review-complete.patch`; no staging or commit is performed.

All four reported blockers have local corrections and regression evidence. **Independent technical re-review
has not passed or been claimed.** The owner condition for commit/merge/push remains unsatisfied; these and
release, publication, installation and service startup remain pending. No real browser, installed application
journey, native provider, actual preparation or harness execution on this repository is claimed. Prior scope
limits, source-versus-delivery separation and T014–T016/T020 boundaries remain in force.


## 13. Independent technical re-review and authorized source delivery (2026-10-31)

The accumulated T013 implementation, new files, API/data/flow parity and all four review corrections were
independently reviewed. No outstanding relevant finding remains. Current delivery binds the exact accepted
revision and ownership/manifest/renderer; omitted source entities no longer replay outgoing links; ordered
imports preserve existing entries and append new roots/children; portable and Markdown downloads have
independent availability. Regression coverage includes the actual profile/configuration/preparation consumers.

Independent verification on the corrected source:

- Focused document exchange, review regressions, domain operations, knowledge API and structured intake review:
  **112 Python tests passed** through `scripts/check`.
- Import/download/editor/consultation interactions: **24 Node tests passed**, including both interface languages.
- TypeScript/Vite build passed; the existing non-blocking chunk-size advisory remains.
- Current application OpenAPI exactly matches `frontend/openapi.json`; offline client generation into a temporary
  file matches `frontend/src/api.generated.ts` byte for byte.
- Documentation checks passed for 109 tracked Markdown files and the two explicitly named new records;
  `git diff --check` is clean. ONE_OFF_TASKS remains empty.
- The preserved correction-round general logs were inspected: **2881 Python passed, 2 skipped, 29 subtests
  passed; 275 Node passed; 10 unittest passed; Alembic comparison and build passed**. The expected duplicate-ZIP
  fixture warning is unchanged. The full general suites were not repeated after this focused independent review.

Remote develop was read as `1b0b7555266e158a1390283d7844e457baf8e140`, equal to the local base, before
integration. The owner authorized a brief descriptive source commit with bullets, merge into develop and push
of develop conditional on successful review. That condition is satisfied; these source-delivery operations
are now authorized. Earlier pending-review/authorization statements above retain their historical context and
are superseded by this section. Source commit and integration are pending at this pre-commit boundary.

Release 0.2.0 through protected main, distribution/publication, installation and service startup remain pending
and unauthorized. No real browser/native provider, installed conversion, actual preparation commands or harness
execution on this repository was performed. T014 is the next implementation task after integration; later
productive workflows, readiness/delegation and installed conversion remain with their owning tasks.


## 14. Source integration record (2026-10-31)

Reviewed source commit `2c54fa9737033e8008262ebbab2292031919f2c0` was created on
`feat/p002-t013-document-roundtrip` with a brief descriptive title and bullet list. The accompanying explicit
merge integrates it into develop. This merge adds current delivery/status documentation only; product source,
tests, schema, flows and generated API/client files match the independently reviewed source commit.
Documentation and whitespace checks are repeated for this closure; product suites are not repeated for
status-only edits. The owner authorized pushing develop without force.

Source completion, source commit and integration into develop are complete. Release 0.2.0 through protected main,
distribution/publication and installation remain separately pending and unauthorized. ONE_OFF_TASKS is empty;
P002-T014 is the next implementation task and has not started. No service launch, harness run, real provider
call, actual preparation or installed-state change was performed.
