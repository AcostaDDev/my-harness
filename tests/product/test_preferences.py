"""P011-T007 (D166): global language preferences, own message catalogs and the visual language frozen per job.

Temporary SQLite/Git and fake agents only; no providers, services or network."""
import json
import re
import sqlite3

from alembic import command
import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from my_harness import i18n
from my_harness.cli import cli_language
from my_harness.storage.database import make_engine
from my_harness.storage.models import ManagedJobRow, ProductPreferencesRow
from my_harness.storage.preferences import (
    PreferencesChanged, PreferencesInvalid, PreferencesKeyReused, PreferencesRepository,
)
from session_client import TestClient
from test_chat import answer, chat  # noqa: F401  (fixture)
from test_managed import context, repository, submit, worker  # noqa: F401  (fixtures)
from test_managed_api import LOCAL, client, config, repo, task, url  # noqa: F401  (fixtures)
from test_phases import checkout, world  # noqa: F401  (fixtures)

PREFERENCES = '/api/managed/preferences'


def change(preferences, ui, work='en', key=None):
    version = preferences.read()['version']
    return preferences.update(expected_version=version, ui_language=ui, default_work_language=work,
                              key=key or f'{ui}-{work}-{version}')


def languages(engine, run_id):
    """Frozen pairs without the hash of the (synthetic) work language association."""
    with Session(engine) as session:
        return [{k: v for k, v in row.language_context.items() if k != 'work_language_sha256'}
                for row in session.scalars(
                    select(ManagedJobRow).where(ManagedJobRow.run_id == run_id).order_by(ManagedJobRow.id))]


# Synthetic `en` work language of tests/product/conftest.py; T008 adds it to the T007 visual capture.
WORK = {'work_language': 'en', 'work_language_source': 'migration'}


def corrupt(engine):
    """Simulates a row edited outside the service: CHECK constraints are bypassed only for this connection."""
    with engine.begin() as connection:
        connection.execute(text('PRAGMA ignore_check_constraints = ON'))
        connection.execute(text("UPDATE product_preferences SET ui_language = 'fr' WHERE id = 1"))
        connection.execute(text('PRAGMA ignore_check_constraints = OFF'))


# --- persistence, CAS and audit ------------------------------------------------------------------


def test_migration_seeds_factory_values_and_reads_never_write(repository):  # noqa: F811
    preferences = PreferencesRepository(repository)
    current = preferences.read()
    assert {k: current[k] for k in ('format', 'version', 'ui_language', 'default_work_language', 'status')} == {
        'format': 'product-preferences-1', 'version': 1, 'ui_language': 'en', 'default_work_language': 'en',
        'status': 'stored'}
    with Session(repository.engine) as session, session.begin():
        session.execute(delete(ProductPreferencesRow))
    assert preferences.read() == {'format': 'product-preferences-1', 'version': 0, 'ui_language': 'en',
                                  'default_work_language': 'en', 'updated_at': None, 'status': 'default'}
    with Session(repository.engine) as session:
        assert session.get(ProductPreferencesRow, 1) is None  # the read did not initialize anything
    created = preferences.update(expected_version=0, ui_language='es', default_work_language='en', key='first')
    assert (created['version'], created['ui_language'], created['status']) == (1, 'es', 'stored')


def test_update_is_cas_idempotent_and_audited(repository):  # noqa: F811
    preferences = PreferencesRepository(repository)
    saved = preferences.update(expected_version=1, ui_language='es', default_work_language='es', key='a')
    assert (saved['version'], saved['replayed']) == (2, False)
    assert preferences.update(expected_version=1, ui_language='es', default_work_language='es',
                              key='a') == {**saved, 'replayed': True}
    with pytest.raises(PreferencesKeyReused):
        preferences.update(expected_version=1, ui_language='en', default_work_language='es', key='a')
    with pytest.raises(PreferencesChanged):  # another window saved first
        preferences.update(expected_version=1, ui_language='en', default_work_language='en', key='b')
    for ui, work, version in (('fr', 'en', 2), ('en', 'EN', 2), ('en', 'en', -1), ('en', 'en', True)):
        with pytest.raises(ValueError):
            preferences.update(expected_version=version, ui_language=ui, default_work_language=work, key='c')
    change(preferences, 'en', 'es', key='d')
    history = preferences.history()
    assert [(e['version'], e['before']['ui_language'], e['after']['ui_language']) for e in history] == [
        (2, 'en', 'es'), (3, 'es', 'en')]
    assert history[0]['previous_sha256'] is None and history[1]['previous_sha256'] == history[0]['sha256']
    assert preferences.read()['version'] == 3


def test_migration_downgrade_refuses_to_drop_recorded_languages(migrated_database, repository):  # noqa: F811
    url, alembic_config = migrated_database
    change(PreferencesRepository(repository), 'es')
    repository.engine.dispose()
    with pytest.raises(RuntimeError, match='cannot be represented before 0024'):
        command.downgrade(alembic_config, '0023_run_projection')


# --- frozen visual language per job ---------------------------------------------------------------


def test_jobs_freeze_the_visual_language_and_continuations_keep_it(repository, context):  # noqa: F811
    preferences = PreferencesRepository(repository)
    change(preferences, 'es')
    job = submit(repository, context)
    frozen = {'format': 'language-context-1', 'ui_language': 'es', 'preferences_version': 2, **WORK}
    assert languages(repository.engine, job.run_id) == [frozen]
    change(preferences, 'en', 'es')  # pending job and default work language do not touch it
    assert languages(repository.engine, job.run_id) == [frozen]
    first, _, _, _ = worker(repository, context, [RuntimeError('Synthetic failure')])
    first.run_once()
    stopped = repository.get_run(job.run_id)
    repository.resume(job.run_id, key='retry', expected_version=stopped.version, retry_executor=True)
    assert languages(repository.engine, job.run_id) == [frozen, frozen]  # a retry is not a new interaction


def test_new_turns_capture_the_current_visual_language_without_changing_earlier_ones(world, chat):  # noqa: F811
    preferences = PreferencesRepository(world.repository)
    cid = chat.create()
    world.script(answer(text='Primera respuesta'), answer(text='Second answer'))
    change(preferences, 'es')
    turn_a = chat.say(cid, text='Primera pregunta')
    change(preferences, 'en')
    world.run()
    turn_b = chat.say(cid, text='Second question')
    world.run()
    frozen = [languages(world.repository.engine, job.run_id)[0]['ui_language'] for job in (turn_a, turn_b)]
    assert frozen == ['es', 'en']
    assert chat.get(cid)['turns'][0]['result']['result']['answer'] == 'Primera respuesta'  # original text kept


def test_new_actions_on_an_earlier_result_capture_the_current_value(world):  # noqa: F811
    change(PreferencesRepository(world.repository), 'es')
    run_id = world.accept_task()  # task job admitted in es, then its commit job in es
    assert [c['ui_language'] for c in languages(world.repository.engine, run_id)] == ['es', 'es']
    change(PreferencesRepository(world.repository), 'en')
    pid = world.create()
    job, _ = world.check(pid, {'phase_id': 'P001', 'verdict': 'NOT_READY', 'summary': 'Synthetic summary',
                               'required_actions': ['Synthetic action'], 'blocking_questions': [],
                               'exit_criteria_results': []})
    assert languages(world.repository.engine, job.run_id)[0]['ui_language'] == 'en'


def test_invalid_stored_preferences_read_as_english_and_block_admission(repository, context):  # noqa: F811
    corrupt(repository.engine)
    preferences = PreferencesRepository(repository)
    assert (preferences.read()['status'], preferences.read()['ui_language']) == ('invalid', 'en')
    with pytest.raises(PreferencesInvalid):
        submit(repository, context)
    with Session(repository.engine) as session:
        assert session.scalar(select(ManagedJobRow.id)) is None
    change(preferences, 'es')  # an explicit save repairs it
    assert submit(repository, context, key='after-repair') is not None


# --- HTTP contract and own diagnostics -------------------------------------------------------------


def test_http_preferences_contract(url, tmp_path, task):  # noqa: F811
    with client(url, tmp_path, config(task)) as http:
        current = http.get(PREFERENCES).json()
        assert (current['version'], current['ui_language'], current['status']) == (1, 'en', 'stored')
        body = {'expected_version': 1, 'ui_language': 'es', 'default_work_language': 'en'}
        assert http.put(PREFERENCES, json=body).status_code == 422  # Idempotency-Key required
        saved = http.put(PREFERENCES, json=body, headers={'Idempotency-Key': 'k1'})
        assert saved.status_code == 200 and saved.json()['version'] == 2 and not saved.json()['replayed']
        assert http.put(PREFERENCES, json=body, headers={'Idempotency-Key': 'k1'}).json()['replayed']
        stale = http.put(PREFERENCES, json={**body, 'ui_language': 'en'}, headers={'Idempotency-Key': 'k2'})
        assert stale.status_code == 409
        assert stale.json()['detail'] == {'code': 'preferences_conflict',
                                          'diagnostic': i18n.message('preferences.conflict', 'es')}
        reused = http.put(PREFERENCES, json={**body, 'expected_version': 2}, headers={'Idempotency-Key': 'k1'})
        assert reused.json()['detail']['code'] == 'idempotency_conflict'
        for invalid in ({**body, 'ui_language': 'fr'}, {**body, 'expected_version': -1}, {**body, 'project': 'x'},
                        {'expected_version': 2, 'ui_language': 'en'}):
            assert http.put(PREFERENCES, json=invalid, headers={'Idempotency-Key': 'k3'}).status_code == 422
        unguarded = http.put(PREFERENCES, json=body, headers={'Idempotency-Key': 'k4', 'X-My-Harness': ''})
        assert unguarded.status_code == 403
        job = http.post('/api/managed/projects/synthetic/runs',
                        json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': '# Plan\n'},
                        headers={'Idempotency-Key': 'run-1'})
        assert job.status_code == 202, job.text
        frozen = {k: v for k, v in job.json()['language_context'].items() if k != 'work_language_sha256'}
        assert frozen == {'format': 'language-context-1', 'ui_language': 'es', 'preferences_version': 2, **WORK}
        anonymous = TestClient(http.app, base_url=LOCAL)  # same service, no session cookie
        refused = anonymous.get(PREFERENCES)
        assert refused.status_code == 401
        assert refused.json()['detail']['diagnostic'] == i18n.message('session.required', 'es')


def test_http_admission_with_invalid_preferences_is_a_typed_conflict(url, tmp_path, task):  # noqa: F811
    engine = make_engine(url)
    corrupt(engine)
    engine.dispose()
    with client(url, tmp_path, config(task)) as http:
        assert http.get(PREFERENCES).json()['status'] == 'invalid'
        refused = http.post('/api/managed/projects/synthetic/runs',
                            json={'task_id': 'P001-T001', 'phase_id': 'P001', 'text': '# Plan\n'},
                            headers={'Idempotency-Key': 'run-1'})
        assert refused.status_code == 409
        assert refused.json()['detail'] == {'code': 'preferences_invalid',
                                            'diagnostic': i18n.message('preferences.invalid', 'en')}


# --- CLI override and catalogs ---------------------------------------------------------------------


def test_cli_language_precedence_without_writing(migrated_database, tmp_path):
    path = migrated_database[0].removeprefix('sqlite:///')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE product_preferences SET ui_language = 'es', version = 2 WHERE id = 1")
    db.close()
    before = open(path, 'rb').read()
    assert cli_language(None, path) == 'es'
    assert cli_language('en', path) == 'en'  # explicit override for this invocation only
    assert open(path, 'rb').read() == before
    assert cli_language(None, str(tmp_path / 'absent.sqlite3')) == 'en'
    assert not (tmp_path / 'absent.sqlite3').exists()
    assert cli_language(None, 'relative.sqlite3') == 'en'
    (tmp_path / 'empty.sqlite3').touch()
    assert cli_language(None, str(tmp_path / 'empty.sqlite3')) == 'en'  # no preferences table yet


def test_catalogs_share_keys_and_parameters_and_fall_back_to_english():
    base, other = i18n.catalog('en'), i18n.catalog('es')
    assert base.keys() == other.keys()
    for key, value in base.items():
        assert set(i18n.PARAMETER.findall(value)) == set(i18n.PARAMETER.findall(other[key])), key
        assert value.strip() and other[key].strip() and value != other[key], key
        assert not re.search(r'[<>]|\{[^a-z_]', value + other[key]), key  # plain text, named fields only
    assert i18n.message('cli.config_conflict', 'es', variable='X').startswith('--config y X')
    assert i18n.message('cli.config_conflict', 'fr', variable='X').startswith('--config and X')
    assert i18n.message('cli.config_conflict', 'en') == base['cli.config_conflict']  # no evaluation, field kept
    assert i18n.message('missing.key', 'es') == 'missing.key'
    assert json.loads(json.dumps(base)) == base
