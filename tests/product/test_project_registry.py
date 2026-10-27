"""H6.2 E2 (D054/D076): `local-config-3` and project registration from the UI.

Synthetic CLIs through the real adapter, real Node/npm/Git and temporary SQLite; no providers or network.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.journal import JournalError
from my_harness.services.local_config import LocalConfigError, load_local_config, summary
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import CONFIG_ENV
from my_harness.storage.models import RegisteredProjectEventRow
from test_agent_roles import v2
from test_local_config import SENTINEL, launches, setup, write  # noqa: F401 (fixture)
from test_managed_api import client
from test_typescript_profile import PHASE, PLAN, TASK, repository, web  # noqa: F401 (fixtures)

POLICY = {'planning_mode': 'agent', 'executor_mode': 'catalog', 'executor_models': ['synthetic-executor'],
          'executor_efforts': ['medium'], 'max_revision_cycles': 1}


def v3(data, roots, *, bootstrap=False, toml_project=False):
    """`local-config-1` fixture data rewritten as `local-config-3`: the project commands become a composition."""
    data = v2(data)
    project = data.pop('projects')[0]
    data['format'] = 'local-config-3'
    data['compositions'] = {'web': {'profile': 'typescript-web', **project['commands']}}
    data['registration'] = {'roots': [str(root) for root in roots], 'bootstrap_enabled': bootstrap}
    if toml_project:
        data['projects'] = [{'id': 'operator', 'root': project['root'], 'repository_trusted': True,
                             'composition': 'web', 'policy': project['policy']}]
    return data


def register(root, project_id='web', **changes):
    return {'action': 'register', 'project_id': project_id, 'expected_version': 0, 'root': str(root),
            'composition': 'web', 'policy': POLICY, 'work_language': 'en', **changes}


def confirm(http, body, trust=True, **extra):
    preview = http.post('/api/managed/registry/preview', json=body)
    assert preview.status_code == 200, preview.text
    preview = preview.json()
    request = {'change': body, 'preview_sha256': preview['preview_sha256'], **extra}
    if trust and preview['trust_required']:
        request['trust_root'] = preview['row']['root']
    return preview, http.post('/api/managed/registry/apply', json=request)


@pytest.fixture
def operator(setup, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    context, data, folder, tmp_path = setup
    return context, data, folder, tmp_path


def test_local_config_3_composes_without_projects_and_hides_environment(operator):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [tmp_path])))
    assert config.projects == () and config.registrar.registrable
    options = config.registrar.options()
    assert options['roots'] == [str(tmp_path)] and options['bootstrap_enabled'] is False
    (composition,) = options['compositions']
    assert composition['name'] == 'web' and composition['profile'] == 'typescript-web'
    shown = json.dumps(summary(config))
    assert SENTINEL not in shown and summary(config)['registration']['compositions'] == options['compositions']
    assert not launches(tmp_path)


def test_local_config_3_toml_projects_name_a_composition(operator):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [], toml_project=True)))
    (project,) = config.projects
    assert project.id == 'operator' and project.versions['local_config'] == 'local-config-3'
    assert 'project_registry' not in project.versions and project.bootstrap_enabled is False
    assert isinstance(config.ports_factory(project.context, dict(project.versions)), tuple)
    for change in ('unknown-composition', 'inline-commands', 'no-compositions', 'bad-root', 'unknown-key'):
        broken = v3(data, [], toml_project=True)
        if change == 'unknown-composition':
            broken['projects'][0]['composition'] = 'absent'
        elif change == 'inline-commands':
            broken['projects'][0]['commands'] = broken['compositions']['web']
        elif change == 'no-compositions':
            broken['compositions'] = {}
        elif change == 'bad-root':
            broken['registration']['roots'] = ['relative']
        else:
            broken['registration']['extra'] = True
        with pytest.raises(LocalConfigError):
            load_local_config(write(folder, broken))


def test_example_template_documents_automatic_local_config_8_keys(operator):
    """The public template needs no executable/version pin; the project explicitly declares its work language."""
    import tomllib
    data = v3(operator[1], [], toml_project=True)
    example = tomllib.loads((Path(__file__).parents[2] / 'examples/local_config.example.toml').read_text())
    assert example['format'] == 'local-config-8' and example.keys() == data.keys() | {'profiles'}
    assert example['registration'].keys() == data['registration'].keys()
    assert example['compositions']['web'].keys() == data['compositions']['web'].keys()
    assert example['projects'][0].keys() == data['projects'][0].keys() | {'work_language'}
    assert example['projects'][0]['policy'].keys() == data['projects'][0]['policy'].keys() - {'max_revision_cycles'}
    for name in ('reviewer', 'executor'):
        assert example['agents'][name].keys() == data['agents'][name].keys() - {'executable', 'cli_version'}


def test_previous_formats_keep_their_frozen_identity(operator):
    """local-config-1, -2 and -3 read the same: the same frozen hash as before their successors."""
    context, data, folder, tmp_path = operator
    for fmt, value in (('local-config-1', data), ('local-config-2', v2(data))):
        project = load_local_config(write(folder, value)).projects[0]
        key = 'providers' if fmt == 'local-config-1' else 'agents'
        expected = hashlib.sha256(freeze({'project': value['projects'][0], key: value[key], 'git': value['git'],
                                          'state_dir': value['service']['state_dir']}).encode()).hexdigest()
        assert project.versions['local_config'] == fmt and project.versions['local_config_sha256'] == expected
        assert 'project_registry' not in project.versions
    # P008-T008: local-config-3 keeps its hash (without the profile, which only enters local-config-4).
    value = v3(data, [], toml_project=True)
    project = load_local_config(write(folder, value)).projects[0]
    composition = {'web': {'profile': 'typescript-web', **value['compositions']['web']}}
    expected = hashlib.sha256(freeze({'project': value['projects'][0], 'agents': value['agents'], 'git': value['git'],
                                      'state_dir': value['service']['state_dir'],
                                      'composition': composition}).encode()).hexdigest()
    assert project.versions['local_config'] == 'local-config-3'
    assert project.versions['local_config_sha256'] == expected


def test_register_from_the_api_to_the_first_task(operator, repository, migrated_database):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        options = http.get('/api/managed/registry').json()
        assert options['available'] and options['format'] == 'local-config-3' and options['projects'] == []
        assert http.get('/api/managed/projects').json() == []
        preview, applied = confirm(http, register(context.root), trust=False)
        assert preview['trust_required'] and preview['version'] == 1 and preview['status'] == 'ACTIVE'
        assert preview['versions']['project_registry'] == '1' and preview['profile'] == 'typescript-web'
        assert applied.status_code == 409 and applied.json()['detail']['code'] == 'trust_unconfirmed'
        request = {'change': register(context.root), 'preview_sha256': preview['preview_sha256'],
                   'trust_root': str(context.root) + '/'}
        assert http.post('/api/managed/registry/apply', json=request).json()['detail']['code'] == 'trust_unconfirmed'
        request['trust_root'] = str(context.root)
        first = http.post('/api/managed/registry/apply', json=request)
        assert first.status_code == 200 and first.json()['replayed'] is False
        again = http.post('/api/managed/registry/apply', json=request)
        assert again.json() == {**first.json(), 'replayed': True}
        detail = http.get('/api/managed/registry/projects/web').json()
        assert detail['version'] == 1 and len(detail['history']) == 1 and detail['available']
        assert detail['trust']['confirmed'] and detail['trust']['root'] == str(context.root)
        assert detail['history'][0]['actor']['uid'] and detail['history'][0]['action'] == 'register'
        project = http.get('/api/managed/projects/web').json()
        assert project['source'] == 'registry' and project['registry_version'] == 1
        assert project['versions'] == preview['versions']
        # First task in the newly registered project, without restarting or editing files.
        job = http.post('/api/managed/projects/web/runs', json={'task_id': TASK, 'phase_id': PHASE, 'text': PLAN},
                        headers={'Idempotency-Key': 'first-task'})
        assert job.status_code == 202, job.text
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert supervisor.run_once().status == 'DONE'
    record = repository.get_run(job.json()['run_id'])
    assert record.status == 'ACCEPTANCE_READY', record.history.stop
    assert [a.request.role for a in record.history.attempts] == ['planner', 'executor', 'reviewer']
    assert 'tasks * 30' in context.path('src/estimate.ts').read_text()


def test_registration_rejections(operator, migrated_database):
    context, data, folder, tmp_path = operator
    links = tmp_path / 'links'
    links.mkdir()
    (links / 'checkout').symlink_to(context.root)
    state = tmp_path / 'state'
    config = load_local_config(write(folder, v3(data, [context.root, links, state])))
    with client(migrated_database[0], tmp_path, config) as http:
        def code(body, status):
            response = http.post('/api/managed/registry/preview', json=body)
            assert response.status_code == status, response.text
            return response.json()['detail']['code']
        assert code(register(tmp_path / 'web-main'), 422) == 'root_not_authorized'
        assert code(register(links / 'checkout'), 422) == 'root_symlink'
        assert code(register(context.root / 'missing'), 422) == 'root_missing'
        assert code(register(str(context.root) + '/../web-task'), 422) == 'root_not_canonical'
        assert code(register('relative/path'), 422) == 'root_not_absolute'
        assert code(register(state, project_id='state'), 422) == 'root_service_state'
        assert code(register(context.root, project_id='new'), 422) == 'invalid_id'
        assert code(register(context.root, project_id='Bad Id'), 422) == 'invalid_id'
        assert code(register(context.root, bootstrap_enabled=True), 422) == 'bootstrap_not_allowed'
        assert code(register(context.root, composition='absent'), 422) == 'invalid_request'
        assert code(register(context.root, policy={**POLICY, 'executor_efforts': ['ultra']}), 422) == 'invalid_request'
        assert code(register(context.root, expected_version=3), 409) == 'stale_version'
        # Nothing executable over HTTP: keys outside the schema are rejected.
        assert http.post('/api/managed/registry/preview', json={**register(context.root), 'commands': {}}
                         ).status_code == 422
        assert confirm(http, register(context.root))[1].status_code == 200
        assert code(register(context.root, project_id='other'), 409) == 'root_taken'
        assert code(register(context.root / 'src', project_id='nested'), 409) == 'root_taken'
        assert code(register(context.root), 409) == 'duplicate_id'
        assert [p['id'] for p in http.get('/api/managed/registry').json()['projects']] == ['web']


def test_ids_cannot_shadow_operator_projects_and_tampered_previews_fail(operator, migrated_database):
    context, data, folder, tmp_path = operator
    other = tmp_path / 'other'
    other.mkdir()
    config = load_local_config(write(folder, v3(data, [tmp_path], toml_project=True)))
    with client(migrated_database[0], tmp_path, config) as http:
        options = http.get('/api/managed/registry').json()
        assert options['operator_projects'] == ['operator']
        response = http.post('/api/managed/registry/preview', json=register(other, project_id='operator'))
        assert response.status_code == 409 and response.json()['detail']['code'] == 'duplicate_id'
        assert http.get('/api/managed/projects/operator').json()['source'] == 'operator'
        assert http.post('/api/managed/registry/preview', json={
            'action': 'update', 'project_id': 'operator', 'expected_version': 0}).status_code == 404
        response = http.post('/api/managed/registry/preview', json=register(tmp_path, project_id='parent'))
        assert response.json()['detail']['code'] in ('root_taken', 'root_service_state')
        body = register(other, project_id='other')
        tampered = http.post('/api/managed/registry/apply', json={
            'change': body, 'preview_sha256': '0' * 64, 'trust_root': str(other)})
        assert tampered.status_code == 409 and tampered.json()['detail']['code'] == 'preview_changed'
        assert http.get('/api/managed/registry').json()['projects'] == []


def test_update_and_retire_are_versioned_audited_and_guarded(operator, repository, migrated_database):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root))[1].status_code == 200
        first = http.get('/api/managed/projects/web').json()['versions']
        update = {'action': 'update', 'project_id': 'web', 'expected_version': 1, 'composition': 'web',
                  'policy': {**POLICY, 'max_revision_cycles': 2}, 'tag_kind': 'annotated'}
        preview, applied = confirm(http, update)
        assert not preview['trust_required'] and preview['version'] == 2
        assert {c['field'] for c in preview['changes']} == {'policy', 'tag_kind'}
        assert applied.status_code == 200
        second = http.get('/api/managed/projects/web').json()
        assert second['registry_version'] == 2 and second['tag_kind'] == 'annotated'
        assert second['versions']['local_config_sha256'] != first['local_config_sha256']
        stale = http.post('/api/managed/registry/preview', json=update)
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'stale_version'
        assert http.post('/api/managed/registry/preview', json={**update, 'expected_version': 2,
                                                                 'root': str(tmp_path)}
                         ).json()['detail']['code'] == 'root_immutable'
        # Unfinished work blocks changes and removals.
        job = http.post('/api/managed/projects/web/runs', json={'task_id': TASK, 'phase_id': PHASE, 'text': PLAN},
                        headers={'Idempotency-Key': 'pending'}).json()
        blocked = {**update, 'expected_version': 2, 'tag_kind': 'lightweight'}
        preview, applied = confirm(http, blocked)
        assert preview['unfinished_jobs'] == [job['id']]
        assert applied.status_code == 409 and applied.json()['detail']['code'] == 'pending_jobs'
        retire = {'action': 'retire', 'project_id': 'web', 'expected_version': 2}
        assert confirm(http, retire)[1].json()['detail']['code'] == 'pending_jobs'
        assert http.get('/api/managed/registry/projects/web').json()['unfinished_jobs'] == [job['id']]
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    assert supervisor.run_once().status == 'DONE'
    with client(migrated_database[0], tmp_path, config) as http:
        preview, applied = confirm(http, retire)
        assert preview['changes'] == [{'field': 'status', 'before': 'ACTIVE', 'after': 'RETIRED'}]
        assert applied.status_code == 200 and applied.json()['project']['status'] == 'RETIRED'
        assert http.get('/api/managed/projects/web').status_code == 404
        kept = http.get('/api/managed/runs/' + job['run_id']).json()  # readable history, no actions
        assert kept['project_id'] is None and kept['actions'] == []
        detail = http.get('/api/managed/registry/projects/web').json()
        assert [e['action'] for e in detail['history']] == ['register', 'update', 'retire']
        assert detail['history'][1]['previous_sha256'] == detail['history'][0]['row_sha256']
        again = http.post('/api/managed/registry/preview', json=register(context.root))
        assert again.json()['detail']['code'] == 'duplicate_id'
        # Logical removal: the root becomes free for another id; the previous one's history is kept.
        assert confirm(http, register(context.root, project_id='web-2'))[1].status_code == 200
    with Session(repository.engine) as session:
        assert session.scalar(select(func.count()).select_from(RegisteredProjectEventRow)) == 4


def test_newer_registry_version_quarantines_jobs_admitted_before(operator, repository, migrated_database):
    """A job admitted with the previous version is not run with the new composition."""
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root))[1].status_code == 200
        old = http.get('/api/managed/projects/web').json()['versions']
        job = http.post('/api/managed/projects/web/runs', json={'task_id': TASK, 'phase_id': PHASE, 'text': PLAN},
                        headers={'Idempotency-Key': 'old'}).json()
        # Simulates the instant between the registry commit and the runtime change: another installed version.
        registrar = config.registrar
        row = http.get('/api/managed/registry/projects/web').json()['row']
        registrar.install(registrar.compose({**row, 'tag_kind': 'annotated'}, 'registro', registry=(2, 'x' * 64)))
    supervisor = LocalSupervisor(repository, config.ports_factory, commit_factory=config.commit_factory)
    with pytest.raises(JournalError, match='differs from the frozen one'):
        supervisor.run_once()
    assert repository.get_run(job['run_id']).status == 'RECOVERY_REQUIRED'
    assert old['project_registry'] == '1' and not launches(tmp_path)


def test_restart_loads_registered_projects_and_reports_unavailable_ones(operator, migrated_database):
    context, data, folder, tmp_path = operator
    value = v3(data, [tmp_path])
    config = load_local_config(write(folder, value))
    with client(migrated_database[0], tmp_path, config) as http:
        assert confirm(http, register(context.root))[1].status_code == 200
        versions = http.get('/api/managed/projects/web').json()['versions']
    with client(migrated_database[0], tmp_path, load_local_config(write(folder, value))) as http:
        assert http.get('/api/managed/projects/web').json()['versions'] == versions
    renamed = copy.deepcopy(value)
    renamed['compositions'] = {'other': renamed['compositions'].pop('web')}
    with client(migrated_database[0], tmp_path, load_local_config(write(folder, renamed))) as http:
        assert http.get('/api/managed/projects/web').status_code == 404
        (item,) = http.get('/api/managed/registry').json()['projects']
        assert not item['available'] and 'registro.composition' in item['diagnostic']
    previous = v2(data)
    with client(migrated_database[0], tmp_path, load_local_config(write(folder, previous))) as http:
        options = http.get('/api/managed/registry').json()
        assert not options['available'] and options['format'] == 'local-config-2'
        assert [p['available'] for p in options['projects']] == [False]
        response = http.post('/api/managed/registry/preview', json=register(Path('/tmp')))
        assert response.status_code == 409 and response.json()['detail']['code'] == 'registry_unavailable'
