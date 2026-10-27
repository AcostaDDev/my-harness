"""Smoke environment regression, using only synthetic CLI subprocesses."""
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace

import pytest

from my_harness.adapters.cli_agents import CLIProcessAdapter
from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.journal import JournalError
from my_harness.services.managed import _Journal
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository


@pytest.fixture
def smoke(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[2] / 'scripts/smoke_cli.py'
    spec = importlib.util.spec_from_file_location('smoke_cli_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.pwd, 'getpwuid', lambda uid: SimpleNamespace(pw_name='synthetic-local'))
    for key, value in {'HOME': str(tmp_path), 'TMPDIR': str(tmp_path), 'LANG': 'C.UTF-8',
                       'USER': 'synthetic-local', 'LOGNAME': 'not-the-local-user',
                       'ANTHROPIC_API_KEY': 'synthetic-excluded', 'OPENAI_API_KEY': 'synthetic-excluded',
                       'CLAUDE_CONFIG_DIR': '/synthetic/excluded', 'CLAUDE_CODE_OAUTH_TOKEN': 'synthetic-excluded',
                       'HARNESS_DATABASE_URL': 'synthetic-excluded'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, 'argv', [str(path), '--authorize-consumption',
        '--codex-model', 'gpt-6-luna', '--codex-effort', 'low',
        '--claude-model', 'claude-sonnet-4-6', '--claude-effort', 'low',
        '--output-parent', str(tmp_path / 'output')])
    return module


@pytest.mark.parametrize('user', [None, '', 'another-user', ' synthetic-local', 'synthetic-local\0'])
def test_invalid_user_stops_before_side_effects(smoke, monkeypatch, tmp_path, capsys, user):
    if user is None:
        monkeypatch.delenv('USER')
    elif '\0' in user:
        # The real os.environ rejects NUL itself; exercise defensive validation.
        monkeypatch.setattr(smoke.os, 'environ', {'USER': user})
    else:
        monkeypatch.setenv('USER', user)
    monkeypatch.setattr(smoke.shutil, 'which', lambda *_: pytest.fail('No CLI resolution expected'))
    monkeypatch.setattr(smoke.subprocess, 'run', lambda *_a, **_k: pytest.fail('No process expected'))
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 2
    assert 'USER' in capsys.readouterr().err
    assert not (tmp_path / 'output').exists()


def test_unresolvable_local_uid_stops_before_side_effects(smoke, monkeypatch, tmp_path, capsys):
    def missing(uid):
        assert uid == os.getuid()
        raise KeyError(uid)
    monkeypatch.setattr(smoke.pwd, 'getpwuid', missing)
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 2 and 'Cannot resolve the local UID' in capsys.readouterr().err
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('legacy', [True, False])
def test_synthetic_smoke_environment_and_frozen_history(smoke, monkeypatch, tmp_path, legacy):
    expected = {key: os.environ[key] for key in ('HOME', 'PATH', 'TMPDIR', 'LANG', 'USER')}
    assert dict(smoke.smoke_environment()) == expected
    assert dict(smoke.smoke_environment()) == expected  # deterministic snapshot
    original_builder = smoke.smoke_environment
    if legacy:
        # Reproduce the old builder, without changing the synthetic executable.
        monkeypatch.setattr(smoke, 'smoke_environment',
                            lambda: tuple((k, v) for k, v in original_builder() if k != 'USER'))
    record = tmp_path / 'launches.jsonl'
    passed_environments = []
    original_popen = smoke.subprocess.Popen
    def capture_popen(*args, **kwargs):
        if 'env' in kwargs:
            passed_environments.append(kwargs['env'].copy())
        return original_popen(*args, **kwargs)
    monkeypatch.setattr(smoke.subprocess, 'Popen', capture_popen)
    probe = str(Path(__file__).with_name('smoke_environment_probe.py'))
    ports = []
    monkeypatch.setattr(smoke.shutil, 'which', lambda provider: sys.executable)
    def synthetic_port(configs, artifact_root):
        configs = [replace(c, cli_version={'codex': '0.164.0', 'claude': '2.1.304'}[c.provider],
                           executable=(sys.executable, probe, c.provider, str(record), 'synthetic-local'))
                   for c in configs]
        port = CLIProcessAdapter(configs, artifact_root)
        ports.append(port)
        return port
    monkeypatch.setattr(smoke, 'CLIProcessAdapter', synthetic_port)
    if legacy:
        with pytest.raises(RuntimeError, match='executor: failed'):
            smoke.main()
    else:
        smoke.main()
    port = ports[0]
    area = port.artifact_root.parent
    engine = make_engine(f'sqlite:///{area / "smoke.sqlite3"}')
    try:
        repo = SQLiteManagedRepository(engine)
        job = repo.get_job(1)
        run = repo.get_run(job.run_id)
        launches = [json.loads(line) for line in record.read_text().splitlines()]
        roles = ['planner', 'executor'] if legacy else ['planner', 'executor', 'reviewer']
        assert [a.request.role for a in run.history.attempts] == roles
        assert len(launches) == len(roles)
        assert len({a.request.id for a in run.history.attempts}) == len(roles)
        environment = {k: v for k, v in expected.items() if not legacy or k != 'USER'}
        assert passed_environments and all(e == environment for e in passed_environments)
        processes = repo.processes(job.id)
        assert all(p['status'] == 'STOPPED' for p in processes)
        for attempt, launch, process in zip(run.history.attempts, launches, processes):
            # CPython locale coercion and macOS CoreFoundation can add these
            # at runtime. The Popen boundary above must still receive exact env.
            observed = launch['environment'].copy()
            observed.pop('LC_CTYPE', None)
            observed.pop('__CF_USER_TEXT_ENCODING', None)
            assert observed == environment
            spec = process['spec']
            assert spec['environment_keys'] == sorted(environment)
            assert spec['environment_sha256'] == hashlib.sha256(freeze(environment).encode()).hexdigest()
            assert spec['adapter_version'] == 'cli-14' and spec['timeout_seconds'] == 60
            model = 'claude-sonnet-4-6' if attempt.request.role == 'executor' else 'gpt-6-luna'
            assert attempt.request.selection.model == model and attempt.request.selection.effort == 'low'
            assert attempt.request.fresh_session and spec['requested']['fresh_session']
            args = launch['argv']
            assert args[args.index('--model') + 1] == model
            assert not {'--resume', '--continue', '--fallback-model'} & set(args)
            if launch['provider'] == 'claude':
                assert args[args.index('--effort') + 1] == 'low'
                for flag in ('--tools', '--allowedTools', '--setting-sources'):
                    assert args[args.index(flag) + 1] == ''
                assert '--strict-mcp-config' in args
                assert json.loads(args[args.index('--mcp-config') + 1]) == {'mcpServers': {}}
                assert json.loads(args[args.index('--settings') + 1]) == {'disableAllHooks': True, 'autoMemoryEnabled': False}
                assert args[args.index('--session-id') + 1] == attempt.request.id
                assert args[args.index('--permission-mode') + 1] == 'dontAsk'
                assert args[args.index('--permission-prompts') + 1] == 'none'
                assert '--no-session-persistence' in args and '--no-chrome' in args
                assert '--disable-slash-commands' in args
            else:
                assert '--strict-config' in args and '--ignore-user-config' in args
                assert '--ignore-rules' in args and '--ephemeral' in args
                assert 'model_reasoning_effort="low"' in args and 'approval_policy="never"' in args
                assert args[args.index('--sandbox') + 1] == 'read-only'
        frozen = json.loads(run.versions_json)
        assert frozen['cli_config_sha256'] == port.frozen_versions()['cli_config_sha256']
        assert frozen['agent_adapter'] == 'cli-14'
        changed = CLIProcessAdapter([replace(c, environment=tuple(expected.items()) if legacy else
                                    tuple((k, v) for k, v in expected.items() if k != 'USER'))
                                    for c in port.agents.values()], port.artifact_root)
        assert changed.frozen_versions()['cli_config_sha256'] != frozen['cli_config_sha256']
        if legacy:
            assert job.status == run.status == 'RECOVERY_REQUIRED'
            assert run.history.attempts[-1].result.status == 'failed'
            assert run.history.attempts[-1].result.payload_json is None
            assert run.history.attempts[-1].result.terminal_observed
            before_events = repo.events(job.run_id)
            before_bytes = {p: p.read_bytes() for p in port.artifact_root.rglob('*') if p.is_file()}
            def persisted_rows():
                with engine.connect() as connection:
                    return {table: connection.exec_driver_sql(f'select * from {table}').fetchall()
                            for table in ('managed_runs', 'managed_attempts', 'managed_jobs',
                                          'managed_processes', 'managed_events', 'checkout_locks')}
            before_rows = persisted_rows()
            monkeypatch.setattr(changed, 'preflight', lambda: pytest.fail('Mismatch must stop before preflight'))
            with pytest.raises(JournalError, match='configuration differs'):
                changed.bind_process_journal(_Journal(repo, job, Event()))
            assert repo.get_run(job.run_id) == run and repo.processes(job.id) == processes
            assert repo.events(job.run_id) == before_events
            assert persisted_rows() == before_rows
            assert all(p.read_bytes() == data for p, data in before_bytes.items())
            assert len(record.read_text().splitlines()) == 2
            assert repo.claim() is None
            with engine.connect() as connection:
                assert connection.exec_driver_sql('select count(*) from checkout_locks').scalar() == 1
        else:
            assert job.status == 'DONE'
            assert all(a.result.status == 'complete' for a in run.history.attempts)
    finally:
        engine.dispose()
