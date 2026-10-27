"""P009-T003: local presets and changes in a single registry; synthetic CLI/SQLite/FS only."""
import copy
from dataclasses import asdict
import hashlib
import json

import pytest
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.journal import JournalError
from my_harness.services.local_config import LocalConfigError, inspect_local_config, load_local_config, summary
from my_harness.services.managed import LocalSupervisor
from my_harness.storage.managed import Conflict
from my_harness.storage.models import (
    ChatConversationRow, ChatProposalRow, ChatTurnRow, ManagedRunRow,
    ManagedJobRow, PlanningConversationRow, PlanningProposalRow, PlanningTurnRow,
)
from test_agent_roles import MIXED_PAIRS, agent
from test_local_config import SENTINEL, launches, setup, web, write  # noqa: F401
from test_managed_api import client
from test_project_registry import POLICY, confirm, operator, register, v3  # noqa: F401
from test_typescript_profile import PHASE, PLAN, TASK, repository  # noqa: F401


def v5(data, roots, *, toml_project=False, selection=None):
    value = v3(data, roots, toml_project=toml_project, bootstrap=True)
    value['format'] = 'local-config-5'
    value['agent_presets'] = {}
    base = value['agents']['reviewer']
    for provider in ('codex', 'claude'):
        for role in ('reviewer', 'executor'):
            config = agent(base, provider, reviewer=role == 'reviewer')
            config.pop('model', None)
            config.pop('effort', None)
            config.update(roles=[role], models=['synthetic-reviewer' if role == 'reviewer' else 'synthetic-executor'],
                          efforts=['medium', 'high'], allow_open_executor=False)
            value['agent_presets'][f'{provider}-{role}'] = config
    if toml_project and selection:
        value['projects'][0]['agent_selection'] = selection
    return value


def selection(reviewer='codex', executor='claude'):
    return {'reviewer': {'preset_id': f'{reviewer}-reviewer', 'model': 'synthetic-reviewer', 'effort': 'high'},
            'executor': {'preset_id': f'{executor}-executor'}}


def project_of(http, config):
    item = http.get('/api/managed/registry/projects/web').json()
    return config.registrar.compose(item['row'], 'registro', registry=(item['version'], item['row_sha256']))[0]


def update(version, **extra):
    return {'action': 'update', 'project_id': 'web', 'expected_version': version, 'composition': 'web',
            'policy': POLICY, **extra}


def test_v4_hash_and_inherited_agents_remain_unchanged(operator):
    context, data, folder, tmp_path = operator
    value = v3(data, [], toml_project=True)
    value['format'] = 'local-config-4'
    old = load_local_config(write(folder, value)).projects[0]
    frozen = {'project': value['projects'][0], 'agents': value['agents'], 'git': value['git'],
              'state_dir': value['service']['state_dir'], 'composition': {'web': value['compositions']['web']},
              'profile': asdict(old.context.profile)}
    assert old.versions['local_config_sha256'] == hashlib.sha256(freeze(frozen).encode()).hexdigest()
    new = load_local_config(write(folder, v5(data, [], toml_project=True))).projects[0]
    assert new.context.policy == old.context.policy
    assert new.versions['cli_config_sha256'] == old.versions['cli_config_sha256']
    assert not launches(tmp_path)


def test_presets_are_private_and_preflight_covers_every_admitted_role(operator):
    _, data, folder, tmp_path = operator
    value = v5(data, [])
    path = write(folder, value)
    config, configs = inspect_local_config(path)
    shown = json.dumps(summary(config))
    assert SENTINEL not in shown and str(folder) not in shown
    assert set(configs) == {'reviewer', 'executor', *(f'preset.{name}.{role}' for name, preset in
                           value['agent_presets'].items() for role in preset['roles'])}
    assert len(config.registrar.options()['agent_presets']) == 4
    assert not launches(tmp_path)
    for fmt in ('local-config-1', 'local-config-2', 'local-config-3', 'local-config-4'):
        broken = copy.deepcopy(value)
        broken['format'] = fmt
        with pytest.raises(LocalConfigError):
            load_local_config(write(folder, broken))


@pytest.mark.parametrize('change', ['role', 'provider', 'effort', 'models', 'missing', 'tools', 'write-version', 'open'])
def test_invalid_presets_fail_at_load_without_processes(operator, change):
    _, data, folder, tmp_path = operator
    value = v5(data, [])
    preset = value['agent_presets']['codex-reviewer']
    if change == 'role':
        preset['roles'] = ['reviewer', 'reviewer']
    elif change == 'provider':
        preset['provider'] = 'other'
    elif change == 'effort':
        preset['efforts'] = ['unknown']
    elif change == 'models':
        preset['models'] = ['-flag']
    elif change == 'missing':
        del preset['models']
    elif change == 'tools':
        value['agent_presets']['claude-executor']['roles'] += ['reviewer']
    elif change == 'write-version':
        value['agent_presets']['codex-executor']['cli_version'] = 'invalid'
    else:
        preset['allow_open_executor'] = 'yes'
    with pytest.raises(LocalConfigError):
        load_local_config(write(folder, value))
    assert not launches(tmp_path)


@pytest.mark.parametrize('reviewer,executor', MIXED_PAIRS)
@pytest.mark.parametrize('fmt', ['local-config-5', 'local-config-8'])
def test_selected_presets_drive_the_plan_and_execution(operator, repository, migrated_database, reviewer, executor, fmt):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, {**v5(data, [tmp_path]), 'format': fmt}))
    with client(migrated_database[0], tmp_path, config) as http:
        shown, saved = confirm(http, register(context.root, agent_selection=selection(reviewer, executor)))
        assert saved.status_code == 200, saved.text
        project = project_of(http, config)
        cli = config.ports_factory(project.context, project.versions)[0]
        assert (cli.agents['reviewer'].provider, cli.agents['executor'].provider) == (reviewer, executor)
        assert config.registrar.agents['reviewer'].provider == 'codex'  # defaults untouched
        job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='selected')
    worker = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert worker.run_once().status == 'DONE'
    record = repository.get_run(job.run_id)
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    assert record.versions_json == freeze(shown['versions'])
    attempts = record.history.attempts
    assert [a.request.role for a in attempts] == ['planner', 'executor', 'reviewer']
    assert attempts[1].request.selection.model == 'synthetic-executor'
    assert attempts[1].request.selection.effort == 'medium' and attempts[1].request.selection.reason
    specs = [item['spec'] for item in repository.processes(job.id)]
    assert [item['provider'] for item in specs] == [reviewer, executor, reviewer]
    assert [json.loads(item)['provider'] for item in launches(tmp_path)] == [reviewer, executor, reviewer]
    with client(migrated_database[0], tmp_path, config) as http:
        preview, blocked = confirm(http, update(1, agent_selection=selection('claude', 'codex')))
        assert blocked.status_code == 409 and blocked.json()['detail']['code'] == 'pending_configuration'
        assert preview['configuration_blockers'] and repository.get_run(job.run_id).versions_json == record.versions_json
    repository.submit_commit(job.run_id, key='commit', expected_version=record.version)
    assert worker.run_once().status == 'DONE'
    committed = repository.get_run(job.run_id)
    assert committed.status == 'COMMITTED'
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, update(1, agent_selection=selection('claude', 'codex')))[1].status_code == 200
        assert repository.get_run(job.run_id) == committed
        assert committed.history.attempts == attempts


def test_four_pairs_switch_on_one_registration_with_restart_and_stale_admission(operator, repository, migrated_database):
    context, data, folder, tmp_path = operator
    value = v5(data, [tmp_path])
    path = write(folder, value)
    config = load_local_config(path)
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root))[1].status_code == 200
        original = project_of(http, config)
        other = tmp_path / 'other'
        other.mkdir()
        assert confirm(http, register(other, project_id='other'))[1].status_code == 200
        other_row = http.get('/api/managed/registry/projects/other').json()
        other_project = config.registrar.compose(other_row['row'], 'other', registry=(1, other_row['row_sha256']))[0]
        for version, pair in enumerate([('codex', 'codex'), ('codex', 'claude'),
                                        ('claude', 'claude'), ('claude', 'codex')], 1):
            body = update(version, agent_selection=selection(*pair))
            preview, saved = confirm(http, body)
            assert saved.status_code == 200, saved.text
            replay = http.post('/api/managed/registry/apply', json={'change': body,
                               'preview_sha256': preview['preview_sha256']})
            assert replay.json()['replayed']
            item = project_of(http, config)
            assert item.id == original.id and item.context.root == original.context.root
            assert (item.versions['reviewer_provider'], item.versions['executor_provider']) == pair
            other_cli = config.ports_factory(other_project.context, other_project.versions)[0]
            assert (other_cli.agents['reviewer'].provider, other_cli.agents['executor'].provider) == ('codex', 'claude')
            with pytest.raises(Conflict, match='configuration changed'):
                repository.submit(original.context, TASK, PHASE, PLAN, dict(original.versions), key=f'old-{version}')
        versions = http.get('/api/managed/projects/web').json()['versions']
        detail = http.get('/api/managed/registry/projects/web').json()
        assert detail['version'] == 5 and len(detail['history']) == 5
        assert 'agent_selection' not in detail['history'][0]['row']
        assert detail['history'][1]['row']['agent_selection'] == selection('codex', 'codex')
    with client(migrated_database[0], tmp_path, load_local_config(path)) as http:
        assert http.get('/api/managed/projects/web').json()['versions'] == versions
        assert http.get('/api/managed/registry/projects/web').json()['history'] == detail['history']
    assert not launches(tmp_path)


@pytest.mark.parametrize('change', ['absent', 'wrong-role', 'reviewer-model', 'reviewer-effort', 'executor-model',
                                   'executor-effort', 'open', 'executable'])
def test_invalid_selection_has_no_fallback(operator, migrated_database, change):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v5(data, [tmp_path])))
    body = register(context.root, agent_selection=selection())
    body['policy'] = copy.deepcopy(POLICY)
    chosen = body['agent_selection']
    if change == 'absent':
        chosen['executor']['preset_id'] = 'absent'
    elif change == 'wrong-role':
        chosen['reviewer']['preset_id'] = 'codex-executor'
    elif change.startswith('reviewer-'):
        chosen['reviewer'][change.split('-')[1]] = 'outside'
    elif change.startswith('executor-'):
        body['policy'][f'executor_{change.split("-")[1]}s'] = ['outside']
    elif change == 'open':
        body['policy']['executor_mode'] = 'open'
    else:
        chosen['executor']['executable'] = ['/untrusted']
    with client(migrated_database[0], tmp_path, config) as http:
        response = http.post('/api/managed/registry/preview', json=body)
        assert response.status_code == 422, response.text
        assert http.get('/api/managed/projects').json() == []
    assert not launches(tmp_path)


def test_selected_preset_drift_quarantines_before_effects(operator, repository, migrated_database):
    context, data, folder, tmp_path = operator
    value = v5(data, [tmp_path])
    config = load_local_config(write(folder, value))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root, agent_selection=selection()))[1].status_code == 200
        project = project_of(http, config)
        job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='pending')
        preview, blocked = confirm(http, update(1, agent_selection=selection('claude', 'codex')))
        assert blocked.status_code == 409 and preview['unfinished_jobs'] == [job.id]
    value['agent_presets']['codex-reviewer']['timeout_seconds'] += 1
    new_config = load_local_config(write(folder, value))
    with client(migrated_database[0], tmp_path, new_config) as http:
        assert http.get('/api/managed/projects/web').json()['versions'] != dict(project.versions)
        worker = LocalSupervisor(repository, new_config.ports_factory, commit_factory=new_config.commit_factory)
        with pytest.raises(JournalError, match='differs from the frozen one'):
            worker.run_once()
    assert repository.get_run(job.run_id).status == 'RECOVERY_REQUIRED'
    assert not launches(tmp_path)


def test_missing_selected_preset_is_unavailable_after_restart(operator, migrated_database):
    context, data, folder, tmp_path = operator
    value = v5(data, [tmp_path])
    config = load_local_config(write(folder, value))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root, agent_selection=selection()))[1].status_code == 200
    del value['agent_presets']['codex-reviewer']
    with client(migrated_database[0], tmp_path, load_local_config(write(folder, value))) as http:
        item = http.get('/api/managed/registry/projects/web').json()
        assert not item['available'] and 'preset missing' in item['diagnostic']
        assert http.get('/api/managed/projects/web').status_code == 404
        assert item['version'] == 1 and len(item['history']) == 1
    assert not launches(tmp_path)


@pytest.mark.parametrize('mode,effort,accepted', [('catalog', 'medium', False), ('open', 'medium', True),
                                               ('open', 'xhigh', False)])
def test_reviewer_cannot_escape_selected_preset_policy(operator, repository, mode, effort, accepted):
    _, data, folder, tmp_path = operator
    value = v5(data, [], toml_project=True, selection=selection())
    value['projects'][0]['policy']['executor_mode'] = mode
    if mode == 'open':
        value['projects'][0]['policy']['executor_models'] = ['reference-only']
    value['agent_presets']['claude-executor']['allow_open_executor'] = True
    value['agent_presets']['codex-reviewer']['environment']['PROBE_SELECTION'] = json.dumps(
        {'model': 'other-model', 'effort': effort})
    config = load_local_config(write(folder, value))
    project = config.projects[0]
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='selection')
    worker = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    worker.run_once()
    record = repository.get_run(job.run_id)
    if accepted:
        assert record.status == 'ACCEPTANCE_READY', record.history.stop
        assert record.history.attempts[1].request.selection.model == 'other-model'
    else:
        assert record.status == 'STOPPED' and record.history.stop.stage == 'planner'
        assert len(launches(tmp_path)) == 1


def seed_proposal(repository, project, kind):
    """Synthetic rows to check admission/staleness without running a provider."""
    job = repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='proposal')
    chat = kind == 'chat'
    conversation_type, turn_type, proposal_type = ((ChatConversationRow, ChatTurnRow, ChatProposalRow) if chat
        else (PlanningConversationRow, PlanningTurnRow, PlanningProposalRow))
    request, result = {'synthetic': 'frozen request'}, {'synthetic': 'frozen answer'}
    with repository._write() as session:
        session.get(ManagedJobRow, job.id).status = 'DONE'
        session.get(ManagedRunRow, job.run_id).status = 'STOPPED'
        conversation = conversation_type(id='conversation', root=str(project.context.root), title='Synthetic',
                                         version=1, actor={}, created_at='now', updated_at='now',
                                         **({} if chat else {'kind': kind, 'known': {}, 'deferred': {}, 'log': []}))
        session.add(conversation)
        session.flush()
        session.add(turn_type(id='turn', conversation_id=conversation.id, number=1, run_id=job.run_id,
                              status='ANSWERED', message='Synthetic', request=request, request_sha256='a' * 64,
                              result=result, actor={}, created_at='now', finished_at='now'))
        session.flush()
        session.add(proposal_type(id='proposal', conversation_id=conversation.id, turn_id='turn', number=1,
                                  status='PROPOSED', proposal_sha256='b' * 64, version=1, created_at='now',
                                  **({'proposal': {}} if chat else {'kind': 'plan', 'content': PLAN,
                                      'reason': 'synthetic', 'content_sha256': 'c' * 64})))
    return job, request, result


@pytest.mark.parametrize('kind', ['phase_planning', 'definition', 'chat'])
def test_usable_conversations_block_or_supersede_without_rewriting_snapshots(operator, repository, migrated_database, kind):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v5(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root))[1].status_code == 200
        project = project_of(http, config)
        job, request, result = seed_proposal(repository, project, kind)
        original = repository.get_run(job.run_id)
        shown, applied = confirm(http, update(1, agent_selection=selection('claude', 'codex')))
        if kind == 'phase_planning':
            assert applied.status_code == 200, applied.text
            with Session(repository.engine) as session:
                proposal = session.get(PlanningProposalRow, 'proposal')
                turn = session.get(PlanningTurnRow, 'turn')
                assert proposal.status == 'SUPERSEDED' and proposal.decision['registry_version'] == 2
                assert turn.request == request and turn.result == result
                assert proposal.content == PLAN and proposal.proposal_sha256 == 'b' * 64
        else:
            assert shown['configuration_blockers'] and applied.status_code == 409
            assert applied.json()['detail']['code'] == 'pending_configuration'
        current = repository.get_run(job.run_id)
        assert current.history == original.history and current.versions_json == original.versions_json
    assert not launches(tmp_path)


def test_transaction_rechecks_job_queued_after_preview(operator, repository, migrated_database):
    from my_harness.storage.registry import ProjectRegistryRepository, RegistryConflict
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v5(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root))[1].status_code == 200
        shown = http.post('/api/managed/registry/preview', json=update(1, agent_selection=selection())).json()
        project = project_of(http, config)
        repository.submit(project.context, TASK, PHASE, PLAN, dict(project.versions), key='racing')
        with pytest.raises(RegistryConflict) as error:
            ProjectRegistryRepository(repository).apply('update', 'web', expected_version=1, row=shown['row'],
                row_sha256=shown['row_sha256'], profile=shown['profile'], preview_sha256=shown['preview_sha256'],
                protect_agents=True)
        assert error.value.code == 'pending_jobs'
        assert http.get('/api/managed/registry/projects/web').json()['version'] == 1
    assert not launches(tmp_path)


def test_new_child_freezes_selected_presets_through_creation(operator, repository, migrated_database):
    from my_harness.services.managed_runtime import ManagedRuntime
    from test_project_creation import request, select_root
    _, data, folder, tmp_path = operator
    parent = tmp_path / 'chosen'
    parent.mkdir()
    config = load_local_config(write(folder, v5(data, [])))
    runtime = ManagedRuntime(repository.engine, config)
    runtime.start()
    try:
        select_root(runtime.creation, parent)
        body = request(runtime.creation, agent_selection=selection('claude', 'codex'))
        result = runtime.creation.confirm(body, 'create')
        assert result['status'] == 'REGISTERED'
        project = runtime.project('child')
        assert project.versions == result['intent']['versions']
        assert result['intent']['agents']['reviewer']['provider'] == 'claude'
        assert result['intent']['agents']['executor']['provider'] == 'codex'
        assert runtime.registry.read('child')['row']['agent_selection'] == selection('claude', 'codex')
        assert list((parent / 'child').iterdir()) == []
    finally:
        runtime.stop()
    assert not launches(tmp_path)
