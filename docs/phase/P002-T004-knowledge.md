# P002-T004 — Structured knowledge and revision model

Status: **completed (2026-10-29); committed, merged into `develop` and pushed at the owner's authorization.**
The owner accepted revision 2 of this refinement with two precisions (explicit root order of sections in the hash;
UI editing of canonical instructions by authorized adoption), recorded with the rest as
[D284](../DECISIONS.md#d284--structured-knowledge-entities-revisions-and-immutability) (G06) and
[D285](../DECISIONS.md#d285--canonical-database-instructions-and-generated-instruction-files) (G07), and delegated the
choice of technical representation within those guarantees. T004 introduces no product one-off entity and ships as
part of 0.2.0 without its own release. The storage and core exist and are exercised by synthetic knowledge only; no
product path, API or UI uses them, so operator-visible behavior is unchanged apart from the new empty tables.

Owner/delivery: P002-T004, branch `feat/p002-t004-structured-knowledge` from local `develop` at `467ecc3` (T003
merge). Accepted route: topic → `develop` at the owner's authorization, then part of the **0.2.0** phase release
(D253/D242); no individual release, publication or installation. Binding design:
[D270](../DECISIONS.md#d270--database-owned-project-knowledge-and-immutable-accepted-revisions),
[D271](../DECISIONS.md#d271--generated-documentation-targets-and-explicit-manual-import),
[D272](../DECISIONS.md#d272--authorization-origins-product-decisions-and-operational-rulings),
[T001 contracts](P002-T001-contracts.md) §§3–6 (INV-08, INV-09, INV-11), gates G06/G07, threat TM05, basis B03–B04,
B13, B22. [D094](../DECISIONS.md#d094--agentsmd-in-every-frozen-prompt) keeps describing current behavior until T007
replaces it.

## 1. Scope

In scope:

- Entities, identities, relationships and immutable accepted revisions for one project's knowledge (§3), including
  the `instructions` logical document (§3.6).
- Migration `0030_structured_knowledge`, models, a repository with draft editing, adoption against an expected
  revision, and retrieval of the current or any earlier accepted revision with its relationships, verifying hashes on
  read.
- A pure core validator of content (`knowledge-content-1`), relationship constraints and change summaries, and the
  canonical hashes of §3.3.
- An explicit legacy identity map and the decision-status mapping of §3.4 as pure functions, exercised only with
  synthetic legacy rows and synthetic DECISIONS/AGENTS text. Missing historical knowledge stays absent or `unknown`.
- Backup/verify/restore checks that the protection triggers are present and unchanged (§3.5); query-only refusal.
- DDBB-DIAGRAM, SPECIFICATION §14 and ARCHITECTURE §13 updated with "implemented, unused by product paths" labels.

Out of scope (owning task): typed commands, capability catalogue and owner-only/self-adoption enforcement (T005);
operation/event records (T006); context assembly from the accepted instructions and the D094 replacement (T007);
creation/onboarding writing knowledge drafts (T011); API/UI editing and draft rebasing (T012); export renderer,
ownership manifest, wrapper derivation, size budgets of rendered files and UI import (T013); binding to task acceptance
and phase lifecycle (T014/T015); conversion of installed projects (T020). No OpenAPI, client-type, catalogue, prompt
or UI change is expected; if one becomes necessary it is surfaced first. No new dependency.

## 2. Evidence required

- Migration upgrade/downgrade on temporary SQLite, `alembic check`, table count and diagram parity.
- Adoption: first revision, sequential revisions, stale expected revision refused, concurrent drafts (first wins,
  second stale), discarded drafts, empty adoption (same content hash as the base) refused.
- Retrieval: old and current accepted revisions return identical content and hashes after later adoptions; a row
  altered with the triggers removed is detected on read and not served.
- Immutability and substitution (§3.2, §3.5): every listed bypass attempt fails in the database, not only in the
  repository.
- Relationship constraints: task in exactly one phase, criterion with exactly one owner, sections within one logical
  document, dense ordering, acyclic dependencies, section trees and supersession, accepted decisions kept and never
  re-versioned, codes unique per scope and never reused, no cross-project references.
- TM05: the change summary lists every added/changed/removed requirement, criterion and instructions section, so a
  weakened criterion or changed rule is visible to T005/T009 enforcement; no path lets a later revision alter an
  earlier one.
- Legacy: synthetic `managed_phases`/task codes/decision headings mapped without modifying legacy rows; synthetic
  DECISIONS statuses mapped per §3.4, with unmapped statuses refused rather than defaulted; synthetic AGENTS/wrapper
  text staged into instructions sections verbatim.
- Backup, verification and restore refuse a database whose triggers are missing or altered; query-only restore refuses
  repository writes.

## 3. Resolutions

Accepted base (owner, 2026-10-29): six item kinds — `requirement`, `criterion`, `phase`, `task`, `decision`,
`section` — each with a stable identity, an immutable `kind` and a code never reused; one checkable condition per
criterion with exactly one owner (requirement, phase or task); typed links stored per revision; a revision as the
complete copy-on-write manifest of members (item → immutable version) and links; drafts mutable, adoption a
compare-and-set against the current accepted head that assigns the next number and records origin (D272), actor,
reason and change summary; no rebase (T012); no product one-off entity; execution and lifecycle states stay in the
operational tables.

| Kind | Code scope | Content (`knowledge-content-1`) | Status in content |
|---|---|---|---|
| `requirement` | `RNNN` per project | title, statement | `active`, `retired` |
| `criterion` | `CNNN` per project | statement | `active`, `retired` |
| `phase` | `PNNN` per project | title, objective, tag (null) | `planned`, `withdrawn` |
| `task` | `PNNN-TNNN` per project | title, problem, expected result, subtasks (ordered text), evidence note | `planned`, `withdrawn` |
| `decision` | `DNNN` per project | title, context, decision, alternatives, consequences, historical status (null) | §3.4 |
| `section` | slug per logical document | title, format `markdown`/`mermaid`, body, target (§3.6) | `active`, `retired` |

Every version carries provenance `known`, `inferred` or `unknown` and an optional source reference (legacy path,
heading and SHA-256, or an onboarding observation), never an invented date or actor.

### 3.1 Sections and logical documents

- A section belongs to exactly one **logical document**, fixed at item creation like its kind. The vocabulary is
  closed and versioned with the content format: `specification`, `architecture`, `data_model`, `flows`,
  `instructions`. It names knowledge, not files: the mapping of logical documents to paths, and which are exported,
  is T013's manifest (G09). Executor parity for `data_model`/`flows` stays T014's.
- Identity is (project, logical document, slug); the slug is unique within its document and never reused there. Other
  kinds have a null document and a code unique per (project, kind). The database enforces both with partial unique
  indexes and a check that only sections, and all sections, have a document.
- Structure within a document: top-level sections have no parent; `part_of` links a section to a parent in the same
  document (and, for instructions, the same target), forming a tree; siblings are ordered by the link position. The
  order of the **root sections** is explicit per revision: each root member carries a `root_position`, dense from 0
  per logical document (shared by all instruction targets), and non-root members have none. A section never moves to another document; moving
  content is retiring one section and creating another, with provenance pointing to the first.

### 3.2 Complete immutability and identity stability

Database triggers (`BEFORE INSERT/UPDATE/DELETE`, `RAISE(ABORT)`), duplicated by repository checks:

| Table | Allowed | Refused |
|---|---|---|
| `knowledge_projects`, `knowledge_items`, `knowledge_item_versions`, `knowledge_identity_map` | `INSERT` of a new key | any `UPDATE` or `DELETE`; an `INSERT` whose primary or natural key already exists (so `INSERT OR REPLACE` cannot substitute a row) |
| `knowledge_revisions` | `INSERT` as `DRAFT` with null number/hashes/adoption fields; one `UPDATE` from `DRAFT` to `ACCEPTED` (with all adoption fields) or `DISCARDED` | any other `UPDATE` (including back to `DRAFT`, or changing id, project or base); `DELETE`; insertion directly as `ACCEPTED`/`DISCARDED` |
| `knowledge_revision_members`, `knowledge_revision_links` | `INSERT`, `UPDATE`, `DELETE` while the revision is `DRAFT` | any `INSERT`, `UPDATE` or `DELETE` touching an `ACCEPTED`/`DISCARDED` revision, checked on both the old and the new revision id |

- **Linear history.** A partial unique index allows one accepted revision per (project, base), and one accepted root
  per project; the adoption trigger requires `number = base.number + 1` (1 for the root) and the base to be
  `ACCEPTED`. Two drafts on the same base cannot both be adopted, whatever the writer.
- **Identity stability.** Composite foreign keys bind a member's version to its item and both to the revision's
  project; link endpoints reference members of the same revision. An item's id, kind, document and code, a version's
  item, number and content hash, and an accepted revision's members and links can never change; identities are never
  reassigned to other content.
- Draft members can be repointed until adoption; rows of a discarded draft remain as written.

### 3.3 Canonical hashes

All hashes are SHA-256 of the existing canonical JSON (`freeze`: sorted keys, compact, UTF-8).

- `content_sha256` of a version: `{format, kind, document, code, content, provenance, source}`.
- `knowledge_sha256` of a revision (the knowledge set): `{format: "knowledge-revision-1", project, members, links}`,
  where `members` is the list of `[item_id, kind, document, code, version_number, content_sha256, root_position]`
  sorted by item id and
  `links` is `[kind, source_item_id, target_item_id, position, qualifier]` sorted by kind, target, position and
  source. Order is covered by link positions, which are mandatory and dense from 0 for ordered kinds (`part_of`,
  `criterion_of`) and null for the others.
- `revision_sha256`: `{knowledge_sha256, project, number, base_revision_sha256, origin, actor, reason, changes}`.
  Including the base hash chains the history, so changing any earlier revision changes every later hash.
- Retrieval recomputes the version, knowledge and revision hashes and the chain to the root; any mismatch is an
  integrity error and nothing is returned. Evidence (T007/T014/T015) binds `revision_sha256` and the revision id.

### 3.4 Historical decision states

Stored decision status is closed: `accepted`, `rejected`, or `retired` (no longer in force without an identifiable
superseder). `retired` is only valid at the item's first version and only with provenance from an import or migration;
a native decision stops being in force only through a `supersedes` link. `supersedes` carries a qualifier `full` or
`partial`; the displayed state (in force, partially superseded, superseded, rejected, retired) is derived. `proposed`
exists only in drafts and refuses adoption. The original status line is kept verbatim in `historical_status` with its
source; the legacy text is never rewritten.

Mapping used by import (T013) and installed migration (T020), defined and tested here:

| Historical status | Canonical result |
|---|---|
| Accepted, including "accepted design", "implementation pending" or similar progress notes | `accepted`; progress stays in `historical_status`, not in the decision status |
| Rejected, discarded, withdrawn | `rejected` |
| Superseded or partially superseded by an identifiable decision in the same set | `accepted` plus a `supersedes` link, `full` or `partial` as stated; an unstated extent requires the owner's choice in the preview |
| Superseded without an identifiable superseder | `retired`, reported in the preview |
| Proposed, pending, draft | staged as a draft-only proposal; it becomes accepted only through a later normal decision adoption, with that adoption's real origin and date |
| Missing or unrecognized | refused until the owner chooses a mapping in the preview; never defaulted to `accepted` (INV-09) |

Historical acceptance is asserted by the imported document (provenance `known` with its hash); it is not a harness
approval record and the adoption's origin is the import or migration adoption itself (D271: no fabricated approvals).

### 3.5 Substitution bypasses and backup protection

Synthetic tests run raw SQL through the harness connection (`foreign_keys=ON`, `trusted_schema=OFF`) and expect a
database refusal for: `UPDATE`/`DELETE` on each protected table; `INSERT OR REPLACE` and `INSERT ... ON CONFLICT DO
UPDATE` over an existing item, version, revision or member; `DELETE` + `INSERT` of an accepted member or link;
moving a member or link from a draft into an accepted revision; inserting a revision already `ACCEPTED`, reverting
`ACCEPTED`/`DISCARDED` to `DRAFT`, re-adopting, or adopting a second revision on the same base or with a skipped
number; pointing a member at another item's or project's version; changing a version's item or content hash. Removing
the triggers is outside the agents' reach (INV-11); a test that drops them and alters rows shows retrieval refuses to
serve the result (§3.3).

Backups already copy the whole database with SQLite's backup API, so the triggers travel with it. Backup creation,
bundle verification and restore additionally compare the trigger set (names and normalized SQL) with the schema's
expected set and refuse a missing or altered one, as they already do for tables. Restored query-only copies keep the
triggers and refuse repository writes.

### 3.6 G07 — instructions in the database, generated files (owner choice, to be recorded as D285)

- **Canonical source.** Project instructions are sections of the `instructions` logical document, revisioned like
  other knowledge. `AGENTS.md` becomes the canonical exported view of that document; `CLAUDE.md` and `GEMINI.md`
  become derived wrappers.
- **Wrappers.** A section has a `target`: `agents` (default, rendered into `AGENTS.md`), `claude` or `gemini`
  (client-specific notes rendered into that wrapper after the fixed import of `AGENTS.md`). Only `instructions`
  sections may have a target other than `agents`. Whether a wrapper is generated for a project, the renderer and
  the size/line budgets of the rendered files are T013's manifest and export.
- **Editing.** The owner can edit the canonical instructions in the UI through the corresponding authorized adoption
  (T012), like any other knowledge, besides importing them explicitly. Exported files remain generated views.
- **Import of existing rules.** A deterministic, model-free staging splits `AGENTS.md` by headings (the preamble is
  its own section) and wrapper content other than the import directive into `claude`/`gemini` sections, keeping the
  text verbatim with provenance `known` (path, heading, SHA-256). It stages a draft only; the rules become canonical
  through an explicit adoption of a previewed hash. Loss and unsupported content are reported (T013/T020); nothing
  is discarded silently. T004 provides and tests the staging function; T011 (onboarding/creation), T013 (UI import)
  and T020 (installed projects) call it.
- **Sensitivity.** Instructions reach every prompt, so changes to `instructions` sections appear in the change
  summary with requirements and criteria for T005's owner-only enforcement.
- **Transition.** Until T007 delivers context from the accepted instructions and T013 exports them, D094 remains the
  implemented behavior: the engine injects the checkout's `AGENTS.md`, and the definition and onboarding roles still
  do not receive it. D094 is superseded only when T007 implements the replacement, with T013 making the files
  generated (owned, protected from agents, edited only through explicit import, D271).

## 4. Planned components

| Component | Responsibility |
|---|---|
| `core/engine/knowledge.py` | Content schemas per kind and document, link rules, ordering and cycle checks, change summary, canonical hashes, decision-status mapping, instructions staging (pure, standard library) |
| `storage/knowledge.py` | Projects, items, drafts, adoption CAS, retrieval with hash/chain verification, item history, identity map, query-only guard |
| `migrations/versions/0030_structured_knowledge.py` | Seven tables, checks, partial uniqueness, composite keys, protection triggers; downgrade refused while rows exist |
| `storage/models.py`, `storage/schema.py`, `storage/backup.py` | Models, required schema, expected trigger set and backup/verify/restore checks |

Tables: `knowledge_projects`, `knowledge_items`, `knowledge_item_versions`, `knowledge_revisions`,
`knowledge_revision_members`, `knowledge_revision_links`, `knowledge_identity_map` (65 → 72).

## 5. Decisions

- **D284 — Structured knowledge entities, revisions and immutability** (G06): §3 base and §3.1–§3.5.
- **D285 — Canonical database instructions and generated instruction files** (G07): §3.6; supersedes D094 when T007
  implements it.

## 6. Implementation notes

Technical choices made within the accepted guarantees:

- Retired or moved section codes stay reserved: an item exists from its first draft write even if the draft is later
  discarded, so a code is never reused for other content.
- Adoption first issues a no-op write so SQLite's write lock is held before the head is read; a concurrent adoption
  then waits and sees the new head (stale) instead of failing on an old snapshot. The partial unique indexes and the
  numbering trigger remain the database guarantee for any writer.
- The schema digest covers the 21 trigger names and their whitespace-normalized SQL; `require_schema`, backup
  creation, bundle verification and restore refuse a mismatch.
- The instructions staging keeps bodies byte for byte; heading lines are rebuilt from depth and title, so trailing
  spaces or skipped levels are reported (`heading_normalized`, `heading_level`) rather than silently changed. Only the
  `@AGENTS.md` directive is removed from wrappers, and that removal is reported.
- Superseded-by clauses inside an accepted status ("accepted; the closure part is superseded by D091") become
  partial links; active "supersedes …" clauses are not read as the decision's own status.

## 7. Verification and delivery

**Delivery status.** Source complete on `feat/p002-t004-structured-knowledge`, branched from `develop` at `467ecc3`.
After reviewing the diff the owner authorized commit, merge into `develop` and push (2026-10-29); Git history
records the commit and merge identities. The 0.2.0 release route remains pending (D242/D253). No release, publication or installation applies to T004.

### Evidence

- **Focused suite.** `scripts/check tests/product/test_knowledge.py`: 30 passed — adoption lifecycle (first,
  sequential, stale, concurrent, discarded, empty), old/current retrieval identity, relationship and logical-document
  rules, preamble/section order preserved verbatim through staging, adoption and retrieval, root swap changing the
  hash (repository and pure hash, including child order and member/link order independence), TM05 sensitive changes,
  decision supersession and retirement, 15 historical status lines (English/Spanish), legacy identity map without
  touching `managed_phases`, 28 raw-SQL substitution attempts refused by the database plus a competing seal on the same
  base, tamper detection on read with the triggers dropped (chain makes later revisions unservable), trigger digest
  and downgrade refusal, backup/restore with trigger verification and query-only refusal.
- **Full checks.** `scripts/check`: unittest 10 ran ok; `alembic check` no drift; pytest 2393 passed, 2 skipped, 1
  failed — `test_configuration.py::test_additive_migration_and_metadata` asserted the old table count (66 = 65 +
  `alembic_version`); it now expects 73 (72 + `alembic_version`). After that run, a fix in the change summary (adding
  an item without a root position no longer marks a structural change, now asserted) and the count update were
  checked with `scripts/check` over `test_configuration`, `test_knowledge`, `test_backup`, `test_orchestration` and
  `test_storage_api` (158 passed); the full suite was not rerun after those two edits. `scripts/check --frontend` was
  not run (no frontend change).
- **Documentation.** `scripts/check-docs` passes; DDBB-DIAGRAM (head 0030, 72 tables), ARCHITECTURE, SPECIFICATION §14,
  ROADMAP, STATE and NEXT_STEPS updated; D284/D285 recorded.
- **Not performed.** No API, OpenAPI, client types, frontend, flows, prompts or catalogues beyond the en/es message
  keys; no harness execution, real agents or providers, network access other than the authorized push, or
  installed-database migration.
  The renderer, wrappers, UI editing and import are later tasks; their behavior is not claimed.
