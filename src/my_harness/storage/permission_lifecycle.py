"""Read-only verification of append-only permission evidence in backups and query-only archives."""
import json
from my_harness.i18n import tr
from my_harness.core.engine.domain_catalogue import digest


def verify_archive(db):
    records = {}
    sequences = {}
    for row in db.execute('SELECT * FROM permission_records ORDER BY project_id, sequence'):
        payload = json.loads(row['payload'])
        sequences[row['project_id']] = sequences.get(row['project_id'], 0) + 1
        if row['sequence'] != sequences[row['project_id']] or row['sha256'] != digest({'kind':row['kind'],'payload':payload}):
            raise ValueError(tr('domain.permission_invalid'))
        if payload.get('parent'):
            parent = records.get(payload['parent'])
            if parent is None or parent[0]['project_id'] != row['project_id'] or parent[0]['kind'] != 'authorization':
                raise ValueError(tr('domain.permission_invalid'))
        for field in ('request_id','record_id','grant_id'):
            if field in payload:
                previous = records.get(payload[field])
                if previous is None or previous[0]['project_id'] != row['project_id']:
                    raise ValueError(tr('domain.permission_invalid'))
        if row['kind'] == 'snapshot':
            for identity in payload['grants']:
                grant = records.get(identity)
                if grant is None or grant[0]['project_id'] != row['project_id'] or grant[0]['kind'] != 'grant':
                    raise ValueError(tr('domain.permission_invalid'))
        records[row['id']] = (row, payload)
    for boundary in db.execute('SELECT * FROM permission_boundaries'):
        snapshot = records.get(boundary['snapshot_id'])
        operation = db.execute('SELECT * FROM workflow_operations WHERE id=?',(boundary['operation_id'],)).fetchone()
        attempt = db.execute('SELECT request_json FROM managed_attempts WHERE id=?',(boundary['attempt_id'],)).fetchone()
        if snapshot is None or snapshot[0]['kind'] != 'snapshot' or not operation or not attempt:
            raise ValueError(tr('domain.permission_invalid'))
        request = json.loads(attempt['request_json'])
        marker = json.loads(request['prompt_snapshot_json'])['permissions']
        if (marker != {'id':snapshot[0]['id'],'sha256':snapshot[0]['sha256']} or
                operation['attempt_id'] != boundary['attempt_id'] or operation['invocation_id'] != boundary['invocation_id'] or
                snapshot[1]['operation_key'] != operation['key'] or snapshot[1]['role'] != request['role']):
            raise ValueError(tr('domain.permission_invalid'))
