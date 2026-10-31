# Repository maintenance — branch cleanup and commit messages

2026-10-31. Owner-requested repository maintenance, separate from product task P002-T014. The owner authorized
deleting leftover branches and committing/pushing the documentation directly on develop without a new branch.
Starting point: clean develop at `8e3a49c`, equal to origin/develop. No product behavior or release is changed.

## Branch cleanup

Checked local branches, commit ancestry, worktree usage and actual remote heads. Deleted 18 local topic branches:
17 tips were already ancestors of develop; one unmerged proposal was obsolete. Only the current worktree exists,
on develop. Remote heads are main and develop, so no remote topic branch required deletion. Both permanent local
branches are retained; the local main pointer is unchanged.

Merged local branches removed:

- `docs/p002-plan`
- `docs/p002-t001-contracts`
- `docs/p002-t002-feasibility`
- `docs/p002-t005-domain-operations`
- `docs/record-0.1.3-release`
- `feat/ot002-question-answers`
- `feat/p002-t003-langgraph-runtime`
- `feat/p002-t004-structured-knowledge`
- `feat/p002-t005-domain-operations`
- `feat/p002-t006-operations-tracing`
- `feat/p002-t007-frozen-context`
- `feat/p002-t008-scoped-tools`
- `feat/p002-t009-judge`
- `feat/p002-t010-permissions`
- `feat/p002-t011-db-intake`
- `feat/p002-t012-knowledge-editing`
- `feat/p002-t013-document-roundtrip`

Also removed `docs/one-off-release-route` at `ed326241aa318ae40c3b3d976014d2c31c284192`. Its sole unique commit
proposed optional main/develop routing under a draft D250. Inspection confirmed that the accepted D261, integrated
by `e2aec3f`, replaced that proposal with the current latest-release rule. The obsolete proposal was not merged.
Merged branches used normal deletion; the inspected obsolete proposal required explicit forced local deletion.

## Commit message guidance and delivery

[D295](../DECISIONS.md#d295--brief-descriptive-commit-messages-with-implementation-bullets) records the owner's
rule: a brief descriptive English subject, a blank line and short bullets describing implemented changes,
following recent commit patterns. AGENTS.md is the single instruction source; its existing client wrappers
inherit this guidance. No product commit-message generator or historical commit is changed.

The maintenance source is complete locally. Documentation checks passed for all 111 tracked Markdown files
and explicitly for this new record; `git diff --check` passed and the full documentation diff was inspected.
Branch enumeration confirms that only main and develop remain locally. Commit and push to develop are authorized.
STATE/NEXT_STEPS still identify T014 as next; ONE_OFF_TASKS is empty. Product tests were not run for this
documentation-only change. Release/publication/installation remain pending for P002 under its existing route;
this maintenance does not authorize them.
