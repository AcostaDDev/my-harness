"""P002-T003 (D280, D282, D283): LangGraph runtime and continuation foundation.

Synthetic graphs and a stdlib journal only (`orchestration_probe.py`); temporary SQLite migrated to head; outbound
sockets blocked; no model, CLI, Git or provider. Controls TM12 (replay duplicates effects) and TM20 (graph drift).
"""
import ast
from contextlib import closing
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys

from alembic import command
import pytest

from my_harness.orchestration import GraphDefinition, GraphRegistry, GraphRunner, operation_key
from my_harness.orchestration.hygiene import scrub_environment
from my_harness.orchestration.saver import HarnessCheckpointSaver
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.database import make_engine
from orchestration_probe import SyntheticJournal, approval_definition, loop_graph

SOURCE = Path(__file__).resolve().parents[2] / 'src/my_harness'
PROBE = Path(__file__).with_name('orchestration_probe.py')
GRAPH_TABLES = ('graph_checkpoint_writes', 'graph_checkpoints', 'graph_threads')


@pytest.fixture
def blocked_network(monkeypatch):
    attempts = []

    def connect(self, address):
        attempts.append(address)
        raise OSError('network blocked by test')
    monkeypatch.setattr(socket.socket, 'connect', connect)
    return attempts


@pytest.fixture
def world(migrated_database, tmp_path, blocked_network):
    url = migrated_database[0]
    journal = SyntheticJournal(tmp_path / 'journal.sqlite3')
    return url, make_engine(url), journal


def runner(engine, *definitions):
    return GraphRunner(engine, GraphRegistry(definitions))


def rows(url, table):
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        return db.execute(f'SELECT * FROM {table}').fetchall()


def test_wait_and_resume_reenters_the_node_without_a_second_effect(world, blocked_network):
    url, engine, journal = world
    graphs = runner(engine, approval_definition(journal))
    waiting = graphs.start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    assert (waiting.status, waiting.reason, waiting.segments) == ('WAITING', 'waiting', 1)
    [pending] = waiting.detail['waiting']
    assert pending['kind'] == 'owner_decision' and pending['payload']['operation'].startswith('op-')
    # A new runner over the same database: nothing is held in memory while waiting.
    done = runner(make_engine(url), approval_definition(journal)).resume('thread-1', 'approved')
    assert (done.status, done.values['decision'], done.segments) == ('COMPLETED', 'approved', 2)
    assert journal.count('entries', 'wait') == 2  # the interrupted node re-entered from its start
    assert journal.count('entries', 'act') == 1 and journal.count('effects') == 1
    assert journal.operations() == [(pending['payload']['operation'], 'COMPLETED')]
    assert blocked_network == []


def test_crash_after_a_recorded_outcome_replays_the_node_and_reconciles(world):
    url, engine, journal = world
    child = subprocess.run((sys.executable, str(PROBE), url, journal.path, 'after_outcome'), capture_output=True,
                           text=True, timeout=60)
    assert child.returncode == 17, child.stderr
    graphs = runner(engine, approval_definition(journal))
    assert graphs.status('thread-crash').status == 'RUNNING'  # no proof that the writer stopped
    with pytest.raises(ValueError):
        graphs.recover('thread-crash', writer_stopped=False)
    resumed = graphs.recover('thread-crash', writer_stopped=True)
    assert resumed.status == 'WAITING'
    assert journal.count('entries', 'act') == 2 and journal.count('effects') == 1
    assert [state for _key, state in journal.operations()] == ['COMPLETED']


def test_crash_before_the_outcome_is_uncertain_and_never_reissued(world):
    url, engine, journal = world
    child = subprocess.run((sys.executable, str(PROBE), url, journal.path, 'before_outcome'), capture_output=True,
                           text=True, timeout=60)
    assert child.returncode == 18, child.stderr
    stopped = runner(engine, approval_definition(journal)).recover('thread-crash', writer_stopped=True)
    assert (stopped.status, stopped.reason) == ('RECOVERY_REQUIRED', 'operation_uncertain')
    assert [key for key, _state in journal.operations()] == [stopped.detail['operation']]
    assert journal.count('effects') == 1 and journal.operations()[0][1] == 'INTENT'
    with pytest.raises(ValueError):
        runner(engine, approval_definition(journal)).resume('thread-crash', 'approved')


@pytest.mark.parametrize('changed', ('version', 'structure', 'unknown'))
def test_graph_drift_quarantines_before_any_node_runs(world, changed):
    url, engine, journal = world
    runner(engine, approval_definition(journal)).start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    definitions = {'version': (approval_definition(journal, version='2'),),
                   'structure': (approval_definition(journal, wait_node='await_owner'),),
                   'unknown': ()}[changed]
    entries = journal.count('entries')
    result = runner(engine, *definitions).resume('thread-1', 'approved')
    assert result.status == 'QUARANTINED'
    assert result.reason == ('graph_unknown' if changed == 'unknown' else 'graph_version_mismatch')
    assert result.detail['stamped']['version'] == '1'
    if changed != 'unknown':
        stamped, registered = result.detail['stamped'], result.detail['registered']
        assert (stamped['version'] != registered['version']) == (changed == 'version')
        assert (stamped['fingerprint'] != registered['fingerprint']) == (changed == 'structure')
    assert journal.count('entries') == entries and journal.count('effects') == 1
    with pytest.raises(ValueError):  # no automatic release; re-authorization is a later owner action
        runner(engine, approval_definition(journal)).resume('thread-1', 'approved')


def test_segment_limit_never_caps_the_length_of_a_run(world):
    url, engine, journal = world
    definition = GraphDefinition('synthetic-loop', '1', lambda: loop_graph(journal, 23), segment_limit=5)
    done = runner(engine, definition).start('synthetic-loop', 'thread-loop', {'revision_ref': 'rev-1'})
    assert (done.status, done.values['count']) == ('COMPLETED', 23)
    assert done.segments > 1
    # One journaled effect per legitimate iteration; segment boundaries replay nothing twice.
    assert journal.count('entries', 'step') == 23 and journal.count('effects') == 23
    assert len({key for key, _state in journal.operations()}) == 23


def test_cancel_and_revoke_stop_without_running_nodes(world):
    url, engine, journal = world
    graphs = runner(engine, approval_definition(journal))
    graphs.start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    graphs.start('synthetic-approval', 'thread-2', {'revision_ref': 'rev-2'})
    entries = journal.count('entries')
    assert graphs.cancel('thread-1').status == 'CANCELLED'
    assert (graphs.revoke('thread-2').status, graphs.status('thread-2').reason) == ('REVOKED', 'authority_revoked')
    for thread in ('thread-1', 'thread-2'):
        with pytest.raises(ValueError):
            graphs.resume(thread, 'approved')
        with pytest.raises(ValueError):
            graphs.cancel(thread)
    assert journal.count('entries') == entries


def test_an_active_segment_observes_cancellation_at_the_next_superstep(world):
    url, engine, journal = world
    graphs = None

    def on_step(count):
        if count == 3:
            graphs.cancel('thread-loop')
    graphs = runner(engine, GraphDefinition('synthetic-loop', '1', lambda: loop_graph(journal, 10, on_step)))
    stopped = graphs.start('synthetic-loop', 'thread-loop', {'revision_ref': 'rev-1'})
    assert (stopped.status, stopped.reason) == ('CANCELLED', 'owner_cancelled')
    assert journal.count('entries', 'step') == 3


def test_state_is_limited_to_primitives_and_identities(world):
    url, engine, journal = world
    graphs = runner(engine, approval_definition(journal))
    with pytest.raises(TypeError):
        graphs.start('synthetic-approval', 'thread-1', {'revision_ref': object()})
    with pytest.raises(LookupError):
        graphs.status('thread-1')  # refused before stamping
    graphs.start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    with pytest.raises(TypeError):
        graphs.resume('thread-1', {'decision': b'raw'})
    assert graphs.status('thread-1').status == 'WAITING'


def test_saver_round_trip_parents_and_immutability(world):
    url, engine, journal = world
    graphs = runner(engine, approval_definition(journal))
    graphs.start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    saver = HarnessCheckpointSaver(engine)
    config = {'configurable': {'thread_id': 'thread-1'}}
    history = list(saver.list(config))
    assert len(history) >= 3 and history[0].config == saver.get_tuple(config).config
    assert [item.parent_config['configurable']['checkpoint_id'] for item in history[:-1]] == \
        [item.config['configurable']['checkpoint_id'] for item in history[1:]]
    assert history[-1].parent_config is None
    assert len(list(saver.list(config, limit=2))) == 2
    assert list(saver.list(config, before=history[0].config))[0].config == history[1].config
    assert any(write[1] == '__interrupt__' for write in history[0].pending_writes)
    latest = history[0]
    with pytest.raises(ValueError):  # the same checkpoint id with other content is never rewritten
        saver.put(latest.config, {**latest.checkpoint, 'channel_values': {'decision': 'forged'}},
                  latest.metadata, {})
    with pytest.raises(Exception):  # no checkpoint for a thread the runner did not stamp
        saver.put({'configurable': {'thread_id': 'unstamped', 'checkpoint_ns': ''}}, latest.checkpoint,
                  latest.metadata, {})
    for unsupported in (lambda: saver.prune(['thread-1']), lambda: saver.copy_thread('thread-1', 'copy'),
                        lambda: saver.delete_for_runs(['run'])):
        with pytest.raises(NotImplementedError):
            unsupported()


def test_operation_keys_distinguish_names_references_and_steps():
    config = {'configurable': {'thread_id': 't'},
              'metadata': {'langgraph_step': 1, 'langgraph_node': 'act', 'langgraph_path': ('__pregel_pull', 'act')}}
    key = operation_key(config, 'act', {'revision': 'r1'})
    assert key == operation_key(config, 'act', {'revision': 'r1'})
    later = {**config, 'metadata': {**config['metadata'], 'langgraph_step': 2}}
    other_thread = {**config, 'configurable': {'thread_id': 'u'}}
    assert len({key, operation_key(config, 'other', {'revision': 'r1'}), operation_key(config, 'act', {'revision': 'r2'}),
                operation_key(later, 'act', {'revision': 'r1'}), operation_key(other_thread, 'act', {'revision': 'r1'})}) == 5


def test_backup_restore_keeps_continuations_and_refuses_runner_writes(world, tmp_path):
    url, engine, journal = world
    runner(engine, approval_definition(journal)).start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    engine.dispose()
    path = url.removeprefix('sqlite:///')
    create_backup(path, tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = f"sqlite:///{tmp_path / 'restored/state.sqlite3'}"
    assert all(rows(restored, table) == rows(url, table) for table in GRAPH_TABLES)
    graphs = runner(make_engine(restored), approval_definition(journal))
    for write in (lambda: graphs.start('synthetic-approval', 'thread-2', {'revision_ref': 'r'}),
                  lambda: graphs.resume('thread-1', 'approved'), lambda: graphs.cancel('thread-1'),
                  lambda: graphs.recover('thread-1', writer_stopped=True)):
        with pytest.raises(PermissionError):
            write()
    assert graphs.status('thread-1').status == 'WAITING'
    assert all(rows(restored, table) == rows(url, table) for table in GRAPH_TABLES)


def test_inherited_tracing_variables_are_removed_and_nothing_is_sent(world, blocked_network, monkeypatch):
    environ = {'LANGSMITH_TRACING': 'true', 'LANGCHAIN_API_KEY': 'synthetic', 'PATH': '/usr/bin'}
    assert scrub_environment(environ) == ['LANGCHAIN_API_KEY', 'LANGSMITH_TRACING'] and environ == {'PATH': '/usr/bin'}
    url, engine, journal = world
    monkeypatch.setenv('LANGSMITH_TRACING', 'true')  # even if set again after import, the context disables it
    monkeypatch.setenv('LANGSMITH_ENDPOINT', 'http://127.0.0.1:9')
    runner(engine, approval_definition(journal)).start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    assert blocked_network == []


def test_package_import_scrubs_the_environment_before_langgraph():
    script = ("import os, sys; os.environ['LANGSMITH_TRACING'] = 'true'; import my_harness.orchestration; "
              "assert 'LANGSMITH_TRACING' not in os.environ")
    result = subprocess.run((sys.executable, '-c', script), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def _imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.module or ''


def test_import_boundary_confines_langgraph_to_the_orchestration_package():
    external = ('langgraph', 'langsmith', 'langchain_core', 'langchain')
    for path in SOURCE.rglob('*.py'):
        relative = path.relative_to(SOURCE).as_posix()
        for module in _imports(path):
            if module.split('.')[0] in external:
                assert relative.startswith('orchestration/'), relative
            if module.startswith('my_harness.orchestration'):
                assert relative.startswith(('orchestration/', 'services/managed_runtime.py')), relative
    script = ("import sys; import my_harness.cli, my_harness.api.app, my_harness.services.managed_runtime; "
              "loaded = [m for m in sys.modules if m.split('.')[0] in ('langgraph', 'langsmith')]; "
              "assert not loaded, loaded")
    result = subprocess.run((sys.executable, '-c', script), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_migration_refuses_a_downgrade_with_continuations(world, migrated_database):
    url, engine, journal = world
    runner(engine, approval_definition(journal)).start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'})
    engine.dispose()
    with pytest.raises(RuntimeError):
        command.downgrade(migrated_database[1], '0028_usage_accounting')
    assert rows(url, 'graph_threads')
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        for table in GRAPH_TABLES:
            db.execute(f'DELETE FROM {table}')
        db.commit()
    command.downgrade(migrated_database[1], '0028_usage_accounting')
    with closing(sqlite3.connect(url.removeprefix('sqlite:///'))) as db:
        tables = {name for name, in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not tables & set(GRAPH_TABLES)
    command.upgrade(migrated_database[1], 'head')


def test_the_supervisor_runtime_owns_the_runner(world):
    from my_harness.services.managed_runtime import ManagedRuntime
    url, engine, journal = world
    graphs = ManagedRuntime(engine).graph_runner(GraphRegistry([approval_definition(journal)]))
    assert isinstance(graphs, GraphRunner)
    assert graphs.start('synthetic-approval', 'thread-1', {'revision_ref': 'rev-1'}).status == 'WAITING'
