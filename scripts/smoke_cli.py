"""Prepared H2.3 smoke: three bounded calls, disposable checkout, own CLI auth.

Not executed in the offline delivery. Requires a deliberate consumption flag
and explicit models/efforts. No fallback, resume, tools, commits or network tools.
The providers' model calls still use network and the user's subscription.
"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
from tempfile import mkdtemp
from threading import Event
from uuid import uuid4

from alembic import command
from alembic.config import Config

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter
from my_harness.adapters.processes import identity
from my_harness.core.engine.context import EnginePolicy, ProjectContext, ProjectProfile
from my_harness.core.engine.contracts import AgentRequest, Attempt, Selection, context_snapshot, stop_history
from my_harness.services.managed import _Journal
from my_harness.storage.database import make_engine
from my_harness.storage.managed import SQLiteManagedRepository


def smoke_environment():
    """Freeze the allowlisted environment after checking USER against the local UID."""
    user = os.environ.get('USER')
    if not user or '\0' in user:
        raise ValueError('Smoke requires a nonempty valid USER; set USER to the local UID account before consumption')
    try:
        local_user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError as exc:
        raise ValueError('Cannot resolve the local UID account; no provider processes launched') from exc
    if user != local_user:
        raise ValueError('USER differs from the local UID account; correct USER before consumption')
    # No credentials, provider selectors or configuration sources are inherited.
    return tuple((key, os.environ[key]) for key in ('HOME', 'PATH', 'TMPDIR', 'LANG', 'USER')
                 if key in os.environ)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorize-consumption', action='store_true', help='Explicitly authorize up to three provider CLI calls')
    parser.add_argument('--codex-model', required=True)
    parser.add_argument('--codex-effort', required=True)
    parser.add_argument('--claude-model', required=True)
    parser.add_argument('--claude-effort', required=True)
    parser.add_argument('--output-parent', type=Path, required=True)
    args = parser.parse_args()
    if not args.authorize_consumption:
        parser.error('Provider consumption is not authorized; no processes launched')
    try:
        env = smoke_environment()
    except ValueError as exc:
        parser.error(str(exc))
    args.output_parent.mkdir(parents=True, exist_ok=True)
    area = Path(mkdtemp(prefix='h2.3-smoke-', dir=args.output_parent)).resolve()
    root = area / 'checkout'
    root.mkdir()
    subprocess.run(('git', 'init', '-q', str(root)), check=True)
    (root / 'README.md').write_text('Disposable synthetic H2.3 smoke. No secrets.\n')
    configs = []
    for provider, version in (('codex', '0.162.1'), ('claude', '2.1.295')):
        executable = shutil.which(provider)
        if executable is None:
            raise RuntimeError(f'{provider} CLI missing; no fallback')
        configs.append(CLIConfig(provider, (executable,), version, env, 60))
    port = CLIProcessAdapter(configs, area / 'artifacts')
    reports = port.preflight()
    if not all(value['available'] for value in reports.values()):
        raise RuntimeError(f'Incompatible CLI: {reports}')
    policy = EnginePolicy((args.claude_model,), (args.claude_effort,), args.codex_model, args.codex_effort,
                          args.codex_model, args.codex_effort, max_revision_cycles=0)
    context = ProjectContext(root, ProjectProfile('smoke-read-only'), policy)
    url = f'sqlite:///{area / "smoke.sqlite3"}'
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    # env.py uses HARNESS_DATABASE_URL. This changes only this process environment.
    os.environ['HARNESS_DATABASE_URL'] = url
    command.upgrade(config, 'head')
    engine = make_engine(url)
    repository = SQLiteManagedRepository(engine)
    versions = {'engine':'h2.3-smoke','commands':None,'evidence':None, **port.frozen_versions()}
    job = repository.submit(context, 'SMOKE-T001', 'SMOKE', 'Read-only CLI stream smoke', versions, key='smoke')
    claim = repository.claim(lease_seconds=240)
    repository.register_owner(claim, identity())
    journal = _Journal(repository, claim, Event())
    port.bind_process_journal(journal)
    history = repository.get_run(job.run_id).history
    try:
        for role in ('planner', 'executor', 'reviewer'):
            selection = Selection(args.claude_model if role=='executor' else args.codex_model,
                                  args.claude_effort if role=='executor' else args.codex_effort, 'Explicit smoke selection')
            request = AgentRequest(str(uuid4()), role, selection,
                'Do not call tools or change files. This is a synthetic CLI transport test. '
                'Return a JSON object with result="smoke-ok". No implementation or review is required.',
                None, context_snapshot(context))
            request = repository.agent_started(claim, history, request)
            result = port.invoke(context, request)
            history = replace(history, attempts=history.attempts + (Attempt(request, result),))
            repository.checkpoint(claim, history, role)
            if result.status != 'complete':
                raise RuntimeError(f'{role}: {result.status}; see preserved artifacts')
        history = stop_history(history, 'smoke', 'Transport smoke complete; no task acceptance inferred')
        repository.close_owner(claim)
        repository.finish(claim, history)
        print(json.dumps({'area':str(area), 'run_id':job.run_id, 'status':'transport-complete',
                          'calls':len(history.attempts)}))
    except BaseException as exc:
        repository.quarantine(claim, f'Smoke stopped: {type(exc).__name__}')
        repository.close_owner(claim)
        raise
    finally:
        port.close()
        engine.dispose()


if __name__ == '__main__':
    main()
