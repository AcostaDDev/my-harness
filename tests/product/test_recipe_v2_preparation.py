"""P011-T020 (D168): `local-config-6` prepares new children with the v2 recipes and the child's work language.

Synthetic toolchains (the D119/D143 probes), real bounded transport, Git and SQLite; no packages, network or agents.
The v1 suites (`test_project_preparation`, `test_typescript_preparation`) keep covering `local-config-5`.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from my_harness.core.engine.journal import JournalError
from my_harness.recipes import django, django_2, typescript_web, typescript_web_2
from my_harness.services.local_config import load_local_config
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.services.project_preparation import DjangoRecipe, DjangoRecipe2, TypeScriptRecipe2
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict
from my_harness.storage.preparation import admit
from test_project_creation import select_root, request
from test_project_registry import POLICY, v3, operator  # noqa: F401
from test_local_config import setup, web, write, launches  # noqa: F401
from test_managed_api import client, git
from test_project_preparation import recipe_data as django_data
from test_typescript_preparation import define, synthetic_cache, typescript_data

FUNCTIONAL = {'django': ('config/settings.py', 'LANGUAGE_CODE = "es"'),
              'typescript': ('index.html', '<html lang="es">')}


def v6(data):
    return {**data, 'format': 'local-config-6'}


def start(operator, migrated_database, stack, fmt='local-config-6'):
    context, data, folder, tmp_path = operator
    cache = synthetic_cache(tmp_path)
    data = django_data(data, folder) if stack == 'django' else typescript_data(data, folder, cache)
    data = {**v6(data), 'format': fmt}
    if fmt in ('local-config-7', 'local-config-8'):
        from test_cli_discovery import fake_client
        for agent in data['agents'].values():
            agent['executable'] = [str(fake_client(tmp_path / 'clients', agent['provider']))]
            agent.pop('cli_version', None)
            agent['environment'].pop('PROBE_VERSION', None)
    config = load_local_config(write(folder, data))
    engine = make_engine(migrated_database[0])
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    return runtime, engine, config, tmp_path


def create(runtime, tmp_path, stack, language):
    parent = tmp_path / 'chosen'
    parent.mkdir()
    select_root(runtime.creation, parent)
    runtime.creation.confirm(request(runtime.creation, composition=stack, work_language=language), 'child')
    return runtime.project('child')


@pytest.fixture
def child(operator, migrated_database, monkeypatch, request):
    """A child from (stack, work language[, config format]), with its D088 root commit accepted."""
    stack, language, *formats = request.param
    runtime, engine, config, tmp_path = start(operator, migrated_database, stack, *formats)
    project = create(runtime, tmp_path, stack, language)
    define(runtime, config, project, monkeypatch)
    service = runtime.preparation
    if stack == 'django':
        original = service._files
        def files(root, plan):
            original(root, plan)
            # Toolchain fixture metadata, not product data or an actual dependency installation.
            (root / django_2.WORK / 'packages.json').write_text(json.dumps(django_2.PACKAGES))
        monkeypatch.setattr(service, '_files', files)
    yield service, config, migrated_database, stack, language
    runtime.stop()
    engine.dispose()
    assert not launches(tmp_path)


def shown(service, **extra):
    return service.preview('child', {'expected_version': 1, 'mode': 'offline', **extra})


def confirm(service, key='prepare', **extra):
    change = {'expected_version': 1, 'mode': 'offline', **extra}
    preview = service.preview('child', change)
    return service.confirm('child', {'change': change, 'preview_sha256': preview['preview_sha256']}, key)


def root(service):
    return service.runtime.project('child').context.root


PAIRS = [('django', 'en'), ('django', 'es'), ('typescript', 'en'), ('typescript', 'es')]


@pytest.mark.parametrize('child', PAIRS, indirect=True, ids=['-'.join(pair) for pair in PAIRS])
def test_v6_child_prepares_with_its_work_language_and_commits_the_v2_manifest(child):
    service, config, database, stack, language = child
    module = django_2 if stack == 'django' else typescript_web_2
    project = service.runtime.project('child')
    assert project.versions['project_recipe'] == module.VERSION and project.context.work_language == language
    # The composition runs with the v2 module's own profile (Django keeps the D133 formatter).
    expected = module.profile()
    if stack == 'django':
        expected = replace(expected, formatter_argv=('ruff', 'format', '--'), formatter_paths=('*.py',))
    assert project.context.profile == expected
    preview = shown(service)
    assert preview['recipe'] == module.VERSION and preview['work_language'] == language
    assert preview['recipe_sha256'] == module.fingerprint(language)
    files = {item['path']: item['content'] for item in preview['files']}
    manifest = (django_2.scaffold(language) if stack == 'django'
                else typescript_web_2.manifest('child', config.registrar.recipes['typescript-web'], language))
    assert files == manifest
    assert FUNCTIONAL[stack][1] in files[FUNCTIONAL[stack][0]]  # the child's functional language is not W or V
    ids = [step['id'] for step in preview['steps']]
    assert len(set(ids)) == len(ids) and ids[0] == 'files' and ids[-1] == 'commit'
    label = 'Django' if stack == 'django' else 'TypeScript web'
    assert preview['commit']['message'] == f'harness: prepare {label} ({module.VERSION})'
    op = confirm(service)
    assert service.run_once() == op['id']
    result = service.repository.read(op['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    receipt = result['receipt']
    assert receipt['recipe'] == module.VERSION and receipt['work_language'] == language
    assert receipt['recipe_sha256'] == module.fingerprint(language)
    assert receipt['work_language_sha256'] == preview['work_language_sha256']
    head = git(root(service), 'show', '--name-only', '--format=%s', 'HEAD').splitlines()
    assert head[0] == preview['commit']['message'] and set(filter(None, head[1:])) == set(manifest)
    probe = 'core/models.py' if stack == 'django' else 'tests/main.test.mjs'
    assert git(root(service), 'show', f'HEAD:{probe}') + '\n' == manifest[probe]
    prepared = service.runtime.project('child')
    assert 'project_environment_sha256' in prepared.versions and service.read('child')['prepared']


AUTOMATIC_CHILDREN = [(stack, language, fmt) for stack, language in PAIRS
                      for fmt in ('local-config-7', 'local-config-8')]


@pytest.mark.parametrize('child', AUTOMATIC_CHILDREN, indirect=True,
                         ids=['-'.join(values) for values in AUTOMATIC_CHILDREN])
def test_http_task_admission_rebinds_the_receipt_after_automatic_cli_resolution(child):
    """A prepared child must be usable by HTTP, whose admission forcibly recomposes the CLI clients."""
    service, config, database, _, language = child
    base = '/api/managed/projects/child'
    task = {'task_id': 'P001-T001', 'phase_id': 'P001',
            'text': (root(service) / 'docs/NEXT_STEPS.md').read_text()}
    with client(database[0], service.runtime.database.parent, config) as http:
        early = http.post(base + '/runs', json=task, headers={'Idempotency-Key': 'before-preparation'})
        assert early.status_code == 409 and early.json()['detail']['code'] == 'preparation_required'
        unprepared = service.runtime.resolve_project('child')
        with Session(service.runtime.engine) as session:
            for purpose in ('task', 'phase_check', 'phase_close'):
                with pytest.raises(Conflict, match='preparation_required'):
                    admit(session, str(unprepared.context.root), unprepared.versions, purpose)
        queued = confirm(service)
        assert service.run_once() == queued['id']
        completed = service.repository.read(queued['id'])
        assert completed['status'] == 'COMPLETED', completed['diagnostic']
        receipt = completed['receipt']
        assert http.get(base + '/preparation').json()['prepared']
        resolved = service.runtime.resolve_project('child')
        assert resolved.context.work_language == language
        with Session(service.runtime.engine) as session:
            for purpose in ('task', 'phase_check', 'phase_close'):
                admit(session, str(resolved.context.root), resolved.versions, purpose)
        response = http.post(base + '/runs', json=task, headers={'Idempotency-Key': 'after-preparation'})
        assert response.status_code == 202, response.text
        result = response.json()
        run = service.managed.get_run(result['run_id'])
        versions = json.loads(run.versions_json)
        assert versions['project_environment_sha256'] == digest(receipt)
        assert versions['recipe_config_sha256'] == receipt['recipe_config_sha256']
        assert versions['reviewer_cli_launch_sha256'] and versions['executor_cli_launch_sha256']
        assert versions['reviewer_cli'] == '0.163.0' and versions['executor_cli'] == '2.1.304'
        assert service.managed.job_language(service.managed.get_job(result['id']))['work_language'] == language
        assert run.status == 'QUEUED' and not run.history.attempts


@pytest.mark.parametrize('child', [('typescript', 'es', 'local-config-8'), ('django', 'es', 'local-config-8')],
                         indirect=True, ids=['typescript-es-v8', 'django-es-v8'])
@pytest.mark.parametrize('drift', ['recipe-config', 'protected-file', 'tool'])
def test_cli_resolution_never_admits_a_changed_preparation(child, drift):
    service, config, _, stack, _ = child
    queued = confirm(service)
    assert service.run_once() == queued['id']
    receipt = service.repository.read(queued['id'])['receipt']
    original = service.runtime.project('child')
    assert original.versions['project_environment_sha256'] == digest(receipt)
    recipe = 'typescript-web' if stack == 'typescript' else 'django'
    if drift == 'recipe-config':
        config.registrar.recipes[recipe]['timeout_seconds'] += 1
    elif drift == 'protected-file':
        path = root(service) / ('package.json' if stack == 'typescript' else 'pyproject.toml')
        path.write_text(path.read_text() + '\n')
    else:
        tool = 'node_executable' if stack == 'typescript' else 'python_executable'
        path = Path(receipt['tools'][tool]['resolved']) if stack == 'typescript' else root(service) / '.venv/bin/python'
        path.write_text(path.read_text() + '\n# Synthetic tool drift\n')
    resolved = service.runtime.resolve_project('child')
    assert resolved.context.work_language == 'es'
    if drift == 'recipe-config':
        assert 'project_environment_sha256' not in resolved.versions
        assert root(service) not in config.registrar._receipts
    with Session(service.runtime.engine) as session:
        for purpose in ('task', 'phase_check', 'phase_close'):
            with pytest.raises((Conflict, JournalError), match='preparation_required'):
                admit(session, str(resolved.context.root), resolved.versions, purpose)
    assert service.repository.read(queued['id'])['receipt'] == receipt
    assert service.runtime.project('child').versions == resolved.versions


@pytest.mark.parametrize('child', [('django', 'es')], indirect=True, ids=['django-es'])
def test_api_returns_the_typed_work_language_and_strict_payload(child):
    service, config, database, *_ = child
    with client(database[0], service.runtime.database.parent, config) as http:
        base = '/api/managed/projects/child/preparation'
        assert http.get(base).json()['recipe'] == django_2.VERSION
        preview = http.post(base + '/preview', json={'expected_version': 1, 'mode': 'offline'})
        assert preview.status_code == 200, preview.text
        assert preview.json()['work_language'] == 'es' and preview.json()['recipe_sha256'] == django_2.fingerprint('es')
        refused = http.post(base + '/preview', json={'expected_version': 1, 'mode': 'offline', 'work_language': 'en'})
        assert refused.status_code == 422


@pytest.mark.unconfirmed_work_language
@pytest.mark.parametrize('child', [('typescript', 'es')], indirect=True, ids=['typescript-es'])
def test_without_a_confirmed_work_language_preparation_is_refused_before_effects(child):
    service, *_ = child
    queued = confirm(service)
    # A row is never deleted by the product: this simulates a root that has none (the D167 gate).
    with service.managed._write() as session:
        session.execute(text('DELETE FROM project_work_languages'))
    # The confirmed intention stops before its first effect...
    assert service.run_once() == queued['id']
    stopped = service.repository.read(queued['id'])
    assert stopped['status'] == 'FAILED' and 'Work language' in stopped['diagnostic']
    assert not (root(service) / typescript_web_2.WORK).exists() and not (root(service) / 'package.json').exists()
    # ...and no new intention is planned without one.
    with pytest.raises(RegistryError) as error:
        shown(service, previous_id=queued['id'], retry_step=0)
    assert error.value.code == 'work_language_required'


@pytest.mark.parametrize('stack', ['django', 'typescript'])
def test_v5_keeps_v1_and_successors_select_v2_from_the_same_recipe_keys(operator, stack):
    context, data, folder, tmp_path = operator
    data = django_data(data, folder) if stack == 'django' else typescript_data(data, folder, synthetic_cache(tmp_path))
    target = tmp_path / 'chosen' / 'probe'
    target.mkdir(parents=True)
    item = {'id': 'probe', 'root': str(target), 'repository_trusted': True, 'policy': POLICY, 'composition': stack,
            'bootstrap_enabled': True}
    versions, profiles = {}, {}
    for fmt in ('local-config-5', 'local-config-6', 'local-config-7', 'local-config-8'):
        config = load_local_config(write(folder, {**data, 'format': fmt}))
        project, _ = config.registrar.compose(item, 'probe', registry=(1, 'x' * 64))
        versions[fmt], profiles[fmt] = project.versions, project.context.profile
    old, new = (django, django_2) if stack == 'django' else (typescript_web, typescript_web_2)
    assert versions['local-config-5']['project_recipe'] == old.VERSION
    assert versions['local-config-6']['project_recipe'] == new.VERSION
    assert versions['local-config-5']['recipe_config_sha256'] != versions['local-config-6']['recipe_config_sha256']
    assert profiles['local-config-5'].executor_instructions == old.profile().executor_instructions
    assert profiles['local-config-6'].executor_instructions == new.profile().executor_instructions
    for fmt in ('local-config-7', 'local-config-8'):
        assert versions[fmt]['project_recipe'] == versions['local-config-6']['project_recipe']
        assert versions[fmt]['recipe_config_sha256'] == versions['local-config-6']['recipe_config_sha256']
        assert profiles[fmt] == profiles['local-config-6']
    if stack == 'typescript':
        # The built-in profile stays for compositions without a recipe, also in v6.
        assert profiles['local-config-6'].junit_reports != profiles['local-config-5'].junit_reports


def test_checks_dispatch_by_stable_id_and_v1_plans_keep_their_labels(tmp_path):
    config = {'installer_executable': '/tools/uv', 'python_executable': '/tools/python', 'timeout_seconds': 300,
              'max_output_bytes': 4096, 'python_version': '3.13.1', 'installer_version': '0.9.5'}
    plan = {'config': config, 'packages': {}}
    for recipe, steps in ((DjangoRecipe, django.steps(tmp_path, config, 'offline')),
                          (DjangoRecipe2, django_2.steps(tmp_path, config, 'offline'))):
        by_step = {recipe.step(spec): spec for spec in steps}
        assert {'python-version', 'installer-version', 'installed-versions'} <= set(by_step)
        with pytest.raises(ValueError, match='Base Python'):
            recipe.check_output(by_step['python-version'], 'Python 3.12.0', plan)
        recipe.check_output(by_step['python-version'], 'Python 3.13.1\n', plan)
        assert [recipe.uncertain(spec) for spec in steps].count(True) == 1
        # Same partial/complete source checks per step, whether keyed by number (v1) or by id (v2).
        assert [recipe.source_check(spec, n) for n, spec in enumerate(steps) if spec['kind'] == 'command'] == [
            None] * 6 + [True, True] + [False] * 7
    # A v2 label changed for display never alters the dispatch.
    spec = {**django_2.steps(tmp_path, config, 'offline')[1], 'label': 'Comprobar intérprete'}
    with pytest.raises(ValueError, match='Base Python'):
        DjangoRecipe2.check_output(spec, 'Python 3.12.0', plan)
    node = {'node_version': '24.15.0', 'npm_version': '11.12.1'}
    tools = {**node, 'node_executable': '/n', 'npm_executable': '/m', 'npm_cache': '/c', 'timeout_seconds': 300,
             'max_output_bytes': 4096}
    npm = next(s for s in typescript_web_2.steps(tmp_path, tools, 'offline') if s['id'] == 'npm-version')
    with pytest.raises(ValueError, match='npm version'):
        TypeScriptRecipe2.check_output({**npm, 'label': 'x'}, '10.0.0', {'config': node})


@pytest.mark.parametrize('child', [('django', 'en')], indirect=True, ids=['django-en'])
def test_v2_recovery_keys_the_uncertain_environment_and_the_successor_on_step_ids(child, monkeypatch):
    service, *_ = child
    original, failing = service._command, {'install', 'create-environment'}
    def command(root, plan, step, journal):
        if step['spec']['id'] in failing:
            failing.discard(step['spec']['id'])
            raise ValueError('Synthetic failure, no network')
        return original(root, plan, step, journal)
    monkeypatch.setattr(service, '_command', command)
    numbers = {spec['id']: n for n, spec in enumerate(shown(service)['steps'])}
    op = confirm(service)
    service.run_once()
    failed = service.repository.read(op['id'])
    assert failed['status'] == 'FAILED' and failed['steps'][numbers['create-environment']]['status'] == 'STARTED'
    # An environment step without its receipt is uncertain: never recreated by a successor.
    with pytest.raises(RegistryError) as error:
        shown(service, previous_id=op['id'], retry_step=numbers['create-environment'])
    assert error.value.code == 'recovery_required'
    monkeypatch.setattr(DjangoRecipe2, 'uncertain', staticmethod(lambda spec: False))
    successor = confirm(service, key='retry', previous_id=op['id'], retry_step=numbers['create-environment'])
    service.run_once()
    failed = service.repository.read(successor['id'])
    assert failed['status'] == 'FAILED' and failed['steps'][numbers['install']]['status'] == 'STARTED'
    last = confirm(service, key='retry-install', previous_id=successor['id'], retry_step=numbers['install'])
    service.run_once()
    result = service.repository.read(last['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    assert result['plan']['work_language'] == 'en' and result['receipt']['work_language'] == 'en'
