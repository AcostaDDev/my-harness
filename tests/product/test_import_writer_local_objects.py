"""P008-T020: A/B writer without transports; temporary Git/SQLite and fake tools only."""
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.git import Git, GitError, GitWorkspace
from my_harness.adapters.local_git import LocalGit
from my_harness.core.engine.commit import CommitIntent
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PhaseRow, ProjectImportRow
from my_harness.storage.phases import PhaseRepository
from onboarding_helpers import operation
from onboarding_helpers import tree_state
from test_import_local_objects import promisor
from test_managed_api import IDENTITY
from test_onboarding_commit import confirm as onboarding_confirm, preview as onboarding_preview, ready as onboarding_ready
from test_onboarding_conversation import world as onboarding_world  # noqa: F401


def flow_ports(flow, request):
    """Only the world of the parametrized flow is built; the other would be discarded preparation."""
    return (request.getfixturevalue('onboarding_world'), onboarding_ready, onboarding_preview, onboarding_confirm)


def sealed(world):
    with Session(world.engine) as session:
        return session.scalar(select(ProjectImportRow)).intent


def stop(world, job):
    world.repo.confirm_stopped(job.id, owner_token=world.repo.get_job(job.id).owner_token,
        expected_version=world.repo.get_run(job.run_id).version, reason='Synthetic writer stopped')


@pytest.mark.parametrize('flow,crash', [
    ('B', None), ('B', 'before'), ('B', 'write'), ('B', 'commit'), ('B', 'register'),
])
def test_all_writer_commands_stay_local_and_recover_same_intent(request, monkeypatch, flow, crash):
    world, prepare, show, submit = flow_ports(flow, request)
    cid = prepare(world)
    root = world.context.root
    _, _, marker = promisor(root)
    local = LocalGit(root)
    objects = local.run('rev-list', '--objects', '--no-object-names', 'HEAD')
    assert b' missing' not in local.run('cat-file', '--batch-check', input=objects)
    configuration = (root / '.git/config').read_bytes()
    requests = list(world.ports.agents.requests)
    calls = []
    original_run, original_code = Git.run, Git.code

    def recording_run(self, *args, **kwargs):
        assert args[0] == '--no-lazy-fetch'
        calls.append(('run', args[1:]))
        return original_run(self, *args, **kwargs)

    def recording_code(self, *args, **kwargs):
        assert args[0] == '--no-lazy-fetch'
        calls.append(('code', args[1:]))
        return original_code(self, *args, **kwargs)

    monkeypatch.setattr(Git, 'run', recording_run)
    monkeypatch.setattr(Git, 'code', recording_code)
    shown = show(world, cid)
    job = submit(world, cid, shown)
    frozen = sealed(world)
    intent = CommitIntent.from_json(frozen)
    assert local.code('cat-file', '-e', intent.expected_commit + '^{commit}') != 0
    assert not marker.exists()
    # Each run gets a new port, like the real composition; it does not inherit the preview mode.
    world.writer = GitWorkspace(IDENTITY)
    if crash:
        target, name = ((world.repo, 'finish') if crash == 'register' else
                        (world.writer, '_write_mechanical' if crash == 'write' else 'execute_documents'))
        original = getattr(target, name)

        def fail(*args, **kwargs):
            if crash in ('write', 'commit'):
                original(*args, **kwargs)
            raise RuntimeError('synthetic writer crash')

        with monkeypatch.context() as interrupted:
            interrupted.setattr(target, name, fail)
            with pytest.raises(RuntimeError, match='synthetic writer crash'):
                world.worker.run_once()
        assert not marker.exists() and world.repo.get_job(job.id).status == 'RECOVERY_REQUIRED'
        stop(world, job)
        world.writer = GitWorkspace(IDENTITY)
        resumed = submit(world, cid)
        assert resumed.run_id == job.run_id
        world.writer = GitWorkspace(IDENTITY)
    assert world.worker.run_once().status == 'DONE'
    assert operation(world)['status'] == 'COMPLETED' and sealed(world) == frozen
    assert local.text('rev-parse', 'HEAD') == intent.expected_commit
    assert local.text('rev-list', '--count', 'HEAD') == '2'
    assert local.text('write-tree') == intent.expected_tree
    assert local.run('status', '--porcelain') == b''
    assert not marker.exists() and (root / '.git/config').read_bytes() == configuration
    assert world.ports.agents.requests == requests
    with Session(world.engine) as session:
        phase, = session.scalars(select(PhaseRow)).all()
        assert phase.documents == shown['baseline'] and phase.status == 'ACTIVE'
    assert ('code', ('cat-file', '-e', intent.expected_commit + '^{commit}')) in calls
    assert any(api == 'run' and args[:4] == ('hash-object', '-t', 'commit', '-w') for api, args in calls)
    assert any(api == 'run' and args[0] == 'update-ref' for api, args in calls)
    assert any(api == 'run' and args[0] == 'read-tree' for api, args in calls)
    # Reconciliation after a later commit: merge-base also uses the local boolean API.
    local.run('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
              'commit', '--allow-empty', '-qm', 'Synthetic later commit')
    assert world.writer.execute_documents(world.context, intent, shown['documents']).status == 'reconciled'
    assert ('code', ('merge-base', '--is-ancestor', intent.expected_commit, local.text('rev-parse', 'HEAD'))) in calls
    assert not marker.exists() and sealed(world) == frozen


@pytest.mark.parametrize('flow,missing', [
    ('B', 'source-blob'), ('B', 'source-tree'), ('B', 'sealed-blob'), ('B', 'sealed-tree'),
])
def test_required_source_or_sealed_objects_block_job_and_resume_without_effects(request, flow, missing):
    world, prepare, show, submit = flow_ports(flow, request)
    root = world.context.root
    # A blob outside the documentation is also needed to capture the whole tree.
    (root / 'synthetic-payload.bin').write_bytes(b'\x00Synthetic code payload\xff')
    git = LocalGit(root)
    git.run('add', 'synthetic-payload.bin')
    git.run('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
            'commit', '-qm', 'Synthetic source object')
    cid = prepare(world)
    shown = show(world, cid)
    job = submit(world, cid, shown)
    frozen = sealed(world)
    intent = CommitIntent.from_json(frozen)
    revision = {'source-blob': 'HEAD:synthetic-payload.bin', 'source-tree': 'HEAD^{tree}',
                'sealed-blob': intent.expected_tree + ':GEMINI.md', 'sealed-tree': intent.expected_tree}[missing]
    obj, path, marker = promisor(root, revision)
    data = path.read_bytes()
    path.unlink()
    before = tree_state(root)
    with pytest.raises((GitError, ValueError), match='missing|local|tree'):
        world.worker.run_once()
    assert world.repo.get_job(job.id).status == 'RECOVERY_REQUIRED'
    assert tree_state(root) == before and not marker.exists() and not path.exists()
    assert PhaseRepository(world.repo).list(str(root)) == []
    stop(world, job)
    with pytest.raises(Conflict, match='missing|local|tree'):
        submit(world, cid)
    assert tree_state(root) == before and not marker.exists() and not path.exists()
    assert sealed(world) == frozen
    # Restoring only the synthetic bytes allows reconciling the original intention, without fetch.
    path.write_bytes(data)
    assert git.text('cat-file', '-t', obj) in ('blob', 'tree')
    assert submit(world, cid).run_id == job.run_id
    assert world.worker.run_once().status == 'DONE'
    assert operation(world)['status'] == 'COMPLETED' and sealed(world) == frozen
    assert git.text('rev-parse', 'HEAD') == intent.expected_commit and not marker.exists()


def unsupported_git(root):
    script = root.parent / 'unsupported git.py'
    calls, fallback = root.parent / 'old-git-calls', root.parent / 'unsafe-fallback'
    script.write_text('#!' + sys.executable + '\nimport pathlib, sys\n'
        'with pathlib.Path(' + repr(str(calls)) + ').open("a") as log:\n'
        '    log.write(repr(sys.argv[1:]) + "\\n")\n'
        'if "--no-lazy-fetch" in sys.argv:\n'
        '    sys.stderr.write("unknown option: --no-lazy-fetch\\n")\n'
        '    raise SystemExit(129)\n'
        'pathlib.Path(' + repr(str(fallback)) + ').write_text("unsafe")\nraise SystemExit(0)\n')
    script.chmod(0o755)
    return str(script), calls, fallback


@pytest.mark.parametrize('api', ['run', 'code'])
def test_both_local_apis_reject_unsupported_git_instead_of_reporting_future_commit_absent(tmp_path, api):
    executable, calls, fallback = unsupported_git(tmp_path / 'repo')
    git = LocalGit(tmp_path, executable=executable)
    with pytest.raises(GitError, match='unknown option: --no-lazy-fetch'):
        getattr(git, api)('cat-file', '-e', 'a' * 40 + '^{commit}')
    assert len(calls.read_text().splitlines()) == 1 and not fallback.exists()


@pytest.mark.parametrize('flow', ['B'])
@pytest.mark.parametrize('stage', ['preview', 'job', 'resume'])
def test_unsupported_writer_git_blocks_before_any_checkout_effect(request, monkeypatch, flow, stage):
    world, prepare, show, submit = flow_ports(flow, request)
    cid = prepare(world)
    if stage != 'preview':
        job = submit(world, cid)
        if stage == 'resume':
            with monkeypatch.context() as interrupted:
                def fail(*args, **kwargs):
                    raise RuntimeError('synthetic writer crash')
                interrupted.setattr(world.writer, 'execute_documents', fail)
                with pytest.raises(RuntimeError, match='synthetic writer crash'):
                    world.worker.run_once()
            stop(world, job)
            assert submit(world, cid).run_id == job.run_id
    executable, calls, fallback = unsupported_git(world.context.root)
    world.writer = GitWorkspace(IDENTITY, executable=executable)
    before = tree_state(world.context.root)
    error = Conflict if stage == 'preview' else GitError
    with pytest.raises(error, match='unknown option: --no-lazy-fetch'):
        show(world, cid) if stage == 'preview' else world.worker.run_once()
    assert tree_state(world.context.root) == before and not fallback.exists()
    assert len(calls.read_text().splitlines()) == 1
    assert PhaseRepository(world.repo).list(str(world.context.root)) == []
    if stage == 'preview':
        assert operation(world) is None
