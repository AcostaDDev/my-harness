"""Requirements/alternatives proposal from the reviewer agent (Codex or Claude); a new read-only invocation.

D088: retired with v1 creation; no new runs are admitted and only already recorded ones run or reconcile."""
from dataclasses import replace

from my_harness.core.engine.contracts import ContractError, Selection, invoke_agent, stop_history
from my_harness.i18n import tr


def validate_result(data):
    if not isinstance(data, dict) or set(data) != {'summary', 'requirements', 'alternatives', 'pending_decisions'}:
        raise ContractError(tr('bootstrap.discovery_requires_summary_requirements'))
    if not isinstance(data['summary'], str) or not data['summary'].strip() or len(data['summary']) > 4000:
        raise ContractError(tr('bootstrap.discovery_summary_non_empty'))
    for field in ('requirements', 'alternatives', 'pending_decisions'):
        value = data[field]
        if (not isinstance(value, list) or len(value) > 30 or (field != 'pending_decisions' and not value)
                or any(not isinstance(item, str) or not item.strip() or len(item) > 4000 for item in value)):
            raise ContractError(tr('bootstrap.discovery_lists_contain_bounded'))
    return data


def execute(context, history, saved, agents, writer, journal):
    journal.checkpoint(history, 'bootstrap_discovery')
    before = writer.inspect_bootstrap(context)
    if before != saved['target'] or before['import_required']:
        return stop_history(history, 'bootstrap_discovery', tr('bootstrap.discovery_target_changed_import')), {
            'status': 'FAILED', 'result': None, 'reason': 'Discovery target changed; import required'}
    selection = Selection(context.policy.planner_model, context.policy.planner_effort,
                          'Explicit planner policy for read-only bootstrap discovery')
    history, data = invoke_agent(context, history, agents, 'bootstrap', selection, saved['prompt'], journal,
                                 prompt_snapshot_json=saved['prompt_snapshot_json'])
    after = writer.inspect_bootstrap(context)
    reason = None
    if before != after:
        reason = tr('bootstrap.discovery_changed_target')
    elif data is None:
        reason = history.stop.reason
    else:
        try:
            validate_result(data)
        except ContractError as exc:
            reason = str(exc)
    if reason:
        return stop_history(history, 'bootstrap_discovery', reason), {
            'status': 'FAILED', 'result': None, 'reason': reason}
    return replace(history, status='completed', stop=None), {'status': 'PROPOSED', 'result': data, 'reason': None}
