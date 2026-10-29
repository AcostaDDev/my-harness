"""P002-T002 bounded real-CLI cases against the stub MCP server (needs explicit owner authorization).

    python3 -I cli_cases.py --work DIR --claude ABS_PATH --codex ABS_PATH CASE [CASE ...]
    python3 -I cli_cases.py --list

Each case runs one non-interactive invocation in DIR/repo (a disposable synthetic Git repository created on first
use) with the read-only flags of `adapters/cli_agents.py` (cli-14) plus the per-invocation broker server.
Outputs: DIR/runs/<case>.stream.jsonl, .stderr, .mcp.jsonl; one JSON summary line per case on stdout.
No global or user configuration is read or changed (Codex: --ignore-user-config; Claude: --setting-sources "").
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = os.path.join(HERE, "stub_mcp_server.py")
BROKER = ("search_tools", "describe_tool", "invoke_tool")
SCHEMA = {"type": "object", "properties": {"phase": {"type": "string"}, "state": {"type": "string"},
          "tool_calls": {"type": "array", "items": {"type": "string"}}},
          "required": ["phase", "state", "tool_calls"], "additionalProperties": False}
PROMPTS = {
    "full": 'You are a read-only reviewer. Use only the harness MCP tools. First call search_tools to find a tool '
            'reporting the phase status, then describe_tool on it, then invoke_tool with its exact version and '
            'schema_digest, empty arguments and idempotency_key "k-c1". Report phase, state and the ordered list of '
            'broker tools you called.',
    "slow": 'Use only the harness MCP tools. Call describe_tool for "project.slow_probe", then invoke_tool on it with '
            'its exact version and schema_digest, empty arguments and idempotency_key "k-c2". Report the result.',
    "denied": 'Use only the harness MCP tools. Call search_tools with query "decision", then invoke_tool on the first '
              'result with its version and schema_digest, arguments {"decision_id": "D900"} and idempotency_key '
              '"k-c3". If a tool is unavailable, say so plainly.',
    "compare": 'You are a read-only reviewer. Using the harness MCP tools, find the tool that reports the active phase '
               'status and call it. Report the phase and state in one line.',
}
# case: (client, prompt, direct tool count, options)
CASES = {
    "claude-c1": ("claude", "full", 0, {"allowed": BROKER, "schema": True}),
    "claude-c2": ("claude", "slow", 0, {"allowed": BROKER, "cancel_on": "slow_start"}),
    "claude-c3": ("claude", "denied", 0, {"allowed": BROKER[:2]}),
    "claude-n-broker": ("claude", "compare", 0, {"server_rule": True, "env": {"ENABLE_TOOL_SEARCH": "false"}}),
    "claude-n-direct-nots": ("claude", "compare", 40, {"server_rule": True, "env": {"ENABLE_TOOL_SEARCH": "false"}}),
    "claude-n-direct-ts": ("claude", "compare", 40, {"server_rule": True, "env": {"ENABLE_TOOL_SEARCH": "true"}}),
    "claude-n-direct-force": ("claude", "compare", 40, {"server_rule": True, "env": {"ENABLE_TOOL_SEARCH": "force"}}),
    "claude-n-direct-ts-tool": ("claude", "compare", 40, {"server_rule": True, "tool_search": True,
                                                          "env": {"ENABLE_TOOL_SEARCH": "true"}}),
    "codex-x1": ("codex", "full", 0, {"schema": True}),
    "codex-x1b": ("codex", "full", 0, {"schema": True, "approve": True, "enabled": BROKER}),
    "codex-x2": ("codex", "slow", 0, {"approve": True, "enabled": BROKER, "cancel_on": "slow_start"}),
    "codex-x3": ("codex", "denied", 0, {"approve": True, "enabled": BROKER[:2]}),
    "codex-n-direct": ("codex", "compare", 40, {"approve": True}),
    "codex-n-broker": ("codex", "compare", 0, {"approve": True}),
}


def stub_env(work, case, direct):
    return {"MCP_PROBE_LOG": os.path.join(work, "runs", case + ".mcp.jsonl"), "PROBE_PROJECT": "p-synthetic",
            "PROBE_ROLE": "reviewer", "PROBE_INVOCATION": "inv-" + case, "PROBE_DIRECT": str(direct)}


def claude_argv(exe, work, case, direct, options):
    server = {"type": "stdio", "command": sys.executable, "args": ["-I", STUB], "env": stub_env(work, case, direct)}
    builtin = ["Read", "Glob", "Grep"] + (["ToolSearch"] if options.get("tool_search") else [])
    allowed = builtin + (["mcp__harness"] if options.get("server_rule")
                         else ["mcp__harness__" + name for name in options["allowed"]])
    argv = [exe, "--print", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--session-id", str(uuid.uuid4()), "--model", "haiku", "--effort", "low",
            "--permission-mode", "dontAsk", "--permission-prompts", "none", "--tools", ",".join(builtin),
            "--allowedTools", ",".join(allowed), "--strict-mcp-config",
            "--mcp-config", json.dumps({"mcpServers": {"harness": server}}),
            "--setting-sources", "", "--settings", '{"disableAllHooks":true,"autoMemoryEnabled":false}',
            "--disable-slash-commands", "--no-chrome", "--restricted"]
    return argv + (["--json-schema", json.dumps(SCHEMA)] if options.get("schema") else [])


def codex_argv(exe, work, case, direct, options):
    env = ",".join(f'{key}={json.dumps(value)}' for key, value in stub_env(work, case, direct).items())
    argv = [exe, "exec", "--strict-config", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--json",
            "--model", "gpt-6.1-sol", "--sandbox", "read-only", "--color", "never",
            "-c", 'approval_policy="never"', "-c", 'model_reasoning_effort="low"', "-c", 'model_provider="openai"',
            "-c", 'web_search="disabled"', "-c", "features.memories=false", "-c", "memories.generate_memories=false",
            "-c", "memories.use_memories=false", "-c", 'history.persistence="none"', "-c", "project_doc_max_bytes=0",
            "-c", f"mcp_servers.harness.command={json.dumps(sys.executable)}",
            "-c", f"mcp_servers.harness.args={json.dumps(['-I', STUB])}",
            "-c", "mcp_servers.harness.env={" + env + "}"]
    if options.get("approve"):  # scoped to this one server; not a global approval bypass
        argv += ["-c", 'mcp_servers.harness.default_tools_approval_mode="approve"']
    if options.get("enabled"):
        argv += ["-c", f"mcp_servers.harness.enabled_tools={json.dumps(list(options['enabled']))}"]
    if options.get("schema"):
        path = os.path.join(work, "runs", "schema.json")
        with open(path, "w") as handle:
            json.dump(SCHEMA, handle)
        argv += ["--output-schema", path]
    return argv + ["--cd", os.path.join(work, "repo"), "-"]


def ensure_repo(work):
    repo = os.path.join(work, "repo")
    if not os.path.isdir(os.path.join(repo, ".git")):
        os.makedirs(repo, exist_ok=True)
        with open(os.path.join(repo, "README.md"), "w") as handle:
            handle.write("# Synthetic probe project\n\nNo real code. Used only by P002-T002 probes.\n")
        for command in (["git", "init", "-q"], ["git", "add", "README.md"],
                        ["git", "-c", "user.name=probe", "-c", "user.email=probe@example.invalid",
                         "commit", "-qm", "synthetic root"]):
            subprocess.run(command, cwd=repo, check=True)
    return repo


def stub_pids(log):
    try:
        with open(log) as handle:
            return sorted({json.loads(line)["pid"] for line in handle if line.strip()})
    except FileNotFoundError:
        return []


def seen(log, kind):
    try:
        with open(log) as handle:
            return any(json.loads(line)["kind"] == kind for line in handle if line.strip())
    except FileNotFoundError:
        return False


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def run(work, case, executables, timeout=240):
    client, prompt, direct, options = CASES[case]
    base = os.path.join(work, "runs", case)
    for suffix in (".stream.jsonl", ".stderr", ".mcp.jsonl"):
        if os.path.exists(base + suffix):
            os.remove(base + suffix)
    build = claude_argv if client == "claude" else codex_argv
    argv = build(executables[client], work, case, direct, options)
    env = dict(os.environ, **options.get("env", {}))
    start, cancelled_at = time.time(), None
    with open(base + ".stream.jsonl", "w") as out, open(base + ".stderr", "w") as err:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=ensure_repo(work),
                                   env=env, start_new_session=True, text=True)
        process.stdin.write(PROMPTS[prompt] + "\n")
        process.stdin.close()
        while process.poll() is None:
            if options.get("cancel_on") and cancelled_at is None and seen(base + ".mcp.jsonl", options["cancel_on"]):
                cancelled_at = round(time.time() - start, 2)
                process.send_signal(signal.SIGTERM)  # the CLI process only, as a supervisor would first
            if time.time() - start > timeout:
                os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(0.2)
        code = process.wait()
    time.sleep(2)
    pids = stub_pids(base + ".mcp.jsonl")
    return {"case": case, "exit": code, "seconds": round(time.time() - start, 2), "cancelled_at": cancelled_at,
            "stub_pids": pids, "stub_alive_after_exit": [pid for pid in pids if alive(pid)]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work")
    parser.add_argument("--claude")
    parser.add_argument("--codex")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("cases", nargs="*")
    args = parser.parse_args()
    if args.list:
        print("\n".join(CASES))
        return
    work = os.path.abspath(args.work)
    os.makedirs(os.path.join(work, "runs"), exist_ok=True)
    executables = {"claude": args.claude, "codex": args.codex}
    for case in args.cases:
        if not executables[CASES[case][0]] or not os.path.isabs(executables[CASES[case][0]]):
            raise SystemExit(f"{case}: absolute --{CASES[case][0]} path required")
        print(json.dumps(run(work, case, executables)), flush=True)


if __name__ == "__main__":
    main()
