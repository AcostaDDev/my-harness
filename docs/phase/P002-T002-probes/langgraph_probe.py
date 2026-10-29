"""P002-T002 LangGraph feasibility probe (synthetic; no model, no network).

Run with an interpreter that has langgraph and langgraph-checkpoint-sqlite installed:
    python -I langgraph_probe.py <work-dir>
Prints one JSON object per check. The "journal" is a stdlib SQLite table standing in for the
T006 domain-operation journal: an effect is keyed by (thread, operation key) and performed once.
"""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from typing import TypedDict

ATTEMPTS = []


def guard_network():
    """Fail loudly on any outbound connection attempted by the library."""
    original = socket.socket.connect

    def connect(self, address):
        ATTEMPTS.append(repr(address))
        raise OSError("network blocked by probe")

    socket.socket.connect = connect
    return original


guard_network()
t0 = time.perf_counter()
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402
import langgraph  # noqa: E402,F401
import importlib.metadata as md  # noqa: E402
IMPORT_SECONDS = round(time.perf_counter() - t0, 3)


class State(TypedDict, total=False):
    operation_id: str
    revision_ref: str
    decision: str
    outcome: str


def journal(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("create table if not exists effects(thread text, op text, performed integer, "
               "primary key(thread, op))")
    db.execute("create table if not exists node_entries(thread text, node text, n integer)")
    return db


def perform_once(db, thread, op):
    """Reconcile-or-perform: a replayed node finds the same operation instead of a new effect."""
    cur = db.execute("insert or ignore into effects values(?, ?, 1)", (thread, op))
    return "performed" if cur.rowcount == 1 else "reconciled"


def build(db_path, version="v1", crash_after_effect=False, naive=False):
    db = journal(db_path)

    def act(state, config):
        thread = config["configurable"]["thread_id"]
        db.execute("insert into node_entries values(?, 'act', 1)", (thread,))
        if naive:
            db.execute("insert into effects values(?, ?, 1) on conflict do update set performed = performed + 1",
                       (thread, state["operation_id"]))
            result = "naive"
        else:
            result = perform_once(db, thread, state["operation_id"])
        if crash_after_effect:
            os._exit(17)  # effect durable in the journal, node output not yet checkpointed
        return {"outcome": result}

    def wait(state, config):
        thread = config["configurable"]["thread_id"]
        db.execute("insert into node_entries values(?, 'wait', 1)", (thread,))
        answer = interrupt({"kind": "owner_decision", "operation_id": state["operation_id"]})
        return {"decision": answer}

    graph = StateGraph(State)
    graph.add_node("act", act)
    graph.add_node("wait" if version == "v1" else "await_owner", wait)
    graph.add_edge(START, "act")
    graph.add_edge("act", "wait" if version == "v1" else "await_owner")
    graph.add_edge("wait" if version == "v1" else "await_owner", END)
    return graph, db


def entries(db, thread, node):
    return db.execute("select count(*) from node_entries where thread = ? and node = ?", (thread, node)).fetchone()[0]


def effects(db, thread):
    return db.execute("select coalesce(sum(performed), 0) from effects where thread = ?", (thread,)).fetchone()[0]


def emit(check, **values):
    print(json.dumps({"check": check, **values}, sort_keys=True), flush=True)


def saver(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    serde = JsonPlusSerializer(allowed_msgpack_modules=None)  # strict: identities/primitives only
    return SqliteSaver(conn, serde=serde)


def check_interrupt(work):
    graph, db = build(os.path.join(work, "journal-a.sqlite3"))
    app = graph.compile(checkpointer=saver(os.path.join(work, "cp-a.sqlite3")))
    cfg = {"configurable": {"thread_id": "t-interrupt"}}
    first = app.invoke({"operation_id": "op-1", "revision_ref": "rev-1"}, cfg, durability="sync")
    pending = [i.value for i in app.get_state(cfg).interrupts]
    wait_before = entries(db, "t-interrupt", "wait")
    final = app.invoke(Command(resume="approved"), cfg, durability="sync")
    emit("interrupt_resume", first_has_interrupt="__interrupt__" in first, pending=pending,
         wait_node_entries_before_resume=wait_before, wait_node_entries_after_resume=entries(db, "t-interrupt", "wait"),
         act_entries=entries(db, "t-interrupt", "act"), effects=effects(db, "t-interrupt"),
         final_decision=final.get("decision"), next=list(app.get_state(cfg).next))


def check_crash(work, naive):
    tag = "naive" if naive else "journal"
    jpath, cpath = os.path.join(work, f"journal-{tag}.sqlite3"), os.path.join(work, f"cp-{tag}.sqlite3")
    child = subprocess.run([sys.executable, "-I", __file__, work, "--crash-child", tag], capture_output=True, text=True)
    graph, db = build(jpath, naive=naive)
    app = graph.compile(checkpointer=saver(cpath))
    cfg = {"configurable": {"thread_id": f"t-crash-{tag}"}}
    before = app.get_state(cfg)
    app.invoke(None, cfg, durability="sync")  # resume from the last checkpoint after the crash
    emit("crash_reentry", mode=tag, child_exit=child.returncode, next_after_restart=list(before.next),
         act_entries=entries(db, f"t-crash-{tag}", "act"), effects=effects(db, f"t-crash-{tag}"),
         interrupts=[i.value for i in app.get_state(cfg).interrupts])


def crash_child(work, tag):
    graph, _ = build(os.path.join(work, f"journal-{tag}.sqlite3"), crash_after_effect=True, naive=(tag == "naive"))
    app = graph.compile(checkpointer=saver(os.path.join(work, f"cp-{tag}.sqlite3")))
    app.invoke({"operation_id": "op-crash", "revision_ref": "rev-1"},
               {"configurable": {"thread_id": f"t-crash-{tag}"}}, durability="sync")


def check_version_drift(work):
    cpath = os.path.join(work, "cp-drift.sqlite3")
    graph, _ = build(os.path.join(work, "journal-drift.sqlite3"))
    app = graph.compile(checkpointer=saver(cpath))
    cfg = {"configurable": {"thread_id": "t-drift"}}
    app.invoke({"operation_id": "op-d", "revision_ref": "rev-1"}, cfg, durability="sync")
    graph2, db2 = build(os.path.join(work, "journal-drift.sqlite3"), version="v2")
    app2 = graph2.compile(checkpointer=saver(cpath))
    state = app2.get_state(cfg)
    try:
        out = app2.invoke(Command(resume="approved"), cfg, durability="sync")
        outcome = {"raised": None, "decision": out.get("decision"), "next": list(app2.get_state(cfg).next)}
    except Exception as exc:  # record the library behavior, whatever it is
        outcome = {"raised": type(exc).__name__, "message": str(exc)[:200]}
    emit("graph_version_drift", stored_next=list(state.next), renamed_node_entries=entries(db2, "t-drift", "wait"),
         **outcome)


def check_memory_and_serde(work):
    graph, db = build(os.path.join(work, "journal-mem.sqlite3"))
    app = graph.compile(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t-mem"}}
    app.invoke({"operation_id": "op-m", "revision_ref": "rev-1"}, cfg)
    strict = JsonPlusSerializer(allowed_msgpack_modules=None)
    try:
        typed = strict.dumps_typed({"ok": "identity-only"})
        roundtrip = strict.loads_typed(typed) == {"ok": "identity-only"}
    except Exception as exc:
        roundtrip = f"{type(exc).__name__}: {exc}"
    emit("memory_saver_and_strict_serde", in_memory_next=list(app.get_state(cfg).next), strict_roundtrip=roundtrip,
         checkpoint_tables=sorted(r[0] for r in sqlite3.connect(os.path.join(work, "cp-a.sqlite3")).execute(
             "select name from sqlite_master where type='table'")))


if __name__ == "__main__":
    work = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "--crash-child":
        crash_child(work, sys.argv[3])
        sys.exit(0)
    os.makedirs(work, exist_ok=True)
    emit("environment", python=sys.version.split()[0], import_seconds=IMPORT_SECONDS,
         versions={d: md.version(d) for d in ("langgraph", "langgraph-checkpoint", "langgraph-checkpoint-sqlite",
                                              "langchain-core", "langsmith")},
         tracing_env={k: v for k, v in os.environ.items() if k.startswith(("LANGSMITH", "LANGCHAIN"))})
    check_interrupt(work)
    check_crash(work, naive=False)
    check_crash(work, naive=True)
    check_version_drift(work)
    check_memory_and_serde(work)
    emit("network", outbound_attempts=ATTEMPTS)
