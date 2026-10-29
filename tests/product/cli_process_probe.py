"""Synthetic executable for H2.3; no agent, authentication or network."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tomllib

provider, mode = sys.argv[1:3]
if '--version' in sys.argv and os.environ.get('PROBE_VERSION'):
    version = os.environ['PROBE_VERSION']
    print(f'codex-cli {version}' if provider == 'codex' else f'{version} (Claude Code)')
    sys.exit(0)
if '--version' in sys.argv:
    print(('codex-cli 0.164.0' if mode == 'version_new' else 'codex-cli 0.163.0') if provider == 'codex'
          else ('2.1.305' if mode == 'claude_new' else '2.1.304') + ' (Claude Code)')
    sys.exit(0)
if '--help' in sys.argv:
    print('synthetic help' if mode == 'incompatible_help' else
          '--json --model --sandbox --ephemeral --ignore-user-config --ignore-rules --strict-config --color --cd --config --skip-git-repo-check '
          '--print --output-format --verbose --include-partial-messages --no-session-persistence '
          '--session-id --effort --permission-mode --permission-prompts --tools --allowedTools '
          '--strict-mcp-config --mcp-config --setting-sources --settings --disable-slash-commands --no-chrome'
          + ('' if mode == 'no_read_flags' else ' --restricted --json-schema'))
    sys.exit(0)
prompt = sys.stdin.read()
record = os.environ.get('PROBE_RECORD')
if record:
    with open(record, 'a') as log:
        log.write(json.dumps({'argv': sys.argv[3:], 'cwd': os.getcwd(), 'prompt': prompt, 'provider': provider,
                              'explicit': os.environ.get('PROBE_EXPLICIT'), 'pid': os.getpid()}) + '\n')
args = sys.argv[3:]
if provider == 'codex':
    # D123/P009-T014: like the pinned exec, refuse a working directory outside any Git repository
    # unless told to skip the check. --ignore-user-config leaves no trusted project to exempt it.
    workdir = Path(args[args.index('--cd') + 1]) if '--cd' in args else Path.cwd()
    if '--skip-git-repo-check' not in args and not any(
            (folder / '.git').exists() for folder in (workdir, *workdir.parents)):
        print('Not inside a trusted directory and --skip-git-repo-check was not specified.', file=sys.stderr)
        sys.exit(1)
    # Characterize CLI configuration semantics independently of the adapter.
    # Help/version do not certify the validity of an invocation's overrides.
    overrides = [args[index + 1] for index, value in enumerate(args) if value == '-c']
    config = tomllib.loads('\n'.join(overrides))
    if os.environ.get('PROBE_MEMORY_REQUIRED') == '1' and (
            config.get('features', {}).get('memories') is not False
            or config.get('memories') != {'generate_memories': False, 'use_memories': False}
            or config.get('history', {}).get('persistence') != 'none' or '--ephemeral' not in args):
        print('Synthetic contract: automatic memory must be disabled', file=sys.stderr)
        sys.exit(1)
    reserved = {'openai', 'ollama', 'lmstudio'} & config.get('model_providers', {}).keys()
    if reserved:
        print('Synthetic config error: model_providers contains reserved built-in provider IDs: '
              + ', '.join(sorted(reserved)), file=sys.stderr)
        sys.exit(1)
    # D052: the writer is the workspace-write sandbox, never with network.
    writer = args[args.index('--sandbox') + 1] == 'workspace-write'
    if writer and os.environ.get('PROBE_TRUST_REQUIRED') == '1' and (
            config.get('projects') != {str(Path.cwd()): {'trust_level': 'untrusted'}}):
        print('Synthetic contract: writer requires explicit untrusted checkout', file=sys.stderr)
        sys.exit(1)
    if writer and config.get('sandbox_workspace_write', {}).get('network_access') is not False:
        print('Synthetic contract: writer requires explicit network_access=false', file=sys.stderr)
        sys.exit(1)
    # D059: independent transport contract, not an emulation of Codex's model
    # or OS sandbox. A writer must explicitly name its checkout and omit /tmp.
    workspace = config.get('sandbox_workspace_write', {})
    if writer and (workspace.get('writable_roots') != [str(Path.cwd())]
                   or workspace.get('exclude_slash_tmp') is not True):
        print('Synthetic contract: writer requires explicit checkout root and exclude_slash_tmp=true',
              file=sys.stderr)
        sys.exit(1)
else:
    if os.environ.get('PROBE_MEMORY_REQUIRED') == '1' and (
            json.loads(args[args.index('--settings') + 1]).get('autoMemoryEnabled') is not False
            or '--no-session-persistence' not in args
            or os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY', '1') != '1'):
        print('Synthetic contract: automatic memory must be disabled', file=sys.stderr)
        sys.exit(1)
    # Independent contract: the CLI requires a wrapper containing a server map,
    # not an empty top-level object. Reject before emitting simulated inference.
    config = json.loads(args[args.index('--mcp-config') + 1])
    if not isinstance(config, dict) or not isinstance(config.get('mcpServers'), dict):
        print('Synthetic config error: mcpServers: expected record', file=sys.stderr)
        sys.exit(1)
    # D052: a reader has a JSON schema and only the fixed read tools, confined by --restricted.
    writer = '--json-schema' not in args
    schema = {} if writer else json.loads(args[args.index('--json-schema') + 1])
    if not writer and (args[args.index('--tools') + 1] != 'Read,Glob,Grep' or '--restricted' not in args
                       or schema.get('type') != 'object'):
        print('Synthetic contract: invalid read-only reviewer invocation', file=sys.stderr)
        sys.exit(1)
    # cli-6 (D058): every required property is typed. PROBE_UNTYPED=text reproduces D057 instead:
    # without declared types the real CLI returned lists and objects as JSON text.
    typed = {key for key, value in schema.get('properties', {}).items() if isinstance(value, dict) and 'type' in value}
    if not writer and not set(schema.get('required', ())) <= typed and os.environ.get('PROBE_UNTYPED') != 'text':
        print('Synthetic contract: untyped --json-schema properties', file=sys.stderr)
        sys.exit(1)
if mode == 'web':
    # Local-config journey: synthetic edit by the writer (either provider) in its checkout cwd.
    if writer:
        path = Path('src/estimate.ts')
        path.write_text(path.read_text().replace('tasks * 45', 'tasks * 30'))
    mode = 'flow'
if mode == 'django':
    # P008-T008: same journey with the declared python-django profile.
    if writer:
        path = Path('shop/pricing.py')
        path.write_text(path.read_text().replace('tasks * 45', 'tasks * 30'))
    mode = 'flow'
def usage_events(provider):
    """H6.4: usage shape characterized in D071 with synthetic values. Claude repeats the same message in
    `assistant` events with partial output; the total of each message arrives in `message_delta`."""
    if provider == 'codex':
        command = {'id': 'item_0', 'type': 'command_execution', 'command': 'synthetic', 'aggregated_output': '',
                   'exit_code': 0, 'status': 'completed'}
        return [{'type': 'item.started', 'item': {**command, 'exit_code': None, 'status': 'in_progress'}},
                {'type': 'item.completed', 'item': command}, {'type': 'item.completed', 'item': command},
                {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'file_change', 'changes': [],
                                                    'status': 'completed'}}]
    def message(ident, model, cache_read, cache_write, content):
        usage = lambda output: {'input_tokens': 3, 'cache_read_input_tokens': cache_read,
                                'cache_creation_input_tokens': cache_write, 'output_tokens': output}
        assistant = {'type': 'assistant', 'message': {'id': ident, 'model': model, 'content': content,
                                                      'usage': usage(1)}}
        return [{'type': 'stream_event', 'event': {'type': 'message_start', 'message': {'id': ident, 'usage': usage(1)}}},
                assistant, assistant,
                {'type': 'stream_event', 'event': {'type': 'message_delta', 'usage': usage(30 if ident == 'msg_1' else 40)}}]
    tool = [{'type': 'tool_use', 'id': 'toolu_1', 'name': 'Read', 'input': {}}]
    return ([{'type': 'system', 'subtype': 'init', 'session_id': 'synthetic', 'model': 'claude-synthetic-a'}]
            + message('msg_1', 'claude-synthetic-a', 100, 400, tool)
            + message('msg_2', 'claude-synthetic-b', 200, 0, [{'type': 'text', 'text': 'synthetic'}])
            + [{'type': 'rate_limit_event', 'rate_limit_info': {'status': 'allowed', 'resetsAt': 0}},
               {'type': 'system', 'subtype': 'thinking_tokens', 'estimated_tokens': 999}])


def with_usage(provider, terminal):
    if provider == 'codex':
        if terminal['type'] != 'turn.completed':
            return terminal  # A Codex turn.failed reports no usage: it stays absent, not zero.
        return {**terminal, 'usage': {'input_tokens': 1000, 'cached_input_tokens': 600, 'cache_write_input_tokens': 0,
                                      'output_tokens': 50, 'reasoning_output_tokens': 10}}
    per_model = lambda cache_read, cache_write, output, thinking, cost: {
        'inputTokens': 3, 'outputTokens': output, 'cacheReadInputTokens': cache_read,
        'cacheCreationInputTokens': cache_write, 'thinkingTokens': thinking, 'costUSD': cost}
    return {**terminal, 'num_turns': 2, 'duration_ms': 900, 'duration_api_ms': 800, 'total_cost_usd': 0.0125,
            'permission_denials': [],
            'usage': {'input_tokens': 6, 'cache_read_input_tokens': 300, 'cache_creation_input_tokens': 400,
                      'output_tokens': 70, 'output_tokens_details': {'thinking_tokens': 12}},
            'modelUsage': {'claude-synthetic-a': per_model(100, 400, 30, 12, 0.01),
                           'claude-synthetic-b': per_model(200, 0, 40, 0, 0.0025)}}


if writer and os.environ.get('PROBE_STREAM_SECONDS'):
    until = time.monotonic() + float(os.environ['PROBE_STREAM_SECONDS'])
    number = 0
    while time.monotonic() < until:
        print(json.dumps({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
              'delta': {'type': 'text_delta', 'text': f'Synthetic progress {number}\n'}}}), flush=True)
        number += 1
        time.sleep(.02)

if mode == 'invalid':
    print('invalid JSONL', flush=True)
elif mode == 'utf8':
    os.write(1, b'{"type":"stream_event","text":"\xc3')
    sys.exit(0)
elif mode == 'partial':
    os.write(1, b'{"type":"res')
    sys.exit(0)
elif mode == 'no_terminal':
    print('{"type":"future.event","unknown":null}', flush=True)
    sys.exit(0)
elif (mode == 'hang' or mode == 'child') and os.environ.get('PROBE_USAGE') == '1' and provider == 'claude':
    # H6.4: one complete message and another started before hanging; without a terminal no total is reported.
    for event in usage_events(provider)[:6]:
        print(json.dumps(event), flush=True)
    time.sleep(60)
    sys.exit(0)
elif mode == 'slow_stream':
    # OT007: an unfinished synthetic invocation keeps journaling past the lease deadline.
    print(json.dumps({'type': 'stream_event', 'event': {'type': 'message_start', 'message': {
        'id': 'msg_synthetic', 'usage': {'input_tokens': 2, 'output_tokens': 1}}}}), flush=True)
    for number in range(3000):
        print(json.dumps({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
              'delta': {'type': 'text_delta', 'text': f'Synthetic step {number}\n'}}}), flush=True)
        time.sleep(.02)
    sys.exit(0)
elif mode == 'repetitive':
    # OT006/D251: synthetic shape of the incident (not its stream). Text deltas imitate tool markup over and
    # over, no native tool_use, no message_delta/result; only the adapter's output guard ends it.
    start = {'type': 'message_start', 'message': {'id': 'msg_synthetic', 'model': 'claude-synthetic',
             'usage': {'input_tokens': 2, 'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 5,
                       'output_tokens': 6}}}
    for event in ({'type': 'system', 'subtype': 'init', 'session_id': 'synthetic'},
                  {'type': 'stream_event', 'event': start},
                  {'type': 'stream_event', 'event': {'type': 'content_block_start', 'index': 0,
                                                     'content_block': {'type': 'text', 'text': ''}}}):
        print(json.dumps(event), flush=True)
    block = ['<invoke name="Write">', '<parameter name="file_path">app/main.go</parameter>',
             '<parameter name="content">package main</parameter>', '</invoke>', '']
    while True:
        for line in block:
            print(json.dumps({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
                             'delta': {'type': 'text_delta', 'text': line + '\n'}}}), flush=True)
        time.sleep(.001)
elif mode == 'long_text':
    # D251 false-positive case: a long but varied streamed answer completes normally.
    for number in range(int(os.environ.get('PROBE_LINES', '1500'))):
        print(json.dumps({'type': 'stream_event', 'event': {'type': 'content_block_delta', 'index': 0,
              'delta': {'type': 'text_delta', 'text': f'Step {number}: checked synthetic item {number * 7}\n}}\n'}}}))
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'usage': None, 'duration_ms': 0,
                      'result': json.dumps({'result': 'Prepared synthetic files'})}), flush=True)
    sys.exit(0)
elif mode == 'term_exit0':
    # P002-T006: the shape T002 characterized for Codex; SIGTERM ends the stream at an in-flight item with exit 0.
    signal.signal(signal.SIGTERM, lambda signum, frame: os._exit(0))
    for event in ({'type': 'thread.started', 'thread_id': 'synthetic'}, {'type': 'turn.started'},
                  {'type': 'item.started', 'item': {'id': 'item_0', 'type': 'mcp_tool_call', 'status': 'in_progress'}}):
        print(json.dumps(event), flush=True)
    time.sleep(60)
    sys.exit(0)
elif mode == 'hang' or mode == 'child':
    if mode == 'child':
        child = subprocess.Popen([sys.executable, '-c',
            'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])
        def reap(signum, frame):
            child.kill()
            child.wait()
            sys.exit(143)
        signal.signal(signal.SIGTERM, reap)
        Path(os.environ['PROBE_CHILD']).write_text(str(child.pid))
    print('{"type":"stream_event","event":{"delta":{"text":"partial"}}}', flush=True)
    time.sleep(60)
    sys.exit(0)
if mode == 'recipe':
    # T005: explicitly scripted, synthetic responses through both real CLI transports.
    # The script lives outside the child and is supplied by the test's operator config.
    script = json.loads(Path(os.environ['PROBE_SCRIPT']).read_text())
    required = set() if writer else set(json.JSONDecoder().raw_decode(prompt.rsplit('JSON Schema:\n', 1)[1])[0]['required'])
    if writer:
        role = 'executor'
        for path, content in script['edits'].items():
            target = Path(path)
            assert not target.is_absolute() and '..' not in target.parts
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
    elif 'drafts' in required:
        role = 'definition'
    elif 'executor_prompt' in required:
        role = 'planner'
    elif 'exit_criteria_results' in required:
        role = 'phase'
    else:
        role = 'reviewer'
    payload = script[role]
    if provider == 'codex':
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(payload)}},
                  {'type': 'turn.completed'}]
    else:
        events = [{'type': 'result', 'subtype': 'success', 'is_error': False,
                   'result': json.dumps(payload) if writer else '',
                   **({} if writer else {'structured_output': payload}), 'usage': None, 'duration_ms': 0}]
elif mode == 'flow' and not writer:
    selection = json.loads(os.environ.get('PROBE_SELECTION', '{"model":"synthetic-executor","effort":"medium"}'))
    if prompt.startswith('Plan exactly'):
        payload = {'task_id':'P001-T001','phase_id':'P001','title':'Synthetic task',
            'objective':'Preserve synthetic content','executor_prompt':'Return synthetic summary',
            'allowed_paths':[os.environ.get('PROBE_ALLOWED', 'app/**')],'forbidden_paths':[],
            'acceptance_criteria':['Content remains valid'],
            'validation_commands':json.loads(os.environ.get('PROBE_VALIDATION', '["test-runner check"]')),
            'executor_selection':{
                **selection,'reason':'Explicit synthetic policy'}}
    else:
        payload = {'task_id':'P001-T001','verdict':'ACCEPT','findings':[], 'blocking_questions':[], 'scope_grants':[]}
    if provider == 'codex':
        events = [{'type':'item.completed','item':{'type':'agent_message','text':json.dumps(payload)}},
                  {'type':'turn.completed'}]
    else:
        # Claude reader: --json-schema result arrives as structured_output.
        payload = {key: value if key in typed or isinstance(value, str) else json.dumps(value)
                   for key, value in payload.items()}
        events = [{'type':'system','subtype':'init','session_id':'synthetic'},
                  {'type':'result','subtype':'success','is_error':False,'result':'',
                   'structured_output':payload,'usage':None,'duration_ms':0}]
elif provider == 'codex':
    events = [ {'type':'thread.started', 'thread_id':'synthetic', 'future':None},
              {'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'result':'ñ'})}},
              {'type':'turn.failed','error':{'message':'synthetic quota'}} if mode == 'error'
              else {'type':'turn.completed','usage':{'input_tokens':0}} ]
else:
    events = [ {'type':'system','subtype':'init','session_id':'synthetic','model':None},
              {'type':'stream_event','event':{'delta':{'text':'ñ'}}},
              {'type':'future.event','opaque':{'a':None}},
              {'type':'result','subtype':'error_during_execution' if mode=='error' else 'success',
               'is_error':mode=='error', 'result': 'not structured' if mode=='bad_payload' else
                  json.dumps({'result':'ñ'}), 'usage':None,'duration_ms':0} ]
if os.environ.get('PROBE_USAGE') == '1':
    events = events[:-1] + usage_events(provider) + [with_usage(provider, events[-1])]
if mode == 'double_terminal':
    events.append(events[-1])
for event in events:
    raw = (json.dumps(event,ensure_ascii=False)+'\n').encode()
    # Force UTF-8 and JSON splits.
    for byte in raw:
        os.write(1,bytes([byte]))
        if mode == 'slow':
            time.sleep(.001)
os.write(2,b'synthetic stderr\xff\n')
sys.exit(7 if mode == 'exit_error' else 0)
