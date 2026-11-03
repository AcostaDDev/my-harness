"""Owner-adopted replacement budgets, preserved through new task identity and a repository restart."""
from dataclasses import replace

import pytest
from sqlalchemy.orm import Session
from alembic import command

from test_git import (repo, repository, make_context, supervisor, load_context, edit, review,
                      TASK, PHASE, PLAN, VERSIONS)
from test_knowledge_documents import (world, prepare_export, KnowledgeDelivery, IDENTITY, OWNER, run)
from my_harness.storage.managed import SQLiteManagedRepository
from my_harness.storage.task_lineage import budget


def adopt_replacement(engine, root, project, knowledge):
    revision = knowledge.revision(project)
    old = revision.item('task', 'P001-T001').item_id
    new = revision.item('task', 'P001-T002').item_id
    draft = run(engine, root, 'knowledge.draft.open', {'expected_revision_id': revision.id}, 'replacement-draft')
    applied = run(engine, root, 'knowledge.draft.apply', {
        'draft_id': draft['draft_id'], 'expected_draft_sha256': draft['draft_sha256'],
        'changes': [{'op': 'link', 'kind': 'replaces', 'source_item_id': new, 'target_item_id': old}]},
        'replacement-link')
    shown = run(engine, root, 'knowledge.adoption.preview', {'draft_id': draft['draft_id']})
    adopted = run(engine, root, 'knowledge.adopt', {
        'draft_id': draft['draft_id'], 'expected_revision_id': revision.id,
        'preview_sha256': shown['preview_sha256'], 'reason': 'Owner adopts the replacement lineage.'},
        'replacement-adopt')
    assert applied['draft_sha256'] and adopted['origin'] == 'owner_confirmed'
    return old, new


def revise(task_id=TASK):
    return {**review('REVISE'), 'task_id': task_id, 'next_prompt': 'Correct within scope.',
            'executor_selection': {'model': 'synthetic-executor', 'effort': 'medium', 'reason': 'Synthetic'}}


def test_replacement_shares_consumed_budget_across_sessions_and_preserves_unrelated_tasks(
        repo, repository, migrated_database):
    engine, knowledge, project, _ = world(migrated_database[0], repo)
    adopt_replacement(engine, repo, project, knowledge)
    export = prepare_export(engine, repo, project)
    KnowledgeDelivery(engine, repo, project).execute(export['record_id'], export['preview_sha256'], IDENTITY)
    context = make_context(repo)
    context = replace(context, policy=replace(context.policy, max_revision_cycles=2))
    first = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key='source-task')
    worker, source_agents = supervisor(repository, load_context(repository.get_run(first.run_id)),
        [edit(), revise(), edit({'app/main.txt': 'partly corrected\n'}), review('BLOCKED')])
    assert worker.run_once().status == 'DONE'
    assert repository.get_run(first.run_id).revisions == 1
    assert len(source_agents.requests) == 4

    restarted = SQLiteManagedRepository(engine, clock=repository.clock)
    # An increased new policy cannot replenish the inherited budget.
    broader = replace(context, policy=replace(context.policy, max_revision_cycles=9))
    second = restarted.submit(broader, 'P001-T002', PHASE, PLAN.replace(TASK, 'P001-T002'),
                              VERSIONS, key='replacement-task')
    with Session(engine) as session:
        state = budget(session, str(repo), 'P001-T002', 9)
        assert state == {'tasks': ['P001-T001', 'P001-T002'], 'executions': 2, 'revision_limit': 2}
    def continue_partial(context, request):
        assert (context.root / 'app/main.txt').read_text() == 'partly corrected\n'
        return edit({'app/main.txt': 'partly corrected\nreplacement completion\n'})(context, request)

    worker, replacement_agents = supervisor(restarted, load_context(restarted.get_run(second.run_id)),
        [continue_partial, revise('P001-T002')])
    assert worker.run_once().status == 'DONE'
    assert restarted.get_run(second.run_id).history.status == 'revision_limit'
    assert len(replacement_agents.requests) == 2
    assert (repo / 'app/main.txt').read_text() == 'partly corrected\nreplacement completion\n'
    again = SQLiteManagedRepository(engine, clock=repository.clock)
    again.resume(second.run_id, key='exhausted-retry', expected_version=again.get_run(second.run_id).version,
                 retry_executor=True)
    worker, exhausted_agents = supervisor(again, load_context(again.get_run(second.run_id)), [])
    assert worker.run_once().status == 'DONE'
    assert exhausted_agents.requests == []

    unrelated = again.submit(context, 'P001-T003', PHASE, PLAN.replace(TASK, 'P001-T003'),
                             VERSIONS, key='independent-task')
    worker, independent_agents = supervisor(again, load_context(again.get_run(unrelated.run_id)),
        [edit(), {**review(), 'task_id': 'P001-T003'}])
    assert worker.run_once().status == 'DONE'
    assert len(independent_agents.requests) == 2
    assert again.get_run(unrelated.run_id).history.status == 'acceptance_ready'


def test_adopted_replacement_is_acyclic_persistent_and_migration_preserves_knowledge(
        repo, repository, migrated_database):
    from my_harness.core.engine.contracts import ContractError
    engine, knowledge, project, _ = world(migrated_database[0], repo)
    old, new = adopt_replacement(engine, repo, project, knowledge)
    revision = knowledge.revision(project)
    draft = knowledge.open_draft(project, revision.id)
    knowledge.unlink(draft, 'replaces', new, old)
    with pytest.raises(ContractError):
        knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    draft = knowledge.open_draft(project, revision.id)
    knowledge.link(draft, 'replaces', old, new)
    with pytest.raises(ContractError):
        knowledge.adopt(draft, revision.id, origin='owner_confirmed', actor=OWNER)
    with pytest.raises(RuntimeError, match='Task replacement evidence'):
        command.downgrade(migrated_database[1], '0036_knowledge_exchange')
    assert knowledge.revision(project).revision_sha256 == revision.revision_sha256


def test_lineage_migration_round_trip_preserves_prior_revision_and_protections(repo, repository, migrated_database):
    from my_harness.storage.schema import require_schema
    engine, knowledge, project, _ = world(migrated_database[0], repo)
    before = knowledge.revision(project).revision_sha256
    command.downgrade(migrated_database[1], '0036_knowledge_exchange')
    command.upgrade(migrated_database[1], 'head')
    require_schema(engine)
    assert knowledge.revision(project).revision_sha256 == before


def test_replacement_adopted_after_failure_cannot_reset_exhausted_budget(repo, repository, migrated_database):
    engine, knowledge, project, _ = world(migrated_database[0], repo)
    context = make_context(repo)  # One correction, hence at most two executor attempts.
    first = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key='before-replacement')
    worker, agents = supervisor(repository, context,
        [edit(), revise(), edit({'app/main.txt': 'retained failure work\n'}), revise()])
    assert worker.run_once().status == 'DONE'
    assert repository.get_run(first.run_id).history.status == 'revision_limit'
    assert len(agents.requests) == 4
    adopt_replacement(engine, repo, project, knowledge)

    from my_harness.storage.database import make_engine
    reopened = make_engine(migrated_database[0])
    try:
        restarted = SQLiteManagedRepository(reopened, clock=repository.clock)
        next_job = restarted.submit(context, 'P001-T002', PHASE, PLAN.replace(TASK, 'P001-T002'),
                                    VERSIONS, key='after-replacement')
        worker, new_agents = supervisor(restarted, load_context(restarted.get_run(next_job.run_id)), [])
        assert worker.run_once().status == 'DONE'
        assert restarted.get_run(next_job.run_id).history.status == 'revision_limit'
        assert new_agents.requests == []
        assert (repo / 'app/main.txt').read_text() == 'retained failure work\n'
        with Session(reopened) as session:
            assert budget(session, str(repo), 'P001-T002', 1)['executions'] == 2
    finally:
        reopened.dispose()


@pytest.mark.parametrize('prior_executions', [1, 2])
@pytest.mark.parametrize('next_limit', [1, 9])
def test_same_task_keeps_consumption_and_ceiling_without_replacement_links(
        repo, repository, migrated_database, prior_executions, next_limit):
    from my_harness.storage.database import make_engine
    from my_harness.storage.models import GraphThreadRow, ManagedRunRow

    engine, _, project, _ = world(migrated_database[0], repo)
    export = prepare_export(engine, repo, project)
    KnowledgeDelivery(engine, repo, project).execute(export['record_id'], export['preview_sha256'], IDENTITY)
    context = make_context(repo)  # Two executor attempts across all runs of this identity.
    first = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key='same-task-first')
    responses = [edit(), review('BLOCKED')] if prior_executions == 1 else [
        edit(), revise(), edit({'app/main.txt': 'retained partial work\n'}), revise()]
    worker, first_agents = supervisor(repository, load_context(repository.get_run(first.run_id)), responses)
    assert worker.run_once().status == 'DONE'
    assert len(first_agents.requests) == prior_executions * 2
    original_work = (repo / 'app/main.txt').read_bytes()

    reopened = make_engine(migrated_database[0])
    try:
        restarted = SQLiteManagedRepository(reopened, clock=repository.clock)
        broader = replace(context, policy=replace(context.policy, max_revision_cycles=next_limit))
        second = restarted.submit(broader, TASK, PHASE, PLAN, VERSIONS, key='same-task-second')
        with Session(reopened) as session:
            assert session.get(ManagedRunRow, second.run_id).revision_limit == 1
            assert budget(session, str(repo), TASK, next_limit) == {
                'tasks': [TASK], 'executions': prior_executions, 'revision_limit': 1}

        def continue_work(context, request):
            assert (context.root / 'app/main.txt').read_bytes() == original_work
            return edit({'app/main.txt': 'remaining attempt preserved the work\n'})(context, request)

        responses = [continue_work, revise()] if prior_executions == 1 else []
        worker, next_agents = supervisor(restarted, load_context(restarted.get_run(second.run_id)), responses)
        assert worker.run_once().status == 'DONE'
        assert restarted.get_run(second.run_id).history.status == 'revision_limit'
        assert len(next_agents.requests) == (2 if prior_executions == 1 else 0)
        if prior_executions == 2:
            assert (repo / 'app/main.txt').read_bytes() == original_work
        with Session(reopened) as session:
            thread = session.get(GraphThreadRow, f'task-job-{second.id}')
            assert (thread.graph_id, thread.status) == ('managed-task', 'COMPLETED')
            assert budget(session, str(repo), TASK, 9)['executions'] == 2

        unrelated = restarted.submit(context, 'P001-T002', PHASE, PLAN.replace(TASK, 'P001-T002'),
                                     VERSIONS, key='same-task-unrelated')
        worker, independent_agents = supervisor(restarted, load_context(restarted.get_run(unrelated.run_id)),
            [edit(), {**review(), 'task_id': 'P001-T002'}])
        assert worker.run_once().status == 'DONE'
        assert len(independent_agents.requests) == 2
        assert restarted.get_run(unrelated.run_id).history.status == 'acceptance_ready'
    finally:
        reopened.dispose()


def test_same_task_exhaustion_is_rechecked_in_the_fenced_attempt_transaction(
        repo, repository, migrated_database):
    from uuid import uuid4
    from sqlalchemy import select, func
    from my_harness.storage.managed import Conflict
    from my_harness.storage.models import ManagedAttemptRow, UsageInvocationRow

    engine, _, project, _ = world(migrated_database[0], repo)
    export = prepare_export(engine, repo, project)
    KnowledgeDelivery(engine, repo, project).execute(export['record_id'], export['preview_sha256'], IDENTITY)
    context = make_context(repo)
    first = repository.submit(context, TASK, PHASE, PLAN, VERSIONS, key='transaction-source')
    worker, agents = supervisor(repository, load_context(repository.get_run(first.run_id)),
                                [edit(), revise(), edit({'app/main.txt': 'second transaction attempt\n'}), revise()])
    assert worker.run_once().status == 'DONE'
    assert repository.get_run(first.run_id).history.status == 'revision_limit'

    restarted = SQLiteManagedRepository(engine, clock=repository.clock)
    broader = replace(context, policy=replace(context.policy, max_revision_cycles=9))
    second = restarted.submit(broader, TASK, PHASE, PLAN, VERSIONS, key='transaction-target')
    claim = restarted.claim(lease_seconds=120)
    assert claim.id == second.id
    saved = restarted.get_run(second.run_id).history
    history = replace(saved, task_json=repository.get_run(first.run_id).history.task_json)
    request = replace(agents.requests[0], id=str(uuid4()), context_json=history.context_json,
                      task_json=history.task_json, permission_snapshot_json=None)
    with pytest.raises(Conflict, match='persistent correction budget'):
        restarted.agent_started(claim, history, request)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ManagedAttemptRow).where(
            ManagedAttemptRow.run_id == second.run_id)) == 0
        assert session.scalar(select(func.count()).select_from(UsageInvocationRow).where(
            UsageInvocationRow.run_id == second.run_id)) == 0
    assert restarted.get_run(second.run_id).history == saved
    restarted.finish(claim, replace(saved, status='revision_limit'))
