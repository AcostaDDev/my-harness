"""P008-T018: missing promised objects, without transport or effects; synthetic fixtures only."""
import shlex
import sys

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.adapters.git import Git, GitError
from my_harness.adapters.local_git import LocalGit
from my_harness.adapters.import_git import _blobs
from my_harness.adapters.project_onboarding import read_inventory as onboarding_inventory
from my_harness.core.tree import ImportInventoryError
from my_harness.core.project_onboarding import OnboardingInventoryError
from my_harness.storage.managed import Conflict
from my_harness.storage.models import PlanningConversationRow
from my_harness.storage.phases import PhaseRepository
from onboarding_helpers import operation
from onboarding_helpers import tree_state
from test_import_git_boundary import job_count
from test_onboarding_conversation import world as onboarding_world  # noqa: F401
from test_onboarding_commit import preview as onboarding_preview, ready as onboarding_ready
from test_project_onboarding import checkout


def promisor(root, revision='HEAD:README.md'):
    """The fake upload-pack would only create a marker. It has no network and delivers no objects."""
    git = Git(root)
    obj = git.text('rev-parse', revision)
    marker, script = root.parent / 'fetch-invoked', root.parent / 'upload-pack probe.py'
    script.write_text('from pathlib import Path\nPath(' + repr(str(marker))
                      + ').write_text("invoked")\nraise SystemExit(1)\n')
    for key, value in {
        'remote.origin.url': str(root),
        'remote.origin.promisor': 'true',
        'remote.origin.partialclonefilter': 'blob:none',
        'remote.origin.uploadpack': shlex.join([sys.executable, str(script)]),
    }.items():
        git.run('config', key, value)
    path = root / '.git/objects' / obj[:2] / obj[2:]
    return obj, path, marker


@pytest.mark.parametrize('flow', ['B'])
@pytest.mark.parametrize('point', ['tree', 'batch'])
def test_missing_promised_blob_rejects_inventory_without_transport_or_any_git_change(tmp_path, monkeypatch, flow, point):
    root = checkout(tmp_path / 'repo', {'README.md': '# Synthetic partial clone\n'})
    obj, path, marker = promisor(root)
    if point == 'tree':
        path.unlink()
    before, calls = tree_state(root), []
    original = Git.run

    def recording(self, *args, **kwargs):
        # Every command, including the first rev-parse/config/status, disables lazy-fetch.
        assert args[0] == '--no-lazy-fetch'
        calls.append(args[1])
        if point == 'batch' and args[1] == 'cat-file':
            path.unlink()
        return original(self, *args, **kwargs)

    with monkeypatch.context() as local:
        local.setattr(Git, 'run', recording)
        error = OnboardingInventoryError
        with pytest.raises(error, match=f'{obj}.*missing'):
            onboarding_inventory(root)
    if point == 'batch':
        before.pop(path.relative_to(root).as_posix())
    assert calls[0] == 'rev-parse' and 'ls-tree' in calls
    assert ('cat-file' in calls) == (point == 'batch')
    assert not marker.exists() and not path.exists() and tree_state(root) == before




def test_onboarding_shared_snapshot_reader_rejects_missing_size_before_capture(onboarding_world, monkeypatch):
    world = onboarding_world
    cid = onboarding_ready(world)
    obj, path, marker = promisor(world.context.root)
    path.unlink()
    before, jobs = tree_state(world.context.root), job_count(world)

    def forbidden(*args, **kwargs):
        pytest.fail('Missing objects must be rejected before capture/seal')

    monkeypatch.setattr(world.writer, 'capture', forbidden)
    monkeypatch.setattr(world.writer, 'seal', forbidden)
    with pytest.raises(Conflict, match=f'{obj}.*missing'):
        onboarding_preview(world, cid)
    assert tree_state(world.context.root) == before and not marker.exists() and not path.exists()
    assert job_count(world) == jobs and operation(world) is None
    assert PhaseRepository(world.repo).list(str(world.context.root)) == []


@pytest.mark.parametrize('flow', ['B'])
def test_missing_tree_object_is_rejected_without_transport(tmp_path, flow):
    root = checkout(tmp_path / 'repo', {'README.md': '# Synthetic tree\n'})
    _, path, marker = promisor(root, 'HEAD^{tree}')
    path.unlink()
    before = tree_state(root)
    error = OnboardingInventoryError
    with pytest.raises(error, match='local|tree'):
        onboarding_inventory(root)
    assert not marker.exists() and not path.exists() and tree_state(root) == before


@pytest.mark.parametrize('response', [b'', b'OBJ missing\n', b'OBJ blob BAD\n', b'OBJ blob 20\nshort\n'])
def test_shared_batch_reader_never_returns_partial_content(tmp_path, monkeypatch, response):
    git = LocalGit(tmp_path)
    monkeypatch.setattr(git, 'run', lambda *a, **kw: response.replace(b'OBJ', b'a' * 40))
    with pytest.raises(ImportInventoryError, match='Git object ' + 'a' * 40):
        _blobs(git, ['a' * 40])


@pytest.mark.parametrize('flow', ['B'])
def test_git_without_no_lazy_fetch_support_fails_on_first_command(tmp_path, monkeypatch, flow):
    root = checkout(tmp_path / 'repo', {'README.md': '# Synthetic fixture\n'})
    before, calls = tree_state(root), []

    def unsupported(self, *args, **kwargs):
        calls.append(args)
        assert args == ('--no-lazy-fetch', 'rev-parse', '--show-toplevel')
        raise GitError('unknown option: --no-lazy-fetch')

    monkeypatch.setattr(Git, 'run', unsupported)
    error = OnboardingInventoryError
    with pytest.raises(error, match='unknown option: --no-lazy-fetch'):
        onboarding_inventory(root)
    assert len(calls) == 1 and tree_state(root) == before
