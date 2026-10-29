# P002-T002 — Runtime, provider and discovery feasibility

Status: **completed (feasibility; documentation and probes)**, 2026-10-29. Findings are evidence from
bounded probes; [D280](../DECISIONS.md#d280--langgraph-1218-dependency-set-placement-and-runtime-hygiene) and
[D281](../DECISIONS.md#d281--per-invocation-mcp-broker-transport-and-minimum-client-capability-contract) were
**accepted by the owner** on 2026-10-29. No product code, `pyproject.toml`, `uv.lock`, schema, API, prompt,
configuration, catalogue or UI change exists; the product behaves as 0.1.9.

Owner/delivery: P002-T002, branch `docs/p002-t002-feasibility` from local `develop` at `bd1705e` (T001 merge; local
`origin/develop` was still `a000e03`, T001 not yet pushed). Route: topic → `develop`, then part of the
**0.2.0** phase release (D253). T002 has no individual release, publication or installation.
Binding design: [T001 contracts](P002-T001-contracts.md) (§9 tool contract, §12 gates), [flows](P002-T001-flows.md)
FL09/FL13, [threats](P002-T001-threat-model.md) TM16/TM19, D269 and D275. Basis B02, B08–B09, B23.
Probe sources: [`P002-T002-probes/`](P002-T002-probes/README.md).

## 1. Authorization and environment

The owner authorized, for this task: network access for downloads into isolated scratch environments (outside the
repository; nothing installed globally, no change to the project lock), and **minimal real runs** of the installed
Claude Code and Codex CLIs in a disposable synthetic repository with a stub MCP server, read-only, without global
configuration changes. Adding the dependency itself belongs to T003 under the accepted D280.

| Item | Observed |
|---|---|
| Platform | macOS ARM64 (Darwin 25.4.0), CPython 3.14.4, uv 0.12.19 |
| Claude Code | 2.1.312; `--model haiku` reported as `claude-haiku-5-5`, `--effort low` |
| Codex | codex-cli 0.165.0; `--model gpt-6.1-sol` requested, `model_reasoning_effort="low"`; the `exec --json` events carry no reported model |
| OpenCode | v2.0.32 installed; only `--version`/`--help` read (future work, no runs) |
| Synthetic repository | One commit with a README; unchanged after all runs (`git status` clean) |

## 2. LangGraph feasibility (G01, G02 feasibility)

### 2.1 Dependency set

`uv add langgraph==1.2.18` on a scratch copy of the project's `pyproject.toml`/`uv.lock` resolves 57 packages
(30 before): **27 added** and **no existing pin changed** (pydantic stays 2.14.0; langgraph needs `>=2.7.4`).
`httpx2-jsfetch` is locked with an `emscripten` marker and is not installed on macOS, so 26 packages install.

| Package | Version | Licence | Wheel |
|---|---|---|---|
| langgraph | 1.2.18 | MIT | pure |
| langgraph-checkpoint | 4.3.1 | MIT | pure |
| langgraph-prebuilt | 1.1.1 | MIT | pure |
| langgraph-sdk | 0.4.10 | MIT | pure |
| langchain-core | 1.7.1 | MIT | pure |
| langchain-protocol | 0.0.20 | MIT | pure |
| langsmith | 0.14.15 | MIT | pure |
| orjson | 3.13.0 | MPL-2.0 AND (Apache-2.0 OR MIT) | cp314 arm64 |
| ormsgpack | 1.13.0 | Apache-2.0 OR MIT | cp314 |
| xxhash | 4.0.2 | BSD-2-Clause | cp314 arm64 |
| zstandard | 0.25.0 | BSD-3-Clause | cp314 arm64 |
| uuid-utils | 0.19.0 | BSD-3-Clause | abi3 |
| pyyaml | 6.0.3 | MIT | cp314 arm64 |
| websockets | 17.3 | BSD-3-Clause | cp314 arm64 |
| charset-normalizer | 3.5.2 | MIT | cp314 universal2 |
| httpx2 / httpcore2 | 2.16.0 / 2.16.0 | BSD-3-Clause | pure |
| httpx2-jsfetch | 1.0 | — (emscripten only, not installed) | — |
| requests / requests-toolbelt | 2.34.2 / 1.0.0 | Apache-2.0 | pure |
| urllib3 | 2.8.0 | MIT | pure |
| jsonpatch / jsonpointer | 1.38 / 3.6 | BSD-3-Clause / Modified BSD | pure |
| tenacity | 9.2.1 | Apache-2.0 | pure |
| distro | 1.9.0 | Apache-2.0 | pure |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | pure |
| truststore | 0.10.5 | MIT | pure |

`langgraph` hard-requires `langgraph-sdk` (client for the hosted LangGraph server) and, through `langchain-core`,
`langsmith` (hosted tracing SDK); neither can be excluded by a resolver option. The added installed footprint is
about 16 MB. `orjson`'s MPL-2.0 component and the new notices need `NOTICE-THIRD-PARTY.md` when the dependency is
added (T003). The official SQLite saver `langgraph-checkpoint-sqlite` 3.1.2 (MIT) would add `aiosqlite` 0.22.1 (MIT)
and `sqlite-vec` 0.1.9 (MIT/Apache-2.0, pre-1.0 binary SQLite extension); its synchronous `SqliteSaver` does not
use `aiosqlite`.

### 2.2 Offline packaging

Reproducing the distribution path of `scripts/build_distribution.py` (PEP 751 `pylock.toml` exported with
`--frozen --no-dev --no-emit-project`, 49 entries) on the scratch lock: after one networked fill of a scratch uv
cache, `uv pip install --offline --link-mode copy -r pylock.toml` into a fresh venv installed 48 packages without
network and `uv pip check --offline` passed. Feasible with the existing install route; the larger cache must be
prepared once with `--allow-network`, as today.

### 2.3 Behavior probes

[`langgraph_probe.py`](P002-T002-probes/langgraph_probe.py), synthetic state of identities only, a stdlib SQLite
"journal" standing in for the T006 operation journal, `SqliteSaver` with a strict serializer, `durability="sync"`,
all outbound sockets blocked. Reproduced twice with identical results.

| Check | Result | Consequence |
|---|---|---|
| `interrupt()` + `Command(resume=…)` | Waits with the typed payload; resume re-enters the interrupted node **from its start** (2 entries) | Code before `interrupt()` must be pure or journaled (INV-02) |
| Crash after effect, before checkpoint (`os._exit` in the node) | Restart resumes at the same node, which **runs again** (2 entries); journaled effect performed once, naive effect **twice** | Effects only through deterministic operation identities reconciled by the journal (INV-02, INV-05) |
| Resume a checkpoint with a changed graph (node renamed) | **No error**: `next` is empty and resume completes silently without running the wait node | LangGraph does not detect graph-version drift; the harness must stamp and check the graph version before resume and quarantine a mismatch (G03, T003) |
| Strict serializer (`allowed_msgpack_modules=None`) | Round-trip of identity-only state works; the default allows deserializing arbitrary msgpack-registered modules | Use a strict serializer; graph state stays primitives/identities (D269) |
| Network with tracing variables unset | No outbound attempt | — |
| [`tracing_probe.py`](P002-T002-probes/tracing_probe.py) with inherited `LANGSMITH_TRACING=true` | DNS lookup of `api.smith.langchain.com`; LangSmith tries to POST the run (graph inputs/outputs) | **Hosted tracing by environment** (TM19); neutralize it |
| Same, inside `langsmith.tracing_context(enabled=False)` | No attempt | Programmatic disable works; combine with environment scrubbing |
| Import cost | 0.21–0.24 s; importing `langgraph.graph` loads `langsmith`, `langgraph_sdk`, `httpx`, `httpx2`, `requests`, `websockets` | Keep the import out of the core and of CLI paths that do not orchestrate |

### 2.4 Placement (G01)

The core stays standard-library-only (ARCHITECTURE §2). LangGraph is confined to one orchestration package that may
import `core`, `storage` and the typed service commands, is imported only by the supervisor-owned runtime, and is
never imported by `core`; an import-boundary test enforces it. Graph nodes call application services; they do not
launch processes or touch Git directly (INV-01). Accepted in D280.

### 2.5 Continuation persistence (G02 feasibility; mechanism decided in T003)

| Option | Feasibility evidence | Cost |
|---|---|---|
| A. Official `SqliteSaver` | Works in the probes (tables `checkpoints`, `writes`) | +3 packages incl. a binary SQLite extension it does not need for checkpoints; own connection and schema outside Alembic, backups and DDBB parity |
| B. Custom saver over Alembic-managed tables in the harness database | Not probed; the 4.3.1 `BaseCheckpointSaver` surface is `get_tuple`, `list`, `put`, `put_writes`, `delete_thread`, `delete_for_runs`, `copy_thread`, `prune`, `get_delta_channel_history`, `get_next_version` (+ async variants) | No new packages; schema, backup, migration and query-only parity; must track the pinned interface |
| C. No checkpointer | — | Loses `interrupt`/resume, so the graph would not own resumable waits (conflicts with D269) |

Recommendation for T003: **B**, with A only by a later owner decision. Under any option the consistency contract the
probes support is: the domain journal is the authority and the checkpoint is routing progress only; an effect's
intent is journaled under a deterministic operation identity before the effect; `durability="sync"`; a checkpoint
behind the journal replays the node, which reconciles; resume first validates the stamped graph version. No
atomicity between checkpoint and journal is assumed.

## 3. Tool transport per client (G04)

[`stub_mcp_server.py`](P002-T002-probes/stub_mcp_server.py) is a stdlib stdio MCP server exposing only
`search_tools`, `describe_tool` and `invoke_tool` over a synthetic catalogue scoped to the caller's role; the caller
(project, role, invocation) comes from the server's environment set by the launcher, never from arguments.
[`cli_cases.py`](P002-T002-probes/cli_cases.py) runs each case with the read-only flags of `cli-14` plus the server.

| Concern | Claude Code 2.1.312 | Codex 0.165.0 |
|---|---|---|
| Per-invocation injection without user/global configuration | `--strict-mcp-config --mcp-config '<json>'` with `--setting-sources ""` | `-c mcp_servers.harness.{command,args,env}` with `--strict-config --ignore-user-config` |
| Read-only role keeps mediated tools | `--restricted --tools Read,Glob,Grep` + `--json-schema`: the three broker tools are listed in `init` and work | `--sandbox read-only` + `--output-schema`: the broker tools work |
| Non-interactive approval | `--permission-mode dontAsk` + `--allowedTools mcp__harness__<tool>` | Default **fails**: "MCP tool call requires approval, but approval policy is never" (no call reaches the server). Works with `mcp_servers.harness.default_tools_approval_mode="approve"` (values: `auto`, `prompt`, `writes`, `approve`; only `approve` and the default characterized) |
| Per-tool allowlist | Tool outside `--allowedTools` is refused client-side and listed in `permission_denials`; the server never receives it | `mcp_servers.harness.enabled_tools` hides the others; the model reports the tool unavailable; the server never receives it |
| Full discovery path (search → describe → invoke) | Completed in order, 5 turns, typed result matches | Completed in order, typed result matches |
| Bridge process authority | Runs outside the client's file confinement (wrote its log outside the checkout) | Runs outside the read-only sandbox (same observation) |
| Normal exit | Client sends SIGTERM to the server | Client sends SIGTERM to the server |
| SIGTERM to the CLI during an in-flight call | Exit 143; server receives SIGTERM; no orphan | **Exit 0**; server is **orphaned**: own process group, parent PID 1, still running until terminated |
| MCP protocol notes | Sends a `server/discover` request before `initialize` (answered `-32601`; the session proceeded) | Standard `initialize`/`tools/list`/`tools/call` |

Consequences: the harness bridge is trusted code with launcher authority, so it must expose only the broker and
authorize every call server-side (D275). The supervisor must record the bridge PID, reap it, and the bridge must exit
on stdin EOF or parent loss even mid-call; cancellation is classified from the supervisor's own record, never from
the exit status; an invocation in flight at cancellation is uncertain and reconciled, never reissued (INV-05, INV-06).
Codex's approval setting must be scoped to the harness server only, never a global approval bypass.

### 3.1 Native deferred loading versus the portable broker

Same prompt ("find the phase-status tool and call it"), synthetic catalogue of 40 tools of realistic size, 39 visible
to the reviewer, exposed either directly as native MCP tools or behind the 3-tool broker. Input tokens include cache
reads/creation.

| Claude Code (haiku, low) | Built-in tools | First request | Total | Turns | Tool calls |
|---|---|---|---|---|---|
| Direct, `ENABLE_TOOL_SEARCH=false` | Read, Glob, Grep | 14,322 | 28,803 | 2 | 1 |
| Direct, `ENABLE_TOOL_SEARCH=true` or `force` | Read, Glob, Grep | 14,322 | 28,803 / 28,802 | 2 | 1 (no deferral) |
| Direct, `ENABLE_TOOL_SEARCH=true` | + ToolSearch | 7,127 | 21,977 | 3 | `ToolSearch("select:<name>")`, then the tool |
| Portable broker | Read, Glob, Grep | 6,196 | 25,923 | 4 | search, describe, invoke |

| Codex (gpt-6.1-sol, low) | Turn input (cached) | Output | Tool calls |
|---|---|---|---|
| Direct 40 tools | 67,211 (44,800) | 135 | 1 |
| Portable broker | 76,922 (72,832) | 234 | search, describe, invoke |

Findings: Claude's native deferral needs the `ToolSearch` built-in in `--tools` (the `cli-14` read-only set removes
it); then the first request costs about as little as the broker with one fewer round trip, but every visible tool
name stays disclosed in the deferred index (the model selected by exact name) and per-call version, digest and
idempotency are not bound unless every tool schema carries them. Codex reports only per-turn aggregates, so its
first-request cost and any native deferral are **unknown**. One sample per cell; no latency or quality conclusion.
Default (D281): the portable broker for both clients; Claude ToolSearch remains an optional optimization
behind the same semantics, measured again in T019.

### 3.2 OpenCode extension notes

OpenCode 2.0.32 offers `opencode mcp` and `opencode run --format json` and models as `provider/model#variant`, so
client kind and inference provider are distinct inputs, as D275 requires. Nothing about its injection, approval,
sandbox, events or authentication was characterized; a future adapter must pass the contract in §5 with its own
evidence.

## 4. Observation coverage (G05)

| Signal | Claude Code 2.1.312 (`stream-json`) | Codex 0.165.0 (`exec --json`) |
|---|---|---|
| Session/thread identity | `session_id` (caller-chosen UUID) | `thread_id` (client-generated) |
| Turns | `num_turns` and one `assistant` event per model message | `turn.started`/`turn.completed`; model requests inside a turn not separable |
| Tool calls | `tool_use` (name, input) and `tool_result` (`is_error`) | `item.started`/`item.completed` `mcp_tool_call` (server, tool, arguments, status, error) |
| Usage, normal completion | `result.usage` and `modelUsage` per model (tokens, cache, list-price `costUSD`); per-message usage in `assistant` events | `turn.completed.usage` (input, cached, output, reasoning tokens); no cost |
| Usage after cancellation | No `result`; per-message usage of completed messages remains | **None**: the stream ends at the in-flight `item.started` |
| Reported model | Per message and in `modelUsage` | Not reported |
| Permission denials | `result.permission_denials` with tool and input | Hidden tools are absent; no denial event |
| Cancellation | SIGTERM → exit 143 | SIGTERM → exit 0, bridge orphaned |
| Server-side view | `tools/list` once, each `tools/call`, SIGTERM at exit | Same; no `notifications/cancelled` from either client |

Missing coverage stays explicit (INV-09): Codex usage on cancellation, Codex reported model and request-level usage
are unknown, not zero.

## 5. Minimum client capability contract (D281)

Accepted in D281. A client/version/profile is admitted for a role only if evidence shows every mandatory capability; otherwise
admission blocks with the missing item (INV-07). Usage reporting is recorded but not mandatory.

| ID | Mandatory capability |
|---|---|
| MC1 | Non-interactive one-shot invocation with a machine-readable event stream and a typed final result for read-only roles |
| MC2 | Per-invocation stdio MCP server injection without reading or writing user/global configuration, excluding every other MCP server |
| MC3 | Client-side allowlist of exactly the broker tools for the role, without enabling other tools |
| MC4 | Non-interactive approval scoped to the harness server's tools, without a general approval or sandbox bypass |
| MC5 | Read-only roles keep the broker while built-in write/exec tools stay unavailable |
| MC6 | Each tool call is observable in the stream with tool name and arguments |
| MC7 | Signal termination ends inference; the supervisor can identify and terminate the bridge process |

Both clients meet MC1–MC7 with the flags in §3. For Codex, MC7 is met only if the supervisor reaps the bridge itself
and the bridge exits on parent loss; Codex alone does not.

## 6. Later qualification matrix (T008, T021)

One cell per client × version × role (reviewer roles, executor, judge) × transport (broker; Claude ToolSearch
optional) × check: MC1–MC7; scope disclosure (unscoped tools neither listed nor describable); stale schema digest and
missing idempotency refused; caller binding not settable by arguments; cancellation mid-call with bridge reaping and
uncertain-invocation recovery; quota/auth errors stop without fallback; event/usage parsing including missing
fields. Fake-CLI cells come first; real-provider cells need their own authorization (G15). Executor/write roles,
judge profiles, larger catalogues and repeated samples were **not** exercised here.

## 7. Gates and threats

| Gate | T002 outcome |
|---|---|
| G01 | Version, lock delta, offline packaging and placement characterized; exact set and placement accepted in D280 |
| G02 | Feasibility and consistency contract established; mechanism recommendation B for T003 |
| G04 | Broker transport per client characterized and accepted in D281; native comparison recorded; minimum contract accepted; T008 implements |
| G05 | Observation coverage table above; T006 implements the records |

TM16 (provider drift, hidden fallback): capability contract per client/version/profile with admission block; observed
differences (Codex approval default, cancellation exit status, orphaned bridge, missing usage) become explicit
checks. TM19 (supply chain): exact lock delta, licences, offline install verified; hosted tracing by environment
found and neutralized in the probe; trust in the pinned upstream code remains.

## 8. Unknowns and limits

- Real behavior is one sample per case on one platform with the cheapest model/effort per client; no executor,
  judge, write role, Sonnet/Opus-class model or other Codex model was run. Model reasoning quality is not assessed.
- Codex `default_tools_approval_mode` values `auto` and `writes`, its per-tool approval keys, and whether its read-only
  sandbox constrains MCP servers by design are not characterized.
- Custom saver (option B), graph-version stamping and journal integration are designs for T003/T006, not tested code.
- Claude's `server/discover` request is undocumented here; the stub's `-32601` answer worked for 2.1.312 only.
- The list-price `costUSD` reported by Claude (total about USD 0.008 for eight runs) is not a subscription charge.

## 9. Verification and delivery

**Delivery status.** Source (documentation and probe sources) complete on `docs/p002-t002-feasibility`. After reviewing
it, the owner accepted D280 and D281 and authorized commit, merge into `develop` and push of `develop` to origin
(2026-10-29), which also publishes the T001 merge; Git history records the identities. No release, publication or
installation applies to T002; the phase route remains 0.2.0 (D253/D242).

### Evidence

- **Discovery.** AGENTS discovery read; one-off queue empty; started on clean `develop` at `bd1705e`.
- **LangGraph.** Scratch venv and scratch lock outside the repository; `langgraph_probe.py` and `tracing_probe.py`
  outputs as in §2.3, reproduced from the repository copies; offline `pylock.toml` install and `uv pip check` passed.
- **Real CLIs.** 14 bounded runs, as authorized: Claude `claude-c1`–`c3` and five `claude-n-*`; Codex `codex-x1`,
  `x1b`, `x2`, `x3`, `codex-n-direct`, `codex-n-broker`. Raw streams stay in the session scratch directory and are not
  committed (real runs). One orphaned stub server (Codex cancellation) was terminated after observation; no probe
  process remained.
- **Documentation checks.** See the task closure note in [NEXT_STEPS](../NEXT_STEPS.md#p002-t002--runtime-provider-and-discovery-feasibility).
- **Not performed.** No product code, dependency addition, lock change, schema, API or UI change, so product suites
  were not run; no harness execution; no OpenCode run; no global configuration change; no release, tag or installation.
