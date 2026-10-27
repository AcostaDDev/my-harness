"""P011-T008 (D167): immutable work language per project and the language pair frozen per job and attempt.

Synthetic CLIs, temporary SQLite and Git checkouts; no providers, services or network. The real admission gate is
active in this module (no synthetic confirmation from conftest).
"""
from dataclasses import replace

from alembic import command
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from my_harness import i18n
from my_harness.services.local_config import LocalConfigError, load_local_config, summary
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.services.project_registry import RegistryError
from my_harness.storage import work_language
from my_harness.storage.backup import create_backup, restore_backup
from my_harness.storage.database import make_engine
from my_harness.storage.models import ManagedAttemptRow, ManagedJobRow
from my_harness.storage.preferences import PreferencesRepository
from test_local_config import launches, setup, write  # noqa: F401  (fixture)
from test_managed import context, repository, submit, worker  # noqa: F401  (fixtures)
from test_managed_api import client
from test_project_creation import change as creation_change, creation, select_root  # noqa: F401  (fixture)
from test_project_registry import confirm, operator, register, v3  # noqa: F401  (fixture)
from test_typescript_profile import PHASE, PLAN, TASK, web  # noqa: F401  (fixture)

pytestmark = pytest.mark.unconfirmed_work_language

PREFERENCES = '/api/managed/preferences'


def preferences(http, ui='en', work='en', key=None):
    version = http.get(PREFERENCES).json()['version']
    body = {'expected_version': version, 'ui_language': ui, 'default_work_language': work}
    response = http.put(PREFERENCES, json=body, headers={'Idempotency-Key': key or f'{ui}-{work}-{version}'})
    assert response.status_code == 200, response.text


def task(http, key, project='web'):
    return http.post(f'/api/managed/projects/{project}/runs', json={'task_id': TASK, 'phase_id': PHASE, 'text': PLAN},
                     headers={'Idempotency-Key': key})


def pair(value):
    return {k: v for k, v in value.items() if k != 'work_language_sha256'}


def associate(engine, root, value, source='migration'):
    with Session(engine) as session, session.begin():
        return work_language.associate(session, root=str(root), project_id='synthetic', work_language=value,
                                       source=source, confirmation={'synthetic': True},
                                       now='2026-10-23T00:00:00.000000+00:00')[0]


# --- registration -----------------------------------------------------------------------------------


def test_registration_fixes_the_work_language_once(operator, migrated_database):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [tmp_path])))
    with client(migrated_database[0], tmp_path, config) as http:
        missing = http.post('/api/managed/registry/preview', json=register(context.root, work_language=None))
        assert missing.status_code == 422 and missing.json()['detail']['code'] == 'work_language_required'
        preferences(http, work='es')  # the default only initializes the choice; the body carries the value
        shown = http.post('/api/managed/registry/preview', json=register(context.root)).json()
        assert shown['work_language'] == {'work_language': 'en', 'source': 'registration',
                                          'default_work_language': 'es', 'preferences_version': 2, 'existing': None}
        preferences(http, work='en')  # a default changed after the preview never replaces the chosen value
        request = {'change': register(context.root), 'preview_sha256': shown['preview_sha256'],
                   'trust_root': str(context.root)}
        assert http.post('/api/managed/registry/apply', json=request).status_code == 200
        project = http.get('/api/managed/projects/web').json()
        work = project['work_language']
        assert (work['work_language'], work['source'], work['project_id']) == ('en', 'registration', 'web')
        assert work['confirmation']['preview_sha256'] == shown['preview_sha256']
        assert (work['confirmation']['default_work_language'], work['confirmation']['preferences_version']) == ('en', 3)
        assert http.get('/api/managed/registry').json()['projects'][0]['work_language'] == work
        assert http.get('/api/managed/registry/projects/web').json()['work_language'] == work
        # Settings only show it: an update or retirement that names it is refused before any change.
        update = {'action': 'update', 'project_id': 'web', 'expected_version': 1, 'composition': 'web',
                  'policy': register(context.root)['policy']}
        refused = http.post('/api/managed/registry/preview', json={**update, 'work_language': 'es'})
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'work_language_immutable'
        assert http.post('/api/managed/registry/preview', json=update).status_code == 200
        # Retiring and registering the same root again never chooses another work language.
        retire = {'action': 'retire', 'project_id': 'web', 'expected_version': 1}
        preview = http.post('/api/managed/registry/preview', json=retire).json()
        applied = http.post('/api/managed/registry/apply', json={'change': retire,
                                                                 'preview_sha256': preview['preview_sha256']})
        assert applied.status_code == 200, applied.text
        other = register(context.root, project_id='again', work_language='es')
        refused = http.post('/api/managed/registry/preview', json=other)
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'work_language_immutable'
        again, applied = confirm(http, register(context.root, project_id='again'))
        assert applied.status_code == 200 and again['work_language']['existing'] == work
        assert http.get('/api/managed/projects/again').json()['work_language'] == work  # the original row
        # Visual es / work en: the job freezes both, with the association's provenance.
        preferences(http, ui='es')
        job = task(http, 'first', 'again')
        assert job.status_code == 202, job.text
        assert job.json()['language_context'] == {
            'format': 'language-context-1', 'ui_language': 'es', 'preferences_version': 4, 'work_language': 'en',
            'work_language_source': 'registration', 'work_language_sha256': work['sha256']}


# --- admission gate and the four combinations ---------------------------------------------------------


def test_unconfirmed_roots_admit_no_new_work_and_continuations_keep_their_pair(repository, context):  # noqa: F811
    with pytest.raises(work_language.WorkLanguageRequired, match='no confirmed work language'):
        submit(repository, context)
    with Session(repository.engine) as session:
        assert session.scalar(select(ManagedJobRow.id)) is None
    associate(repository.engine, context.root, 'es')
    job = submit(repository, context)
    first, _, _, _ = worker(repository, context, [RuntimeError('Synthetic failure')])
    first.run_once()
    stopped = repository.get_run(job.run_id)
    PreferencesRepository(repository).update(expected_version=1, ui_language='es', default_work_language='en',
                                             key='visual-es')
    repository.resume(job.run_id, key='retry', expected_version=stopped.version)
    with Session(repository.engine) as session:
        jobs = session.scalars(select(ManagedJobRow).order_by(ManagedJobRow.id)).all()
        attempts = session.scalars(select(ManagedAttemptRow)).all()
        frozen = jobs[0].language_context
        assert pair(frozen) == {'format': 'language-context-1', 'ui_language': 'en', 'preferences_version': 1,
                                'work_language': 'es', 'work_language_source': 'migration'}
        assert jobs[1].language_context == frozen  # a continuation is not a new interaction
        assert attempts and all(row.language_context == frozen for row in attempts)  # copied into each attempt


@pytest.mark.parametrize('ui, work', [('en', 'en'), ('en', 'es'), ('es', 'en'), ('es', 'es')])
def test_four_visual_and_work_combinations(repository, context, ui, work):  # noqa: F811
    associate(repository.engine, context.root, work)
    preferences_repository = PreferencesRepository(repository)
    preferences_repository.update(expected_version=1, ui_language=ui, default_work_language='es' if work == 'en' else 'en',
                                  key='change')
    job = submit(repository, context)
    with Session(repository.engine) as session:
        frozen = session.get(ManagedJobRow, job.id).language_context
    assert (frozen['ui_language'], frozen['work_language']) == (ui, work)
    # Changing both globals afterwards changes neither the pending job nor the project's work language.
    preferences_repository.update(expected_version=2, ui_language='es' if ui == 'en' else 'en',
                                  default_work_language=work, key='again')
    with Session(repository.engine) as session:
        assert session.get(ManagedJobRow, job.id).language_context == frozen
    assert work_language.read(repository.engine, context.root)['work_language'] == work


def test_a_stale_context_with_another_work_language_is_refused(repository, context):  # noqa: F811
    associate(repository.engine, context.root, 'en')
    with pytest.raises(work_language.Conflict, match='confirmed work language'):
        submit(repository, replace(context, work_language='es'))
    with pytest.raises(work_language.WorkLanguageImmutable):
        associate(repository.engine, context.root, 'es')
    assert submit(repository, replace(context, work_language='en')) is not None


# --- explicit confirmation for projects without one ----------------------------------------------------


def test_projects_without_a_work_language_confirm_it_explicitly(operator, migrated_database):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v3(data, [], toml_project=True)))
    with client(migrated_database[0], tmp_path, config) as http:
        preferences(http, ui='es')
        assert http.get('/api/managed/projects/operator').json()['work_language'] is None
        refused = task(http, 'before', 'operator')
        assert refused.status_code == 409 and refused.json()['detail'] == {
            'code': 'work_language_required', 'diagnostic': i18n.message('work_language.unconfirmed', 'es')}
        url = '/api/managed/projects/operator/work-language'
        invalid = http.post(url + '/preview', json={'work_language': 'fr'})
        assert invalid.status_code == 422
        shown = http.post(url + '/preview', json={'work_language': 'es'}).json()
        assert shown['files_preserved'] and shown['root'] == str(context.root) and shown['unfinished_jobs'] == []
        assert shown['work_language']['existing'] is None and shown['work_language']['source'] == 'migration'
        body = {'change': {'work_language': 'es'}, 'preview_sha256': shown['preview_sha256'], 'reason': 'Spanish docs'}
        assert http.post(url, json={**body, 'reason': ''}).status_code == 422
        stale = http.post(url, json={**body, 'preview_sha256': '0' * 64})
        assert stale.status_code == 409 and stale.json()['detail']['code'] == 'preview_changed'
        applied = http.post(url, json=body)
        assert applied.status_code == 200 and applied.json()['replayed'] is False
        work = applied.json()['project']['work_language']
        assert (work['work_language'], work['source'], work['confirmation']['reason']) == ('es', 'migration', 'Spanish docs')
        assert http.post(url, json=body).json() == {**applied.json(), 'replayed': True}
        again = http.post(url + '/preview', json={'work_language': 'en'})
        assert again.status_code == 409 and again.json()['detail']['code'] == 'work_language_immutable'
        job = task(http, 'after', 'operator')
        assert job.status_code == 202 and job.json()['language_context']['work_language'] == 'es'
    with client(migrated_database[0], tmp_path, config) as http:  # restart: SQLite rules
        assert http.get('/api/managed/projects/operator').json()['work_language'] == work


# --- local-config-6 -----------------------------------------------------------------------------------


def v6(data, value='es', **changes):
    config = v3(data, [], toml_project=True)
    config['format'] = 'local-config-6'
    if value is not None:
        config['projects'][0]['work_language'] = value
    config['projects'][0].update(changes)
    return config


def test_local_config_6_declares_the_work_language_and_sqlite_rules(operator, migrated_database):
    context, data, folder, tmp_path = operator
    config = load_local_config(write(folder, v6(data)))
    assert config.projects[0].context.work_language == 'es'  # loading is free of effects
    assert summary(config)['projects'][0]['work_language'] == 'es'
    assert work_language.read(make_engine(migrated_database[0]), context.root) is None
    with client(migrated_database[0], tmp_path, config) as http:
        work = http.get('/api/managed/projects/operator').json()['work_language']
        assert (work['work_language'], work['source']) == ('es', 'toml')
        assert work['confirmation']['local_config'] == 'local-config-6'
        assert task(http, 'toml', 'operator').json()['language_context']['work_language'] == 'es'
    changed = load_local_config(write(folder, v6(data, 'en')))
    engine = make_engine(migrated_database[0])
    runtime = ManagedRuntime(engine, changed)
    with pytest.raises(ValueError, match='never changes|does not change'):
        runtime.start()
    engine.dispose()
    # Without the key the project reads the confirmed value; v1–v5 keep their keys and v6 its own checks.
    undeclared = load_local_config(write(folder, v6(data, None)))
    with client(migrated_database[0], tmp_path, undeclared) as http:
        assert http.get('/api/managed/projects/operator').json()['work_language'] == work
    with pytest.raises(LocalConfigError, match='work_language'):
        load_local_config(write(folder, v6(data, 'fr')))
    previous = v6(data)
    previous['format'] = 'local-config-5'
    with pytest.raises(LocalConfigError, match='work_language'):
        load_local_config(write(folder, previous))
    # P011-T020 (D168): v6 admits `[recipes]` (the v2 recipes; covered in test_recipe_v2_preparation).
    assert load_local_config(write(folder, {**v6(data), 'recipes': {}})).registrar.recipes == {}


# --- creation ------------------------------------------------------------------------------------------


def test_creation_seals_the_work_language_and_registers_it(creation):  # noqa: F811
    service, parent, config, url = creation
    select_root(service, parent)
    body = creation_change(service, work_language=None)
    body.pop('work_language')
    with pytest.raises(RegistryError) as error:
        service.preview(body)
    assert error.value.code == 'work_language_required'
    body = creation_change(service, work_language='es')
    shown = service.preview(body)
    assert shown['contract'] == 'project-creation-2' and shown['work_language']['work_language'] == 'es'
    assert shown['work_language_seal'] == {'work_language': 'es', 'existing_sha256': None}
    result = service.confirm({'change': body, 'preview_sha256': shown['preview_sha256'],
                              'trust_root': shown['target']}, 'create')
    assert result['status'] == 'REGISTERED'
    work = work_language.read(service.runtime.engine, shown['target'])
    assert (work['work_language'], work['source'], work['project_id']) == ('es', 'creation', 'child')
    assert work['confirmation']['preview_sha256'] == shown['preview_sha256']
    assert service.runtime.project('child').context.work_language == 'es'


# --- persistence ---------------------------------------------------------------------------------------


def test_backup_keeps_the_association_and_downgrade_refuses_to_drop_it(repository, context, migrated_database,  # noqa: F811
                                                                         tmp_path):
    database = migrated_database[0].removeprefix('sqlite:///')
    command.downgrade(migrated_database[1], '0024_product_preferences')  # nothing confirmed yet: lossless
    command.upgrade(migrated_database[1], 'head')
    saved = associate(repository.engine, context.root, 'es')
    create_backup(database, tmp_path / 'backup', writers_stopped=True)
    restore_backup(tmp_path / 'backup', tmp_path / 'restored')
    restored = make_engine(f"sqlite:///{tmp_path / 'restored' / 'state.sqlite3'}")
    try:
        assert work_language.read(restored, context.root) == saved
    finally:
        restored.dispose()
    with pytest.raises(RuntimeError, match='Confirmed work languages'):
        command.downgrade(migrated_database[1], '0024_product_preferences')
    assert work_language.read(repository.engine, context.root) == saved
