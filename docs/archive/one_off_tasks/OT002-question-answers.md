# OT002 — Question-first reviewer answers, full-width layout and live activity (0.1.3)

Work notes for one-off task OT002, released as `0.1.3`
([D239](../../DECISIONS.md#d239--one-off-tasks-released-as-patch-versions)). Decision:
[D240](../../DECISIONS.md#d240--question-first-answers-and-the-live-activity-rail).

## Scope as implemented

- **Answers (OT002 as planned).** Onboarding, definition and phase planning render the reviewer's open questions
  before the conversation history and its free composer: open blocking questions first, informative and deferred
  after, declared pending items apart. Each question has its own answer field; drafts live in browser local storage
  (`harness-planning-answers-v1:<project>:<conversation>`, per question id, with the question text and source turn).
  An explicit review shows the exact message for one answer, the selection or all prepared answers and sends it as
  one ordinary planning message through the existing endpoint (expected version, workspace idempotency key). The
  message carries `[q:<12 hex>]` markers and the question text. States (draft, waiting, resolved, still asked, not
  reviewed) are read from the turns; drafts for questions no longer asked are offered to include or discard; the
  whole message must fit 20,000 characters. Deferral stays a separate control. The free composer is labelled as
  "Other message to the reviewer" when questions exist.
- **Scope added by the owner in the implementation session.** Use the full window width on every page; a sticky side
  rail (`Workbench`, CSS container query from 800 px of body width) on project, phase, task, run, chat and planning
  pages; and a live activity panel that shows what the agent is doing in the latest run, read from the existing
  run events endpoint. Run states `ANSWERING`/`DISCOVERING` got labels. The onboarding conversation picker is laid out
  side by side with its form.
- **Not changed.** No API contract, schema, stored format, question derivation, blocking, deferral or adoption rule.
  The exported OpenAPI changes only its version string; the generated client types are unchanged.

Files: `frontend/src/answers.ts`, `frontend/src/pages/Answers.tsx`, `frontend/src/run-activity.ts`,
`frontend/src/Activity.tsx`, `Workbench` in `frontend/src/ui.tsx`, `Planning.tsx`, `Chat.tsx`, `Task.tsx`, `Run.tsx`,
`RunEvidence.tsx`, `Project.tsx`, `Phases.tsx`, `styles.css`, en/es catalogs; tests `answers`, `run-activity`,
`question-answers` and `live-activity`; flows (onboarding, definition, task run, chat), SPECIFICATION §8,
ARCHITECTURE §7, CHANGELOG, READMEs and version `0.1.3` in `pyproject.toml`, `uv.lock`, `api/app.py`,
`frontend/package*.json` and `frontend/openapi.json`.

## Design tooling

The frontend-design plugin was invoked in this session as the skill `frontend-design:frontend-design` (Claude Code
plugin cache `claude-plugins-official/frontend-design`), with the brief: an existing token-based design system, a
question-first answer workspace, full-width dashboard layouts with a right rail, and a live agent-activity rail,
consistent with the system, accessible, en/es, light/dark and responsive. The plan derived from it, after reviewing
it against the plugin's list of templated defaults:

- **Color and type:** the existing tokens and system font stacks only (no new fonts or dependencies). Amber keeps
  meaning "waiting on you" (blocking questions, items to decide); blue means "running now".
- **Layout:** main column plus a 280–440 px sticky rail, side by side only when the body is wide enough, stacked
  below otherwise; the main column first in reading and keyboard order. Text blocks keep their reading measures.
- **One distinctive element:** the activity trace. A vertical line of nodes whose shape encodes the kind of step
  (filled dot for a message, square for commands, edits and validations, dashed for thinking, diamond for warnings,
  small dot for lifecycle) and whose color encodes how it ended; the only unprompted motion is the pulse of what is
  running now, disabled by `prefers-reduced-motion`. A "now" line shows the role and what is being streamed.
- **Revisions made against the plugin's critique:** per-step monospace tags were removed (they repeated the label);
  numbered question markers were dropped (the cards are not a sequence); streamed prose uses the interface font
  (monospace only for commands and paths); copy names actions by their effect ("Send as one turn", "Review selected").
- **Self-critique from screenshots:** the review panel moved above the sticky batch bar and the bar hides while
  reviewing (it covered the preview in narrow columns) and is static on phones; the chat list narrowed and the
  container threshold lowered so the rail appears at 1440 px; the "sent" notice clears when the reviewer answers;
  the onboarding picker form wraps on phones.

## Checks run

- `node --test frontend/tests/*.test.mjs`: 188 pass (26 new): pure answers (storage isolation and corruption,
  composition and markers, selection rules, code-point limit, standings, resolution, pruning, sent marks), pure
  activity folding (Claude and Codex records, partial deltas, validations, unknown events, merge bounds), the live
  feed's backfill and cursor requests (en/es), and component/request tests of the answers: one answer, selected set
  and all prepared answers each in exactly one request with the idempotency key and expected version (en/es);
  partial submission with waiting/read-only state and no submission while queued; failed turn shown as not reviewed;
  aggregate limit; drafts across a remount and 409/500 errors; new question set never reattaching a draft and an
  explicit earlier-answer inclusion; stale review after a version change; double click; deferral with a reason;
  read-only confirmed conversation; onboarding document order (answers, conversation, composer, rail) in en/es.
- `npm --prefix frontend run check` and `npm --prefix frontend run build`: pass (the existing Mermaid chunk-size
  warning is unchanged).
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 10 tests OK.
- `uv run --frozen --offline pytest -q`: 2072 passed, 2 skipped, 29 subtests passed, 0 failed.
- `alembic check` on a temporary database upgraded to head: no new upgrade operations.
- `scripts/export_openapi.py` and `npm --prefix frontend run generate:types`: only the OpenAPI version string changes;
  the generated client types are identical.
- Local links and anchors of the changed documents: 257 checked, none broken; `git diff --check` clean.
- Synthetic visual/functional QA in Chrome: the repository's Vite dev server with an in-browser API mock injected
  from a scratch script outside the repository (synthetic project, conversation, questions and scripted Claude-style
  event streams; no service, database, provider or real data). Checked at 2560 and 1440 px and in 390 px frames,
  dark and light themes, English and Spanish: onboarding with drafts, review of all prepared answers, sending as one
  turn, the rail switching to the new turn and streaming, waiting → resolved/new questions, the resolved list and
  draft pruning, drafts persisting across a reload, task/run/project/chat/phase rails, no horizontal overflow on
  phones; keyboard only: typing, Tab/Space to select, Enter on the review button moving focus to the review heading,
  visible focus rings.

- Release package: `scripts/build_distribution.py --offline` from the tree of `v0.1.3`, then
  `scripts/check_distribution.py --cache-dir .local/uv-cache` (exact members, metadata, licenses, `SHA256SUMS`,
  isolated wheel journey: OK; without the repository cache the isolated install cannot find the wheels offline).
  `my-harness-0.1.3-distribution.tar.gz` has the same layout as 0.1.2, SHA-256
  `1496547a9fb8d2d11d0031e2410bc50db62c984fe3cf19e4738964185a4bcc91`.
- Released through pull request #2 (`develop` → `main`, merge commit `64c21d0`, lightweight tag `v0.1.3`) and
  published as the GitHub Release `v0.1.3`; the downloaded asset matches its `.sha256` and the local build byte for
  byte.

## Not run or not covered

- No real service, database or provider was used for the visual QA; the mock reproduces documented shapes, not a
  recorded run. The live feed against real Claude Code/Codex streams is covered by synthetic records shaped like the
  repository's stream fixtures and probes only.
- Other browsers, screen readers, a real long-running run with thousands of events, and phase pages with a full
  phase definition in the browser (the mock served only the task list) were not checked.
- Drafts are per browser; a conversation answered from two browsers shows server-derived states in both, but each
  keeps its own unsent drafts.
