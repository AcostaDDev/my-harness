"""P002-T002: does an inherited LangSmith tracing environment make a synthetic graph reach the network?

    LANGSMITH_TRACING=true LANGSMITH_API_KEY=synthetic-not-a-key python -I tracing_probe.py [--disable]
Outbound connections and DNS lookups are blocked and recorded. `--disable` wraps the invocation in
`langsmith.tracing_context(enabled=False)`. Prints one JSON line.
"""
import json
import socket
import sys
import time
from typing import TypedDict

attempts = []


def connect(self, address):
    attempts.append(repr(address))
    raise OSError("network blocked by probe")


def getaddrinfo(host, *args, **kwargs):
    attempts.append("dns:" + str(host))
    raise OSError("network blocked by probe")


socket.socket.connect = connect
socket.getaddrinfo = getaddrinfo

from langgraph.graph import END, START, StateGraph  # noqa: E402


class State(TypedDict):
    x: int


graph = StateGraph(State)
graph.add_node("n", lambda state: {"x": state["x"] + 1})
graph.add_edge(START, "n")
graph.add_edge("n", END)
if "--disable" in sys.argv[1:]:
    from langsmith import tracing_context
    with tracing_context(enabled=False):
        out = graph.compile().invoke({"x": 1})
else:
    out = graph.compile().invoke({"x": 1})
time.sleep(3)  # background tracing threads flush asynchronously
print(json.dumps({"disabled": "--disable" in sys.argv[1:], "result": out, "attempts": sorted(set(attempts))}))
