"""Local development with a single command: dependencies up to date, migrated database, API :8013 and Vite :5173.

Usage: scripts/dev [--database PATH] [--config TOML]

`uv run --frozen` (in scripts/dev) syncs the Python environment from uv.lock. This
script reinstalls the frontend only if its lock changed, migrates the development SQLite
with a prior snapshot (storage/migrate.py), starts the API and Vite in their own
process groups and stops them together on Ctrl+C or when one of them exits.
No network: npm and uv work offline with the caches in .local/.
"""
import argparse
import hashlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from threading import Thread
import time

from toolchain import check_tools

ROOT = Path(__file__).resolve().parents[1]
API_PORT, UI_PORT = 8013, 5173  # fixed by frontend/package.json and vite.config.ts
STAMP = ROOT / '.local/dev/frontend-lock.sha256'


def lock_digest(root=ROOT):
    return hashlib.sha256((root / 'frontend/package-lock.json').read_bytes()).hexdigest()


def frontend_install_needed(root=ROOT, stamp=STAMP):
    if not (root / 'frontend/node_modules').is_dir() or not stamp.is_file():
        return True
    return stamp.read_text().strip() != lock_digest(root)


def ensure_frontend(root=ROOT, stamp=STAMP):
    if not frontend_install_needed(root, stamp):
        return False
    print('frontend: lock changed or dependencies missing; offline npm ci', flush=True)
    subprocess.run(['npm', 'ci', '--offline', '--ignore-scripts', '--no-audit', '--no-fund',
                    '--cache', str(root / '.local/npm-cache')], cwd=root / 'frontend', check=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(lock_digest(root) + '\n')
    return True


def port_free(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def listening(port):
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(('127.0.0.1', port)) == 0


def stop(process, grace=10.0):
    """Terminate the child's own process group; kill it only if it does not exit in time."""
    if process.poll() is not None:
        return process.returncode
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            return process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            continue
    return process.wait()


class Services:
    """Children in their own sessions; the parent forwards the stop and leaves no orphans."""

    def __init__(self):
        self.children = []
        self.stopping = False

    def start(self, name, argv, *, env=None, cwd=ROOT, relay=None):
        process = subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True,
                                   stdout=subprocess.PIPE if relay else None,
                                   stderr=subprocess.STDOUT if relay else None, text=True)
        if relay:
            Thread(target=self._relay, args=(process, relay), daemon=True).start()
        self.children.append((name, process))
        return process

    @staticmethod
    def _relay(process, relay):
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            relay(line)

    def wait_port(self, port, process, timeout=30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stopping:
            if process.poll() is not None:
                return False
            if listening(port):
                return True
            time.sleep(0.2)
        return False

    def request_stop(self, *_):
        self.stopping = True

    def run(self):
        """Until Ctrl+C/TERM or until a child exits; returns the exit code."""
        code = 0
        while not self.stopping:
            for name, process in self.children:
                if process.poll() is not None:
                    print(f'{name} exited with code {process.returncode}; stopping the rest', flush=True)
                    code = process.returncode or 1
                    self.stopping = True
                    break
            time.sleep(0.2)
        self.close()
        return code

    def close(self):
        for _, process in reversed(self.children):
            stop(process)


def api_command(database, config):
    env = {**os.environ, 'HARNESS_DATABASE_URL': f'sqlite:///{database}', 'PYTHONUNBUFFERED': '1'}
    if config is not None:
        if env.get('HARNESS_MANAGED_CONFIG'):
            raise SystemExit('--config and HARNESS_MANAGED_CONFIG are incompatible; choose a single composition.')
        env.update(HARNESS_MANAGED_CONFIG='my_harness.services.local_config:from_environment',
                   HARNESS_LOCAL_CONFIG=str(config))
    argv = [sys.executable, '-m', 'uvicorn', 'my_harness.api.app:create_app', '--factory',
            '--host', '127.0.0.1', '--port', str(API_PORT), '--workers', '1',
            '--no-proxy-headers', '--no-access-log']
    return argv, env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--database', type=Path, default=ROOT / '.local/harness.sqlite3',
                        help='development SQLite (default .local/harness.sqlite3)')
    parser.add_argument('--config', type=Path,
                        help='optional local-config TOML; without it the managed API only reads')
    args = parser.parse_args(argv)
    database = args.database.expanduser().absolute()
    config = args.config.expanduser().absolute() if args.config else None

    check_tools()
    busy = [port for port in (API_PORT, UI_PORT) if not port_free(port)]
    if busy:
        raise SystemExit(f'Ports in use on 127.0.0.1: {busy}; stop the previous service.')
    ensure_frontend()
    from my_harness.storage.migrate import MigrationRefused, prepare_database
    try:
        outcome = prepare_database(str(database), ROOT / '.local/backups')
    except (MigrationRefused, ValueError) as exc:
        raise SystemExit(f'Database: {exc}') from None
    print(f'database: {database} ({outcome.action}, revision {outcome.revision})'
          + (f'; prior snapshot {outcome.snapshot}' if outcome.snapshot else ''), flush=True)
    if config is not None:
        from my_harness.services.local_config import load_local_config
        load_local_config(config)  # validate before launching anything; runs no processes

    services = Services()
    signal.signal(signal.SIGINT, services.request_stop)
    signal.signal(signal.SIGTERM, services.request_stop)
    key = []  # path from the service's access-key line (my_harness.api.session); keep the match in sync
    api_argv, api_env = api_command(database, config)
    api = services.start('api', api_argv, env=api_env,
                         relay=lambda line: key.append(line.split(' at ', 1)[1].strip())
                         if 'access key at' in line else None)
    if not services.wait_port(API_PORT, api):
        services.close()
        return 0 if services.stopping else 1
    ui = services.start('ui', ['npm', '--prefix', 'frontend', 'run', 'dev'])
    if not services.wait_port(UI_PORT, ui):
        services.close()
        return 0 if services.stopping else 1
    print(f'\nMy Harness (development)\n  UI:    http://127.0.0.1:{UI_PORT}\n  API:   http://127.0.0.1:{API_PORT}\n'
          f'  Key:   {key[0] if key else "see the API access-key line"}\n  Ctrl+C stops both.\n', flush=True)
    return services.run()


if __name__ == '__main__':
    sys.exit(main())
