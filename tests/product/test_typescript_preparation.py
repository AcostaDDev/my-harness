"""P010-T002 (D142): `typescript-web-recipe-1` with synthetic node/npm, real bounded transport, Git and SQLite.

The default toolchain and npm cache are synthetic. The journey's real variant needs an explicitly populated cache
(HARNESS_TEST_TYPESCRIPT_NPM_CACHE) and the installed node/npm; it runs offline and never downloads packages.
"""
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from sqlalchemy.orm import Session

from my_harness.adapters.preparation import verify_receipt
from my_harness.core.engine.journal import JournalError
from my_harness.recipes import django, typescript_web
from my_harness.services.local_config import LocalConfigError, load_local_config
from my_harness.services.managed import LocalSupervisor
from my_harness.services.managed_runtime import ManagedRuntime
from my_harness.services.project_registry import RegistryError, digest
from my_harness.storage.database import make_engine
from my_harness.storage.managed import Conflict
from my_harness.storage.models import RegisteredProjectRow
from test_definition import World, ready, DRAFTS, answer
import test_definition
from test_project_creation import select_root, request
from test_project_registry import POLICY, v3, operator  # noqa: F401
from test_local_config import setup, web, write, launches  # noqa: F401
from test_managed_api import Ports, client, git
from test_project_agents import selection, v5
from test_project_preparation import recipe_data as django_data

FIXTURE_LOCK = Path(__file__).resolve().parents[1] / 'fixtures/typescript_web/package-lock.json'
MANIFEST = ['.gitignore', 'index.html', 'package-lock.json', 'package.json', 'scripts/build.mjs', 'scripts/test.mjs',
            'src/main.ts', 'tests/main.test.mjs', 'tsconfig.json']
PROTECTED = {'.gitignore', 'package-lock.json', 'package.json', 'scripts/build.mjs', 'scripts/test.mjs',
             'tests/main.test.mjs', 'tsconfig.json'}
INSTALL = 3


def typescript_data(data, folder, cache, *, real=False, allow_network=False):
    data = v3(data, [], bootstrap=True)
    data['format'] = 'local-config-5'
    if real:
        node, npm = (shutil.which(name) for name in ('node', 'npm'))
        versions = [subprocess.run([tool, '--version'], check=True, capture_output=True, text=True).stdout.strip()
                    for tool in (node, npm)]
        versions[0] = versions[0].removeprefix('v')
    else:
        source = Path(__file__).with_name('typescript_preparation_probe.py').read_text()
        for name in ('synthetic-node', 'synthetic-npm'):
            tool = folder / name
            tool.write_text('#!' + sys.executable + '\n' + source)
            tool.chmod(0o700)
        node, npm, versions = str(folder / 'synthetic-node'), str(folder / 'synthetic-npm'), ['24.15.0', '11.12.1']
    data['recipes'] = {'typescript-web': {'node_executable': node, 'node_version': versions[0],
        'npm_executable': npm, 'npm_version': versions[1], 'npm_cache': str(cache),
        'timeout_seconds': 120, 'max_output_bytes': 65536, 'allow_network': allow_network}}
    data['compositions']['typescript'] = {'profile': 'typescript-web', 'recipe': 'typescript-web',
        'executables': {'node': node, 'npm': npm},
        'environment': {**data['compositions']['web']['environment'], 'npm_config_cache': str(cache)},
        'authorize_profile_commands': True}
    return data


def synthetic_cache(tmp_path):
    cache = tmp_path / 'npm-cache'
    (cache / '_cacache').mkdir(parents=True)
    (cache / '_cacache/typescript-5.9.3').write_text('synthetic cached tarball')
    return cache


def calls(cache):
    return [json.loads(line) for line in (cache / 'probe.jsonl').read_text().splitlines()]


def drafts():
    result = dict(DRAFTS)
    result['docs/NEXT_STEPS.md'] = result['docs/NEXT_STEPS.md'].replace('`app/**`', '`src/`').replace(
        '`test-runner check`', '`npm run test`')
    return result


def child(runtime, tmp_path, composition='typescript'):
    parent = tmp_path / 'chosen'
    parent.mkdir()
    select_root(runtime.creation, parent)
    runtime.creation.confirm(request(runtime.creation, composition=composition), 'child')
    return runtime.project('child')


def define(runtime, config, project, monkeypatch):
    ports = Ports()
    writer = config.commit_factory(project.context, project.versions)
    worker = LocalSupervisor(runtime.repository, lambda c, v: (ports.agents, ports.runner, ports._workspace(c)),
                             commit_factory=lambda c, v: writer)
    world = World(project.context, runtime.repository, writer, worker, ports)
    monkeypatch.setattr(test_definition, 'VERSIONS', dict(project.versions))
    monkeypatch.setattr(test_definition, 'DRAFTS', drafts())
    world.accept(ready(world))
    assert worker.run_once().status == 'DONE'


@pytest.fixture
def preparation(operator, migrated_database, monkeypatch):
    context, data, folder, tmp_path = operator
    cache = synthetic_cache(tmp_path)
    config = load_local_config(write(folder, typescript_data(data, folder, cache)))
    engine = make_engine(migrated_database[0])
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    project = child(runtime, tmp_path)
    define(runtime, config, project, monkeypatch)
    yield runtime.preparation, config, migrated_database, folder, cache
    runtime.stop()
    engine.dispose()
    assert not launches(tmp_path)


def shown(service, **extra):
    return service.preview('child', {'expected_version': 1, 'mode': 'offline', **extra})


def confirm(service, key='prepare', preview=None, **extra):
    change = {'expected_version': 1, 'mode': 'offline', **extra}
    preview = preview or service.preview('child', change)
    return service.confirm('child', {'change': change, 'preview_sha256': preview['preview_sha256']}, key)


def root(service):
    return service.runtime.project('child').context.root


def complete(service):
    op = confirm(service)
    assert service.run_once() == op['id']
    result = service.repository.read(op['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    return result


def test_preview_shows_the_exact_manifest_steps_and_lock_without_tools_or_writes(preparation):
    service, config, _, _, cache = preparation
    project = service.runtime.project('child')
    assert project.versions['project_recipe'] == typescript_web.VERSION
    assert 'project_environment_sha256' not in project.versions
    before = sorted(root(service).rglob('*'))
    preview = shown(service)
    assert preview == shown(service) and sorted(root(service).rglob('*')) == before
    assert not (cache / 'probe.jsonl').exists()
    assert preview['recipe'] == typescript_web.VERSION and 'templates' not in preview and 'packages' not in preview
    files = {item['path']: item['content'] for item in preview['files']}
    assert sorted(files) == MANIFEST
    package = json.loads(files['package.json'])
    assert package['name'] == 'child' and package['private'] and package['type'] == 'module'
    assert package['engines'] == {'node': '24.15.0', 'npm': '11.12.1'}
    assert package['devDependencies'] == {'typescript': '5.9.3'}
    assert set(package['scripts']) == {'check', 'test', 'build'}
    lock, fixture = json.loads(files['package-lock.json']), json.loads(FIXTURE_LOCK.read_text())
    assert lock['packages']['node_modules/typescript'] == fixture['packages']['node_modules/typescript']
    assert lock['packages']['']['engines'] == package['engines'] and lock['name'] == 'child'
    assert preview['lock_sha256'] == digest_text(files['package-lock.json'])
    assert '.harness-preparation/' in files['.gitignore'] and 'node_modules/' in files['.gitignore']
    labels = [step['label'] for step in preview['steps']]
    assert labels == ['Manifiesto empaquetado y entorno local de procesos', 'Verificar Node', 'Verificar npm',
                      'Instalar dependencias fijadas del lock (sin scripts)', 'Validar: npm run check',
                      'Validar: npm run test', 'Validar: npm run build', 'Commit técnico y recibo de preparación']
    install = preview['steps'][INSTALL]
    assert install['argv'][1:] == ['ci', '--ignore-scripts', '--no-audit', '--no-fund', '--offline']
    environment = install['environment']
    assert environment['npm_config_cache'] == str(cache) and environment['npm_config_engine_strict'] == 'true'
    assert environment['npm_config_registry'] == typescript_web.REGISTRY and environment['npm_config_fetch_retries'] == '0'
    assert environment['HOME'].startswith(str(root(service) / typescript_web.WORK))
    assert environment['npm_config_userconfig'] != environment['npm_config_globalconfig']
    assert preview['network'] == {'enabled': False, 'registry': typescript_web.REGISTRY, 'cache': str(cache),
                                  'automatic_retry': False, 'notice': preview['network']['notice']}
    assert set(preview['tool_files']) == {'node_executable', 'npm_executable'}
    assert preview['commit']['message'] == 'harness: prepare TypeScript web (typescript-web-recipe-1)'
    with pytest.raises(Conflict, match='preparation_required'):
        service.managed.submit(project.context, 'P001-T001', 'P001', 'synthetic', key='task',
                               versions=dict(project.versions))
    with pytest.raises(RegistryError) as error:
        shown(service, mode='network')
    assert error.value.code == 'network_not_allowed'
    assert not (root(service) / typescript_web.WORK).exists()


def digest_text(value):
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


def test_technical_commit_receipt_restart_and_drift_of_manifest_or_tools(preparation):
    service, config, database, folder, cache = preparation
    document_head = git(root(service), 'rev-parse', 'HEAD')
    documents = set(git(root(service), 'ls-files').splitlines())
    preview = shown(service)
    queued = confirm(service, preview=preview)
    assert confirm(service, preview=preview) == queued
    service.run_once()
    op = service.repository.read(queued['id'])
    assert op['status'] == 'COMPLETED', op['diagnostic']
    assert op['receipt']['commit'] == git(root(service), 'rev-parse', 'HEAD') != document_head
    assert git(root(service), 'rev-parse', 'HEAD^') == document_head
    assert git(root(service), 'status', '--porcelain') == ''
    assert set(git(root(service), 'ls-files').splitlines()) == documents | set(MANIFEST)
    assert (root(service) / 'node_modules/.bin/tsc').is_symlink() and (root(service) / 'dist/main.js').exists()
    assert not git(root(service), 'ls-files', 'node_modules', '.build', 'dist', '.local', typescript_web.WORK)
    receipt = op['receipt']
    assert set(receipt['protected_files']) == PROTECTED and 'environment' not in receipt
    assert set(receipt['tools']) == {'node_executable', 'npm_executable'}
    junit = [s['evidence']['junit'] for s in op['steps'] if 'junit' in (s['evidence'] or {})]
    assert len(junit) == 1 and junit[0]['status'] == 'complete'
    assert [(name, argv[:1]) for name, argv, _ in calls(cache)] == [
        ('synthetic-node', ['--version']), ('synthetic-npm', ['--version']), ('synthetic-npm', ['ci']),
        ('synthetic-npm', ['run']), ('synthetic-npm', ['run']), ('synthetic-npm', ['run'])]
    verify_receipt(root(service), receipt)
    assert service.read('child')['prepared'] and service.read('child')['recipe'] == typescript_web.VERSION
    assert service.runtime.project('child').versions['project_environment_sha256'] == digest(receipt)
    engine = make_engine(database[0])
    restarted = ManagedRuntime(engine, config)
    restarted.start()
    try:
        assert restarted.preparation.read('child')['prepared']
        assert restarted.preparation.run_once() is None
    finally:
        restarted.stop(); engine.dispose()
    # node_modules is not frozen: the profile reinstalls it before every task.
    shutil.rmtree(root(service) / 'node_modules')
    verify_receipt(root(service), receipt)
    project = service.runtime.project('child')
    assert service.managed.submit(project.context, 'P001-T001', 'P001', 'synthetic', key='prepared',
                                  versions=dict(project.versions)).status == 'QUEUED'
    tool = folder / 'synthetic-npm'
    original = tool.read_text()
    tool.write_text(original + '\n# changed bytes\n')
    with pytest.raises(JournalError, match='preparation_required'):
        verify_receipt(root(service), receipt)
    tool.write_text(original)
    (root(service) / 'package.json').write_text('{"name": "foreign"}\n')
    with pytest.raises(JournalError, match='preparation_required'):
        verify_receipt(root(service), receipt)
    assert not service.read('child')['prepared']
    runner = config.ports_factory(project.context, project.versions)[1]
    with pytest.raises(JournalError, match='preparation_required'):
        runner.run_managed(project.context, project.context.profile.validations[0], 'after-drift')


def test_offline_cache_miss_fails_without_network_and_an_explicit_successor_completes(preparation):
    service, _, _, _, cache = preparation
    (cache / '_cacache/typescript-5.9.3').unlink()
    op = confirm(service)
    service.run_once()
    failed = service.repository.read(op['id'])
    assert failed['status'] == 'FAILED' and failed['steps'][INSTALL]['status'] == 'STARTED'
    assert 'Instalar' in failed['diagnostic']
    assert not (root(service) / 'node_modules').exists() and not (cache / '_cacache/typescript-5.9.3').exists()
    installs = [argv for name, argv, _ in calls(cache) if argv[:1] == ['ci']]
    assert installs == [['ci', '--ignore-scripts', '--no-audit', '--no-fund', '--offline']]
    assert service.run_once() is None
    with pytest.raises(RegistryError):
        shown(service, previous_id=op['id'], retry_step=INSTALL + 1)
    (cache / '_cacache/typescript-5.9.3').write_text('synthetic cache populated by the operator')
    successor = confirm(service, key='explicit-retry', previous_id=op['id'], retry_step=INSTALL)
    service.run_once()
    result = service.repository.read(successor['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    assert service.repository.read(op['id'])['steps'][INSTALL]['status'] == 'STARTED'
    assert sum(argv == ['--version'] for _, argv, _ in calls(cache)) == 2  # node and npm, once each
    assert sum(argv[:1] == ['ci'] for _, argv, _ in calls(cache)) == 2


def test_partial_install_bytes_require_external_resolution_and_are_never_deleted(preparation):
    service, _, _, _, cache = preparation
    (cache / 'partial').write_text('synthetic interrupted extraction')
    op = confirm(service)
    service.run_once()
    assert service.repository.read(op['id'])['status'] == 'FAILED'
    (cache / 'partial').unlink()
    with pytest.raises(RegistryError, match='environment') as error:
        shown(service, previous_id=op['id'], retry_step=INSTALL)
    assert error.value.code == 'recovery_required'
    assert (root(service) / 'node_modules/typescript/partial').exists()


@pytest.mark.parametrize('step', [1, 2, INSTALL, 4, 5, 6])
def test_interruption_before_a_command_retries_only_that_step(preparation, monkeypatch, step):
    service, _, _, _, cache = preparation
    original, failed = service._command, []
    def command(root, plan, spec, journal):
        if spec['number'] == step and not failed:
            failed.append(step)
            raise ValueError('Synthetic interruption before the process started')
        return original(root, plan, spec, journal)
    monkeypatch.setattr(service, '_command', command)
    op = confirm(service)
    service.run_once()
    assert service.repository.read(op['id'])['status'] == 'FAILED'
    successor = confirm(service, key='retry', previous_id=op['id'], retry_step=step)
    service.run_once()
    result = service.repository.read(successor['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    observed = [(name, argv) for name, argv, _ in calls(cache)]
    assert len(observed) == len(set(map(json.dumps, observed))) == 6  # every command ran exactly once


def test_install_that_ran_without_its_step_receipt_is_not_repeated(preparation, monkeypatch):
    service, _, _, _, cache = preparation
    original = service._command
    def lost(root, plan, spec, journal):
        result = original(root, plan, spec, journal)
        if spec['number'] == INSTALL:
            raise ValueError('Synthetic crash after npm ci, before its checkpoint')
        return result
    monkeypatch.setattr(service, '_command', lost)
    op = confirm(service)
    service.run_once()
    assert service.repository.read(op['id'])['status'] == 'FAILED'
    with pytest.raises(RegistryError, match='environment'):
        shown(service, previous_id=op['id'], retry_step=INSTALL)
    assert (root(service) / 'node_modules/typescript/package.json').exists()


def test_interrupted_file_step_retries_only_from_the_initial_workspace(preparation, monkeypatch):
    service, *_ = preparation
    original = service._files
    def interrupted(root, plan):
        raise ValueError('Synthetic interruption before any write')
    monkeypatch.setattr(service, '_files', interrupted)
    op = confirm(service)
    service.run_once()
    assert service.repository.read(op['id'])['status'] == 'FAILED'
    monkeypatch.setattr(service, '_files', original)
    successor = confirm(service, key='files-retry', previous_id=op['id'], retry_step=0)
    service.run_once()
    assert service.repository.read(successor['id'])['status'] == 'COMPLETED'


def test_partial_file_step_is_not_adopted(preparation, monkeypatch):
    service, *_ = preparation
    original = service._files
    def partial(root, plan):
        original(root, plan)
        raise ValueError('Synthetic crash after writing the manifest')
    monkeypatch.setattr(service, '_files', partial)
    op = confirm(service)
    service.run_once()
    with pytest.raises(RegistryError) as error:
        shown(service, previous_id=op['id'], retry_step=0)
    assert error.value.code == 'recovery_required'
    assert (root(service) / 'package.json').exists()


def test_commit_adoption_crash_reconciles_the_same_commit_without_commands(preparation, monkeypatch):
    service, _, _, _, cache = preparation
    original = service._commit
    def crash(*args):
        original(*args)
        raise ValueError('Synthetic lost SQLite adoption after commit')
    monkeypatch.setattr(service, '_commit', crash)
    op = confirm(service)
    service.run_once()
    failed = service.repository.read(op['id'])
    assert failed['status'] == 'FAILED'
    head, count = git(root(service), 'rev-parse', 'HEAD'), len(calls(cache))
    monkeypatch.setattr(service, '_commit', original)
    successor = confirm(service, key='reconcile', previous_id=op['id'], retry_step=len(failed['steps']) - 1)
    service.run_once()
    result = service.repository.read(successor['id'])
    assert result['status'] == 'COMPLETED', result['diagnostic']
    assert git(root(service), 'rev-parse', 'HEAD') == head and len(calls(cache)) == count


def test_foreign_source_before_commands_never_commits(preparation, monkeypatch):
    service, _, _, _, cache = preparation
    initial = git(root(service), 'rev-parse', 'HEAD')
    original = service._files
    def files(root, plan):
        original(root, plan)
        (root / 'src/extra.ts').write_text('export const foreign = 1;\n')
    monkeypatch.setattr(service, '_files', files)
    op = confirm(service)
    service.run_once()
    failed = service.repository.read(op['id'])
    assert failed['status'] == 'FAILED' and failed['receipt'] is None and 'Foreign' in failed['diagnostic']
    assert not (cache / 'probe.jsonl').exists()
    assert git(root(service), 'rev-parse', 'HEAD') == initial


def test_failed_junit_behind_a_success_exit_never_commits(preparation):
    service, _, _, _, cache = preparation
    initial = git(root(service), 'rev-parse', 'HEAD')
    (cache / 'bad-junit').write_text('synthetic failure marker')
    op = confirm(service)
    service.run_once()
    failed = service.repository.read(op['id'])
    assert failed['status'] == 'FAILED' and 'JUnit' in failed['diagnostic'] and failed['receipt'] is None
    assert git(root(service), 'rev-parse', 'HEAD') == initial


@pytest.mark.parametrize('path', ['node_modules', '.harness-preparation', 'package.json', 'src', 'dist'])
def test_existing_targets_or_symlinks_are_never_adopted(preparation, path):
    service, *_ = preparation
    target = root(service) / path
    target.symlink_to(root(service) / 'missing')
    with pytest.raises((RegistryError, ValueError)):
        shown(service)
    assert target.is_symlink()


def test_ignored_manifest_target_is_refused(preparation):
    service, *_ = preparation
    (root(service) / '.git/info').mkdir(exist_ok=True)
    (root(service) / '.git/info/exclude').write_text('scripts/\n')
    with pytest.raises(RegistryError) as error:
        shown(service)
    assert error.value.code == 'target_ignored'


def test_only_children_created_by_the_service_are_eligible(preparation):
    service, *_ = preparation
    with service.managed._write() as session:
        session.get(RegisteredProjectRow, 'child').creation_id = None
    with pytest.raises(RegistryError) as error:
        shown(service)
    assert error.value.code == 'recipe_unavailable'


def test_network_requires_the_operator_ceiling_and_the_explicit_choice(operator, migrated_database, monkeypatch):
    context, data, folder, tmp_path = operator
    cache = synthetic_cache(tmp_path)
    (cache / '_cacache/typescript-5.9.3').unlink()
    config = load_local_config(write(folder, typescript_data(data, folder, cache, allow_network=True)))
    engine = make_engine(migrated_database[0])
    runtime = ManagedRuntime(engine, config)
    runtime.start()
    try:
        project = child(runtime, tmp_path)
        define(runtime, config, project, monkeypatch)
        service = runtime.preparation
        offline = shown(service)
        assert '--offline' in offline['steps'][INSTALL]['argv'] and not offline['network']['enabled']
        network = shown(service, mode='network')
        assert '--offline' not in network['steps'][INSTALL]['argv'] and network['network']['enabled']
        assert 'caché' in network['network']['notice'] and network['network']['registry'] == typescript_web.REGISTRY
        op = confirm(service, mode='network')
        service.run_once()
        assert service.repository.read(op['id'])['status'] == 'COMPLETED'
        assert (cache / '_cacache/typescript-5.9.3').exists()
    finally:
        runtime.stop(); engine.dispose()


def test_api_exposes_the_recipe_and_keeps_the_strict_payload(preparation):
    service, config, database, *_ = preparation
    with client(database[0], service.runtime.database.parent, config) as http:
        base = '/api/managed/projects/child/preparation'
        read = http.get(base)
        assert read.status_code == 200 and read.json()['recipe'] == typescript_web.VERSION
        assert not read.json()['prepared']
        body = {'expected_version': 1, 'mode': 'offline'}
        assert http.post(base + '/preview', json={**body, 'argv': ['arbitrary']}).status_code == 422
        preview = http.post(base + '/preview', json=body)
        assert preview.status_code == 200, preview.text
        assert preview.json()['recipe'] == typescript_web.VERSION


@pytest.mark.parametrize('change', ['v4', 'unknown-key', 'loose-version', 'cache-in-state', 'cache-missing',
                                    'composition-cache', 'composition-tool', 'composition-profile', 'undeclared',
                                    'shell'])
def test_recipe_configuration_rejects_untyped_or_unavailable_authority(operator, change):
    _, data, folder, tmp_path = operator
    raw = typescript_data(data, folder, synthetic_cache(tmp_path))
    recipe, composition = raw['recipes']['typescript-web'], raw['compositions']['typescript']
    if change == 'v4': raw['format'] = 'local-config-4'
    elif change == 'unknown-key': recipe['arbitrary_shell'] = 'anything'
    elif change == 'loose-version': recipe['node_version'] = '24'
    elif change == 'cache-in-state':
        (Path(raw['service']['state_dir']) / 'cache').mkdir()
        recipe['npm_cache'] = composition['environment']['npm_config_cache'] = raw['service']['state_dir'] + '/cache'
    elif change == 'cache-missing': recipe['npm_cache'] = str(tmp_path / 'absent')
    elif change == 'composition-cache': composition['environment']['npm_config_cache'] = str(tmp_path)
    elif change == 'composition-tool': composition['executables']['npm'] = composition['executables']['node']
    elif change == 'composition-profile': raw['compositions']['typescript']['recipe'] = 'django'
    elif change == 'undeclared': del raw['recipes']['typescript-web']
    else:
        shell = folder / 'sh'
        shutil.copyfile(recipe['npm_executable'], shell)
        shell.chmod(0o700)
        recipe['npm_executable'] = composition['executables']['npm'] = str(shell)
    with pytest.raises(LocalConfigError):
        load_local_config(write(folder, raw))


def test_npm_cache_inside_the_checkout_is_refused_at_composition(operator):
    _, data, folder, tmp_path = operator
    checkout = tmp_path / 'inside'
    (checkout / 'cache').mkdir(parents=True)
    raw = typescript_data(data, folder, checkout / 'cache')
    config = load_local_config(write(folder, raw))
    row = {'id': 'inside', 'root': str(checkout), 'repository_trusted': True, 'composition': 'typescript',
           'policy': POLICY}
    with pytest.raises(LocalConfigError, match='npm cache'):
        config.registrar.compose(row, 'synthetic')


def test_both_recipes_coexist_and_django_keeps_its_fingerprint_and_hash(operator):
    """The Django recipe module is byte-identical, so its fingerprint and composition hashes are unchanged."""
    _, data, folder, tmp_path = operator
    assert django.fingerprint() == 'd2b89bcaa647d659dac7417c4af53e7cb532cfbaef1fd7346cb29d440eb35ff2'
    only = load_local_config(write(folder, django_data(data, folder)))
    raw = django_data(data, folder)
    both = typescript_data(data, folder, synthetic_cache(tmp_path))
    both['recipes'] = {**raw['recipes'], **both['recipes']}
    both['compositions']['django'] = raw['compositions']['django']
    for role in ('reviewer', 'executor'):
        both['agents'][role]['environment']['PYTHONDONTWRITEBYTECODE'] = '1'
    combined = load_local_config(write(folder, both, name='both.toml'))
    root = tmp_path / 'new'
    root.mkdir()
    row = {'id': 'new', 'root': str(root), 'repository_trusted': True, 'composition': 'django', 'policy': POLICY}
    first, second = only.registrar.compose(row, 'django')[0], combined.registrar.compose(row, 'django')[0]
    assert first.versions['project_recipe'] == second.versions['project_recipe'] == django.VERSION
    assert first.versions['recipe_config_sha256'] == second.versions['recipe_config_sha256']
    typescript = combined.registrar.compose({**row, 'composition': 'typescript'}, 'typescript')[0]
    assert typescript.versions['project_recipe'] == typescript_web.VERSION
    assert typescript.context.profile.name == 'typescript-web'
    assert typescript.context.profile == only.registrar.profiles['typescript-web']


@pytest.fixture(params=['synthetic', 'real'])
def journey(request, operator, migrated_database, monkeypatch):
    _, raw, folder, tmp_path = operator
    real = request.param == 'real'
    if real:
        cache = os.environ.get('HARNESS_TEST_TYPESCRIPT_NPM_CACHE')
        if not cache:
            pytest.skip('Real node/npm require an explicitly populated npm cache; no implicit downloads')
        cache = Path(cache).resolve(strict=True)
    else:
        cache = synthetic_cache(tmp_path)
    value = typescript_data(raw, folder, cache, real=real)
    presets = v5(raw, [])['agent_presets']
    script = folder / 'responses.json'
    for agent in [*value['agents'].values(), *presets.values()]:
        agent['executable'][-1] = 'recipe'
        agent['environment'].update(PROBE_SCRIPT=str(script))
    value['agent_presets'] = presets
    config = load_local_config(write(folder, value))
    captured = []
    app = importlib.import_module('my_harness.api.app')
    runtime_class = app.ManagedRuntime
    def runtime(*args, **kwargs):
        instance = runtime_class(*args, **kwargs)
        captured.append(instance)
        return instance
    monkeypatch.setattr(app, 'ManagedRuntime', runtime)
    yield config, captured, script, tmp_path, real


def post(http, path, body, key=None, status=200):
    response = http.post(path, json=body, headers={'Idempotency-Key': key} if key else {})
    assert response.status_code == status, response.text
    return response.json()


def test_new_child_definition_preparation_and_first_task_with_profile_validations(journey, migrated_database):
    """Criterion 11 for `typescript-web`: from an empty folder to a committed first task, no protected writes."""
    config, runtimes, script, temporary, real = journey
    script.write_text(json.dumps({'definition': answer(drafts())}))
    parent = temporary / 'chosen'
    parent.mkdir()
    root = parent / 'child'
    base = '/api/managed/projects/child'
    with client(migrated_database[0], temporary, config) as http:
        runtime = runtimes[-1]
        worker = LocalSupervisor(runtime.repository, config.ports_factory, commit_factory=config.commit_factory)
        selected = {'action': 'select', 'expected_version': 0, 'path': str(parent)}
        preview = post(http, '/api/managed/project-creation-root/preview', selected)
        post(http, '/api/managed/project-creation-root/apply',
             {'change': selected, 'preview_sha256': preview['preview_sha256'], 'confirm_path': str(parent)}, 'root')
        change = {'project_id': 'child', 'directory_name': 'child', 'root_version': 1, 'composition': 'typescript',
                  'policy': POLICY, 'agent_selection': selection('codex', 'claude'), 'work_language': 'en'}
        preview = post(http, '/api/managed/project-creations/preview', change)
        post(http, '/api/managed/project-creations/confirm',
             {'change': change, 'preview_sha256': preview['preview_sha256'], 'trust_root': str(root)}, 'child')
        conversation = post(http, base + '/planning', {'kind': 'definition', 'title': 'Sintético',
            'brief': '# Ensayo sintético\n\nSin proveedores reales.\n'}, 'definition', 201)['id']
        post(http, base + f'/planning/{conversation}/messages', {'expected_version': 0, 'text': 'Propón'}, 'turn', 202)
        assert worker.run_once().status == 'DONE'
        planning = base + f'/planning/{conversation}'
        for proposal in http.get(planning).json()['proposals']:
            post(http, planning + f"/proposals/{proposal['id']}/apply", {
                'expected_version': http.get(planning).json()['version'],
                'proposal_sha256': proposal['proposal_sha256'], 'confirmed': True})
        preview = post(http, planning + '/accept/preview', {})
        assert preview['ready'], preview['blockers']
        definition = post(http, planning + '/accept', {'preview_sha256': preview['preview_sha256'], 'confirmed': True,
            'reason': 'Synthetic exact definition', 'resume_operation_id': None, 'expected_version': None}, 'accept', 202)
        assert worker.run_once().status == 'DONE'
        assert runtime.repository.get_run(definition['run_id']).status in ('COMMITTED', 'COMPLETED')
        task = {'task_id': 'P001-T001', 'phase_id': 'P001', 'text': (root / 'docs/NEXT_STEPS.md').read_text()}
        refused = http.post(base + '/runs', json=task, headers={'Idempotency-Key': 'early'})
        assert refused.status_code == 409 and 'preparation_required' in refused.text
        assert not (root / 'package.json').exists()
        change = {'expected_version': 1, 'mode': 'offline'}
        preview = post(http, base + '/preparation/preview', change)
        prepared = post(http, base + '/preparation/confirm',
                        {'change': change, 'preview_sha256': preview['preview_sha256']}, 'prepare')
        assert runtime.preparation.run_once() == prepared['id']
        operation = runtime.preparation.repository.read(prepared['id'])
        assert operation['status'] == 'COMPLETED', (operation['diagnostic'], [
            (s['number'], s.get('evidence')) for s in operation['steps'] if s['status'] == 'STARTED'])
        assert git(root, 'rev-list', '--count', 'HEAD') == '2'
        main = (root / 'src/main.ts').read_text() + 'export const increment = "P001-T001";\n'
        script.write_text(json.dumps({
            'planner': {'task_id': 'P001-T001', 'phase_id': 'P001', 'title': 'Synthetic increment',
                'objective': 'Extend the prepared module', 'executor_prompt': 'Apply the synthetic increment',
                'allowed_paths': ['src/'], 'forbidden_paths': [],
                'acceptance_criteria': ['Synthetic behavior is present.'], 'validation_commands': [],
                'executor_selection': {'model': 'synthetic-executor', 'effort': 'medium', 'reason': 'Synthetic'}},
            'edits': {'src/main.ts': main}, 'executor': {'result': 'Applied P001-T001'},
            'reviewer': {'task_id': 'P001-T001', 'verdict': 'ACCEPT', 'findings': [],
                         'blocking_questions': [], 'scope_grants': []}}))
        job = post(http, base + '/runs', task, 'P001-T001', 202)
        assert worker.run_once().status == 'DONE'
        accepted = runtime.repository.get_run(job['run_id'])
        assert accepted.status == 'ACCEPTANCE_READY', accepted.history.stop
        commands = [p['spec']['command']['argv'] for p in runtime.repository.command_processes(job['id'])]
        assert commands == [['node', '--version'], ['npm', '--version'],
                            ['npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund'],
                            ['npm', 'run', 'check'], ['npm', 'run', 'test'], ['npm', 'run', 'build']]
        cycle = accepted.history.cycles[-1]
        assert all(entry.result.passed for entry in cycle.validation.entries)
        commit = post(http, f"/api/managed/runs/{job['run_id']}/actions",
                      {'action': 'commit', 'expected_version': accepted.version}, 'commit', 202)
        assert worker.run_once().status == 'DONE'
        assert runtime.repository.get_run(commit['run_id']).status == 'COMMITTED'
        assert git(root, 'rev-list', '--count', 'HEAD') == '3'
        # D088 regenerates the control blocks in the same commit; no manifest file changes.
        assert git(root, 'show', '--name-only', '--format=', 'HEAD').splitlines() == [
            'docs/NEXT_STEPS.md', 'docs/STATE.md', 'src/main.ts']
        assert git(root, 'status', '--porcelain') == ''
        verify_receipt(root, operation['receipt'])


def test_example_fragment_names_exactly_the_recipe_and_composition_keys():
    import tomllib
    example = tomllib.loads((Path(__file__).parents[2] / 'examples/typescript-web-recipe.example.toml').read_text())
    assert set(example['recipes']['typescript-web']) == {'node_executable', 'node_version', 'npm_executable',
        'npm_version', 'npm_cache', 'allow_network', 'timeout_seconds', 'max_output_bytes'}
    composition = example['compositions']['typescript']
    assert composition['recipe'] == composition['profile'] == 'typescript-web'
    assert set(composition['executables']) == {'node', 'npm'}
    assert composition['environment']['npm_config_cache'] == example['recipes']['typescript-web']['npm_cache']
