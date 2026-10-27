"""Local migration with a prior snapshot: new database, up to date, or updated after copying.

Migrations only change SQLite; external artifacts are not touched. That is why
the snapshot is of the database (SQLite backup API, integrity and SHA-256) and not
an H5.2 bundle, which requires the current schema. It never restores or deletes anything: on a
failure it keeps database and snapshot for inspection.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from my_harness.launcher import initialize, local_database
from my_harness.storage.backup import RESTORED_USER_VERSION
from my_harness.storage.database import make_engine
from my_harness.storage.schema import require_schema
from my_harness.i18n import tr

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'


class MigrationRefused(ValueError):
    pass


@dataclass(frozen=True)
class MigrationOutcome:
    action: str  # created | current | migrated
    previous: str | None
    revision: str
    snapshot: Path | None = None


def _config(url):
    config = Config()
    config.set_main_option('script_location', str(MIGRATIONS).replace('%', '%%'))
    config.attributes['database_url'] = url
    return config


def _connect(path, mode):
    connection = sqlite3.connect(f'{path.as_uri()}?mode={mode}', uri=True, isolation_level=None, timeout=1)
    connection.execute('PRAGMA trusted_schema=OFF')
    return connection


def _revision(path):
    with closing(_connect(path, 'ro')) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] == RESTORED_USER_VERSION:
            raise MigrationRefused(tr('migrate.restored'))
        try:
            rows = [r[0] for r in db.execute('SELECT version_num FROM alembic_version')]
        except sqlite3.OperationalError as exc:
            raise MigrationRefused(tr('migrate.unversioned')) from exc
        if len(rows) != 1:
            raise MigrationRefused(tr('migrate.revisions'))
        return rows[0]


def _writers_alive(path):
    """A live service or writer on the database prevents migrating it."""
    from my_harness.adapters.processes import liveness
    with closing(_connect(path, 'ro')) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('managed_jobs', 'project_preparation_operations'):
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            if table in tables and {'process_owner', 'owner_closed'} <= columns:
                owners = db.execute(f'SELECT process_owner FROM {table} WHERE process_owner IS NOT NULL '
                                    'AND NOT owner_closed')
                if any(liveness(json.loads(row[0])) == 'alive' for row in owners):
                    return True
        if 'managed_processes' in tables:
            groups = db.execute('SELECT identity FROM managed_processes WHERE identity IS NOT NULL')
            if any(liveness(json.loads(row[0]), group=True) == 'alive' for row in groups):
                return True
        if 'managed_events' in tables:
            commands = db.execute("SELECT payload FROM managed_events WHERE kind='command_process_spawned'")
            if any(liveness(json.loads(row[0])['identity'], group=True) == 'alive' for row in commands):
                return True
        return False


def _unlinked(path):
    if '..' in path.parts or any(part.is_symlink() for part in (path, *path.parents)):
        raise MigrationRefused(tr('migrate.path', path=path))


def _snapshot_directory(path, directory):
    directory = Path(directory).expanduser()
    if not directory.is_absolute():
        raise MigrationRefused(tr('migrate.snapshots_absolute'))
    _unlinked(directory)
    if any(os.path.lexists(parent / '.git') for parent in (directory, *directory.parents)):
        raise MigrationRefused(tr('migrate.snapshots_outside'))
    with closing(_connect(path, 'ro')) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('managed_runs', 'managed_activations', 'managed_phases', 'registered_projects',
                      'project_preparation_operations'):
            if table in tables:
                for (root,) in db.execute(f'SELECT DISTINCT root FROM {table}'):
                    if directory.resolve().is_relative_to(Path(root).resolve()):
                        raise MigrationRefused(tr('migrate.snapshots_registered'))
    return directory


def _snapshot(path, revision, target, directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = directory / f'{path.stem}-{revision}-{stamp}.sqlite3'
    # Exclusive: never overwrite an earlier copy.
    with destination.open('xb'):
        pass
    os.chmod(destination, 0o600)
    with closing(_connect(path, 'ro')) as source, closing(_connect(destination, 'rw')) as copy:
        source.backup(copy)
        if copy.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise MigrationRefused(tr('migrate.snapshot_integrity', snapshot=destination))
        if copy.execute('SELECT version_num FROM alembic_version').fetchall() != [(revision,)]:
            raise MigrationRefused(tr('migrate.snapshot_revision', snapshot=destination))
    raw = destination.read_bytes()
    manifest = {'format': 'premigration-1', 'source': str(path), 'source_revision': revision,
                'target_revision': target, 'snapshot': destination.name,
                'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw),
                'created_at': datetime.now(timezone.utc).isoformat()}
    with destination.with_suffix('.json').open('x') as file:
        json.dump(manifest, file, indent=2, sort_keys=True)
        file.flush()
        os.fsync(file.fileno())
    with destination.open('rb') as file:
        os.fsync(file.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return destination


def prepare_database(value: str, snapshots: Path) -> MigrationOutcome:
    """Create if missing; if migrations are pending, copy and then `upgrade head`."""
    return _prepare_database(value, snapshots, create=True)


def migrate_database(value: str, snapshots: Path, *, writers_stopped: bool = False) -> MigrationOutcome:
    """Installed entry point: never creates databases or infers that the service is stopped."""
    if writers_stopped is not True:
        raise MigrationRefused(tr('migrate.writers'))
    path, _ = local_database(value)
    _unlinked(path)
    for suffix in ('-wal', '-shm', '-journal'):
        auxiliary = Path(str(path) + suffix)
        _unlinked(auxiliary)
        if auxiliary.exists() and not auxiliary.is_file():
            raise MigrationRefused(tr('migrate.sidecars'))
    return _prepare_database(value, snapshots, create=False)


def _prepare_database(value, snapshots, *, create):
    path, url = local_database(value)
    head = ScriptDirectory.from_config(_config(url)).get_current_head()
    if not path.exists():
        if not create:
            raise MigrationRefused(tr('migrate.missing'))
        initialize(value)
        return MigrationOutcome('created', None, head)
    if not path.is_file() or path.is_symlink():
        raise MigrationRefused(tr('migrate.regular'))
    current = _revision(path)
    known = {script.revision for script in ScriptDirectory.from_config(_config(url)).walk_revisions()}
    if current not in known:
        raise MigrationRefused(tr('migrate.unknown_revision', revision=current))
    if _writers_alive(path):
        raise MigrationRefused(tr('migrate.alive'))
    if not create:
        snapshots = _snapshot_directory(path, snapshots)
    if current == head:
        return MigrationOutcome('current', current, head)
    snapshot = _snapshot(path, current, head, Path(snapshots))
    try:
        command.upgrade(_config(url), 'head')
        engine = make_engine(url)
        try:
            require_schema(engine)
        finally:
            engine.dispose()
    except Exception as exc:
        raise MigrationRefused(tr('migrate.failed', snapshot=snapshot, error=exc)) from exc
    return MigrationOutcome('migrated', current, head, snapshot)
