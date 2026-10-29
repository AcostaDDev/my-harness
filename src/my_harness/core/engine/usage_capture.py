"""P001-T003 (D254/D259): allowlisted usage-capture-1 evidence and its reconciliation. No I/O.

A capture is built from the native source's sealed process evidence (spec, lifecycle and the adapter's
`process_finished` metadata), never from prompts, argv, environment values or artifact paths. Components are
alternative views of one invocation: the terminal total, a reported per-model breakdown and ID-keyed Claude
requests. They are never added together; `evidence` selects one reconciled view for the pure calculator.
"""

import math

from my_harness.core.engine.metrics import STREAM_ACCOUNTING, raw_usage
from my_harness.core.engine.valuation import NORMALIZATION

CAPTURE = 'usage-capture-1'
SEMANTICS = {'claude': 'claude-cli-1', 'codex': 'codex-cli-1'}
LAUNCH = ('pending', 'not_invoked', 'observed', 'unknown_execution')
CLAUDE_MODEL_COUNTERS = ('inputTokens', 'outputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens',
                         'thinkingTokens', 'webSearchRequests')
# Delegated children are not established to be inside the parent's terminal total (T001 §2).
DELEGATION_TOOLS = frozenset({'Task', 'Agent'})
# Activity names that can carry a separate server charge; client file/shell tools never do.
SERVER_TOOLS = frozenset({'WebSearch', 'web_search', 'web_search_call'})
CATEGORIES = ('input_tokens', 'cache_read_tokens', 'cache_write_tokens', 'output_tokens')
KEY_LIMIT = 200


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _invalid(value):
    return isinstance(value, dict) and value.get('invalid') is True


def _text(value, limit=200):
    return value if isinstance(value, str) and value and len(value) <= limit else None


def _amount(value):
    """Client-reported amount: an exact lexeme when retained, else the historical float's repr, labelled."""
    if type(value) is str and len(value) <= 64:
        return {'value': value, 'representation': 'lexeme'}
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return {'value': repr(value), 'representation': 'legacy_float'}
    return None


def refusal_boundary(spec, capture, identity_present):
    """Positive supervisor evidence that the target CLI was never released; not inferred from stopping it.

    Additive evidence for T007 receipts and artifact inventories. Historical usage-capture-1 classification below
    stays unchanged. A gate process can exist while the target executable still has never received GO.
    """
    if not isinstance(spec, dict) or not isinstance(capture, dict) or capture.get('status') != 'refused':
        return None
    if (spec.get('launch_permitted') is False and not identity_present
            and capture.get('launch_boundary') in (None, 'before_spawn') and capture.get('launch_permitted') is not True):
        return 'before_spawn'
    if (identity_present and spec.get('launch_permitted') is not False and capture.get('launch_permitted') is False
            and capture.get('launch_boundary') == 'before_go'):
        return 'before_go'
    return None


def launch_state(spec, status, identity_present, capture):
    """Native launch gate, from positive evidence only. A missing process row proves nothing."""
    if spec is None:
        return 'unknown_execution'
    if spec.get('launch_permitted') is False:
        return 'not_invoked'
    if isinstance(capture, dict) and capture.get('status') == 'refused':
        # The gate wrapper was stopped before it released the CLI (identity_changed) or never spawned.
        return 'not_invoked'
    if isinstance(capture, dict) and identity_present:
        return 'observed'
    if status in (None, 'PENDING') and capture is None and not identity_present:
        return 'pending'
    return 'unknown_execution'


def build(*, spec, status, identity_present, capture, selection):
    """Allowlisted capture document; JSON-safe and float-free so it can be content-addressed."""
    spec = spec if isinstance(spec, dict) else None
    capture = capture if isinstance(capture, dict) else None
    provider = spec.get('provider') if spec else None
    provider = provider if provider in SEMANTICS else None
    meta = capture or {}
    observed = meta.get('observed') if isinstance(meta.get('observed'), dict) else {}
    stream = meta.get('stream_metrics') if isinstance(meta.get('stream_metrics'), dict) else {}
    accounting = stream.get('accounting') if isinstance(stream.get('accounting'), dict) else {}
    if accounting.get('format') != STREAM_ACCOUNTING:
        accounting = {}
    lexemes = accounting.get('cost_lexemes') if isinstance(accounting.get('cost_lexemes'), dict) else {}
    model_usage = None
    if provider == 'claude' and isinstance(observed.get('modelUsage'), dict):
        model_usage = {}
        for name, data in sorted(observed['modelUsage'].items()):
            if _text(name) and isinstance(data, dict):
                model_usage[name] = {key: data[key] if _count(data[key]) is not None else {'invalid': True}
                                     for key in CLAUDE_MODEL_COUNTERS if key in data}
    models = observed.get('message_models')
    model_costs = lexemes.get('models') if isinstance(lexemes.get('models'), dict) else {}
    requests = None
    if provider == 'claude' and isinstance(accounting.get('requests'), list):
        requests = [{'id': item['id'] if _text(item.get('id'), KEY_LIMIT) else None,
                     'model': _text(item.get('model')), 'usage': raw_usage('claude', item.get('usage')),
                     'conflict': item.get('conflict') is True}
                    for item in accounting['requests'] if isinstance(item, dict)]
    wall = meta.get('wall_duration_seconds')
    denials = observed.get('permission_denials')
    artifacts = meta.get('artifacts') if isinstance(meta.get('artifacts'), dict) else {}
    final = meta.get('final_usage_observed')
    return {
        'format': CAPTURE,
        'launch': launch_state(spec, status, identity_present, capture),
        'client': {'provider': provider, 'adapter_version': _text((spec or {}).get('adapter_version'), 40),
                   'cli_version': _text((spec or {}).get('cli_version'), 80)},
        'requested': {'model': _text((selection or {}).get('model')), 'effort': _text((selection or {}).get('effort'), 40)},
        'native_status': _text(meta.get('status'), 40), 'exit_code': meta.get('exit_code') if type(meta.get('exit_code')) is int else None,
        'group_state': _text(meta.get('group_state'), 40), 'settled_by': _text(meta.get('settled_by'), 40),
        'final_usage_observed': final if type(final) is bool else ('usage' in observed if capture else None),
        # An init/top-level model can echo the client selection: reported selection, not a response model.
        'reported_selection': {'model': _text(observed.get('model')), 'effort': _text(observed.get('effort'), 40)},
        'response_models': sorted(m for m in models if _text(m)) if isinstance(models, list) else None,
        'usage': raw_usage(provider, observed.get('usage')) if provider else None,
        'model_usage': model_usage,
        'requests': requests,
        'unidentified_messages': _count(accounting.get('unidentified_messages')),
        'reported_amounts': {
            'total_cost_usd': _amount(lexemes.get('total_cost_usd', observed.get('total_cost_usd'))),
            'models': {name: _amount(model_costs.get(name, (observed['modelUsage'][name] or {}).get('costUSD')))
                       for name in (model_usage or {})} or None},
        'activity': {'tools': stream.get('tools') if isinstance(stream.get('tools'), dict) else None,
                     'items': stream.get('items') if isinstance(stream.get('items'), dict) else None,
                     'permission_denials': len(denials) if isinstance(denials, list) else None,
                     'turns': _count(observed.get('num_turns'))},
        'timing': {'started_at': _text(meta.get('started_at'), 40),
                   'wall_ms': round(wall * 1000) if type(wall) in (int, float) and math.isfinite(wall) and wall >= 0 else None,
                   'duration_ms': _count(observed.get('duration_ms')),
                   'api_duration_ms': _count(observed.get('duration_api_ms'))},
        'artifacts': {name: {'sha256': item.get('sha256'), 'size': item.get('size')}
                      for name, item in sorted(artifacts.items()) if isinstance(item, dict)} or None,
    }


def _claude(usage, *, model=None):
    """Claude raw counters → calculator quantities. Lifetimes only when the nested breakdown is present."""
    lifetimes = usage.get('cache_creation') if isinstance(usage.get('cache_creation'), dict) else {}
    details = usage.get('output_tokens_details') if isinstance(usage.get('output_tokens_details'), dict) else {}
    values = {'input_tokens': usage.get('input_tokens'), 'cache_read_tokens': usage.get('cache_read_input_tokens'),
              'cache_write_tokens': usage.get('cache_creation_input_tokens'), 'output_tokens': usage.get('output_tokens'),
              'write_5m': lifetimes.get('ephemeral_5m_input_tokens'), 'write_1h': lifetimes.get('ephemeral_1h_input_tokens'),
              'reasoning_tokens': details.get('thinking_tokens')}
    return values


def _codex(usage):
    return {'input_tokens': usage.get('input_tokens'), 'cache_read_tokens': usage.get('cached_input_tokens'),
            'cache_write_tokens': usage.get('cache_write_input_tokens'), 'output_tokens': usage.get('output_tokens'),
            'reasoning_tokens': usage.get('reasoning_output_tokens')}


def _clean(values, reasons):
    result = {}
    for key, value in values.items():
        if _invalid(value):
            reasons.add('invalid_quantity')
            value = None
        result[key] = value
    return result


def components(capture):
    """Every observed view, with stable keys and inclusion relations. No view is added to another."""
    provider = capture['client']['provider']
    semantics = SEMANTICS.get(provider)
    # One terminal is the final total even when the structured payload itself was invalid (status 'invalid').
    final = capture['final_usage_observed'] is True
    coverage = 'complete' if final else 'partial'
    result = []
    usage = capture['usage']
    if semantics and isinstance(usage, dict):
        reasons = set()
        values = _clean(_claude(usage) if provider == 'claude' else _codex(usage), reasons)
        result.append({'key': 'invocation', 'grain': 'invocation_total', 'parent_key': None, 'inclusion': None,
                       'reported_model': None, 'model_source': None, 'semantics': semantics, 'coverage': coverage,
                       **values, 'reasons': sorted(reasons)})
    for name, data in sorted((capture['model_usage'] or {}).items()):
        reasons = set()
        values = _clean({'input_tokens': data.get('inputTokens'), 'cache_read_tokens': data.get('cacheReadInputTokens'),
                         'cache_write_tokens': data.get('cacheCreationInputTokens'),
                         'output_tokens': data.get('outputTokens'), 'reasoning_tokens': data.get('thinkingTokens')},
                        reasons)
        values.update(write_5m=0 if values['cache_write_tokens'] == 0 else None,
                      write_1h=0 if values['cache_write_tokens'] == 0 else None)
        result.append({'key': f'model:{name}', 'grain': 'model_total', 'parent_key': 'invocation' if usage else None,
                       'inclusion': 'includes' if usage else 'unknown', 'reported_model': name,
                       'model_source': 'model_usage', 'semantics': semantics, 'coverage': coverage,
                       **values, 'reasons': sorted(reasons)})
    for request in capture['requests'] or ():
        if request['id'] is None:
            continue
        reasons = {'model_partition_conflict'} if request['conflict'] else set()
        values = _clean(_claude(request['usage'] or {}), reasons)
        result.append({'key': f"request:{request['id']}", 'grain': 'request',
                       'parent_key': 'invocation' if usage else None, 'inclusion': 'includes' if usage else 'unknown',
                       'reported_model': request['model'], 'model_source': 'response' if request['model'] else None,
                       'semantics': semantics, 'coverage': coverage, **values, 'reasons': sorted(reasons)})
    return result


def _totals(items):
    sums = {}
    for key in CATEGORIES:
        values = [item[key] for item in items]
        sums[key] = sum(values) if all(_count(v) is not None for v in values) else None
    return sums


def _matches(parent, children):
    if not children:
        return False
    sums = _totals(children)
    return all(sums[key] is not None and sums[key] == parent[key] for key in CATEGORIES)


def _selected(item, **changes):
    keys = ('key', 'grain', 'reported_model', 'model_source', 'semantics', 'coverage', 'input_tokens',
            'cache_read_tokens', 'cache_write_tokens', 'output_tokens', 'reasoning_tokens', 'write_5m', 'write_1h')
    value = {key: item.get(key) for key in keys if key in item}
    if item['semantics'] != 'claude-cli-1':
        value.pop('write_5m', None), value.pop('write_1h', None)
    return {**value, **changes}


def evidence(capture, views=None):
    """Select one reconciled view for usage-accounting-1, or the explicit reasons none is complete."""
    views = components(capture) if views is None else views
    reasons = set()
    provider = capture['client']['provider']
    tools = (capture['activity'] or {}).get('tools') or {}
    items = (capture['activity'] or {}).get('items') or {}
    server = (capture['usage'] or {}).get('server_tool_use') if isinstance(capture['usage'], dict) else None
    charges_complete = not (set(tools) & SERVER_TOOLS or set(items) & SERVER_TOOLS
                            or isinstance(server, dict) and any(v != 0 for v in server.values()))
    delegation = 'unknown' if set(tools) & DELEGATION_TOOLS else 'none'
    base = {'format': NORMALIZATION, 'partition': 'single', 'delegation': delegation,
            'charges_complete': charges_complete, 'charges': []}
    if capture['launch'] == 'not_invoked':
        return None
    if provider is None:
        return {**base, 'coverage': 'absent', 'components': [], 'reasons': ['capture_unavailable']}
    if capture['native_status'] is None:
        reasons.add('capture_unavailable')
    if capture['settled_by'] == 'closing_owner' or capture['native_status'] == 'interrupted':
        reasons.add('partial_capture')
    total = next((v for v in views if v['grain'] == 'invocation_total'), None)
    models = [v for v in views if v['grain'] == 'model_total']
    requests = [v for v in views if v['grain'] == 'request']
    for view in views:
        reasons.update(r for r in view['reasons'] if r == 'invalid_quantity')
    if total is None or total['coverage'] != 'complete':
        reasons.add('terminal_missing')
        if capture['native_status'] == 'invalid' and total is not None:
            reasons.add('inconsistent_usage')
        usable = [v for v in requests if not v['reasons']]
        if usable and len(usable) == len(requests) and not capture['unidentified_messages']:
            # Measured subtotal of identified requests; it can never certify final usage.
            return {**base, 'coverage': 'partial', 'partition': 'single' if len(usable) == 1 else 'disjoint',
                    'components': [_selected(v, coverage='partial') for v in usable], 'reasons': sorted(reasons)}
        return {**base, 'coverage': 'absent', 'components': [], 'reasons': sorted(reasons | {'usage_missing'})}
    coverage = 'partial' if 'partial_capture' in reasons else 'complete'
    if requests and not capture['unidentified_messages'] and all(not v['reasons'] for v in requests) \
            and all(v['reported_model'] for v in requests) and _matches(total, requests):
        return {**base, 'coverage': coverage, 'partition': 'single' if len(requests) == 1 else 'disjoint',
                'components': [_selected(v) for v in requests], 'reasons': sorted(reasons)}
    if any(v['reasons'] for v in requests):
        reasons.add('model_partition_conflict')
    if len(models) == 1:
        model = models[0]['reported_model']
        return {**base, 'coverage': coverage,
                'components': [_selected(total, reported_model=model, model_source='model_usage')],
                'reasons': sorted(reasons)}
    if len(models) > 1:
        if _matches(total, models):
            writers = [m for m in models if m['cache_write_tokens']]
            selected = []
            for item in models:
                if len(writers) == 1 and item is writers[0] and item['cache_write_tokens'] == total['cache_write_tokens']:
                    # Only one model wrote cache: its lifetimes are exactly the terminal's breakdown.
                    item = {**item, 'write_5m': total.get('write_5m'), 'write_1h': total.get('write_1h')}
                selected.append(_selected(item))
            return {**base, 'coverage': coverage, 'partition': 'disjoint', 'components': selected,
                    'reasons': sorted(reasons)}
        reasons.add('model_partition_conflict')
        return {**base, 'coverage': coverage, 'components': [_selected(total)], 'reasons': sorted(reasons)}
    response = capture['response_models'] or []
    if len(response) == 1:
        return {**base, 'coverage': coverage,
                'components': [_selected(total, reported_model=response[0], model_source='response')],
                'reasons': sorted(reasons)}
    reasons.add('model_partition_unknown' if len(response) > 1 else 'model_unreported')
    return {**base, 'coverage': coverage, 'components': [_selected(total)], 'reasons': sorted(reasons)}
