# P001-T005 — Billing/reference controls and metrics UI

T005 is split by [D263](../../DECISIONS.md#d263--p001-t005-split-accounting-page-and-billingreference-control-contracts)
into two sequential deliveries; it is complete when both are delivered. One section per delivery.

## T005a — Accounting UI

Status: complete; source delivered through `feat/p001-t005a-accounting-ui` (branched from `develop` at `c769b0e`).
Owner: P001-T005a; implementation detail
[D264](../../DECISIONS.md#d264--accounting-page-routes-exact-amounts-and-derived-reference-period).
Delivery route: topic → `develop`/`origin`, as for T001–T004; commit, merge and push were authorized by the owner after
review. Git records the source and merge commit IDs; the local topic branch is removed after the merge.
No task release or version bump: 0.1.9 qualification/publication stays at P001 closure (T006). Distribution, operator
installation and service restart are outside T005a.

### Implemented boundary

| Area | Implementation |
|---|---|
| Page | `frontend/src/pages/Accounting.tsx` (own lazy chunk): selection policy and cohorts, filters, coverage, amounts by basis, tokens with cache hit and wall throughput, task spend, paginated groups (13 D262 dimensions, root only globally), paginated invocations and the invocation detail with paginated valuations. |
| Helpers | `frontend/src/accounting.ts`: query building (UTC days, inclusive last day → exclusive `started_before`), group → filter mapping, exact decimal/money formatting without floats, bucket state, reference period state, observation age, reason keys, capture facts and line rates. |
| Routes/navigation | `/accounting` and `/projects/:p/accounting` (`router.ts`, `Page.tsx`), sidebar and project navigation (`Shell.tsx`), a link on Statistics (`stats.accounting`); the global page is mounted on a query-only archive and during configuration. |
| Texts | 285 en/es keys (`nav.accounting`, `stats.accounting`, `accounting.*`), including the 28 calculator/comparison reason codes. |
| Style | `.table-scroll` became a positioned container so visually hidden column headers cannot widen the page. |

No API, OpenAPI/client type, schema, migration, configuration format, backend module or flow changed. Statistics keeps
its `metrics-1` panels and wording; it only gains the link sentence.

### Acceptance coverage

| Criterion | Evidence |
|---|---|
| Global and per-project page, linked from Statistics and the project; archive without mutation controls or polling | Router round trip and trails (`router.test.mjs`); component test renders the page in live and archive modes: only `/api/managed/accounting/*` (and `/projects`) GET reads, no `/metrics/*` read, no timer in the archive (also after opening a detail), CLI commands only when live. |
| Coverage and one amount per compatible bucket | `amount` shown only when the API gives it, otherwise the known subtotal with a `partial` mark; API USD, credits and a counterfactual subscription equivalent render as separate rows; unpriced reasons grouped with their code. Exact decimals tested to 12+ places, large integers beyond 2^53 and en/es separators. |
| Tokens, cache hit, throughput, task indicators | Category sums with contributors/partials; null categories show "no data" while an observed zero stays `0`; ratios state their invocation and excluded counts; task indicators state their denominators and stay "no data" when the API returns null (acceptance unknown or unpriced). |
| Groups, invocations, detail | Groups narrow the filters only through API-accepted filters (unknown values and roots offer none; mixed/unknown effective models filter by kind; phase/task only in a project). The detail shows requested versus effective model and kind, the client's echoed selection, provider/client version, launch/outcome/native status, measured and reported durations, turns, tools, capture provenance, alternative components (never added), valuations with lines, rates, tariff/identity references (source, observation age), effective-period state, discrepancy and reasons. |
| Selection policy | Admission valuation by default, or one cohort selected from the paginated list; a `BUILDING` cohort is announced as incomplete; selecting it re-reads every panel with `cohort`. Backfill/repricing are named as CLI commands only. |

### Validation

| Check | Result |
|---|---|
| Focused | `node --test frontend/tests/accounting.test.mjs`: 7 passed (5 helper tests, 2 page renders: en/live and es/archive). Router tests extended. |
| Full (`scripts/check --frontend`) | unittest 10 ran; `alembic check`: no new operations; pytest **2339 passed, 2 skipped, 29 subtests passed** (existing 11 warnings); Node **238/238**; frontend build (`tsc` + Vite) passed, with the existing large-chunk advisory. |
| Documentation | `scripts/check-docs`; `git diff --check`. |
| Synthetic visual QA | Chrome against a temporary Vite entry that mounted the real app shell and page with a synthetic in-page `fetch` (no service, database, provider or private data), removed afterwards. English/dark and Spanish/light; live and query-only archive (no CLI commands, only read controls: filters, cohort selection, pagination, details); keyboard: cohort selection with Enter keeps focus and `aria-pressed`, filter form submits with Enter, opening a detail moves focus to its heading; 390 px content in an iframe (the window itself could not be resized): no page-level horizontal scroll after the `.table-scroll` fix, tables scroll in place; no console errors. QA found and fixed the cache-hit percent spacing and an unreadably small period mark. |

Omissions: no real service, operator database, real accounting data, provider or CLI; no real mobile device or
emulation, other browsers or screen readers; the per-project route and the configuration-mode mount were checked by
types, router tests and code review, not in the browser. No distribution build, installation or service restart.

## T005b — Billing-profile and reference controls

Status: complete; source delivered through `feat/p001-t005b-billing-controls` (branched from `develop` at `0d51449`).
Owner: P001-T005b; implementation detail
[D265](../../DECISIONS.md#d265--billing-controls-reference-listing-and-save-time-billing-review) within D263.
Delivery route: topic → `develop`/`origin`, like T001–T005a; commit, merge and push were authorized by the owner after
review. Git records the source and merge commit IDs; the local topic branch is removed after the merge. No task release or version bump: 0.1.9 qualification/publication stays at P001 closure (T006).
Distribution, operator installation and service restart are outside T005b. With both deliveries integrated, T005 is
complete.

### Implemented boundary

| Area | Implementation |
|---|---|
| Reference API | `api/configuration.py`: `GET /references` (page ≤ 50, no configuration-setup dependency), `POST /references/preview`, `POST /references/import`; models `ReferenceBundleRead`, `ReferenceSchemeRead`, `ReferenceImportRead`. `storage/accounting_views.py` `references`/`bundle_view` (read-only, packaged first, damaged rows listed as unavailable). `storage/accounting_operations.py`: preview digest seals bundle/raw digest/count/conflicts only; store-time conflict → `reference_conflict`. |
| Save-time review | `services/configuration_editing.py` `billing_review`, called by `ConfigurationRepository._preview` (`storage/configuration.py`): `billing_configuration_refused` with path-free details, `effects.billing_unknown`. `storage/billing.py` `choose` is the pure profile choice shared with the frozen binding. 409 diagnostic `setup.billing_refused`; reference errors `setup.reference_invalid`/`setup.reference_conflict` (en/es). |
| UI | `frontend/src/billing.ts` (pure checks mirroring `billing_profiles`/`selection`, scheme fill, resolution), `BillingFields.tsx` (`GlobalBilling`, `ProjectBilling`, `ReferenceList` with import). Mounted in the global editor (`Configuration.tsx`), the project editor (`ProjectProfile.tsx`) and read-only on the global accounting page (`Accounting.tsx`). Save impact lists unknown inherited roles; refusal lines show project, setting and code (`configuration.ts` `refusalLine`, toast via `ui.tsx`). 83 en/es `billing.*` keys. |
| Contracts | `frontend/openapi.json` exported and `api.generated.ts` regenerated with the README commands. No schema, migration, configuration format, flow diagram node or CLI contract change; `accounting-references` keeps its preview → confirm usage with the new digest semantics. |

### Acceptance coverage

| Criterion | Evidence |
|---|---|
| Explicit, previewed conversion; guided global profiles/conditions/defaults and project selections; TOML complete; loading never converts | `billing.test.mjs` (conversion changes only `format`; field rules; defaults by provider; scheme fill keeps conditions); `configuration.test.mjs` (bundles read only after conversion; profile added only with a provider; scheme fill; Codex profile not offered to the Claude executor; preview body has v10, the exact billing table and the untouched `CUSTOM` environment); `project-profile.test.mjs` (v2 conversion, per-role options by provider, inherited/selected resolution, agents unchanged, review alone saves nothing). Existing TOML/form round trips unchanged. |
| D263 save-time validation | `test_billing_controls.py`: unavailable bundle refused with its field, then accepted after an explicit import; explicit selections missing or provider-mismatched refused with project/role/setting; a v9 global lacks every selection; inherited unknown defaults reported for v2 and v1 projects; a global save removing or re-providering a profile selected by a derived copy names the project, while other billing edits derive the copy and report its unknown role. |
| Reference routes, idempotent digest, size/conflict/archive | API test: listing never inserts rows; preview, stale refusal, import, retried confirmation returning the same sealed report with 0 inserted rows; pagination; invalid bundle and > 1 MiB → 422; restored archive lists the packaged bundle and refuses both POSTs (409 `restored_read_only`). `test_usage_accounting.py` updated for the stable digest. |
| Billing-only saves keep technical receipts; frozen jobs keep their binding | v1 → v2 billing-only conversion previews `preparation_required: false` and activates with the existing receipt; the T003 binding tests (frozen revision, sealed job revision) still pass on the refactored `choose`. No authentication, credential or machine-wide setting is read or written by any of these paths. |

### Validation

| Check | Result |
|---|---|
| Focused | `scripts/check tests/product/test_billing_controls.py tests/product/test_usage_accounting.py tests/product/test_configuration.py tests/product/test_configuration_api.py`; `node --test` of `billing`, `configuration`, `project-profile` and `accounting` tests. |
| Full (`scripts/check --frontend`) | unittest 10 ran; `alembic check`: no new operations; pytest **2345 passed, 2 skipped, 29 subtests passed** (existing 11 warnings); Node **247/247**; frontend build (`tsc` + Vite) passed. Final run after the QA fixes and documentation. |
| Documentation | `scripts/check-docs`; `git diff --check`. |
| Synthetic visual QA | Chrome against a temporary Vite entry mounting the real configuration, project editor and accounting pages with a synthetic in-page `fetch` (no service, database, provider or private data), removed afterwards. English/dark and Spanish/light; unconverted and converted global form, scheme fill, condition warnings, save impact with an unknown inherited role, billing refusal naming project and settings (es), project selections (es), reference list and import preview → confirm → result, archive accounting page with the list and no import control; 390 px iframes of the three views: no horizontal overflow; keyboard: name → provider by type-ahead → Add with Enter keeps focus on Add. QA found and fixed an observation range rendered as `[object Object]` and a silent no-op when adding a profile without a provider. |

Omissions: no real service, operator database or configuration, provider, CLI or real reference bundle beyond the
packaged one in pytest; no real mobile device, other browsers or screen readers; macOS select popups were not driven
by arrow keys (type-ahead was used). The CLI `accounting-references` was not re-run by hand (its module paths are
covered by pytest). No distribution build, installation or service restart.
