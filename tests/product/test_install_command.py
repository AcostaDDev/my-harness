"""P013-T002: installer orchestration with synthetic archives and fake local tools only.

No package installation, provider, listening service, download or operator configuration is used.
"""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
# Avoid importing an unrelated site module named install.
spec = importlib.util.spec_from_file_location('harness_installer', SCRIPTS / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
from build_distribution import write_checksums  # noqa: E402
from distribution_artifacts import archive_members, check_artifacts, write_manifest  # noqa: E402


def bundle(path):
    path.mkdir()
    project = {'name': 'my-harness', 'version': '0.1.0', 'license': 'MIT',
               'requires-python': '>=3.14,<3.15', 'dependencies': ['fastapi==0.143.0']}
    metadata = ('Name: my-harness\nVersion: 0.1.0\nLicense-Expression: MIT\nRequires-Python: >=3.14,<3.15\n'
                'Requires-Dist: fastapi==0.143.0\nLicense-File: LICENSE\nLicense-File: NOTICE.md\n'
                'License-File: NOTICE-THIRD-PARTY.md\n\nSynthetic package\n')
    info = 'my_harness-0.1.0.dist-info/'
    with zipfile.ZipFile(path / 'my_harness-0.1.0-py3-none-any.whl', 'w') as wheel:
        for name, content in {'my_harness/api/app.py': 'FastAPI(title="My Harness", version="0.1.0")',
                              'my_harness/web/index.html': '<div id="root"></div>',
                              'my_harness/migrations/versions/0001_synthetic.py': '# synthetic',
                              info + 'METADATA': metadata,
                              **{info + 'licenses/' + name: 'Synthetic license' for name in
                                 ('LICENSE', 'NOTICE.md', 'NOTICE-THIRD-PARTY.md')}}.items():
            wheel.writestr(name, content)
    with tarfile.open(path / 'my_harness-0.1.0.tar.gz', 'w:gz') as archive:
        member = tarfile.TarInfo('my_harness-0.1.0/PKG-INFO')
        content = metadata.encode()
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    (path / 'pylock.toml').write_text('lock-version = "1.0"\n[[packages]]\nname = "fastapi"\nversion = "0.143.0"\n'
        '[[packages.wheels]]\nurl = "https://example.invalid/fastapi.whl"\n'
        'hashes = {sha256 = "' + 'a' * 64 + '"}\n')
    from distribution_artifacts import BUNDLE_SCRIPTS
    (path / 'scripts').mkdir()
    for name in BUNDLE_SCRIPTS:
        source = SCRIPTS / name if name != 'installed_config.py' else SCRIPTS.parent / 'tests/fixtures/e2e' / name
        shutil.copy2(source, path / 'scripts' / name)
    write_manifest(path, project)
    write_checksums(path)
    return path


@pytest.fixture
def setup(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    distribution = bundle(tmp_path / 'local built package')
    tools = tmp_path / 'local tools'
    tools.mkdir()
    log = tmp_path / 'commands.jsonl'
    # Real subprocess boundary, fake tools: no uv/pip/Node/network actions can happen here.
    program = f'''#!{sys.executable}
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
with open({str(log)!r}, 'a') as stream:
    stream.write(json.dumps({{'tool': pathlib.Path(sys.argv[0]).name, 'args': args,
                             'env': {{k: os.environ[k] for k in ('UV_OFFLINE', 'UV_CACHE_DIR', 'UV_NO_VERIFY_HASHES', 'HARNESS_LOCAL_CONFIG') if k in os.environ}}, 'cwd': os.getcwd()}}) + '\\n')
if pathlib.Path(sys.argv[0]).name == 'fake python':
    if '-c' in args:
        print('3.14')
    elif any(a.endswith('build_distribution.py') for a in args):
        shutil.copytree({str(distribution)!r}, args[args.index('--out-dir') + 1])
    elif any(a.endswith('check_distribution.py') for a in args):
        if os.environ.get('FAIL_CHECK'):
            sys.exit(9)
elif '--version' in args:
    print('uv 0.12.19')
elif 'venv' in args:
    venv = pathlib.Path(args[-1]); (venv / 'bin').mkdir(parents=True)
    (venv / 'bin/python').write_text('synthetic interpreter')
    (venv / 'bin/my-harness').write_text('synthetic CLI')
elif 'sync' in args and os.environ.get('FAIL_SYNC'):
    sys.exit(8)
'''
    for name in ('fake python', 'fake uv'):
        (tools / name).write_text(program)
        (tools / name).chmod(0o700)
    argv = ['--dist', str(distribution), '--python', str(tools / 'fake python'), '--uv', str(tools / 'fake uv')]
    for name in ('install', 'data', 'config', 'cache'):
        argv += ['--' + name + '-dir', str(tmp_path / (name + ' with spaces'))]
    monkeypatch.setenv('UV_NO_VERIFY_HASHES', '1')
    monkeypatch.setenv('UV_SYSTEM_PYTHON', '1')
    monkeypatch.setenv('HARNESS_LOCAL_CONFIG', '/must/not/read.toml')
    return installer.parse_args(argv), log


def calls(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_package_install_and_identical_offline_repeat(setup):
    args, log = setup
    receipt = installer.install(args)
    root = args.install_dir
    assert receipt['status'] == 'READY' and not receipt['network']
    assert receipt['checks'] == ['artifacts-members-metadata-hashes', 'isolated-installed-synthetic-journey']
    pointer = (root / 'current.json').read_bytes()
    generation = root / 'generations' / json.loads(pointer)['generation']
    assert (generation / 'venv/bin/python').is_file()
    assert (root / 'current.json').stat().st_mode & 0o777 == 0o600
    assert args.data_dir.stat().st_mode & 0o777 == 0o700
    commands = calls(log)
    assert not any(c['tool'] in ('node', 'npm') for c in commands)
    installation_calls = [c for c in commands if c['args'] != ['--version'] and '-c' not in c['args']]
    assert all(Path(c['cwd']).is_relative_to(generation) for c in installation_calls)
    assert all(c['env'].get('UV_OFFLINE') == '1' for c in installation_calls)
    assert all('UV_NO_VERIFY_HASHES' not in c['env'] and 'HARNESS_LOCAL_CONFIG' not in c['env'] for c in installation_calls)
    sync = next(c for c in commands if 'sync' in c['args'])
    assert '--require-hashes' in sync['args'] and '--only-binary' in sync['args']
    assert sync['env']['UV_CACHE_DIR'] == str(args.cache_dir / 'uv')
    assert installer.install(args) == receipt
    assert (root / 'current.json').read_bytes() == pointer
    assert len([c for c in calls(log) if 'sync' in c['args']]) == 1


@pytest.mark.parametrize('step', ['FAIL_SYNC', 'FAIL_CHECK'])
def test_failure_never_publishes_partial_installation(setup, monkeypatch, step):
    args, _ = setup
    monkeypatch.setenv(step, '1')
    with pytest.raises(installer.InstallRefused, match='No new installation'):
        installer.install(args)
    assert not (args.install_dir / 'current.json').exists()
    receipts = list((args.install_dir / 'generations').glob('*/installation.json'))
    assert len(receipts) == 1 and json.loads(receipts[0].read_text())['status'] == 'FAILED'
    with pytest.raises(installer.InstallRefused, match='Occupied or incomplete'):
        installer.install(args)


def test_upgrade_keeps_previous_generation_and_data_on_failure(setup, monkeypatch):
    args, _ = setup
    installer.install(args)
    current = (args.install_dir / 'current.json').read_bytes()
    marker = args.data_dir / 'operator-data'
    marker.write_bytes(b'preserved')
    # New checksum-valid delivery of the same product version is a different generation.
    (args.dist / 'scripts/install').write_text('# different wrapper\n')
    write_checksums(args.dist)
    with pytest.raises(installer.InstallRefused, match='--upgrade'):
        installer.install(args)
    args.upgrade = True
    with pytest.raises(installer.InstallRefused, match='--writers-stopped'):
        installer.install(args)
    args.writers_stopped = True
    monkeypatch.setenv('FAIL_CHECK', '1')
    with pytest.raises(installer.InstallRefused):
        installer.install(args)
    assert (args.install_dir / 'current.json').read_bytes() == current
    assert marker.read_bytes() == b'preserved'
    monkeypatch.delenv('FAIL_CHECK')
    installer.install(args)
    assert (args.install_dir / 'current.json').read_bytes() != current
    assert len(list((args.install_dir / 'generations').iterdir())) == 3
    assert marker.read_bytes() == b'preserved'


def test_network_requires_positive_option_and_verification_remains_offline(setup):
    args, log = setup
    args.allow_network = True
    installer.install(args)
    commands = calls(log)
    sync = next(c for c in commands if 'sync' in c['args'])
    assert '--offline' not in sync['args'] and sync['env']['UV_OFFLINE'] == '0'
    check = next(c for c in commands if any(a.endswith('check_distribution.py') for a in c['args']))
    assert check['env']['UV_OFFLINE'] == '1'
    args.allow_network = False
    installer.install(args)
    assert len([c for c in calls(log) if 'sync' in c['args']]) == 1


@pytest.mark.parametrize('problem', ['relative', 'overlap', 'checkout', 'symlink', 'occupied', 'public', 'data_occupied'])
def test_invalid_paths_fail_before_tool_or_installation_effects(setup, problem, tmp_path):
    args, log = setup
    if problem == 'relative':
        args.install_dir = Path('relative')
    elif problem == 'overlap':
        args.data_dir = args.install_dir / 'data'
    elif problem == 'checkout':
        args.install_dir = SCRIPTS.parent / 'should-not-create'
    elif problem == 'symlink':
        args.install_dir.symlink_to(tmp_path / 'absent')
    elif problem == 'occupied':
        args.install_dir.mkdir(mode=0o700)
        (args.install_dir / 'unrelated').write_text('keep')
    elif problem == 'public':
        args.config_dir.mkdir(mode=0o755)
        args.config_dir.chmod(0o755)
    else:
        args.data_dir.mkdir(mode=0o700)
        (args.data_dir / 'keep').write_text('keep')
    with pytest.raises(installer.InstallRefused):
        installer.install(args)
    assert not (args.install_dir / 'current.json').exists()
    assert not any('sync' in c['args'] for c in calls(log)) if log.exists() else True


def test_missing_tools_do_not_create_destination(setup):
    args, _ = setup
    args.uv = '/nonexistent/synthetic-uv'
    with pytest.raises(installer.InstallRefused, match='missing'):
        installer.install(args)
    assert not args.install_dir.exists()


def test_repeat_detects_changed_installed_files(setup):
    args, _ = setup
    installer.install(args)
    generation = json.loads((args.install_dir / 'current.json').read_text())['generation']
    (args.install_dir / 'generations' / generation / 'venv/bin/my-harness').write_text('changed')
    with pytest.raises(installer.InstallRefused, match='venv has changed'):
        installer.install(args)


@pytest.mark.parametrize('problem', ['checksum', 'extra_file', 'member', 'duplicate', 'unsafe', 'lock_hash'])
def test_self_contained_artifact_verifier_rejects_tampering(tmp_path, problem):
    distribution = bundle(tmp_path / 'built')
    assert check_artifacts(distribution)['project']['version'] == '0.1.0'
    wheel = next(distribution.glob('*.whl'))
    if problem == 'extra_file':
        (distribution / 'extra').write_text('unexpected')
    elif problem == 'lock_hash':
        lock = distribution / 'pylock.toml'
        lock.write_text(lock.read_text().replace('a' * 64, 'invalid'))
        write_checksums(distribution)
    else:
        with zipfile.ZipFile(wheel, 'a') as archive:
            name = {'checksum': 'new', 'member': 'new', 'duplicate': 'my_harness/web/index.html',
                    'unsafe': '../escape'}[problem]
            archive.writestr(name, 'changed')
        if problem != 'checksum':
            write_checksums(distribution)
    with pytest.raises(AssertionError):
        check_artifacts(distribution)


def test_sdist_links_are_rejected_without_extracting(tmp_path):
    archive = tmp_path / 'synthetic.tar.gz'
    with tarfile.open(archive, 'w:gz') as stream:
        member = tarfile.TarInfo('safe-looking')
        member.type = tarfile.SYMTYPE
        member.linkname = '/outside'
        stream.addfile(member)
    with pytest.raises(AssertionError, match='Unsafe'):
        archive_members(archive)


def test_delivered_verifier_imports_without_checkout_or_dependencies(tmp_path):
    distribution = bundle(tmp_path / 'detached')
    result = subprocess.run([sys.executable, '-E', '-s', '-B', str(distribution / 'scripts/check_distribution.py'),
                             '--help'], cwd=tmp_path, env={'PATH': '/nonexistent'}, capture_output=True, text=True)
    assert result.returncode == 0 and '--python' in result.stdout, result.stderr


def test_clone_build_is_composed_with_selected_paths(setup, tmp_path, monkeypatch):
    args, log = setup
    clone = tmp_path / 'synthetic clone'
    for name in ('scripts', 'src', 'frontend', 'tests/fixtures/e2e'):
        (clone / name).mkdir(parents=True)
    for name in ('pyproject.toml', 'uv.lock', 'README.md', 'LICENSE', 'NOTICE.md', 'NOTICE-THIRD-PARTY.md',
                 'scripts/build_distribution.py', 'tests/fixtures/e2e/installed_config.py', 'frontend/package-lock.json'):
        (clone / name).write_text('synthetic')
    args.clone, args.dist = clone, None
    tools_checked = []
    monkeypatch.setattr(installer, 'check_tools', lambda uv, build: tools_checked.append((uv, build)))
    installer.install(args)
    build = next(c for c in calls(log) if any(a.endswith('build_distribution.py') for a in c['args']))
    assert '--offline' in build['args']
    assert build['args'][build['args'].index('--cache-dir') + 1] == str(args.cache_dir)
    assert tools_checked == [(str(Path(args.uv)), True)]


def test_interrupted_generation_is_retained_without_publishing(setup, monkeypatch):
    args, _ = setup
    monkeypatch.setattr(installer, 'sync_generation', lambda directory: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        installer.install(args)
    assert not (args.install_dir / 'current.json').exists()
    receipt = next((args.install_dir / 'generations').glob('*/installation.json'))
    assert json.loads(receipt.read_text())['status'] == 'FAILED'


def test_concurrent_installer_cannot_acquire_same_lock(tmp_path):
    tmp_path.chmod(0o700)
    with installer.installation_lock(tmp_path):
        with pytest.raises(installer.InstallRefused, match='in progress'):
            with installer.installation_lock(tmp_path):
                pytest.fail('Concurrent lock unexpectedly acquired')


def test_invalid_interpreter_is_diagnosed_before_creating_directories(setup, monkeypatch):
    args, _ = setup
    monkeypatch.setattr(installer.subprocess, 'check_output', lambda *a, **k: '3.13\n')
    with pytest.raises(installer.InstallRefused, match='Python >=3.14,<3.15 required; found 3.13'):
        installer.install(args)
    assert not args.install_dir.exists()


@pytest.mark.parametrize('network', [False, True])
def test_build_helper_routes_caches_locks_and_verification(tmp_path, monkeypatch, network):
    import build_distribution as builder
    import check_distribution as checker
    root = tmp_path / 'source'
    (root / 'frontend/dist').mkdir(parents=True)
    (root / 'src/my_harness').mkdir(parents=True)
    (root / 'src/my_harness/__init__.py').write_text('')
    (root / 'scripts').mkdir()
    (root / 'tests/fixtures/e2e').mkdir(parents=True)
    for name in builder.PROJECT_FILES:
        (root / name).write_text('[project]\nname = "my-harness"\nversion = "0.1.0"\n' if name == 'pyproject.toml' else 'synthetic')
    from distribution_artifacts import BUNDLE_SCRIPTS
    for name in BUNDLE_SCRIPTS:
        (root / ('tests/fixtures/e2e' if name == 'installed_config.py' else 'scripts') / name).write_text('# synthetic')
    output, cache = tmp_path / 'new output', tmp_path / 'cache root'
    argv = ['build_distribution.py', '--out-dir', str(output), '--cache-dir', str(cache),
            '--python', '/selected/python', '--uv', '/selected/uv', '--allow-network' if network else '--offline']
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(builder, 'ROOT', root)
    checked = []
    monkeypatch.setattr(builder, 'check_tools', lambda uv: checked.append(('tools', uv)))
    monkeypatch.setattr(checker, 'check_checkout_artifacts', lambda dist, project: checked.append(('checkout', dist)))
    monkeypatch.setattr(builder, 'write_manifest', lambda dist, project: (dist / 'distribution-1.json').write_text('{}'))
    commands = []
    def fake_run(argv, **kwargs):
        commands.append((argv, kwargs))
        if 'build' in argv and argv[0] == '/selected/uv':
            (output / 'synthetic.whl').write_text('synthetic')
        if 'export' in argv:
            (output / 'pylock.toml').write_text('synthetic')
    monkeypatch.setattr(builder.subprocess, 'run', fake_run)
    for name in ('UV_CACHE_DIR', 'UV_PYTHON', 'UV_PYTHON_DOWNLOADS'):
        monkeypatch.setenv(name, os.environ.get(name, ''))
    builder.main()
    assert checked == [('tools', '/selected/uv'), ('checkout', output)]
    npm = commands[0][0]
    assert npm[:2] == ['npm', 'ci'] and '--ignore-scripts' in npm and '--no-audit' in npm
    assert ('--offline' in npm) is not network
    assert npm[npm.index('--cache') + 1] == str(cache / 'npm')
    export = next(argv for argv, _ in commands if 'export' in argv)
    assert '--frozen' in export and '--offline' in export and '--no-emit-project' in export
    assert os.environ['UV_CACHE_DIR'] == str(cache / 'uv')
    assert os.environ['UV_PYTHON_DOWNLOADS'] == 'never'
    assert all((output / 'scripts' / name).exists() for name in BUNDLE_SCRIPTS)
    assert 'scripts/install.py' in (output / 'SHA256SUMS').read_text()


def test_macos_case_aliases_cannot_bypass_destination_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, 'platform', 'darwin')
    assert installer.overlap(tmp_path / 'Data', tmp_path / 'data/nested')
    assert not installer.overlap(tmp_path / 'Data', tmp_path / 'Database')


@pytest.mark.parametrize('kind', ['symlink', 'fifo'])
def test_manifest_special_files_are_rejected_before_reading(tmp_path, kind):
    distribution = bundle(tmp_path / 'package')
    manifest = distribution / 'distribution-1.json'
    manifest.unlink()
    if kind == 'symlink':
        manifest.symlink_to('/nonexistent/synthetic-manifest')
    else:
        os.mkfifo(manifest)
    with pytest.raises(AssertionError, match='Symlink|Special file'):
        check_artifacts(distribution)


@pytest.mark.parametrize('uv_path', ['uv', '/synthetic tools/uv'])
@pytest.mark.parametrize('version,accepted', [('0.12.19', True), ('0.12.18', False)])
def test_uv_pin_accepts_vendor_suffix_independently_of_executable_path(monkeypatch, uv_path, version, accepted):
    from toolchain import check_tools
    monkeypatch.setattr(subprocess, 'check_output', lambda argv, **kw: f'uv {version} (Homebrew synthetic)\n')
    if accepted:
        check_tools(uv_path, build=False)
    else:
        with pytest.raises(SystemExit, match='0.12.19 required'):
            check_tools(uv_path, build=False)


def test_installer_npm_environment_uses_distinct_configs_without_operator_overrides(tmp_path, monkeypatch):
    npm = shutil.which('npm')
    if npm is None:
        pytest.skip('npm unavailable; installed clone rehearsal also verifies this boundary')
    temporary = tmp_path / 'private temporary'
    temporary.mkdir()
    (temporary / 'empty.npmrc').write_text('')
    foreign = tmp_path / 'operator.npmrc'
    foreign.write_text('registry=https://example.invalid/\n')
    monkeypatch.setenv('NPM_CONFIG_GLOBALCONFIG', str(foreign))
    monkeypatch.setenv('NPM_CONFIG_REGISTRY', 'https://example.invalid/')
    monkeypatch.setenv('npm_config_registry', 'https://example.invalid/')
    env = installer.clean_environment(tmp_path / 'cache', Path(sys.executable), False, temporary)
    result = subprocess.run([npm, 'config', 'get', 'registry'], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'https://registry.npmjs.org/'
    assert foreign.read_text() == 'registry=https://example.invalid/\n'
