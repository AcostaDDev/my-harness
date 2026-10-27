"""Exact permission scopes. Prompts and review verdicts are never authority."""
import hashlib
import json

from my_harness.core.engine.contracts import freeze
from my_harness.core.engine.evidence import matches

KINDS = ('files', 'tools', 'network', 'product', 'acceptance')
LAYERS = ('global', 'project', 'contract', 'provider')


def digest(value):
    return hashlib.sha256(freeze(value).encode()).hexdigest()


def binding(run):
    return digest({'run_id': run.id, 'context': run.context_json,
                   'task': json.loads(run.history_json)['history']['task_json'],
                   'versions': run.versions_json})


def allowed(run, kind, target):
    """Every explicit ceiling must contain this exact operation target."""
    authority = json.loads(json.loads(run.versions_json).get('permission_authority', '{}'))
    if kind not in KINDS or not target.strip():
        return False
    if not all(target in authority.get(layer, {}).get(kind, []) for layer in LAYERS):
        return False
    if kind == 'files':
        from my_harness.core.engine.documents import executor_protected
        from my_harness.core.engine.serialization import restore_context
        context = restore_context(run.context_json)
        task = json.loads(json.loads(run.history_json)['history']['task_json'])
        try:
            context.path(target)
        except ValueError:
            return False
        if (not matches(target, task['allowed_paths']) or matches(target, task['forbidden_paths'])
                or executor_protected(context, task['task_id'], target)
                or (matches(target, context.profile.sensitive_paths)
                    and not matches(target, context.profile.sensitive_allowlist))):
            return False
    return True


def snapshot_payload(request):
    if request.permission_snapshot_json is None:
        return {'grants': [], 'denials': []}
    value = json.loads(request.permission_snapshot_json)
    payload = value['payload']
    if value['sha256'] != digest(payload) or payload['attempt_id'] != request.id:
        raise ValueError('Invalid permission snapshot')
    if payload['context_json'] != request.context_json or payload['task_json'] != request.task_json:
        raise ValueError('Permission snapshot does not match the frozen attempt')
    return payload


def snapshot_entries(request):
    return snapshot_payload(request)['grants']
