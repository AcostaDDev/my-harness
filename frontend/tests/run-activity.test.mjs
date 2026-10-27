import { test } from 'node:test';
import assert from 'node:assert/strict';
import { activity, isLive, merge, relevant } from '../src/run-activity.ts';

// Synthetic events shaped like the managed journal: process_update adds attempt_id to agent records.
let sequence = 0;
const at = '2026-10-27T10:00:00+00:00';
const event = (kind, payload = {}) => ({ sequence: ++sequence, kind, recorded_at: at, payload });
const agent = original => event('agent_event', { attempt_id: 'a1', job_id: 1, record: sequence, original });

test('a Claude attempt reads as its steps: tools update in place and end with their result', () => {
  sequence = 0;
  const events = [
    event('job_queued', { action: 'run' }), event('job_claimed'), event('attempt_started', { attempt_id: 'a1', number: 1, role: 'executor' }),
    event('process_spawned', { attempt_id: 'a1' }),
    agent({ type: 'system', subtype: 'init', model: 'claude-synthetic' }),
    agent({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'tool_use', id: 'toolu_1', name: 'Bash', input: {} } } }),
    agent({ type: 'assistant', message: { id: 'm1', content: [{ type: 'tool_use', id: 'toolu_1', name: 'Bash', input: { command: 'npm test' } }] } }),
    agent({ type: 'user', message: { content: [{ type: 'tool_result', tool_use_id: 'toolu_1', is_error: false, content: 'ok' }] } }),
    agent({ type: 'assistant', message: { id: 'm2', content: [{ type: 'tool_use', id: 'toolu_2', name: 'Edit', input: { file_path: 'src/app.ts' } }] } }),
    agent({ type: 'assistant', message: { id: 'm3', content: [{ type: 'text', text: 'Done' }] } }),
    agent({ type: 'assistant', message: { id: 'm3', content: [{ type: 'text', text: 'Done: tests pass.' }] } }),
    agent({ type: 'result', subtype: 'success', is_error: false, num_turns: 3, duration_ms: 4200, result: '{}' }),
    event('process_finished', { attempt_id: 'a1', status: 'complete', wall_duration_seconds: 4.31 }),
  ];
  const { items, now } = activity(events);
  assert.deepEqual(items.map(i => i.label), ['queued', 'claimed', 'attempt', 'process', 'session', 'command', 'edit', 'message', 'agent_done', 'process_done']);
  const command = items.find(i => i.kind === 'command');
  assert.deepEqual([command.detail, command.running, command.tone, command.role], ['npm test', false, 'ok', 'executor']);
  const edit = items.find(i => i.kind === 'edit');
  assert.deepEqual([edit.detail, edit.running, edit.tone], ['src/app.ts', true, 'active'], 'no tool_result yet: still running');
  assert.equal(items.find(i => i.kind === 'message').detail, 'Done: tests pass.', 'a repeated message grows in place');
  assert.equal(items.find(i => i.label === 'process').running, false);
  assert.deepEqual(items.at(-1).params, { status: 'complete', seconds: 4.3 });
  assert.equal(now, null);
});

test('partial deltas show what is being written now, without becoming lines', () => {
  sequence = 0;
  const events = [
    agent({ type: 'stream_event', event: { type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } } }),
    agent({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'Reading the ' } } }),
    agent({ type: 'stream_event', event: { type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: 'brief' } } }),
  ];
  const { items, now } = activity(events);
  assert.deepEqual(items, []);
  assert.deepEqual(now, { kind: 'writing', text: 'Reading the brief', role: undefined });
  const stopped = activity([...events, agent({ type: 'stream_event', event: { type: 'content_block_stop', index: 0 } })]);
  assert.equal(stopped.now, null);
});

test('a Codex attempt reads commands, file changes, reasoning and its final message', () => {
  sequence = 0;
  const command = { id: 'item_0', type: 'command_execution', command: 'bash -lc ls', aggregated_output: '', exit_code: null, status: 'in_progress' };
  const started = activity([agent({ type: 'thread.started', thread_id: 't' }), agent({ type: 'item.started', item: command })]);
  assert.equal(started.items[1].running, true);
  assert.deepEqual(started.now, { kind: 'tool', tool: 'shell', text: 'bash -lc ls', role: undefined });
  const events = [
    agent({ type: 'thread.started', thread_id: 't' }), agent({ type: 'item.started', item: command }),
    agent({ type: 'item.completed', item: { ...command, exit_code: 2, status: 'failed' } }),
    agent({ type: 'item.completed', item: { id: 'item_1', type: 'reasoning', text: '**Plan** first' } }),
    agent({ type: 'item.completed', item: { id: 'item_2', type: 'file_change', changes: [{ path: 'a.ts', kind: 'update' }, { path: 'b.ts', kind: 'add' }], status: 'completed' } }),
    agent({ type: 'item.completed', item: { id: 'item_3', type: 'agent_message', text: 'Finished' } }),
    agent({ type: 'turn.completed', usage: { input_tokens: 1 } }),
  ];
  const { items, now } = activity(events);
  assert.deepEqual(items.map(i => [i.kind, i.label, i.tone]), [
    ['lifecycle', 'thread', 'neutral'], ['command', 'command', 'danger'], ['thinking', 'thinking', 'neutral'],
    ['edit', 'files', 'ok'], ['message', 'message', 'neutral'], ['result', 'agent_done', 'ok']]);
  assert.equal(items[3].detail, 'a.ts\nb.ts');
  assert.equal(items[3].params.count, 2);
  assert.equal(now, null);
});

test('validations, warnings and long records are named; unknown events are ignored', () => {
  sequence = 0;
  const events = [
    event('command_started', { command_id: 'c1', command: { argv: ['pytest', '-q'] } }),
    event('command_finished', { command_id: 'c1', result: { exit_code: 1, duration_seconds: 2.04, timed_out: false } }),
    event('recovery_required', { reason: 'lease expired' }),
    event('agent_event', { attempt_id: 'a1', type: 'assistant', original_reference: { size: 40960 } }),
    event('some_future_kind', { x: 1 }),
  ];
  const { items } = activity(events);
  assert.deepEqual(items.map(i => i.label), ['check_failed', 'recovery', 'large_record']);
  assert.deepEqual(items[0].params, { code: '1', seconds: 2 });
  assert.equal(items[0].detail, 'pytest -q');
  assert.equal(items[2].params.size, 40);
});

test('the feed keeps the newest relevant events once each, bounded, and knows which statuses still advance', () => {
  sequence = 0;
  const bytes = event('stream_bytes', { size: 10 });
  const delta = agent({ type: 'stream_event', event: { type: 'message_delta', usage: {} } });
  const tool = agent({ type: 'assistant', message: { id: 'm', content: [{ type: 'text', text: 'hi' }] } });
  assert.deepEqual([relevant(bytes), relevant(delta), relevant(tool)], [false, false, true]);
  const merged = merge([tool], [bytes, delta, tool]);
  assert.deepEqual(merged.map(e => e.sequence), [tool.sequence]);
  const many = Array.from({ length: 30 }, (_, i) => ({ sequence: i + 100, kind: 'job_claimed', recorded_at: at, payload: {} }));
  assert.deepEqual(merge(many.slice(10), many.slice(0, 10), 5).map(e => e.sequence), [125, 126, 127, 128, 129]);
  assert.ok(isLive('EXECUTING') && isLive('ANSWERING') && isLive('QUEUED'));
  assert.ok(!isLive('COMMITTED') && !isLive('FAILED') && !isLive(undefined));
});
