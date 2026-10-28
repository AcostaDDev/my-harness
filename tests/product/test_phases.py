"""H3.3: managed phases with temporary Git/SQLite and fake agents; no providers or network."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

from alembic import command
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIConfig, argv_for
from my_harness.core.engine.commit import CommitUncertain
from my_harness.core.engine.contracts import AgentRequest, ContractError, Selection
from my_harness.core.engine.journal import JournalError
from my_harness.core.engine.phases import digest, phase_definition, validate_phase_result
from my_harness.core.engine.validation import CommandResult
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.managed_views import SQLiteManagedViews
from my_harness.storage.models import ManagedAttemptRow, PhaseEventRow
from my_harness.storage.phases import PhaseRepository
from conftest import clear_accounting
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import (
    PLAN, VERSIONS, Ports, client, edit, git, make_context, review, settle,
)

CRITERIA = ['Synthetic behavior is accepted', 'Documentation describes accepted reality']
PLAN_2 = PLAN.replace('P001-T001 — HTTP task', 'P001-T002 — Second task')


def phase_review(verdict='READY', questions=(), actions=None, **extra):
    data = {'phase_id': 'P001', 'verdict': verdict, 'summary': f'Synthetic {verdict}',
            'exit_criteria_results': [{'criterion': c, 'passed': verdict == 'READY', 'evidence': 'synthetic'}
                                      for c in CRITERIA],
            'required_actions': actions if actions is not None else ([] if verdict != 'REVISE' else ['Update docs']),
            'blocking_questions': list(questions)}
    return {**data, **extra}


def definition(context, tasks=('P001-T001',), tag='phase-P001-complete', **overrides):
    data = {'code': 'P001', 'objective': 'Synthetic phase', 'exit_criteria': CRITERIA, 'tasks': list(tasks),
            'documents': ['docs/STATE.md', 'docs/NEXT_STEPS.md'], 'tag': tag}
    return {**data, **overrides}


@pytest.fixture
def checkout(tmp_path, _legacy_close):
    root = tmp_path / 'phase-checkout'
    (root / 'app').mkdir(parents=True)
    (root / 'docs').mkdir()
    (root / 'app/main.txt').write_text('baseline\n', encoding='utf-8')
    (root / 'docs/STATE.md').write_text('# State\n', encoding='utf-8')
    (root / 'docs/NEXT_STEPS.md').write_text('# Next\n', encoding='utf-8')
    (root / 'docs/DECISIONS.md').write_text('# Decisions\n', encoding='utf-8')
    (root / 'docs/ROADMAP.md').write_text('## P001 — Synthetic phase\n\n**Objetivo:** Synthetic phase\n'
        '**Criterios de salida:**\n' + ''.join(f'- {item}\n' for item in CRITERIA), encoding='utf-8')
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', 'baseline')
    return make_context(root)


class World:
    def __init__(self, repository, context, responses=(), commands=()):
        self.repository, self.context = repository, context
        self.ports = Ports(responses, commands)
        self.worker = LocalSupervisor(repository, self.ports, commit_factory=self.ports.writer)
        self.phases = PhaseRepository(repository)
        self.keys = 0

    def key(self):
        self.keys += 1
        return f'key-{self.keys}'

    def script(self, *responses):
        self.ports.agents.responses.extend(responses)

    def run(self):
        claimed = self.worker.run_once()
        assert claimed is not None
        return claimed

    def accept_task(self, task='P001-T001', plan=PLAN, text='implemented\n'):
        def change(context, request):
            context.path('app/main.txt').write_text(text, encoding='utf-8')
            return {'result': 'synthetic'}
        self.script(change, {**review(), 'task_id': task})
        job = self.repository.submit(self.context, task, 'P001', plan, VERSIONS, key=self.key())
        self.run()
        record = self.repository.get_run(job.run_id)
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        self.repository.submit_commit(job.run_id, key=self.key(), expected_version=record.version)
        self.run()
        assert self.repository.get_run(job.run_id).status == 'COMMITTED'
        return job.run_id

    def create(self, **kwargs):
        return self.phases.create(self.context, definition(self.context, **kwargs))

    def get(self, pid):
        from my_harness.core.engine.phases import document_hashes
        root, data = self.phases.definition(pid)
        return self.phases.get(pid, document_hashes(self.context, data['documents']),
                               document_hashes(self.context, self.phases.closure_files(pid)))

    def check(self, pid, *responses):
        self.script(*responses)
        job = self.phases.submit_check(self.context, pid, self.get(pid)['version'], key=self.key(), versions=VERSIONS)
        self.run()
        return job, self.get(pid)

    def close(self, pid, binding=None, key=None):
        detail = self.get(pid)
        binding = binding or detail['ready']['binding_sha256']
        job = self.phases.submit_close(self.context, pid, detail['version'], key=key or self.key(), versions=VERSIONS,
                                       binding_sha256=binding, reason='Synthetic close decision', ttl_seconds=3600)
        self.run()
        return job, self.get(pid)

    def abandon(self, pid, reason):
        from dataclasses import replace
        job = self.phases.abandon(pid, self.get(pid)['version'], reason=reason,
                                  context=replace(self.context, documents='v2'),
                                  git=self.ports.writer(self.context, VERSIONS), key=self.key(), versions=VERSIONS)
        self.run()
        return job


@pytest.fixture
def world(repository, checkout):  # noqa: F811
    return World(repository, checkout)


def head(world):
    return git(world.context.root, 'rev-parse', 'HEAD')


def tags(world):
    return git(world.context.root, 'tag', '--list')


def kinds(world, pid):
    with Session(world.repository.engine) as session:
        rows = session.scalars(select(PhaseEventRow).where(PhaseEventRow.phase_id == pid)
                               .order_by(PhaseEventRow.sequence)).all()
        assert [row.sequence for row in rows] == list(range(1, len(rows) + 1))
        return [row.kind for row in rows]


# --- full journey -----------------------------------------------------------------------------


def test_ready_close_tags_the_reviewed_head_without_editing_documents(world):
    world.accept_task()
    pid = world.create()
    docs = {p: world.context.path(p).read_bytes() for p in ('docs/STATE.md', 'docs/NEXT_STEPS.md')}
    _, ready = world.check(pid, phase_review())
    assert ready['status'] == 'READY_TO_CLOSE' and 'close' in ready['actions']
    binding = ready['ready']['binding']
    assert binding['head'] == head(world) and binding['tasks']['P001-T001']['commit'] == head(world)
    assert ready['ready']['binding_sha256'] == digest(binding) and ready['ready']['stale_reasons'] == []
    check = ready['operations'][-1]
    assert check['status'] == 'READY' and check['result']['validation']['entries'][0]['result']['exit_code'] == 0
    _, closed = world.close(pid)
    assert closed['status'] == 'CLOSED' and closed['actions'] == []
    assert git(world.context.root, 'rev-parse', 'refs/tags/phase-P001-complete') == binding['head'] == head(world)
    close = closed['operations'][-1]
    assert close['status'] == 'CLOSED' and close['result']['tag']['status'] == 'created'
    auth = closed['authorizations'][-1]
    assert auth['kind'] == 'close' and auth['status'] == 'CONSUMED' and auth['actor']['user']
    assert auth['scope'] == {'check_operation_id': check['id'], 'binding_sha256': ready['ready']['binding_sha256'],
                             'tag': 'phase-P001-complete', 'tag_kind': 'lightweight'}
    assert {p: world.context.path(p).read_bytes() for p in docs} == docs
    assert git(world.context.root, 'status', '--porcelain') == ''
    assert world.ports.roles() == ['executor', 'reviewer', 'phase']
    assert kinds(world, pid) == ['phase_created', 'phase_check_queued', 'phase_checked', 'close_authorized',
                                 'phase_close_queued', 'phase_tag_intent', 'phase_closed']
    # A closed phase does not advance: no new tasks, no other closure, no questions.
    with pytest.raises(Conflict, match='closed'):
        world.repository.submit(world.context, 'P001-T009', 'P001', PLAN, VERSIONS, key='late')
    with pytest.raises(Conflict):
        world.close(pid, binding=ready['ready']['binding_sha256'])
    with pytest.raises(Conflict):
        world.phases.raise_question(pid, closed['version'], text='Late question')


def test_phase_runs_are_not_task_runs(world):
    world.accept_task()
    pid = world.create(tag=None)
    job, ready = world.check(pid, phase_review())
    record = world.repository.get_run(job.run_id)
    assert record.status == 'COMPLETED'
    detail = SQLiteManagedViews(world.repository.engine).run(job.run_id)
    assert detail['purpose'] == 'phase_check' and detail['actions'] == []
    for call in (lambda: world.repository.resume(job.run_id, key='r', expected_version=record.version),
                 lambda: world.repository.submit_commit(job.run_id, key='c', expected_version=record.version)):
        with pytest.raises(Conflict):
            call()
    with Session(world.repository.engine) as session:
        attempt = session.scalars(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id == job.run_id)).one()
        request = json.loads(attempt.request_json)
    snapshot = json.loads(request['prompt_snapshot_json'])
    assert request['role'] == 'phase' and snapshot['parts'][0]['version']['name'] == 'close-phase'
    assert snapshot['output_schema']['required'] == ['phase_id', 'verdict', 'summary', 'exit_criteria_results',
                                                     'required_actions', 'blocking_questions']
    assert json.loads(request['permission_snapshot_json'])['payload']['grants'] == []
    _, closed = world.close(pid)
    assert closed['status'] == 'CLOSED' and closed['operations'][-1]['result']['tag'] is None and tags(world) == ''


# --- stale READY ------------------------------------------------------------------------------


def _commit_file(world, path, text):
    world.context.path(path).write_text(text, encoding='utf-8')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-q', '-m', f'external {path}')


@pytest.mark.parametrize('change', ['code_commit', 'dirty_tree', 'docs_commit'])
def test_stale_ready_never_closes_and_requires_new_evidence(world, change):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    if change == 'code_commit':
        _commit_file(world, 'app/other.txt', 'external\n')
    elif change == 'dirty_tree':
        world.context.path('app/main.txt').write_text('uncommitted\n', encoding='utf-8')
    else:
        _commit_file(world, 'docs/STATE.md', '# State changed\n')
    before = head(world)
    _, stale = world.close(pid, binding=ready['ready']['binding_sha256'])
    assert stale['status'] == 'NEEDS_RECONCILIATION' and stale['ready'] is None and 'close' not in stale['actions']
    assert stale['operations'][-1]['status'] == 'STALE' and stale['authorizations'][-1]['status'] == 'INVALIDATED'
    assert tags(world) == '' and head(world) == before
    if change == 'docs_commit':
        assert stale['documents']['drift'] == ['docs/STATE.md']
        _, drift = world.check(pid)  # no agent answer: the drift is detected first
        assert drift['operations'][-1]['status'] == 'NEEDS_RECONCILIATION' and world.ports.roles()[-1] == 'phase'
        assert len(world.ports.roles()) == 3
        world.phases.reconcile(world.context, pid, drift['version'], documents_sha256=drift['documents']['current_sha256'],
                               reason='Adopt reviewed STATE edit')
    if change == 'dirty_tree':
        _, dirty = world.check(pid)
        assert dirty['status'] == 'ACTIVE' and 'Uncommitted' in dirty['operations'][-1]['result']['reasons'][0]
        git(world.context.root, 'checkout', '--', 'app/main.txt')
    _, again = world.check(pid, phase_review())
    assert again['status'] == 'READY_TO_CLOSE' and again['ready']['binding']['head'] == head(world)
    _, closed = world.close(pid)
    assert closed['status'] == 'CLOSED' and git(world.context.root, 'rev-parse', 'phase-P001-complete') == head(world)


def test_stale_binding_or_authority_change_is_refused_before_queueing(world):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    with pytest.raises(Conflict, match='current READY evidence'):
        world.phases.submit_close(world.context, pid, ready['version'], key='x', versions=VERSIONS,
                                  binding_sha256='0' * 64, reason='r', ttl_seconds=60)
    with pytest.raises(Conflict, match='reload'):
        world.phases.submit_close(world.context, pid, ready['version'] - 1, key='y', versions=VERSIONS,
                                  binding_sha256=ready['ready']['binding_sha256'], reason='r', ttl_seconds=60)
    world.phases.raise_question(pid, ready['version'], text='Is the archive wording approved?')
    blocked = world.get(pid)
    assert blocked['status'] == 'BLOCKED' and blocked['ready'] is None
    assert blocked['actions'] == ['reconcile', 'reconcile_task', 'question', 'amend', 'abandon']
    with pytest.raises(Conflict):
        world.phases.submit_close(world.context, pid, blocked['version'], key='z', versions=VERSIONS,
                                  binding_sha256=ready['ready']['binding_sha256'], reason='r', ttl_seconds=60)
    question = blocked['questions'][0]
    world.phases.answer(pid, question['id'], blocked['version'], expected_question_version=1, answer='Yes')
    answered = world.get(pid)
    assert answered['status'] == 'ACTIVE' and answered['ready'] is None and 'close' not in answered['actions']
    assert answered['questions'][0]['answer']['text'] == 'Yes' and answered['questions'][0]['answer']['actor']['uid']
    _, again = world.check(pid, phase_review())
    assert again['ready']['binding']['questions_sha256'] != ready['ready']['binding']['questions_sha256']
    assert len(world.ports.agents.requests) == 4 and world.ports.roles()[-1] == 'phase'
    # The answer reaches the evaluator as evidence.
    assert 'Is the archive wording approved?' in world.ports.agents.requests[-1].prompt


def test_pending_commit_intent_blocks_close(world):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    from my_harness.storage.models import ManagedCommitRow
    with Session(world.repository.engine) as session, session.begin():
        session.scalars(select(ManagedCommitRow)).one().status = 'INTENT'  # synthetic intention not reconciled
    with pytest.raises(Conflict, match='awaits reconciliation'):
        world.phases.submit_close(world.context, pid, ready['version'], key='close', versions=VERSIONS,
                                  binding_sha256=ready['ready']['binding_sha256'], reason='r', ttl_seconds=60)
    assert world.get(pid)['status'] == 'READY_TO_CLOSE'


def test_authority_change_during_check_downgrades_ready(world):
    world.accept_task()
    pid = world.create()

    def raise_during_review(context, request):
        world.phases.raise_question(pid, world.get(pid)['version'], text='Raised while checking')
        return phase_review()
    _, detail = world.check(pid, raise_during_review)
    assert detail['operations'][-1]['status'] == 'NOT_READY' and detail['status'] == 'BLOCKED'
    assert 'changed during the check' in detail['operations'][-1]['result']['reasons'][0]


# --- questions, gates and reconciliation ---------------------------------------------------


def test_pending_questions_block_check_close_and_batch(world):
    pid = world.create(tasks=('P001-T001',))
    version = world.get(pid)['version']
    world.phases.raise_question(pid, version, text='Which archive format?')
    detail = world.get(pid)
    assert detail['status'] == 'BLOCKED' and 'check' not in detail['actions']
    for call in (
            lambda: world.phases.submit_check(world.context, pid, detail['version'], key='c', versions=VERSIONS),
            lambda: world.phases.authorize_batch(pid, detail['version'], tasks=['P001-T001'], ttl_seconds=60, reason='r')):
        with pytest.raises(Conflict, match='questions'):
            call()
    with pytest.raises(Conflict, match='answered'):
        world.phases.answer(pid, detail['questions'][0]['id'], detail['version'], expected_question_version=2, answer='x')
    assert world.ports.agents.requests == [] and world.ports.requested == 0


def test_agent_blocking_questions_are_persisted_and_block_progress(world):
    world.accept_task()
    pid = world.create()
    _, blocked = world.check(pid, phase_review('BLOCKED', questions=['Approve the public API name?']))
    question = blocked['questions'][0]
    assert blocked['status'] == 'BLOCKED' and question['status'] == 'OPEN'
    assert question['source']['kind'] == 'phase_check' and question['source']['attempt_id']
    assert question['source']['run_id'] == blocked['operations'][-1]['run_id']
    with pytest.raises(Conflict, match='questions'):
        world.phases.submit_check(world.context, pid, blocked['version'], key='again', versions=VERSIONS)
    world.phases.answer(pid, question['id'], blocked['version'], expected_question_version=1, answer='Approved')
    _, ready = world.check(pid, phase_review())
    assert ready['status'] == 'READY_TO_CLOSE'


def test_deterministic_gates_do_not_spend_an_agent_call(world):
    pid = world.create(tasks=('P001-T001',))
    _, missing = world.check(pid)
    assert missing['status'] == 'ACTIVE' and missing['operations'][-1]['status'] == 'NOT_READY'
    assert 'no committed acceptance' in missing['operations'][-1]['result']['reasons'][0]
    world.accept_task()
    world.ports.runner.responses.append(CommandResult(1, stderr='synthetic failure'))
    _, failing = world.check(pid)
    assert failing['operations'][-1]['result']['reasons'] == ['Baseline validation failed']
    assert world.ports.roles() == ['executor', 'reviewer']


def test_revise_requires_reconciliation_and_reconcile_is_bound_to_reviewed_documents(world):
    world.accept_task()
    pid = world.create()
    _, revise = world.check(pid, phase_review('REVISE', actions=['Describe the accepted behavior in STATE']))
    assert revise['status'] == 'NEEDS_RECONCILIATION' and revise['operations'][-1]['result']['reasons'] == [
        'Describe the accepted behavior in STATE']
    _commit_file(world, 'docs/STATE.md', '# State\nAccepted behavior described.\n')
    detail = world.get(pid)
    seen = detail['documents']['current_sha256']
    assert detail['documents']['drift'] == ['docs/STATE.md']
    world.context.path('docs/NEXT_STEPS.md').write_text('# Next (unreviewed)\n', encoding='utf-8')
    with pytest.raises(Conflict, match='reviewed'):
        world.phases.reconcile(world.context, pid, detail['version'], documents_sha256=seen, reason='Adopt')
    git(world.context.root, 'checkout', '--', 'docs/NEXT_STEPS.md')
    world.phases.reconcile(world.context, pid, detail['version'], documents_sha256=seen, reason='Adopt reviewed edit')
    reconciled = world.get(pid)
    op = reconciled['operations'][-1]
    assert reconciled['status'] == 'ACTIVE' and reconciled['documents']['drift'] == []
    assert op['kind'] == 'reconcile' and op['result']['changed'] == ['docs/STATE.md']
    assert op['result']['before']['docs/STATE.md'] != op['result']['after']['docs/STATE.md']
    _, ready = world.check(pid, phase_review())
    assert ready['status'] == 'READY_TO_CLOSE'
    # The history of checks is kept complete.
    assert [o['status'] for o in ready['operations']] == ['REVISE', 'RECORDED', 'READY']


@pytest.mark.parametrize('bad', [
    phase_review(exit_criteria_results=[{'criterion': CRITERIA[0], 'passed': True, 'evidence': 'x'}]),
    phase_review(exit_criteria_results=[{'criterion': c, 'passed': False, 'evidence': 'x'} for c in CRITERIA]),
    phase_review(phase_id='P002'),
    phase_review('REVISE', actions=[]),
])
def test_invalid_phase_review_stops_without_retry_or_fallback(world, bad):
    world.accept_task()
    pid = world.create()
    _, failed = world.check(pid, bad)
    assert failed['operations'][-1]['status'] == 'FAILED' and failed['status'] == 'ACTIVE'
    assert world.ports.roles() == ['executor', 'reviewer', 'phase']
    assert failed['operations'][-1]['result']['result'] == bad


# --- separate authorizations -----------------------------------------------------------------


def test_batch_and_close_authorizations_are_distinct_explicit_and_audited(world):
    pid = world.create(tasks=('P001-T001', 'P001-T002'))
    detail = world.get(pid)
    assert 'authorize_batch' in detail['actions'] and 'close' not in detail['actions']
    with pytest.raises(ValueError, match='frozen phase definition'):
        world.phases.authorize_batch(pid, detail['version'], tasks=['P009-T001'], ttl_seconds=60, reason='r')
    auth_id = world.phases.authorize_batch(pid, detail['version'], tasks=['P001-T001', 'P001-T002'],
                                           ttl_seconds=3600, reason='Run both synthetic tasks')
    detail = world.get(pid)
    batch = detail['authorizations'][0]
    assert batch['kind'] == 'batch' and batch['effective_status'] == 'ACTIVE' and batch['actor']['uid']
    assert 'batch_next' in detail['actions'] and 'authorize_batch' not in detail['actions']

    def change(text):
        def call(context, request):
            context.path('app/main.txt').write_text(text, encoding='utf-8')
            return {'result': 'synthetic'}
        return call
    world.script(change('one\n'), review())
    job = world.phases.batch_next(world.context, pid, detail['version'], key='batch-1', versions=VERSIONS,
                                  authorization_id=auth_id, text=PLAN)
    again = world.phases.batch_next(world.context, pid, detail['version'], key='batch-1', versions=VERSIONS,
                                    authorization_id=auth_id, text=PLAN)
    assert again.id == job.id
    with pytest.raises(Conflict, match='unfinished'):
        world.phases.batch_next(world.context, pid, world.get(pid)['version'], key='batch-2', versions=VERSIONS,
                                authorization_id=auth_id, text=PLAN_2)
    world.run()
    record = world.repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY'  # the batch neither confirms commits nor checks the phase
    assert world.get(pid)['status'] == 'ACTIVE' and world.get(pid)['operations'] == []
    with pytest.raises(Conflict, match='without committed acceptance'):
        world.phases.batch_next(world.context, pid, world.get(pid)['version'], key='batch-2', versions=VERSIONS,
                                authorization_id=auth_id, text=PLAN_2)
    world.repository.submit_commit(job.run_id, key='commit-1', expected_version=record.version)
    world.run()
    world.script(change('two\n'), {**review(), 'task_id': 'P001-T002'})
    second = world.phases.batch_next(world.context, pid, world.get(pid)['version'], key='batch-2',
                                     versions=VERSIONS, authorization_id=auth_id, text=PLAN_2)
    world.run()
    record = world.repository.get_run(second.run_id)
    world.repository.submit_commit(second.run_id, key='commit-2', expected_version=record.version)
    world.run()
    detail = world.get(pid)
    assert detail['authorizations'][0]['effective_status'] == 'COMPLETE'
    assert detail['status'] == 'ACTIVE' and 'close' not in detail['actions']  # batch ≠ closure
    with pytest.raises(Conflict, match='READY'):
        world.phases.submit_close(world.context, pid, detail['version'], key='close', versions=VERSIONS,
                                  binding_sha256='0' * 64, reason='Batch does not close', ttl_seconds=60)
    world.phases.revoke(pid, auth_id, detail['version'], reason='Batch finished')
    _, ready = world.check(pid, phase_review())
    _, closed = world.close(pid)
    close = [a for a in closed['authorizations'] if a['kind'] == 'close']
    assert closed['status'] == 'CLOSED' and len(close) == 1 and close[0]['id'] != auth_id
    events = kinds(world, pid)
    assert events.count('batch_task_queued') == 2 and 'batch_revoked' in events and 'close_authorized' in events
    with pytest.raises(Conflict, match='batch'):
        world.phases.revoke(pid, close[0]['id'], closed['version'], reason='Cannot revoke a close')


def test_expired_or_revoked_batch_cannot_advance(world):
    pid = world.create(tasks=('P001-T001',))
    auth_id = world.phases.authorize_batch(pid, 1, tasks=['P001-T001'], ttl_seconds=1, reason='Short batch')
    from datetime import timedelta
    original = world.repository.clock
    world.repository.clock = lambda: original() + timedelta(seconds=5)
    assert world.get(pid)['authorizations'][0]['effective_status'] == 'EXPIRED'
    with pytest.raises(Conflict, match='current batch authorization'):
        world.phases.batch_next(world.context, pid, world.get(pid)['version'], key='late', versions=VERSIONS,
                                authorization_id=auth_id, text=PLAN)
    world.repository.clock = original
    world.phases.revoke(pid, auth_id, world.get(pid)['version'], reason='Stop batch')
    with pytest.raises(Conflict, match='current batch authorization'):
        world.phases.batch_next(world.context, pid, world.get(pid)['version'], key='late-2', versions=VERSIONS,
                                authorization_id=auth_id, text=PLAN)


# --- restart, crashes and concurrency -----------------------------------------------------


def test_restart_preserves_phase_history_and_does_not_repeat_effects(world):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    restarted = World(SQLiteManagedRepository(world.repository.engine), world.context)
    restarted.keys = world.keys
    assert restarted.get(pid) == ready
    assert restarted.worker.run_once() is None  # nothing pending: the check is not repeated
    _, closed = restarted.close(pid)
    assert closed['status'] == 'CLOSED' and restarted.ports.roles() == []
    assert [o['status'] for o in closed['operations']] == ['READY', 'CLOSED']


def test_crash_during_check_requires_explicit_recovery_without_repeating(world):
    world.accept_task()
    pid = world.create()
    world.script(JournalError('Synthetic persistence failure during phase review'))
    job = world.phases.submit_check(world.context, pid, world.get(pid)['version'], key='check', versions=VERSIONS)
    with pytest.raises(JournalError):
        world.run()
    held = world.repository.get_job(job.id)
    assert held.status == 'RECOVERY_REQUIRED' and world.get(pid)['status'] == 'CHECKING'
    assert world.worker.run_once() is None
    record = world.repository.get_run(job.run_id)
    world.repository.confirm_stopped(job.id, owner_token=held.owner_token, expected_version=record.version,
                                     reason='Synthetic worker stopped')
    detail = world.get(pid)
    assert detail['status'] == 'ACTIVE' and detail['operations'][-1]['status'] == 'INTERRUPTED'
    assert world.repository.get_run(job.run_id).history.attempts[-1].result.error.startswith('Interrupted')
    assert world.ports.roles() == ['executor', 'reviewer', 'phase']
    _, ready = world.check(pid, phase_review())
    assert ready['status'] == 'READY_TO_CLOSE' and world.ports.roles().count('phase') == 2


class CrashAfterTag:
    def __init__(self, workspace):
        self.workspace = workspace

    def __getattr__(self, name):
        return getattr(self.workspace, name)

    def tag(self, context, intent):
        self.workspace.tag(context, intent)
        raise CommitUncertain('Synthetic crash after creating the tag')


def test_crash_after_tag_intent_is_reconciled_only_by_an_explicit_new_close(world):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    world.worker.commit_factory = lambda c, v: CrashAfterTag(world.ports.writer(c, v))
    detail = world.get(pid)
    job = world.phases.submit_close(world.context, pid, detail['version'], key='close-1', versions=VERSIONS,
                                    binding_sha256=ready['ready']['binding_sha256'], reason='Close', ttl_seconds=3600)
    with pytest.raises(CommitUncertain):
        world.run()
    assert world.get(pid)['status'] == 'CLOSING' and tags(world) == 'phase-P001-complete'
    held = world.repository.get_job(job.id)
    world.repository.confirm_stopped(job.id, owner_token=held.owner_token,
                                     expected_version=world.repository.get_run(job.run_id).version,
                                     reason='Synthetic close worker stopped')
    detail = world.get(pid)
    interrupted = detail['operations'][-1]
    assert detail['status'] == 'READY_TO_CLOSE' and interrupted['status'] == 'INTERRUPTED'
    assert interrupted['result']['tag_effect'] == 'uncertain' and interrupted['result']['tag_intent']['target'] == head(world)
    assert detail['authorizations'][-1]['status'] == 'INVALIDATED'
    world.worker.commit_factory = world.ports.writer
    _, closed = world.close(pid)
    assert closed['status'] == 'CLOSED' and closed['operations'][-1]['result']['tag']['status'] == 'reconciled'
    assert tags(world) == 'phase-P001-complete'
    assert [a['status'] for a in closed['authorizations']] == ['INVALIDATED', 'CONSUMED']


def test_existing_foreign_tag_is_never_moved(world):
    base = head(world)
    world.accept_task()
    git(world.context.root, 'tag', 'phase-P001-complete', base)
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    _, failed = world.close(pid)
    assert failed['status'] == 'READY_TO_CLOSE' and failed['operations'][-1]['status'] == 'FAILED'
    assert 'never moved' in failed['operations'][-1]['result']['reasons'][0]
    assert git(world.context.root, 'rev-parse', 'refs/tags/phase-P001-complete') == base
    assert failed['authorizations'][-1]['status'] == 'INVALIDATED'


def test_concurrent_close_requests_queue_one_job(world):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    barrier = Barrier(4)

    def attempt(index):
        barrier.wait()
        try:
            return world.phases.submit_close(world.context, pid, ready['version'], key=f'close-{index}',
                                             versions=VERSIONS, binding_sha256=ready['ready']['binding_sha256'],
                                             reason='Concurrent close', ttl_seconds=60)
        except Conflict:
            return None
    with ThreadPoolExecutor(4) as pool:
        results = [r for r in pool.map(attempt, range(4)) if r is not None]
    assert len(results) == 1
    detail = world.get(pid)
    assert detail['status'] == 'CLOSING' and len(detail['authorizations']) == 1
    with pytest.raises(Conflict):  # no commits or questions during the closure
        world.phases.raise_question(pid, detail['version'], text='Too late')
    world.run()
    assert world.get(pid)['status'] == 'CLOSED'


def test_definition_validation_and_one_open_phase_per_checkout(world):
    for bad, match in (({'tag': 'bad..tag'}, 'Tag'), ({'documents': ['../outside.md']}, 'checkout'),
                       ({'tasks': ['A', 'A']}, 'distinct'), ({'exit_criteria': []}, 'distinct'),
                       ({'code': 'bad code'}, 'code')):
        with pytest.raises((ContractError, ValueError), match=match):
            world.create(**bad)
    pid = world.create()
    with pytest.raises(Conflict, match='already exists'):
        world.create()
    with pytest.raises(Conflict, match='open phase'):
        world.create(code='P002')
    assert world.get(pid)['definition']['documents'] == ['docs/STATE.md', 'docs/NEXT_STEPS.md']


def test_validate_phase_result_requires_ready_consistency():
    definition = {'code': 'P001', 'exit_criteria': CRITERIA}
    assert validate_phase_result(definition, phase_review())
    with pytest.raises(ContractError, match='READY'):
        validate_phase_result(definition, phase_review(blocking_questions=['?']))


def test_cli_codex_handles_phase_role_read_only(tmp_path):
    context = make_context(tmp_path)
    config = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    request = AgentRequest('00000000-0000-4000-8000-000000000001', 'phase', Selection('m', 'low', 'r'), 'p', None, '{}')
    argv = argv_for(config, context, request)
    assert argv[argv.index('--sandbox') + 1] == 'read-only'


def test_migration_roundtrip_preserves_runs(migrated_database, world):
    world.accept_task()
    pid = world.create()
    world.check(pid, phase_review())
    run = world.repository.get_run(world.get(pid)['operations'][0]['run_id'])
    command.check(migrated_database[1])
    clear_accounting(migrated_database[0])  # 0028 refuses to drop accounting records; this test is about 0010
    command.downgrade(migrated_database[1], '0009_permissions')
    assert 'managed_phases' not in inspect(world.repository.engine).get_table_names()
    command.upgrade(migrated_database[1], 'head')
    command.check(migrated_database[1])
    assert world.repository.get_run(run.history.id).history == run.history


# --- HTTP ----------------------------------------------------------------------------------


def test_http_phase_flow_with_guards_confirmation_and_server_actions(tmp_path, migrated_database, checkout, monkeypatch):
    from my_harness.services.managed_runtime import CONFIG_ENV
    from test_managed_api import config
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    ports = Ports([edit, review(), phase_review()])
    with client(migrated_database[0], tmp_path, config(checkout, ports)) as http:
        job = http.post('/api/managed/projects/synthetic/runs', json={'task_id': 'P001-T001', 'phase_id': 'P001',
                        'text': PLAN}, headers={'Idempotency-Key': 'start'}).json()
        run = settle(http, job['run_id'])
        http.post(f"/api/managed/runs/{job['run_id']}/actions", json={'action': 'commit', 'expected_version':
                  run['version']}, headers={'Idempotency-Key': 'commit'})
        assert settle(http, job['run_id'])['status'] == 'COMMITTED'
        body = {'code': 'P001', 'objective': 'HTTP phase', 'exit_criteria': CRITERIA, 'tasks': ['P001-T001'],
                'tag': 'phase-P001-complete'}
        denied = http.post('/api/managed/projects/synthetic/phases', json=body, headers={'X-My-Harness': '0'})
        assert denied.status_code == 403
        created = http.post('/api/managed/projects/synthetic/phases', json=body)
        assert created.status_code == 201, created.text
        phase = created.json()
        assert phase['definition']['documents'] == ['docs/STATE.md', 'docs/NEXT_STEPS.md']
        assert phase['project_id'] == 'synthetic' and phase['documents']['drift'] == []
        assert http.get('/api/managed/projects/synthetic/phases').json()[0]['status'] == 'ACTIVE'
        pid = phase['id']
        check = http.post(f'/api/managed/phases/{pid}/actions', json={'action': 'check', 'expected_version':
                          phase['version']}, headers={'Idempotency-Key': 'check'})
        assert check.status_code == 202, check.text
        settle(http, check.json()['run_id'])
        ready = http.get(f'/api/managed/phases/{pid}').json()
        assert ready['status'] == 'READY_TO_CLOSE' and 'close' in ready['actions']
        close = {'action': 'close', 'expected_version': ready['version'], 'reason': 'HTTP close',
                 'binding_sha256': ready['ready']['binding_sha256']}
        assert http.post(f'/api/managed/phases/{pid}/actions', json=close,
                         headers={'Idempotency-Key': 'close'}).status_code == 422  # without confirmation
        stale = http.post(f'/api/managed/phases/{pid}/actions', json={**close, 'confirmed': True,
                          'binding_sha256': 'f' * 64}, headers={'Idempotency-Key': 'close-stale'})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'conflict'
        closing = http.post(f'/api/managed/phases/{pid}/actions', json={**close, 'confirmed': True},
                            headers={'Idempotency-Key': 'close'})
        assert closing.status_code == 202, closing.text
        settle(http, closing.json()['run_id'])
        closed = http.get(f'/api/managed/phases/{pid}').json()
        assert closed['status'] == 'CLOSED' and closed['actions'] == []
        events = http.get(f'/api/managed/phases/{pid}/events', params={'limit': 3}).json()
        assert [e['sequence'] for e in events['items']] == [1, 2, 3] and events['has_more']
        run = http.get(f"/api/managed/runs/{closing.json()['run_id']}").json()
        assert run['purpose'] == 'phase_close' and run['actions'] == []
    assert ports.roles() == ['executor', 'reviewer', 'phase']
    assert git(checkout.root, 'rev-parse', 'phase-P001-complete') == git(checkout.root, 'rev-parse', 'HEAD')


def test_http_without_git_writer_reads_but_does_not_queue_phase_operations(tmp_path, migrated_database, checkout,
                                                                         monkeypatch):
    from my_harness.services.managed_runtime import CONFIG_ENV
    from test_managed_api import config
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    with client(migrated_database[0], tmp_path, config(checkout, Ports([]), commit=False, supervisor=False)) as http:
        phase = http.post('/api/managed/projects/synthetic/phases', json={
            'code': 'P001', 'objective': 'o', 'exit_criteria': ['c'], 'tasks': [], 'documents': ['docs/STATE.md'],
            'tag': None}).json()
        assert 'check' not in phase['actions'] and 'reconcile' in phase['actions']
        assert 'abandon' not in phase['actions']
        assert 'reconcile_task' not in phase['actions']
        refused_task = http.post(f"/api/managed/phases/{phase['id']}/reconcile-task", json={
            'expected_version': phase['version']}, headers={'Idempotency-Key': 'r'})
        assert refused_task.status_code == 409 and refused_task.json()['detail']['code'] == 'commit_writer_unavailable'
        refused = http.post(f"/api/managed/phases/{phase['id']}/actions", json={'action': 'check', 'expected_version':
                            phase['version']}, headers={'Idempotency-Key': 'k'})
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'commit_writer_unavailable'
        Path(checkout.root / 'docs/STATE.md').write_text('# Changed\n', encoding='utf-8')
        drift = http.get(f"/api/managed/phases/{phase['id']}").json()
        assert drift['documents']['drift'] == ['docs/STATE.md']
        adopted = http.post(f"/api/managed/phases/{phase['id']}/reconcile", json={
            'expected_version': drift['version'], 'documents_sha256': drift['documents']['current_sha256'],
            'reason': 'Adopt', 'confirmed': True})
        assert adopted.status_code == 200 and adopted.json()['documents']['drift'] == []
