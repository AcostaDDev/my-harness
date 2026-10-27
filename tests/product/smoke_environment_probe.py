"""Independent synthetic smoke CLI: no auth, secrets, agents or network."""
import json
import os
from pathlib import Path
import sys

provider, record, expected_user = sys.argv[1:4]
args = sys.argv[4:]
if '--version' in args:
    print('codex-cli 0.164.0' if provider == 'codex' else '2.1.304 (Claude Code)')
    sys.exit(0)
if '--help' in args:
    print('--json --model --sandbox --ephemeral --ignore-user-config --ignore-rules --strict-config --color --cd --config --skip-git-repo-check '
          '--print --output-format --verbose --include-partial-messages --no-session-persistence '
          '--session-id --effort --permission-mode --permission-prompts --tools --allowedTools '
          '--strict-mcp-config --mcp-config --setting-sources --settings --disable-slash-commands --no-chrome')
    sys.exit(0)
sys.stdin.read()
with Path(record).open('a') as log:
    log.write(json.dumps({'provider': provider, 'argv': args, 'environment': dict(os.environ)}) + '\n')
if provider == 'claude':
    # Requirement belongs to this executable, independently of the smoke builder.
    failed = os.environ.get('USER') != expected_user
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': failed,
                      'result': 'Synthetic USER missing' if failed else '{"result":"smoke-ok"}'}))
    sys.exit(1 if failed else 0)
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"result":"smoke-ok"}'}}))
print('{"type":"turn.completed"}')
