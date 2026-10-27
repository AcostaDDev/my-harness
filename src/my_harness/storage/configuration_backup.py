"""Data-only configuration inventory for backup format 2; never follow restored paths."""
import json
from pathlib import Path

from my_harness.services.configuration import MAX_BYTES, digest
from my_harness.services.managed_runtime import PROJECT_ID
from my_harness.storage.configuration_files import ConfigurationFiles


def inventory(db):
    scopes = [dict(row) for row in db.execute('SELECT * FROM configuration_scopes ORDER BY scope')]
    revisions = [dict(row) for row in db.execute('SELECT * FROM configuration_revisions ORDER BY scope,revision')]
    operations = [dict(row) for row in db.execute('SELECT * FROM configuration_operations ORDER BY id')]
    return {'scopes': scopes, 'revisions': revisions,
            'operations': [{'id': row['id'], 'format': row['format'], 'kind': row['kind'],
                            'status': row['status'], 'payload_sha256': digest(row['payload'].encode())}
                           for row in operations]}, operations


def references(db, add):
    data, operations = inventory(db)
    directories = {row['scope']: row['directory'] for row in data['scopes']}
    for row in data['scopes']:
        scope = row['scope']
        if scope != 'global' and (not scope.startswith('project:') or not PROJECT_ID.fullmatch(scope[8:])):
            raise ValueError('configuration_scope')
        root = Path(row['directory'])
        add(root.joinpath(*ConfigurationFiles.working(row['scope'])), f"configuration:{row['scope']}:working")
        for key in ('saved_revision', 'active_revision', 'pending_revision'):
            revision = row[key]
            if revision is not None and not any(r['scope'] == row['scope'] and r['revision'] == revision
                                                for r in data['revisions']):
                raise ValueError('missing_configuration_revision')
    for row in data['revisions']:
        add(Path(directories[row['scope']]).joinpath(*ConfigurationFiles.immutable(
            row['scope'], row['revision'], row['sha256'])),
            f"configuration:{row['scope']}:revision:{row['revision']}", row['sha256'])
    for row in operations:
        if row['format'] != 'configuration-operation-1':
            raise ValueError('unknown_configuration_operation_format')
        payload = json.loads(row['payload'])
        if row['kind'] == 'SAVE' and row['status'] in ('INTENDED', 'FILES_WRITTEN', 'RECOVERY_REQUIRED', 'CONFLICT'):
            for change in payload['changes']:
                if digest(change['text'].encode()) != change['sha256']:
                    raise ValueError('configuration_candidate_hash')
                root = Path(payload['directory'])
                add(root.joinpath(*ConfigurationFiles.working(change['scope'])),
                    f"configuration:{change['scope']}:intent:{row['id']}:working", optional=True)
                add(root.joinpath(*ConfigurationFiles.immutable(change['scope'], change['revision'], change['sha256'])),
                    f"configuration:{change['scope']}:intent:{row['id']}:immutable", change['sha256'], optional=True)
        if row['kind'] == 'ASSIST' and payload.get('process'):
            process = payload['process']
            spec, capture = process['spec'], process.get('capture')
            if Path(spec['prompt_path']) != Path(spec['artifacts']) / 'prompt.txt':
                raise ValueError('assistance_prompt_reference')
            add(spec['prompt_path'], f"assistance:{row['id']}:prompt", spec['prompt_sha256'])
            for stream in ('stdout', 'stderr'):
                artifact = capture['artifacts'][stream] if capture else None
                if artifact and Path(artifact['path']) != Path(spec['artifacts']) / f'{stream}.bin':
                    raise ValueError('assistance_stream_reference')
                add(Path(spec['artifacts']) / f'{stream}.bin', f"assistance:{row['id']}:{stream}",
                    artifact['sha256'] if artifact else None, artifact['size'] if artifact else None,
                    optional=artifact is None)
    for row in db.execute('SELECT id,preparation_id,spec,capture FROM managed_processes WHERE preparation_id IS NOT NULL ORDER BY id'):
        spec = json.loads(row['spec'])
        if 'prompt_path' not in spec:
            continue  # Native commands retain their bounded output in the step evidence.
        capture = json.loads(row['capture']) if row['capture'] else None
        directory = Path(spec['artifacts'])
        if Path(spec['prompt_path']) != directory / 'prompt.txt':
            raise ValueError('preparation_prompt_reference')
        add(spec['prompt_path'], f"preparation:{row['id']}:prompt", spec['prompt_sha256'])
        for stream in ('stdout', 'stderr'):
            artifact = capture['artifacts'][stream] if capture else None
            if artifact and Path(artifact['path']) != directory / f'{stream}.bin':
                raise ValueError('preparation_stream_reference')
            chunks = []
            for event in db.execute("SELECT payload FROM project_preparation_events WHERE operation_id=? AND kind='executor_stream_bytes' ORDER BY version", (row['preparation_id'],)):
                event = json.loads(event[0])
                if event.get('step_id') == row['id'] and event['stream'] == stream:
                    chunks.append((event['offset'], event['size'], event['sha256']))
            add(directory / f'{stream}.bin', f"preparation:{row['id']}:{stream}",
                artifact['sha256'] if artifact else None, artifact['size'] if artifact else None,
                optional=artifact is None and not chunks, chunks=chunks)
    return data


def read_private(source, ref):
    """Reuse editor guards for TOML, including private directories, ownership and size."""
    if not any(label.startswith('configuration:') for label in ref['labels']):
        return None
    path = Path(source)
    # Find the configured root by the known internal layout, not by traversing arbitrary paths.
    label = next(label for label in ref['labels'] if label.startswith('configuration:'))
    scope = label.split(':working')[0].split(':revision:')[0].split(':intent:')[0][14:]
    parts = (ConfigurationFiles.working(scope) if label.endswith(':working') else
             ('versions', path.parent.name, path.name))
    root = path.parents[len(parts) - 1]
    raw = ConfigurationFiles(root).read(parts)
    if raw is not None and len(raw) > MAX_BYTES:
        raise ValueError('configuration_size')
    return raw
