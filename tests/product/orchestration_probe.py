"""Synthetic graphs and journal for the P002-T003 runtime tests; a child process is killed by the crash tests.

The journal is a stdlib SQLite file standing in for the T006 operation journal: it seals intents, records outcomes
and counts node entries and performed effects. No model, CLI, Git or network is involved.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from my_harness.orchestration import GraphDefinition, GraphRegistry, GraphRunner, OperationRecord, run_operation, wait_for
from my_harness.storage.database import make_engine


class State(TypedDict, total=False):
    revision_ref: str
    operation: str
    decision: str
    count: int


class SyntheticJournal:
    def __init__(self, path):
        self.path = str(path)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY, kind TEXT, state TEXT, result TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS entries(node TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS effects(key TEXT)")

    def _db(self):
        return _Connection(self.path)

    def seal(self, key, kind, references):
        with self._db() as db:
            created = db.execute("INSERT OR IGNORE INTO operations VALUES (?, ?, 'INTENT', '{}')", (key, kind)).rowcount
            state, result = db.execute("SELECT state, result FROM operations WHERE key = ?", (key,)).fetchone()
        return OperationRecord(key, kind, state, bool(created), json.loads(result))

    def complete(self, key, result):
        with self._db() as db:
            db.execute("UPDATE operations SET state = 'COMPLETED', result = ? WHERE key = ? AND state = 'INTENT'",
                       (json.dumps(result), key))
            kind, = db.execute("SELECT kind FROM operations WHERE key = ?", (key,)).fetchone()
        return OperationRecord(key, kind, 'COMPLETED', False, result)

    def entered(self, node):
        with self._db() as db:
            db.execute("INSERT INTO entries VALUES (?)", (node,))

    def effect(self, key):
        with self._db() as db:
            db.execute("INSERT INTO effects VALUES (?)", (key,))
        return {'effect': key}

    def count(self, table, node=None):
        with self._db() as db:
            if node is None:
                return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            return db.execute(f"SELECT count(*) FROM {table} WHERE node = ?", (node,)).fetchone()[0]

    def operations(self):
        with self._db() as db:
            return db.execute("SELECT key, state FROM operations ORDER BY key").fetchall()


class _Connection:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        return self.connection

    def __exit__(self, *exc):
        self.connection.close()


def approval_graph(journal, *, crash=None, wait_node='wait'):
    """act (one journaled effect) -> wait (owner decision) -> END. `crash` kills the process inside `act`."""
    def act(state, config):
        journal.entered('act')
        if crash == 'before_outcome':
            port = _CrashBeforeOutcome(journal)
        else:
            port = journal
        record = run_operation(port, config, 'act', 'synthetic', {'revision': state['revision_ref']},
                               lambda: journal.effect(state['revision_ref']))
        if crash == 'after_outcome':
            os._exit(17)  # effect and outcome durable in the journal, node output not checkpointed
        return {'operation': record.key}

    def wait(state, config):
        journal.entered('wait')
        return {'decision': wait_for('owner_decision', {'operation': state['operation']})}

    builder = StateGraph(State)
    builder.add_node('act', act)
    builder.add_node(wait_node, wait)
    builder.add_edge(START, 'act')
    builder.add_edge('act', wait_node)
    builder.add_edge(wait_node, END)
    return builder


class _CrashBeforeOutcome:
    """An external effect happens, then the process dies before its outcome is recorded."""

    def __init__(self, journal):
        self.journal = journal

    def seal(self, key, kind, references):
        return self.journal.seal(key, kind, references)

    def complete(self, key, result):
        os._exit(18)


def loop_graph(journal, target, on_step=None):
    """`step` runs `target` times; each pass performs one journaled effect keyed by its own step."""
    def step(state, config):
        journal.entered('step')
        count = state.get('count', 0) + 1
        run_operation(journal, config, 'step', 'synthetic', {'revision': state['revision_ref']},
                      lambda: journal.effect(f'step-{count}'))
        if on_step is not None:
            on_step(count)
        return {'count': count}

    builder = StateGraph(State)
    builder.add_node('step', step)
    builder.add_edge(START, 'step')
    builder.add_conditional_edges('step', lambda state: END if state['count'] >= target else 'step')
    return builder


def approval_definition(journal, version='1', **options):
    return GraphDefinition('synthetic-approval', version, lambda: approval_graph(journal, **options))


def main():
    url, journal_path, crash = sys.argv[1:]
    journal = SyntheticJournal(Path(journal_path))
    runner = GraphRunner(make_engine(url), GraphRegistry([approval_definition(journal, crash=crash)]))
    runner.start('synthetic-approval', 'thread-crash', {'revision_ref': 'rev-1'})


if __name__ == '__main__':
    main()
