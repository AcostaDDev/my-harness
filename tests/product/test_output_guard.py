"""OT006/D251: bounded repetitive-output stop policy over synthetic streams; no agents or providers."""
import json
import sys

import pytest
from sqlalchemy.orm import Session

from my_harness.adapters.cli_agents import CLIConfig, CLIProcessAdapter, write_tools
from my_harness.adapters.processes import liveness
from my_harness.adapters.streams import AgentStream, OutputGuard
from my_harness.storage.models import ManagedProcessRow
from test_cli_agents import PROBE, setup_invocation
from test_managed import context, repository  # noqa: F401


def delta(text):
    return {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
                                              'delta': {'type': 'text_delta', 'text': text}}}


def feed(events):
    stream = AgentStream('claude', lambda kind, data: None)
    stream.feed(b''.join((json.dumps(event) + '\n').encode() for event in events))
    return stream


IMITATION = ['<invoke name="Write">', '<parameter name="file_path">app/main.go</parameter>',
             '<parameter name="content">package main</parameter>', '</invoke>']


def test_repeated_textual_tool_imitation_stops_within_one_window():
    events = [delta(line + '\n') for _ in range(OutputGuard.WINDOW) for line in IMITATION]
    stream = feed(events)
    stop = stream.stop
    assert stop['code'] == 'repetitive_output' and stop['policy'] == 'output-guard-1'
    # Triggered exactly when the window first filled, not after the whole input.
    assert stop['text_lines'] == OutputGuard.WINDOW and stop['distinct_in_window'] == len(IMITATION)
    # Text imitations are counted as markers, never as native tool calls.
    assert stop['native_tool_uses'] == 0 and stop['textual_tool_markers'] == OutputGuard.WINDOW // 4
    assert stream.metrics.summary()['tools'] == {}


def test_split_deltas_and_markers_are_counted_once():
    pieces = ['<inv', 'oke name="Write">\nsame line', ' continues\n', '<invoke', ' x>\n']
    guard = feed([delta(piece) for piece in pieces]).guard
    assert guard.textual_tool_markers == 2 and guard.lines == 3 and guard.stop is None


@pytest.mark.parametrize('shape', ['numbered', 'code', 'tool_input', 'blank_lines', 'thinking'])
def test_legitimate_long_output_is_not_stopped(shape):
    if shape == 'numbered':
        events = [delta(f'Checked synthetic item {n}\n') for n in range(5000)]
    elif shape == 'code':
        # Code repeats braces and short keywords, but far more than 5% of its lines differ.
        events = [delta(f'func handler{n}(value int) int {{\n\treturn value + {n}\n}}\n\n') for n in range(2000)]
    elif shape == 'tool_input':
        # File contents travel as native tool input JSON and never count as assistant text.
        events = [{'type': 'stream_event', 'event': {'type': 'content_block_start', 'index': 1,
                   'content_block': {'type': 'tool_use', 'id': 'toolu_synthetic', 'name': 'Write', 'input': {}}}}]
        events += [{'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 1,
                    'delta': {'type': 'input_json_delta', 'partial_json': 'same line\\n'}}}] * 5000
    elif shape == 'blank_lines':
        events = [delta('\n\n   \n')] * 5000 + [delta('Done.\n')]
    else:
        events = [{'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
                   'delta': {'type': 'thinking_delta', 'thinking': 'same thought\n'}}}] * 5000
    stream = feed(events)
    assert stream.stop is None
    if shape == 'tool_input':
        assert stream.guard.native_tool_uses == 1 and stream.guard.characters == 0


def test_unbounded_single_line_stops_at_its_limit():
    stop = feed([delta('x' * 65536)] * 5).stop
    assert stop['code'] == 'line_limit' and stop['text_characters'] == 5 * 65536


def test_codex_streams_have_no_partial_text_guard():
    stream = AgentStream('codex', lambda kind, data: None)
    assert stream.guard is None and stream.stop is None


@pytest.mark.parametrize('tools,allowed,expected', [
    ((), (), []),
    (('Read', 'Write', 'Edit'), ('Read',), []),           # Enabled but denied under dontAsk.
    (('Read',), ('Write',), []),                          # Allowed but absent from the inventory.
    (('Read', 'Write'), ('Write(app/**)',), ['Write']),   # A scoped rule still makes the tool usable.
    (('Edit', 'Write'), ('Edit', 'Write'), ['Write', 'Edit']),
])
def test_writer_tool_inventory_matches_launch_argv(tools, allowed, expected):
    config = CLIConfig('claude', (sys.executable,), '2.1.304', (), 10, tools=tools, allowed_tools=allowed)
    assert write_tools(config) == expected
    assert write_tools(CLIConfig('codex', (sys.executable,), '0.163.0', (), 10)) is None


def test_grantable_write_tool_is_not_usable_without_an_explicit_rule():
    config = CLIConfig('claude', (sys.executable,), '2.1.304', (), 10, tools=('Read', 'Write'),
                       allowed_tools=('Read',), grantable_tools=('Write(app/**)',))
    assert write_tools(config) == []


def adapter(tmp_path, mode, timeout=30):
    configs = [CLIConfig(provider, (sys.executable, PROBE, provider, mode), version, (), timeout,
                         **({'tools': ('Read', 'Write'), 'allowed_tools': ('Read', 'Write')} if provider == 'claude' else {}))
               for provider, version in (('codex', '0.163.0'), ('claude', '2.1.304'))]
    return CLIProcessAdapter(configs, tmp_path / 'captures')


def test_repetitive_cli_stream_is_stopped_with_evidence_and_unknown_final_usage(tmp_path, context, repository):
    port = adapter(tmp_path, 'repetitive')
    _, _, request = setup_invocation(repository, context, port)
    result = port.invoke(context, request)
    assert result.status == 'repetitive' and result.payload_json is None and result.error == 'CLI repetitive'
    assert not result.terminal_observed
    metadata = json.loads(result.metadata_json)
    assert metadata['group_state'] == 'dead' and metadata['output_guard']['code'] == 'repetitive_output'
    assert metadata['output_guard']['native_tool_uses'] == 0 and metadata['output_guard']['textual_tool_markers'] > 0
    # Only the message_start counters exist: reported as such, flagged as not final, never completed.
    assert metadata['final_usage_observed'] is False
    assert metadata['stream_metrics']['message_usage']['output_tokens'] == 6
    stdout = metadata['artifacts']['stdout']
    assert stdout['size'] > 0 and (tmp_path / 'captures' / request.id / 'stdout.bin').stat().st_size == stdout['size']
    with Session(repository.engine) as session:
        process = session.get(ManagedProcessRow, request.id)
        assert process.spec['output_guard'] == 'output-guard-1' and process.status == 'STOPPED'
        assert process.capture['output_guard'] == metadata['output_guard']


def test_long_varied_cli_stream_completes(tmp_path, context, repository):
    port = adapter(tmp_path, 'long_text')
    _, _, request = setup_invocation(repository, context, port)
    result = port.invoke(context, request)
    assert result.status == 'complete', result.error
    metadata = json.loads(result.metadata_json)
    assert metadata['output_guard']['code'] is None and metadata['output_guard']['text_lines'] == 3000
    assert metadata['final_usage_observed'] is True


def test_interrupted_invocation_leaves_partial_capture_beside_artifacts(tmp_path, context, repository):
    from my_harness.storage.managed import OwnershipLost
    port = adapter(tmp_path, 'repetitive')
    _, _, request = setup_invocation(repository, context, port)
    original = port.journal.process_update
    seen = []

    def update(attempt_id, kind, payload):
        if kind == 'stream_bytes' and seen:
            raise OwnershipLost('synthetic lease loss')
        seen.append(kind)
        return original(attempt_id, kind, payload)

    port.journal.process_update = update
    with pytest.raises(OwnershipLost):
        port.invoke(context, request)
    capture = json.loads((tmp_path / 'captures' / request.id / 'capture.json').read_text())
    assert capture['status'] == 'interrupted' and capture['interruption'] == 'OwnershipLost'
    assert capture['group_state'] == 'dead' and capture['final_usage_observed'] is False
    assert capture['artifacts']['stdout']['size'] > 0
    assert seen == ['process_spawned']
    # The fenced journal kept the stale RUNNING row; only an independent check can settle it.
    with Session(repository.engine) as session:
        process = session.get(ManagedProcessRow, request.id)
        assert process.status == 'RUNNING' and process.capture is None
        assert liveness(process.identity, group=True) == 'dead'
