# P002-T002 probes

Reproducible sources behind the [T002 feasibility record](../P002-T002-feasibility.md). They are evidence tools, not
product code: nothing imports them, pytest does not collect them (`testpaths = ["tests"]`), and they are not packaged.
All data is synthetic. Raw outputs of real CLI runs are not committed.

| File | Purpose | Needs |
|---|---|---|
| `langgraph_probe.py` | Interrupt/resume, crash re-entry with and without a journal, graph-version drift, strict serializer, network guard | Python 3.14 venv with `langgraph==1.2.18` and `langgraph-checkpoint-sqlite==3.1.2` |
| `tracing_probe.py` | Whether inherited LangSmith variables make a graph reach the network; `--disable` uses `tracing_context(enabled=False)` | Same venv |
| `stub_mcp_server.py` | Stdlib stdio MCP server with the portable broker (or `PROBE_DIRECT=N` native tools) and a JSON-lines log | Python 3 standard library |
| `cli_cases.py` | Bounded real Claude Code/Codex cases with the `cli-14` read-only flags plus the broker server | Installed CLIs, signed in; **explicit owner authorization** |

Commands used (scratch paths outside the repository; network only for the first venv/cache fill):

```sh
uv venv --python 3.14 "$SCRATCH/lg/venv"
uv pip install --python "$SCRATCH/lg/venv/bin/python" langgraph==1.2.18 langgraph-checkpoint-sqlite==3.1.2
"$SCRATCH/lg/venv/bin/python" -I langgraph_probe.py "$SCRATCH/lgwork"
LANGSMITH_TRACING=true LANGSMITH_API_KEY=synthetic-not-a-key "$SCRATCH/lg/venv/bin/python" -I tracing_probe.py
LANGSMITH_TRACING=true LANGSMITH_API_KEY=synthetic-not-a-key "$SCRATCH/lg/venv/bin/python" -I tracing_probe.py --disable
python3 -I cli_cases.py --list
python3 -I cli_cases.py --work "$SCRATCH/cli" --claude "$(command -v claude)" --codex "$(command -v codex)" claude-c1 codex-x1b
```

The lock delta was measured by copying `pyproject.toml`, `uv.lock` and the licence/readme files into a scratch
directory and running `uv add --no-sync langgraph==1.2.18`; the offline check exported `pylock.toml` as
`scripts/build_distribution.py` does and installed it with `uv pip install --offline` into a fresh venv.
