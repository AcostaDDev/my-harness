"""P002-T006 (G05, D281, D277): `trace-observation-1`, the normalized signals of one settled invocation. No I/O.

Built from the native source's sealed process evidence only (spec, process status, the adapter's `process_finished`
metadata or the closing owner's capture), like `usage-capture-1`. Each counter declares its meaning and its source
(supplied, reported, derived, measured, absent) and coverage; a harness attempt, a revision round and a native turn
are different counters. Missing evidence stays absent with a reason, never zero (INV-09). Usage views are named,
never added: the token amounts themselves stay in the accounting ledger. Termination is classified from the
supervisor's record, never from the exit status (D281: Codex exits 0 after SIGTERM).
"""
from my_harness.core.engine.usage_capture import launch_state

FORMAT = 'trace-observation-1'
SOURCES = ('supplied', 'reported', 'derived', 'measured', 'absent')
COVERAGE = ('complete', 'partial', 'absent')
MEANINGS = {
    'harness_attempt': 'position of the attempt in its run',
    'revision_round': 'executor rounds of the run up to this attempt',
    'native_turns': 'turns reported or delimited by the client',
    'tool_calls': 'tool uses observed in the stream, once per id',
    'permission_denials': 'denials reported by the client',
}
# Statuses the supervisor sets itself before stopping the group; the stream cannot produce them.
SUPERVISOR_STOPS = {'cancelled': 'cancelled', 'timeout': 'timeout', 'repetitive': 'output_guard',
                    'refused': 'refused'}
STREAM_ENDS = {'complete': 'completed', 'failed': 'failed', 'partial': 'partial', 'invalid': 'invalid_stream'}


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _counter(name, value, source, coverage, reason=None):
    if value is None:
        source, coverage = 'absent', 'absent'
    item = {'meaning': MEANINGS[name], 'value': value, 'source': source, 'coverage': coverage}
    if value is None:
        item['reason'] = reason or 'not_observed'
    return item


def termination(spec, process_status, capture):
    """Class and source of how the invocation ended; the exit status is evidence, not the classifier."""
    capture = capture if isinstance(capture, dict) else None
    if spec is None:
        return {'class': 'unknown', 'source': 'absent', 'reason': 'no_process_evidence'}
    if capture is None:
        state = 'pending' if process_status in (None, 'PENDING') else 'unknown'
        return {'class': state, 'source': 'absent', 'reason': 'no_capture'}
    status = capture.get('status')
    writer = 'stopped' if capture.get('group_state') == 'dead' else 'uncertain'
    result = {'writer': writer, 'exit_code': _count(capture.get('exit_code'))}
    if capture.get('settled_by') == 'closing_owner' or status == 'interrupted':
        return {**result, 'class': 'interrupted', 'source': 'supervisor'}
    if status in SUPERVISOR_STOPS:
        return {**result, 'class': SUPERVISOR_STOPS[status], 'source': 'supervisor'}
    if status in STREAM_ENDS:
        cls = STREAM_ENDS[status]
        if cls == 'completed' and (writer != 'stopped' or process_status == 'UNCERTAIN'):
            cls = 'failed'  # a terminal leader is not proof that its children stopped
        return {**result, 'class': cls, 'source': 'measured'}
    return {**result, 'class': 'unknown', 'source': 'absent', 'reason': 'unknown_status'}


def observe(*, spec, process_status, capture, identity_present=False, attempt_number=None,
            revision_round=None) -> dict:
    """`trace-observation-1` of one native invocation; `attempt_number`/`revision_round` are harness-supplied."""
    spec = spec if isinstance(spec, dict) else None
    capture = capture if isinstance(capture, dict) else None
    provider = spec.get('provider') if spec else None
    provider = provider if provider in ('claude', 'codex') else None
    meta = capture or {}
    observed = meta.get('observed') if isinstance(meta.get('observed'), dict) else {}
    stream = meta.get('stream_metrics') if isinstance(meta.get('stream_metrics'), dict) else None
    ended = termination(spec, process_status, capture)
    complete = ended['class'] == 'completed'
    # Native terminal events counted from the stream (`StreamMetrics.terminals`), independent of whether the final
    # payload was valid and of how the invocation ended; captures before that counter only prove a terminal when
    # the stream completed.
    terminals = stream.get('terminals') if stream and isinstance(stream.get('terminals'), dict) else None
    if terminals is not None and all(_count(v) is not None for v in terminals.values()):
        terminal_seen = sum(terminals.values()) > 0
    else:
        terminals, terminal_seen = None, complete
    coverage = 'complete' if terminal_seen else 'partial'
    missing = []

    def absent(name, reason):
        missing.append({'signal': name, 'reason': reason})
        return reason

    counters = {
        'harness_attempt': _counter('harness_attempt', _count(attempt_number), 'supplied', 'complete',
                                    'not_a_managed_attempt'),
        'revision_round': _counter('revision_round', _count(revision_round), 'derived', 'complete',
                                   'not_a_managed_attempt'),
    }
    # Native turns: Claude reports `num_turns` on its terminal; Codex delimits each turn with `turn.completed` or
    # `turn.failed`. Without a terminal nothing is counted (a cancelled stream ends inside the turn).
    turns, source = _count(observed.get('num_turns')), 'reported'
    if turns is None and provider == 'codex':
        delimited = (terminals.get('turn.completed', 0) + terminals.get('turn.failed', 0) if terminals is not None
                     else 1 if complete else 0)
        if delimited:
            turns, source = delimited, 'measured'
    unreported = 'not_reported' if terminal_seen else 'no_terminal'
    counters['native_turns'] = _counter('native_turns', turns, source, 'complete',
                                        None if turns is not None else absent('native_turns', unreported))
    tools = stream.get('tools') if stream and isinstance(stream.get('tools'), dict) else None
    if tools is not None and all(_count(v) is not None for v in tools.values()):
        counters['tool_calls'] = {**_counter('tool_calls', sum(tools.values()), 'measured', coverage),
                                  'by_name': dict(sorted(tools.items()))}
    else:
        counters['tool_calls'] = _counter('tool_calls', None, 'absent', 'absent',
                                          absent('tool_calls', 'no_stream_metrics'))
    denials = observed.get('permission_denials')
    if isinstance(denials, list):
        counters['permission_denials'] = _counter('permission_denials', len(denials), 'reported', 'complete')
    else:
        # Codex hides disallowed tools instead of reporting a denial (T002 §4).
        reason = 'not_reported_by_client' if provider == 'codex' else unreported
        counters['permission_denials'] = _counter('permission_denials', None, 'absent', 'absent',
                                                  absent('permission_denials', reason))

    # Usage: the view the evidence offers; a terminal total and per-message usage are alternatives, never summed.
    if isinstance(observed.get('usage'), dict):
        usage = {'view': 'terminal', 'source': 'reported', 'coverage': 'complete',
                 'alternatives': ['messages'] if stream and stream.get('message_usage') else []}
    elif provider == 'claude' and stream and isinstance(stream.get('message_usage'), dict):
        usage = {'view': 'messages', 'source': 'derived', 'coverage': 'partial', 'alternatives': []}
    else:
        usage = {'view': None, 'source': 'absent', 'coverage': 'absent', 'alternatives': [],
                 'reason': absent('usage', unreported)}
    models = sorted(observed['modelUsage']) if isinstance(observed.get('modelUsage'), dict) else []
    if not models and isinstance(observed.get('message_models'), list):
        models = sorted(m for m in observed['message_models'] if isinstance(m, str))
    if not models and isinstance(observed.get('model'), str):
        models = [observed['model']]
    reported_model = ({'value': models, 'source': 'reported'} if models else
                      {'value': None, 'source': 'absent', 'reason': absent(
                          'reported_model', 'not_reported_by_client' if provider == 'codex' else unreported)})
    session = next((observed[k] for k in ('session_id', 'thread_id') if isinstance(observed.get(k), str)), None)
    return {
        'format': FORMAT, 'provider': provider,
        'launch': launch_state(spec, process_status, identity_present, capture),
        'termination': ended, 'counters': counters, 'usage': usage, 'reported_model': reported_model,
        'native_session': {'present': session is not None, 'source': 'reported' if session else 'absent'},
        'missing': missing,
    }
