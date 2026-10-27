"""Packaged CLI interface policy and local launch identity (D173).

Candidate support is conditional on the known interface contract, not an observation of
undocumented provider behavior. No network, inference, credentials or project code is used.
"""
from dataclasses import replace
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tomllib

from my_harness.i18n import tr

VERSION = 'cli-capabilities-1'
MINIMUM = {'codex': '0.163.0', 'claude': '2.1.304'}
VERSION_FORM = re.compile(r'(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})')
CAPABILITIES = ('fresh_session', 'streaming', 'selection', 'permissions', 'approvals', 'configuration',
                'trust', 'memory', 'instructions', 'response_contract', 'git_precondition', 'cancellation')
POLICY = {'version': VERSION, 'minimum': MINIMUM, 'capabilities': CAPABILITIES,
          'candidate_admission': 'automatic/known-interface/conditional',
          'references': ['D042', 'D059', 'D066', 'D068', 'D122', 'D124', 'D173', 'D174'],
          'identity_scope': 'explicit-launch-files-and-shebang'}
POLICY_SHA256 = hashlib.sha256(json.dumps(POLICY, sort_keys=True, separators=(',', ':')).encode()
    + b''.join(Path(__file__).with_name(name).read_bytes() for name in
               ('cli_compatibility.py', 'cli_agents.py', 'cli_diagnostics.py'))).hexdigest()


class CompatibilityError(ValueError):
    """A safe structured refusal, also suitable for API/CLI corrections."""

    def __init__(self, code, **params):
        self.code, self.params = code, params
        super().__init__(tr(f'cli_diagnostics.{code}', **params))


def version_tuple(value):
    if not isinstance(value, str) or not VERSION_FORM.fullmatch(value):
        return None
    return tuple(map(int, value.split('.')))


def eligible(provider, version):
    parsed = version_tuple(version)
    return provider in MINIMUM and parsed is not None and parsed >= version_tuple(MINIMUM[provider])


def discover(config):
    """Resolve only the selected command on its explicit PATH, without invoking a shell."""
    if config.executable:
        return config
    path = dict(config.environment).get('PATH', '')
    # Empty/relative PATH entries must not search the checkout or the caller's cwd.
    folders = path.split(os.pathsep)
    if not path or any(not part or not Path(part).is_absolute() for part in folders):
        raise CompatibilityError('discovery_path', provider=config.provider)
    executable = shutil.which(config.provider, path=path)
    if executable is None:
        raise CompatibilityError('client_missing', provider=config.provider)
    return replace(config, executable=(str(Path(executable).absolute()),))


@lru_cache(maxsize=128)
def _content_hash(path, signature):
    # The signature includes ctime/inode as well as mtime/size; every use restats the file.
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def launch_identity(config):
    """Bind explicit argv files and script interpreters. Transitive runtime dependencies are not certified."""
    artifacts, visited = [], set()

    def add(raw, *, interpreter=False):
        path = Path(raw)
        resolved = path.resolve(strict=True)
        if str(path) in visited:
            return
        visited.add(str(path))
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or (interpreter and not os.access(resolved, os.X_OK)):
            raise OSError()
        signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        digest = _content_hash(str(resolved), signature)
        after = resolved.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) != signature:
            raise OSError()
        artifacts.append({'path': str(path), 'resolved': str(resolved), 'sha256': digest})
        # Bound reads; never parse/execute arbitrary package configuration or shell syntax.
        with resolved.open('rb') as stream:
            first = stream.readline(4096)
        if first.startswith(b'#!'):
            parts = first[2:].decode('utf-8').strip().split()
            if not parts or len(visited) > 8:
                raise OSError()
            if parts[0] == '/usr/bin/env':
                if len(parts) != 2 or parts[1].startswith('-'):
                    raise OSError()
                path_value = dict(config.environment).get('PATH', '')
                if not path_value or any(not p or not Path(p).is_absolute() for p in path_value.split(os.pathsep)):
                    raise OSError()
                target = shutil.which(parts[1], path=path_value)
                if target is None:
                    raise OSError()
                add('/usr/bin/env', interpreter=True)
                add(target, interpreter=True)
            elif Path(parts[0]).is_absolute():
                add(parts[0], interpreter=True)
            else:
                raise OSError()

    if not config.executable:
        raise OSError()
    add(config.executable[0], interpreter=True)
    executable_name = Path(config.executable[0]).name
    if executable_name.startswith('python') or executable_name in ('node', 'nodejs', 'ruby', 'perl'):
        for arg in config.executable[1:]:
            if arg in ('-c', '-e'):
                break  # inline code is bound by the complete argv hash
            if arg == '-m':
                raise OSError()  # module resolution would import arbitrary code to identify it
            if arg.startswith('-'):
                continue
            if not Path(arg).is_absolute():
                raise OSError()
            add(arg)
            break  # later arguments can be mutable data (logs/config), not launch code
    payload = {'scope': POLICY['identity_scope'], 'argv': config.executable, 'artifacts': artifacts}
    return payload, hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def profile(provider, observed, access):
    reference = observed == MINIMUM[provider]
    return {'policy': VERSION, 'policy_sha256': POLICY_SHA256, 'access': access,
            'classification': 'reference' if reference else 'candidate',
            'provenance': 'reference-contract' if reference else 'conditional-known-interface',
            'capabilities': list(CAPABILITIES), 'internal_effects_verified': False,
            'not_verified': ['effective_tool_permissions', 'startup_persistence', 'automatic_memory_effects',
                             'transitive_executable_dependencies', 'authentication', 'inference']}


def guard_contract(provider, argv, root, access):
    """Validate the actual transport before GO, independently of help and the argv builder."""
    def option(name):
        return argv[argv.index(name) + 1]

    try:
        if any(flag in argv for flag in ('--resume', '--continue', '--dangerously-skip-permissions',
                                         '--dangerously-bypass-approvals-and-sandbox', '--yolo')):
            return False
        if provider == 'codex':
            if not {'exec', '--strict-config', '--ignore-user-config', '--ignore-rules', '--ephemeral',
                    '--json'} <= set(argv):
                return False
            config = tomllib.loads('\n'.join(argv[i + 1] for i, arg in enumerate(argv) if arg == '-c'))
            if (option('--sandbox') != ('workspace-write' if access == 'write' else 'read-only')
                    or option('--cd') != str(root) or option('--color') != 'never'
                    or config.get('approval_policy') != 'never' or config.get('model_provider') != 'openai'
                    or config.get('web_search') != 'disabled' or config.get('project_doc_max_bytes') != 0
                    or config.get('features', {}).get('memories') is not False
                    or config.get('memories') != {'generate_memories': False, 'use_memories': False}
                    or config.get('history') != {'persistence': 'none'}):
                return False
            if access == 'write':
                return (config.get('sandbox_workspace_write') == {'network_access': False,
                         'writable_roots': [str(root)], 'exclude_slash_tmp': True}
                        and config.get('projects') == {str(root): {'trust_level': 'untrusted'}}
                        and '--skip-git-repo-check' not in argv)
            return 'projects' not in config
        if (not {'--print', '--verbose', '--include-partial-messages', '--no-session-persistence',
                 '--strict-mcp-config', '--disable-slash-commands', '--no-chrome'} <= set(argv)
                or option('--output-format') != 'stream-json' or option('--permission-mode') != 'dontAsk'
                or option('--permission-prompts') != 'none' or option('--setting-sources') != ''
                or json.loads(option('--settings')) != {'disableAllHooks': True, 'autoMemoryEnabled': False}
                or json.loads(option('--mcp-config')) != {'mcpServers': {}}):
            return False
        if access == 'read':
            return ('--restricted' in argv and option('--tools') == option('--allowedTools') == 'Read,Glob,Grep'
                    and json.loads(option('--json-schema')).get('type') == 'object')
        return '--restricted' not in argv and '--json-schema' not in argv
    except (IndexError, ValueError, TypeError, AttributeError):
        return False
