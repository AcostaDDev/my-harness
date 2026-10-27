"""Start the verified installed package outside the checkout; never install or migrate."""
import argparse
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess

from install import (InstallRefused, absolute, current_installation, installation_lock,
                     overlap, private_directory)


# Runs with the installed interpreter and dependencies, never imports source-checkout code.
# Read-only archives take priority over any operational TOML, including a missing/invalid one.
PREFLIGHT = '''
import sys
import sqlite3
from pathlib import Path
from sqlalchemy import create_engine
from my_harness.launcher import local_database
from my_harness.storage.schema import require_schema
from my_harness.storage.backup import is_read_only_archive
try:
    path, url = local_database(sys.argv[1])
    archived = False
    if path.exists():
        # Validation must not create WAL files or change an old database before D150.
        engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(
            path.as_uri() + '?mode=ro', uri=True, autocommit=False))
        try:
            require_schema(engine)
            archived = is_read_only_archive(engine)
        except Exception as error:
            raise RuntimeError('Database is not ready. Stop service and writers; use my-harness migrate '
                               '--database PATH --snapshots DIRECTORY --writers-stopped separately '
                               '(D150, verified backup before migration). ' + str(error)) from None
        finally:
            engine.dispose()
except Exception as error:
    print('Startup preflight failed: ' + str(error), file=sys.stderr)
    sys.exit(1)
sys.exit(20 if archived else 0)
'''


class StartRefused(Exception):
    pass


def regular_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        raise StartRefused(f'Expected a regular file owned by this user, without links: {path}')


def outside_checkout(path):
    if any((p / '.git').exists() or (p / '.git').is_symlink() or
           ((p / 'pyproject.toml').exists() and (p / 'src').is_dir()) for p in (path, *path.parents)):
        raise StartRefused(f'Startup paths must be outside checkouts: {path}')


@contextmanager
def instance_lock(root):
    path = root / '.start.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise StartRefused(f'Unsafe startup lock: {path}')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StartRefused('Another service is using this installation') from None
        yield descriptor
    finally:
        os.close(descriptor)


class Children:
    """Forward terminal/service signals and reap each child before releasing the instance lock."""
    def __init__(self, lock_descriptors):
        self.child = None
        self.stopped = None
        self.lock_descriptors = lock_descriptors

    def signal(self, number, frame):
        self.stopped = number
        if self.child is not None:
            try:
                os.killpg(self.child.pid, number)
            except ProcessLookupError:
                pass

    def run(self, argv, *, cwd, env):
        if self.stopped is not None:
            return 128 + self.stopped
        # Keep exclusion even if the wrapper is killed: the live service still owns both flock descriptions.
        self.child = subprocess.Popen(list(map(str, argv)), cwd=cwd, env=env, start_new_session=True,
                                      pass_fds=self.lock_descriptors)
        try:
            # A signal can arrive between the initial check and publishing the child handle.
            if self.stopped is not None:
                self.signal(self.stopped, None)
            result = self.child.wait()
            return 128 + self.stopped if self.stopped else (128 - result if result < 0 else result)
        finally:
            self.child = None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-dir', type=Path,
                        default=Path.home() / 'Library/Application Support/My Harness/installation')
    parser.add_argument('--database', type=Path, help='Database within the installation data directory; default: harness.sqlite3')
    parser.add_argument('--config', type=Path, help='TOML within the installation configuration directory; default: global.toml if present')
    parser.add_argument('--port', type=int, default=8013, help='Loopback port (default: 8013)')
    parser.add_argument('--temp-dir', type=Path, help='Private temporary directory; default: data/tmp')
    return parser.parse_args(argv)


def start(args):
    if not 1 <= args.port <= 65535:
        raise StartRefused('Port must be between 1 and 65535')
    root = absolute(args.install_dir)
    outside_checkout(root)
    if not root.is_dir():
        raise StartRefused(f'Installation is missing: {root}; run scripts/install explicitly first')
    private_directory(root)
    # The installation lock also prevents a cooperating upgrade/replay while the service runs.
    with instance_lock(root) as instance_descriptor, installation_lock(root) as install_descriptor:
        receipt, generation = current_installation(root)
        request = receipt['request']
        if absolute(request['install_dir']) != root:
            raise StartRefused('Installation receipt belongs to another directory; venvs cannot be relocated')
        data, configuration = (absolute(request[key]) for key in ('data_dir', 'config_dir'))
        if overlap(data, configuration) or any(overlap(root, p) for p in (data, configuration)):
            raise StartRefused('Installation, data and configuration directories must not overlap')
        for path in (data, configuration):
            outside_checkout(path)
            if not path.is_dir():
                raise StartRefused(f'Installation directory is missing; it will not be recreated: {path}')
            private_directory(path)
        database = absolute(args.database or data / 'harness.sqlite3')
        config = absolute(args.config or configuration / 'global.toml')
        temporary = absolute(args.temp_dir or data / 'tmp')
        if not database.is_relative_to(data) or database == data:
            raise StartRefused('--database must be within the receipt data directory')
        if not config.is_relative_to(configuration) or config == configuration:
            raise StartRefused('--config must be within the receipt configuration directory')
        if overlap(temporary, root) or overlap(temporary, configuration) or database.is_relative_to(temporary):
            raise StartRefused('Temporary directory must not contain the database or overlap installation/configuration')
        for path in (database, config, temporary):
            outside_checkout(path)
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = absolute(str(database) + suffix)
            if path.exists():
                regular_file(path)
                if not database.exists():
                    raise StartRefused(f'Database is absent but auxiliary files exist; preserve and inspect them: {path}')
        if config.exists():
            regular_file(config)
        # Reject a busy port before initialization; uvicorn remains authoritative if another process races us.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(('127.0.0.1', args.port))
            except OSError as error:
                raise StartRefused(f'Loopback port {args.port} is unavailable; choose --port or stop its owner: {error}') from None
        private_directory(database.parent)
        private_directory(temporary)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('HARNESS_', 'PYTHON', 'UV_', 'PIP_', 'GIT_'))
               and k not in ('VIRTUAL_ENV', 'CONDA_PREFIX', 'TMPDIR', 'TMP', 'TEMP')}
        env.update(TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
        python = generation / 'venv/bin/python'
        command = [python, '-I', '-B', '-m', 'my_harness.cli']
        selected_config = str(config) if args.config is not None or config.exists() else ''
        children = Children((instance_descriptor, install_descriptor))
        previous = {number: signal.signal(number, children.signal) for number in (signal.SIGINT, signal.SIGTERM)}
        try:
            code = children.run([python, '-I', '-B', '-c', PREFLIGHT, database, selected_config], cwd=data, env=env)
            if children.stopped or code not in (0, 20):
                return code
            archived = code == 20
            if not database.exists():
                code = children.run([*command, 'init-db', '--database', database], cwd=data, env=env)
                if code:
                    return code
                if not database.is_file():
                    raise StartRefused('init-db did not produce a database; no service was started')
            if not selected_config and not archived:
                print('No global TOML: starting the protected configuration assistant at /setup.', flush=True)
            print(f'Starting installed My Harness at http://127.0.0.1:{args.port}; database: {database}.', flush=True)
            serve = [*command, 'serve', '--database', database, '--port', str(args.port),
                     '--configuration-dir', configuration, '--state-dir', data]
            if selected_config and not archived:
                serve += ['--config', selected_config]
            return children.run(serve, cwd=data, env=env)
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)


def main(argv=None):
    # Product files only; does not change the caller's shell umask or existing file permissions.
    previous = os.umask(0o077)
    try:
        return start(parse_args(argv))
    except (StartRefused, InstallRefused, OSError, ValueError, KeyError, TypeError, AssertionError) as error:
        raise SystemExit(f'Startup refused: {error}') from None
    finally:
        os.umask(previous)


if __name__ == '__main__':
    raise SystemExit(main())
