"""H3.2: frozen requests, next-attempt authority and recovery, all offline."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json
import os
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIConfig, argv_for
from my_harness.adapters.engine_fake import ScriptedAgentAdapter, ScriptedCommandRunner, SyntheticWorkspace
from my_harness.core.engine.contracts import AgentResult, freeze
from my_harness.core.engine.permissions import KINDS, LAYERS, digest, snapshot_entries
from my_harness.core.engine.serialization import dump_history, load_history
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedConfig, ManagedProject
from my_harness.storage.managed import Conflict, SQLiteManagedRepository
from my_harness.storage.models import ManagedAttemptRow, PermissionRequestRow
from my_harness.storage.permissions import PermissionRepository
from test_managed import PLAN, VERSIONS, context, repository
from test_managed_api import client

TARGETS = dict(files='app/main.txt', tools='Bash(test-runner check)', network='example.invalid',
               product='requirement:R1', acceptance='checkpoint')
OPERATIONS = dict(files='write', tools='use', network='connect', product='decide', acceptance='accept')


@pytest.fixture
def setup(repository, context):
    context = replace(context, policy=replace(context.policy, max_revision_cycles=3))
    authority = {layer: {kind: [target] for kind, target in TARGETS.items()} for layer in LAYERS}
    versions = {**VERSIONS, 'permission_authority': freeze(authority)}
    agents = ScriptedAgentAdapter([AgentResult(None, True, 1, error='Synthetic permission stop')] * 8)
    runner = ScriptedCommandRunner([])
    workspace = SyntheticWorkspace(context, ('app/main.txt',))
    worker = LocalSupervisor(repository, lambda c, v: (agents, runner, workspace))
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, versions, key='start')
    worker.run_once()
    return repository, PermissionRepository(repository), job.run_id, worker, agents, context


def request(setup, kind='tools', **overrides):
    repository, permissions, run_id, _, _, _ = setup
    record = repository.get_run(run_id)
    body = dict(kind=kind, target=TARGETS[kind], operation=OPERATIONS[kind], arguments=[], requested_by='synthetic executor',
                source_attempt_id=record.history.attempts[-1].request.id, reason='Synthetic required operation', ttl_seconds=3600)
    return permissions.create(run_id, record.version, **{**body, **overrides})


def decide(setup, row, decision='grant', scope='once', **overrides):
    repository, permissions, run_id, *_ = setup
    body = dict(expected_request_version=row['version'], fingerprint=row['fingerprint'], decision=decision,
                scope=scope, reason='Synthetic operator decision')
    return permissions.decide(run_id, row['id'], repository.get_run(run_id).version, **{**body, **overrides})


def resume(setup, retry=True):
    repository, _, run_id, worker, *_ = setup
    repository.resume(run_id, key=str(repository.get_run(run_id).version), expected_version=repository.get_run(run_id).version,
                      retry_executor=retry)
    worker.run_once()
    return repository.get_run(run_id)


@pytest.mark.parametrize('kind', KINDS)
def test_categories_audited_and_do_not_imply_each_other(setup, kind):
    row = request(setup, kind)
    assert row['status'] == 'PENDING' and row['decision'] is None
    result = decide(setup, row)
    assert result['decision']['actor']['uid'] == os.getuid()
    assert result['decision']['fingerprint'] == row['fingerprint']
    assert result['decision']['expires_at'] == row['expires_at']
    assert result['decision']['reason'] == 'Synthetic operator decision'
    assert len(setup[4].requests) == 1  # granting never launches
    record = resume(setup)
    grants = snapshot_entries(record.history.attempts[-1].request)
    assert [g['request']['kind'] for g in grants] == ([kind] if kind in ('files', 'tools', 'network') else [])
    assert not record.history.acceptance


@pytest.mark.parametrize('layer', LAYERS)
def test_each_higher_ceiling_denies_independently(setup, layer):
    repo, permissions, run_id, *_ = setup
    # Synthetic persisted configuration for testing each frozen ceiling.
    from my_harness.storage.models import ManagedRunRow
    with Session(repo.engine) as session, session.begin():
        run = session.get(ManagedRunRow, run_id)
        versions = json.loads(run.versions_json)
        authority = json.loads(versions['permission_authority'])
        authority[layer]['tools'] = []
        versions['permission_authority'] = freeze(authority)
        run.versions_json = freeze(versions)
    row = request(setup)
    with pytest.raises(Conflict, match='authority'):
        decide(setup, row)
    assert permissions.list(run_id)[0]['status'] == 'PENDING'
    assert decide(setup, row, decision='deny')['status'] == 'DENIED'
    assert not snapshot_entries(resume(setup).history.attempts[-1].request)


@pytest.mark.parametrize('scope,counts', [('once', [1, 0]), ('task', [1, 1])])
def test_restart_once_and_task_preserve_history_and_budget(setup, scope, counts):
    repo, permissions, run_id, worker, agents, context = setup
    row = request(setup); decide(setup, row, scope=scope)
    with Session(repo.engine) as session:
        original = session.scalars(select(ManagedAttemptRow).where(ManagedAttemptRow.run_id == run_id)).one()
        original_bytes = original.request_json, original.result_json
    restarted = SQLiteManagedRepository(repo.engine)
    setup = (restarted, PermissionRepository(restarted), run_id,
             LocalSupervisor(restarted, worker.ports_factory), agents, context)
    for count in counts:
        record = resume(setup)
        assert len(snapshot_entries(record.history.attempts[-1].request)) == count
        assert load_history(dump_history(record.history)) == record.history
    assert record.revisions == 2 and len(record.history.attempts) == 3
    with Session(repo.engine) as session:
        original = session.get(ManagedAttemptRow, original.id)
        assert (original.request_json, original.result_json) == original_bytes
    item = setup[1].list(run_id)[0]
    assert item['status'] == ('CONSUMED' if scope == 'once' else 'GRANTED')
    assert bool(item['consumed_by']) == (scope == 'once')


def test_expiry_at_decision_and_at_next_attempt(setup):
    repo, permissions, run_id, *_ = setup
    now = repo.clock()
    repo.clock = lambda: now
    pending = request(setup, ttl_seconds=1)
    now += timedelta(seconds=1)
    with pytest.raises(Conflict, match='expired'):
        decide(setup, pending)
    row = request(setup, target=TARGETS['tools'], ttl_seconds=1)
    decide(setup, row)
    now += timedelta(seconds=1)
    assert not snapshot_entries(resume(setup).history.attempts[-1].request)
    assert [r['effective_status'] for r in permissions.list(run_id)] == ['EXPIRED', 'EXPIRED']


def test_replaced_request_cannot_accept_old_decision_or_grant(setup):
    first = request(setup); decide(setup, first, scope='task')
    second = request(setup, supersedes=first['id'], reason='Changed operation context')
    with pytest.raises(Conflict):
        decide(setup, first)
    with pytest.raises(Conflict):
        decide(setup, second, fingerprint=first['fingerprint'])
    decide(setup, second, decision='deny')
    assert not snapshot_entries(resume(setup).history.attempts[-1].request)
    records = setup[1].list(setup[2])
    assert records[0]['status'] == 'SUPERSEDED' and records[0]['decision']['scope'] == 'task'
    assert records[1]['status'] == 'DENIED_CONSUMED' and records[1]['supersedes'] == first['id']


def test_duplicate_scope_requires_explicit_replacement(setup):
    request(setup)
    with pytest.raises(Conflict, match='Replace'):
        request(setup)


def test_concurrent_grant_and_deny_only_one_commits(setup):
    row = request(setup)
    repo, permissions, run_id, *_ = setup
    version = repo.get_run(run_id).version
    barrier = Barrier(2)
    def act(decision):
        barrier.wait()
        try:
            return permissions.decide(run_id, row['id'], version, expected_request_version=1,
                    fingerprint=row['fingerprint'], decision=decision, scope='once', reason=decision)['status']
        except Conflict:
            return 'CONFLICT'
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(act, ['grant', 'deny']))
    assert results.count('CONFLICT') == 1
    assert len([e for e in repo.events(run_id) if e['kind'] == 'permission_decided']) == 1


def test_queued_or_live_attempt_refuses_permission_mutation(setup):
    row = request(setup)
    repo, _, run_id, *_ = setup
    repo.resume(run_id, key='pending', expected_version=repo.get_run(run_id).version, retry_executor=True)
    with pytest.raises(Conflict, match='boundary'):
        decide(setup, row)
    assert repo.claim() is not None
    with pytest.raises(Conflict, match='boundary'):
        request(setup, kind='network')


def test_revalidate_does_not_consume_executor_grant(setup):
    row = request(setup); decide(setup, row)
    initial = setup[0].get_run(setup[2]).history
    record = resume(setup, retry=False)
    assert [a.request.role for a in record.history.attempts] == ['executor', 'reviewer']
    assert record.history.attempts[0] == initial.attempts[0]
    assert record.revisions == 0 and record.history.cycles
    assert setup[1].list(setup[2])[0]['status'] == 'GRANTED'
    assert len(snapshot_entries(resume(setup).history.attempts[-1].request)) == 1


def test_cli_scoped_tool_rule_only_changes_next_argv(setup):
    row = request(setup); decide(setup, row)
    previous = setup[0].get_run(setup[2]).history.attempts[0].request
    current = resume(setup).history.attempts[-1].request
    config = CLIConfig('claude', ('/synthetic/claude',), '2.1.304', (), 1, tools=('Bash',),
                       grantable_tools=(TARGETS['tools'],))
    before, after = (argv_for(config, setup[-1], r) for r in (previous, current))
    assert before[before.index('--allowedTools') + 1] == ''
    assert after[after.index('--allowedTools') + 1] == TARGETS['tools']
    assert after[after.index('--permission-mode') + 1] == 'dontAsk'
    assert before[before.index('--tools') + 1] == ''
    assert after[after.index('--tools') + 1] == 'Bash'
    assert config.allowed_tools == ()
    with pytest.raises(ValueError, match='capabilities'):
        argv_for(replace(config, grantable_tools=()), setup[-1], current)
    bad = json.loads(current.permission_snapshot_json)
    bad['payload']['task_json'] = '{}'
    bad['sha256'] = digest(bad['payload'])
    with pytest.raises(ValueError, match='frozen attempt'):
        argv_for(config, setup[-1], replace(current, permission_snapshot_json=freeze(bad)))
    with pytest.raises(ValueError, match='snapshot'):
        argv_for(config, setup[-1], replace(current, id='another-attempt'))


def test_codex_executor_refuses_tool_grant_before_launch(setup):
    # D052: Codex has no tool inventory to scope; the grant is refused, never ignored.
    row = request(setup); decide(setup, row)
    previous = setup[0].get_run(setup[2]).history.attempts[0].request
    current = resume(setup).history.attempts[-1].request
    config = CLIConfig('codex', ('/synthetic/codex',), '0.164.0', (), 1)
    argv = argv_for(config, setup[-1], previous)
    assert argv[argv.index('--sandbox') + 1] == 'workspace-write'
    with pytest.raises(ValueError, match='cannot enforce scoped tool grants'):
        argv_for(config, setup[-1], current)


def test_network_grant_refused_by_cli_before_launch(setup):
    row = request(setup, 'network'); decide(setup, row)
    current = resume(setup).history.attempts[-1].request
    config = CLIConfig('claude', ('/synthetic/claude',), '2.1.304', (), 1)
    with pytest.raises(ValueError, match='network'):
        argv_for(config, setup[-1], current)


def test_api_guards_versions_confirmation_and_no_invocation(setup, migrated_database, tmp_path):
    repo, _, run_id, _, agents, context = setup
    conf = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),))
    row = request(setup)
    path = f'/api/managed/runs/{run_id}/permissions'
    with client(migrated_database[0], tmp_path, conf) as http:
        assert http.get(path).json()[0]['fingerprint'] == row['fingerprint']
        body = dict(expected_version=repo.get_run(run_id).version, expected_request_version=1,
                    fingerprint=row['fingerprint'], decision='grant', scope='once', reason='HTTP decision', confirmed=True)
        url = path + f"/{row['id']}/decision"
        assert http.post(url, json=body, headers={'Origin': 'https://external.invalid'}).status_code == 403
        assert http.post(url, json={**body, 'confirmed': False}).status_code == 422
        assert http.post(url, json={**body, 'expected_version': body['expected_version'] - 1}).status_code == 409
        result = http.post(url, json=body)
        assert result.status_code == 200 and result.json()['decision']['actor']['uid'] == os.getuid()
        assert http.post(url, json=body).status_code == 409
        assert len(agents.requests) == 1


def test_denial_prevents_executor_call_and_replacement_restores_explicit_retry(setup):
    row = request(setup); decide(setup, row, decision='deny')
    original_calls = len(setup[4].requests)
    record = resume(setup)
    assert len(setup[4].requests) == original_calls
    assert 'explicit permission denial' in record.history.stop.reason
    replacement = request(setup, supersedes=row['id']); decide(setup, replacement)
    record = resume(setup)
    assert len(setup[4].requests) == original_calls + 1
    assert snapshot_entries(record.history.attempts[-1].request)[0]['id'] == replacement['id']


def test_permission_migration_roundtrip_and_old_codec(setup, migrated_database):
    from alembic import command
    from sqlalchemy import inspect
    row = request(setup); decide(setup, row)
    record = resume(setup)
    assert json.loads(dump_history(record.history))['format'] == 5
    old = json.loads(dump_history(record.history))
    old['format'] = 4
    for attempt in old['history']['attempts']:
        attempt['request'].pop('permission_snapshot_json')
    historical = load_history(freeze(old))
    assert all(a.request.permission_snapshot_json is None for a in historical.attempts)
    assert json.loads(dump_history(historical))['format'] == 4
    command.check(migrated_database[1])
    command.downgrade(migrated_database[1], '0008_prompt_versions')
    assert 'permission_requests' not in inspect(setup[0].engine).get_table_names()
    command.upgrade(migrated_database[1], 'head')
    assert setup[0].get_run(setup[2]) == record
    command.check(migrated_database[1])


def test_mutated_request_cannot_reuse_fingerprint(setup):
    row = request(setup)
    with Session(setup[0].engine) as session, session.begin():
        stored = session.get(PermissionRequestRow, row['id'])
        stored.request = {**stored.request, 'target': 'Bash(other-command)'}
    with pytest.raises(Conflict, match='changed'):
        decide(setup, row)


def test_grant_bound_to_frozen_configuration_is_not_reused(setup):
    from my_harness.storage.models import ManagedRunRow
    row = request(setup); decide(setup, row)
    with Session(setup[0].engine) as session, session.begin():
        run = session.get(ManagedRunRow, setup[2])
        run.versions_json = freeze({**json.loads(run.versions_json), 'changed': 'synthetic'})
    assert not snapshot_entries(resume(setup).history.attempts[-1].request)


def test_file_ceiling_cannot_expand_contract_or_escape_checkout(setup):
    from my_harness.storage.models import ManagedRunRow
    repo, _, run_id, *_ = setup
    with Session(repo.engine) as session, session.begin():
        run = session.get(ManagedRunRow, run_id)
        versions = json.loads(run.versions_json)
        authority = json.loads(versions['permission_authority'])
        for layer in LAYERS:
            authority[layer]['files'] += ['docs/STATE.md', '../outside.txt']
        versions['permission_authority'] = freeze(authority)
        run.versions_json = freeze(versions)
    for path in ('docs/STATE.md', '../outside.txt'):
        row = request(setup, 'files', target=path)
        with pytest.raises(Conflict, match='authority'):
            decide(setup, row)


def test_cli_grant_launch_uses_persisted_snapshot_and_exact_rule(repository, context, tmp_path):
    from test_cli_agents import adapter
    port = adapter(tmp_path, mode='exit_error')
    port.agents['executor'] = replace(port.agents['executor'], tools=('Bash',), grantable_tools=(TARGETS['tools'],))
    authority = {layer: {'tools': [TARGETS['tools']]} for layer in LAYERS}
    versions = {**VERSIONS, **port.frozen_versions(), 'permission_authority': freeze(authority)}
    workspace = SyntheticWorkspace(context, ('app/main.txt',))
    configs = dict(port.agents)
    from my_harness.adapters.cli_agents import CLIProcessAdapter
    worker = LocalSupervisor(repository, lambda c, v: (CLIProcessAdapter(configs, port.artifact_root),
                                                      ScriptedCommandRunner([]), workspace))
    job = repository.submit(context, 'P001-T001', 'P001', PLAN, versions, key='cli')
    worker.run_once()
    setup = (repository, PermissionRepository(repository), job.run_id, worker, None, context)
    row = request(setup); decide(setup, row)
    record = resume(setup)
    launches = [json.loads(line) for line in (tmp_path / 'launches.jsonl').read_text().splitlines()]
    assert len(launches) == 2
    assert launches[0]['argv'][launches[0]['argv'].index('--allowedTools') + 1] == ''
    assert launches[1]['argv'][launches[1]['argv'].index('--allowedTools') + 1] == TARGETS['tools']
    assert snapshot_entries(record.history.attempts[-1].request)[0]['id'] == row['id']
    with Session(repository.engine) as session:
        stored = session.get(ManagedAttemptRow, record.history.attempts[-1].request.id)
        assert json.loads(stored.request_json)['permission_snapshot_json'] == record.history.attempts[-1].request.permission_snapshot_json


def test_api_create_replace_deny_and_actions(setup, migrated_database, tmp_path):
    repo, _, run_id, _, agents, context = setup
    conf = ManagedConfig((ManagedProject('synthetic', context, VERSIONS),))
    path = f'/api/managed/runs/{run_id}/permissions'
    with client(migrated_database[0], tmp_path, conf) as http:
        run = http.get(f'/api/managed/runs/{run_id}').json()
        assert run['actions'] == ['revalidate', 'retry_executor', 'permissions']
        body = dict(expected_version=run['version'], kind='tools', target=TARGETS['tools'], operation='use', arguments=[],
                    requested_by='synthetic executor', source_attempt_id=repo.get_run(run_id).history.attempts[0].request.id,
                    reason='HTTP request', ttl_seconds=3600)
        assert http.post(path, json=body, headers={'X-My-Harness': ''}).status_code == 403
        response = http.post(path, json=body)
        assert response.status_code == 201
        first = response.json()
        assert http.post(path, json=body).status_code == 409
        replacement = http.post(path, json={**body, 'expected_version': repo.get_run(run_id).version,
                                          'supersedes': first['id'], 'reason': 'Changed request'})
        assert replacement.status_code == 201
        second = replacement.json()
        denial = http.post(path + f"/{second['id']}/decision", json=dict(expected_version=repo.get_run(run_id).version,
            expected_request_version=second['version'], fingerprint=second['fingerprint'], decision='deny',
            scope='task', reason='HTTP explicit denial', confirmed=True))
        assert denial.status_code == 200
        rows = http.get(path).json()
        assert [r['status'] for r in rows] == ['SUPERSEDED', 'DENIED']
        assert len(agents.requests) == 1


def test_crash_after_intent_never_reuses_once_grant(setup):
    from test_managed import SyntheticCrash
    row = request(setup); decide(setup, row)
    repo, permissions, run_id, _, agents, context = setup
    def crash(c, r):
        raise SyntheticCrash()
    agents.responses.insert(0, crash)
    record = repo.get_run(run_id)
    repo.resume(run_id, key='crash-after-grant', expected_version=record.version, retry_executor=True)
    now = repo.clock()
    repo.clock = lambda: now
    worker = LocalSupervisor(repo, setup[3].ports_factory, lease_seconds=1)
    with pytest.raises(SyntheticCrash):
        worker.run_once()
    consumed = permissions.list(run_id)[0]
    assert consumed['status'] == 'CONSUMED' and consumed['consumed_by']
    with Session(repo.engine) as session:
        intent = session.get(ManagedAttemptRow, consumed['consumed_by'])
        assert intent.result_json is None and json.loads(intent.request_json)['permission_snapshot_json']
    now += timedelta(seconds=2)
    recovered = repo.recover_expired()
    assert len(recovered) == 1
    job = repo.get_job(recovered[0])
    with pytest.raises(Conflict, match='boundary'):
        request(setup, kind='network')
    repo.confirm_stopped(job.id, owner_token=job.owner_token, expected_version=repo.get_run(run_id).version,
                         reason='Synthetic owner closed; no process was launched')
    record = resume(setup)
    assert not snapshot_entries(record.history.attempts[-1].request)
    assert record.revisions == 2


def test_cli_checks_expiry_again_at_launch_boundary(setup):
    row = request(setup); decide(setup, row)
    current = resume(setup).history.attempts[-1].request
    saved = json.loads(current.permission_snapshot_json)
    saved['payload']['grants'][0]['expires_at'] = '2000-01-01T00:00:00.000000+00:00'
    saved['sha256'] = digest(saved['payload'])
    config = CLIConfig('claude', ('/synthetic/claude',), '2.1.304', (), 1,
                       tools=('Bash',), grantable_tools=(TARGETS['tools'],))
    with pytest.raises(ValueError, match='expired'):
        argv_for(config, setup[-1], replace(current, permission_snapshot_json=freeze(saved)))


def test_revalidate_revise_never_launches_executor_or_consumes_grant(setup):
    from test_managed import review
    row = request(setup); decide(setup, row)
    agents = setup[4]
    agents.responses.appendleft(review('REVISE'))
    initial_calls = len(agents.requests)
    record = resume(setup, retry=False)
    assert record.history.stop.stage == 'revision'
    assert record.history.cycles[-1].verdict == 'REVISE'
    assert [r.role for r in agents.requests[initial_calls:]] == ['reviewer']
    assert record.revisions == 0
    assert setup[1].list(setup[2])[0]['status'] == 'GRANTED'
