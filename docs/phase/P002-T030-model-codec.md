# P002-T030 — Proposed semantic model and codec

Part of the [T030 review record](P002-T030-contracts.md). This is a normative design grammar for the proposed
version. The implemented [knowledge and exchange model](../DDBB-DIAGRAM.md#p002-structured-knowledge) and its
migrations remain the baseline. SQL layout is a T031 choice within these invariants.

## Closed semantic grammar

Records below use a closed JSON object grammar. Every listed key is required. `T?` allows explicit null, with
the meaning in the table. Arrays are present even when empty. Empty string is allowed only for `text0`. Reject
unknown/duplicate keys, unknown discriminator values, unsafe integers, invalid UTF-8, NUL and lone surrogates.
`title` is a nonblank, single-line UTF-8 string ≤ 240 bytes with no control characters. `text` is nonblank
UTF-8 ≤ 65,536 bytes and `text0` has the same bound. Keep every supplied character, including original line
endings and trailing newlines. Size counts UTF-8 bytes. `list<T>` holds up to 64 entries unless stated otherwise.
Times are UTC RFC 3339 seconds; digests are lowercase hex SHA-256. IDs are opaque ASCII
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`. Integers are nonnegative and ≤ 2^53−1, with versions ≥ 1.
Canonical JSON uses sorted keys, UTF-8, no insignificant whitespace, no ASCII escaping except JSON-required
escapes, and integer decimal numbers. Sort set-valued arrays as specified below before digesting. Array order
otherwise has meaning. A hash verifies content identity; it conveys no authority.

| Object | Fields and constraints |
|---|---|
| Semantic revision `semantic-revision-2` | `format, project:ID, revision:ID, number:uint, base:Digest?, language:en\|es, records:list<Member>[0..2048], links:list<Link>[0..8192]`. Null base means the first revision. Digest covers the entire object. Accepted revision number, base and project identity come from the destination store, and actor/time/reason/outcome from the adoption record |
| Member | `id:ID, version:uint, kind:Kind, code:ID, position:uint?, provenance:Provenance, content:Content[kind]`. Digest over the full member. ID is stable within the project; kind is immutable. Codes are human labels, unique per kind per project (task codes retain phase prefix). References use IDs. A renamed label needs a new version and cannot reassign an existing identity. Positions are zero-based, dense for roots of each kind (each block document separately), null for every owned child. Version allocation is server-controlled, including after foreign import |
| Provenance | `quality:known\|inferred\|unknown, source:Source?`. Null means unbound, only for unknown or new native owner-authored text whose provenance is in the local command record. `Source={kind:legacy_document\|legacy_record\|observation\|portable, identity:ID, sha256:Digest, locator:Locator, start:uint?, length:uint?}`. Both range fields null means whole record, otherwise both required and checked as UTF-8 byte range within captured bytes. Quality describes attribution, not permission or proof. Retain original source metadata/raw bytes separately on conversion |
| Link | `kind:LinkKind, from:ID, to:ID, position:uint?, coverage:Coverage?`. Null position for unordered links. `Coverage={mode:full\|partial, fields:list<DecisionField>}`. Null coverage except on supersession. Full has no fields; partial lists one or more distinct target fields in sorted order |
| Planned delivery | `{tag:title?, targets:list<title>, conditions:list<text>}`. Null tag means unspecified. The whole value may be null where indicated, meaning no plan yet; this never represents an actual release |

A portable `Locator` is either `{type:"record", format:ID, project:ID, revision:ID, member:ID, version:uint}`
or `{type:"view", path:Path}` for a registered logical export target. Other captures use
`{type:"capture", ref:ID}` with an opaque source-capture identifier. The source digest and range
refer to retained original bytes in each case. Logical paths and capture IDs have no filesystem
authority. The trusted host maintains its private binding from capture ID to authorized storage,
checkout or original path separately. Absolute paths, host aliases and private root names are never
portable locator fields or resolution inputs. Capture-backed references that cannot be verified
remain unresolved for mapping. No path is synthesized from a source claim.

Record kinds and **all** permitted content keys follow. `active|retired` and `planned|withdrawn` describe
definitions only. Source attestation, approved scopes/commands, acceptance facts, current lifecycle state and
witnesses are stored by their operational owners.

| Kind / view | Content fields |
|---|---|
| `project_intent` / ROADMAP | `title:title, objective:text`; exactly one in an adoptable project |
| `requirement` / SPECIFICATION | `title:title, statement:text, status:active\|retired` |
| `phase` / ROADMAP | `title:title, objective:text, scope:list<text>, exclusions:list<text>, delivery:PlannedDelivery?, status:planned\|withdrawn` |
| `task` / NEXT_STEPS | `title:title, problem:text, expected_result:text, scope:list<text>, exclusions:list<text>, delivery_requirements:list<text>, evidence_notes:text0, status:planned\|withdrawn`. Notes are narrative, even if they mention a check |
| `subtask` / NEXT_STEPS | `title:title, outcome:text, status:planned\|withdrawn`; not independently schedulable |
| `criterion` / owner's view | `statement:text, status:active\|retired` |
| `decision` / DECISIONS | `title:title, context:text0, resolution:text, alternatives:text0, consequences:text0, historical_status:text?, applies:list<Scope>, status:proposed\|accepted\|rejected\|retired`. Null historical status means none supplied. DecisionField is context, resolution, alternatives or consequences. Only local owner adoption can establish a new accepted decision; imported dispositions are source-claimed until explicit classification |
| `block` / typed document | `document:specification\|architecture\|data_model\|flows\|state, type:BlockType, title:title?, format:markdown\|mermaid, body:text0, responsibilities:list<text>, boundaries:list<text>, applies:list<Scope>, status:active\|retired`. Null title means untitled. Responsibilities/boundaries/applicability allowed only for architecture blocks; otherwise empty |
| `gate` / NEXT_STEPS | `title:title, purpose:text, evaluator:coverage@1, applies:list<Scope>[1..64], boundaries:list<Boundary>[1..17], requirements_note:text0, freshness_seconds:uint?, failure:hold`. Boundary enum, criterion consumers and clock in [gates](P002-T030-gates-editing.md#evaluation-contract); null TTL means binding-based validity only |
| `evidence_requirement` / criterion or gate | `statement:text, applies:list<Scope>[1..64], alternatives:list<WitnessRule>[1..8], freshness_seconds:uint?`. Same TTL semantics as gate. Each alternative fully specifies one admissible witness; see gates |
| `instruction` / DB instructions | `title:title?, body:text, status:active\|retired, scope:list<Scope>[1..64], roles:list<Role>, clients:list<Client>, stages:list<Stage>, export:common\|claude\|gemini\|none`. Null title means untitled. Role/stage/client are [closed registry values](P002-T030-inference.md#stages-and-seals). Empty selectors mean all for that dimension. Export selector never decides runtime applicability. Every matching active rule is mandatory |

Codes retain v1 patterns for R/C/P/T/D (ASCII digits); subtasks use `Pddd-Tddd-Sddd` with their owning task's
prefix at creation. Reparenting within the task preserves code and identity. Moving across tasks requires
withdrawal and creation with explicit provenance, with no lifecycle replacement inferred. Other codes are
lowercase slugs (letters/digits separated by hyphens). Gate/evidence codes have no effect on witnesses.
`BlockType` by document: specification = purpose, scope, exclusions, assumptions, unknowns, narrative
(one active root each for purpose and scope; other types repeatable); architecture = overview, component,
interface, invariant, data_flow, deployment, narrative (one active overview root); data_model/flows = narrative,
diagram; state = note (zero or one root, no children). Only architecture data_flow/deployment/narrative,
data_model and flows permit mermaid. The named singleton roots cannot be nested. Standalone gate definitions
may be shared; unattached definitions do not confer applicability.

`Scope` is a tagged union of `{type:"project"}`, `{type:"entity", id:ID, descendants:bool}`,
`{type:"component", id:ID}` (architecture component), or `{type:"path", prefix:Path}`.
A Path is a relative slash-separated UTF-8 path ≤ 512 bytes, components nonempty and neither dot nor dot-dot,
no backslash/control characters, compared case-sensitively on component boundaries in a validated inventory.
Aliases/collisions are checked by admission, not by normalizing a user's string. Entity scope uses exact ownership
closure (project-scoped entities can match themselves). Component matching uses verified explicit `uses_architecture` and architecture dependency
closure computed before scope expansion; path matching uses frozen admitted path scope (including a directory prefix if their subtrees intersect).
Decision and architecture scope arrays may be empty (explicit links only). Nonempty matching selectors
make those definitions mandatory independently of whether the task author linked them. Scope arrays are OR; role × client × stage × scope is AND. Parentage provides display order, never hidden
predicate inheritance. Missing scope facts are unknown, not a false predicate. Use an explicit project rule for
the base instruction set; DB project invocations require at least one matching active project-wide rule.
Normative scope selectors, witness alternatives and role/client/stage selectors are sets sorted by canonical JSON.
Adoption rejects detectable contradictory applicability (e.g. duplicate normalized selectors/rule identity).
Unresolved conflicting instruction prose is a located owner review issue; there is no executable priority,
automatic rewrite or inferred override. Instruction content cannot change runtime grants.

## Relationships

All endpoints resolve in the same destination revision, never by label equality. A retired/withdrawn endpoint
remains consultable; a mandatory operational relation to an unavailable/inactive endpoint stops that boundary; a replacement link
remains valid against a withdrawn historical task.
Every directed (kind, from, to) tuple is unique, including ordered links. Sort records by ID and links by (kind, from, to) in JSON.
Positions order each root or each `(kind, to, child-kind group)`. For `part_of`, the child groups are task,
subtask, block and instruction. For `criterion_of` and `requires_evidence`, there is one group per owner.
An ID cannot refer to itself. Max structural depth is eight below a document or task root.

| Kind | Source → target, cardinality and semantics |
|---|---|
| `part_of` | task → phase exactly 1; subtask → task/subtask exactly 1; block → block in same document 0..1; instruction → instruction 0..1 (same export selector). Ordered |
| `criterion_of` | criterion → requirement/phase/task/subtask exactly 1. Ordered. Every admitted task, subtask and phase has ≥1 active criterion; retirement may leave a structurally valid revision that refuses that admission |
| `depends_on` | phase → phase, task → task, subtask → subtask in same root task, architecture block → architecture block; 0..64 out. Cross-phase task dependencies permitted and checked jointly with phase dependencies and task membership for scheduling cycles (phase completion depends on its tasks; tasks depend on prerequisite phase completion) |
| `addresses` | phase/task/subtask → requirement 0..64 out; explicit only |
| `supersedes` | proposed/accepted decision → earlier accepted decision 0..64 out; accepted previous content and prior links immutable. Per target field, at most one direct effective accepted successor. Full claims all four fields; overlapping sibling claims refuse; later replacement follows explicit successor chain |
| `replaces` | task → earlier accepted task 0..64 out, owner-only, immutable once adopted, D296 lineage and smallest ceiling/all prior consumption; no link from code reuse or reorder |
| `governed_by` | phase/task/subtask → accepted decision 0..64 out; draft may point to a proposed decision only if that exact decision is accepted in the same owner adoption |
| `uses_architecture` | phase/task/subtask → architecture block 0..64 out |
| `requires_gate` | phase/task/subtask → gate 0..64 out; definition also applies via explicit scope and boundary predicates, so omitting a link cannot suppress an independently applicable gate |
| `requires_evidence` | evidence_requirement → criterion/gate exactly 1 (inverse display of “owner requires evidence”). Ordered. Each consumed criterion and effective gate needs applicable evidence at its defined consumer boundary |

Resolve decision applicability from the selected original and each explicit successor. A superseded field
uses the latest effective successor on its unique field chain; other fields remain attributed to the original.
A successor cannot narrow already-applicable superseded fields; new, unlinked fields use its own selectors.
An adopted revision contains no proposed decision. New decisions append in the owner-confirmed order.
An accepted/rejected/retired record's content, ordinal and prior outgoing supersession links are immutable.
Scopes implement the planned `applies_to` relation as typed fields, with embedded endpoint validation. No parallel
editable edges for the same scope. Architecture applicability is via verified use/dependency closure and declared selectors; prose mentions
remain prose. Acyclic checks cover the ownership graph, dependency domains and cross-phase scheduling expansion,
decision supersession and task replacement independently. References can share a target. An invalid relation reports
document, record/link ID and field/index; it is never dropped on repair. Data-model and flow blocks stay in their
own companion-owned supporting views, even when referenced from architecture prose.

## Markdown and portable exchange

Use `harness-project-2` for a closed standalone `{format, semantic, sha256}` envelope, with SHA-256 over
`semantic`. It carries definitions only, including all canonical instruction rules. On import revision IDs,
dispositions, history and provenance in that envelope are source claims. Use `harness-documents-2` and renderer
`harness-knowledge-markdown-2` for marked views plus `docs/.harness/knowledge.json`. The closed companion is
`{format, renderer, portable, manifest, manifest_sha256, projection, files}`. The source manifest and
its verified hash describe exact view selection and grant no local ownership. Each file entry is
`{path, sha256, spans}`, sorted by path; each span is `{id, field, start, length}` (zero-based UTF-8 byte
offset/length into the full file, sorted by offset). Span IDs are member IDs or the projection's reserved `!`
namespace (not valid member IDs), with `!projection` for projection fields; field is a JSON pointer into content or projection. Field spans are nonoverlapping.
The portable semantic payload is complete even where an instruction is not rendered. Document/companion max
512 KiB each except optional instruction views max 64 KiB each, 4 MiB total; portable standalone max 4 MiB.
Refuse overflow, allow a standalone download independently of rendering/ownership. No timestamp from render-time
clock, no host paths in portable identity.

Fixed titles (en / es) and traversal:

| View | Heading en / es | Order and placement |
|---|---|---|
| SPECIFICATION.md | Specification / Especificación | Spec blocks depth-first, then requirements in root order and their criteria |
| ARCHITECTURE.md | Architecture / Arquitectura | Architecture blocks depth-first; architecture relations beside referring entities |
| DECISIONS.md | Decisions / Decisiones | Generated index in decision root order, then records in that order |
| ROADMAP.md | Roadmap / Hoja de ruta | Project objective, then phase roots and criteria; active/actual flags only via projection |
| NEXT_STEPS.md | Next steps / Próximos pasos | Active phase and next task projections; phase order → tasks → ordered subtasks, criteria beside owners; gates once in root order with their requirements |
| STATE.md | State / Estado | Sealed projection, then optional note |
| Supporting views | Data model / Modelo de datos; Flows / Flujos | DDBB-DIAGRAM.md and flows/knowledge.md under docs, depth-first by their own order |

Six views use paths under docs. Begin each with `# TITLE` + LF. Begin the decision index with a blank line
and `## Index` / `## Índice` + LF, then bullet relations with KIND `decision` to each decision.
A NEXT_STEPS phase grouping uses the phase heading with anchor `phase-tasks-ID` and renders no editable
phase fields there. Operational projection rows appear before entities in every view that includes them. Criteria/evidence sit before the owner's other children.
Each entity begins with a blank line, `<a id="k-ID"></a>` + LF and `## CODE — TITLE` + LF. Use only CODE
for kinds without a title/null title. Entity heading depth increases with display nesting up to H6; beyond H6
use H6 with stable anchor and a separate parent reference. Escape Markdown punctuation in inline literals by
prefixing backslash for ASCII punctuation (headings, code/labels and link text); anchors use raw validated IDs.
Position is represented by traversal and in companion, never by a prose ordinal. Remaining scalars map as follows:

| Field class | Exact Markdown projection (LF frames, raw field bytes preserved) |
|---|---|
| All narrative scalar fields (`statement, objective, problem, expected_result, evidence_notes, context, resolution, alternatives, consequences, historical_status, body, outcome, purpose, requirements_note`) | One labelled block in the grammar-table field order: `**KEY**\n<!-- harness:field ID /content/KEY TOKEN -->\n` + raw UTF-8 payload + `\n<!-- harness:end TOKEN -->\n`. TOKEN is the first decimal nonnegative integer whose literal end comment is absent from the baseline raw payload. Null has no block. For Mermaid insert an opening `mermaid` backtick fence + LF before raw bytes, and close the fence + LF immediately after the payload's framing LF, before the end marker. Fence length is max(3, 1+longest backtick run). The companion length counts raw bytes only |
| Ordered narrative lists (`scope, exclusions, responsibilities, boundaries, delivery_requirements, delivery.targets, delivery.conditions`) | Same labelled block for each text element, KEY is its slash path suffix, field path appends zero-based index (e.g. `/content/delivery/targets/0`); for scope selectors and gate boundary enums use the typed metadata rule below instead |
| `delivery.tag` and `status` | `- KEY: VALUE\n` inline escaped scalar; null/empty lists have no line. Definitions only. Member title maps to heading, format to body framing, document/kind to placement |
| Other typed fields (including applicability, witness alternatives, stage/client/role selectors, gate evaluator/freshness/failure and export selector), member versions and provenance | Companion only. Human UI reads typed records and renders these directly; no JSON authoring. Raw spans cover only labelled payloads or instruction bytes, so all other visible text is derived decoration |
| Relations | Under source fields except ownership edges which are represented by placement. Sorted by (kind,to) (index by decision order). Each line `- KIND: [CODE](PATH#k-ID)\n`, relative POSIX path (empty for same view), add ` (full)` or ` (partial: field, field)` before LF for supersession. `criterion_of` / `requires_evidence` / `part_of` use placement, plus the same relation line to the parent when clamped at H6. Selector references stay typed in companion |
| Operational rows | Generated labelled blocks with IDs in `!` namespace; render `- KEY: VALUE\n` using escaped strings/enums and fixed field order below. Null renders `unknown` / `desconocido`; no row implies no claim beyond the sealed slice. Paged lists preserve sealed order and explicit truncation |

KEY is the literal schema key or slash path suffix for lists (machine decoration in both languages); document
titles and the unknown placeholder use the selected project work language. Definition status tokens are literal.
Sealed operational state labels are inputs in the project work language; UI labels use the viewer language.
The companion is a baseline generation. Verify its schema, portable and manifest digests, file inventory,
and each declared file hash and span map against deterministic rendering of that baseline. Reconstruction
does not need the original files on disk. For every supplied file verify its registered path, limits and
UTF-8, capture its actual byte digest and identify the mode:

- Exact view verifies byte equality with that file's reconstructed baseline.
- Explicit IDE import walks the expected baseline frames in order, verifying all noneditable bytes exactly.
  Each editable marked field keeps its exact opening frame and token. Consume raw bytes until the exact
  token-specific end frame (including Mermaid framing when present). Token selection excludes the reserved
  end frame from baseline payloads. For Mermaid it also excludes the end comment delimiter from the payload,
  and the parser validates the baseline fence and refuses an edited payload that can close it early.
  Retain changed line endings, lengths and trailing newlines inside the raw spans. Baseline hashes/offsets
  verify the generation. Derive new spans and hashes from actual bytes. Unknown, missing, duplicate or
  ambiguous frames and edited decoration refuse the file with located diagnostics. Marker-shaped text that
  is not a reserved closing delimiter for that field stays raw data. A collision with that delimiter needs
  correction or explicit typed authoring. No parsing of headings or unframed prose as canonical input.
  Show exact field differences, including sensitive text, before the owner chooses what to stage.
- Instruction views and operational projection rows are exact-only. A changed instruction file remains
  available as an original for explicit mapping or typed authoring. Neither its bytes nor an imported
  projection mutate the canonical or operational record.

Omitted files have no incoming bytes to verify. Record their omission separately from a verified unchanged
file. Refuse an unexpected supplied file or changed baseline metadata; retain original inputs for repair or
explicit mapping. Baseline metadata and marked body edits are proposals, independent of local authority.

For owner acceptance of the format transition, historical v1 keeps the T013 reader and its explicit IDE
import behavior. The proposed v2 path keeps direct marked narrative edits in the IDE. For companion-only
values use typed authoring or an explicit portable proposal against the verified baseline. For edited
unmarked instruction files preserve the raw input and open the explicit mapping comparison. These two v2
lanes replace editing v1 metadata in place and staging v1 instruction headings directly; they present
the resulting proposed values or mapping diagnostics before staging. A failed v2 verification does not
reinterpret the input as v1.

### Explicit partial selection

Verification never selects edits. An explicit, sealed import selection binds the companion digest, supplied
path/digest pairs, selected member IDs, exact field changes to apply, selected relationship operations and
source-to-destination maps, including maps for typed selector endpoints. The UI lists each member under
its canonical home view (criterion with owner, evidence requirement with criterion/gate, all other kinds in their declared view). An index, grouping,
projection or relation target does not make that target selectable via the referencing file. Select a new
record as a complete definition, or select exact changes to a mapped existing record. In either case
only explicitly selected relationship operations are staged. For ordered edges or new members include the
required ownership and order operations, validated as a unit. Relations and typed selector fields may point to omitted entities only via an explicit verified exact destination mapping (including same-project same-kind identity with a
verified current version). Unmapped endpoints refuse staging until resolved. No implicit creation or
update of the endpoint. Incoming relationships from unselected sources remain intact.

A Markdown selection admits only members whose home file was supplied and verified. Omission preserves
local members, fields, links and relative sibling order. New entries append in source order unless an explicit
order operation was selected. Moves and densification are shown in the comparison. Neither omitted file
nor unselected record/edge is a deletion signal. If both baseline and IDE content are available, preview
which exact bytes supplied each selected field. The complete standalone portable envelope has its own
explicit typed selection and mapping; canonical instructions with no exported view can be selected there
from the companion's verified portable payload or in shared authoring. Merely importing any subset of
Markdown, even every exported Markdown file, does not select hidden instructions. A local owner still
confirms exact adoption after prospective graph validation.

### Operational projection

`projection` is `{at:Time, revision:ID, active_phase:ID?, next_task:ID?, summary:list<Row>[0..100], truncated:bool}`;
`Row={kind:definition\|delivery\|task\|run\|gate\|blocker\|evidence, ref:ID?, state:Value?, note:text0}`.
`Value` is the opaque verified owner-record display label (single-line title). Null ref/state means unavailable.
Render fixed field order at/revision/active_phase/next_task/truncated then row fields kind/ref/state/note, with
note a labelled rich block at `/summary/N/note` using the row's index in the full sealed summary and
span ID `!projection`. STATE includes all rows; ROADMAP includes active_phase and delivery rows; NEXT_STEPS
includes active_phase, next_task and blocker rows. Projection sources are the sealed owner query snapshots at
export intent (revision/plan/READY/run/evaluation/delivery); no import uses them as local facts. Sort rows by
kind then by ref (null last), then digest. Snapshot time is input, and projection bytes remain historical.

### Instructions and transition

The canonical instruction view reads DB rules ordered by the tree. D322 ownership v2 keeps optional selections:
none, AGENTS alone, or AGENTS plus either/both wrappers (wrapper dependency on AGENTS is explicit).
Render AGENTS with common rules, wrappers begin exactly `@AGENTS.md\n` then target rules. Active rule only.
For each rule emit an optional escaped heading at H1 for roots, increasing with depth and clamped at H6,
followed by LF, then body verbatim plus LF. There are no machine markers in these instruction views.
Record raw body spans and check full bytes of supplied instruction views on import. The manifest
controls export selection and grants no import selection or runtime authority. Keep existing 60/15 line
caps and per-view byte cap; over-budget or executable/dynamic include directives refuse compatibility export
without deleting the canonical rule. Legacy include text preserved for review; no discovery directive may be
activated in the new runtime. Retain `harness-ownership-1` intact. Proposed `harness-ownership-2` is a closed
manifest `{format, renderer, destination:ID, language, targets:list<Target>}`, with sorted unique
`Target={path,kind:canonical\|support\|companion\|instruction}` for registered exact paths only. A full disk
generation owns all six canonical targets and companion; supporting views are independently selectable if
present, instruction wrappers as above. No implicit acquisition, relinquishment or deletion. T032 seals exact
target selection, reviewed original bytes and path/head baseline, retained generation and separate confirmation.

## Conversion and verification obligations

| Source | Proposed conversion into an explicit mapping draft |
|---|---|
| v1 revision / marked v1 / portable v1 | Read through the historical codec, keep bytes, digests, manifest, root/child order and provenance. Use the identity rules below. Map requirement and criterion strings verbatim; phase objective/tag map to objective and delivery.tag (null delivery if tag absent); task strings and evidence map to their namesakes/evidence_notes. Old sections keep body/format/title/order, with unclassified block types and requirement/phase gaps shown for explicit resolution. Decisions map decision → resolution and retain original provenance and status text. Immutable decisions retain original version and links through read-only adapters; absence of old applicability selectors is shown as unmapped for owner review, never inferred from prose; any portable decision materialization is a projection, with digest and locator back to the original. A legacy partial supersession without a field binding needs explicit applicability mapping for current use, preserving the original relation as history |
| Historical task/phase text, managed blocks, original Markdown | Retain source bytes and locator/hash; parse historical formats only with registered readers. Preserve explicit structured parent/dependency/criterion records via reviewed mappings. Convert an actual historical subtask list into ordered fresh children, storing each source string verbatim as outcome and reporting a required title/criterion if absent. Do not parse arbitrary prose mentions as links. Owner supplies missing intent, roles, gate definitions, scopes and relationships; incomplete work remains a working copy |
| v1 instruction sections or loose originals | Preserve original client target, headings, body, order and bytes, including wrappers and nesting/normalization reports. Stage as unclassified inputs until owner explicitly resolves applicability and discovery/conflict text. Preserve parsed split spans and the whole source, including CRLF/preamble/unmapped bytes |
| Imported operational material | Current STATE/projection is view-only. Strict envelope refuses approval/READY/evidence/usage/run keys. Outside that envelope archive original claims as source-claimed consultation; no satisfaction, authorization, operational replay or inferred lineage |

### Identity, mapping and order

The v1 identity is keyed by source project and item ID; the original document and code are retained
metadata. Resolve an exact historical reference using format, source project, revision, item ID,
version and verified digest. The conversion preview contains these source bindings, each proposed
destination ID/kind/code/version, and explicit unresolved or history-only entries. Persist the accepted
mapping with its version and digest. Repeat conversion resolves the existing mapping or refuses a
conflicting remap. Foreign IDs are source labels, requiring an explicit destination map or fresh ID.

- Same-project requirement, criterion, phase and task keep their local ID and kind, with a new version
  if their schema/content changes. D296 lineage applies only to compatible task identities or explicitly
  confirmed replacement. New project intent, subtasks derived from a legacy string list, gates and
  evidence definitions are new identities.
- A v1 decision keeps its ID and immutable historical version. A v2 member for that ID is a read-only,
  versioned schema projection pinned to the exact v1 version, with its own v2 digest and projection
  version. The renderer and mapping use that version without appending a semantic decision edit.
  Resolve earlier decision references through that projection or the historical adapter as appropriate.
  Any new decision meaning requires an independent superseder under the normal rules.
- A v1 section always keeps its original ID and kind in history. Allocate a fresh v2 ID for its block
  or instruction and record the typed mapping with source and destination kinds. Different section IDs
  map separately even when their slugs match across documents. Check all v2 codes against per-kind
  project uniqueness and reserve them in the preview. Preserve an available slug or explicitly map a
  colliding one to a valid distinct code, e.g. a document-prefixed slug. Resolve remaining collisions with
  a reviewed distinct code before adoption. Never match, merge or silently rename records by slug.

Rebind a current typed edge or selector only through verified endpoint mappings and validate its v2 kind,
scope and cardinality. If its target has no valid current representation, retain the historical edge and
report an unresolved current relation. Owner review must resolve or explicitly classify it as historical
where allowed. Historical references in original content still resolve using the exact original source
binding and adapter. Preserve literal prose and links as data; never rewrite or derive typed edges from
them. A historical source lookup cannot grant runtime source access. Preserve original sibling order
within each mapped document/parent/target group. Reparenting, splitting or merging order groups needs
explicit reviewed destination positions; no sorting by code. Assign dense positions only in the new
revision. Histories, hashes, renderer generations and decision contents are never regenerated in place.

[Examples and negative vectors](P002-T030-fixtures.md) anchor the grammar. T031 verifies ownership/order/cycles,
old-vs-new revisions and decision/lineage immutability. T032 verifies byte round trips in both languages,
projection poisoning, spans, partial import, compatibility budget and exact recovered Git export.
T033 verifies scope selection and prospective graph/preview diagnostics. T036 verifies mapped intake and
loss reporting before adoption, T037 checks readable editing and T038 verifies restored historical parity.
