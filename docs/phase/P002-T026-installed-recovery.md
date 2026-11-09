# P002-T026 — Installed-state migration and integrated recovery

## Baseline and delivery

Started on 2026-11-09 from clean `develop` at `cd85462`, equal to local `origin/develop`.
The one-off queue is empty. Dependencies include T025 source `18bef36` (D318) and its restored
consultation evidence. The recorded installation is 0.1.9 at `0028_usage_accounting`. The
development head is `0041_work_map_reads` with 94 tables.

| Stage | Disposition |
| --- | --- |
| Source and synthetic qualification | Complete as source `2fe92a4` on `feat/p002-t026-installed-recovery` |
| Technical review | Independent technical re-review passed after both corrections |
| Integration | Integrated into `develop` by the accompanying merge. Push of `develop` authorized |
| Release | Pending 0.2.0 via protected `main` |
| Distribution and publication | Pending |
| Installation | Pending; recorded installation is 0.1.9 |

Route and stage separation follow D235, D242 and D253.

## Minimum contract and required evidence

- Exercise the installed `migrate` command with a synthetic 0028 database, verified pre-upgrade
  copy and refusal cases. Preserve frozen history and accounting. Stage conversion of adopted
  sources and relevant records with exact inputs, stable identities, reference validation and
  explicit owner choices before adoption. Preserve provenance and unknown evidence.
- Qualify joins across the graph checkpoint, domain transaction, CLI, Git and export boundaries.
  Reconcile sealed identities and deterministic effects. Require current evidence for explicit
  stopped-writer confirmation, preserve uncertain inference, and quarantine incompatible graph stamps.
- Upgrade a synthetic 0.1.9 format-3 backup without modifying the source, retain earlier format
  compatibility and verify head restore in an independent query-only root. Exercise portable
  knowledge transfer separately from archived operational evidence.
- Keep the fault matrix, compatibility limits, check results and omissions in this record.
  Use temporary SQLite databases, repositories and synthetic processes. T027 owns the wider
  security/provider audit, T028 journey/UX/performance qualification and T029 packaging and delivery.

## Implemented boundaries

- The installed `migrate` fixture uses the real 0028 schema with a frozen native run, attempted CLI
  execution, artifact references, accounting capture and valuation, and a phase with two adopted definitions.
  The pre-migration copy is checked against the source rows, SQLite integrity, foreign keys, revision,
  length and SHA-256. The copy holds a SQLite writer reservation and rechecks observed process ownership.
- `knowledge-convert` adds the first revision, legacy mappings, exact source receipt and optional proposed
  decision draft through `DomainOperations` and existing knowledge validation and adoption. Replaying the same confirmation
  returns the stored result. The task fixture preserves a historical READY-to-close state without creating
  a structured READY binding, operational permissions, invocation, charge, receipt or graph. Both the
  old and amended definitions remain in place. Selected Markdown bytes stay available in the receipt.
  Remapping merges definition and document sources by original code before applying the canonical code.
  Roadmap titles, plan text and source references stay with the canonical item. Legacy and canonical endpoints
  resolve through the same identity, and distinct originals claiming one canonical code block confirmation.
- `backup-upgrade` accepts 0.1.9 format 3 at 0028 and retains the earlier format paths. It publishes the
  new completion seal only after integrity and reference verification. The working database retains its archive
  mark. Alembic writes through a private connection, and ordinary product connections stay query-only.
  The original database, manifest, completion seal and files are compared byte for byte. The head archive exercise removes both the
  synthetic checkout and original artifact root and compares the same invocation's trace, sealed observed
  steps, contextual chat receipts and accounting. Foreign scopes cannot read them. A queued chat job stays
  queued when the archive opens with supervisor configuration, and POSTs return 409.
- D294 portable transfer is exercised independently on converted knowledge. The target allocates new
  identities, validates every mapped link and rejects exclusion of a referenced requirement. The transfer
  does not copy old execution rows, grants, delivery evidence or the unadopted decision draft.

## Fault matrix

| Injection or refusal | Exercised boundary | Verified restart or outcome |
| --- | --- | --- |
| Live recorded owner, SQLite write lock or failed snapshot | Installed `migrate` at 0028 | CLI refuses before Alembic. Source bytes and revision remain intact |
| Stale file, stale adopted baseline or unresolved historical decision | Installed conversion preview and confirmation | No partial adoption. Exact fresh consent adopts once. Same consent returns the original result |
| Owner remaps a phase and its task, with and without the roadmap selected | `knowledge-convert` preview, confirmation and replay | Collisions are blocking preview entries. The corrected choice keeps one mapping per original, task text, provenance and links. Historical rows and checkout bytes are identical |
| Process exit after the command and audit sink but before domain commit | Real domain service, operation journal and LangGraph saver | No partial domain row, audit outcome or operation. Replay commits one draft under the original node key |
| Process exit after domain commit but before node result/checkpoint | Same graph, reopened runner | Same command, operation and draft. Historical checkpoints retained |
| Crash after a generic effect seal | Operation port with production journal | Sealed intent stops re-entry. Uncertain outcome and original intent remain available |
| Exit at wrapper spawn or after native output before invocation settlement | Synthetic executable, adapter gate, fenced attempt, journal and accounting | Restart opens no ports. Stale versions and live or uncertain owners refuse. Current explicit stopped-writer confirmation settles once, preserving absent or partial evidence |
| Lease expires during unresolved CLI intent | Attempt, lease, operation and confirm-stopped | Stale writer cannot settle. Expiry does not prove death. Owner confirmation reconciles to an interrupted result without retrying inference |
| Fault after tag, partial archive write, commit publication or during domain settlement | Structured phase closure, Git, export receipts and supervisor | Reopen and reconcile the same commit and export intent. Exactly one commit and successor. The exact tag object survives |
| Unrelated checkout edit after a partial archive write | Structured phase closure recovery | Refusal preserves the foreign bytes and existing tag |
| Unknown graph, version drift or structural drift | Runner resume, including replacement of an autonomous failed thread | Quarantine before a node or replacement runs, with stamped/registered evidence and owner action. Historical checkpoints and operation seals retained |
| Tampered file, manifest inventory, database accounting digest, revision, archive mark, artifact labels or unmanifested WAL | 0.1.9 format-3 `backup-upgrade` | Refuses with no completed output. An unmarked database is refused before copying it. The original remains byte-identical |
| Abrupt subprocess exit after Alembic commits `0041_work_map_reads` | 0.1.9 format-3 `backup-upgrade` | No `COMPLETE`. The normal product engine passes the schema check, opens query-only and refuses a write. Source files remain byte-identical |

## Compatibility and omissions

- The format-3 upgrade is qualified for released 0.1.9 at `0028_usage_accounting`. The format-2 fixture
  uses 0027 as in 0.1.8. Format 1 is a synthetic no-configuration compatibility shape. Arbitrary unpublished
  intermediate format-3 revisions are outside this path.
- Conversion supports roots with persisted documentary phase definitions. Document selections require
  bytes matching an existing adoption, including completed bootstrap/import evidence where available.
  Arbitrary prose is preserved as source evidence. Only the documented heading and field formats are
  mapped automatically. An operator supplies noncanonical code mappings, ambiguous statuses or extents,
  and references without a structural source. Source selection and canonical text limits still apply. Oversize
  fields are refused without truncation. Later operational activation is separate.
- Fixtures use temporary SQLite, Git and synthetic local executables. No operator data, provider, listening
  service, installed wheel or release candidate was used. Provider/security audit, full journey and UX
  qualification, and packaging/delivery remain with T027, T028 and T029 respectively.
- No schema, HTTP contract, exported OpenAPI, generated client, frontend or dependency change is required.

## Verification

- Focused `scripts/check` runs exercised `test_installed_migration.py`, `test_installed_recovery.py`,
  `test_backup.py`, `test_usage_accounting.py`, `test_knowledge.py`, `test_orchestration.py`,
  `test_operation_journal.py`, `test_autonomous_roadmap.py`, `test_structured_phases.py`,
  `test_chat_context.py`, `test_knowledge_documents.py` and `test_document_export.py`.
- The offline CLI help showed the Spanish conversion arguments. The message catalogue check covers both languages.
- One full `scripts/check` run passed 10 unittest tests and Alembic. Pytest reported 3,299 passed,
  3 skipped and 29 subtests passed, with one failure in the domain-service ownership guard. The guard exposed
  conversion opening its knowledge transaction outside `DomainOperations`. The transaction and materialization
  moved into that service. The existing guard stayed intact.
- The initial backup compatibility regression passed 10 cases, including format 2 at head and 0.1.9 format 3
  at 0028.
- After the domain-service correction, focused verification passed 163 tests across domain operations,
  installed recovery, knowledge documents, accounting and backup. This includes the unchanged ownership
  guard and both installed conversion paths.

### Technical review corrections

- Independent review reported 214 passing focused tests, clean documentation and whitespace checks, and
  reproduced the two blockers with separate synthetic fixtures.
- The new abrupt-exit case and both remapping cases failed on the pre-correction source. After correction,
  159 focused tests passed across installed recovery, installed migration, backup, usage accounting and domain
  operations. This includes the unchanged domain-service ownership guard and the format 1, 2 and 0.1.9 format 3
  compatibility cases. The subprocess exercises the CLI and normal database engine without starting the service.
- One full `scripts/check` run on the corrected source passed all 10 unittest tests and Alembic found no new
  upgrade operations. Pytest reported 3,305 passed, 3 skipped and 29 subtests passed. The sole warning came from
  the synthetic installer-verifier test that deliberately creates a duplicate ZIP entry.
- `scripts/check-docs` and `git diff --check` passed. The diff was reviewed and the three untracked files were
  checked separately for whitespace. The one-off queue is empty and the source remains uncommitted for technical
  re-review.

## Source integration — 2026-11-09

Independent technical re-review passed. The reviewer inspected the private Alembic connection and the
joins by original source code, and repeated the 159 focused tests covering installed recovery and migration,
backup, usage accounting and the domain-service boundary. The interrupted upgrade remained query-only at
head, and remapped conversion preserved a single identity per source with and without the roadmap. The
implementer's final full check is recorded above. Documentation and whitespace checks passed independently.
Verification used synthetic data, with the real installation and service outside the exercise.

The owner authorized source commit, merge and push of `develop` upon successful review. The accompanying
merge integrates source `2fe92a4` and advances the plan to P002-T027. Release 0.2.0 through protected `main`,
distribution/publication and installation remain pending. The recorded operator installation remains 0.1.9.
