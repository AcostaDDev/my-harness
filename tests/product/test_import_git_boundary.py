"""P008-T016: H1–H3 regressions with temporary Git/SQLite, no providers or real code."""
from hashlib import sha256
import os
import shlex
import sys

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.adapters.git import Git
from my_harness.adapters.import_git import check_filters
from my_harness.core.engine.commit import CommitIntent
from my_harness.core.tree import ImportInventoryError
from my_harness.storage.managed import Conflict
from my_harness.storage.models import ManagedJobRow, ProjectImportRow
from my_harness.storage.phases import PhaseRepository
from onboarding_helpers import checkout_state, operation
from test_onboarding_commit import confirm, preview, ready
from test_onboarding_conversation import world  # noqa: F401
from test_project_onboarding import checkout


def install_filter(root, kind, included):
    """The fake filter would leave a marker if Git invoked it; it must never run."""
    port = Git(root)
    marker = root.parent / 'filter-invoked'
    script = root.parent / 'filter probe.py'
    script.write_text('import pathlib, sys\npathlib.Path(' + repr(str(marker))
                      + ').write_text("invoked")\nsys.stdout.buffer.write(sys.stdin.buffer.read())\n')
    command = shlex.join([sys.executable, str(script)])
    if included:
        config = root.parent / 'included.config'
        port.run('config', '--file', str(config), f'filter.synthetic.{kind}', command)
        port.run('config', 'include.path', str(config))
    else:
        port.run('config', f'filter.synthetic.{kind}', command)
    (root / '.git/info/attributes').write_text('*.md filter=synthetic\n')
    doc = root / 'README.md'
    stamp = doc.stat().st_mtime_ns
    os.utime(doc, ns=(stamp - 3_000_000_000, stamp - 3_000_000_000))
    return marker


def job_count(world):
    with Session(world.engine) as session:
        return session.scalar(select(func.count()).select_from(ManagedJobRow))


def assert_no_effect(world, before, jobs):
    assert checkout_state(world.context.root) == before
    assert job_count(world) == jobs
    assert operation(world) is None
    assert PhaseRepository(world.repo).list(str(world.context.root)) == []
    assert Git(world.context.root).text('rev-list', '--count', 'HEAD') == '1'


@pytest.mark.parametrize('kind', ['clean', 'process'])
@pytest.mark.parametrize('included', [False, True])
def test_inventory_rejects_filters_before_status_without_touching_git(tmp_path, monkeypatch, kind, included):
    root = checkout(tmp_path / 'repo', {'README.md': '# Synthetic source\n'})
    marker = install_filter(root, kind, included)
    before = checkout_state(root)
    calls = []
    original = Git.run

    def recording(self, *args, **kwargs):
        calls.append(args[1] if args[0] == '--no-lazy-fetch' else args[0])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Git, 'run', recording)
    with pytest.raises(ImportInventoryError, match='Git filters'):
        check_filters(Git(root))
    assert 'config' in calls and not {'status', 'add', 'hash-object'} & set(calls)
    assert not marker.exists() and checkout_state(root) == before


@pytest.mark.parametrize('stage,kind,included', [
    ('preview', 'clean', False), ('preview', 'process', True),
    ('confirm', 'clean', True), ('confirm', 'process', False),
])
def test_preview_and_confirmation_refuse_new_filters_before_capture(world, monkeypatch, stage, kind, included):
    cid = ready(world)
    shown = preview(world, cid)
    marker = install_filter(world.context.root, kind, included)
    before, jobs = checkout_state(world.context.root), job_count(world)

    def forbidden(*args):
        pytest.fail('Git capture/seal must not precede the filter guard')

    monkeypatch.setattr(world.writer, 'capture', forbidden)
    monkeypatch.setattr(world.writer, 'seal', forbidden)
    with pytest.raises(Conflict, match='Git filters'):
        preview(world, cid) if stage == 'preview' else confirm(world, cid, shown)
    assert not marker.exists()
    assert_no_effect(world, before, jobs)


@pytest.mark.parametrize('kind,included', [('clean', False), ('process', True)])
def test_job_rejects_filters_before_writing_and_recovers_same_intent(world, monkeypatch, kind, included):
    cid = ready(world)
    shown = preview(world, cid)
    job = confirm(world, cid, shown)
    with Session(world.engine) as session:
        sealed = session.scalar(select(ProjectImportRow)).intent
    marker = install_filter(world.context.root, kind, included)
    before = checkout_state(world.context.root)

    def forbidden(*args):
        pytest.fail('No writer operation is allowed before rejecting filters')

    with monkeypatch.context() as blocked:
        for name in ('capture', 'seal', 'execute_documents'):
            blocked.setattr(world.writer, name, forbidden)
        with pytest.raises(ImportInventoryError, match='Git filters'):
            world.worker.run_once()
    assert not marker.exists() and checkout_state(world.context.root) == before
    assert not world.context.path('GEMINI.md').exists()
    assert world.repo.get_job(job.id).status == 'RECOVERY_REQUIRED'
    assert PhaseRepository(world.repo).list(str(world.context.root)) == []
    port = Git(world.context.root)
    assert port.text('rev-list', '--count', 'HEAD') == '1'
    port.run('config', '--unset-all', 'include.path' if included else f'filter.synthetic.{kind}')
    (world.context.root / '.git/info/attributes').unlink()
    world.repo.confirm_stopped(job.id, owner_token=world.repo.get_job(job.id).owner_token,
        expected_version=world.repo.get_run(job.run_id).version, reason='Synthetic writer stopped')
    resumed = confirm(world, cid)
    assert resumed.run_id == job.run_id
    assert world.worker.run_once().status == 'DONE'
    assert operation(world)['status'] == 'COMPLETED'
    assert port.text('rev-parse', 'HEAD') == CommitIntent.from_json(sealed).expected_commit
    with Session(world.engine) as session:
        assert session.scalar(select(ProjectImportRow)).intent == sealed




def test_ignored_gemini_blocks_preview_and_confirmation_without_any_writes(world):
    root = world.context.root
    ignore = root / '.gitignore'
    ignore.write_text(ignore.read_text() + 'GEMINI.md\n')
    port = Git(root)
    port.run('add', '.gitignore')
    port.run('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
             'commit', '-qm', 'Synthetic ignored destination')
    cid = ready(world)
    before, jobs = checkout_state(root), job_count(world)
    for action in (lambda: preview(world, cid), lambda: confirm(world, cid, {'preview_sha256': '0' * 64,
                    'resume_operation_id': None, 'expected_version': None, 'profile_sha256': '0' * 64})):
        with pytest.raises(Conflict, match='ignored by Git'):
            action()
        assert checkout_state(root) == before and job_count(world) == jobs
        assert operation(world) is None and not (root / 'GEMINI.md').exists()
        assert PhaseRepository(world.repo).list(str(root)) == []
        assert port.text('rev-list', '--count', 'HEAD') == '2'


def test_new_ignore_rule_after_confirmation_blocks_job_before_writing(world):
    cid = ready(world)
    confirm(world, cid)
    (world.context.root / '.git/info/exclude').write_text('GEMINI.md\n')
    before = checkout_state(world.context.root)
    with pytest.raises(ValueError, match='ignored by Git'):
        world.worker.run_once()
    assert checkout_state(world.context.root) == before
    assert not world.context.path('GEMINI.md').exists()
    assert PhaseRepository(world.repo).list(str(world.context.root)) == []


def test_attribute_conversion_after_confirmation_is_rejected_before_writing(world):
    cid = ready(world)
    world.planning.edit_draft(world.context, cid, world.view(cid)['version'], path='GEMINI.md',
        content='# Gemini\r\n\r\n@AGENTS.md\r\n', base_sha256=world.view(cid)['known']['GEMINI.md'], writer=None)
    shown = preview(world, cid)
    confirm(world, cid, shown)
    (world.context.root / '.git/info/attributes').write_text('GEMINI.md text eol=lf\n')
    before = checkout_state(world.context.root)
    assert world.worker.run_once().status == 'DONE'
    assert operation(world)['result']['status'] == 'INVALIDATED'
    assert checkout_state(world.context.root) == before
    assert not world.context.path('GEMINI.md').exists()
    assert PhaseRepository(world.repo).list(str(world.context.root)) == []


def test_final_seal_cannot_change_the_preview_tree(world, monkeypatch):
    cid = ready(world)
    world.planning.edit_draft(world.context, cid, world.view(cid)['version'], path='GEMINI.md',
        content='# Gemini\r\n\r\n@AGENTS.md\r\n', base_sha256=world.view(cid)['known']['GEMINI.md'], writer=None)
    shown = preview(world, cid)
    before, jobs = checkout_state(world.context.root), job_count(world)
    original, calls = world.writer.seal, []

    def changed(context, plan):
        calls.append(plan)
        if len(calls) == 2:  # First: recompute preview. Second: seal the persisted commit intent.
            attributes_file = context.root / '.git/info/attributes'
            attributes_file.write_text('GEMINI.md text eol=lf\n')
            try:
                return original(context, plan)
            finally:
                attributes_file.unlink()
        return original(context, plan)

    monkeypatch.setattr(world.writer, 'seal', changed)
    with pytest.raises(ValueError, match='changed after the import preview'):
        confirm(world, cid, shown)
    assert_no_effect(world, before, jobs)
