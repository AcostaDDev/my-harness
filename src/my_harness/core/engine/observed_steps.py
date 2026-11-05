"""P002-T019 (D305, D310, T018 §6): `observed-step-1`, the client-neutral ordered steps of one settled invocation.
No I/O.

Derived once from the attempt's sealed native evidence, in record order: `agent_event` records (oversize ones
resolved by the caller from verified stdout bytes, or marked unavailable), the parser's diagnostics and the receipt
time of the chunk that carried each record's terminating newline. Nothing is inferred or repeated:

- Every record is validated against the shape it is read with before any step changes; a malformed record or an
  unknown item type becomes a `not_observed` step at its position and the following records are still processed.
- An open turn or call at stream end is never closed as completed, turns are never manufactured, and a message is
  the final answer only when its own turn is observed to complete (Codex) or the terminal result reports success
  (Claude). Steps observed only at their end carry that end, with start and duration absent.
- Coverage is `complete` only when nothing is missing: no gaps, no open turn or call, a final answer, every result,
  denial and broker event correlated, and no bound reached. Otherwise it is `partial` with its reasons.
- Bounds are applied while deriving: at most 10,000 steps are materialized; later ones are only counted by kind,
  while their calls still absorb their results and keep the compact metadata (tool and argument digest) that broker
  attribution needs across the whole invocation. Overlap and broker matching are linear after sorting.
- Fields a call's first records do not carry (an MCP server, tool or arguments, a file change list) are taken from
  the later record that first carries them, never replaced once observed; a call whose `item.started` is missing
  has no observed start or duration.

Steps carry codes, digests, sizes and masked argument summaries of explicit fields only; message, reasoning and
result content is never kept. Units differ per client and are labelled (`claude_message` is one assistant message
id, `codex_turn` one `turn.started` … `turn.completed`/`turn.failed`).
"""
from collections import Counter
from datetime import datetime
import hashlib
import json

from my_harness.core.engine.trace_payload import MASK, SECRET_VALUES, SENSITIVE_KEY, bound

FORMAT = 'observed-step-1'
DERIVATION = 3
MAX_STEPS = 10_000
MAX_BYTES = 4 * 1024 * 1024
MAX_SUMMARY = 256
MAX_SOURCES = 4
MAX_NAME = 200
MAX_CODE = 64
KINDS = ('turn', 'tool_call', 'message', 'reasoning', 'not_observed')
OUTCOMES = ('completed', 'error', 'denied', 'cancelled_in_flight', 'not_observed', 'unclassified')
OPEN = ('cancelled_in_flight', 'not_observed')
REASONS = ('invalid_record', 'partial_tail', 'oversize_record_unavailable', 'cancelled_in_flight',
           'unsupported_event', 'unsupported_client', 'no_stream', 'step_bound_reached')
COVERAGE_REASONS = ('not_observed_steps', 'step_bound_reached', 'no_terminal', 'open_turns', 'open_calls',
                    'final_answer_absent', 'uncorrelated_results', 'uncorrelated_denials', 'unlinked_broker_events',
                    'ambiguous_broker_calls', 'unsupported_blocks', 'assistant_without_id', 'derivation_errors',
                    'no_evidence', 'unsupported_client')
CLIENTS = ('claude', 'codex')
# Termination classes (trace-observation-1) in which the supervisor itself cut the stream.
SUPERVISOR_STOPS = frozenset({'cancelled', 'timeout', 'output_guard'})
DIAGNOSTICS = {'invalid': 'invalid_record', 'invalid_envelope': 'invalid_record', 'partial_tail': 'partial_tail'}
CLAUDE_KNOWN = frozenset({'system', 'rate_limit_event'})
CLAUDE_TOOLS = frozenset({'tool_use', 'server_tool_use'})
CLAUDE_TEXT = {'text': 'text', 'thinking': 'thinking', 'redacted_thinking': 'data'}
CODEX_KNOWN = frozenset({'thread.started'})
CODEX_ITEMS = frozenset({'item.started', 'item.updated', 'item.completed'})
CODEX_TEXT = frozenset({'agent_message', 'reasoning'})
# Supported Codex tool items and the explicit fields their argument summary and result digest read (nothing else);
# `observed` names the fields whose presence means the arguments were observed on that record.
CODEX_TOOLS = {
    'command_execution': {'arguments': lambda item: {'command': item.get('command')},
                          'result': ('aggregated_output', 'exit_code'), 'observed': ('command',),
                          'fields': {'command': str, 'aggregated_output': (str, type(None)),
                                     'exit_code': (int, type(None))}},
    'mcp_tool_call': {'arguments': lambda item: item.get('arguments', {}), 'result': ('result', 'error'),
                      'observed': ('arguments',), 'fields': {'server': str, 'tool': str}},
    'file_change': {'arguments': lambda item: [{'path': c.get('path'), 'kind': c.get('kind')}
                                               for c in item.get('changes') or ()],
                    'result': (), 'observed': ('changes',), 'fields': {'changes': list}},
    'web_search': {'arguments': lambda item: {'query': item.get('query')}, 'result': (), 'observed': ('query',),
                   'fields': {'query': str}},
}
CODEX_STATUS = {'completed': 'completed', 'failed': 'error'}
BROKER_SERVER = 'harness'
_BOUND_RESERVE = 1024  # room for the closing `step_bound_reached` marker within the byte bound


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(data: bytes) -> dict:
    return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def _content(value) -> bytes:
    """Bytes a size and digest describe: text as UTF-8, anything else as canonical JSON."""
    return value.encode('utf-8') if isinstance(value, str) else _canonical(value).encode('utf-8')


def _key(*parts) -> bytes:
    """A compact deduplication key (16 bytes), so repeated-record bookkeeping stays small."""
    return hashlib.sha256(repr(parts).encode('utf-8')).digest()[:16]


class _Mask:
    def __init__(self):
        self.redactions = 0

    def text(self, value: str) -> str:
        for pattern in SECRET_VALUES:
            value, found = pattern.subn(MASK, value)
            self.redactions += found
        return value

    def value(self, value, depth=0):
        if isinstance(value, str):
            return self.text(value)
        if depth > 32:
            return '…'
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                key = self.text(str(key))
                if SENSITIVE_KEY.match(key):
                    self.redactions += 1
                    result[key] = MASK
                else:
                    result[key] = self.value(item, depth + 1)
            return result
        if isinstance(value, (list, tuple)):
            return [self.value(item, depth + 1) for item in value]
        return value


def label(value, limit=MAX_NAME):
    """A masked, bounded name or code from the native stream (never a secret, never unbounded)."""
    if not isinstance(value, str):
        return None
    return _Mask().text(value)[:limit]


def arguments(value) -> dict:
    """Size and digest of the native arguments plus a summary masked before it is truncated to 256 characters."""
    raw = _content(value)
    mask = _Mask()
    masked = mask.value(value)
    text = mask.text(masked if isinstance(masked, str) else _canonical(masked))
    return {**_digest(raw), 'summary': text[:MAX_SUMMARY], 'summary_truncated': len(text) > MAX_SUMMARY,
            'redactions': mask.redactions}


def _ms(start, end):
    try:
        delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except (TypeError, ValueError):
        return None
    return max(0, round(delta.total_seconds() * 1000))


# Shape validation (before any step changes) --------------------------------------------------------------------------

def _is(value, kinds):
    return isinstance(value, kinds) and not (kinds is int and isinstance(value, bool))


def _optional(mapping, key, kinds):
    return key not in mapping or mapping[key] is None or _is(mapping[key], kinds)


def claude_valid(event) -> bool:
    kind = event.get('type')
    if kind == 'stream_event':
        inner = event.get('event')
        if not isinstance(inner, dict) or not _optional(inner, 'type', str):
            return False
        if inner.get('type') == 'message_start':
            message = inner.get('message')
            return isinstance(message, dict) and isinstance(message.get('id'), str)
        return True
    if kind in ('assistant', 'user'):
        message = event.get('message')
        if not isinstance(message, dict) or not _optional(message, 'id', str):
            return False
        content = message.get('content')
        if kind == 'user' and (content is None or isinstance(content, str)):
            return True
        if not isinstance(content, list):
            return False
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get('type'), str):
                return False
            btype = block['type']
            if kind == 'assistant' and btype in CLAUDE_TOOLS and not (
                    isinstance(block.get('id'), str) and isinstance(block.get('name'), str)):
                return False
            if kind == 'assistant' and btype in CLAUDE_TEXT and not _optional(block, CLAUDE_TEXT[btype], str):
                return False
            if kind == 'user' and btype == 'tool_result' and not (
                    isinstance(block.get('tool_use_id'), str) and _optional(block, 'is_error', bool)):
                return False
        return True
    if kind == 'result':
        denials = event.get('permission_denials')
        if denials is not None and not (isinstance(denials, list) and all(
                isinstance(d, dict) and isinstance(d.get('tool_use_id'), str) for d in denials)):
            return False
        return _optional(event, 'is_error', bool) and _optional(event, 'subtype', str)
    return True


def codex_valid(event) -> bool:
    if event.get('type') not in CODEX_ITEMS:
        return True
    item = event.get('item')
    if not isinstance(item, dict) or not isinstance(item.get('type'), str):
        return False
    if not (_optional(item, 'id', str) and _optional(item, 'status', str)):
        return False
    if item['type'] in CODEX_TEXT:
        return _optional(item, 'text', str)
    spec = CODEX_TOOLS.get(item['type'])
    if spec is None:
        return True  # an unknown item type is a gap of its own, not a malformed record
    for field, kinds in spec['fields'].items():
        value = item.get(field)
        required = not isinstance(kinds, tuple)
        if (value is None and required and item.get('status') != 'in_progress') or (
                value is not None and not _is(value, kinds)):
            return False
    if item['type'] == 'file_change' and not all(  # `changes` may be null while the item is in progress
            isinstance(c, dict) and _optional(c, 'path', str) and _optional(c, 'kind', str)
            for c in item.get('changes') or ()):
        return False
    return True


# Steps -----------------------------------------------------------------------------------------------------------

class _Step(dict):
    """A materialized step: the payload plus private bookkeeping (record interval, sources)."""
    materialized = True

    def __init__(self, deriver, kind, item, *, point=False, **fields):
        super().__init__(kind=kind, **fields)
        self.opened, self.closed = item['index'], None
        self.first, self.latest, self.count = [], None, 0  # first three distinct records, the latest one, total
        self.add_source(deriver, item)
        if point:  # observed once, at its end: start and duration are not observed
            self['started_at'], self['finished_at'] = None, item.get('at')
        else:
            self['started_at'] = item.get('at')

    def add_source(self, deriver, item):
        reference = deriver.reference(item)
        if reference is None or reference in self.first or reference == self.latest:
            return
        self.count += 1
        if len(self.first) < MAX_SOURCES - 1:
            self.first.append(reference)
        else:
            self.latest = reference

    @property
    def sources(self):
        """At most four references: the first three records and the last one."""
        return self.first + ([self.latest] if self.latest is not None else [])

    def close(self, deriver, item, outcome):
        self['outcome'] = outcome
        self.closed = item['index'] if item is not None else None
        if item is not None:
            self.add_source(deriver, item)
            self['finished_at'] = item.get('at')


class _Omitted:
    """A step past the bound: counted by kind, never materialized; its call still absorbs its result. A call keeps
    only its tool and argument digest, so broker attribution can count it (never link to it)."""
    materialized = False
    __slots__ = ('kind', 'done', 'fields', 'arguments_observed')

    def __init__(self, kind, fields):
        self.kind, self.done = kind, False
        self.fields = {}
        if kind == 'tool_call':
            self['tool'], self['arguments'] = fields.get('tool'), fields.get('arguments')

    def __contains__(self, key):
        return key == 'outcome' and self.done

    def __getitem__(self, key):
        return self.fields[key]

    def __setitem__(self, key, value):
        if key == 'outcome':
            self.done = True
        elif key == 'tool':
            self.fields['tool'] = value
        elif key == 'arguments':
            self.fields['arguments'] = {'sha256': (value or {}).get('sha256')}

    def get(self, key, default=None):
        return self.fields.get(key, default)

    def add_source(self, deriver, item):
        pass

    def close(self, deriver, item, outcome):
        self.done = True


class Deriver:
    """Feeds normalized records in native order and returns the bounded step payloads and their summary.

    A record is `{'index', 'sequence', 'record', 'at'}` plus one of: `event` (the parsed native object),
    `diagnostic` (the parser's code; not a native row, so it is never a source record) or `unavailable` (an oversize
    record whose bytes could not be verified: `{'code', 'size', 'sha256', 'type'}`). `at` is the receipt time of the
    chunk that carried its terminating newline, or None when no chunk evidence exists.
    """

    def __init__(self, *, client, run_id, attempt_id, termination=None, brokers=()):
        self.client = client if client in CLIENTS else None
        self.raw_client = client
        self.run_id, self.attempt_id = run_id, attempt_id
        self.termination = termination
        self.brokers = brokers
        self.steps: list[_Step] = []
        self.omitted = Counter()
        self.omitted_calls: list[_Omitted] = []  # compact calls past the bound, for invocation-wide attribution
        self.calls: dict = {}
        self.blocks: dict = {}
        self.items: dict = {}
        self.turn = None
        self.last_turn_item = None
        self.turns: dict = {}
        self.records = 0
        self.last_record = None
        self.last_item = None
        self.unmatched = Counter()
        self.terminal = False
        self.denials = None
        self.final = None  # 'present', 'failed', or None (absent)
        self.last_message = None

    # Bookkeeping ----------------------------------------------------------------------------------------------------

    def reference(self, item):
        """`agent_event` rows only (T018 §6.2); a parser diagnostic or a synthetic position has none."""
        if item.get('sequence') is None or 'diagnostic' in item:
            return None
        return {'run_id': self.run_id, 'attempt_id': self.attempt_id, 'sequence': item['sequence'],
                'record': item.get('record'), 'oversize': bool(item.get('oversize'))}

    def _add(self, kind, item, *, point=False, **fields):
        if len(self.steps) >= MAX_STEPS:
            self.omitted[kind] += 1
            omitted = _Omitted(kind, fields)
            if kind == 'tool_call':
                self.omitted_calls.append(omitted)
            return omitted
        step = _Step(self, kind, item, point=point, **fields)
        if kind != 'turn' and 'parent_seq' not in fields:
            step['parent_turn'] = self.turn if getattr(self.turn, 'materialized', False) else None
            step.turn = self.turn
        self.steps.append(step)
        return step

    def gap(self, item, reason, **fields):
        if 'diagnostic' in item and item.get('record') is not None:
            fields['stream_record'] = item['record']  # the parser's record number; no native row exists
        return self._add('not_observed', item, point=True, reason=reason, **fields)

    # Input ----------------------------------------------------------------------------------------------------------

    def feed(self, item):
        self.records += 1
        self.last_item = item
        if item.get('record') is not None:
            self.last_record = item['record']
        if self.client is None:
            return  # one `unsupported_client` step at the end; the records stay as evidence
        if 'diagnostic' in item:
            self.gap(item, DIAGNOSTICS.get(item['diagnostic'], 'invalid_record'),
                     event_type=label(item['diagnostic'], MAX_CODE))
            return
        if 'unavailable' in item:
            missing = item['unavailable']
            self.gap(item, 'oversize_record_unavailable', event_type=label(missing.get('type'), MAX_CODE),
                     detail=missing.get('code'), record_size=missing.get('size'), record_sha256=missing.get('sha256'))
            return
        event = item['event']
        valid = claude_valid if self.client == 'claude' else codex_valid
        if not isinstance(event, dict) or not valid(event):
            self.gap(item, 'invalid_record', event_type=label(event.get('type') if isinstance(event, dict)
                                                             else None, MAX_CODE))
            return
        try:
            (self._claude if self.client == 'claude' else self._codex)(item, event)
        except (TypeError, ValueError, KeyError, AttributeError):  # a shape the validation did not foresee
            self.unmatched['derivation_errors'] += 1
            self.gap(item, 'invalid_record', event_type=label(event.get('type'), MAX_CODE))

    # Claude Code stream-json ----------------------------------------------------------------------------------------

    def _claude_turn(self, ident, item):
        turn = self.turns.get(ident)
        if self.turn is not None and self.turn is not turn:
            self._close_turn(self.last_turn_item or item, 'completed')
        if turn is None:
            turn = self._add('turn', item, unit='claude_message', max_concurrency=0)
            self.turns[ident] = turn
        else:
            turn.add_source(self, item)  # the same message id repeated: one turn, never a second one
        self.turn = turn
        self.last_turn_item = item
        return turn

    def _close_turn(self, item, outcome):
        if self.turn is not None and 'outcome' not in self.turn:
            self.turn.close(self, item, outcome)
        self.turn = None

    def _claude(self, item, event):
        kind = event['type']
        if kind == 'stream_event':
            inner = event['event']
            if inner.get('type') == 'message_start':
                self._claude_turn(inner['message']['id'], item)
            elif inner.get('type') == 'message_stop' and self.turn is not None:
                self._close_turn(item, 'completed')
            elif self.turn is not None:
                self.last_turn_item = item
            return
        if kind == 'assistant':
            message = event['message']
            turn = self._claude_turn(message['id'], item) if isinstance(message.get('id'), str) else None
            if turn is None:
                self.unmatched['assistant_without_id'] += 1
            for block in message['content']:
                self._claude_block(item, message.get('id'), block)
            return
        if kind == 'user':
            if self.turn is not None:
                self._close_turn(self.last_turn_item or item, 'completed')
            content = event['message'].get('content')
            for block in content if isinstance(content, list) else ():
                if block['type'] == 'tool_result':
                    self._claude_result(item, block)
            return
        if kind == 'result':
            if self.turn is not None:
                self._close_turn(self.last_turn_item or item, 'completed')
            self.terminal = True
            self.denials = event.get('permission_denials')
            for denial in self.denials or ():
                call = self.calls.get(denial['tool_use_id'])
                if call is None:
                    self.unmatched['denials'] += 1
                else:
                    call['outcome'] = 'denied'
                    call.add_source(self, item)
            answer = event.get('structured_output', event.get('result'))
            success = event.get('subtype') == 'success' and event.get('is_error') is False
            if answer is not None:
                self._add('message', item, point=True, parent_seq=None, message={
                    **_digest(_content(answer)), 'present': True, 'final': success, 'terminal': True})
            self.final = 'present' if success and answer is not None else 'failed'
            return
        if kind in CLAUDE_KNOWN:
            return
        self.gap(item, 'unsupported_event', event_type=label(kind, MAX_CODE))

    def _claude_block(self, item, message_id, block):
        kind = block['type']
        if kind in CLAUDE_TOOLS:
            ident = block['id']
            if ident in self.calls:
                self.calls[ident].add_source(self, item)
                return
            tool = self._tool_name(block['name']) if kind == 'tool_use' else {'name': label(block['name']),
                                                                              'origin': 'native'}
            self.calls[ident] = self._add('tool_call', item, call_id=label(ident), tool=tool,
                                          arguments=arguments(block.get('input', {})))
            return
        if kind in CLAUDE_TEXT:
            body = block.get(CLAUDE_TEXT[kind])
            if body is None:
                return
            content = _content(body)
            key = _key(message_id, kind, hashlib.sha256(content).digest())
            if key in self.blocks:
                self.blocks[key].add_source(self, item)
                return
            step_kind = 'message' if kind == 'text' else 'reasoning'
            self.blocks[key] = self._add(step_kind, item, point=True, **{step_kind: {
                **_digest(content), 'present': True, **({'final': False} if kind == 'text' else {})}})
            return
        self.unmatched['unsupported_blocks'] += 1

    def _claude_result(self, item, block):
        call = self.calls.get(block['tool_use_id'])
        if call is None or 'outcome' in call:
            self.unmatched['results'] += 1
            return
        call['result'] = {**_digest(_content(block.get('content'))), 'present': True}
        call.close(self, item, 'error' if block.get('is_error') is True else 'completed')

    def _tool_name(self, name):
        if name.startswith('mcp__'):
            parts = name.split('__', 2)
            if len(parts) == 3:
                origin = 'harness_broker' if parts[1] == BROKER_SERVER else 'other_mcp'
                return {'name': label(parts[2]), 'server': label(parts[1]), 'origin': origin}
        return {'name': label(name), 'origin': 'native'}

    # Codex exec --json ----------------------------------------------------------------------------------------------

    def _codex(self, item, event):
        kind = event['type']
        if kind == 'turn.started':
            if self.turn is not None:  # a second start without an end: the first turn's end was never observed
                self._close_turn(None, 'not_observed')
            self.turn = self._add('turn', item, unit='codex_turn', start_observed=True, max_concurrency=0)
            return
        if kind in ('turn.completed', 'turn.failed'):
            outcome = 'completed' if kind == 'turn.completed' else 'error'
            if self.turn is None:  # native evidence of a turn whose start the stream did not carry
                self.turn = self._add('turn', item, point=True, unit='codex_turn', start_observed=False,
                                      max_concurrency=0)
            self._close_turn(item, outcome)
            self.terminal = True
            return
        if kind in CODEX_ITEMS:
            self._codex_item(item, kind, event['item'])
            return
        if kind in CODEX_KNOWN:
            return
        self.gap(item, 'unsupported_event', event_type=label(kind, MAX_CODE))

    def _codex_item(self, item, kind, native):
        itype, ident = native['type'], native.get('id')
        if itype in CODEX_TEXT:
            if kind != 'item.completed':
                return
            key = _key('codex', itype, ident if ident is not None else item['index'])
            if key in self.blocks:
                self.blocks[key].add_source(self, item)
                return
            step_kind = 'message' if itype == 'agent_message' else 'reasoning'
            body = native.get('text')  # absent text is kept explicit: `present: false`, never a final answer
            fields = {**_digest(_content(body)), 'present': True} if body is not None else {'present': False}
            if step_kind == 'message':
                fields['final'] = False
            step = self._add(step_kind, item, point=True, **{step_kind: fields})
            self.blocks[key] = step
            if step_kind == 'message':
                self.last_message = step
            return
        spec = CODEX_TOOLS.get(itype)
        if spec is None:  # unknown or unsupported item type: one gap per item, nothing of its fields is kept
            key = _key('unknown', ident if ident is not None else item['index'])
            if key in self.items:
                self.items[key].add_source(self, item)
            else:
                self.items[key] = self.gap(item, 'unsupported_event', event_type=label(f'item:{itype}', MAX_CODE))
            return
        call = self.calls.get(ident) if ident is not None else None
        if call is not None and 'outcome' in call:
            call.add_source(self, item)  # a repeated record of a call already completed: one call
            return
        if call is None:
            # Only an end observed: that end is recorded, with start and duration absent.
            call = self._add('tool_call', item, point=kind == 'item.completed', call_id=label(ident),
                             tool=self._codex_tool(itype, native), arguments=arguments(spec['arguments'](native)))
            call.arguments_observed = any(native.get(name) is not None for name in spec['observed'])
            if kind == 'item.updated' and call.materialized:
                call['started_at'] = None  # first seen in progress: its `item.started` (the start) is not observed
            if ident is not None:
                self.calls[ident] = call
        else:
            call.add_source(self, item)
            self._codex_fill(call, itype, spec, native)
        if kind == 'item.completed':
            result = {name: native[name] for name in spec['result'] if native.get(name) is not None}
            if result:
                call['result'] = {**_digest(_content(result)), 'present': True}
            status = native.get('status')
            outcome = CODEX_STATUS.get(status, 'unclassified')
            if outcome == 'unclassified':
                call['status_code'] = label(status, MAX_CODE) if status is not None else None
            call.close(self, item, outcome)

    @staticmethod
    def _codex_tool(itype, native):
        if itype == 'mcp_tool_call':  # an in-progress record may not name its server yet: origin unknown
            server = native.get('server')
            origin = 'harness_broker' if server == BROKER_SERVER else ('other_mcp' if server else None)
            return {'name': label(native.get('tool')), 'server': label(server), 'origin': origin}
        return {'name': label(itype), 'origin': 'native'}

    def _codex_fill(self, call, itype, spec, native):
        """Call fields the earlier records of the item did not carry, from the first later record that does; a field
        already observed is never replaced."""
        if itype == 'mcp_tool_call':
            tool, observed = call.get('tool') or {}, self._codex_tool(itype, native)
            if tool.get('server') is None and observed['server'] is not None:
                tool = {**tool, 'server': observed['server'], 'origin': observed['origin']}
            if tool.get('name') is None and observed['name'] is not None:
                tool = {**tool, 'name': observed['name']}
            call['tool'] = tool
        if not getattr(call, 'arguments_observed', True) and any(native.get(name) is not None
                                                                 for name in spec['observed']):
            call['arguments'] = arguments(spec['arguments'](native))
            call.arguments_observed = True

    # Output ---------------------------------------------------------------------------------------------------------

    def _end(self):
        cut = self.termination in SUPERVISOR_STOPS
        open_outcome = 'cancelled_in_flight' if cut else 'not_observed'
        for step in self.steps:
            if step['kind'] in ('tool_call', 'turn') and 'outcome' not in step:
                step['outcome'] = open_outcome  # never closed as completed; no end was observed
        self.turn = None
        if cut and self.last_item is not None:
            last_turn = next((s for s in reversed(self.steps) if s['kind'] == 'turn'), None)
            gap = self.gap(self.last_item, 'cancelled_in_flight')
            if gap.materialized:
                gap['parent_turn'] = last_turn if last_turn is not None and last_turn['outcome'] in OPEN else None
        if self.client == 'codex':
            message = self.last_message
            if message is None:
                self.final = None
            elif not message.materialized:
                self.final = 'beyond_bound'
            elif not (getattr(message, 'turn', None) is not None and getattr(message.turn, 'materialized', False)
                      and message.turn.get('outcome') == 'completed'):
                self.final = 'turn_not_completed'
            elif not message['message'].get('present'):
                self.final = 'message_text_absent'  # the last message of a completed turn carried no text
            else:
                message['message']['final'] = True  # bound to the completion of its own turn
                self.final = 'present'

    def _parallel(self):
        """Record-order intervals (end exclusive); O(n log n) per turn instead of pairwise comparisons."""
        groups = {}
        for step in self.steps:
            if step['kind'] == 'tool_call':
                groups.setdefault(id(step.get('parent_turn')), []).append(step)
        horizon = (self.last_item or {}).get('index', 0) + 1
        for calls in groups.values():
            spans = sorted(((c.opened, c.closed + 1 if c.closed is not None else horizon, c) for c in calls),
                           key=lambda span: span[0])
            reach = None
            for position, (start, end, call) in enumerate(spans):
                before = reach is not None and reach > start
                after = position + 1 < len(spans) and spans[position + 1][0] < end
                call['parallel'] = before or after
                reach = end if reach is None else max(reach, end)
            points = sorted([(s, 1) for s, _e, _c in spans] + [(e, -1) for _s, e, _c in spans])
            running = peak = 0
            for _, change in points:
                running += change
                peak = max(peak, running)
            turn = calls[0].get('parent_turn')
            if turn is not None:
                turn['max_concurrency'] = peak

    @staticmethod
    def _broker_key(call):
        tool = call.get('tool') or {}
        if tool.get('origin') != 'harness_broker':
            return None
        return tool.get('name'), (call.get('arguments') or {}).get('sha256')

    def _brokers(self):
        """Links a native harness call to its broker events only when name and argument digest single both out
        across the whole invocation: calls past the bound count too (never linked), and an ambiguous call keeps no
        link and says why (`link_absent`)."""
        native, beyond, broker = {}, Counter(), {}
        for step in self.steps:
            if step['kind'] == 'tool_call':
                key = self._broker_key(step)
                if key is not None:
                    native.setdefault(key, []).append(step)
        for call in self.omitted_calls:
            key = self._broker_key(call)
            if key is not None:
                beyond[key] += 1
        for event in self.brokers:
            broker.setdefault((label(event.get('broker')), event.get('arguments_sha256')), []).append(event)
        owned = 0
        for key in list(native) + [key for key in beyond if key not in native]:
            steps, events = native.get(key, []), broker.get(key, ())
            calls = len(steps) + beyond[key]
            if calls == 1 and len(events) == 1:
                if steps:
                    steps[0]['tool']['links'] = {k: v for k, v in events[0].items()
                                                 if k.endswith('_event_id') and v is not None}
                owned += 1  # a single call past the bound owns its broker call, unlinked like the step itself
            elif events or calls > 1:
                self.unmatched['ambiguous_broker_calls'] += calls
                for step in steps:
                    step['tool']['link_absent'] = 'ambiguous_broker_calls'
        unlinked = sum(len(events) for events in broker.values()) - owned
        if unlinked:
            self.unmatched['broker_events'] += unlinked

    def payloads(self):
        """The ordered step payloads with dense `seq` and resolved parents, before the byte bound."""
        self._end()
        self._parallel()
        self._brokers()
        if self.client is None:
            self.steps, self.omitted = [], Counter()
            reason = 'no_stream' if self.records == 0 and self.raw_client is None else 'unsupported_client'
            self.gap({'index': 0, 'sequence': None, 'at': None}, reason, client=label(self.raw_client, MAX_CODE))
        elif self.records == 0:
            self.gap({'index': 0, 'sequence': None, 'at': None}, 'no_stream')
        index = {id(step): seq for seq, step in enumerate(self.steps)}
        result = []
        for seq, step in enumerate(self.steps):
            payload = {'format': FORMAT, 'seq': seq}
            parent = step.get('parent_turn')
            payload.update((key, value) for key, value in step.items() if key != 'parent_turn')
            if 'parent_seq' not in step:
                payload['parent_seq'] = index.get(id(parent)) if parent is not None else None
            started, finished = payload.get('started_at'), payload.get('finished_at')
            payload['timing'] = 'chunk_receipt' if started or finished else 'absent'
            payload['duration_ms'] = _ms(started, finished) if started and finished else None
            payload['source_record'] = step.sources
            payload['source_record_count'] = step.count
            if step['kind'] in ('message', 'reasoning'):
                payload.setdefault('outcome', 'completed')
            if step['kind'] == 'not_observed':
                payload['outcome'] = 'not_observed'
            result.append(payload)
        return result

    def derive(self):
        """(steps, summary): at most 10,000 events and 4 MiB, ending in one `step_bound_reached` gap if cut."""
        steps = self.payloads()
        sizes = [_size(step) for step in steps]
        kept, used, cut = steps, sum(sizes), None
        if self.omitted or used > MAX_BYTES:
            kept, used = [], 0
            for step, size in zip(steps, sizes):
                if len(kept) >= MAX_STEPS - 1:
                    cut = 'steps'
                    break
                if used + size + _BOUND_RESERVE > MAX_BYTES:
                    cut = 'bytes'
                    break
                kept.append(step)
                used += size
            cut = cut or 'steps'
        bound_info = None
        if cut is not None:
            remaining = Counter(s['kind'] for s in steps[len(kept):]) + self.omitted
            remaining = dict(sorted(remaining.items()))
            total = sum(remaining.values())
            marker = {'format': FORMAT, 'seq': len(kept), 'kind': 'not_observed', 'reason': 'step_bound_reached',
                      'outcome': 'not_observed', 'bound': cut, 'remaining': remaining, 'remaining_total': total,
                      'parent_seq': None, 'timing': 'absent', 'started_at': None, 'finished_at': None,
                      'duration_ms': None, 'source_record': [], 'source_record_count': 0}
            kept.append(marker)
            used += _size(marker)
            bound_info = {'reason': cut, 'remaining': remaining, 'remaining_total': total}
        return kept, self.summary(kept, len(steps) + sum(self.omitted.values()), bound_info, used)

    def coverage(self, kept, bound_info):
        if self.client is None or self.records == 0:
            return 'absent', ['no_evidence' if self.client is not None or self.raw_client is None
                              else 'unsupported_client']
        reasons = []
        if any(s['kind'] == 'not_observed' and s['reason'] != 'step_bound_reached' for s in kept):
            reasons.append('not_observed_steps')
        if bound_info:
            reasons.append('step_bound_reached')
        if not self.terminal:
            reasons.append('no_terminal')
        if any(s['kind'] == 'turn' and s.get('outcome') in OPEN for s in kept):
            reasons.append('open_turns')
        if any(s['kind'] == 'tool_call' and s.get('outcome') in OPEN for s in kept):
            reasons.append('open_calls')
        if self.final != 'present':
            reasons.append('final_answer_absent')
        for key, reason in (('results', 'uncorrelated_results'), ('denials', 'uncorrelated_denials'),
                            ('broker_events', 'unlinked_broker_events'),
                            ('ambiguous_broker_calls', 'ambiguous_broker_calls'),
                            ('unsupported_blocks', 'unsupported_blocks'),
                            ('assistant_without_id', 'assistant_without_id'),
                            ('derivation_errors', 'derivation_errors')):
            if self.unmatched.get(key):
                reasons.append(reason)
        return ('partial' if reasons else 'complete'), reasons

    def summary(self, kept, derived, bound_info, used):
        counts = {}
        for step in kept:
            key = step['reason'] if step['kind'] == 'not_observed' else step.get('outcome')
            bucket = counts.setdefault(step['kind'], {})
            bucket[key] = bucket.get(key, 0) + 1
        absent = []
        if self.client == 'codex':
            absent += [{'signal': 'permission_denials', 'reason': 'not_reported_by_client'},
                       {'signal': 'request_turns', 'reason': 'not_separable_by_client'}]
        elif self.client == 'claude' and self.denials is None:
            absent.append({'signal': 'permission_denials', 'reason': 'no_terminal' if not self.terminal
                           else 'not_reported'})
        if self.client is not None and self.final != 'present':
            absent.append({'signal': 'final_answer', 'reason': self.final or 'not_observed'})
        coverage, reasons = self.coverage(kept, bound_info)
        concurrency = [s.get('max_concurrency', 0) for s in kept if s['kind'] == 'turn']
        return {'format': FORMAT, 'derivation': DERIVATION, 'client': label(self.raw_client, MAX_CODE),
                'unit': {'claude': 'claude_message', 'codex': 'codex_turn'}.get(self.client),
                'steps': len(kept), 'derived_steps': derived, 'counts': counts, 'coverage': coverage,
                'coverage_reasons': reasons, 'bound': bound_info, 'payload_bytes': used, 'records': self.records,
                'last_record': self.last_record, 'termination': self.termination,
                'max_concurrency': max(concurrency, default=0), 'unmatched': dict(sorted(self.unmatched.items())),
                'absent': absent, 'timing': 'chunk_receipt'}


def _size(step) -> int:
    clean = bound(step)
    return len(_canonical(clean.payload).encode('utf-8')) + sum(len(data) for _ref, data in clean.artifacts)
