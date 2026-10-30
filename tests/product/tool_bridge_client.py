"""Synthetic one-shot CLI. No model/provider. Also a client-neutral JSON-RPC conformance fixture."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tomllib

client, version, mode = sys.argv[1:4]
if '--version' in sys.argv:
    print(f'codex-cli {version}' if client == 'codex' else f'{version} (Claude Code)')
    raise SystemExit(0)
if '--help' in sys.argv:
    print('--json --model --sandbox --ephemeral --ignore-user-config --ignore-rules --strict-config --color --cd '
          '--config --skip-git-repo-check --print --output-format --verbose --include-partial-messages '
          '--no-session-persistence --session-id --effort --permission-mode --permission-prompts --tools '
          '--allowedTools --strict-mcp-config --mcp-config --setting-sources --settings --disable-slash-commands '
          '--no-chrome --restricted --json-schema')
    raise SystemExit(0)
sys.stdin.read()
args = sys.argv[4:]
if client == 'codex':
    config = tomllib.loads('\n'.join(args[i + 1] for i, a in enumerate(args) if a == '-c'))
    assert config['approval_policy'] == 'never' and config['web_search'] == 'disabled'
    assert set(config['mcp_servers']) == {'harness'}
    server = config['mcp_servers']['harness']
    assert server['default_tools_approval_mode'] == 'approve'
    assert server['enabled_tools'] == ['search_tools', 'describe_tool', 'invoke_tool']
else:
    config = json.loads(args[args.index('--mcp-config') + 1])
    assert set(config['mcpServers']) == {'harness'}
    server = config['mcpServers']['harness']
    assert '--strict-mcp-config' in args
    assert args[args.index('--permission-mode') + 1] == 'dontAsk'
    if '--restricted' in args:
        assert args[args.index('--tools') + 1] == 'Read,Glob,Grep'
    assert [x for x in args[args.index('--allowedTools') + 1].split(',') if x.startswith('mcp__')] == [
        'mcp__harness__search_tools', 'mcp__harness__describe_tool', 'mcp__harness__invoke_tool']
bridge = None
if mode != 'no-bridge':
    command = [server['command'], *server['args']]
    if mode == 'startup-failure':
        # Synthetic client observes a failed stdio child, yet still emits a valid final answer below.
        command = [sys.executable, '-I', '-c', 'raise SystemExit(7)']
    relay_env = {**os.environ, **server['env']}
    for name in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'):
        if 'BRIDGE_' + name in os.environ:
            relay_env[name] = os.environ['BRIDGE_' + name]  # synthetic inheritance at the MCP launch boundary
    bridge = subprocess.Popen(command, env=relay_env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, start_new_session=True)
    Path(os.environ['BRIDGE_PID']).write_text(str(bridge.pid))
    if mode == 'startup-failure':
        assert bridge.wait(timeout=3) == 7
sequence = 0


def rpc(method, params, *, error=None):
    global sequence
    sequence += 1
    bridge.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': sequence, 'method': method, 'params': params}) + '\n')
    bridge.stdin.flush()
    response = json.loads(bridge.stdout.readline())
    assert response['id'] == sequence, response
    if error is not None:
        assert response['error']['code'] == error
        return response['error']
    return response['result']


def call(name, arguments):
    if client == 'codex':
        print(json.dumps({'type': 'item.started', 'item': {'id': str(sequence), 'type': 'mcp_tool_call',
              'server': 'harness', 'tool': name, 'arguments': arguments, 'status': 'in_progress'}}), flush=True)
    else:
        print(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': str(sequence), 'name': 'mcp__harness__' + name, 'input': arguments}]}}), flush=True)
    return json.loads(rpc('tools/call', {'name': name, 'arguments': arguments})['content'][0]['text'])


if mode == 'registered-no-init':
    rpc('ping', {}, error=-32602)  # wait for real registration without completing initialization
elif mode not in ('no-bridge', 'startup-failure'):
    rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                       'clientInfo': {'name': 'synthetic-' + client, 'version': version}})
    assert [t['name'] for t in rpc('tools/list', {})['tools']] == ['search_tools', 'describe_tool', 'invoke_tool']
    if mode != 'available-no-calls':
        found = call('search_tools', {'query': 'lookup', 'key': 'search'})
        entry = found['result']['items'][0]
        schema = call('describe_tool', {'id': entry['id'], 'version': entry['version'], 'key': 'describe'})
        assert schema['result']['schema_sha256'] == entry['schema_sha256']
        if mode == 'cancel':
            signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
        result = call('invoke_tool', {'id': entry['id'], 'version': entry['version'],
            'schema_sha256': entry['schema_sha256'], 'arguments': {'item_id': os.environ['ITEM_ID']}, 'key': 'read'})
        Path(os.environ['BRIDGE_RESULT']).write_text(json.dumps(result))
if os.environ.get('JUDGE_PROTOCOL_FAULT'):
    print('{}', flush=True)  # Invalid envelope, distinct from malformed final JSON.
if mode == 'cancel':
    time.sleep(30)
elif mode in ('auth', 'quota') or os.environ.get('JUDGE_FAILURE'):
    failure = os.environ.get('JUDGE_FAILURE', mode)
    if client == 'codex':
        print(json.dumps({'type': 'turn.failed', 'error': {'message': 'synthetic ' + failure}}), flush=True)
    else:
        print(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True,
                          'result': 'synthetic ' + failure}), flush=True)
else:
    writer = (args[args.index('--sandbox') + 1] == 'workspace-write' if client == 'codex'
              else '--json-schema' not in args)
    payload = {'result': 'Synthetic executor result.'} if writer else {
        'task_id': 'P001-T001', 'verdict': 'ACCEPT', 'findings': [], 'blocking_questions': [], 'scope_grants': []}
    if os.environ.get('JUDGE_PAYLOAD'):
        payload = json.loads(os.environ['JUDGE_PAYLOAD'])
    raw_payload = os.environ.get('JUDGE_RAW_OUTPUT', json.dumps(payload))
    if client == 'codex':
        print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': raw_payload}}))
        print(json.dumps({'type': 'turn.completed'}), flush=True)  # no usage/model telemetry fabricated
    else:
        result = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': raw_payload, 'usage': None}
        if 'JUDGE_RAW_OUTPUT' not in os.environ:
            result['structured_output'] = payload
        print(json.dumps(result), flush=True)
if bridge is not None and mode != 'orphan':
    bridge.stdin.close()
    bridge.wait(timeout=3)
