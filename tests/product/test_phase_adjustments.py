"""H3.4 (D033): H0/H1 guard, unattended batch with commits, amendment/abandonment, configurable tags
and reconciliation with an agent. Temporary Git/SQLite and fake agents; no providers or network."""
from datetime import timedelta
from dataclasses import replace
import json

from alembic import command
from session_client import TestClient
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from my_harness.api.app import create_app
from my_harness.core.engine.commit import CommitUncertain
from my_harness.core.engine.journal import JournalError
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.managed import Conflict
from my_harness.storage.models import ManagedAttemptRow, PhaseDefinitionRow
from test_managed import repository  # noqa: F401  (fixture)
from test_managed_api import IDENTITY, LOCAL, PLAN, VERSIONS, Ports, client, git, review, settle
from test_phases import (  # noqa: F401  (fixtures)
    CRITERIA, PLAN_2, CrashAfterTag, checkout, head, kinds, phase_review, tags, world,
)

PLAN_BOTH = PLAN + PLAN_2[PLAN_2.index('## P001-T002'):]


def change(text):
    def call(context, request):
        context.path('app/main.txt').write_text(text, encoding='utf-8')
        return {'result': 'synthetic'}
    return call


def accept(task):
    return {**review(), 'task_id': task}


def drain(world, limit=20):
    """Runs the supervisor until it claims nothing; the batch driver runs on every round."""
    for count in range(limit):
        if world.worker.run_once() is None:
            return count
    raise AssertionError('The supervisor did not settle')


def chain(world, pid, tasks=('P001-T001', 'P001-T002'), ttl=3600, text=PLAN_BOTH):
    return world.phases.authorize_batch(pid, world.get(pid)['version'], tasks=list(tasks), ttl_seconds=ttl,
                                        reason='Unattended synthetic batch', chain_commits=True, text=text,
                                        context=world.context, versions=VERSIONS)


def batch(detail, auth_id):
    return next(a for a in detail['authorizations'] if a['id'] == auth_id)


# --- H0/H1 guard -----------------------------------------------------------------------------------


def test_h0_h1_mutations_reject_foreign_host_origin_and_missing_header(migrated_database, tmp_path):
    url, _ = migrated_database
    body = {'title': 'Simulación sintética'}
    with TestClient(create_app(url, tmp_path), base_url="http://testserver") as foreign:  # Host: testserver
        rejected = foreign.post('/api/simulations', json=body, headers={'X-My-Harness': '1'})
        assert rejected.status_code == 403 and rejected.json()['detail']['code'] == 'host_rejected'
        assert foreign.put('/api/legacy/projects/x/observation', json={'enabled': True},
                           headers={'X-My-Harness': '1'}).json()['detail']['code'] == 'host_rejected'
        assert foreign.get('/api/simulations').status_code == 403  # H5.6 covers reads too
    with TestClient(create_app(url, tmp_path), base_url=LOCAL) as local:
        missing = local.post('/api/simulations', json=body)
        assert missing.status_code == 403 and missing.json()['detail']['code'] == 'csrf_header_required'
        cross = local.post('/api/simulations', json=body, headers={'X-My-Harness': '1',
                                                                   'Origin': 'https://attacker.example'})
        assert cross.status_code == 403 and cross.json()['detail']['code'] == 'origin_rejected'
        put = local.put('/api/legacy/projects/x/observation', json={'enabled': True})
        assert put.status_code == 403 and put.json()['detail']['code'] == 'csrf_header_required'
        # The guard precedes the lookup: with the header, the unknown project gives 404.
        assert local.put('/api/legacy/projects/x/observation', json={'enabled': True},
                         headers={'X-My-Harness': '1', 'Origin': LOCAL}).status_code == 404
        assert local.get('/api/simulations').json() == []  # no rejection created rows
        created = local.post('/api/simulations', json=body, headers={'X-My-Harness': '1',
                                                                     'Origin': LOCAL})
        assert created.status_code == 201


# --- unattended batch -------------------------------------------------------------------------------


def test_unattended_batch_chains_task_commit_and_next_task_without_checking_or_closing(world):
    pid = world.create(tasks=('P001-T001', 'P001-T002'))
    auth_id = chain(world, pid)
    detail = world.get(pid)
    view = batch(detail, auth_id)
    assert view['scope']['chain_commits'] is True and 'text' not in view['scope']
    assert 'batch_next' not in detail['actions'] and 'authorize_batch' not in detail['actions']
    with pytest.raises(Conflict, match='supervisor'):
        world.phases.batch_next(world.context, pid, detail['version'], key='manual', versions=VERSIONS,
                                authorization_id=auth_id, text=PLAN)
    world.script(change('one\n'), accept('P001-T001'), change('two\n'), accept('P001-T002'))
    assert drain(world) == 4  # task → commit → task → commit, without intervention
    detail = world.get(pid)
    assert all(item is not None for item in detail['tasks'].values())
    assert detail['tasks']['P001-T002']['commit'] == head(world)
    assert git(world.context.root, 'rev-parse', detail['tasks']['P001-T002']['commit'] + '^') == \
        detail['tasks']['P001-T001']['commit']
    assert batch(detail, auth_id)['status'] == 'COMPLETED'
    assert detail['status'] == 'ACTIVE' and detail['operations'] == [] and tags(world) == ''  # never checks/closes
    assert world.ports.roles() == ['executor', 'reviewer', 'executor', 'reviewer']
    events = kinds(world, pid)
    assert events.count('batch_task_queued') == 2 and events.count('batch_commit_queued') == 2
    assert events[-1] == 'batch_completed'
    assert drain(world) == 0  # nothing else to do: the batch finished


def test_unattended_batch_stops_at_the_first_blocked_task(world):
    pid = world.create(tasks=('P001-T001', 'P001-T002'))
    auth_id = chain(world, pid)
    world.script(change('one\n'), {**accept('P001-T001'), 'verdict': 'BLOCKED',
                                   'blocking_questions': ['Which wording?']})
    assert drain(world) == 1
    detail = world.get(pid)
    stopped = batch(detail, auth_id)
    assert stopped['status'] == 'STOPPED' and 'P001-T001' in stopped['closed']['reason']
    assert detail['tasks'] == {'P001-T001': None, 'P001-T002': None}
    assert world.ports.roles() == ['executor', 'reviewer']  # the second task never starts
    assert 'authorize_batch' in detail['actions']  # resuming requires another explicit authorization


@pytest.mark.parametrize('interruption', ['question', 'expiry', 'revocation', 'invalidated_evidence'])
def test_unattended_batch_stops_on_question_expiry_revocation_or_invalidated_evidence(world, interruption):
    pid = world.create(tasks=('P001-T001', 'P001-T002'))
    auth_id = chain(world, pid, ttl=60)
    world.script(change('one\n'), accept('P001-T001'))
    world.run()  # first task up to ACCEPTANCE_READY; the commit is not queued yet
    before = head(world)
    if interruption == 'question':
        world.phases.raise_question(pid, world.get(pid)['version'], text='Product decision needed')
    elif interruption == 'expiry':
        original = world.repository.clock
        world.repository.clock = lambda: original() + timedelta(seconds=120)
    elif interruption == 'revocation':
        world.phases.revoke(pid, auth_id, world.get(pid)['version'], reason='Stop the batch')
    else:
        world.context.path('app/main.txt').write_text('edited after review\n', encoding='utf-8')
    drain(world)
    detail = world.get(pid)
    expected = {'question': 'STOPPED', 'expiry': 'EXPIRED', 'revocation': 'REVOKED',
                'invalidated_evidence': 'STOPPED'}[interruption]
    assert batch(detail, auth_id)['status'] == expected
    assert head(world) == before and detail['tasks']['P001-T001'] is None  # no commit after the stop
    assert world.ports.roles() == ['executor', 'reviewer']
    if interruption == 'invalidated_evidence':
        assert 'did not complete' in batch(detail, auth_id)['closed']['reason']
        assert 'batch_commit_queued' in kinds(world, pid)


def test_crash_in_unattended_batch_requires_explicit_recovery_and_repeats_nothing(world):
    pid = world.create(tasks=('P001-T001', 'P001-T002'))
    auth_id = chain(world, pid)
    world.script(JournalError('Synthetic persistence failure during execution'))
    with pytest.raises(JournalError):
        world.run()
    assert drain(world) == 0
    detail = world.get(pid)
    assert batch(detail, auth_id)['status'] == 'STOPPED' and 'recovery' in batch(detail, auth_id)['closed']['reason']
    with Session(world.repository.engine) as session:
        attempts = session.scalars(select(ManagedAttemptRow)).all()
        assert len(attempts) == 1
    from my_harness.storage.models import ManagedJobRow
    with Session(world.repository.engine) as session:
        held = session.scalars(select(ManagedJobRow).where(ManagedJobRow.status == 'RECOVERY_REQUIRED')).one()
        job_id, token, run_id = held.id, held.owner_token, held.run_id
    world.repository.confirm_stopped(job_id, owner_token=token, reason='Synthetic worker stopped',
                                     expected_version=world.repository.get_run(run_id).version)
    assert drain(world) == 0 and world.ports.roles() == ['executor']  # no relaunching or chaining


def test_unattended_batch_does_not_adopt_runs_started_outside_it(world):
    pid = world.create(tasks=('P001-T001',))
    world.script(change('manual\n'), accept('P001-T001'))
    world.repository.submit(world.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='manual')
    world.run()
    auth_id = chain(world, pid, tasks=('P001-T001',))
    drain(world)
    stopped = batch(world.get(pid), auth_id)
    assert stopped['status'] == 'STOPPED' and 'outside this batch' in stopped['closed']['reason']
    assert world.get(pid)['tasks']['P001-T001'] is None


# --- amendment and abandonment --------------------------------------------------------------------


def test_amendment_keeps_previous_definition_and_invalidates_ready_and_batches(world):
    pid = world.create(tasks=('P001-T001', 'P001-T002'))
    auth_id = world.phases.authorize_batch(pid, world.get(pid)['version'], tasks=['P001-T001'], ttl_seconds=60,
                                           reason='Manual batch')
    first = world.get(pid)
    data = {key: first['definition'][key] for key in ('objective', 'exit_criteria', 'documents', 'tag')}
    world.phases.amend(world.context, pid, first['version'], data={**data, 'tasks': ['P001-T001']},
                       reason='Second task moves to another phase')
    amended = world.get(pid)
    assert amended['definition_number'] == 2 and amended['definition']['tasks'] == ['P001-T001']
    assert [d['number'] for d in amended['definitions']] == [1, 2]
    assert amended['definitions'][0]['definition'] == first['definition']  # the previous one stays intact
    assert amended['definitions'][0]['origin'] == 'created' and amended['definitions'][1]['origin'] == 'amended'
    assert amended['definitions'][1]['reason'] == 'Second task moves to another phase'
    assert batch(amended, auth_id)['status'] == 'INVALIDATED'
    world.accept_task()
    _, ready = world.check(pid, phase_review())
    assert ready['status'] == 'READY_TO_CLOSE'
    world.context.path('README.md').write_text('# Synthetic readme\n', encoding='utf-8')
    git(world.context.root, 'add', '-A')
    git(world.context.root, 'commit', '-q', '-m', 'readme')
    with pytest.raises(ValueError, match='code'):
        world.phases.amend(world.context, pid, ready['version'], data={**data, 'code': 'P009', 'tasks': []},
                           reason='Rename')
    with pytest.raises(Conflict, match='does not change'):
        world.phases.amend(world.context, pid, ready['version'], data={**data, 'tasks': ['P001-T001']}, reason='Same')
    documents = data['documents'] + ['README.md']
    world.phases.amend(world.context, pid, ready['version'],
                       data={**data, 'tasks': ['P001-T001'], 'documents': documents}, reason='Track the readme')
    after = world.get(pid)
    assert after['status'] == 'ACTIVE' and after['ready'] is None and 'close' not in after['actions']
    assert after['documents']['baseline']['README.md'] == after['documents']['current']['README.md']
    amend_op = after['operations'][-1]
    assert amend_op['kind'] == 'amend' and amend_op['result']['ready_invalidated'] is True
    assert amend_op['result']['added_documents'] == ['README.md']
    with pytest.raises(Conflict):  # the previous READY does not close
        world.phases.submit_close(world.context, pid, after['version'], key='late', versions=VERSIONS,
                                  binding_sha256=ready['ready']['binding_sha256'], reason='r', ttl_seconds=60)
    _, again = world.check(pid, phase_review())
    assert again['ready']['binding']['definition_sha256'] == after['definition_sha256']
    assert kinds(world, pid).count('definition_amended') == 2


def test_abandonment_is_terminal_audited_and_frees_the_checkout(world):
    pid = world.create(tasks=('P001-T001',))
    auth_id = world.phases.authorize_batch(pid, world.get(pid)['version'], tasks=['P001-T001'], ttl_seconds=60,
                                           reason='Manual batch')
    world.phases.raise_question(pid, world.get(pid)['version'], text='Still relevant?')
    world.abandon(pid, 'Scope dropped by the user')
    detail = world.get(pid)
    assert detail['status'] == 'ABANDONED' and detail['actions'] == []
    op = detail['operations'][-1]
    assert op['kind'] == 'close' and op['request']['terminal'] == 'ABANDONED'
    assert next(a for a in detail['authorizations'] if a['id'] == auth_id)['status'] == 'INVALIDATED'
    assert len(detail['questions']) == 1 and op['result']['archive'] == 'docs/archive/phase-001'
    for call in (
            lambda: world.repository.submit(world.context, 'P001-T001', 'P001', PLAN, VERSIONS, key='late'),
            lambda: world.phases.submit_check(world.context, pid, detail['version'], key='c', versions=VERSIONS),
            lambda: world.phases.raise_question(pid, detail['version'], text='Late'),
            lambda: world.abandon(pid, 'Again'),
            lambda: world.phases.amend(world.context, pid, detail['version'], data={
                'objective': 'x', 'exit_criteria': ['c'], 'tasks': [], 'documents': ['docs/STATE.md'], 'tag': None},
                reason='Late amendment')):
        with pytest.raises(Conflict):
            call()
    assert world.create(code='P002')  # an abandoned phase does not occupy the checkout
    assert kinds(world, pid)[-1] == 'phase_abandoned'


# --- configurable tags ----------------------------------------------------------------------------


def close_annotated(world, pid, key):
    detail = world.get(pid)
    job = world.phases.submit_close(world.context, pid, detail['version'], key=key, versions=VERSIONS,
                                    binding_sha256=detail['ready']['binding_sha256'], reason='Annotated close',
                                    ttl_seconds=3600, tag_kind='annotated')
    return job


def test_annotated_tag_fixes_message_identity_and_date_in_the_intent(world):
    world.accept_task()
    pid = world.create()
    _, ready = world.check(pid, phase_review())
    close_annotated(world, pid, 'close')
    world.run()
    closed = world.get(pid)
    tag = closed['operations'][-1]['result']['tag']
    assert closed['status'] == 'CLOSED' and tag['status'] == 'created'
    ref = 'refs/tags/phase-P001-complete'
    assert git(world.context.root, 'cat-file', '-t', ref) == 'tag'
    assert git(world.context.root, 'rev-parse', ref) == tag['object']
    assert git(world.context.root, 'rev-parse', ref + '^{commit}') == ready['ready']['binding']['head']
    body = git(world.context.root, 'cat-file', '-p', ref)
    assert f'tagger {IDENTITY.name} <{IDENTITY.email}>' in body
    assert f"Harness-Ready-Binding: {ready['ready']['binding_sha256']}" in body
    with Session(world.repository.engine) as session:
        from my_harness.storage.models import PhaseOperationRow
        op = session.get(PhaseOperationRow, closed['operations'][-1]['id'])
        intent = op.request['tag_intent']
    assert intent['kind'] == 'annotated' and intent['object'] == tag['object']
    assert type(intent['tagged_at']) is int and abs(world.repository.clock().timestamp() - intent['tagged_at']) < 600
    assert world.ports.writer(world.context, VERSIONS).seal_tag(world.context, intent) == tag['object']  # deterministic
    assert closed['authorizations'][-1]['scope']['tag_kind'] == 'annotated'


def test_annotated_tag_crash_is_reconciled_with_the_same_object(world):
    world.accept_task()
    pid = world.create()
    world.check(pid, phase_review())
    world.worker.commit_factory = lambda c, v: CrashAfterTag(world.ports.writer(c, v))
    job = close_annotated(world, pid, 'close-1')
    with pytest.raises(CommitUncertain):
        world.run()
    created = git(world.context.root, 'rev-parse', 'refs/tags/phase-P001-complete')
    held = world.repository.get_job(job.id)
    world.repository.confirm_stopped(job.id, owner_token=held.owner_token, reason='Synthetic close worker stopped',
                                     expected_version=world.repository.get_run(job.run_id).version)
    world.worker.commit_factory = world.ports.writer
    original = world.repository.clock
    world.repository.clock = lambda: original() + timedelta(hours=1)  # another date: the intention is reused
    close_annotated(world, pid, 'close-2')
    world.run()
    closed = world.get(pid)
    assert closed['status'] == 'CLOSED' and closed['operations'][-1]['result']['tag']['status'] == 'reconciled'
    assert git(world.context.root, 'rev-parse', 'refs/tags/phase-P001-complete') == created
    assert [a['status'] for a in closed['authorizations']] == ['INVALIDATED', 'CONSUMED']


def test_existing_lightweight_tag_is_never_replaced_by_an_annotated_one(world):
    world.accept_task()
    git(world.context.root, 'tag', 'phase-P001-complete', head(world))
    pid = world.create()
    world.check(pid, phase_review())
    close_annotated(world, pid, 'close')
    world.run()
    failed = world.get(pid)
    assert failed['status'] == 'READY_TO_CLOSE' and failed['operations'][-1]['status'] == 'FAILED'
    assert 'never moved' in failed['operations'][-1]['result']['reasons'][0]
    assert git(world.context.root, 'cat-file', '-t', 'refs/tags/phase-P001-complete') == 'commit'


# --- reconciliation with an agent ------------------------------------------------------------------


def test_agent_reconciliation_is_a_reviewed_committed_task_limited_to_phase_documents(world):
    world.accept_task()
    pid = world.create()
    _, revise = world.check(pid, phase_review('REVISE', actions=['Describe the accepted behavior in STATE']))
    assert 'reconcile_task' in revise['actions']

    def document(context, request):
        context.path('docs/STATE.md').write_text('# State\nAccepted behavior described.\n', encoding='utf-8')
        return {'result': 'synthetic'}
    world.script(document, accept('P001-RECONCILE-1'))
    job = world.phases.submit_reconcile_task(world.context, pid, revise['version'], key='reconcile',
                                             versions=VERSIONS)
    again = world.phases.submit_reconcile_task(world.context, pid, revise['version'], key='reconcile',
                                               versions=VERSIONS)
    assert again.id == job.id
    world.run()
    record = world.repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY' and world.ports.roles()[-2:] == ['executor', 'reviewer']
    assert 'planner' not in world.ports.roles()
    contract = json.loads(record.history.task_json)
    assert contract['allowed_paths'] == ['docs/STATE.md', 'docs/NEXT_STEPS.md']
    assert contract['prompt_template']['name'] == 'reconcile-phase'
    assert any('Describe the accepted behavior in STATE' in c for c in contract['acceptance_criteria'])
    executor = world.ports.agents.requests[-2]
    assert 'Edit only the phase documents' in executor.prompt and 'Describe the accepted behavior' in executor.prompt
    detail = world.get(pid)
    assert detail['operations'][-1]['kind'] == 'reconcile_task' and detail['operations'][-1]['status'] == 'ACCEPTANCE_READY'
    assert 'reconcile_task' not in detail['actions']
    with pytest.raises(Conflict, match='committed before adopting'):
        world.phases.reconcile(world.context, pid, detail['version'],
                               documents_sha256=detail['documents']['current_sha256'], reason='Too early')
    world.repository.submit_commit(job.run_id, key='commit-reconcile', expected_version=record.version)
    world.run()
    committed = world.get(pid)
    assert git(world.context.root, 'show', '--name-only', '--format=', 'HEAD') == 'docs/STATE.md'
    world.phases.reconcile(world.context, pid, committed['version'],
                           documents_sha256=committed['documents']['current_sha256'], reason='Adopt reviewed commit')
    adopted = world.get(pid)
    task_op = next(o for o in adopted['operations'] if o['kind'] == 'reconcile_task')
    adoption = adopted['operations'][-1]
    assert task_op['status'] == 'ADOPTED' and task_op['result']['commit'] == head(world)
    assert adoption['result']['source']['run_id'] == job.run_id and adoption['result']['changed'] == ['docs/STATE.md']
    assert adopted['status'] == 'ACTIVE' and adopted['documents']['drift'] == []
    _, ready = world.check(pid, phase_review())
    assert ready['status'] == 'READY_TO_CLOSE'


def test_agent_reconciliation_writing_outside_documents_is_never_eligible(world):
    world.accept_task()
    pid = world.create()
    _, revise = world.check(pid, phase_review('REVISE'))

    def outside(context, request):
        context.path('docs/STATE.md').write_text('# State\nUpdated.\n', encoding='utf-8')
        context.path('app/main.txt').write_text('sneaky code change\n', encoding='utf-8')
        return {'result': 'synthetic'}
    world.script(outside, accept('P001-RECONCILE-1'))
    job = world.phases.submit_reconcile_task(world.context, pid, revise['version'], key='reconcile',
                                             versions=VERSIONS)
    world.run()
    record = world.repository.get_run(job.run_id)
    assert record.status == 'STOPPED' and record.history.acceptance is not None
    assert not record.history.acceptance.eligible
    before = head(world)
    with pytest.raises(Conflict, match='eligible'):
        world.repository.submit_commit(job.run_id, key='commit', expected_version=record.version)
    assert head(world) == before
    assert 'reconcile_task' in world.get(pid)['actions']  # the failed attempt does not block another explicit one


# --- migration and HTTP -----------------------------------------------------------------------------


def test_migration_0011_backfills_definitions_and_refuses_lossy_downgrade(migrated_database, world):
    pid = world.create()
    with world.repository.engine.begin() as connection:
        connection.execute(text('DELETE FROM phase_definitions'))
    command.downgrade(migrated_database[1], '0010_phases')
    command.upgrade(migrated_database[1], 'head')
    command.check(migrated_database[1])
    with Session(world.repository.engine) as session:
        row = session.scalars(select(PhaseDefinitionRow).where(PhaseDefinitionRow.phase_id == pid)).one()
        assert row.origin == 'migrated' and row.reason is None and row.actor is None and row.number == 1
    world.abandon(pid, 'Abandon before downgrade')
    with pytest.raises(RuntimeError, match='Abandoned'):
        command.downgrade(migrated_database[1], '0010_phases')


def test_http_h34_phase_actions_with_annotated_project_and_guards(tmp_path, migrated_database, checkout, monkeypatch):
    from my_harness.services.managed_runtime import CONFIG_ENV
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    checkout = replace(checkout, documents='v2')
    # P008-T007: with the unified layout every attempt requires AGENTS.md.
    checkout.path('AGENTS.md').write_text('# Sintético\n\nInstrucciones sintéticas.\n', encoding='utf-8')
    git(checkout.root, 'add', 'AGENTS.md')
    git(checkout.root, 'commit', '-q', '-m', 'docs: instrucciones sintéticas')
    ports = Ports([change('one\n'), accept('P001-T001'), phase_review()])
    managed = ManagedConfig((ManagedProject('synthetic', checkout, VERSIONS, tag_kind='annotated'),),
                            ports_factory=ports, commit_factory=ports.writer, supervisor=True, poll_seconds=0.02)
    with client(migrated_database[0], tmp_path, managed) as http:
        assert http.get('/api/managed/projects').json()[0]['tag_kind'] == 'annotated'
        phase = http.post('/api/managed/projects/synthetic/phases', json={
            'code': 'P001', 'objective': 'HTTP phase', 'exit_criteria': CRITERIA, 'tasks': ['P001-T001'],
            'tag': 'phase-P001-complete'}).json()
        pid = phase['id']
        assert phase['tag_kind'] == 'annotated' and phase['definition_number'] == 1
        assert {'amend', 'abandon', 'reconcile_task', 'authorize_batch'} <= set(phase['actions'])
        body = {'expected_version': phase['version'], 'tasks': ['P001-T001'], 'ttl_seconds': 600,
                'reason': 'HTTP unattended batch', 'confirmed': True, 'chain_commits': True}
        assert http.post(f'/api/managed/phases/{pid}/authorizations', json=body).status_code == 422  # no plan
        assert http.post(f'/api/managed/phases/{pid}/authorizations', json={**body, 'text': PLAN},
                         headers={'X-My-Harness': '0'}).status_code == 403
        authorized = http.post(f'/api/managed/phases/{pid}/authorizations', json={**body, 'text': PLAN})
        assert authorized.status_code == 201, authorized.text
        auth = authorized.json()['authorizations'][0]
        assert auth['scope']['chain_commits'] and 'text' not in auth['scope'] and 'context_json' not in auth['scope']
        import time
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = http.get(f'/api/managed/phases/{pid}').json()
            if current['authorizations'][0]['status'] != 'ACTIVE':
                break
            time.sleep(0.05)
        assert current['authorizations'][0]['status'] == 'COMPLETED' and current['tasks']['P001-T001']
        check = http.post(f'/api/managed/phases/{pid}/actions', json={'action': 'check', 'expected_version':
                          current['version']}, headers={'Idempotency-Key': 'check'})
        settle(http, check.json()['run_id'])
        ready = http.get(f'/api/managed/phases/{pid}').json()
        assert ready['status'] == 'READY_TO_CLOSE'
        amend = {'expected_version': ready['version'], 'objective': 'HTTP phase (amended)', 'exit_criteria': CRITERIA,
                 'tasks': ['P001-T001'], 'documents': ['docs/STATE.md', 'docs/NEXT_STEPS.md'],
                 'tag': 'phase-P001-complete', 'reason': 'Clarify objective'}
        assert http.post(f'/api/managed/phases/{pid}/amend', json=amend).status_code == 422  # without confirmation
        amended = http.post(f'/api/managed/phases/{pid}/amend', json={**amend, 'confirmed': True})
        assert amended.status_code == 200, amended.text
        assert amended.json()['status'] == 'ACTIVE' and amended.json()['ready'] is None
        assert [d['origin'] for d in amended.json()['definitions']] == ['created', 'amended']
        task = http.post(f'/api/managed/phases/{pid}/reconcile-task', json={
            'expected_version': amended.json()['version']}, headers={'Idempotency-Key': 'reconcile'})
        assert task.status_code == 202, task.text
        assert settle(http, task.json()['run_id'])['status'] == 'STOPPED'  # no scripted answer: it stops
        current = http.get(f'/api/managed/phases/{pid}').json()
        abandoned = http.post(f'/api/managed/phases/{pid}/abandon', json={
            'expected_version': current['version'], 'reason': 'HTTP abandonment', 'confirmed': True},
            headers={'Idempotency-Key': 'abandon'})
        assert abandoned.status_code == 200, abandoned.text
        import time
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            final = http.get(f'/api/managed/phases/{pid}').json()
            if final['status'] != 'CLOSING':
                break
            time.sleep(0.05)
        assert final['status'] == 'ABANDONED' and final['actions'] == []
