"""Install My Harness into private, verified generations. Offline unless --allow-network is explicit."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

if sys.version_info < (3, 11):
    raise SystemExit('Installer bootstrap requires Python >=3.11; select local Python 3.14 with --python')

from distribution_artifacts import check_artifacts, digest
from toolchain import check_tools

ROOT = Path(__file__).resolve().parents[1]


class InstallRefused(Exception):
    pass


def absolute(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise InstallRefused(f'An absolute path is required: {path}')
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink():
            raise InstallRefused(f'Symlink path component is not allowed: {part}')
    return path


def overlap(a, b):
    if sys.platform == 'darwin':
        # The supported macOS volume may be case insensitive, including not-yet-created destinations.
        a, b = Path(str(a).casefold()), Path(str(b).casefold())
    return a.is_relative_to(b) or b.is_relative_to(a)


def private_directory(path):
    if path.exists():
        info = path.stat()
        if not path.is_dir() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise InstallRefused(f'Expected a private directory owned by this user (permissions 0700): {path}')
    else:
        missing = [path]
        while not missing[-1].parent.exists():
            missing.append(missing[-1].parent)
        for folder in reversed(missing):
            folder.mkdir(mode=0o700)


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise InstallRefused(f'Expected a regular, unlinked receipt: {path}')
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise InstallRefused(f'Receipt must be private and owned by this user: {path}')
    return json.loads(path.read_text())


def write_json(path, value):
    """Publish a private file and its directory durably; never truncate the previous reference."""
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    data = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    try:
        with temporary.open('xb') as stream:
            os.chmod(temporary, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def installation_lock(root):
    path = root / '.install.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077:
            raise InstallRefused(f'Unsafe installation lock: {path}')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallRefused('Another installation is in progress') from None
        yield descriptor
    finally:
        os.close(descriptor)


def clean_environment(cache, python, network, temporary):
    # Operator resolver/configuration/environment switches cannot defeat hashes, offline mode or venv isolation.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('UV_', 'PIP_', 'PYTHON', 'HARNESS_', 'npm_config_', 'NPM_CONFIG_'))
           and k not in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'NODE_OPTIONS', 'NPM_CONFIG_USERCONFIG')}
    env.update(UV_CACHE_DIR=str(cache / 'uv'), UV_PYTHON=str(python), UV_PYTHON_DOWNLOADS='never',
               UV_NO_CONFIG='1', UV_OFFLINE='0' if network else '1', PYTHONNOUSERSITE='1',
               PYTHONDONTWRITEBYTECODE='1', npm_config_cache=str(cache / 'npm'),
               npm_config_userconfig=os.devnull, npm_config_globalconfig=str(temporary / 'empty.npmrc'))
    return env


def run(argv, *, cwd, env):
    print('+ ' + ' '.join(map(str, argv)), flush=True)
    try:
        subprocess.run(list(map(str, argv)), cwd=cwd, env=env, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InstallRefused(f'Installation step failed: {argv[0]}. Offline cache may be incomplete; '
                             'use the chosen cache with --allow-network to prepare it. '
                             f'No new installation has been published. ({exc})') from None


def executable(value):
    found = shutil.which(value)
    if not found:
        raise InstallRefused(f'Required local executable is missing: {value}; install/select it explicitly')
    # Python/uv may be local tool symlinks; installation/data/config destinations may not.
    return Path(found).absolute()


def source_identity(root):
    paths = [root / p for p in ('pyproject.toml', 'uv.lock', 'README.md', 'LICENSE', 'NOTICE.md',
                                'NOTICE-THIRD-PARTY.md', 'tests/fixtures/e2e/installed_config.py')]
    for folder in ('src', 'scripts', 'frontend'):
        paths.extend(p for p in (root / folder).rglob('*') if p.is_file() and not
                     set(p.relative_to(root / folder).parts) & {'__pycache__', 'node_modules', 'dist'})
    return digest(json.dumps({p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(set(paths))},
                             sort_keys=True).encode())


def venv_identity(venv):
    result = {}
    for path in sorted(venv.rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        key = path.relative_to(venv).as_posix()
        if path.is_symlink():
            result[key] = {'link': os.readlink(path)}
        elif path.is_file():
            result[key] = {'sha256': digest(path.read_bytes()), 'mode': stat.S_IMODE(path.stat().st_mode)}
    return result


def sync_generation(directory):
    """Make package/venv bytes durable before the reference can advertise this generation."""
    directories = [directory.parent, directory]
    for path in directory.rglob('*'):
        if path.is_symlink():
            continue
        if path.is_dir():
            directories.append(path)
        elif path.is_file():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    for path in reversed(directories):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def current_installation(root):
    pointer = read_json(root / 'current.json')
    generation = pointer['generation']
    if not isinstance(generation, str) or not generation.startswith('gen-') or '/' in generation or '..' in generation:
        raise InstallRefused('Invalid generation reference')
    directory = absolute(root / 'generations' / generation)
    receipt_path = directory / 'installation.json'
    receipt = read_json(receipt_path)
    if pointer['format'] != 'installation-1' or pointer['receipt_sha256'] != digest(receipt_path.read_bytes()):
        raise InstallRefused('Installation reference/receipt mismatch')
    if receipt['status'] != 'READY' or receipt['format'] != 'installation-1':
        raise InstallRefused('Installation is incomplete; inspect its intention before retrying')
    check_artifacts(directory / 'distribution')
    if receipt['distribution_sha256'] != digest((directory / 'distribution/SHA256SUMS').read_bytes()):
        raise InstallRefused('Distribution does not match the installation receipt')
    if receipt['venv'] != venv_identity(directory / 'venv'):
        raise InstallRefused('Installed venv has changed; preserve and inspect this generation')
    return receipt, directory


def parse_args(argv=None):
    base = Path.home() / 'Library/Application Support/My Harness'
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--clone', type=Path, help='Source clone (default: this script\'s checkout)')
    source.add_argument('--dist', type=Path, help='Local built distribution; no Node/npm or checkout required')
    for name, default in (('install', base / 'installation'), ('data', base / 'data'),
                          ('config', base / 'configuration'), ('cache', Path.home() / 'Library/Caches/My Harness')):
        parser.add_argument(f'--{name}-dir', type=Path, default=default)
    parser.add_argument('--python', help='Local Python 3.14 executable; never downloaded')
    parser.add_argument('--uv', default='uv', help='Local uv 0.12.19 executable; never downloaded')
    network = parser.add_mutually_exclusive_group()
    network.add_argument('--offline', action='store_true', help='Default: use cache only; never fall back to network')
    network.add_argument('--allow-network', action='store_true', help='Allow locked dependency downloads into the chosen cache')
    parser.add_argument('--upgrade', action='store_true', help='Publish a new generation, keeping the previous one')
    parser.add_argument('--writers-stopped', action='store_true', help='Declare service and writers stopped for an upgrade')
    return parser.parse_args(argv)


def install(args):
    root, data, config, cache = (absolute(getattr(args, name + '_dir')) for name in ('install', 'data', 'config', 'cache'))
    source = absolute(args.dist or args.clone or ROOT)
    clone = not args.dist
    paths = (root, data, config)
    for i, path in enumerate(paths):
        if overlap(path, source) or any((p / '.git').exists() or
                ((p / 'pyproject.toml').exists() and (p / 'src').is_dir()) for p in (path, *path.parents)):
            raise InstallRefused(f'Installation/data/configuration must be outside checkouts and package input: {path}')
        if any(overlap(path, other) for other in paths[i + 1:]) or overlap(path, cache):
            raise InstallRefused('Installation, data, configuration and cache directories must not overlap')
        if path.exists():
            private_directory(path)
    if root.exists() and any(root.iterdir()) and not (root / 'current.json').exists():
        raise InstallRefused(f'Occupied or incomplete installation: {root}; inspect and preserve it before retrying')
    if args.upgrade and not args.writers_stopped:
        raise InstallRefused('--upgrade requires --writers-stopped; stop the service and all writers first (D150)')
    uv = executable(args.uv)
    python = executable(args.python or ('python3.14' if shutil.which('python3.14') else 'python3'))
    observed = subprocess.check_output([str(python), '-I', '-c', 'import sys; print("%s.%s" % sys.version_info[:2])'],
                                       text=True).strip()
    if observed != '3.14':
        raise InstallRefused(f'Python >=3.14,<3.15 required; found {observed} at {python}; use --python')
    check_tools(str(uv), build=clone)
    if not shutil.which('git'):
        raise InstallRefused('Git is required for the isolated synthetic verification; no provider CLI is needed')
    if clone and not all((source / p).is_file() for p in ('uv.lock', 'scripts/build_distribution.py', 'frontend/package-lock.json')):
        raise InstallRefused(f'Not a source clone: {source}; built packages must use --dist')
    if not clone:
        check_artifacts(source)
    identity = source_identity(source) if clone else digest((source / 'SHA256SUMS').read_bytes())
    request = {'source': str(source), 'source_kind': 'clone' if clone else 'dist', 'source_sha256': identity,
               'install_dir': str(root), 'data_dir': str(data), 'config_dir': str(config), 'cache_dir': str(cache),
               'python': str(python), 'python_version': observed, 'python_sha256': digest(python.read_bytes()),
               'uv': str(uv), 'uv_sha256': digest(uv.read_bytes())}
    print(json.dumps({'plan': request, 'network': 'locked npm/Python dependencies' if args.allow_network else 'disabled',
                      'verification': 'isolated synthetic service/agents only; no operator configuration',
                      'migration': 'never; existing databases require a separate D150 command'}, indent=2), flush=True)
    private_directory(root)
    with installation_lock(root):
        previous = None
        if (root / 'current.json').exists():
            previous, _ = current_installation(root)
            if previous['request'] == request:
                print(f'Already installed and verified: {root / "current.json"}')
                return previous
            if not args.upgrade:
                raise InstallRefused('A different installation is active; use --upgrade --writers-stopped to preserve and replace it')
            if any(previous['request'][field] != request[field] for field in ('data_dir', 'config_dir')):
                raise InstallRefused('Upgrade must retain the existing data/configuration directories')
        elif args.upgrade:
            raise InstallRefused('--upgrade needs an existing valid installation')
        for path in (data, config):
            if not previous and path.exists() and any(path.iterdir()):
                raise InstallRefused(f'New installation requires empty data/configuration directories: {path}')
            private_directory(path)
        # Cache may be deliberately shared; never chmod existing folders.
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        generations = root / 'generations'
        private_directory(generations)
        generation = generations / ('gen-' + uuid.uuid4().hex)
        generation.mkdir(mode=0o700)
        receipt_path = generation / 'installation.json'
        receipt = {'format': 'installation-1', 'status': 'PREPARING', 'request': request,
                   'network': bool(args.allow_network), 'previous': (root / 'current.json').read_text() if previous else None, 'checks': []}
        write_json(receipt_path, receipt)
        temporary = generation / 'tmp'
        private_directory(temporary)
        # npm rejects loading one path as both user and global config, including /dev/null.
        with (temporary / 'empty.npmrc').open('x') as stream:
            os.chmod(stream.name, 0o600)
        env = clean_environment(cache, python, args.allow_network, temporary)
        env['TMPDIR'] = str(temporary)
        distribution = generation / 'distribution'
        try:
            if clone:
                run([python, '-E', '-s', '-B', source / 'scripts/build_distribution.py', '--out-dir', distribution,
                     '--cache-dir', cache, '--python', python, '--uv', uv,
                     '--allow-network' if args.allow_network else '--offline'], cwd=generation, env=env)
                if source_identity(source) != identity:
                    raise InstallRefused('Source files changed during the build; generation cannot be published')
            else:
                shutil.copytree(source, distribution)
            manifest = check_artifacts(distribution)
            if not clone and digest((distribution / 'SHA256SUMS').read_bytes()) != identity:
                raise InstallRefused('Distribution changed while copying; generation cannot be published')
            receipt['checks'].append('artifacts-members-metadata-hashes')
            # Downloads occur only here when explicitly enabled. The full installed verification is always offline.
            venv = generation / 'venv'
            run([uv, 'venv', '--offline', '--no-python-downloads', '--python', python, venv], cwd=generation, env=env)
            mode = [] if args.allow_network else ['--offline']
            run([uv, 'pip', 'sync', *mode, '--link-mode', 'copy', '--require-hashes', '--only-binary', ':all:', '--python', venv / 'bin/python',
                 distribution / 'pylock.toml'], cwd=generation, env=env)
            wheel = next(distribution.glob('*.whl'))
            run([uv, 'pip', 'install', '--offline', '--link-mode', 'copy', '--no-deps', '--python', venv / 'bin/python', wheel], cwd=generation, env=env)
            run([python, '-E', '-s', '-B', distribution / 'scripts/check_distribution.py', '--dist', distribution,
                 '--python', python, '--uv', uv, '--cache-dir', cache / 'uv'], cwd=generation,
                env=env | {'UV_OFFLINE': '1'})
            receipt['checks'].append('isolated-installed-synthetic-journey')
            run([uv, 'pip', 'check', '--offline', '--python', venv / 'bin/python'], cwd=generation, env=env)
            receipt.update(status='READY', project_version=manifest['project']['version'],
                           distribution_sha256=digest((distribution / 'SHA256SUMS').read_bytes()), venv=venv_identity(venv))
            write_json(receipt_path, receipt)
            sync_generation(generation)
        except BaseException as exc:
            # An interruption leaves the old reference untouched. Retain all bytes for diagnosis, never auto-delete.
            receipt.update(status='FAILED', diagnostic=str(exc))
            write_json(receipt_path, receipt)
            raise
        write_json(root / 'current.json', {'format': 'installation-1', 'generation': generation.name,
                                          'receipt_sha256': digest(receipt_path.read_bytes())})
        print(f'Installed and verified: {root / "current.json"}. Database/configuration files were not changed.')
        return receipt


def main(argv=None):
    try:
        install(parse_args(argv))
    except (InstallRefused, OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as exc:
        raise SystemExit(f'Installation refused: {exc}') from None


if __name__ == '__main__':
    main()
