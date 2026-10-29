"""P002-T002 stub MCP server: portable discovery surface over a synthetic scoped catalogue.

Standard library only; newline-delimited JSON-RPC over stdio. Exposes exactly three broker tools
(search_tools, describe_tool, invoke_tool). The caller (project, role, invocation) comes from the
environment the launcher sets, never from tool arguments. Every received message, signal and stdin
EOF is appended to MCP_PROBE_LOG as JSON lines. No effect is real: invoke returns canned data.
"""
import hashlib
import json
import os
import signal
import sys
import time

LOG = os.environ.get("MCP_PROBE_LOG", os.devnull)
CALLER = {"project": os.environ.get("PROBE_PROJECT", "unset"), "role": os.environ.get("PROBE_ROLE", "unset"),
          "invocation": os.environ.get("PROBE_INVOCATION", "unset")}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


CATALOGUE = {
    "project.phase_status": {
        "version": "1", "kind": "query", "roles": ["reviewer", "executor"],
        "summary": "Read the active phase identifier and its lifecycle state.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "result": {"phase": "P900", "state": "ACTIVE", "revision": "rev-synthetic-7"},
    },
    "knowledge.decision_get": {
        "version": "1", "kind": "query", "roles": ["reviewer", "executor"],
        "summary": "Read one accepted decision by identifier.",
        "input_schema": {"type": "object", "properties": {"decision_id": {"type": "string"}},
                         "required": ["decision_id"], "additionalProperties": False},
        "result": {"decision_id": "D900", "title": "Synthetic decision", "status": "accepted"},
    },
    "project.slow_probe": {
        "version": "1", "kind": "query", "roles": ["reviewer", "executor"],
        "summary": "Synthetic long-running query used to observe cancellation.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "sleep": 90, "result": {"done": True},
    },
    "task.adopt_result": {  # never disclosed to a reviewer
        "version": "1", "kind": "adopt", "roles": ["owner"],
        "summary": "Adopt a task result (owner only).",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "result": {"adopted": True},
    },
}
# PROBE_DIRECT=N: comparison mode exposing N catalogue tools directly as native MCP tools (no broker),
# padded with synthetic query tools of realistic description/schema size.
DIRECT = int(os.environ.get("PROBE_DIRECT", "0"))
for index in range(max(0, DIRECT - len(CATALOGUE))):
    CATALOGUE[f"knowledge.synthetic_{index:02d}"] = {
        "version": "1", "kind": "query", "roles": ["reviewer", "executor"],
        "summary": f"Read synthetic knowledge record family {index:02d}: requirements, criteria, revisions and "
                   "their accepted status, filtered by phase, task and revision reference.",
        "input_schema": {"type": "object", "properties": {
            "phase_id": {"type": "string", "description": "Phase identifier such as P001"},
            "task_id": {"type": "string", "description": "Task identifier such as P001-T001"},
            "revision": {"type": "string", "description": "Accepted revision reference"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, "additionalProperties": False},
        "result": {"records": []},
    }
for entry in CATALOGUE.values():
    entry["schema_digest"] = digest(entry["input_schema"])

BROKER = [
    {"name": "search_tools", "description": "Search the harness tool catalogue for tools available to this caller. "
     "Returns bounded descriptors (id, version, summary, schema_digest).",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"},
                     "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}},
    {"name": "describe_tool", "description": "Return the input schema and digest of one catalogue tool.",
     "inputSchema": {"type": "object", "properties": {"tool_id": {"type": "string"}}, "required": ["tool_id"]}},
    {"name": "invoke_tool", "description": "Invoke one catalogue tool with its exact version and schema digest.",
     "inputSchema": {"type": "object", "properties": {
         "tool_id": {"type": "string"}, "version": {"type": "string"}, "schema_digest": {"type": "string"},
         "arguments": {"type": "object"}, "idempotency_key": {"type": "string"}},
         "required": ["tool_id", "version", "schema_digest", "arguments", "idempotency_key"]}},
]


def log(kind, **values):
    with open(LOG, "a") as handle:
        handle.write(json.dumps({"t": round(time.time(), 3), "pid": os.getpid(), "kind": kind, **values}) + "\n")


def visible(tool_id):
    return tool_id in CATALOGUE and CALLER["role"] in CATALOGUE[tool_id]["roles"]


def refuse(code, detail):
    return {"refused": code, "detail": detail}


def call(name, args):
    if name == "search_tools":
        words = set(str(args.get("query", "")).lower().replace(".", " ").replace("_", " ").split())
        hits = [{"id": k, "version": v["version"], "summary": v["summary"], "schema_digest": v["schema_digest"]}
                for k, v in CATALOGUE.items() if visible(k)
                and (not words or words & set((k + " " + v["summary"]).lower().replace(".", " ").replace("_", " ").split()))]
        return {"tools": hits[: int(args.get("limit") or 5)]}
    if name == "describe_tool":
        tool_id = args.get("tool_id")
        if not visible(tool_id):
            return refuse("unknown_tool", "no such tool for this caller")
        entry = CATALOGUE[tool_id]
        return {"id": tool_id, "version": entry["version"], "kind": entry["kind"],
                "input_schema": entry["input_schema"], "schema_digest": entry["schema_digest"]}
    if name == "invoke_tool":
        tool_id = args.get("tool_id")
        if not visible(tool_id):
            return refuse("unknown_tool", "no such tool for this caller")
        entry = CATALOGUE[tool_id]
        if args.get("version") != entry["version"] or args.get("schema_digest") != entry["schema_digest"]:
            return refuse("stale_schema", "version or schema digest does not match the catalogue")
        if not args.get("idempotency_key"):
            return refuse("missing_idempotency_key", "idempotency_key required")
        if entry.get("sleep"):
            log("slow_start", tool=tool_id)
            time.sleep(entry["sleep"])
            log("slow_end", tool=tool_id)
        return {"caller": CALLER, "tool": tool_id, "result": entry["result"]}
    return refuse("unknown_broker_tool", name)


def respond(message_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": message_id}
    payload.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main():
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda number, frame: (log("signal", signal=signal.Signals(number).name), sys.exit(0)))
    log("start", caller=CALLER, argv=sys.argv[1:])
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            log("bad_line", line=line[:200])
            continue
        log("recv", message=message)
        method, message_id = message.get("method"), message.get("id")
        if method == "initialize":
            respond(message_id, {"protocolVersion": message["params"].get("protocolVersion", "2025-06-18"),
                                 "capabilities": {"tools": {"listChanged": False}},
                                 "serverInfo": {"name": "harness-probe", "version": "0.0.1"},
                                 "instructions": "Harness tools: use search_tools, then describe_tool, then invoke_tool."})
        elif method == "tools/list":
            direct = [{"name": k.replace(".", "__"), "description": v["summary"], "inputSchema": v["input_schema"]}
                      for k, v in CATALOGUE.items() if visible(k)]
            respond(message_id, {"tools": direct if DIRECT else BROKER})
        elif method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            if DIRECT and name.replace("__", ".") in CATALOGUE:
                tool_id = name.replace("__", ".")
                result = ({"caller": CALLER, "tool": tool_id, "result": CATALOGUE[tool_id]["result"]}
                          if visible(tool_id) else refuse("unknown_tool", "no such tool for this caller"))
            else:
                result = call(name, params.get("arguments") or {})
            log("result", tool=params.get("name"), result=result)
            respond(message_id, {"content": [{"type": "text", "text": json.dumps(result)}],
                                 "structuredContent": result, "isError": "refused" in result})
        elif method == "ping":
            respond(message_id, {})
        elif message_id is not None:
            respond(message_id, error={"code": -32601, "message": f"method not found: {method}"})
    log("stdin_eof")


if __name__ == "__main__":
    main()
