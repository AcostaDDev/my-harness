"""Read-only structural verification of T009 evidence in backups/restored archives."""
import json

from my_harness.core.engine import judge as core
from my_harness.core.engine.domain_catalogue import digest
from my_harness.i18n import tr


def verify_archive(db):
    requests = {}
    for row in db.execute('SELECT * FROM judge_requests'):
        payload = json.loads(row['payload'])
        core.input_check(row['duty'], payload['inputs'])
        snapshot = db.execute('SELECT project_id, revision_id, sha256 FROM context_snapshots WHERE id=?', (row['snapshot_id'],)).fetchone()
        if (snapshot is None or snapshot['project_id'] != row['project_id'] or
                snapshot['revision_id'] != payload['revision_id'] or payload['format'] != core.FORMAT or
                digest({'evidence': payload['evidence'], 'context_sha256': snapshot['sha256']}) != row['evidence_sha256'] or
                digest({'project': row['project_id'], 'duty': row['duty'], 'subject': row['subject']}) != row['equivalence_sha256']):
            raise ValueError(tr('judge.invalid'))
        requests[row['id']] = (row, payload)
    bindings = {}
    for binding in db.execute('SELECT * FROM judge_invocations'):
        row, payload = requests[binding['request_id']]
        attempt = db.execute('SELECT * FROM managed_attempts WHERE id=?', (binding['attempt_id'],)).fetchone()
        operation = db.execute('SELECT * FROM workflow_operations WHERE id=?', (binding['operation_id'],)).fetchone()
        invocation = db.execute('SELECT attempt_id FROM usage_invocations WHERE id=?', (binding['invocation_id'],)).fetchone()
        request = json.loads(attempt['request_json'])
        snapshot = json.loads(request['prompt_snapshot_json'])
        marker = snapshot['judge']
        core.marker_check(snapshot, request['role'], frozenset(tuple(r) for r in snapshot['scoped_tools']['tools']))
        if (request['role'] != 'judge' or invocation['attempt_id'] != attempt['id'] or
                operation['attempt_id'] != attempt['id'] or operation['invocation_id'] != binding['invocation_id'] or
                marker['request_id'] != row['id'] or marker['request_sha256'] != digest(payload) or
                json.loads(operation['refs'])['judge_request_id'] != row['id'] or
                snapshot['canonical_context']['id'] != row['snapshot_id']):
            raise ValueError(tr('judge.invalid'))
        bindings[row['id']] = (binding, attempt)
    for ruling in db.execute('SELECT * FROM judge_rulings'):
        row, request = requests[ruling['request_id']]
        payload = json.loads(ruling['payload'])
        if not payload['proposal_only'] or ruling['status'] not in ('VALIDATED', 'ESCALATED', 'FAILED', 'UNCERTAIN'):
            raise ValueError(tr('judge.invalid'))
        if 'native_result_sha256' in payload:
            binding, attempt = bindings[row['id']]
            native = json.loads(attempt['result_json'])
            if digest(native) != payload['native_result_sha256'] or payload['attempt_id'] != attempt['id']:
                raise ValueError(tr('judge.invalid'))
        if ruling['status'] == 'VALIDATED':
            if 'native_result_sha256' not in payload:
                raise ValueError(tr('judge.invalid'))
            candidate = core.candidate(row['duty'], request['inputs'], request['evidence'], request['policy'],
                                       json.dumps(payload['candidate']))
            if candidate['outcome'] in ('escalate', 'abstain') or candidate != json.loads(native['payload_json']):
                raise ValueError(tr('judge.invalid'))
    for link in db.execute('SELECT * FROM judge_decision_links'):
        found = db.execute('SELECT 1 FROM judge_rulings r JOIN judge_requests q ON q.id=r.request_id '
            'JOIN knowledge_revision_members m ON m.project_id=q.project_id AND m.revision_id=? AND m.item_id=? '
            "JOIN knowledge_items i ON i.id=m.item_id AND i.kind='decision' WHERE r.id=?",
            (link['revision_id'], link['decision_id'], link['ruling_id'])).fetchone()
        if not found:
            raise ValueError(tr('judge.invalid'))
