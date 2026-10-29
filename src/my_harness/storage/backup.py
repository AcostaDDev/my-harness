"""H5.2: verified local bundles; no execution port or checkout write."""

import base64
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat

from my_harness.core.engine.serialization import load_history
from my_harness.storage import run_projection
from my_harness.storage.models import Base
from my_harness.storage.schema import SCHEMA_REVISION, triggers_intact
from my_harness.i18n import tr

FORMAT = 3  # P001-T003: accounting digests/native links verified in the same snapshot (D257)
RESTORED_USER_VERSION = 0x483532
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILES = 10000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024


class BackupError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _absolute(path):
    path = Path(path).expanduser().absolute()
    if '..' in path.parts or path.resolve() != path:
        raise BackupError(tr('backup.path_link', path=path))
    return path


def _relative(path):
    if not isinstance(path, str) or not path or any(p in ('', '.', '..') for p in path.split('/')) or PurePosixPath(path).is_absolute():
        raise BackupError(tr('backup.unsafe_relative'))
    return path


def _historical_path(path):
    # The reference is frozen data: verifying a bundle does not query its originals.
    if not isinstance(path, str) or not path.startswith('/') or any(p in ('.', '..', '') for p in path.split('/')[1:]):
        raise BackupError(tr('backup.historical_absolute'))
    return Path(path)


def _read(path, limit=MAX_FILE_BYTES):
    """Each component is opened without following links; special files never block."""
    path = _absolute(path)
    descriptors = []
    try:
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(fd)
        for part in path.parts[1:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        descriptors.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BackupError(tr('backup.not_regular', path=path))
        if before.st_size > limit:
            raise BackupError(tr('backup.size_limit', path=path))
        chunks, size = [], 0
        while chunk := os.read(fd, 65536):
            size += len(chunk)
            if size > limit:
                raise BackupError(tr('backup.size_limit', path=path))
            chunks.append(chunk)
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise BackupError(tr('backup.changed_reading', path=path))
        return b''.join(chunks)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _connect(path, mode='ro'):
    connection = sqlite3.connect(f'{path.as_uri()}?mode={mode}', uri=True, isolation_level=None, timeout=1)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA trusted_schema=OFF')
    if mode == 'ro':
        connection.execute('PRAGMA query_only=ON')
    return connection


def is_read_only_archive(engine):
    from sqlalchemy import text
    with engine.connect() as connection:
        return connection.scalar(text('PRAGMA user_version')) == RESTORED_USER_VERSION


def _integrity(db, *, restored=False):
    if db.execute('PRAGMA integrity_check').fetchall()[0][0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
        raise BackupError(tr('backup.integrity'))
    revisions = [r[0] for r in db.execute('SELECT version_num FROM alembic_version')]
    if revisions != [SCHEMA_REVISION]:
        raise BackupError(tr('backup.schema_version'))
    expected_version = RESTORED_USER_VERSION if restored else 0
    if db.execute('PRAGMA user_version').fetchone()[0] != expected_version:
        raise BackupError(tr('backup.restore_version'))
    for name, table in Base.metadata.tables.items():
        columns = {r['name'] for r in db.execute(f'PRAGMA table_info("{name}")')}
        if columns != set(table.columns.keys()):
            raise BackupError(tr('backup.schema_table', name=name))
    if not triggers_intact(db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()):
        raise BackupError(tr('backup.schema_triggers'))
    projected = dict.fromkeys(run_projection.TABLES, 0)
    for run_id, history_json in db.execute('SELECT id, history_json FROM managed_runs ORDER BY id'):
        try:
            history = load_history(history_json)
            for cycle in history.cycles:
                for entry in cycle.validation.entries:
                    for report in entry.reports:
                        if report.original_base64 is not None:
                            raw = base64.b64decode(report.original_base64, validate=True)
                            if _hash(raw) != report.sha256 or len(raw) != report.size_bytes:
                                raise BackupError(tr('backup.junit'))
            # D142: the derived projection must match the recomputed one; it is never rebuilt here.
            for name, count in run_projection.verify(db, run_id, history_json, history).items():
                projected[name] += count
        except run_projection.ProjectionMismatch as exc:
            raise BackupError(str(exc)) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupError(tr('backup.history', error=exc)) from exc
    for name, count in projected.items():
        if db.execute(f'SELECT count(*) FROM {name}').fetchone()[0] != count:
            raise BackupError(tr('backup.projection', projection=run_projection.PROJECTION, name=name))
    # P002-T006: every offloaded trace artifact matches its digest and size, and every reference has its bytes,
    # including the references inside an offloaded JSON payload.
    stored = {}
    for event_id, sha256, size, media, content in db.execute(
            'SELECT event_id, sha256, size, media, content FROM trace_artifacts'):
        if _hash(content) != sha256 or len(content) != size:
            raise BackupError(tr('backup.trace_artifact', sha256=sha256))
        stored.setdefault(event_id, {})[sha256] = (media, content)
    from my_harness.core.engine.trace_payload import contained_references
    for event_id, payload in db.execute('SELECT event_id, payload FROM trace_events'):
        artifacts = stored.get(event_id, {})
        try:
            references = list(contained_references(json.loads(payload), artifacts))
        except (ValueError, UnicodeDecodeError) as exc:
            raise BackupError(tr('backup.trace_artifact', sha256=event_id)) from exc
        for reference in references:
            if reference.get('sha256') not in artifacts:
                raise BackupError(tr('backup.trace_artifact', sha256=reference.get('sha256')))
    from my_harness.storage.accounting_backup import AccountingMismatch, verify
    from my_harness.storage.frozen_context import verify_archive
    try:
        verify_archive(db)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise BackupError(tr('backup.context')) from exc
    try:
        return verify(db)
    except (AccountingMismatch, KeyError, TypeError, ValueError) as exc:
        raise BackupError(tr('backup.accounting', error=exc)) from exc


def _refusal_boundary(db, row, spec, capture):
    """An artifact exemption needs positive no-launch evidence and no contradictory observed output."""
    from my_harness.core.engine.usage_capture import refusal_boundary
    boundary = refusal_boundary(spec, capture, row['identity'] is not None)
    if boundary is None:
        if spec.get('launch_permitted') is False or isinstance(capture, dict) and capture.get('launch_permitted') is False:
            raise BackupError(tr('backup.prelaunch_evidence'))
        return None
    if (row['status'] != 'STOPPED' or capture.get('group_state') != 'dead' or 'artifacts' in capture or
            boundary == 'before_spawn' and any(k in spec for k in ('artifacts', 'prompt_path', 'prompt_sha256'))):
        raise BackupError(tr('backup.prelaunch_evidence'))
    kinds = ('stream_bytes', 'agent_event', 'context_input_delivered')
    if boundary == 'before_spawn':
        kinds += ('process_spawned',)
    for event in db.execute('SELECT kind,payload FROM managed_events WHERE run_id='
                            '(SELECT run_id FROM managed_attempts WHERE id=?)', (row['attempt_id'],)):
        if event['kind'] in kinds and json.loads(event['payload']).get('attempt_id') == row['attempt_id']:
            raise BackupError(tr('backup.prelaunch_evidence'))
    return boundary


def _references(db):
    """Only known external locations; never search arbitrarily for 'path' fields."""
    refs = {}

    def add(source, label, sha=None, size=None, *, optional=False, chunks=()):
        path = str(_historical_path(str(source)))
        ref = refs.setdefault(path, {'labels': [], 'expected': [], 'optional': True, 'chunks': []})
        ref['labels'].append(label)
        ref['optional'] &= optional
        if sha is not None:
            ref['expected'].append((sha, size))
        ref['chunks'].extend(chunks)

    for row in db.execute('SELECT * FROM managed_processes WHERE job_id IS NOT NULL ORDER BY attempt_id'):
        spec, capture = json.loads(row['spec']), json.loads(row['capture']) if row['capture'] else None
        refusal = _refusal_boundary(db, row, spec, capture)
        if refusal == 'before_spawn':
            continue  # No prompt, stream path, hash or file was created or promised.
        directory = _historical_path(spec['artifacts'])
        prompt = _historical_path(spec['prompt_path'])
        if prompt != directory / 'prompt.txt':
            raise BackupError(tr('backup.prompt_reference'))
        add(prompt, f"process:{row['attempt_id']}:prompt", spec['prompt_sha256'])
        if refusal == 'before_go':
            continue  # The real prepared prompt remains required; target streams were never created.
        for stream in ('stdout', 'stderr'):
            chunks = []
            for event in db.execute("SELECT payload FROM managed_events WHERE kind='stream_bytes' AND run_id=(SELECT run_id FROM managed_attempts WHERE id=?) ORDER BY sequence", (row['attempt_id'],)):
                event = json.loads(event[0])
                if event.get('attempt_id') == row['attempt_id'] and event['stream'] == stream:
                    chunks.append((event['offset'], event['size'], event['sha256']))
            artifact = capture['artifacts'][stream] if capture else None
            path = directory / f'{stream}.bin'
            if artifact and _historical_path(artifact['path']) != path:
                raise BackupError(tr('backup.stream_reference'))
            add(path, f"process:{row['attempt_id']}:{stream}", artifact['sha256'] if artifact else None,
                artifact['size'] if artifact else None, optional=not artifact and not chunks, chunks=chunks)
    snapshots = set()
    for row in db.execute('SELECT * FROM managed_activations ORDER BY id'):
        snapshots.add(row['snapshot_root'])
        if row['manifest_json']:
            if _hash(row['manifest_json'].encode()) != row['manifest_sha256']:
                raise BackupError(tr('backup.migration_manifest'))
            manifest = json.loads(row['manifest_json'])
            if manifest['snapshot_root'] != row['snapshot_root']:
                raise BackupError(tr('backup.migration_snapshot'))
            for artifact in manifest['artifacts']:
                if artifact['sha256']:
                    add(Path(row['snapshot_root']) / _relative(artifact['path']),
                        f"migration:{row['id']}:snapshot:{artifact['path']}", artifact['sha256'], artifact['size_bytes'])
        if row['export_path']:
            add(row['export_path'], f"migration:{row['id']}:export", row['export_sha256'])
    for row in db.execute('SELECT * FROM legacy_artifacts ORDER BY root,path'):
        if row['root'] in snapshots and row['sha256']:
            add(Path(row['root']) / _relative(row['path']), f"migration-snapshot:{row['root']}:{row['path']}", row['sha256'], row['size_bytes'])
    from my_harness.storage.configuration_backup import references
    references(db, add)
    return refs


def _check_bytes(data, ref):
    if any(label.startswith('configuration:') for label in ref['labels']) and len(data) > 65536:
        raise BackupError(tr('backup.reference_hash'))
    for sha, size in ref['expected']:
        if _hash(data) != sha or (size is not None and len(data) != size):
            raise BackupError(tr('backup.reference_hash'))
    previous = 0
    for offset, size, sha in ref['chunks']:
        if type(offset) is not int or type(size) is not int or offset != previous or size <= 0 or _hash(data[offset:offset + size]) != sha:
            raise BackupError(tr('backup.stream_range'))
        previous = offset + size


def _new_destination(destination):
    destination = _absolute(destination)
    if not destination.parent.is_dir():
        raise BackupError(tr('backup.parent'))
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise BackupError(tr('backup.destination_new')) from exc
    return destination


def _finish(destination, manifest):
    raw = _json(manifest)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise BackupError(tr('backup.manifest_limit'))
    _write(destination / 'manifest.json', raw)
    _write(destination / 'COMPLETE', _hash(raw).encode())
    for directory, _, _ in os.walk(destination, topdown=False):
        _sync(Path(directory))
    _sync(destination.parent)


def _create_backup(database, destination, *, artifact_roots=(), writers_stopped=False, hook=None):
    """Service/writers explicitly stopped; BEGIN IMMEDIATE closes DB races."""
    if writers_stopped is not True:
        raise BackupError(tr('backup.writers'))
    database, destination = _absolute(database), _absolute(destination)
    _read(database)  # validate path/type before opening SQLite
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = Path(str(database) + suffix)
        if os.path.lexists(sidecar):
            _read(sidecar)  # SQLite also opens these files; do not admit links/special files.
    roots = tuple(_absolute(root) for root in artifact_roots)
    if any(not r.is_dir() or r == Path('/') for r in roots):
        raise BackupError(tr('backup.artifact_roots'))
    if destination == database or any(destination.is_relative_to(r) or r.is_relative_to(destination) for r in roots):
        raise BackupError(tr('backup.overlap'))
    before = database.stat()
    with closing(_connect(database, 'rw')) as lock:
        lock.execute('BEGIN IMMEDIATE')
        try:
            accounting_inventory = _integrity(lock)
            from my_harness.adapters.processes import liveness
            for row in lock.execute('SELECT process_owner, owner_closed FROM managed_jobs WHERE process_owner IS NOT NULL'):
                if not row['owner_closed'] and liveness(json.loads(row['process_owner'])) == 'alive':
                    raise BackupError(tr('backup.service_owner'))
            for row in lock.execute('SELECT process_owner, owner_closed FROM project_preparation_operations WHERE process_owner IS NOT NULL'):
                if not row['owner_closed'] and liveness(json.loads(row['process_owner'])) == 'alive':
                    raise BackupError(tr('backup.preparation_owner'))
            for row in lock.execute('SELECT identity FROM managed_processes WHERE identity IS NOT NULL'):
                if liveness(json.loads(row['identity']), group=True) == 'alive':
                    raise BackupError(tr('backup.process_group'))
            from my_harness.storage.command_processes import persisted_identities
            if any(liveness(value, group=True) == 'alive' for value in persisted_identities(lock)):
                raise BackupError(tr('backup.validation_group'))
            for row in lock.execute("SELECT payload FROM configuration_operations WHERE kind='ASSIST'"):
                payload = json.loads(row[0])
                if (not payload.get('owner_closed') and liveness(payload['owner']) == 'alive'
                        or payload.get('process', {}).get('identity')
                        and liveness(payload['process']['identity'], group=True) == 'alive'):
                    raise BackupError(tr('backup.service_owner'))
            checkouts = {Path(r[0]) for r in lock.execute('SELECT root FROM managed_runs UNION SELECT root FROM managed_activations UNION SELECT root FROM managed_phases UNION SELECT root FROM registered_projects UNION SELECT root FROM project_preparation_operations')}
            if any(destination.is_relative_to(r) or any(root.is_relative_to(r) or r.is_relative_to(root) for root in roots) for r in checkouts):
                raise BackupError(tr('backup.outside_checkouts'))
            # Do not test death by lease or modify jobs/locks. An uncertain state may be copied,
            # always under the stop declaration and with all its bytes verifiable.
            destination = _new_destination(destination)
            db_path = destination / 'state.sqlite3'
            with closing(_connect(database)) as source, closing(_connect(db_path, 'rwc')) as target:
                source.backup(target)
                _integrity(target)
                # The copy itself also prevents accidentally opening another writing queue.
                target.execute(f'PRAGMA user_version={RESTORED_USER_VERSION}')
            os.chmod(db_path, 0o600)
            _sync(db_path)
            if hook:
                hook('database_copied')
            refs = _references(lock)
            from my_harness.storage.configuration_backup import inventory, read_private
            configuration = inventory(lock)[0]
            from my_harness.storage.retention import authorized_absences
            purged = authorized_absences(lock, refs)
            files, absent, total = [], [], 0
            if len(refs) > MAX_FILES:
                raise BackupError(tr('backup.too_many_references'))
            for index, (source, ref) in enumerate(sorted(refs.items())):
                path = Path(source)
                if not any(path.is_relative_to(root) for root in roots):
                    raise BackupError(tr('backup.outside_root', source=source))
                if source in purged:
                    if os.path.lexists(path):
                        raise BackupError(tr('backup.purged_back'))
                    continue
                try:
                    raw = read_private(source, ref) if any(label.startswith('configuration:') for label in ref['labels']) else _read(path)
                    if raw is None:
                        raise FileNotFoundError(source)
                except FileNotFoundError:
                    if not ref['optional']:
                        raise BackupError(tr('backup.artifact_missing', source=source))
                    absent.append(source)
                    continue
                _check_bytes(raw, ref)
                total += len(raw)
                if total > MAX_TOTAL_BYTES:
                    raise BackupError(tr('backup.total_limit'))
                relative = f'artifacts/{index:06d}.bin'
                _write(destination / relative, raw)
                files.append({'source': source, 'path': relative, 'sha256': _hash(raw), 'size_bytes': len(raw), 'labels': ref['labels']})
                if hook:
                    hook('artifact_copied')
            # Rereading the set at the end detects changes between files, optional ones included.
            for item in files:
                ref = refs[item['source']]
                raw = (read_private(item['source'], ref) if any(label.startswith('configuration:') for label in ref['labels'])
                       else _read(item['source']))
                if raw is None:
                    raise BackupError(tr('backup.changed_copy'))
                if _hash(raw) != item['sha256'] or len(raw) != item['size_bytes']:
                    raise BackupError(tr('backup.changed_copy'))
            if any(os.path.lexists(path) for path in absent):
                raise BackupError(tr('backup.appeared'))
            if any(os.path.lexists(path) for path in purged):
                raise BackupError(tr('backup.purged_copy'))
            after = database.stat()
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise BackupError(tr('backup.source_replaced'))
            raw_db = _read(db_path)
            manifest = {'format': FORMAT, 'kind': 'backup', 'schema': SCHEMA_REVISION,
                        'consistency': 'service-and-writers-stopped/sqlite-backup/write-lock',
                        'database': {'path': 'state.sqlite3', 'sha256': _hash(raw_db), 'size_bytes': len(raw_db)},
                        'configuration': configuration, 'accounting': accounting_inventory,
                        'files': files, 'absent_optional': absent, 'absent_purged': purged,
                        'external_legacy_sources': [r[0] for r in lock.execute('SELECT root FROM legacy_sources ORDER BY root') if r[0] not in {r[0] for r in lock.execute('SELECT snapshot_root FROM managed_activations')}],
                        'runs': [dict(r) for r in lock.execute('SELECT id,root,status,purpose FROM managed_runs ORDER BY id')],
                        'execution_authorized': False}
            _finish(destination, manifest)
            return manifest
        finally:
            lock.rollback()


def create_backup(database, destination, *, artifact_roots=(), writers_stopped=False, hook=None):
    try:
        return _create_backup(database, destination, artifact_roots=artifact_roots,
                              writers_stopped=writers_stopped, hook=hook)
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(tr('backup.unpublished', error=exc)) from exc


def verify_bundle(bundle):
    """Verifies manifest, DB, embedded originals and complete correspondence of references."""
    bundle = _absolute(bundle)
    try:
        raw = _read(bundle / 'manifest.json', MAX_MANIFEST_BYTES)
        if _read(bundle / 'COMPLETE', 64) != _hash(raw).encode():
            raise BackupError(tr('backup.bundle_incomplete'))
        manifest = json.loads(raw)
        if type(manifest['format']) is int and manifest['format'] in (1, 2, FORMAT) and manifest['schema'] != SCHEMA_REVISION:
            # Older matching-schema bundles stay readable by their own release; this one needs an explicit copy.
            raise BackupError(tr('backup.upgrade_required'))
        if (type(manifest['format']) is not int or manifest['format'] not in (1, 2, FORMAT) or manifest['schema'] != SCHEMA_REVISION or
                manifest['kind'] not in ('backup', 'restored') or manifest['execution_authorized'] is not False):
            raise BackupError(tr('backup.bundle_format'))
        database = manifest['database']
        if database['path'] != 'state.sqlite3':
            raise BackupError(tr('backup.sqlite_path'))
        raw_db = _read(bundle / database['path'])
        if _hash(raw_db) != database['sha256'] or len(raw_db) != database['size_bytes']:
            raise BackupError(tr('backup.sqlite_hash'))
        for suffix in ('-wal', '-journal'):
            sidecar = bundle / (database['path'] + suffix)
            if os.path.lexists(sidecar) and _read(sidecar):
                raise BackupError(tr('backup.sidecars'))
        if len(manifest['files']) > MAX_FILES:
            raise BackupError(tr('backup.too_many_artifacts'))
        with closing(_connect(bundle / 'state.sqlite3')) as db:
            accounting_inventory = _integrity(db, restored=True)
            from my_harness.storage.configuration_backup import inventory
            configuration = inventory(db)[0]
            if (manifest['format'] == 1 and any(configuration.values())
                    or manifest['format'] >= 2 and manifest.get('configuration') != configuration):
                raise BackupError(tr('backup.configuration_bundle_required'))
            if (manifest['format'] < FORMAT and any(accounting_inventory.values())
                    or manifest['format'] == FORMAT and manifest.get('accounting') != accounting_inventory):
                raise BackupError(tr('backup.accounting', error='inventory'))
            refs = _references(db)
            from my_harness.storage.retention import authorized_absences
            purged = authorized_absences(db, refs)
            if manifest.get('absent_purged', {}) != purged:
                raise BackupError(tr('backup.purged_audit'))
            runs = [dict(r) for r in db.execute('SELECT id,root,status,purpose FROM managed_runs ORDER BY id')]
            if manifest['runs'] != runs:
                raise BackupError(tr('backup.runs_inventory'))
        sources, paths, total = set(), set(), 0
        for item in manifest['files']:
            relative = _relative(item['path'])
            source = item['source']
            if not relative.startswith('artifacts/') or relative in paths or source in sources or source not in refs:
                raise BackupError(tr('backup.duplicate_references'))
            data = _read(bundle / relative)
            total += len(data)
            if total > MAX_TOTAL_BYTES or _hash(data) != item['sha256'] or len(data) != item['size_bytes']:
                raise BackupError(tr('backup.artifact_hash'))
            _check_bytes(data, refs[source])
            if item['labels'] != refs[source]['labels']:
                raise BackupError(tr('backup.provenance'))
            sources.add(source)
            paths.add(relative)
        absent = manifest['absent_optional']
        if (len(set(absent)) != len(absent) or sources & set(absent) or
                (sources | set(absent)) & set(purged) or set(refs) != sources | set(absent) | set(purged) or
                any(not refs[s]['optional'] for s in absent)):
            raise BackupError(tr('backup.references_missing'))
        return manifest
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(tr('backup.bundle_invalid', error=exc)) from exc


def restore_backup(bundle, destination):
    bundle, destination = _absolute(bundle), _absolute(destination)
    if destination.is_relative_to(bundle) or bundle.is_relative_to(destination):
        raise BackupError(tr('backup.restore_overlap'))
    manifest = verify_bundle(bundle)  # Nothing created until the complete originals are verified.
    with closing(_connect(bundle / 'state.sqlite3')) as db:
        checkouts = [Path(r[0]) for r in db.execute('SELECT root FROM managed_runs UNION SELECT root FROM managed_activations UNION SELECT root FROM managed_phases UNION SELECT root FROM registered_projects UNION SELECT root FROM project_preparation_operations')]
    if any(destination.is_relative_to(r) or r.is_relative_to(destination) for r in checkouts):
        raise BackupError(tr('backup.restore_checkouts'))
    destination = _new_destination(destination)
    raw = _read(bundle / 'state.sqlite3')
    if _hash(raw) != manifest['database']['sha256']:
        raise BackupError(tr('backup.sqlite_changed'))
    _write(destination / 'state.sqlite3', raw)
    # Persistent internal mark: make_engine enables query_only, even when the file is moved.
    with closing(_connect(destination / 'state.sqlite3', 'rw')) as db:
        db.execute(f'PRAGMA user_version={RESTORED_USER_VERSION}')
    for item in manifest['files']:
        data = _read(bundle / item['path'])
        if _hash(data) != item['sha256']:
            raise BackupError(tr('backup.artifact_changed'))
        _write(destination / item['path'], data)
    raw = _read(destination / 'state.sqlite3')
    restored = {**manifest, 'kind': 'restored', 'restored_from': manifest['database']['sha256'],
                'database': {**manifest['database'], 'sha256': _hash(raw), 'size_bytes': len(raw)}}
    _finish(destination, restored)
    verify_bundle(destination)
    return restored


def restored_artifact(engine, source):
    """Resolve historical references without rewriting snapshots or going back to the originals."""
    if not is_read_only_archive(engine):
        return None
    bundle = Path(engine.url.database).resolve().parent
    raw = _read(bundle / 'manifest.json', MAX_MANIFEST_BYTES)
    if _read(bundle / 'COMPLETE', 64) != _hash(raw).encode():
        raise BackupError(tr('backup.restored_manifest'))
    manifest = json.loads(raw)
    return next((bundle / _relative(item['path']) for item in manifest['files'] if item['source'] == str(source)), None)


def _verify_files(bundle, manifest):
    """Structural check of an older bundle's own bytes; its schema-specific checks belong to its release."""
    database = manifest['database']
    raw_db = _read(bundle / _relative(database['path']))
    if database['path'] != 'state.sqlite3' or _hash(raw_db) != database['sha256'] or len(raw_db) != database['size_bytes']:
        raise BackupError(tr('backup.sqlite_hash'))
    for item in manifest['files']:
        relative = _relative(item['path'])
        data = _read(bundle / relative)
        if not relative.startswith('artifacts/') or _hash(data) != item['sha256'] or len(data) != item['size_bytes']:
            raise BackupError(tr('backup.artifact_hash'))
    return raw_db


def upgrade_bundle(bundle, destination):
    """Explicit archive upgrade: a NEW format-3 bundle migrated from a copy; the original stays byte-identical.

    Only SQLite changes (the same Alembic chain as `migrate`); artifacts are copied verbatim and re-verified.
    The copy keeps the query-only restore mark and grants no execution, activation or recalculation.
    """
    bundle, destination = _absolute(bundle), _absolute(destination)
    if destination.is_relative_to(bundle) or bundle.is_relative_to(destination):
        raise BackupError(tr('backup.restore_overlap'))
    try:
        raw = _read(bundle / 'manifest.json', MAX_MANIFEST_BYTES)
        if _read(bundle / 'COMPLETE', 64) != _hash(raw).encode():
            raise BackupError(tr('backup.bundle_incomplete'))
        manifest = json.loads(raw)
        if (type(manifest.get('format')) is not int or manifest['format'] not in (1, 2)
                or manifest.get('kind') not in ('backup', 'restored') or manifest.get('execution_authorized') is not False):
            raise BackupError(tr('backup.bundle_format'))
        raw_db = _verify_files(bundle, manifest)
        destination = _new_destination(destination)
        db_path = destination / 'state.sqlite3'
        _write(db_path, raw_db)
        with closing(_connect(db_path, 'rw')) as db:
            db.execute('PRAGMA user_version=0')  # Only for this private copy's migration; restored again below.
        from alembic import command
        from my_harness.storage.migrate import _config
        command.upgrade(_config(f'sqlite:///{db_path}'), 'head')
        with closing(_connect(db_path, 'rw')) as db:
            db.execute(f'PRAGMA user_version={RESTORED_USER_VERSION}')
        for suffix in ('-wal', '-shm', '-journal'):
            sidecar = Path(str(db_path) + suffix)
            if os.path.lexists(sidecar):
                os.unlink(sidecar)
        _sync(db_path)
        with closing(_connect(db_path)) as db:
            accounting_inventory = _integrity(db, restored=True)
            from my_harness.storage.configuration_backup import inventory
            configuration = inventory(db)[0]
        for item in manifest['files']:
            _write(destination / item['path'], _read(bundle / item['path']))
        upgraded = _read(db_path)
        result = {**manifest, 'format': FORMAT, 'schema': SCHEMA_REVISION, 'configuration': configuration,
                  'accounting': accounting_inventory,
                  'database': {'path': 'state.sqlite3', 'sha256': _hash(upgraded), 'size_bytes': len(upgraded)},
                  'upgraded_from': {'format': manifest['format'], 'schema': manifest['schema'],
                                    'manifest_sha256': _hash(raw), 'database_sha256': manifest['database']['sha256']}}
        _finish(destination, result)
        verify_bundle(destination)
        return result
    except (OSError, sqlite3.Error, KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, BackupError):
            raise
        raise BackupError(tr('backup.bundle_invalid', error=exc)) from exc
