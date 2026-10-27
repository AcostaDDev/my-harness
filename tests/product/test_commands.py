"""Native product runner: temporary SQLite/checkouts and cooperative synthetic processes only."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event
import time
from uuid import uuid4

import pytest

from my_harness.adapters.commands import CommandConfig, ManagedCommandRunner
from my_harness.adapters.engine_fake import ScriptedAgentAdapter, SyntheticWorkspace
from my_harness.adapters.processes import identity, liveness
from my_harness.core.engine.context import Command
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.core.engine.validation import run_command
from my_harness.services.managed import LocalSupervisor, _Journal
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from test_managed import context, repository, PLAN, VERSIONS, edit, review


def configuration(context, command, **kwargs):
    return CommandConfig(str(context.root), True, (command,),
                         (('python', sys.executable),), (('EXPLICIT', 'yes'),), **kwargs)


def setup(repository, context, config, *, versions=None):
    port = ManagedCommandRunner(config)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN,
                            versions or {**VERSIONS, **port.frozen_versions()}, key=str(uuid4()))
    claim = repository.claim()
    repository.register_owner(claim, identity())
    journal = _Journal(repository, claim, Event())
    port.bind_process_journal(journal)
    return port, journal, job, claim


def execute(repository, context, command, **kwargs):
    port, journal, job, claim = setup(repository, context, configuration(context, command, **kwargs))
    try:
        result = run_command(context, port, command, journal)
        return result, repository.command_processes(job.id), repository.events(job.run_id)
    finally:
        repository.close_owner(claim)


@pytest.mark.parametrize('code,exit_code', [('print("ok")', 0), ('import sys; sys.exit(7)', 7)])
def test_observed_exit_duration_capture_and_intent_order(repository, context, code, exit_code):
    command = Command(('python', '-c', code))
    result, rows, events = execute(repository, context, command)
    assert result.exit_code == exit_code and result.duration_seconds > 0
    assert result.passed == (exit_code == 0)
    assert rows[0]['status'] == 'STOPPED' and rows[0]['capture']['group_state'] == 'dead'
    kinds = [e['kind'] for e in events]
    assert kinds.index('command_started') < kinds.index('command_process_intent') < kinds.index('command_process_spawned')
    assert kinds.index('command_process_spawned') < kinds.index('command_process_finished') < kinds.index('command_finished')
    capture = json.loads(result.capture_json)
    assert all(stream['complete'] for stream in capture['streams'].values())
    assert rows[0]['spec']['argv'][0] == sys.executable


def test_literal_argv_explicit_environment_cwd_and_raw_bytes(repository, context, monkeypatch):
    monkeypatch.setenv('SHOULD_NOT_INHERIT', 'secret')
    code = 'import os,sys,json; print(json.dumps([sys.argv[1:],dict(os.environ),os.getcwd()])); os.write(2,b"\\xff")'
    command = Command(('python', '-c', code, '$(touch escaped)', ';', 'two words'), cwd='app',
                      environment=(('EXPLICIT', 'override'),))
    result, rows, events = execute(repository, context, command)
    argv, env, cwd = json.loads(result.stdout)
    assert argv == ['$(touch escaped)', ';', 'two words'] and cwd == str(context.root / 'app')
    assert env['EXPLICIT'] == 'override' and 'SHOULD_NOT_INHERIT' not in env
    assert not context.path('app/escaped').exists()
    raw = b''.join(base64.b64decode(e['payload']['data_base64']) for e in events
                   if e['kind'] == 'command_process_bytes' and e['payload']['stream'] == 'stderr')
    assert raw == b'\xff' and result.stderr == '\ufffd'
    assert json.loads(result.capture_json)['streams']['stderr']['sha256'] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('stream', [1, 2])
def test_excessive_output_bounded_and_never_passes(repository, context, stream):
    command = Command(('python', '-c', f'import os; os.write({stream}, b"x" * 2000000)'))
    result, rows, events = execute(repository, context, command, max_output_bytes=1024)
    assert not result.passed and 'limit' in result.error
    name = 'stdout' if stream == 1 else 'stderr'
    capture = json.loads(result.capture_json)['streams'][name]
    assert capture['saved_bytes'] == 1024 and capture['observed_bytes'] > 1024
    assert capture['truncated'] and not capture['complete']
    assert sum(len(base64.b64decode(e['payload']['data_base64'])) for e in events
               if e['kind'] == 'command_process_bytes') == 1024


def test_timeout_even_with_closed_pipes(repository, context):
    command = Command(('python', '-c', 'import os,time; os.close(1); os.close(2); time.sleep(30)'), timeout_seconds=0.1)
    result, rows, _ = execute(repository, context, command)
    assert result.timed_out and not result.passed and result.duration_seconds < 3
    assert result.exit_code is not None and rows[0]['status'] == 'STOPPED'


def test_missing_executable_is_not_an_invented_exit(repository, context):
    command = Command(('python', '-c', 'pass'))
    config = replace(configuration(context, command), executables=(('python', str(context.root / 'missing')),))
    port, journal, job, claim = setup(repository, context, config)
    result = run_command(context, port, command, journal)
    assert result.exit_code is None and 'unavailable' in result.error
    row = repository.command_processes(job.id)[0]
    assert row['identity'] is None and row['status'] == 'STOPPED'
    repository.close_owner(claim)


@pytest.mark.parametrize('mode', ['trust', 'authorization', 'cwd', 'ceiling'])
def test_trust_authorization_path_and_limit_are_independent(repository, context, mode):
    command = Command(('python', '-c', 'raise RuntimeError("must not run")'))
    config = configuration(context, command)
    if mode == 'trust':
        config = replace(config, repository_trusted=False)
    elif mode == 'authorization':
        config = replace(config, authorized_commands=())
    elif mode == 'cwd':
        context.path('link').symlink_to(context.path('app'), target_is_directory=True)
        command = replace(command, cwd='link')
        config = replace(config, authorized_commands=(command,))
    else:
        config = replace(config, max_timeout_seconds=1)
    port, journal, job, claim = setup(repository, context, config)
    result = run_command(context, port, command, journal)
    assert not result.passed and result.error and not repository.command_processes(job.id)
    repository.close_owner(claim)


@pytest.mark.parametrize('change', ['environment', 'executable', 'limit', 'legacy'])
def test_frozen_configuration_mismatch_before_effects(repository, context, change):
    command = Command(('python', '-c', 'pass'))
    config = configuration(context, command)
    port = ManagedCommandRunner(config)
    versions = {**VERSIONS, **port.frozen_versions()}
    if change == 'environment':
        config = replace(config, environment=(('NEW', 'value'),))
    elif change == 'executable':
        config = replace(config, executables=(('python', '/missing/python'),))
    elif change == 'limit':
        config = replace(config, max_output_bytes=5)
    else:
        versions = VERSIONS
    with pytest.raises(JournalError, match='frozen'):
        setup(repository, context, config, versions=versions)


def test_runner_has_no_unmanaged_or_default_execution(context):
    command = Command(('python', '-c', 'pass'))
    runner = ManagedCommandRunner(configuration(context, command))
    with pytest.raises(JournalError):
        run_command(context, runner, command)
    with pytest.raises(JournalError):
        runner.run(context, command)
    from my_harness.services.managed_runtime import ManagedConfig
    assert ManagedConfig().ports_factory is None and not ManagedConfig().supervisor


@pytest.mark.parametrize('stage', ['intent', 'spawned', 'bytes', 'finished'])
def test_journal_failure_stops_flow_and_preserves_lock(repository, context, monkeypatch, stage):
    marker = context.path('app/marker')
    command = Command(('python', '-c', f'from pathlib import Path; Path({str(marker)!r}).write_text("once"); print("ok",flush=True)'))
    context = replace(context, profile=replace(context.profile, preparation=(command,)))
    config = configuration(context, command)
    agents = ScriptedAgentAdapter([])
    port = ManagedCommandRunner(config)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN,
                            {**VERSIONS, **port.frozen_versions()}, key='failure')
    original = repository.command_process_event
    def fail(claim, command_id, kind, payload):
        if kind == stage:
            raise RuntimeError('synthetic journal failure')
        return original(claim, command_id, kind, payload)
    monkeypatch.setattr(repository, 'command_process_event', fail)
    supervisor = LocalSupervisor(repository, lambda *_: (agents, port, SyntheticWorkspace(context, ())))
    with pytest.raises(JournalError):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not agents.requests and supervisor.run_once() is None
    assert marker.exists() == (stage in ('bytes', 'finished'))
    claim = repository.get_job(job.id)
    repository.confirm_stopped(job.id, owner_token=claim.owner_token,
        expected_version=repository.get_run(job.run_id).version, reason='synthetic processes stopped')
    assert supervisor.run_once() is None


def wait_dead(value):
    deadline = time.monotonic() + 5
    while liveness(value, group=True) != 'dead' and time.monotonic() < deadline:
        time.sleep(0.02)
    assert liveness(value, group=True) == 'dead'


@pytest.mark.parametrize('close_pipes', [False, True])
def test_child_outlives_leader_never_certifies_success(repository, context, close_pipes):
    child = context.path('app/child.pid')
    code = ('import os,time; pid=os.fork(); '
            f'open({str(child)!r},"w").write(str(pid)) if pid else None; '
            'os._exit(0) if pid else None; '
            + ('os.close(1); os.close(2); ' if close_pipes else '') + 'time.sleep(30)')
    command = Command(('python', '-c', code), timeout_seconds=2)
    port, journal, job, claim = setup(repository, context, configuration(context, command))
    try:
        try:
            result = run_command(context, port, command, journal)
            assert not result.passed and any(word in result.error for word in ('Descendants', 'group'))
        except JournalError:
            assert repository.command_processes(job.id)[0]['status'] == 'UNCERTAIN'
        value = repository.command_processes(job.id)[0]['identity']
        wait_dead(value)
    finally:
        repository.close_owner(claim)


def test_real_supervisor_crash_restart_live_group_and_explicit_recovery(repository, context, tmp_path):
    marker = context.path('app/launches')
    command = Command(('python', '-c',
        f'import time; open({str(marker)!r},"a").write("once\\n"); print("started",flush=True); time.sleep(30)'),
        timeout_seconds=40)
    context = replace(context, profile=replace(context.profile, preparation=(command,)))
    config = configuration(context, command)
    port = ManagedCommandRunner(config)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN,
                            {**VERSIONS, **port.frozen_versions()}, key='crash')
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps(asdict(config)))
    process = subprocess.Popen((sys.executable, str(Path(__file__).with_name('command_supervisor_probe.py')),
                               str(repository.engine.url), str(config_path)), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    value = None
    try:
        out, err = process.communicate(timeout=10)
        assert process.returncode == 90, (out, err)
        row = repository.command_processes(job.id)[0]
        value = row['identity']
        assert row['capture'] is None and liveness(value, group=True) == 'alive'
        assert marker.read_text() == 'once\n'
        restarted = SQLiteManagedRepository(repository.engine,
            clock=lambda: datetime.now(timezone.utc) + timedelta(seconds=60))
        assert restarted.recover_expired() == [job.id]
        agents = ScriptedAgentAdapter([])
        supervisor = LocalSupervisor(restarted, lambda *_: pytest.fail('must not construct ports'))
        assert supervisor.run_once() is None
        claim = restarted.get_job(job.id)
        with pytest.raises(Conflict, match='command group'):
            restarted.confirm_stopped(job.id, owner_token=claim.owner_token,
                expected_version=restarted.get_run(job.run_id).version, reason='lease alone is not evidence')
        assert marker.read_text() == 'once\n'
        os.killpg(value['pgid'], signal.SIGTERM)  # Test-owned synthetic group, never product recovery.
        wait_dead(value)
        restarted.confirm_stopped(job.id, owner_token=claim.owner_token,
            expected_version=restarted.get_run(job.run_id).version, reason='observed synthetic group absent')
        assert supervisor.run_once() is None and marker.read_text() == 'once\n'
        assert restarted.get_run(job.run_id).status == 'INTERRUPTED'
        assert restarted.command_processes(job.id)[0]['capture'] is None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if value and liveness(value, group=True) == 'alive':
            os.killpg(value['pgid'], signal.SIGKILL)
            wait_dead(value)


@pytest.mark.parametrize('mode', ['correct', 'failed-tests', 'type-error', 'changed-after-validation'])
def test_product_runner_typescript_offline_exact_evidence_and_commit(web, repository, tmp_path, mode):
    from my_harness.adapters.git import GitWorkspace
    from my_harness.storage.backup import create_backup, restore_backup
    from test_typescript_profile import task_checkout, TASK, PHASE, PLAN as WEB_PLAN, IDENTITY, edit as web_edit, review as web_review
    context, fixture_runner = task_checkout(web, tmp_path)
    # Reuse only the fixture's explicit executable/environment data. Its run() is never used.
    config = CommandConfig(str(context.root), True,
        context.profile.preparation + context.profile.validations,
        tuple(fixture_runner.executables.items()), tuple(fixture_runner.environment.items()))
    agents = ScriptedAgentAdapter([web_edit('correct' if mode == 'changed-after-validation' else mode), web_review()])
    workspace = GitWorkspace(IDENTITY)
    versions = {**VERSIONS, **ManagedCommandRunner(config).frozen_versions()}
    job = repository.submit(context, TASK, PHASE, WEB_PLAN, versions, key='product-web')
    supervisor = LocalSupervisor(repository, lambda *_: (agents, ManagedCommandRunner(config), workspace),
                                 commit_factory=lambda *_: workspace)
    assert supervisor.run_once().status == 'DONE'
    record = repository.get_run(job.run_id)
    assert not fixture_runner.calls
    rows = repository.command_processes(job.id)
    assert len(rows) == 6 and all(r['status'] == 'STOPPED' for r in rows)
    assert all(r['spec']['config_sha256'] == versions['command_config_sha256'] for r in rows)
    history = record.history
    assert json.loads(dump_history(history))['format'] == 7
    assert load_history(dump_history(history)) == history
    assert SQLiteManagedRepository(repository.engine).get_run(job.run_id) == record
    validation = history.cycles[0].validation
    for entry in validation.entries:
        capture = json.loads(entry.result.capture_json)
        assert any(row['command_id'] == capture['command_id'] for row in rows)
        if entry.reports:
            assert entry.command_id == capture['command_id']
    if mode in ('failed-tests', 'type-error'):
        assert record.status == 'STOPPED' and not validation.all_passed
        with pytest.raises(Conflict):
            repository.submit_commit(job.run_id, key='rejected', expected_version=record.version)
    else:
        assert record.status == 'ACCEPTANCE_READY'
        assert history.acceptance.evidence == validation.evidence == workspace.capture(context)
        report = validation.entries[1].reports[0]
        assert report.status == 'complete' and report.original_base64 and len(report.cases) == 3
        assert validation.entries[1].command_id in [r['command_id'] for r in rows]
        if mode == 'changed-after-validation':
            context.path('src/estimate.ts').write_text('// later external change\n')
        repository.submit_commit(job.run_id, key='commit', expected_version=record.version)
        assert supervisor.run_once().status == 'DONE'
        after = repository.get_run(job.run_id)
        assert after.status == ('STOPPED' if mode == 'changed-after-validation' else 'COMMITTED')
        assert after.history.cycles == history.cycles
    assert len(agents.requests) == 2 and supervisor.run_once() is None
    if mode == 'correct':
        from my_harness.storage.database import make_engine
        bundle, restored = tmp_path / 'backup', tmp_path / 'restored'
        create_backup(Path(repository.engine.url.database), bundle, writers_stopped=True)
        restore_backup(bundle, restored)
        restored_engine = make_engine(f"sqlite:///{restored / 'state.sqlite3'}")
        try:
            reader = SQLiteManagedRepository(restored_engine)
            assert reader.get_run(job.run_id) == repository.get_run(job.run_id)
            assert reader.events(job.run_id) == repository.events(job.run_id)
            assert reader.command_processes(job.id) == repository.command_processes(job.id)
        finally:
            restored_engine.dispose()


# Existing TypeScript fixture only prepares synthetic Git and explicit environment.
from test_typescript_profile import web


def test_same_command_identity_cannot_execute_twice(repository, context):
    marker = context.path('app/count')
    command = Command(('python', '-c', f'open({str(marker)!r},"a").write("once\\n")'))
    port, journal, job, claim = setup(repository, context, configuration(context, command))
    command_id = journal.command_started(command)
    assert port.run_managed(context, command, command_id).passed
    with pytest.raises(JournalError, match='One process intent'):
        port.run_managed(context, command, command_id)
    assert marker.read_text() == 'once\n' and len(repository.command_processes(job.id)) == 1
    repository.close_owner(claim)


@pytest.mark.parametrize('state', ['alive', 'unknown'])
def test_recovery_requires_closed_owner_and_absent_group(repository, context, monkeypatch, state):
    from my_harness.adapters import processes
    command = Command(('python', '-c', 'pass'))
    port, journal, job, claim = setup(repository, context, configuration(context, command))
    assert run_command(context, port, command, journal).passed
    repository.quarantine(claim, 'synthetic interruption after capture')
    def confirm():
        repository.confirm_stopped(job.id, owner_token=claim.owner_token,
            expected_version=repository.get_run(job.run_id).version, reason='explicit inspection')
    with pytest.raises(Conflict, match='owner'):
        confirm()
    repository.close_owner(claim)
    with monkeypatch.context() as patch:
        patch.setattr(processes, 'liveness', lambda *a, **kw: state)
        with pytest.raises(Conflict, match='command group'):
            confirm()
    confirm()
    assert repository.claim() is None


def test_unknown_group_aborts_before_next_validator_or_agent(repository, context, monkeypatch):
    from my_harness.adapters import commands
    from my_harness.adapters.processes import CancellationResult
    first = Command(('python', '-c', 'print("ok")'))
    second = Command(('python', '-c', 'raise RuntimeError("not reached")'))
    context = replace(context, profile=replace(context.profile, preparation=(first, second)))
    config = replace(configuration(context, first), authorized_commands=(first, second))
    agents = ScriptedAgentAdapter([])
    port = ManagedCommandRunner(config)
    job = repository.submit(context, 'P001-T001', 'P001', PLAN,
                            {**VERSIONS, **port.frozen_versions()}, key='unknown')
    stop = commands.stop_group
    def uncertain(process, **kwargs):
        stop(process, **kwargs)
        return CancellationResult(True, 'unknown')
    monkeypatch.setattr(commands, 'stop_group', uncertain)
    monkeypatch.setattr(commands, 'liveness', lambda *a, **kw: 'unknown')
    supervisor = LocalSupervisor(repository, lambda *_: (agents, port, SyntheticWorkspace(context, ())))
    with pytest.raises(JournalError, match='quarantine'):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not agents.requests and len(repository.command_processes(job.id)) == 1
    assert supervisor.run_once() is None


@pytest.mark.parametrize('overrides', [
    {'max_timeout_seconds': float('nan')}, {'max_timeout_seconds': float('inf')},
    {'max_output_bytes': 1048577}, {'drain_seconds': 3},
    {'environment': (('A', '1'), ('A', '2'))}, {'executables': (('python', 'python'),)},
])
def test_invalid_configuration_has_no_effects(context, overrides):
    config = configuration(context, Command(('python', '-c', 'pass')))
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_maintenance_checks_validator_groups(repository, context, tmp_path, monkeypatch):
    import sqlite3
    from my_harness.adapters import processes
    from my_harness.storage.backup import create_backup, BackupError
    from my_harness.storage.retention import _stopped
    command = Command(('python', '-c', 'pass'))
    _, rows, _ = execute(repository, context, command)
    monkeypatch.setattr(processes, 'liveness', lambda *a, **kw: 'alive')
    with pytest.raises(BackupError, match='validation'):
        create_backup(Path(repository.engine.url.database), tmp_path / 'blocked-copy', writers_stopped=True)
    with sqlite3.connect(repository.engine.url.database) as db:
        with pytest.raises(ValueError, match='validation'):
            _stopped(db, True)


def test_old_command_history_roundtrips_without_new_fields(repository, context):
    from test_managed import worker
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, VERSIONS, key='old')
    supervisor, *_ = worker(repository, context, [edit(), review()])
    supervisor.run_once()
    old = dump_history(repository.get_run(job.run_id).history)
    assert json.loads(old)['format'] < 7 and 'capture_json' not in old
    assert dump_history(load_history(old)) == old


def test_frozen_native_configuration_never_runs_with_another_runner(repository, context):
    from my_harness.adapters.engine_fake import ScriptedCommandRunner
    command = Command(('python', '-c', 'pass'))
    context = replace(context, profile=replace(context.profile, preparation=(command,)))
    versions = {**VERSIONS, **ManagedCommandRunner(configuration(context, command)).frozen_versions()}
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, versions, key='swapped')
    agents, runner = ScriptedAgentAdapter([]), ScriptedCommandRunner(())
    supervisor = LocalSupervisor(repository, lambda *_: (agents, runner, SyntheticWorkspace(context, ())))
    with pytest.raises(JournalError, match='frozen native'):
        supervisor.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not runner.calls and not agents.requests and not repository.command_processes(job.id)
