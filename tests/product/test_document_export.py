"""Offline export over temporary Git and SQLite; no agents or providers."""
from dataclasses import replace
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.git import GitWorkspace
from my_harness.core.engine.document_export import BEGIN, END, replace_block, text_hash
from my_harness.core.engine.journal import JournalError
from my_harness.storage.document_export import DocumentExportRepository
from my_harness.storage.managed import Conflict
from my_harness.storage.models import ManagedAttemptRow, PhaseOperationRow, ManagedJobRow
from test_managed import repository  # noqa: F401
from test_managed_api import VERSIONS, LOCAL, client, git
from test_phases import world, checkout, head, phase_review, tags  # noqa: F401


def exporter(w):
    return DocumentExportRepository(w.repository)


def shown(w, pid):
    return exporter(w).preview(w.context, pid, w.ports.writer(w.context, VERSIONS))


def queue(w, pid, view=None, key=None):
    view = view or shown(w, pid)
    return exporter(w).submit(w.context, pid, view['expected_version'], key=key or w.key(), versions=VERSIONS,
                              preview_sha256=view['preview_sha256'], reason='Reviewed exact synthetic diff',
                              confirmed=True, git=w.ports.writer(w.context, VERSIONS),
                              resume_operation_id=view['resume_operation_id'])


def docs(w):
    return {p: w.context.path(p).read_bytes() for p in (w.context.state_file, w.context.next_steps_file)}


def confirm(w, job):
    row = w.repository.get_job(job.id)
    w.repository.confirm_stopped(job.id, owner_token=row.owner_token,
                                 expected_version=w.repository.get_run(job.run_id).version, reason='Synthetic writer stopped')


def test_exact_export_preserves_prose_deterministic_idempotent_and_adopts_after_commit(world):
    world.context.path('docs/STATE.md').write_bytes(b'# Human\r\nKeep exactly.\r\n')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-q', '-m', 'human prose')
    world.accept_task()
    pid = world.create()
    world.phases.raise_question(pid, world.get(pid)['version'], text='Decide wording <script>')
    original, old_head = docs(world), head(world)
    a, b = shown(world, pid), shown(world, pid)
    assert a == b and docs(world) == original and head(world) == old_head
    assert a['snapshot']['tasks']['P001-T001']['acceptance'] is True
    assert a['snapshot']['tasks']['P001-T001']['commit'] == old_head
    assert a['snapshot']['open_questions'][0]['text'].endswith('<script>')
    assert '<script>' not in a['documents'][0]['content']
    job = queue(world, pid, a, key='export-once')
    assert docs(world) == original
    assert queue(world, pid, a, key='export-once').id == job.id
    world.run()
    new_head = head(world)
    assert new_head != old_head and git(world.context.root, 'rev-parse', 'HEAD^') == old_head
    assert git(world.context.root, 'status', '--porcelain') == ''
    assert docs(world)['docs/STATE.md'].startswith(original['docs/STATE.md'])
    detail = world.get(pid)
    assert detail['documents']['drift'] == [] and detail['status'] == 'BLOCKED'
    assert detail['operations'][-1]['status'] == 'COMMITTED'
    assert world.repository.get_run(job.run_id).status == 'COMMITTED'
    assert world.ports.roles() == ['executor', 'reviewer']  # export has no agents
    assert queue(world, pid, a, key='export-once').id == job.id  # retry after restart/effect
    assert world.worker.run_once() is None and head(world) == new_head
    with pytest.raises(Conflict, match='no change'):
        queue(world, pid)


@pytest.mark.parametrize('text', [BEGIN, END, END + '\n' + BEGIN, BEGIN + '\nx\n' + END + '\n' + END,
                                  'prefix ' + BEGIN + '\nx\n' + END, BEGIN + 'inline\n' + END,
                                  BEGIN + '\rinline\n' + END, BEGIN + '\nx\n' + END + '\rinline'])
def test_malformed_markers_never_touch_prose(text):
    with pytest.raises(ValueError, match='markers'):
        replace_block(text, 'new\n')


def test_block_replacement_preserves_suffix_prefix_and_newlines():
    text = '# Human\r\n' + BEGIN + '\r\nold\r\n' + END + '\r\nEnd\r\n'
    assert replace_block(text, 'new\n') == '# Human\r\n' + BEGIN + '\nnew\n' + END + '\r\nEnd\r\n'


@pytest.mark.parametrize('when', ['before_preview', 'after_preview', 'after_queue'])
def test_external_document_edits_are_never_overwritten(world, when):
    pid = world.create()
    view = shown(world, pid)
    if when == 'after_queue':
        job = queue(world, pid, view)
    world.context.path('docs/STATE.md').write_text('external\n', encoding='utf-8')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-q', '-m', 'external document')
    before, old = docs(world), head(world)
    if when == 'before_preview':
        with pytest.raises(Conflict, match='externally'):
            shown(world, pid)
    elif when == 'after_preview':
        with pytest.raises(Conflict, match='externally'):
            queue(world, pid, view)
    else:
        world.run()
        assert world.get(pid)['operations'][-1]['status'] == 'INVALIDATED'
        assert world.repository.get_run(job.run_id).status == 'STOPPED'
    assert docs(world) == before and head(world) == old


@pytest.mark.parametrize('change', ['untracked', 'staged', 'markers', 'missing', 'symlink', 'protected', 'same_path'])
def test_preview_fails_closed(world, change):
    if change == 'protected':
        world.context = replace(world.context, profile=replace(world.context.profile, protected_paths=('docs/*',)))
    elif change == 'same_path':
        world.context = replace(world.context, next_steps_file=world.context.state_file)
    pid = world.create()
    target = world.context.path(world.context.state_file)
    if change == 'untracked':
        (world.context.root / 'new.txt').write_text('unrelated\n')
    elif change == 'staged':
        # Different index even though the worktree goes back to HEAD.
        target.write_text('staged\n')
        git(world.context.root, 'add', '-A')
        target.write_text('# State\n')
    elif change == 'markers':
        target.write_text(BEGIN)
        git(world.context.root, 'add', '-A')
        git(world.context.root, 'commit', '-q', '-m', 'malformed markers')
        world.phases.reconcile(world.context, pid, world.get(pid)['version'],
                               documents_sha256=world.get(pid)['documents']['current_sha256'], reason='Adopt malformed synthetic doc')
    elif change == 'missing':
        target.unlink()
    elif change == 'symlink':
        target.unlink()
        target.symlink_to(world.context.root / 'app/main.txt')
    with pytest.raises((Conflict, ValueError)):
        shown(world, pid)


@pytest.mark.parametrize('point', ['before_write', 'partial_write', 'after_commit', 'before_adoption'])
def test_crash_recovery_reuses_intent_without_duplicate_commits(world, point, monkeypatch):
    pid = world.create()
    before, original_head = docs(world), head(world)
    job = queue(world, pid)
    original_write, original_execute = GitWorkspace._write_mechanical, GitWorkspace.execute
    original_settle = __import__('my_harness.storage.document_export', fromlist=['settle']).settle
    once = [False]
    def write(self, context, intent):
        if not once[0]:
            once[0] = True
            if point == 'partial_write':
                original_write(self, context, intent)
            raise RuntimeError('synthetic write crash')
        return original_write(self, context, intent)
    def execute(self, context, intent):
        result = original_execute(self, context, intent)
        if not once[0]:
            once[0] = True
            raise RuntimeError('synthetic post commit crash')
        return result
    def settle(*args):
        original_settle(*args)
        if not once[0]:
            once[0] = True
            raise RuntimeError('synthetic adoption transaction crash')
    if point in ('before_write', 'partial_write'):
        monkeypatch.setattr(GitWorkspace, '_write_mechanical', write)
    elif point == 'after_commit':
        monkeypatch.setattr(GitWorkspace, 'execute', execute)
    else:
        monkeypatch.setattr('my_harness.storage.document_export.settle', settle)
    with pytest.raises((RuntimeError, JournalError), match='synthetic'):
        world.run()
    with Session(world.repository.engine) as session:
        op = session.scalar(select(PhaseOperationRow).where(PhaseOperationRow.run_id == job.run_id))
        raw = op.request['commit_intent']
        expected = json.loads(raw)['expected_commit']
        assert op.status == 'INTENT'
        assert session.get(ManagedJobRow, job.id).status == 'RECOVERY_REQUIRED'
        assert session.scalar(select(ManagedAttemptRow.id)) is None
    assert world.get(pid)['documents']['baseline'] == {p: text_hash(v.decode()) for p, v in before.items()}
    with pytest.raises(Conflict, match='unfinished'):
        shown(world, pid)
    confirm(world, job)
    recovered = shown(world, pid)
    assert recovered['resume_operation_id'] == op.id
    resumed = queue(world, pid, recovered)
    assert resumed.run_id == job.run_id
    world.run()
    assert head(world) == expected and git(world.context.root, 'rev-parse', 'HEAD^') == original_head
    assert git(world.context.root, 'status', '--porcelain') == ''
    assert world.get(pid)['documents']['drift'] == []
    assert world.get(pid)['operations'][-1]['result']['commit'] == expected
    assert world.worker.run_once() is None


def test_closed_phase_exports_separately_without_moving_tag_and_old_phase_refused(world):
    pid = world.create(tasks=())
    _, ready = world.check(pid, phase_review())
    world.close(pid)
    tag = git(world.context.root, 'rev-parse', 'refs/tags/phase-P001-complete')
    assert BEGIN.encode() not in docs(world)['docs/STATE.md']
    job = queue(world, pid)
    world.run()
    assert world.get(pid)['status'] == 'CLOSED' and head(world) != tag
    assert git(world.context.root, 'rev-parse', 'refs/tags/phase-P001-complete') == tag
    assert world.repository.get_run(job.run_id).status == 'COMMITTED'
    world.create(code='P002', tasks=(), tag=None)
    with pytest.raises(Conflict, match='latest phase'):
        shown(world, pid)


def test_stale_sqlite_preview_version_hash_and_confirmation_rejected(world):
    pid = world.create()
    view = shown(world, pid)
    with pytest.raises(ValueError, match='confirmation'):
        exporter(world).submit(world.context, pid, view['expected_version'], key='no-confirm', versions=VERSIONS,
                               preview_sha256=view['preview_sha256'], reason='x', confirmed=False,
                               git=world.ports.writer(world.context, VERSIONS))
    world.phases.raise_question(pid, world.get(pid)['version'], text='new question')
    with pytest.raises(Conflict, match='Preview changed'):
        queue(world, pid, view)
    queued = queue(world, pid)
    # Changing the authority after admission does not allow an effect with a stale snapshot.
    with Session(world.repository.engine) as session:
        from my_harness.storage.models import PhaseRow
        p = session.get(PhaseRow, pid)
        p.status = 'ACTIVE'
        session.commit()
    old = head(world)
    with pytest.raises(Conflict, match='authority changed'):
        world.run()
    assert head(world) == old and world.repository.get_job(queued.id).status == 'RECOVERY_REQUIRED'


def test_active_batch_prevents_export(world):
    pid = world.create()
    world.phases.authorize_batch(pid, world.get(pid)['version'], tasks=['P001-T001'], ttl_seconds=3600, reason='x')
    with pytest.raises(Conflict, match='Revoke'):
        shown(world, pid)


def test_http_guard_confirmation_versions_idempotency_and_projection(world, tmp_path):
    from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
    pid = world.create()
    configuration = ManagedConfig((ManagedProject('synthetic', world.context, VERSIONS),),
                                  ports_factory=world.ports, commit_factory=world.ports.writer, supervisor=False)
    path = f'/api/managed/phases/{pid}/export'
    with client(str(world.repository.engine.url), tmp_path, configuration) as http:
        view = http.get(path)
        assert view.status_code == 200, view.text
        v = view.json()
        assert v == http.get(path).json() and v['diff']
        body = {'expected_version': v['expected_version'], 'preview_sha256': v['preview_sha256'],
                'resume_operation_id': None, 'reason': 'HTTP exact diff reviewed', 'confirmed': True}
        assert http.post(path, json=body).status_code == 422  # mandatory idempotency key
        assert http.post(path, json={**body, 'confirmed': False}, headers={'Idempotency-Key': 'bad'}).status_code == 422
        assert http.post(path, json={**body, 'preview_sha256': '0' * 64},
                         headers={'Idempotency-Key': 'hash'}).status_code == 409
        assert http.post(path, json={**body, 'expected_version': v['expected_version'] + 1},
                         headers={'Idempotency-Key': 'version'}).status_code == 409
        assert http.post(path, json=body, headers={'Idempotency-Key': 'origin', 'Origin': 'https://foreign.invalid'}).status_code == 403
        # The guard precedes the lookup, managed reads included.
        assert http.get(path, headers={'Host': 'foreign.invalid'}).status_code == 403
        http.headers.pop('X-My-Harness')
        assert http.post(path, json=body, headers={'Idempotency-Key': 'missing-csrf'}).status_code == 403
        http.headers['X-My-Harness'] = '1'
        response = http.post(path, json=body, headers={'Idempotency-Key': 'http-export'})
        assert response.status_code == 202, response.text
        assert http.post(path, json=body, headers={'Idempotency-Key': 'http-export'}).json() == response.json()
        assert http.post(path, json={**body, 'reason': 'different'}, headers={'Idempotency-Key': 'http-export'}).status_code == 409
        job = response.json()
        world.run()
        detail = http.get(f"/api/managed/runs/{job['run_id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()['purpose'] == 'document_export' and detail.json()['status'] == 'COMMITTED'
        assert detail.json()['actions'] == []
        phase = http.get(f'/api/managed/phases/{pid}')
        assert phase.status_code == 200 and phase.json()['operations'][-1]['kind'] == 'document_export'
        assert phase.json()['documents']['drift'] == []
        assert http.post(path, json=body, headers={'Idempotency-Key': 'http-export'}).json()['id'] == job['id']
        assert http.get(path).json()['diff'] == ''
    # Restarting the service keeps the operation and the submission without invoking or duplicating Git.
    old = head(world)
    with client(str(world.repository.engine.url), tmp_path, configuration) as http:
        assert http.post(path, json=body, headers={'Idempotency-Key': 'http-export'}).json()['id'] == job['id']
        assert head(world) == old and world.worker.run_once() is None


def test_non_export_document_drift_blocks_before_effect(world):
    extra = world.context.path('docs/OTHER.md')
    extra.write_text('adopted\n')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-q', '-m', 'extra document')
    pid = world.create(documents=['docs/STATE.md', 'docs/NEXT_STEPS.md', 'docs/OTHER.md'])
    view = shown(world, pid)
    job = queue(world, pid, view)
    extra.write_text('external\n')
    before = docs(world)
    world.run()
    assert world.get(pid)['operations'][-1]['status'] == 'INVALIDATED'
    assert docs(world) == before and world.repository.get_run(job.run_id).status == 'STOPPED'


def test_partial_recovery_never_overwrites_new_external_bytes(world, monkeypatch):
    pid = world.create()
    job = queue(world, pid)
    original = GitWorkspace._write_mechanical
    def crash(self, context, intent):
        original(self, context, intent)
        raise RuntimeError('partial crash')
    monkeypatch.setattr(GitWorkspace, '_write_mechanical', crash)
    with pytest.raises(RuntimeError, match='partial crash'):
        world.run()
    confirm(world, job)
    view = shown(world, pid)
    # Recovery also preserves foreign changes made after the crash.
    world.context.path('docs/NEXT_STEPS.md').write_text('external after crash\n')
    before, old = docs(world), head(world)
    resumed = queue(world, pid, view)
    world.run()
    assert docs(world) == before and head(world) == old
    assert world.repository.get_run(resumed.run_id).status == 'STOPPED'
    assert world.get(pid)['operations'][-1]['status'] == 'INVALIDATED'


def test_ready_export_preserves_history_and_makes_close_stale(world):
    pid = world.create(tasks=())
    _, ready = world.check(pid, phase_review())
    queue(world, pid)
    world.run()
    detail = world.get(pid)
    assert detail['ready']['stale_reasons'] and detail['status'] == 'READY_TO_CLOSE'
    # Exporting the same state again does not generate another commit.
    assert shown(world, pid)['diff'] == ''
    world.close(pid)
    assert world.get(pid)['status'] == 'NEEDS_RECONCILIATION' and tags(world) == ''


def test_concurrent_submissions_share_one_job(world):
    from concurrent.futures import ThreadPoolExecutor
    pid = world.create()
    view = shown(world, pid)
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = list(pool.map(lambda _: queue(world, pid, view, key='concurrent-export'), range(3)))
    assert len({job.id for job in jobs}) == 1
    world.run()
    assert world.worker.run_once() is None and world.get(pid)['operations'][-1]['status'] == 'COMMITTED'
