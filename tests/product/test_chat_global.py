"""E5: snapshots and deterministic commands. Git/SQLite/fake agents only."""
from dataclasses import replace
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.chat_snapshot import HeadSnapshot, snapshot_path
from my_harness.adapters.cli_agents import CLIConfig, argv_for
from my_harness.core.engine.chat_commands import COMMANDS, parse
from my_harness.core.engine.contracts import AgentRequest, Selection, context_snapshot
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.chat import ChatRepository
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.models import CheckoutLockRow, ManagedJobRow, ChatTurnRow
from test_chat import Chat, answer, chat, jobs  # noqa: F401
from test_managed import repository  # noqa: F401
from test_managed_api import PLAN, VERSIONS, git, client, config, Ports, settle
from test_phases import checkout, world  # noqa: F401


def test_chat_uses_frozen_head_while_writer_owns_dirty_checkout(world, chat):
    writer = world.repository.submit(world.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='writer')
    claim = world.repository.claim()
    cid = chat.create()
    old_head = git(world.context.root, 'rev-parse', 'HEAD')
    job = chat.say(cid)
    world.context.path('app/main.txt').write_text('new committed version\n')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-qm', 'concurrent writer')
    world.context.path('docs/STATE.md').write_text('dirty writer state')
    def read(context, request):
        assert context.root != world.context.root
        assert context.path('app/main.txt').read_text() == 'baseline\n'
        assert context.path('docs/STATE.md').read_text() == '# State\n'
        assert context.path('app/main.txt').stat().st_mode & 0o222 == 0
        assert not (context.root / '.git').exists()
        assert old_head in request.prompt
        assert json.loads(request.prompt_snapshot_json)['rendered'] == request.prompt
        return answer()
    world.script(read)
    assert world.run().id == job.id
    with Session(world.repository.engine) as session:
        assert session.get(CheckoutLockRow, str(world.context.root)).job_id == writer.id
    assert world.repository.get_job(writer.id).status == 'ACTIVE'
    assert chat.get(cid)['turns'][0]['head'] == old_head
    assert not list(snapshot_path(world.repository, claim).parent.iterdir())
    assert world.context.path('docs/STATE.md').read_text() == 'dirty writer state'


def test_chat_ownership_and_recovery_never_release_another_writer(world, chat):
    writer = world.repository.submit(world.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='writer')
    writer_claim = world.repository.claim()
    cid = chat.create()
    chat.say(cid)
    claim = world.repository.claim(lane='chat')
    assert claim is not None
    destination = snapshot_path(world.repository, claim)
    head = chat.repo.snapshot(claim.run_id)['context']['head']
    # Persisted identity exists before any export; emulate a hard exit partway through export.
    world.repository.effect(claim, 'chat_snapshot_intent', {'head': head, 'path': str(destination)})
    HeadSnapshot(world.context.root).export(head, destination)
    (destination / 'app').chmod(0o755)
    (destination / 'app' / 'outside').symlink_to(world.context.root, target_is_directory=True)
    fresh = SQLiteManagedRepository(world.repository.engine)
    fresh.quarantine(claim, 'Synthetic process exited during export')
    assert destination.exists()
    fresh.confirm_stopped(claim.id, owner_token=claim.owner_token,
                          expected_version=fresh.get_run(claim.run_id).version, reason='Synthetic process dead')
    assert not destination.exists() and world.context.path('app/main.txt').read_text() == 'baseline\n'
    assert chat.get(cid)['turns'][0]['status'] == 'UNKNOWN'
    assert fresh.claim(lane='chat') is None
    fresh.heartbeat(writer_claim)
    with Session(fresh.engine) as session:
        assert session.get(CheckoutLockRow, str(world.context.root)).job_id == writer.id
    assert git(world.context.root, 'worktree', 'list', '--porcelain').count('worktree ') == 1


def test_failed_snapshot_creation_recovers_partial_directory(world, chat, monkeypatch):
    cid = chat.create()
    job = chat.say(cid)
    def partial(self, head, destination):
        destination.mkdir()
        (destination / 'partial').write_text('synthetic')
        raise OSError('synthetic interrupted export')
    monkeypatch.setattr(HeadSnapshot, 'export', partial)
    with pytest.raises(OSError):
        world.run()
    claim = world.repository.get_job(job.id)
    assert snapshot_path(world.repository, claim).exists()
    world.repository.confirm_stopped(job.id, owner_token=claim.owner_token,
        expected_version=world.repository.get_run(job.run_id).version, reason='worker stopped')
    assert not snapshot_path(world.repository, claim).exists()
    assert world.ports.roles() == []


def test_task_context_defaults_are_frozen_and_foreign_runs_are_rejected(world, chat, tmp_path):
    pid = world.create()
    task = world.repository.submit(world.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='task')
    cid = chat.repo.create(world.context, title='Task context', task_run_id=task.run_id)
    assert chat.get(cid)['task_run_id'] == task.run_id
    assert chat.get(cid)['phase']['id'] == pid
    job = chat.say(cid)
    assert chat.repo.snapshot(job.run_id)['context']['runs'][0]['task_id'] == 'P001-T001'
    assert chat.repo.list(str(world.context.root))[0]['task_run_id'] == task.run_id
    with pytest.raises(LookupError):
        chat.repo.create(world.context, title='Invalid', task_run_id='missing')
    with pytest.raises(LookupError):
        chat.repo.create(world.context, title='Not task', task_run_id=job.run_id)


@pytest.mark.parametrize('text', ['/nope', '/estado ahora', '/tarea', '/tarea   ', '/CHECK', '//estado'])
def test_slash_commands_never_fall_back_to_a_model(world, chat, text):
    cid = chat.create()
    with pytest.raises(ValueError):
        chat.say(cid, text=text)
    assert world.ports.roles() == [] and jobs(world) == 0


def test_all_command_previews_are_read_only_and_bind_the_observed_context(world, chat):
    pid = world.create()
    cid = chat.create(pid)
    for name in COMMANDS:
        text = '/' + name + (' Ajustar texto' if name == 'tarea' else '')
        preview = chat.repo.command_preview(world.context, cid, 0, text)
        assert preview['name'] == name and preview['phase_code'] == 'P001'
        assert preview['phase_version'] == world.get(pid)['version']
        assert preview == chat.repo.command_preview(world.context, cid, 0, text)
        if name != 'tarea':
            with pytest.raises(ValueError, match='deterministic'):
                chat.say(cid, text=text)
    assert jobs(world) == 0 and world.ports.roles() == []
    with pytest.raises(Conflict):
        chat.repo.command_preview(world.context, cid, 10, '/estado')


def test_task_command_is_idempotent_proposal_without_snapshot_or_agent(world, chat, monkeypatch):
    cid = chat.create()
    def no_head(*args):
        pytest.fail('deterministic commands do not inspect Git')
    monkeypatch.setattr(HeadSnapshot, 'head', no_head)
    job = chat.say(cid, text='/tarea Ajusta el texto', key='command')
    world.run()
    assert chat.repo.submit_message(world.context, cid, 0, key='command', versions=VERSIONS,
                                   text='/tarea Ajusta el texto').id == job.id
    detail = chat.get(cid)
    assert detail['turns'][0]['command']['name'] == 'tarea'
    assert len(detail['proposals']) == 1 and detail['proposals'][0]['proposal']['objective'] == 'Ajusta el texto'
    assert world.ports.roles() == [] and jobs(world) == 1
    with pytest.raises(ValueError, match='confirmation'):
        chat.accept(cid, detail['proposals'][0], confirmed=False)
    accepted = chat.accept(cid, detail['proposals'][0])
    assert json.loads(accepted.request_json)['action'] == 'start'


def test_codex_exported_chat_only_skips_git_discovery(tmp_path):
    from test_managed_api import make_context
    origin = make_context(tmp_path)
    snapshot = tmp_path / 'snapshot'
    snapshot.mkdir()
    execution = replace(origin, root=snapshot)
    request = AgentRequest('id', 'chat', Selection('m', 'low', 'reason'), 'prompt', None, context_snapshot(origin))
    cfg = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    argv = argv_for(cfg, execution, request)
    assert '--skip-git-repo-check' in argv and argv[argv.index('--sandbox') + 1] == 'read-only'
    assert '--skip-git-repo-check' not in argv_for(cfg, origin, request)


def test_http_commands_have_no_effect_until_explicit_proposal_acceptance(tmp_path, migrated_database, checkout):
    ports = Ports()
    with client(migrated_database[0], tmp_path, config(checkout, ports)) as http:
        cid = http.post('/api/managed/projects/synthetic/conversations', json={'title': 'Commands'},
                        headers={'Idempotency-Key': 'commands'}).json()['id']
        for name in COMMANDS:
            text = '/' + name + (' Ajusta texto' if name == 'tarea' else '')
            preview = http.post(f'/api/managed/conversations/{cid}/commands/preview', json={'expected_version': 0, 'text': text})
            assert preview.status_code == 200 and preview.json()['name'] == name
        assert http.get('/api/managed/projects/synthetic/runs').json()['items'] == []
        denied = http.post(f'/api/managed/conversations/{cid}/commands/preview',
            json={'expected_version': 0, 'text': '/estado'}, headers={'X-My-Harness': '0'})
        assert denied.status_code == 403
        job = http.post(f'/api/managed/conversations/{cid}/messages',
            json={'expected_version': 0, 'text': '/tarea Ajusta texto'}, headers={'Idempotency-Key': 'cmd'}).json()
        settle(http, job['run_id'])
        detail = http.get(f'/api/managed/conversations/{cid}').json()
        assert len(detail['proposals']) == 1 and detail['turns'][0]['status'] == 'ANSWERED'
    assert ports.roles() == []


def test_service_chat_lane_answers_while_writer_agent_is_still_running(world, chat):
    from threading import Event
    from my_harness.services.managed_runtime import SupervisorWorker
    started, release, answered = Event(), Event(), Event()
    def slow_writer(context, request):
        started.set()
        assert release.wait(10)
        return {'result': 'synthetic'}
    def fast_chat(context, request):
        assert not release.is_set()
        answered.set()
        return answer()
    from test_managed_api import review
    world.script(slow_writer, fast_chat, review())
    world.repository.submit(world.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='slow')
    worker = SupervisorWorker(world.worker, 0.01)
    worker.start()
    try:
        assert started.wait(10)
        cid = chat.create()
        chat.say(cid)
        worker.notify()
        assert answered.wait(10), worker.error()
    finally:
        release.set()
        worker.stop(10)
    assert not worker.alive() and worker.error() is None


def test_old_chat_jobs_keep_the_writer_lock_semantics(world, chat):
    cid = chat.create()
    job = chat.say(cid)
    with world.repository._write() as session:
        row = session.get(ManagedJobRow, job.id)
        request = json.loads(row.request_json)
        request['action'] = 'chat_turn'
        from my_harness.core.engine.contracts import freeze
        row.request_json = freeze(request)
    assert world.repository.claim(lane='chat') is None
    claim = world.repository.claim(lane='writer')
    with Session(world.repository.engine) as session:
        assert session.get(CheckoutLockRow, str(world.context.root)).job_id == claim.id


def test_upgrade_existing_conversation_keeps_history_and_context(migrated_database, world, chat):
    from alembic import command
    from sqlalchemy import text
    cid = chat.create()
    chat.say(cid, text='/tarea Synthetic request')
    world.run()
    command.downgrade(migrated_database[1], '0016_project_registry')
    command.upgrade(migrated_database[1], 'head')
    command.check(migrated_database[1])
    assert chat.get(cid)['task_run_id'] is None
    assert chat.get(cid)['turns'][0]['status'] == 'ANSWERED'
    assert len(chat.get(cid)['proposals']) == 1
