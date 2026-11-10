# P002-T030 — Synthetic vectors and evidence

Part of the [T030 review record](P002-T030-contracts.md). These are review vectors for the
[proposed grammar](P002-T030-model-codec.md), not fixtures of the implemented product. All project content
is synthetic. There are no actual runs, credentials or private data.

## Codec and relation vectors

The [semantic fixture](P002-T030-fixtures/semantic.json) shows all six documents and canonical instructions.
Assume an earlier accepted revision contains the old task and D001 unchanged, an owner confirms D002,
and the confirmed task and phase validation plans include `sample-check` and `phase-check` respectively.
Local adoption and confirmation supply those facts. The fixture alone conveys no authority. Wrap it in the standalone envelope with its canonical SHA-256 for transport.
For the es variant change only the envelope language and regenerate using the same source values;
`Return **7**.`, CRLF, IDs and ordering are identical. Example emitted specification prefix below
(visualization shows LF framing, and the body payload terminates in CRLF; the digest is over actual bytes).

```markdown
# Specification

<a id="k-purpose"></a>
## purpose — Purpose
**body**
<!-- harness:field purpose /content/body 0 -->
Return **7**.

<!-- harness:end 0 -->
- status: active
```

The es prefix uses `# Especificación` in place of `# Specification`. For the fixed prefix above the raw
body starts at UTF-8 byte 119 in en and 121 in es (zero based). The Architecture Mermaid body remains
`flowchart LR\n  A --> B` inside a mermaid fence. NEXT_STEPS shows the active phase/next task from the
sealed projection, the task/subtask tree, then gate with its evidence requirement. DECISIONS shows an
index plus a `supersedes` relation with `(partial: consequences)`; ROADMAP shows planned local delivery
and independent sealed operational projection. STATE may display an unavailable ref as `unknown` /
`desconocido` with the note below the projection. AGENTS optional output is exactly
`# Sample rule\nKeep the review bounded.\n## Counter rule\nCheck the count.\n`. It omits `rule-hidden`.
No exported instructions is also valid with the same DB rules. The v2 companion binds view bytes and positions. A valid canonical portable hash cannot authorize a
forged Markdown decoration or confer operational authority.

| Vector | Expected result / owner |
|---|---|
| SPECIFICATION: insert an extra unframed paragraph, or remove required purpose root | Decoration refusal / missing singleton on adoption. Keep original bytes. T031/T032 |
| ARCHITECTURE: move diagram under specification, put Mermaid into a component, or reverse diagram/component dependency to close a cycle | Located cross-document ownership / format / cycle refusal. T031/T032 |
| DECISIONS: edit D001 resolution or add second successor claiming the same field, or import an owner approval key | Frozen member / overlapping supersession / unknown key. Historical D001 remains. T031/T032 |
| ROADMAP: add `installed: true` to planned delivery, duplicate phase position or add phase dependency to a task | Unknown key / dense order / endpoint refusal. T031/T032 |
| NEXT_STEPS: make the subtask its own ancestor, use unknown phase/task/architecture/gate ref, duplicate owner, or attach evidence to a task directly | Cycle / missing endpoint / owner cardinality / endpoint refusal; keep work. T031/T033 |
| NEXT_STEPS: put evidence `status: passed` in criterion or use a gate `evaluator: shell` | Unknown operational key / unsupported evaluator. T032/T033 |
| STATE: change `unknown` to `satisfied` in the Markdown or put READY into the semantic note schema as a field | Byte mismatch / unknown key. A prose claim in an allowed body stays prose. T032/T033 |
| Instructions: invalid stage, empty scope, unknown component, duplicate position, or wrapper without selected AGENTS | Located invalid selector/scope/target/order/manifest. Over-budget output refuses only that generation. T031/T032 |
| Exchange: swap en header into es generation, truncate a UTF-8 span or append a fake marker to decoration | Deterministic byte mismatch. Marker-shaped text other than the reserved delimiter for that field remains data. T032 |
| Exchange: duplicate JSON keys, missing nullable key, unknown format, bad digest, unsafe path alias, foreign label collision | Strict refusal or explicit unresolved identity mapping. T032/T036 |
| Partial import: select task but omit prerequisite; supply the exact local mapped target, or leave it unresolved | Only explicitly selected changes stage; omitted records/order are retained, and unresolved endpoints refuse. T031/T032 |
| v1: old subtask with trailing newline and a prose mention of a decision/check; old rule includes a discovery directive | Preserve exact string, order and origin, allocate fresh child ID and require missing semantics; no inferred link, evidence, permission or active discovery. T031/T036 |

## Technical review vectors

Run `python3 docs/phase/P002-T030-fixtures/review_vectors.py` from the repository root. The script uses
synthetic inputs, local standard-library assertions and small transition models. It checks the stated examples
against the semantic fixture and expected byte/identity/binding relationships. Product validators, storage,
codec and browser behavior are future acceptance work.

| Review point | Synthetic input and expected result |
|---|---|
| Evidence before and after effects | The confirmed plan maps `criterion-p` to `task` and requires its committed acceptance. First admit and launch I02 with exact authority, prerequisite and scope guards, with no candidate/check result. Validate candidate A; record `sample-check` under task A. I03 reviews the exact candidate and terminal result. Passing validation supports `criterion-t`, `criterion-s`, `criterion-r` and the acceptance-only `gate` in the same task context. Independent acceptance and exact delivery supply the task receipts. Run `phase-check` on the current phase snapshot, including the task commit with unchanged sealed check inputs. Verify the mapped task receipt and distinct phase witness, perform I04 if required, then mark READY. A failed `sample-check` still permits authorized diagnostic I03, but blocks acceptance, export and READY. Moving that check to admission or validation-start creates an invalid dependency; changing the task's check inputs invalidates its phase contribution |
| v1 identities | `s-spec` and `s-arch` are v1 sections named `notes`, in specification and architecture respectively at position 1. Allocate `b-spec/notes` and `b-arch/architecture-notes` as distinct block IDs/codes in their original order groups. Map `s-rule` to fresh instruction `i-rule`. Its literal link to the original specification section is unchanged and resolved only in the historical context using the verified v1 reference. A current typed ref uses the explicit mapping. Original v1 digests remain identical |
| Partial marked exchange and IDE edit | Supply only `AGENTS.md`, whose exact 72 bytes are shown above, with the full companion. The body spans start at byte 14 (24 bytes) and 55 (16 bytes). Select the scope field of existing mapped `rule-scoped`; its component selector points to `component` whose ARCHITECTURE home is omitted. Verify its exact local mapping to `local-counter@4`, then stage just the selected field. Omit that map and staging holds. The parent, omitted component, their other relationships and `rule-hidden` stay unchanged. Separately replace only the marked purpose body with `Return **7 tokens**.\r\n`; retain frames, derive new length/hash, show the difference in the import preview |
| Typed planner bypass | Owner confirms `src/counter.py` and catalogue `sample-check` with argv `["python3","checks/count.py"]` and 30 s timeout. The matching typed request reaches I02 without I01 or I13. Missing limits, requesting `docs/STATE.md` or changing the command behind the same check ID refuses before launch. A queued legacy reconciliation has no fresh typed admission; only previously recorded effects are eligible for exact reconciliation |
| Saved copy and consent recovery | Save edits to purpose and scope. Stage derives both; a caller-supplied operation list is rejected. Editor A reserves and adopts once, losing the reply. Editor B's temporarily empty result cannot reserve or fence while A is unresolved. After loss of the browser key, authorized domain lookup recovers the same settled result and exact replay has one effect total. If the old reservation was still in transit, a successful empty-slot recovery fence rejects its old generation and a late dispatch. Explicitly cancelling an undispatched reservation leaves a tombstone |
| Delivered task coverage renewal (`check_delivered_coverage_renewal`) | Tasks A and B both deliver with distinct authorized STATE generations. B changes the check configuration used by A and preserves A's own code and generated artifact. B's contribution and the phase check pass, but A's stale contribution holds READY. Exact owner admission, current validation and review, and separate acceptance renew A's coverage on B's snapshot. READY passes with exactly two deliveries and unchanged historical digests. Losing either required generation proof holds READY. Changing only A's generated artifact requires a new delivery. Changing only STATE with a valid generation stales B's check because it reads STATE |
| Recovery view race (`check_recovery_fence`) | B reads an empty recovery view at generation 1. A reserves and settles before B fences, leaving generation 1 and an empty reservation slot. B's stale view is refused. B refreshes, presents A's result and confirms that view before the fence advances to 2 and enables fresh consent. In the opposite ordering, B fences the empty view first and A's delayed generation-1 reservation and dispatch are refused. A and B have distinct envelopes and digests over the full envelopes including the keys |

Additional negative and routed authoring cases are in
[gates and editing](P002-T030-gates-editing.md#fences-and-test-matrix).

## Offline boundary probe

From the repository root run `python3 docs/phase/P002-T030-fixtures/probe.py` on a macOS host with the
local `sandbox-exec` and system Git. The script uses a temporary synthetic repo, no user config, and no
service startup. Observed on Darwin arm64, Python 3.14.4 and Apple Git 2.50.1 (Apple Git-155):

- Positive projection and noncanonical Markdown preserved.
- Eight path-scoped OS denials (original, renamed copy, symlink, hardlink, mixed file, nested instructions,
  external original and retained copy) via a child shell process; two Git object lookups denied (host Git
  object path behind the local deny and projected workspace without a Git object store).
- Bounded synthetic slice with source and exposure digests; syntax check, test and candidate retest passed.
- Host exact code+document tree matched the independent Git worktree reference,
  `2b0a6e3490d7622062b8dbcac5a9c641978feb4d`. Ref CAS passed once and rejected a stale expected ref;
  selected source blob remained unchanged. Two independent temporary directories produced identical results.

The local deny rule covers a single synthetic storage subtree. It deliberately tests a narrow OS
primitive, not an allow-all-except-paths production profile. The bounded source read simulates capture
and receipt, not a broker/tool integration. The probe does not exercise guest isolation, all possible
copy/provenance detection, transport/network denial, actual client startup or provider behavior, and
cannot qualify a native profile. The [follow-on protocol](P002-T030-d321.md#evidence-and-gate-disposition)
specifies the evidence required to resolve D321 feasibility.
